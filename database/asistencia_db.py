"""
Acceso a datos de asistencia y horas extras (empleados, modalidades, feriados, parámetros y registros).
Usa el mismo cliente de Supabase que el resto de la app (database.conection).
"""
from database.asistencia_logica import PARAMS_DEFECTO, a_fecha
from database.conection import supabase

PAGINA = 1000          # Supabase devuelve como máximo 1000 filas por consulta: se pide por tandas


def _todo(construir):
    """construir(inicio, fin) -> consulta con .range(inicio, fin). Junta todas las tandas."""
    filas, inicio = [], 0
    while True:
        lote = construir(inicio, inicio + PAGINA - 1).execute().data or []
        filas += lote
        if len(lote) < PAGINA:
            return filas
        inicio += PAGINA


# ---------------- Empleados ----------------
def listar_empleados():
    return _todo(lambda a, b: supabase.table("empleados_planta").select("*").order("id").range(a, b))


def insertar_empleado(data: dict):
    return supabase.table("empleados_planta").insert(data).execute().data[0]


def actualizar_empleado(empleado_id, patch: dict):
    return supabase.table("empleados_planta").update(patch).eq("id", empleado_id).execute().data


# ---------------- Modalidades ----------------
def listar_modalidades():
    return supabase.table("modalidades_turno").select("*").order("nombre").execute().data


def guardar_modalidad(data: dict):
    return supabase.table("modalidades_turno").upsert(data, on_conflict="nombre").execute().data


def borrar_modalidad(nombre):
    return supabase.table("modalidades_turno").delete().eq("nombre", nombre).execute().data


# ---------------- Feriados ----------------
def listar_feriados():
    return supabase.table("feriados_planta").select("*").order("fecha").execute().data


def guardar_feriado(fecha, motivo):
    return supabase.table("feriados_planta").upsert({"fecha": str(fecha), "motivo": motivo or None}, on_conflict="fecha").execute().data


def borrar_feriado(fecha):
    return supabase.table("feriados_planta").delete().eq("fecha", str(fecha)).execute().data


# ---------------- Parámetros ----------------
def leer_parametros():
    """Los parámetros guardados, completados con los valores por defecto de los que falten."""
    filas = supabase.table("parametros_asistencia").select("*").execute().data or []
    guardados = {f["clave"]: float(f["valor"]) for f in filas}
    return {**PARAMS_DEFECTO, **{k: v for k, v in guardados.items() if k in PARAMS_DEFECTO}}


def guardar_parametros(params: dict):
    filas = [{"clave": k, "valor": float(v)} for k, v in params.items() if k in PARAMS_DEFECTO]
    return supabase.table("parametros_asistencia").upsert(filas, on_conflict="clave").execute().data


# ---------------- Registros ----------------
def listar_registros(desde, hasta):
    d, h = str(a_fecha(desde)), str(a_fecha(hasta))
    return _todo(lambda a, b: supabase.table("registros_asistencia").select("*").gte("fecha", d).lte("fecha", h)
                 .order("fecha").order("id").range(a, b))


def guardar_registros(registros: list, lote=200):
    """Crea o reemplaza (un registro por empleado y por día). Devuelve la cantidad guardada."""
    total = 0
    for i in range(0, len(registros), lote):
        parte = registros[i:i + lote]
        supabase.table("registros_asistencia").upsert(parte, on_conflict="empleado_id,fecha").execute()
        total += len(parte)
    return total


def actualizar_registro(registro_id, patch: dict):
    return supabase.table("registros_asistencia").update(patch).eq("id", registro_id).execute().data


def borrar_registros(ids: list):
    if not ids:
        return 0
    supabase.table("registros_asistencia").delete().in_("id", list(ids)).execute()
    return len(ids)


# ---------------- Importar la planilla anterior ----------------
def importar_planilla(datos: dict, area: str, reemplazar_registros=True, creado_por=None, importar_parametros=True):
    """
    Carga lo que devolvió asistencia_logica.leer_planilla(). No pisa a los empleados que ya existen
    (ni sus salarios): solo agrega los nuevos. Devuelve un resumen con cantidades.
    """
    resumen = {"empleados_nuevos": 0, "empleados_existentes": 0, "registros_nuevos": 0, "registros_reemplazados": 0,
               "registros_omitidos": 0, "modalidades": 0, "feriados": 0, "parametros": 0}
    if datos.get("parametros") and importar_parametros:
        guardar_parametros({**leer_parametros(), **datos["parametros"]})       # solo cambia lo que trae la planilla
        resumen["parametros"] = len(datos["parametros"])
    for m in datos.get("modalidades", []):
        guardar_modalidad({k: m.get(k) for k in ("nombre", "ingreso", "salida", "descanso", "tipo", "estado")})
        resumen["modalidades"] += 1
    for f in datos.get("feriados", []):
        guardar_feriado(f["fecha"], f.get("motivo"))
        resumen["feriados"] += 1

    existentes = {str(e["nombre"]).strip().casefold(): e for e in listar_empleados()}
    for e in datos.get("empleados", []):
        clave = e["nombre"].strip().casefold()
        if clave in existentes:
            resumen["empleados_existentes"] += 1
            continue
        existentes[clave] = insertar_empleado({"nombre": e["nombre"], "area": area or None, "salario_base": e.get("salario_base", 0),
                                               "adicional_fijo": e.get("adicional_fijo", 0), "activo": True})
        resumen["empleados_nuevos"] += 1

    registros = datos.get("registros", [])
    if registros:
        fechas = sorted(r["fecha"] for r in registros)
        ya = {(r["empleado_id"], r["fecha"]) for r in listar_registros(fechas[0], fechas[-1])}
        filas = []
        for r in registros:
            emp = existentes.get(r["empleado"].strip().casefold())
            if not emp:
                continue
            clave = (emp["id"], r["fecha"])
            if clave in ya:
                if not reemplazar_registros:
                    resumen["registros_omitidos"] += 1
                    continue
                resumen["registros_reemplazados"] += 1
            else:
                resumen["registros_nuevos"] += 1
            filas.append({"empleado_id": emp["id"], "fecha": r["fecha"], "semana": r.get("semana"), "modalidad": r.get("modalidad"),
                          "ingreso": r.get("ingreso"), "salida": r.get("salida"), "descanso": r.get("descanso", 0),
                          "he_diurna_adic": r.get("he_diurna_adic", 0), "he_nocturna_adic": r.get("he_nocturna_adic", 0),
                          "observaciones": r.get("observaciones"), "creado_por": creado_por})
        guardar_registros(filas)
    return resumen
