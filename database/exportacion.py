"""
Exportación a Excel pensada para Power BI.

Cada hoja es una TABLA PLANA con nombre (primera fila = títulos, sin celdas combinadas, sin totales intercalados),
con fechas, horas y números reales (no texto). Las hojas se relacionan por identificadores
(empleado_id, turno_id) y hay una hoja Calendario. La hoja Diccionario explica cada columna.

Los números salen de las mismas funciones de cálculo que usa la app (asistencia_logica y productividad_logica),
así que coinciden con lo que se ve en pantalla.
"""
import io
from datetime import date, datetime, timedelta

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

FORMATOS = {"texto": None, "entero": "0", "decimal": "0.00", "fecha": "dd/mm/yyyy", "hora": "hh:mm", "fechahora": "dd/mm/yyyy hh:mm",
            "porcentaje": "0.0", "logico": None}
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def hoy_paraguay():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Asuncion"))
    except Exception:
        return datetime.utcnow() - timedelta(hours=3)


def _num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _hora_local(valor):
    """'2026-10-30T17:03:11+00:00' (UTC, como guarda la base) -> datetime en hora de Paraguay, sin zona."""
    if valor in (None, ""):
        return None
    try:
        d = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        return d
    try:
        from zoneinfo import ZoneInfo
        return d.astimezone(ZoneInfo("America/Asuncion")).replace(tzinfo=None)
    except Exception:
        return (d.astimezone(None) - timedelta(hours=0)).replace(tzinfo=None)


def _r(v, dec=2):
    return None if v is None else round(float(v), dec)


# ----------------------------------------------------------------
# Escritura de hojas
# ----------------------------------------------------------------
def _hoja_tabla(wb, hoja, tabla, spec, filas):
    """Una hoja con una tabla de Excel con nombre. spec: [(columna, descripcion, formato)]."""
    ws = wb.create_sheet(hoja)
    columnas = [c for c, _, _ in spec]
    ws.append(columnas)
    for f in filas:
        ws.append([f.get(c) for c in columnas])
    relleno = PatternFill("solid", fgColor="1F3A5F")
    for i, (c, _, fmt) in enumerate(spec, start=1):
        celda = ws.cell(row=1, column=i)
        celda.font, celda.fill, celda.alignment = Font(bold=True, color="FFFFFF"), relleno, Alignment(horizontal="center", vertical="center")
        formato = FORMATOS.get(fmt)
        if formato:
            for fila in range(2, len(filas) + 2):
                ws.cell(row=fila, column=i).number_format = formato
        ancho = max([len(str(c))] + [len(str(f.get(c))) for f in filas[:300] if f.get(c) is not None] + [8])
        ws.column_dimensions[get_column_letter(i)].width = min(ancho + 2, 48)
    ws.freeze_panes = "A2"
    if filas:                                                    # una tabla de Excel necesita al menos una fila de datos
        t = Table(displayName=tabla, ref=f"A1:{get_column_letter(len(columnas))}{len(filas) + 1}")
        t.tableStyleInfo = TableStyleInfo(name="TableStyleLight9", showRowStripes=True)
        ws.add_table(t)
    return ws


def _calendario(desde, hasta, feriados):
    """Una fila por día entre desde y hasta. 'feriados' = {fecha: motivo}."""
    filas, d = [], desde
    while d <= hasta:
        filas.append({"fecha": d, "anio": d.year, "mes": d.month, "nombre_mes": MESES[d.month - 1], "periodo": f"{d.year}-{d.month:02d}",
                      "trimestre": (d.month - 1) // 3 + 1, "semana_iso": d.isocalendar()[1], "dia_semana_num": d.isoweekday(),
                      "dia_semana": DIAS[d.weekday()], "es_domingo": d.weekday() == 6, "es_feriado": d in feriados, "motivo_feriado": feriados.get(d)})
        d += timedelta(days=1)
    return filas


SPEC_CALENDARIO = [
    ("fecha", "Día (clave para relacionar con las demás tablas)", "fecha"), ("anio", "Año", "entero"), ("mes", "Número de mes (1 a 12)", "entero"),
    ("nombre_mes", "Nombre del mes", "texto"), ("periodo", "Año y mes (AAAA-MM), útil para ordenar y agrupar", "texto"), ("trimestre", "Trimestre (1 a 4)", "entero"),
    ("semana_iso", "Número de semana ISO", "entero"), ("dia_semana_num", "Día de la semana: 1 = lunes … 7 = domingo", "entero"),
    ("dia_semana", "Nombre del día de la semana", "texto"), ("es_domingo", "Verdadero si es domingo", "logico"),
    ("es_feriado", "Verdadero si es feriado (según los feriados cargados en la app)", "logico"), ("motivo_feriado", "Motivo del feriado", "texto")]


def _leeme(wb, titulo, usuario_nombre, rango, tablas, notas):
    ws = wb.active
    ws.title = "Leeme"
    ahora = hoy_paraguay()
    lineas = [(titulo, True), ("", False),
              (f"Generado el {ahora:%d/%m/%Y a las %H:%M} por {usuario_nombre or '—'}", False), (f"Datos: {rango}", False), ("", False),
              ("TABLAS (cada una es una hoja y una tabla de Excel con nombre)", True)]
    lineas += [(f"  · {n}: {d}", False) for n, d in tablas]
    lineas += [("", False), ("CÓMO USARLO EN POWER BI", True),
               ("  1. Power BI Desktop -> Obtener datos -> Libro de Excel -> elegí este archivo.", False),
               ("  2. Marcá las tablas (no las hojas) que quieras: aparecen con el mismo nombre de la lista de arriba. Podés dejar afuera «Leeme» y «Diccionario».", False),
               ("  3. Las tablas se relacionan por los identificadores que se indican en el Diccionario (por ejemplo empleado_id o turno_id)", False),
               ("     y por la fecha con la tabla Calendario.", False),
               ("  4. Para actualizar: volvé a descargar el archivo desde la app, guardalo con el MISMO nombre y en la MISMA carpeta,", False),
               ("     y en Power BI tocá «Actualizar».", False), ("", False), ("NOTAS", True)]
    lineas += [(f"  · {n}", False) for n in notas]
    for i, (texto, negrita) in enumerate(lineas, start=1):
        c = ws.cell(row=i, column=1, value=texto)
        if negrita:
            c.font = Font(bold=True, size=12)
    ws.column_dimensions["A"].width = 140


def _diccionario(wb, specs):
    filas = [{"tabla": t, "columna": c, "descripcion": d, "tipo": {"texto": "Texto", "entero": "Número entero", "decimal": "Número decimal", "fecha": "Fecha",
                                                                  "hora": "Hora", "fechahora": "Fecha y hora", "porcentaje": "Número (porcentaje, 0 a 100)",
                                                                  "logico": "Verdadero/Falso"}[f]}
             for t, spec in specs.items() for c, d, f in spec]
    _hoja_tabla(wb, "Diccionario", "Diccionario", [("tabla", "", "texto"), ("columna", "", "texto"), ("descripcion", "", "texto"), ("tipo", "", "texto")], filas)


def _a_bytes(wb):
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


# ----------------------------------------------------------------
# ASISTENCIA
# ----------------------------------------------------------------
ETIQUETA_PARAMETROS = {
    "dias_base": "Días base del mes (para el valor hora)", "horas_jornada_diurna": "Horas de la jornada diurna", "horas_jornada_nocturna": "Horas de la jornada nocturna",
    "factor_he_diurna": "Hora extra diurna (factor)", "factor_he_nocturna": "Hora extra nocturna (factor)", "factor_domingo_diurno": "Domingo diurno (factor)",
    "factor_domingo_nocturno": "Domingo nocturno (factor)", "factor_feriado_diurno": "Feriado diurno (factor)", "factor_feriado_nocturno": "Feriado nocturno (factor)",
    "tope_he_diarias": "Alerta: más de estas horas extra por día", "domingo_todo_el_turno": "1 = todo el turno de domingo/feriado se paga con su factor",
    "cruce_por_hora_real": "1 = los turnos que cruzan la medianoche se pagan por hora real"}


def excel_asistencia(empleados, modalidades, feriados_lista, params, registros, usuario_nombre=None, con_montos=True):
    """
    Libro de Excel con TODA la asistencia. con_montos=False deja afuera salarios, valor hora y montos (solo horas).
    registros: los registros diarios de la base (ya filtrados por el período que se quiera exportar).
    """
    from database import asistencia_logica as A
    P = A.parametros_completos(params)
    feriados_motivo = {A.a_fecha(f["fecha"]): f.get("motivo") for f in feriados_lista if A.a_fecha(f["fecha"])}
    feriados = set(feriados_motivo)
    mods = A.modalidad_por_nombre(modalidades)
    por_id = {e["id"]: e for e in empleados}
    registros = sorted((r for r in registros if A.a_fecha(r.get("fecha"))), key=lambda r: (A.a_fecha(r["fecha"]), str((por_id.get(r["empleado_id"]) or {}).get("nombre") or "").casefold()))
    fechas = [A.a_fecha(r["fecha"]) for r in registros]
    desde, hasta = (min(fechas), max(fechas)) if fechas else (None, None)
    m_cat = ["he_diurna", "he_nocturna", "domingo_diurno", "domingo_nocturno", "feriado_diurno", "feriado_nocturno"]
    nombre_h = {c: f"{c}_h" for c in m_cat}
    nombre_m = {c: f"monto_{c}" for c in m_cat}
    desc_cat = {"he_diurna": "hora extra diurna", "he_nocturna": "hora extra nocturna", "domingo_diurno": "domingo diurno", "domingo_nocturno": "domingo nocturno",
                "feriado_diurno": "feriado diurno", "feriado_nocturno": "feriado nocturno"}

    # ---- Empleados
    spec_emp = [("empleado_id", "Identificador del empleado (clave)", "entero"), ("nombre", "Nombre", "texto"), ("area", "Área", "texto"), ("activo", "Verdadero si está activo", "logico")]
    if con_montos:
        spec_emp += [("salario_base", "Salario base (Gs.)", "decimal"), ("adicional_fijo", "Adicional fijo (Gs.)", "decimal"), ("valor_hora", "Valor hora (Gs.) = (salario + adicional) / días base / horas de jornada diurna", "decimal")]
    filas_emp = []
    for e in sorted(empleados, key=lambda x: str(x.get("nombre") or "").casefold()):
        f = {"empleado_id": e["id"], "nombre": e.get("nombre"), "area": e.get("area"), "activo": e.get("activo") is not False}
        if con_montos:
            f.update(salario_base=_num(e.get("salario_base")), adicional_fijo=_num(e.get("adicional_fijo")), valor_hora=_r(A.valor_hora(e, P)))
        filas_emp.append(f)

    # ---- Registro diario
    spec_reg = [("registro_id", "Identificador del registro", "entero"), ("fecha", "Fecha del día (se relaciona con Calendario)", "fecha"), ("anio", "Año", "entero"),
                ("mes", "Mes (1 a 12)", "entero"), ("semana", "Etiqueta de semana de la planilla (texto)", "texto"), ("empleado_id", "Se relaciona con Empleados", "entero"),
                ("empleado", "Nombre del empleado", "texto"), ("area", "Área", "texto"), ("modalidad", "Modalidad de turno del día", "texto"),
                ("estado_modalidad", "Trabajo / Libre / Ausente / Vacaciones/Reposo", "texto"), ("ingreso", "Hora de ingreso", "hora"), ("salida", "Hora de salida", "hora"),
                ("descanso_h", "Horas de descanso descontadas", "decimal"), ("he_diurna_adicional_h", "Horas extra diurnas adicionales cargadas a mano", "decimal"),
                ("he_nocturna_adicional_h", "Horas extra nocturnas adicionales cargadas a mano", "decimal"), ("tipo_dia", "HABIL, DOMINGO o FERIADO (según el día en que empieza)", "texto"),
                ("cruza_medianoche", "Verdadero si el turno pasa de un día al siguiente", "logico"), ("horas_netas", "Horas trabajadas (sin descanso, con adicionales)", "decimal"),
                ("horas_ordinarias", "Horas dentro de la jornada normal", "decimal")]
    spec_reg += [(nombre_h[c], f"Horas de {desc_cat[c]}", "decimal") for c in m_cat]
    if con_montos:
        spec_reg += [(nombre_m[c], f"Gs. de {desc_cat[c]} (horas x valor hora x factor)", "decimal") for c in m_cat]
        spec_reg += [("monto_total_dia", "Gs. de horas extra y recargos del día (suma de las 6 categorías)", "decimal")]
    spec_reg += [("observaciones", "Observaciones cargadas", "texto"), ("avisos", "Avisos del cálculo (por ejemplo, más horas extra que el tope)", "texto")]
    filas_reg = []
    for r in registros:
        d = A.a_fecha(r["fecha"])
        e = por_id.get(r["empleado_id"]) or {}
        c = A.calcular_registro(r, mods, P, feriados)
        f = {"registro_id": r.get("id"), "fecha": d, "anio": d.year, "mes": d.month, "semana": r.get("semana"), "empleado_id": r["empleado_id"], "empleado": e.get("nombre"),
             "area": e.get("area"), "modalidad": r.get("modalidad"), "estado_modalidad": (mods.get(r.get("modalidad")) or {}).get("estado"),
             "ingreso": A.a_hora(r.get("ingreso")), "salida": A.a_hora(r.get("salida")), "descanso_h": _num(r.get("descanso")),
             "he_diurna_adicional_h": _num(r.get("he_diurna_adic")), "he_nocturna_adicional_h": _num(r.get("he_nocturna_adic")), "tipo_dia": c["tipo_dia"],
             "cruza_medianoche": bool(c["cruza"]), "horas_netas": c["netas"], "horas_ordinarias": c["ordinarias"],
             "observaciones": r.get("observaciones"), "avisos": " ".join(c["avisos"]) or None}
        for cat in m_cat:
            f[nombre_h[cat]] = c["horas"][cat]
        if con_montos:
            vh = A.valor_hora(e, P) if e else 0.0
            total = 0.0
            for cat in m_cat:
                monto = c["horas"][cat] * vh * P[A.FACTOR_CATEGORIA[cat]]
                f[nombre_m[cat]] = round(monto, 2)
                total += monto
            f["monto_total_dia"] = round(total, 2)
        filas_reg.append(f)

    # ---- Resumen mensual (la misma liquidación de la pantalla, mes por mes)
    spec_mes = [("periodo", "Año y mes (AAAA-MM)", "texto"), ("anio", "Año", "entero"), ("mes", "Mes (1 a 12)", "entero"), ("empleado_id", "Se relaciona con Empleados", "entero"),
                ("empleado", "Nombre del empleado", "texto"), ("area", "Área", "texto"), ("dias_trabajados", "Días con horas trabajadas", "entero"), ("ausencias", "Días Ausente", "entero"),
                ("libres", "Días Libre", "entero"), ("vacaciones", "Días de Vacaciones/Reposo", "entero"),
                ("dias_sin_registro", "Días del mes (hasta el último día con datos) sin ningún registro", "entero"), ("horas_netas", "Horas trabajadas en el mes", "decimal"),
                ("horas_ordinarias", "Horas dentro de la jornada normal", "decimal")]
    spec_mes += [(nombre_h[c], f"Horas de {desc_cat[c]}", "decimal") for c in m_cat]
    spec_mes += [("horas_extra_y_recargo", "Suma de las horas de las 6 categorías", "decimal")]
    if con_montos:
        spec_mes += [("salario", "Salario base + adicional (Gs.)", "decimal"), ("valor_hora", "Valor hora (Gs.)", "decimal")]
        spec_mes += [(nombre_m[c], f"Gs. de {desc_cat[c]} (redondeado al guaraní, como en la liquidación)", "decimal") for c in m_cat]
        spec_mes += [("total_a_pagar", "Total a pagar por horas extra y recargos (Gs.)", "decimal")]
    filas_mes = []
    if desde:
        mes_ini = date(desde.year, desde.month, 1)
        while mes_ini <= hasta:
            siguiente = date(mes_ini.year + (mes_ini.month == 12), mes_ini.month % 12 + 1, 1)
            p_ini, p_fin = max(mes_ini, desde), min(siguiente - timedelta(days=1), hasta)
            liq = A.liquidar(empleados, registros, modalidades, P, feriados, p_ini, p_fin)
            for f in liq["filas"]:
                det = liq["detalle"].get(f["empleado_id"], [])
                if f["dias_sin_registro"] >= (p_fin - p_ini).days + 1:          # sin ningún registro ese mes: no se agrega una fila vacía
                    continue
                fila = {"periodo": f"{mes_ini.year}-{mes_ini.month:02d}", "anio": mes_ini.year, "mes": mes_ini.month, "empleado_id": f["empleado_id"], "empleado": f["empleado"],
                        "area": f["area"] or None, "dias_trabajados": f["dias_trabajados"], "ausencias": f["ausencias"], "libres": f["libres"], "vacaciones": f["vacaciones"],
                        "dias_sin_registro": f["dias_sin_registro"], "horas_netas": round(sum(x["calculo"]["netas"] for x in det), 2),
                        "horas_ordinarias": round(sum(x["calculo"]["ordinarias"] for x in det), 2)}
                for c in m_cat:
                    fila[nombre_h[c]] = f[f"{c}_horas"]
                fila["horas_extra_y_recargo"] = round(sum(f[f"{c}_horas"] for c in m_cat), 2)
                if con_montos:
                    fila.update(salario=f["salario"], valor_hora=_r(f["valor_hora"]), total_a_pagar=f["total"])
                    for c in m_cat:
                        fila[nombre_m[c]] = f[f"{c}_monto"]
                filas_mes.append(fila)
            mes_ini = siguiente

    # ---- Modalidades, feriados, parámetros, calendario
    spec_mod = [("modalidad", "Nombre de la modalidad de turno", "texto"), ("tipo", "Tipo de turno", "texto"), ("ingreso", "Hora de ingreso por defecto", "hora"),
                ("salida", "Hora de salida por defecto", "hora"), ("descanso_h", "Descanso por defecto (horas)", "decimal"), ("estado", "Trabajo / Libre / Ausente / Vacaciones/Reposo", "texto")]
    filas_mod = [{"modalidad": m.get("nombre"), "tipo": m.get("tipo"), "ingreso": A.a_hora(m.get("ingreso")), "salida": A.a_hora(m.get("salida")),
                  "descanso_h": _num(m.get("descanso")), "estado": m.get("estado")} for m in modalidades]
    spec_fer = [("fecha", "Fecha del feriado (se relaciona con Calendario)", "fecha"), ("motivo", "Motivo", "texto")]
    filas_fer = [{"fecha": d, "motivo": feriados_motivo[d]} for d in sorted(feriados_motivo)]
    spec_par = [("clave", "Nombre interno del parámetro", "texto"), ("descripcion", "Qué es", "texto"), ("valor", "Valor", "decimal")]
    filas_par = [{"clave": k, "descripcion": ETIQUETA_PARAMETROS.get(k), "valor": P[k]} for k in sorted(P)]
    if not con_montos:
        filas_par = [f for f in filas_par if not f["clave"].startswith("factor_") and f["clave"] != "dias_base"]
    filas_cal = _calendario(desde, hasta, feriados_motivo) if desde else []

    specs = {"Empleados": spec_emp, "Registro_diario": spec_reg, "Resumen_mensual": spec_mes, "Modalidades": spec_mod, "Feriados": spec_fer, "Parametros": spec_par,
             "Calendario": SPEC_CALENDARIO}
    wb = openpyxl.Workbook()
    rango = f"asistencia del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y} ({len(registros)} registros diarios, {len(empleados)} empleados)" if desde else "sin registros"
    notas = ["El resumen mensual usa la misma liquidación que la pantalla: redondea al guaraní por empleado y categoría, por eso puede diferir en unos pocos guaraníes de la suma de los días.",
             "Un turno que cruza la medianoche se reparte por hora real entre los dos días si así está configurado en Parámetros (cruce_por_hora_real).",
             "Las columnas de horas están en horas decimales (7,5 = 7 horas y 30 minutos)."]
    if con_montos:
        notas.insert(0, "⚠️ Este archivo contiene SALARIOS y montos: guardalo en un lugar protegido.")
    else:
        notas.insert(0, "Este archivo NO contiene salarios ni montos: solo asistencia y horas.")
    _leeme(wb, "ASISTENCIA Y HORAS EXTRAS — datos para Power BI", usuario_nombre, rango,
           [("Empleados", "una fila por empleado"), ("Registro_diario", "una fila por empleado y por día, con todas sus horas"), ("Resumen_mensual", "una fila por empleado y mes"),
            ("Modalidades", "los tipos de turno"), ("Feriados", "los feriados cargados"), ("Parametros", "las reglas de cálculo"), ("Calendario", "una fila por día"),
            ("Diccionario", "qué significa cada columna")], notas)
    for hoja, spec, filas in (("Empleados", spec_emp, filas_emp), ("Registro_diario", spec_reg, filas_reg), ("Resumen_mensual", spec_mes, filas_mes), ("Modalidades", spec_mod, filas_mod),
                              ("Feriados", spec_fer, filas_fer), ("Parametros", spec_par, filas_par), ("Calendario", SPEC_CALENDARIO, filas_cal)):
        _hoja_tabla(wb, hoja, hoja, spec, filas)
    _diccionario(wb, specs)
    return _a_bytes(wb)


# ----------------------------------------------------------------
# PRODUCTIVIDAD
# ----------------------------------------------------------------
def excel_productividad(turnos, setups, paradas, rechazos, familias, catalogo, usuario_nombre=None):
    """Libro de Excel con TODA la productividad (turnos, setups, paradas, rechazos y catálogos)."""
    from database import productividad_logica as P
    enr = sorted(P.enriquecer(turnos, setups, paradas, rechazos), key=lambda t: t["inicio"])
    spec_tur = [("turno_id", "Identificador del registro (clave: lo usan Setups, Paradas y Rechazos)", "entero"), ("fecha", "Fecha en que EMPIEZA el turno (se relaciona con Calendario)", "fecha"),
                ("anio", "Año", "entero"), ("mes", "Mes (1 a 12)", "entero"), ("hora_inicio", "Hora de inicio", "hora"), ("hora_fin", "Hora de fin", "hora"),
                ("inicio", "Fecha y hora de inicio", "fechahora"), ("fin", "Fecha y hora de fin", "fechahora"), ("op", "Número de orden de producción", "texto"), ("item", "Item (opcional)", "texto"),
                ("operador", "Operador", "texto"), ("producto", "Producto", "texto"), ("ancho_cm", "Ancho en cm", "decimal"), ("espesor_um", "Espesor en micras", "decimal"),
                ("densidad", "Densidad usada para los metros lineales", "decimal"), ("familia", "Código de la familia (se relaciona con Familias)", "texto"),
                ("maquina", "Máquina según la familia (MONO/RFH)", "texto"), ("barrera", "Barrera / Sin Barrera", "texto"), ("color", "Color/tipo de la familia", "texto"),
                ("kg_producidos", "Kilos producidos (buenos)", "decimal"), ("scrap_refile_kg", "Scrap de refile (kg)", "decimal"), ("horas_turno", "Duración del tramo en horas", "decimal"),
                ("horas_setup", "Horas de setup", "decimal"), ("horas_parada", "Horas de parada", "decimal"), ("horas_produccion", "Horas de producción neta = turno - setup - paradas", "decimal"),
                ("kg_por_hora", "Kilos / horas de producción neta (vacío si no hubo producción)", "decimal"), ("metros_lineales", "Metros lineales = kg / (ancho m x espesor mm x densidad)", "decimal"),
                ("metros_por_hora", "Metros lineales / horas de producción neta", "decimal"), ("scrap_setup_kg", "Scrap de los setups (kg)", "decimal"), ("kg_rechazados", "Kilos rechazados (kg)", "decimal"),
                ("scrap_total_kg", "Scrap total = setup + refile + rechazados (kg)", "decimal"), ("pct_scrap", "Scrap total / (kilos producidos + scrap total) x 100", "porcentaje"),
                ("rendimiento_pct", "Kilos producidos / (kilos producidos + scrap total) x 100", "porcentaje"), ("observaciones", "Observaciones", "texto"),
                ("creado_por", "Quién lo cargó", "texto"), ("fecha_carga", "Cuándo se cargó", "fechahora"), ("modificado_por", "Quién lo modificó por última vez", "texto")]
    filas_tur, filas_set, filas_par, filas_rec = [], [], [], []
    for t in enr:
        c = t["calculo"]
        carga = _hora_local(t.get("fecha_creacion"))
        filas_tur.append({"turno_id": t["id"], "fecha": t["inicio"].date(), "anio": t["inicio"].year, "mes": t["inicio"].month, "hora_inicio": t["inicio"].time(), "hora_fin": t["fin"].time(),
                          "inicio": t["inicio"], "fin": t["fin"], "op": t.get("op"), "item": t.get("item"), "operador": t.get("operador"), "producto": t.get("producto"),
                          "ancho_cm": t.get("ancho_cm"), "espesor_um": t.get("espesor_um"), "densidad": t.get("densidad"), "familia": t.get("familia"), "maquina": t.get("maquina"),
                          "barrera": t.get("barrera"), "color": t.get("color"), "kg_producidos": _num(t.get("kg_producidos")), "scrap_refile_kg": _num(t.get("scrap_refile_kg")),
                          "horas_turno": _r(c["horas_turno"]), "horas_setup": _r(c["h_setup"]), "horas_parada": _r(c["h_parada"]), "horas_produccion": _r(c["h_prod"]),
                          "kg_por_hora": _r(c["kg_h"]), "metros_lineales": _r(c["metros"]), "metros_por_hora": _r(c["metros_h"]), "scrap_setup_kg": _r(c["scrap_setup"]),
                          "kg_rechazados": _r(c["kg_rechazados"]), "scrap_total_kg": _r(c["scrap_total"]), "pct_scrap": _r(c["pct_scrap"], 1), "rendimiento_pct": _r(c["rendimiento"], 1),
                          "observaciones": t.get("observaciones"), "creado_por": t.get("creado_por"), "fecha_carga": carga, "modificado_por": t.get("modificado_por")})
        ctx = {"turno_id": t["id"], "fecha": t["inicio"].date(), "op": t.get("op"), "operador": t.get("operador"), "familia": t.get("familia"), "maquina": t.get("maquina")}
        for s in t["setups"]:
            filas_set.append({**ctx, "setup_id": s.get("id"), "tipo_setup": s.get("tipo"), "inicio": s["inicio"], "fin": s["fin"], "horas": _r(P.horas(s["fin"] - s["inicio"])),
                              "scrap_kg": _num(s.get("scrap_kg")), "observaciones": s.get("observaciones")})
        for p in t["paradas"]:
            filas_par.append({**ctx, "parada_id": p.get("id"), "tipo_falla": p.get("tipo_falla"), "categoria": p.get("categoria"), "sistema": p.get("sistema"), "detalle": p.get("detalle"),
                              "inicio": p["inicio"], "fin": p["fin"], "horas": _r(P.horas(p["fin"] - p["inicio"]))})
        for r in t["rechazos"]:
            filas_rec.append({**ctx, "rechazo_id": r.get("id"), "kg": _num(r.get("kg")), "motivo": r.get("motivo")})
    ctx_spec = [("turno_id", "Se relaciona con Turnos", "entero"), ("fecha", "Fecha en que empieza el turno", "fecha"), ("op", "Orden de producción", "texto"), ("operador", "Operador", "texto")]
    ctx_spec_mq = ctx_spec + [("familia", "Familia", "texto"), ("maquina", "Máquina", "texto")]
    spec_set = [("setup_id", "Identificador del setup", "entero")] + ctx_spec_mq + [("tipo_setup", "Tipo de setup", "texto"), ("inicio", "Inicio", "fechahora"), ("fin", "Fin", "fechahora"),
                                                                                  ("horas", "Duración en horas", "decimal"), ("scrap_kg", "Scrap generado en el setup (kg)", "decimal"), ("observaciones", "Observaciones", "texto")]
    spec_par = [("parada_id", "Identificador de la parada", "entero")] + ctx_spec_mq + [("tipo_falla", "Causa (tipo de falla)", "texto"),
                                                                                      ("categoria", "Técnica (mantenimiento) / Preparación / No programada (externa)", "texto"), ("sistema", "Sistema afectado", "texto"),
                                                                                      ("detalle", "Detalle escrito", "texto"), ("inicio", "Inicio", "fechahora"), ("fin", "Fin", "fechahora"), ("horas", "Duración en horas", "decimal")]
    spec_rec = [("rechazo_id", "Identificador del rechazo", "entero")] + ctx_spec_mq + [("kg", "Kilos rechazados", "decimal"), ("motivo", "Motivo del rechazo", "texto")]
    spec_fam = [("codigo", "Código de la familia (clave)", "texto"), ("maquina", "Máquina", "texto"), ("barrera", "Barrera / Sin Barrera", "texto"), ("color", "Color/tipo", "texto"), ("activo", "Verdadero si está activa", "logico")]
    filas_fam = [{"codigo": f.get("codigo"), "maquina": f.get("maquina"), "barrera": f.get("barrera"), "color": f.get("color"), "activo": f.get("activo") is not False} for f in familias]
    spec_cat = [("tipo", "operador / tipo_falla / sistema_falla / tipo_setup / motivo_rechazo", "texto"), ("nombre", "Nombre del elemento", "texto"),
                ("categoria", "Categoría (solo para tipos de falla)", "texto"), ("activo", "Verdadero si se ofrece en los desplegables", "logico")]
    filas_cat = [{"tipo": i.get("tipo"), "nombre": i.get("nombre"), "categoria": i.get("categoria"), "activo": i.get("activo") is not False} for i in catalogo]
    fechas = [t["inicio"].date() for t in enr]
    desde, hasta = (min(fechas), max(fechas)) if fechas else (None, None)
    filas_cal = _calendario(desde, hasta, {}) if desde else []
    spec_cal = [c for c in SPEC_CALENDARIO if c[0] not in ("es_feriado", "motivo_feriado")]
    filas_cal = [{k: v for k, v in f.items() if k not in ("es_feriado", "motivo_feriado")} for f in filas_cal]

    specs = {"Turnos": spec_tur, "Setups": spec_set, "Paradas": spec_par, "Rechazos": spec_rec, "Familias": spec_fam, "Catalogos": spec_cat, "Calendario": spec_cal}
    wb = openpyxl.Workbook()
    rango = (f"producción del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y} ({len(enr)} registros, {len(filas_set)} setups, {len(filas_par)} paradas, {len(filas_rec)} rechazos)" if desde else "sin registros")
    _leeme(wb, "PRODUCTIVIDAD — datos para Power BI", usuario_nombre, rango,
           [("Turnos", "una fila por tramo de trabajo (operador, OP, horario) con todos sus cálculos"), ("Setups", "una fila por preparación"), ("Paradas", "una fila por parada o falla"),
            ("Rechazos", "una fila por rechazo"), ("Familias", "familias de producto"), ("Catalogos", "operadores, tipos de falla, sistemas, setups y motivos"), ("Calendario", "una fila por día"),
            ("Diccionario", "qué significa cada columna")],
           ["Las tablas Setups, Paradas y Rechazos se relacionan con Turnos por turno_id (uno a muchos).",
            "Para promedios correctos de kg/h en Power BI usá una medida: suma de kg_producidos dividida por suma de horas_produccion (no el promedio de la columna kg_por_hora).",
            "Las horas están en horas decimales (7,5 = 7 horas y 30 minutos).",
            "kg_producidos son los kilos buenos; el scrap y los rechazos se suman aparte."])
    for hoja, spec, filas in (("Turnos", spec_tur, filas_tur), ("Setups", spec_set, filas_set), ("Paradas", spec_par, filas_par), ("Rechazos", spec_rec, filas_rec),
                              ("Familias", spec_fam, filas_fam), ("Catalogos", spec_cat, filas_cat), ("Calendario", spec_cal, filas_cal)):
        _hoja_tabla(wb, hoja, hoja, spec, filas)
    _diccionario(wb, specs)
    return _a_bytes(wb)
