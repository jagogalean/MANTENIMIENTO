"""
Inicio: el centro de control del día.

Responde, en este orden: ¿hay máquinas paradas?, ¿cómo vamos este mes?,
¿qué hago hoy?, ¿qué llegó por QR?, ¿qué falta en el almacén?
Reemplaza al Panel General y al Asistente del Día (sus cálculos se reutilizan).
"""
import streamlit as st

from views import ui
from views.asistente import construir_agenda_del_dia, generar_resumen_ia
from views.dashboard import calcular_ranking_maquinas
from views.presupuesto import calcular_gasto_real_por_mes
from database.conection import get_presupuestos_cached
from database.ots_servicio import es_parada

# Categoría de la agenda -> (nombre corto, pantalla a la que lleva)
_DESTINO = {
    "Backlog sin asignar": ("Sin asignar", "ordenes"),
    "OT Bloqueada": ("Bloqueada", "ordenes"),
    "OT Pendiente": ("OT", "ordenes"),
    "Plan Preventivo": ("Preventivo", "preventivo"),
    "Stock Crítico": ("Stock", "repuestos"),
    "Contrato / Tercero": ("Tercero", "terceros"),
}


def _sin_emoji(categoria):
    partes = str(categoria).split(" ", 1)
    return partes[1] if len(partes) == 2 and not partes[0][:1].isalnum() else str(categoria)


def _horas(ot_desde, hasta):
    d = ui.a_datetime(ot_desde)
    if not d:
        return None
    return max((hasta - d).total_seconds() / 3600, 0)


def _texto_antiguedad(horas):
    if horas is None:
        return ""
    if horas < 1:
        return "hace minutos"
    if horas < 24:
        return f"hace {horas:.0f} h"
    return f"hace {horas / 24:.0f} d"


def _ir_a(paginas, clave, etiqueta, key, vista_ot=None):
    """Botón que lleva a otra pantalla. Si esa pantalla no está en el menú del rol, no se muestra."""
    pagina = paginas.get(clave)
    if pagina is None:
        return
    if st.button(etiqueta, key=key, use_container_width=True):
        if vista_ot:
            st.session_state["ots_vista_pedida"] = vista_ot
        st.switch_page(pagina)


@st.cache_data(ttl=60, show_spinner=False)
def _rutinas_de_hoy():
    """(hechos, total, pendientes_por_zona) de las rutinas del operador: diarias de hoy y semanales de esta semana."""
    from database import rutinas_db as rdb
    from database import rutinas_logica as R
    hoy = R.hoy_paraguay()
    zonas = {z["id"]: z["nombre"] for z in rdb.listar_zonas()}
    items = [{**i, "zona_nombre": zonas.get(i["zona_id"])} for i in rdb.listar_items() if i.get("activo") is not False]
    if not items:
        return None
    ejec = rdb.listar_ejecuciones(R.lunes_de(hoy), hoy)
    por_id = {e["id"]: e for e in ejec}
    resp = rdb.listar_respuestas(list(por_id)) if ejec else []
    hechos = [{"item_id": r.get("item_id"), "fecha": por_id[r["ejecucion_id"]]["fecha"], "operador": por_id[r["ejecucion_id"]].get("operador_nombre"),
               "resultado": r.get("resultado"), "hora": por_id[r["ejecucion_id"]].get("creado_en")} for r in resp if r["ejecucion_id"] in por_id]
    estados = R.estado_items(items, hechos, hoy)
    pendientes = {}
    for e in estados:
        if e["estado"] != "hecho":
            z = e["item"].get("zona_nombre") or "(sin zona)"
            pendientes[z] = pendientes.get(z, 0) + 1
    return sum(1 for e in estados if e["estado"] == "hecho"), len(estados), pendientes


def _tarjeta_rutinas(paginas):
    try:
        datos = _rutinas_de_hoy()
    except Exception:
        return                                   # si las tablas de rutinas no están, la tarjeta no aparece
    if not datos:
        return
    hechos, total, pendientes = datos
    with st.container(border=True):
        color = "green" if hechos == total else ("red" if hechos == 0 else "orange")
        st.subheader("Rutinas de hoy")
        st.markdown(f":{color}-badge[{hechos} de {total} hechos]")
        st.progress(hechos / total if total else 0)
        if pendientes:
            st.caption("Falta: " + " · ".join(f"{z} ({n})" for z, n in sorted(pendientes.items())))
        else:
            st.caption("Se hizo todo lo de hoy.")
        _ir_a(paginas, "rutinas", "Ver qué se hizo", "ini_rutinas")


def render_inicio(usuario, paginas, avisos_pendientes=None):
    ahora = ui.ahora()
    hoy = ahora.date()
    maquinas = st.session_state.get("maquinas", [])
    ots = st.session_state.get("ots", [])
    planes = st.session_state.get("planes", [])
    repuestos = st.session_state.get("repuestos", [])
    ejecuciones = st.session_state.get("plan_ejecuciones", [])
    mapa_maq = {m["id"]: m for m in maquinas}
    es_admin = usuario.get("rol") == "admin"

    cab, acciones = st.columns([3, 2], vertical_alignment="bottom")
    with cab:
        ui.encabezado("Inicio", f"{ui.fecha_larga(hoy).capitalize()} · Lo que necesita atención primero")
    with acciones:
        if es_admin:
            b1, b2 = st.columns(2)
            with b1:
                _ir_a(paginas, "ordenes", ui.con_contador("Ver avisos QR", len(avisos_pendientes or [])),
                      "ini_ver_avisos", vista_ot="avisos")
            with b2:
                if paginas.get("ordenes") is not None and st.button("+ Nueva OT", type="primary",
                                                                    use_container_width=True, key="ini_nueva_ot"):
                    st.session_state["ots_abrir_nueva"] = True
                    st.switch_page(paginas["ordenes"])

    abiertas = [o for o in ots if o.get("estado") != "Completada"]

    # --- 1. Máquinas paradas ---------------------------------------------------
    paradas = [o for o in abiertas if es_parada(o)]
    if paradas:
        detalle = " · ".join(
            f"{mapa_maq.get(o.get('maquina_id'), {}).get('nombre', 'Máquina')} "
            f"({o.get('codigo')}, {_texto_antiguedad(_horas(o.get('fecha_inicio'), ahora))})"
            for o in paradas[:4]
        )
        st.error(f"**{len(paradas)} máquina(s) parada(s).** {detalle}", icon=":material/warning:")

    # --- 2. Indicadores del mes -----------------------------------------------
    inicio_mes = hoy.replace(day=1)
    bloqueadas = [o for o in abiertas if o.get("estado") == "Bloqueada"]
    sin_asignar = [o for o in abiertas if o.get("tecnico_id") is None]

    vencidos, proximos = [], []
    for p in planes:
        f = ui.a_fecha(p.get("proxima_ejecucion"))
        if f is None:
            continue
        if f < hoy:
            vencidos.append(p)
        elif (f - hoy).days <= 7:
            proximos.append(p)

    hechos_mes = [e for e in ejecuciones
                  if (ui.a_fecha(e.get("fecha_realizada")) or hoy.replace(year=1900)) >= inicio_mes]
    base_cumpl = len(hechos_mes) + len(vencidos)
    cumplimiento = round(100 * len(hechos_mes) / base_cumpl) if base_cumpl else None

    gasto_mes = calcular_gasto_real_por_mes(ots, st.session_state.get("ot_repuestos", []), repuestos) \
        .get(inicio_mes.strftime("%Y-%m-01"), {})
    gasto_total = sum(gasto_mes.get(k, 0) for k in ("mano_obra", "repuestos", "terceros"))
    presupuesto = 0
    try:
        for fila in get_presupuestos_cached() or []:
            if str(fila.get("periodo"))[:10] == inicio_mes.strftime("%Y-%m-01") and fila.get("categoria") == "total":
                presupuesto = float(fila.get("monto") or 0)
    except Exception as e:
        ui.log.warning("No se pudo leer el presupuesto: %s", e)

    k1, k2, k3, k4 = st.columns(4)
    with k1, st.container(border=True):
        st.metric("OTs abiertas", len(abiertas))
        st.caption(f"{len(bloqueadas)} bloqueadas · {len(sin_asignar)} sin asignar")
    with k2, st.container(border=True):
        st.metric("Preventivos vencidos", len(vencidos))
        st.caption(f"{len(proximos)} más vencen en 7 días")
    with k3, st.container(border=True):
        st.metric(f"Cumplimiento preventivo · {ui.nombre_mes(hoy)}",
                  f"{cumplimiento} %" if cumplimiento is not None else "—")
        st.caption(f"{len(hechos_mes)} hechos · {len(vencidos)} vencidos sin hacer")
    with k4, st.container(border=True):
        st.metric(f"Gasto de {ui.nombre_mes(hoy)}", ui.formato_gs(gasto_total))
        if presupuesto:
            pct = gasto_total / presupuesto
            st.progress(min(pct, 1.0))
            st.caption(f"{pct * 100:.0f} % del presupuesto de {ui.formato_gs(presupuesto)}")
        else:
            st.caption("Sin presupuesto cargado para este mes")

    # --- 3. Para hoy + avisos + stock -----------------------------------------
    izq, der = st.columns([3, 2], gap="medium")

    with izq, st.container(border=True):
        st.subheader("Para hoy")
        tareas = construir_agenda_del_dia()
        if not tareas:
            st.success("No hay pendientes urgentes. Buen momento para avanzar con el preventivo.")
        else:
            st.caption(f"{len(tareas)} pendientes, ordenados por prioridad. Se muestran los 8 primeros.")
            for i, t in enumerate(tareas[:8]):
                categoria = _sin_emoji(t["categoria"])
                corto, destino = _DESTINO.get(categoria, (categoria, None))
                color = "red" if t["alerta"] else ("orange" if t["prioridad"] >= 2 else "gray")
                c_txt, c_btn = st.columns([5, 1.3], vertical_alignment="center")
                c_txt.markdown(f":{color}-badge[{corto}] {t['texto'].replace('⚠️', '').strip()}")
                with c_btn:
                    if destino:
                        _ir_a(paginas, destino, "Abrir", f"ini_tarea_{i}")
            if len(tareas) > 8:
                with st.expander(f"Ver los otros {len(tareas) - 8}"):
                    for t in tareas[8:]:
                        st.markdown(f"- {_sin_emoji(t['categoria'])}: {t['texto'].replace('⚠️', '').strip()}")

    with der:
        if "rutinas" in paginas:
            _tarjeta_rutinas(paginas)
        if es_admin and avisos_pendientes is not None:
            with st.container(border=True):
                st.subheader(ui.con_contador("Avisos QR nuevos", len(avisos_pendientes)))
                if not avisos_pendientes:
                    st.caption("No hay avisos pendientes.")
                for s in avisos_pendientes[:3]:
                    nombre = mapa_maq.get(s.get("equipo_id"), {}).get("nombre", "Máquina")
                    texto = str(s.get("descripcion") or "")[:70]
                    st.markdown(f"**{texto}**  \n:gray[{nombre} · Prioridad {s.get('prioridad') or '—'}]")
                if avisos_pendientes:
                    _ir_a(paginas, "ordenes", "Revisar avisos", "ini_avisos", vista_ot="avisos")

        criticos = sorted([r for r in repuestos if (r.get("stock_actual") or 0) <= (r.get("stock_minimo") or 0)],
                          key=lambda r: (r.get("stock_actual") or 0))
        with st.container(border=True):
            st.subheader(ui.con_contador("Stock bajo mínimo", len(criticos)))
            if not criticos:
                st.caption("Todo el stock está por encima del mínimo.")
            for r in criticos[:5]:
                color = "red" if (r.get("stock_actual") or 0) <= 0 else "orange"
                st.markdown(f"{r.get('nombre')} :{color}-badge[{r.get('stock_actual') or 0} de "
                            f"{r.get('stock_minimo') or 0}]")
            if criticos:
                _ir_a(paginas, "compras", "Pedir compra", "ini_compra")

    # --- 4. Estado de las OTs y costos del año --------------------------------
    c_est, c_rank = st.columns([3, 2], gap="medium")
    with c_est, st.container(border=True):
        st.subheader("OTs abiertas por estado")
        conteo = {
            "Pendientes": len([o for o in abiertas if o.get("estado") == "Pendiente"]),
            "En ejecución": len([o for o in abiertas if o.get("estado") == "En Ejecucion"]),
            "Bloqueadas": len(bloqueadas),
        }
        if not abiertas:
            st.caption("No hay OTs abiertas.")
        else:
            st.bar_chart({"OTs": conteo}, horizontal=True, height=180, color="#0E5A75")
        # Indicadores del mes (no de toda la historia)
        correctivas_mes = [o for o in ots if o.get("tipo_mantenimiento") == "Correctivo"
                           and o.get("estado") == "Completada"
                           and (ui.a_fecha(o.get("fecha_fin")) or hoy.replace(year=1900)) >= inicio_mes]
        horas_rep = [h for h in (_horas(o.get("fecha_inicio"), ui.a_datetime(o.get("fecha_fin")) or ahora)
                                 for o in correctivas_mes) if h is not None]
        mttr = sum(horas_rep) / len(horas_rep) if horas_rep else None
        paro_mes = sum(float(o.get("horas_paro") or 0) for o in ots
                       if (ui.a_fecha(o.get("fecha_inicio")) or hoy.replace(year=1900)) >= inicio_mes)
        st.caption(f"MTTR de {ui.nombre_mes(hoy)}: {f'{mttr:.1f} h' if mttr is not None else 'sin correctivas cerradas'}"
                   f" · Horas de paro de {ui.nombre_mes(hoy)}: {paro_mes:.1f} h")

    with c_rank, st.container(border=True):
        st.subheader(f"Máquinas con más costo · {hoy.year}")
        ots_anio = [o for o in ots if (ui.a_fecha(o.get("fecha_inicio")) or hoy.replace(year=1900)).year == hoy.year]
        ranking = [r for r in calcular_ranking_maquinas(maquinas, ots_anio, st.session_state.get("ot_repuestos", []),
                                                        repuestos) if r["costo_total"] > 0]
        if not ranking:
            st.caption("Todavía no hay costos cargados en las OTs de este año.")
        for r in ranking:
            st.markdown(f"**{r['nombre']}** · {ui.formato_gs(r['costo_total'])} · {float(r['horas_paro'] or 0):.1f} h de paro")

    with st.expander("Resumen del día redactado con IA"):
        st.caption("La IA solo resume la lista de pendientes; no agrega datos.")
        if st.button("Generar resumen", key="ini_ia"):
            with st.spinner("Redactando..."):
                st.info(generar_resumen_ia(construir_agenda_del_dia()))
