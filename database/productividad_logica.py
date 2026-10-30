"""
Lógica del módulo Productividad (sin Streamlit ni base de datos: se puede probar sola).

Un registro es un TRAMO DE TRABAJO: un operador, en una OP, durante un horario. Dentro del tramo puede haber
varias preparaciones (setups), varias paradas y varios rechazos.

Regla de horas (reemplaza la verificación del Excel):
    horas de producción neta = horas del turno - horas de setup - horas de parada
Los setups y las paradas no pueden superponerse entre sí ni salirse del horario del turno, así que las horas
siempre cuadran.
"""
import collections
from datetime import date, datetime, time, timedelta

DENSIDAD_DEFECTO = 0.92
CATEGORIAS_PARADA = ["Técnica (mantenimiento)", "Preparación", "No programada (externa)"]
TIPOS_CATALOGO = {
    "operador": "Operadores",
    "tipo_falla": "Tipos de falla",
    "sistema_falla": "Sistemas de falla",
    "tipo_setup": "Tipos de setup",
    "motivo_rechazo": "Motivos de rechazo",
}
ROLES_CARGA = ("admin", "logistica")
ROLES_VISTA = ("admin", "gerente", "logistica")


# ----------------------------------------------------------------
# Permisos
# ----------------------------------------------------------------
def puede_ver(usuario):
    return (usuario or {}).get("rol") in ROLES_VISTA


def puede_cargar(usuario):
    return (usuario or {}).get("rol") in ROLES_CARGA


def puede_administrar(usuario):
    return (usuario or {}).get("rol") == "admin"


def puede_borrar(usuario, registro):
    """Borra el administrador, o quien cargó el registro."""
    if puede_administrar(usuario):
        return True
    return puede_cargar(usuario) and bool(registro.get("creado_por")) and registro.get("creado_por") == (usuario or {}).get("nombre")


# ----------------------------------------------------------------
# Conversión de fechas y horas
# ----------------------------------------------------------------
def a_fecha(v):
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def a_hora(v):
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v.time().replace(microsecond=0)
    if isinstance(v, time):
        return v.replace(microsecond=0)
    texto = str(v).strip()
    for formato in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(texto[:8] if formato == "%H:%M:%S" else texto[:5], formato).time()
        except ValueError:
            continue
    return None


def a_datetime(v):
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v.replace(tzinfo=None)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "")[:19]).replace(tzinfo=None)
    except ValueError:
        return None


def _num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def hoy_paraguay():
    """Fecha de hoy en Paraguay (el servidor está en hora UTC: pasadas las 21:00 ya sería 'mañana')."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Asuncion")).date()
    except Exception:
        return (datetime.utcnow() - timedelta(hours=3)).date()


def horas(delta):
    return round(delta.total_seconds() / 3600, 4)


# ----------------------------------------------------------------
# Horarios del turno
# ----------------------------------------------------------------
def limites_turno(fecha, h_ini, h_fin):
    """(inicio, fin) del turno. Si la hora de fin es menor o igual a la de inicio, termina al día siguiente."""
    inicio = datetime.combine(fecha, h_ini)
    fin = datetime.combine(fecha, h_fin)
    if fin <= inicio:
        fin += timedelta(days=1)
    return inicio, fin


def resolver_tramo(fecha, h_turno_ini, h_turno_fin, h_ini, h_fin):
    """
    Ubica en el calendario un setup o parada que se carga solo con horas. Una hora anterior al inicio del
    turno se considera del día siguiente (turno de noche que cruza la medianoche).
    """
    inicio_turno, _ = limites_turno(fecha, h_turno_ini, h_turno_fin)
    ini = datetime.combine(fecha, h_ini)
    if ini < inicio_turno:
        ini += timedelta(days=1)
    fin = datetime.combine(ini.date(), h_fin)
    if fin <= ini:
        fin += timedelta(days=1)
    return ini, fin


def metros_lineales(kg, ancho_cm, espesor_um, densidad=DENSIDAD_DEFECTO):
    """Metros lineales = kg / (ancho en m × espesor en mm × densidad). Misma fórmula del Excel."""
    ancho, espesor, dens = _num(ancho_cm), _num(espesor_um), _num(densidad) or DENSIDAD_DEFECTO
    if _num(kg) <= 0 or ancho <= 0 or espesor <= 0:
        return 0.0
    return _num(kg) / ((ancho / 100.0) * (espesor / 1000.0) * dens)


# ----------------------------------------------------------------
# Cálculo de un tramo
# ----------------------------------------------------------------
def calcular(inicio, fin, setups, paradas, rechazos, kg, scrap_refile, ancho_cm, espesor_um, densidad):
    """
    setups / paradas: listas de dicts con 'inicio' y 'fin' (datetime); setups con 'scrap_kg'; paradas con 'categoria'.
    rechazos: lista de dicts con 'kg'. Devuelve todos los números del tramo.
    """
    h_turno = horas(fin - inicio)
    h_setup = round(sum(horas(s["fin"] - s["inicio"]) for s in setups), 4)
    h_parada = round(sum(horas(p["fin"] - p["inicio"]) for p in paradas), 4)
    h_prod = round(h_turno - h_setup - h_parada, 4)
    por_cat = collections.defaultdict(float)
    for p in paradas:
        por_cat[p.get("categoria") or "Sin categoría"] += horas(p["fin"] - p["inicio"])
    scrap_setup = sum(_num(s.get("scrap_kg")) for s in setups)
    kg_rech = sum(_num(r.get("kg")) for r in rechazos)
    kg = _num(kg)
    scrap_total = scrap_setup + _num(scrap_refile) + kg_rech
    procesado = kg + scrap_total
    metros = metros_lineales(kg, ancho_cm, espesor_um, densidad)
    return {
        "horas_turno": h_turno, "h_setup": h_setup, "h_parada": h_parada, "h_prod": h_prod,
        "h_parada_cat": {k: round(v, 4) for k, v in por_cat.items()},
        "kg": kg, "kg_h": (kg / h_prod) if h_prod > 0 else None,
        "metros": metros, "metros_h": (metros / h_prod) if h_prod > 0 and metros else None,
        "scrap_setup": scrap_setup, "scrap_refile": _num(scrap_refile), "kg_rechazados": kg_rech,
        "scrap_total": scrap_total, "pct_scrap": (scrap_total / procesado * 100) if procesado > 0 else None,
        "rendimiento": (kg / procesado * 100) if procesado > 0 else None,
        "pct_prod": (h_prod / h_turno * 100) if h_turno > 0 else None,
        "pct_setup": (h_setup / h_turno * 100) if h_turno > 0 else None,
        "pct_parada": (h_parada / h_turno * 100) if h_turno > 0 else None,
    }


def evaluar_formulario(turno, setups, paradas, rechazos, categorias_falla=None):
    """
    Valida lo que se carga en pantalla (los setups y paradas vienen solo con horas) y calcula los números.
    Devuelve {errores, avisos, setups, paradas, calculo}: 'setups' y 'paradas' ya con fecha y hora completas.
    """
    categorias_falla = categorias_falla or {}
    errores, avisos = [], []
    fecha, h_ini, h_fin = a_fecha(turno.get("fecha")), a_hora(turno.get("hora_inicio")), a_hora(turno.get("hora_fin"))
    if not fecha or not h_ini or not h_fin:
        return {"errores": ["Completá la fecha y el horario de inicio y fin del turno."], "avisos": [], "setups": [], "paradas": [], "calculo": None}
    if h_ini == h_fin:
        return {"errores": ["El inicio y el fin del turno no pueden ser la misma hora."], "avisos": [], "setups": [], "paradas": [], "calculo": None}
    inicio, fin = limites_turno(fecha, h_ini, h_fin)

    def resolver(filas, etiqueta, completar):
        resueltas = []
        for i, f in enumerate(filas, 1):
            hi, hf = a_hora(f.get("hora_inicio")), a_hora(f.get("hora_fin"))
            if hi is None or hf is None:
                errores.append(f"{etiqueta} {i}: completá la hora de inicio y la de fin.")
                continue
            ini, fi = resolver_tramo(fecha, h_ini, h_fin, hi, hf)
            if ini < inicio or fi > fin:
                errores.append(f"{etiqueta} {i} ({hi:%H:%M} a {hf:%H:%M}): queda fuera del horario del turno ({h_ini:%H:%M} a {h_fin:%H:%M}).")
                continue
            resueltas.append({**f, "inicio": ini, "fin": fi, **completar(f)})
        return resueltas

    setups_r = resolver(setups, "Setup", lambda f: {})
    paradas_r = resolver(paradas, "Parada", lambda f: {"categoria": categorias_falla.get(f.get("tipo_falla"), f.get("categoria"))})
    for i, f in enumerate(setups, 1):
        if not f.get("tipo"):
            errores.append(f"Setup {i}: elegí el tipo de setup.")
    for i, f in enumerate(paradas, 1):
        if not f.get("tipo_falla"):
            errores.append(f"Parada {i}: elegí el tipo de falla.")

    intervalos = sorted([(s["inicio"], s["fin"], f"Setup ({s.get('tipo') or '?'})") for s in setups_r] +
                        [(p["inicio"], p["fin"], f"Parada ({p.get('tipo_falla') or '?'})") for p in paradas_r])
    for (i1, f1, n1), (i2, f2, n2) in zip(intervalos, intervalos[1:]):
        if i2 < f1:
            errores.append(f"Se superponen: {n1} {i1:%H:%M}–{f1:%H:%M} y {n2} {i2:%H:%M}–{f2:%H:%M}.")

    for i, r in enumerate(rechazos, 1):
        if _num(r.get("kg")) > 0 and not r.get("motivo"):
            errores.append(f"Rechazo {i}: elegí el motivo.")
        if _num(r.get("kg")) < 0:
            errores.append(f"Rechazo {i}: los kilos no pueden ser negativos.")
    for campo, etiqueta in (("kg_producidos", "Los kilos producidos"), ("scrap_refile_kg", "El scrap de refile")):
        if _num(turno.get(campo)) < 0:
            errores.append(f"{etiqueta} no pueden ser negativos.")
    for i, s in enumerate(setups, 1):
        if _num(s.get("scrap_kg")) < 0:
            errores.append(f"Setup {i}: el scrap no puede ser negativo.")

    calculo = calcular(inicio, fin, setups_r, paradas_r, rechazos, turno.get("kg_producidos"), turno.get("scrap_refile_kg"),
                       turno.get("ancho_cm"), turno.get("espesor_um"), turno.get("densidad"))
    if calculo["h_prod"] < -1e-6 and not errores:
        errores.append(f"Los setups y las paradas suman {calculo['h_setup'] + calculo['h_parada']:.1f} h y el turno dura {calculo['horas_turno']:.1f} h.")
    kg = _num(turno.get("kg_producidos"))
    if not errores:
        if kg > 0 and calculo["h_prod"] <= 1e-6:
            avisos.append("Cargaste kilos producidos pero no queda tiempo de producción: todo el turno está en setup o paradas.")
        if kg <= 0 and calculo["h_prod"] > 0.25:
            avisos.append(f"El turno tiene {calculo['h_prod']:.1f} h de producción neta pero 0 kilos producidos.")
        if kg > 0 and (_num(turno.get("ancho_cm")) <= 0 or _num(turno.get("espesor_um")) <= 0):
            avisos.append("Sin ancho y espesor no se pueden calcular los metros lineales.")
        if calculo["kg_h"] and calculo["kg_h"] > 1500:
            avisos.append(f"{calculo['kg_h']:.0f} kg/h es un valor muy alto: revisá los kilos y las horas.")
    return {"errores": errores, "avisos": avisos, "setups": setups_r, "paradas": paradas_r, "calculo": calculo}


def solapa_con(turno, existentes, ignorar_id=None):
    """Tramos ya cargados del mismo operador cuyo horario se superpone con el de este. Devuelve la lista."""
    fecha, h_ini, h_fin = a_fecha(turno.get("fecha")), a_hora(turno.get("hora_inicio")), a_hora(turno.get("hora_fin"))
    if not fecha or not h_ini or not h_fin or h_ini == h_fin:
        return []
    ini, fin = limites_turno(fecha, h_ini, h_fin)
    resultado = []
    for e in existentes:
        if e.get("id") == ignorar_id or (e.get("operador") or "").strip().casefold() != (turno.get("operador") or "").strip().casefold():
            continue
        ef, ei, eh = a_fecha(e.get("fecha")), a_hora(e.get("hora_inicio")), a_hora(e.get("hora_fin"))
        if not ef or not ei or not eh or ei == eh:
            continue
        i2, f2 = limites_turno(ef, ei, eh)
        if ini < f2 and i2 < fin:
            resultado.append(e)
    return resultado


# ----------------------------------------------------------------
# Datos guardados -> números (para registros e indicadores)
# ----------------------------------------------------------------
def enriquecer(turnos, setups, paradas, rechazos):
    """Cada tramo guardado con sus setups, paradas, rechazos y todos sus cálculos."""
    hijos = {"s": collections.defaultdict(list), "p": collections.defaultdict(list), "r": collections.defaultdict(list)}
    for s in setups:
        hijos["s"][s["turno_id"]].append({**s, "inicio": a_datetime(s.get("inicio")), "fin": a_datetime(s.get("fin"))})
    for p in paradas:
        hijos["p"][p["turno_id"]].append({**p, "inicio": a_datetime(p.get("inicio")), "fin": a_datetime(p.get("fin"))})
    for r in rechazos:
        hijos["r"][r["turno_id"]].append(r)
    resultado = []
    for t in turnos:
        fecha, h_ini, h_fin = a_fecha(t.get("fecha")), a_hora(t.get("hora_inicio")), a_hora(t.get("hora_fin"))
        if not fecha or not h_ini or not h_fin or h_ini == h_fin:
            continue
        inicio, fin = limites_turno(fecha, h_ini, h_fin)
        s = [x for x in hijos["s"][t["id"]] if x["inicio"] and x["fin"]]
        p = [x for x in hijos["p"][t["id"]] if x["inicio"] and x["fin"]]
        r = hijos["r"][t["id"]]
        calculo = calcular(inicio, fin, s, p, r, t.get("kg_producidos"), t.get("scrap_refile_kg"), t.get("ancho_cm"), t.get("espesor_um"), t.get("densidad"))
        resultado.append({**t, "inicio": inicio, "fin": fin, "setups": s, "paradas": p, "rechazos": r, "calculo": calculo})
    return resultado


def kpis(enr):
    c = [t["calculo"] for t in enr]
    h_turno, h_prod = sum(x["horas_turno"] for x in c), sum(x["h_prod"] for x in c)
    kg, scrap = sum(x["kg"] for x in c), sum(x["scrap_total"] for x in c)
    return {
        "tramos": len(enr), "horas_turno": h_turno, "h_prod": h_prod, "h_setup": sum(x["h_setup"] for x in c),
        "h_parada": sum(x["h_parada"] for x in c), "kg": kg, "metros": sum(x["metros"] for x in c),
        "kg_h": kg / h_prod if h_prod > 0 else None, "scrap_total": scrap,
        "pct_scrap": scrap / (kg + scrap) * 100 if kg + scrap > 0 else None,
        "pct_prod": h_prod / h_turno * 100 if h_turno > 0 else None,
        "pct_setup": sum(x["h_setup"] for x in c) / h_turno * 100 if h_turno > 0 else None,
        "pct_parada": sum(x["h_parada"] for x in c) / h_turno * 100 if h_turno > 0 else None,
    }


def pareto(enr, por="tipo_falla", categorias=None, top=None):
    """Paradas agrupadas por 'tipo_falla' o por 'sistema', de la que más horas suma a la que menos."""
    horas_por, cant = collections.defaultdict(float), collections.Counter()
    for t in enr:
        for p in t["paradas"]:
            if categorias and (p.get("categoria") or "Sin categoría") not in categorias:
                continue
            clave = (p.get(por) or "(sin dato)")
            horas_por[clave] += horas(p["fin"] - p["inicio"])
            cant[clave] += 1
    total = sum(horas_por.values())
    filas, acumulado = [], 0.0
    for clave, h in sorted(horas_por.items(), key=lambda kv: (-kv[1], kv[0])):
        acumulado += h
        filas.append({"clave": clave, "horas": round(h, 2), "cantidad": cant[clave],
                      "pct": round(h / total * 100, 1) if total else 0.0, "acumulado": round(acumulado / total * 100, 1) if total else 0.0})
    return filas[:top] if top else filas


def por_grupo(enr, campo):
    """Producción agrupada por operador, familia, OP o producto (kg/h = kilos totales ÷ horas de producción totales)."""
    acum = collections.defaultdict(lambda: {"tramos": 0, "h_prod": 0.0, "kg": 0.0, "scrap": 0.0, "metros": 0.0})
    for t in enr:
        g = acum[t.get(campo) or "(sin dato)"]
        c = t["calculo"]
        g["tramos"] += 1
        g["h_prod"] += c["h_prod"]
        g["kg"] += c["kg"]
        g["scrap"] += c["scrap_total"]
        g["metros"] += c["metros"]
    filas = []
    for clave, g in acum.items():
        filas.append({"clave": clave, "tramos": g["tramos"], "h_prod": round(g["h_prod"], 2), "kg": round(g["kg"], 1),
                      "kg_h": round(g["kg"] / g["h_prod"], 1) if g["h_prod"] > 0 else None,
                      "pct_scrap": round(g["scrap"] / (g["kg"] + g["scrap"]) * 100, 1) if g["kg"] + g["scrap"] > 0 else None})
    return sorted(filas, key=lambda f: (-(f["kg"] or 0), f["clave"]))


def scrap_por_motivo(enr):
    """Kilos rechazados por motivo, más el scrap de setup y el de refile como componentes del scrap total."""
    motivos = collections.defaultdict(float)
    setup = refile = 0.0
    for t in enr:
        setup += t["calculo"]["scrap_setup"]
        refile += t["calculo"]["scrap_refile"]
        for r in t["rechazos"]:
            motivos[r.get("motivo") or "(sin motivo)"] += _num(r.get("kg"))
    total = setup + refile + sum(motivos.values())
    filas = [{"clave": "Scrap de setup", "kg": round(setup, 1)}, {"clave": "Scrap de refile", "kg": round(refile, 1)}]
    filas += [{"clave": f"Rechazo: {m}", "kg": round(k, 1)} for m, k in sorted(motivos.items(), key=lambda kv: -kv[1])]
    for f in filas:
        f["pct"] = round(f["kg"] / total * 100, 1) if total else 0.0
    return filas


def setup_por_tipo(enr):
    acum = collections.defaultdict(lambda: {"cantidad": 0, "horas": 0.0, "scrap": 0.0})
    for t in enr:
        for s in t["setups"]:
            g = acum[s.get("tipo") or "(sin tipo)"]
            g["cantidad"] += 1
            g["horas"] += horas(s["fin"] - s["inicio"])
            g["scrap"] += _num(s.get("scrap_kg"))
    return sorted(({"clave": k, "cantidad": g["cantidad"], "horas": round(g["horas"], 2),
                    "horas_prom": round(g["horas"] / g["cantidad"], 2), "scrap": round(g["scrap"], 1),
                    "scrap_prom": round(g["scrap"] / g["cantidad"], 1)} for k, g in acum.items()), key=lambda f: -f["horas"])


def evolucion_mensual(enr):
    acum = collections.defaultdict(lambda: {"tramos": 0, "h_turno": 0.0, "h_prod": 0.0, "h_parada": 0.0, "h_setup": 0.0, "kg": 0.0, "scrap": 0.0})
    for t in enr:
        g = acum[(t["inicio"].year, t["inicio"].month)]
        c = t["calculo"]
        g["tramos"] += 1
        g["h_turno"] += c["horas_turno"]
        g["h_prod"] += c["h_prod"]
        g["h_parada"] += c["h_parada"]
        g["h_setup"] += c["h_setup"]
        g["kg"] += c["kg"]
        g["scrap"] += c["scrap_total"]
    return [{"mes": f"{a}-{m:02d}", "tramos": g["tramos"], "h_turno": round(g["h_turno"], 1), "h_prod": round(g["h_prod"], 1),
             "h_setup": round(g["h_setup"], 1), "h_parada": round(g["h_parada"], 1), "kg": round(g["kg"], 1),
             "kg_h": round(g["kg"] / g["h_prod"], 1) if g["h_prod"] > 0 else None,
             "pct_scrap": round(g["scrap"] / (g["kg"] + g["scrap"]) * 100, 1) if g["kg"] + g["scrap"] > 0 else None}
            for (a, m), g in sorted(acum.items())]
