"""
Importar la planilla de logística (Productividad.xlsx, hoja «Producción») al CMMS.

Para cuando alguien cargó los turnos solo en el Excel y no en la app: se sube la planilla y los turnos que
todavía no están cargados se guardan, con la MISMA validación que el formulario (horas dentro del turno,
sin superposiciones). Los que ya existen (mismo operador con horario superpuesto) se saltean, así se puede
subir la planilla entera todas las veces sin duplicar nada.

Cómo se lee cada renglón:
· Renglones seguidos con el mismo día, OP, operador y horario de turno son UN turno (así sale del Excel que
  genera la app cuando un turno tuvo varias fallas o setups). Los kilos y el refile se suman.
· Setups y fallas se ubican por su HORA dentro del turno (como en el formulario). Las fechas de setup/falla
  de la planilla no se usan, porque a veces quedan mal tipeadas (ej.: «fin» al día siguiente con 3 h de setup).
· Ancho (mm) se guarda en cm (la base guarda cm). Si la planilla vieja trae «Ancho (cm)», se toma como cm.
· Una falla sin horas (0:00) no se carga como parada; si tiene horas pero no tipo, entra como «Sin tipo».
"""
import io
from datetime import datetime, time, timedelta

from database import productividad_logica as P


def _hora(v):
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.time().replace(second=0, microsecond=0)
    if isinstance(v, time):
        return v.replace(second=0, microsecond=0)
    if isinstance(v, timedelta):
        s = int(v.total_seconds()) % 86400
        return time(s // 3600, (s % 3600) // 60)
    if isinstance(v, (int, float)) and 0 <= v < 1:
        m = round(v * 24 * 60)
        return time((m // 60) % 24, m % 60)
    return P.a_hora(v)


def _horas(v):
    """Duración de la planilla (12:00, 0,5 día, timedelta…) -> horas."""
    if v is None or v == "":
        return 0.0
    if isinstance(v, timedelta):
        return v.total_seconds() / 3600
    if isinstance(v, time):
        return v.hour + v.minute / 60
    if isinstance(v, datetime):
        return v.hour + v.minute / 60
    if isinstance(v, (int, float)):
        return v * 24 if v < 2 else float(v)
    return 0.0


def _num(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _txt(v):
    if v is None:
        return None
    s = str(v).strip()
    if isinstance(v, float) and v.is_integer():
        s = str(int(v))
    return s or None


def leer(contenido: bytes):
    """Devuelve la lista de renglones (dict por encabezado) de la hoja «Producción». ValueError si no es la planilla."""
    import openpyxl
    try:
        libro = openpyxl.load_workbook(io.BytesIO(contenido), data_only=True, read_only=True)
    except Exception as e:
        raise ValueError(f"No se pudo abrir el archivo como Excel (.xlsx): {type(e).__name__}.")
    hoja = next((h for h in libro.worksheets if h.title.strip().lower() in ("producción", "produccion")), None)
    if hoja is None:
        raise ValueError("El archivo no tiene la hoja «Producción» (la de la planilla de productividad).")
    filas = hoja.iter_rows(values_only=True)
    encabezado = [str(c).strip() if c is not None else "" for c in (next(filas, None) or [])]
    faltan = [c for c in ("Día", "No. OP", "Operador", "Hora Inicio de Turno", "Hora fin de Turno") if c not in encabezado]
    if faltan:
        raise ValueError("A la hoja «Producción» le faltan columnas: " + ", ".join(faltan) + ".")
    salida = []
    for n, r in enumerate(filas, 2):
        d = {c: (r[i] if i < len(r) else None) for i, c in enumerate(encabezado) if c}
        if d.get("Día") is None and d.get("Operador") is None:
            continue
        salida.append({"_renglon": n, **d})
    libro.close()
    return salida


def armar_turnos(renglones):
    """Agrupa los renglones en turnos (con sus setups, paradas y rechazos). Devuelve (turnos, errores_por_renglon)."""
    turnos, errores = [], []
    actual, clave_actual = None, None
    for d in renglones:
        dia = P.a_fecha(d.get("Día"))
        h_ini, h_fin = _hora(d.get("Hora Inicio de Turno")), _hora(d.get("Hora fin de Turno"))
        operador, op = _txt(d.get("Operador")), _txt(d.get("No. OP"))
        if not dia and not op and _num(d.get("Kilos Producidos")) is None:
            continue                                   # renglón vacío o preparado de antemano (solo con el operador)
        if not dia or not h_ini or not h_fin or not operador or not op:
            falta = [n for n, v in (("Día", dia), ("Hora de inicio del turno", h_ini), ("Hora de fin del turno", h_fin), ("Operador", operador), ("No. OP", op)) if not v]
            errores.append({"renglon": d["_renglon"], "motivo": "Falta: " + ", ".join(falta)})
            continue
        hoy = P.hoy_paraguay()
        if dia > hoy + timedelta(days=1) or dia < hoy - timedelta(days=400):
            errores.append({"renglon": d["_renglon"], "motivo": f"La fecha {dia:%d/%m/%Y} parece mal escrita (revisá el año)."})
            continue
        clave = (dia, op, operador.casefold(), h_ini, h_fin)
        if clave != clave_actual:
            ancho_mm = _num(d.get("Ancho (mm)"))
            ancho_cm = (ancho_mm / 10) if ancho_mm else _num(d.get("Ancho (cm)"))
            actual = {"renglones": [], "setups": [], "paradas": [], "rechazos": [],
                      "turno": {"fecha": dia, "hora_inicio": h_ini, "hora_fin": h_fin, "op": op, "operador": operador,
                                "item": _txt(d.get("Item")) or "", "producto": _txt(d.get("Producto")) or "",
                                "ancho_cm": ancho_cm, "espesor_um": _num(d.get("Espesor Mic (mm)")) or _num(d.get("Espesor Mic")),
                                "densidad": _num(d.get("Densidad (kg/m3)")) or P.DENSIDAD_DEFECTO,
                                "familia": _txt(d.get("Familia del Producto")), "maquina": _txt(d.get("Maquina")),
                                "barrera": _txt(d.get("Tipo de Producto")), "color": _txt(d.get("Color del Producto")),
                                "kg_producidos": 0.0, "scrap_refile_kg": 0.0, "horas_planificadas": None,
                                "observaciones": "Importado de la planilla"}}
            turnos.append(actual)
            clave_actual = clave
        t = actual["turno"]
        actual["renglones"].append(d["_renglon"])
        t["kg_producidos"] += _num(d.get("Kilos Producidos")) or 0
        t["scrap_refile_kg"] += _num(d.get("Scrap por Refile (kg)")) or 0
        if t["horas_planificadas"] is None and _horas(d.get("Total Horas Planificadas")) > 0:
            t["horas_planificadas"] = round(_horas(d.get("Total Horas Planificadas")), 4)
        s_ini, s_fin = _hora(d.get("Hora Inicio de Setup")), _hora(d.get("Hora fin de Setup"))
        if s_ini and s_fin and s_ini != s_fin:
            actual["setups"].append({"tipo": _txt(d.get("Tipo de Setup")) or "Sin tipo", "hora_inicio": s_ini, "hora_fin": s_fin,
                                     "scrap_kg": _num(d.get("Scrap de Setup (kg)")) or 0, "observaciones": ""})
        elif _num(d.get("Scrap de Setup (kg)")):
            actual.setdefault("avisos", []).append(f"Renglón {d['_renglon']}: tiene scrap de setup pero el setup no tiene horario; el scrap se suma al refile.")
            t["scrap_refile_kg"] += _num(d.get("Scrap de Setup (kg)"))
        f_ini, f_fin = _hora(d.get("Hora Inicio de Fallas")), _hora(d.get("Hora fin de Fallas"))
        if f_ini and f_fin and f_ini != f_fin and _horas(d.get("Total de Horas de Fallas")) > 0:
            actual["paradas"].append({"tipo_falla": _txt(d.get("Tipo de Fallas")) or "Sin tipo", "sistema": _txt(d.get("Sistema de Fallas")) or "",
                                      "hora_inicio": f_ini, "hora_fin": f_fin, "detalle": ""})
        if _num(d.get("Kilos Rechazados")) or _txt(d.get("Motivo de Rechazo")):
            actual["rechazos"].append({"kg": _num(d.get("Kilos Rechazados")) or 0, "motivo": _txt(d.get("Motivo de Rechazo"))})
    return turnos, errores


def analizar(contenido, existentes, categorias_falla=None):
    """
    existentes: turnos ya guardados (al menos los de las fechas de la planilla).
    Devuelve {"nuevos": [...], "repetidos": [...], "errores": [...], "avisos": [...]}. Cada nuevo trae turno, evaluacion y rechazos.
    """
    renglones = leer(contenido)
    grupos, errores = armar_turnos(renglones)
    nuevos, repetidos, avisos = [], [], []
    ya = list(existentes)
    for g in grupos:
        t = g["turno"]
        donde = "Renglón " + "-".join(str(x) for x in (g["renglones"][0], g["renglones"][-1]) if x) if len(g["renglones"]) > 1 else f"Renglón {g['renglones'][0]}"
        pisa = P.solapa_con(t, ya)
        if pisa:
            otro = next((x for x in pisa if str(x.get("id", "")).startswith("nuevo-")), None)
            if otro:
                errores.append({"renglon": donde, "motivo": f"{t['operador']} figura dos veces con horarios superpuestos en la planilla "
                                                             f"(ya está en {otro['donde']}). Se carga solo el primero."})
            else:
                repetidos.append({"donde": donde, "turno": t})
            continue
        ev = P.evaluar_formulario(t, g["setups"], g["paradas"], g["rechazos"], categorias_falla)
        if ev["errores"]:
            errores.append({"renglon": donde, "motivo": " ".join(ev["errores"])})
            continue
        avisos += g.get("avisos", [])
        nuevos.append({"donde": donde, "turno": t, "evaluacion": ev, "rechazos": g["rechazos"]})
        # el siguiente renglón no puede pisar a este (dos veces el mismo turno dentro de la planilla)
        ya.append({"id": f"nuevo-{len(nuevos)}", "donde": donde, "fecha": t["fecha"].isoformat(), "operador": t["operador"],
                   "hora_inicio": t["hora_inicio"].strftime("%H:%M:%S"), "hora_fin": t["hora_fin"].strftime("%H:%M:%S")})
    fechas = [g["turno"]["fecha"] for g in grupos]
    return {"nuevos": nuevos, "repetidos": repetidos, "errores": errores, "avisos": avisos,
            "desde": min(fechas) if fechas else None, "hasta": max(fechas) if fechas else None, "renglones": len(renglones)}


def rango_fechas(contenido):
    """Primera y última fecha de la planilla (para traer solo esos turnos de la base)."""
    fechas = [P.a_fecha(d.get("Día")) for d in leer(contenido)]
    fechas = [f for f in fechas if f]
    return (min(fechas), max(fechas)) if fechas else (None, None)
