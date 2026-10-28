"""
Lógica de la Programación de Preventivos.

No usa Streamlit ni la base de datos: recibe listas de planes y equipos y devuelve
números y fechas, así se puede probar sola.

Conceptos:
- Un plan tiene una primera fecha (proxima_ejecucion) y una frecuencia en días: se repite
  cada N días a partir de esa fecha.
- Cada ejecución consume horas-hombre (HH), puede requerir máquina parada (HH en parada)
  y tiene un costo estimado en guaraníes.
- "Línea" = equipos que se detienen juntos (toda la COEX es la línea 'R9'). Dos paradas el
  mismo día o la misma semana en la misma línea se acumulan.
"""
import collections
from datetime import date, datetime, timedelta

PARAMS_DEFECTO = {
    "max_hp_semana": 30.0,   # máximo de HH en parada por semana y por línea
    "hh_semana": 40.0,       # HH de mantenimiento disponibles por semana (todo el equipo)
    "tope_mes": 0.0,         # tope de gasto por mes en Gs.; 0 = usar 1,5 veces el promedio mensual
    "hp_minima_coincidencia": 2.0,   # paradas de menos HH que esto no se consideran "choque" entre sí
    "costo_plan_grande": 10_000_000,  # un plan que cuesta esto o más (o supera el máximo de parada) es "grande"
    "dias_plan_grande": 30,          # los planes grandes no se proponen antes de estos días (coordinar parada y compras)
    "horizonte": 365,        # días hacia adelante que se proyectan
}


# ----------------------------------------------------------------
# Utilidades de fecha
# ----------------------------------------------------------------
def a_fecha(valor):
    """Acepta date, datetime, 'AAAA-MM-DD' o None."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    try:
        return datetime.strptime(str(valor)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def lunes_de(fecha):
    return fecha - timedelta(days=fecha.weekday())


def ocurrencias(inicio, frecuencia_dias, desde, hasta):
    """Fechas de ejecución desde 'inicio' cada 'frecuencia_dias', limitadas al rango [desde, hasta]."""
    if inicio is None or not frecuencia_dias or int(frecuencia_dias) <= 0:
        return []
    f = int(frecuencia_dias)
    if inicio < desde:
        pasos = -(-(desde - inicio).days // f)            # techo
        actual = inicio + timedelta(days=pasos * f)
    else:
        actual = inicio
    resultado = []
    while actual <= hasta:
        resultado.append(actual)
        actual += timedelta(days=f)
    return resultado


def _siguiente_mes(d):
    return date(d.year + (d.month == 12), d.month % 12 + 1, 1)


def linea_de(plan, maquinas):
    m = maquinas.get(plan.get("maquina_id"), {})
    return m.get("linea") or m.get("codigo") or f"M{plan.get('maquina_id')}"


def etiqueta_plan(plan, maquinas):
    m = maquinas.get(plan.get("maquina_id"), {})
    return f"{m.get('codigo') or '?'} · {plan.get('nombre_plan')}"


def _num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


# ----------------------------------------------------------------
# Proyección y cargas
# ----------------------------------------------------------------
def proyectar(planes, maquinas, desde, hasta):
    """Todas las ejecuciones de los planes que tienen fecha, dentro del rango."""
    ocs = []
    for p in planes:
        inicio = a_fecha(p.get("proxima_ejecucion"))
        for f in ocurrencias(inicio, p.get("frecuencia_dias"), desde, hasta):
            ocs.append({"plan_id": p["id"], "fecha": f, "linea": linea_de(p, maquinas),
                        "costo": _num(p.get("costo_estimado")), "hh": _num(p.get("horas_hombre")),
                        "hp": _num(p.get("horas_parada"))})
    return ocs


def resumen_mensual(ocs, desde, hasta):
    """Una fila por mes del rango (aunque no tenga nada): eventos, gasto, HH y HH en parada."""
    meses = collections.OrderedDict()
    d = date(desde.year, desde.month, 1)
    while d <= hasta:
        meses[(d.year, d.month)] = {"mes": d, "eventos": 0, "costo": 0.0, "hh": 0.0, "hp": 0.0}
        d = _siguiente_mes(d)
    for o in ocs:
        fila = meses.get((o["fecha"].year, o["fecha"].month))
        if fila:
            fila["eventos"] += 1
            fila["costo"] += o["costo"]
            fila["hh"] += o["hh"]
            fila["hp"] += o["hp"]
    return list(meses.values())


def carga_semanal(ocs):
    """{(lunes, línea): {'hp', 'hh', 'ids'}} con las HH de cada línea en cada semana."""
    semanas = collections.defaultdict(lambda: {"hp": 0.0, "hh": 0.0, "ids": []})
    for o in ocs:
        s = semanas[(lunes_de(o["fecha"]), o["linea"])]
        s["hp"] += o["hp"]
        s["hh"] += o["hh"]
        s["ids"].append(o["plan_id"])
    return dict(semanas)


# ----------------------------------------------------------------
# Avisos
# ----------------------------------------------------------------
def detectar_avisos(ocs, planes, maquinas, desde, hasta, params=None, presupuesto_mes=None):
    """
    Lista de avisos ordenada por gravedad. Cada aviso: {tipo, severidad, texto, plan_ids}.
    severidad: 'alta' (hay que corregirlo), 'media' (conviene revisarlo), 'info' (solo informativo).
    presupuesto_mes: {(año, mes): monto} con el presupuesto mensual cargado en el sistema (opcional).
    """
    P = {**PARAMS_DEFECTO, **(params or {})}
    por_id = {p["id"]: p for p in planes}
    nombre = lambda pid: etiqueta_plan(por_id[pid], maquinas) if pid in por_id else f"plan {pid}"
    avisos = []

    # 1) Paradas acumuladas en una misma línea y semana
    hp_sem = collections.defaultdict(lambda: {"hp": 0.0, "ids": [], "por_plan": collections.defaultdict(float)})
    hh_sem = collections.defaultdict(lambda: {"hh": 0.0, "ids": []})
    for o in ocs:
        lun = lunes_de(o["fecha"])
        if o["hp"] > 0:
            hp_sem[(lun, o["linea"])]["hp"] += o["hp"]
            hp_sem[(lun, o["linea"])]["ids"].append(o["plan_id"])
            hp_sem[(lun, o["linea"])]["por_plan"][o["plan_id"]] += o["hp"]
        hh_sem[lun]["hh"] += o["hh"]
        hh_sem[lun]["ids"].append(o["plan_id"])
    for (lun, linea), v in sorted(hp_sem.items()):
        if v["hp"] <= P["max_hp_semana"]:
            continue
        ids = list(dict.fromkeys(v["ids"]))
        mayor_id, mayor_hp = max(v["por_plan"].items(), key=lambda kv: kv[1])
        resto = v["hp"] - mayor_hp
        if mayor_hp > P["max_hp_semana"] and resto <= 0.25 * P["max_hp_semana"]:
            extra = f" (más {resto:.1f} HH de rutina de otros planes)" if resto > 0 else ""
            avisos.append({"tipo": "plan_mayor", "severidad": "info", "plan_ids": [mayor_id],
                           "texto": f"Semana del {lun:%d/%m/%Y}: «{nombre(mayor_id)}» necesita {mayor_hp:.0f} HH con la línea parada{extra}. "
                                    f"Supera el máximo de {P['max_hp_semana']:.0f}, pero es un solo plan y no se puede dividir: "
                                    "asegurate de que esa semana no tenga ningún otro trabajo importante en esa línea."})
        else:
            avisos.append({"tipo": "acumulacion_parada", "severidad": "alta", "plan_ids": ids,
                           "texto": f"Semana del {lun:%d/%m/%Y}: la línea {linea} acumula {v['hp']:.0f} HH en parada con "
                                    f"{len(ids)} planes (máximo {P['max_hp_semana']:.0f}). Movelos a semanas distintas."})

    # 2) HH de todo el equipo en una semana
    for lun, v in sorted(hh_sem.items()):
        if v["hh"] > P["hh_semana"]:
            ids = list(dict.fromkeys(v["ids"]))
            avisos.append({"tipo": "hh_semana", "severidad": "media", "plan_ids": ids,
                           "texto": f"Semana del {lun:%d/%m/%Y}: {v['hh']:.0f} HH de mantenimiento programadas "
                                    f"(disponibles: {P['hh_semana']:.0f}). {len(ids)} plan(es) esa semana."})

    # 3) Dos paradas el mismo día en la misma línea
    por_dia = collections.defaultdict(list)
    for o in ocs:
        if o["hp"] >= P["hp_minima_coincidencia"]:
            por_dia[(o["fecha"], o["linea"])].append(o["plan_id"])
    for (dia, linea), ids in sorted(por_dia.items()):
        ids = list(dict.fromkeys(ids))
        if len(ids) >= 2:
            avisos.append({"tipo": "mismo_dia", "severidad": "media", "plan_ids": ids,
                           "texto": f"{dia:%d/%m/%Y}: coinciden {len(ids)} paradas en la línea {linea} "
                                    f"({'; '.join(nombre(i) for i in ids[:3])}{'…' if len(ids) > 3 else ''})."})

    # 4) Gasto mensual alto
    meses = resumen_mensual(ocs, desde, hasta)
    total = sum(m["costo"] for m in meses)
    promedio = total / len(meses) if meses else 0
    for m in meses:
        presu = (presupuesto_mes or {}).get((m["mes"].year, m["mes"].month))
        tope = presu or P["tope_mes"] or (1.5 * promedio)
        if tope and m["costo"] > tope:
            origen = "presupuesto del mes" if presu else ("tope que definiste" if P["tope_mes"] else "1,5 veces el promedio mensual")
            avisos.append({"tipo": "gasto_mes", "severidad": "media", "plan_ids": [],
                           "texto": f"{m['mes']:%m/%Y}: gasto programado de Gs. {m['costo']:,.0f} supera el {origen} "
                                    f"(Gs. {tope:,.0f}).".replace(",", ".")})
    orden = {"alta": 0, "media": 1, "info": 2}
    return sorted(avisos, key=lambda a: orden[a["severidad"]])


# ----------------------------------------------------------------
# Sugerencia automática de fechas
# ----------------------------------------------------------------
def sugerir_fechas(planes, maquinas, inicio, fijos_ids=(), params=None):
    """
    Propone una primera fecha (día hábil) para cada plan que no esté en 'fijos_ids', repartiendo
    la carga a lo largo del año:
      - HH en parada por semana y línea, HH de todo el equipo por semana y gasto por mes;
      - evita dos paradas el mismo día en la misma línea;
      - coloca primero lo más pesado (lo difícil de ubicar) y lo liviano después.
    Los planes en 'fijos_ids' (que ya tienen fecha) no se mueven, pero se tienen en cuenta.

    Devuelve {plan_id: fecha}.
    """
    P = {**PARAMS_DEFECTO, **(params or {})}
    horizonte = int(P["horizonte"])
    hasta = inicio + timedelta(days=horizonte)
    fijos_ids = set(fijos_ids)

    L_hp, L_hh, L_c = collections.defaultdict(float), collections.defaultdict(float), collections.defaultdict(float)
    ocupado = collections.defaultdict(int)                     # (día, línea) -> paradas ese día

    def sumar(fecha, linea, hp, hh, c):
        L_hp[(lunes_de(fecha), linea)] += hp
        L_hh[lunes_de(fecha)] += hh
        L_c[(fecha.year, fecha.month)] += c
        if hp >= P["hp_minima_coincidencia"]:
            ocupado[(fecha, linea)] += 1

    fijos = [p for p in planes if p["id"] in fijos_ids and a_fecha(p.get("proxima_ejecucion"))]
    for o in proyectar(fijos, maquinas, inicio, hasta):
        sumar(o["fecha"], o["linea"], o["hp"], o["hh"], o["costo"])

    a_ubicar = [p for p in planes if p["id"] not in fijos_ids and (p.get("frecuencia_dias") or 0) > 0]
    gasto_anual = sum(_num(p.get("costo_estimado")) * horizonte / int(p["frecuencia_dias"]) for p in a_ubicar)
    gasto_anual += sum(o["costo"] for o in proyectar(fijos, maquinas, inicio, hasta))
    s_hp = max(P["max_hp_semana"], 1.0)
    s_hh = max(P["hh_semana"], 1.0)
    s_c = P["tope_mes"] or max(gasto_anual / 12, 1.0)

    peso = lambda p: _num(p.get("horas_parada")) * 3 + _num(p.get("horas_hombre")) + _num(p.get("costo_estimado")) / 1e6 * 2
    resultado = {}
    for p in sorted(a_ubicar, key=peso, reverse=True):
        f = int(p["frecuencia_dias"])
        linea = linea_de(p, maquinas)
        hp, hh, c = _num(p.get("horas_parada")), _num(p.get("horas_hombre")), _num(p.get("costo_estimado"))
        mejor = None
        grande = c >= P["costo_plan_grande"] or hp > P["max_hp_semana"]
        primero = int(P["dias_plan_grande"]) if grande else 0
        for delta in range(primero, min(primero + min(f, horizonte), horizonte)):   # la 1.ª fecha siempre dentro del año proyectado
            cand = inicio + timedelta(days=delta)
            if cand.weekday() >= 5:                              # solo días hábiles para la primera fecha
                continue
            puntaje = 1e-4 * delta                               # a igualdad, la fecha más cercana
            for o in ocurrencias(cand, f, inicio, hasta):
                lun = lunes_de(o)
                if hp:
                    puntaje += ((L_hp[(lun, linea)] + hp) ** 2 - L_hp[(lun, linea)] ** 2) / s_hp ** 2
                if hh:
                    puntaje += ((L_hh[lun] + hh) ** 2 - L_hh[lun] ** 2) / s_hh ** 2
                if c:
                    mes = (o.year, o.month)
                    puntaje += ((L_c[mes] + c) ** 2 - L_c[mes] ** 2) / s_c ** 2
                if hp >= P["hp_minima_coincidencia"] and ocupado[(o, linea)]:
                    puntaje += 50.0                              # dos paradas el mismo día en la misma línea
                if o.weekday() >= 5:
                    puntaje += 0.02                              # cae sábado/domingo: se hará el día hábil cercano
            if mejor is None or puntaje < mejor[0]:
                mejor = (puntaje, cand)
        elegido = mejor[1] if mejor else inicio
        resultado[p["id"]] = elegido
        for o in ocurrencias(elegido, f, inicio, hasta):
            sumar(o, linea, hp, hh, c)
    return resultado
