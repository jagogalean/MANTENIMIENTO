"""
Excel de las rondas del operador (estándar de marca + Power BI). Lo genera el coordinador cuando quiere, desde
«Rutinas del Operador» → Cumplimiento: el Excel de un período, con la tabla «Cumplimiento» (¿se hizo o no?, control por control).
(excel_ronda, el Excel de una sola ronda, queda disponible pero ya no se ofrece al operador al terminar.)
Todas las filas salen de los mismos datos que se guardan en rut_ejecuciones / rut_respuestas.
"""


from database import excel_marca as M
from database import rutinas_logica as R

ETQ_RESULTADO = {"OK": "OK", "NO_OK": "No OK", "NA": "No aplica"}

SPEC_RONDAS = [
    ("ronda_id", "Identificador de la ronda (clave)", "texto"), ("fecha", "Día de la ronda", "fecha"), ("hora_envio", "Fecha y hora en que se envió", "fechahora"),
    ("zona", "Zona de la planta", "texto"), ("operador", "Quién hizo la ronda", "texto"), ("controles", "Controles hechos en la ronda", "entero"),
    ("controles_ok", "Controles con resultado OK", "entero"), ("controles_no_ok", "Controles con problema (No OK)", "entero"),
    ("controles_na", "Controles que no aplicaban", "entero"), ("fallas_creadas", "Reportes de falla creados automáticamente", "entero"),
    ("resultado_ronda", "«Con problemas» si hubo algún No OK, si no «Sin problemas»", "texto")]
SPEC_CONTROLES = [
    ("ronda_id", "Ronda a la que pertenece (clave hacia Rondas)", "texto"), ("fecha", "Día de la ronda", "fecha"), ("zona", "Zona", "texto"), ("operador", "Operador", "texto"),
    ("item_id", "Identificador de la rutina (clave)", "entero"), ("codigo", "Código de la rutina", "texto"), ("control", "Nombre del control", "texto"),
    ("resultado", "OK, No OK o No aplica", "texto"), ("es_problema", "Verdadero si hubo un problema", "logico"), ("que_paso", "Qué se detectó (puntos con problema y su valor)", "texto"),
    ("comentario", "Lo que escribió el operador", "texto"), ("reporte_falla_id", "Número del reporte de falla creado (si hubo)", "entero"),
    ("tiene_foto", "Verdadero si adjuntó foto", "logico"), ("foto_ruta", "Ubicación de la foto en el almacenamiento (solo administradores la pueden abrir)", "texto")]
SPEC_LECTURAS = [
    ("ronda_id", "Ronda (clave hacia Rondas)", "texto"), ("fecha", "Día de la ronda", "fecha"), ("zona", "Zona", "texto"), ("operador", "Operador", "texto"),
    ("item_id", "Identificador de la rutina (clave)", "entero"), ("codigo", "Código de la rutina", "texto"), ("control", "Nombre del control", "texto"),
    ("punto", "Punto de control (lo que se miró o midió)", "texto"), ("tipo", "numero = valor medido; si no, OK/No OK", "texto"), ("unidad", "Unidad de la medida", "texto"),
    ("valor", "Valor medido", "decimal"), ("resultado", "OK, No OK o No aplica", "texto"), ("fuera_de_rango", "Verdadero si el valor se pasó del rango", "logico"),
    ("rango", "Rango permitido", "texto")]

SPEC_CUMPLIMIENTO = [
    ("fecha", "Día que tocaba (diaria) o domingo de la semana (semanal)", "fecha"), ("semana", "Lunes de la semana", "fecha"),
    ("zona", "Zona de la planta", "texto"), ("item_id", "Identificador de la rutina (clave)", "entero"), ("codigo", "Código de la rutina", "texto"),
    ("control", "Nombre del control", "texto"), ("frecuencia", "Diaria o Semanal", "texto"),
    ("se_hizo", "«Sí» si se hizo en su día/semana, «No» si quedó sin hacer", "texto"), ("hecho", "Verdadero si se hizo (1 = hecho, para sumar en Power BI)", "logico"),
    ("operador", "Quién lo hizo (vacío si no se hizo)", "texto"), ("resultado", "OK, No OK o No aplica (vacío si no se hizo)", "texto")]

TABLA_CUMPLIMIENTO = ("Cumplimiento", "Cumplimiento", "Una fila por cada control que TOCABA en el período: si se hizo o no, quién y con qué resultado.")

TABLAS = [("Rondas", "Rondas", "Una fila por ronda enviada: quién, dónde, cuándo y cuántos controles."),
          ("Controles", "Controles", "Una fila por control respondido (con su resultado, comentario, falla y foto)."),
          ("Lecturas", "Lecturas", "Una fila por punto de control (valores medidos con su rango, y OK/No OK de cada punto).")]


def _fecha(v):
    return R.a_fecha(v) if v else None


def _num(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _que_paso(detalle):
    partes = []
    for x in detalle or []:
        if x.get("resultado") == "NO_OK" or x.get("fuera_rango"):
            partes.append(f"{x.get('texto')}" + (f": {R.fmt_num(x['valor'])}{(' ' + x['unidad']) if x.get('unidad') else ''}" if x.get("valor") is not None else ""))
    return "; ".join(partes) or None


def tablas_desde_filas(ejec, filas):
    """
    ejec: [{id, fecha, zona_nombre, operador_nombre, creado_en}].  filas: respuestas con ejecucion_id, fecha, zona, operador,
    item_id, item_codigo, item_titulo, resultado, detalle, comentario, falla_id, foto_ruta.
    """
    por_ronda = {}
    for r in filas:
        por_ronda.setdefault(r["ejecucion_id"], []).append(r)
    rondas = []
    for e in ejec:
        rs = por_ronda.get(e["id"], [])
        no_ok = sum(1 for r in rs if r["resultado"] == "NO_OK")
        rondas.append({"ronda_id": str(e["id"]), "fecha": _fecha(e["fecha"]), "hora_envio": M.hora_local(e.get("creado_en")), "zona": e.get("zona_nombre"),
                       "operador": e.get("operador_nombre"), "controles": len(rs), "controles_ok": sum(1 for r in rs if r["resultado"] == "OK"), "controles_no_ok": no_ok,
                       "controles_na": sum(1 for r in rs if r["resultado"] == "NA"), "fallas_creadas": sum(1 for r in rs if r.get("falla_id")),
                       "resultado_ronda": "Con problemas" if no_ok else "Sin problemas"})
    controles = [{"ronda_id": str(r["ejecucion_id"]), "fecha": _fecha(r["fecha"]), "zona": r.get("zona"), "operador": r.get("operador"), "item_id": r.get("item_id"),
                  "codigo": r.get("item_codigo"), "control": r.get("item_titulo"), "resultado": ETQ_RESULTADO.get(r["resultado"], r["resultado"]),
                  "es_problema": r["resultado"] == "NO_OK", "que_paso": _que_paso(r.get("detalle")), "comentario": r.get("comentario"),
                  "reporte_falla_id": r.get("falla_id"), "tiene_foto": bool(r.get("foto_ruta")), "foto_ruta": r.get("foto_ruta")} for r in filas]
    lecturas = [{"ronda_id": str(r["ejecucion_id"]), "fecha": _fecha(r["fecha"]), "zona": r.get("zona"), "operador": r.get("operador"), "item_id": r.get("item_id"),
                 "codigo": r.get("item_codigo"), "control": r.get("item_titulo"), "punto": x.get("texto"), "tipo": x.get("tipo"), "unidad": x.get("unidad"),
                 "valor": _num(x.get("valor")), "resultado": ETQ_RESULTADO.get(x.get("resultado"), x.get("resultado")), "fuera_de_rango": bool(x.get("fuera_rango")),
                 "rango": x.get("rango")} for r in filas for x in (r.get("detalle") or [])]
    return {"Rondas": rondas, "Controles": controles, "Lecturas": lecturas}


def _libro(titulo, usuario, rango, datos, desde, hasta, notas):
    specs = {"Rondas": SPEC_RONDAS, "Controles": SPEC_CONTROLES, "Lecturas": SPEC_LECTURAS, "Cumplimiento": SPEC_CUMPLIMIENTO}
    tablas = ([TABLA_CUMPLIMIENTO] if "Cumplimiento" in datos else []) + TABLAS
    return M.libro(titulo, usuario, rango, tablas, specs, datos, notas=notas, con_calendario=(desde, hasta))


def tabla_cumplimiento(detalle):
    """detalle: salida de rutinas_logica.detalle_cumplimiento()."""
    return [{"fecha": f["fecha"], "semana": f["semana"], "zona": f["zona"], "item_id": f["item_id"], "codigo": f["codigo"], "control": f["control"],
             "frecuencia": f["frecuencia"], "se_hizo": "Sí" if f["hecho"] else "No", "hecho": f["hecho"], "operador": f["operador"],
             "resultado": ETQ_RESULTADO.get(f["resultado"], f["resultado"])} for f in detalle]


NOTAS = ["«Cumplimiento» responde «¿se hizo o no?»: % cumplimiento = filas con hecho = Verdadero ÷ total de filas.",
         "Las fotos no van dentro del Excel: «foto_ruta» indica dónde está cada una (se ve en la app, en Rutinas del Operador → Cumplimiento).",
         "«Lecturas» tiene una fila por cada punto de control; los valores medidos están en «valor» con su «rango» y «fuera_de_rango».",
         "Clave entre tablas: ronda_id (Rondas → Controles → Lecturas)."]


def excel_periodo(ejec, filas, desde, hasta, usuario=None, detalle=None):
    """Todas las rondas entre dos fechas (administrador). Con «detalle» agrega la tabla Cumplimiento (lo hecho y lo que faltó)."""
    datos = tablas_desde_filas(ejec, filas)
    if detalle is not None:
        datos["Cumplimiento"] = tabla_cumplimiento(detalle)
    return _libro("RONDAS DEL OPERADOR — datos para Power BI", usuario, f"rondas del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}",
                  datos, desde, hasta, NOTAS)


def excel_ronda(zona_nombre, operador, ronda_uuid, fecha, hora, payload, items_por_id, fallas=None):
    """
    El Excel de UNA ronda recién enviada, armado con lo que el operador respondió.
    payload: lo enviado a la base (R.armar_respuesta). fallas: [{item_id, falla_id}] que devolvió la base.
    """
    falla_de = {f.get("item_id"): f.get("falla_id") for f in (fallas or [])}
    ejec = [{"id": ronda_uuid, "fecha": fecha, "zona_nombre": zona_nombre, "operador_nombre": operador, "creado_en": hora}]
    filas = [{**p, "ejecucion_id": ronda_uuid, "fecha": fecha, "zona": zona_nombre, "operador": operador,
              "item_codigo": (items_por_id.get(p["item_id"]) or {}).get("codigo"), "falla_id": falla_de.get(p["item_id"])} for p in payload]
    d = tablas_desde_filas(ejec, filas)
    titulo = f"RONDA DE CONTROL — {zona_nombre} — {fecha:%d/%m/%Y}"
    return _libro(titulo, operador, f"ronda de {operador} en «{zona_nombre}» del {fecha:%d/%m/%Y}", d, fecha, fecha, NOTAS)
