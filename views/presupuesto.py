import streamlit as st
from datetime import datetime, date
import calendar
from database.conection import get_presupuestos_cached, guardar_presupuesto

CATEGORIAS = ["mano_obra", "repuestos", "terceros"]
NOMBRES_CATEGORIA = {
    "mano_obra": "🔧 Mano de Obra",
    "repuestos": "🔩 Repuestos",
    "terceros": "🚚 Terceros / Servicios",
    "total": "💰 Total"
}


def _primer_dia_mes(alguna_fecha: date) -> str:
    return alguna_fecha.replace(day=1).strftime("%Y-%m-%d")


def _mes_de_iso(fecha_iso: str):
    """Extrae 'YYYY-MM-01' a partir de una fecha ISO guardada en una OT."""
    try:
        f = datetime.fromisoformat(fecha_iso.replace("Z", "+00:00"))
        return f.strftime("%Y-%m-01")
    except (TypeError, ValueError, AttributeError):
        return None


def calcular_gasto_real_por_mes(ots, ot_repuestos, repuestos):
    """
    Recorre TODAS las OTs y arma, por mes (periodo 'YYYY-MM-01'), cuánto se
    gastó en cada categoría. El mes se define por la fecha de inicio de la OT.

    OJO: el Lucro Cesante (costo de la parada de producción) NO se incluye
    acá a propósito — es un indicador de impacto en producción, no un gasto
    que salga de tu presupuesto de mantenimiento. Se muestra aparte, como
    dato de referencia, para no mezclar los dos conceptos.
    """
    map_costo_rep = {r["id"]: r.get("costo_unitario", 0) for r in repuestos}

    costo_repuestos_por_ot = {}
    for orr in ot_repuestos:
        ot_id = orr.get("ot_id")
        costo = orr.get("cantidad_usada", 0) * map_costo_rep.get(orr.get("repuesto_id"), 0)
        costo_repuestos_por_ot[ot_id] = costo_repuestos_por_ot.get(ot_id, 0) + costo

    gasto = {}  # { 'YYYY-MM-01': {'mano_obra': x, 'repuestos': x, 'terceros': x, 'lucro_cesante': x} }

    for o in ots:
        mes = _mes_de_iso(o.get("fecha_inicio"))
        if not mes:
            continue
        if mes not in gasto:
            gasto[mes] = {"mano_obra": 0, "repuestos": 0, "terceros": 0, "lucro_cesante": 0}

        gasto[mes]["mano_obra"] += o.get("costo_mano_obra", 0) or 0
        gasto[mes]["repuestos"] += costo_repuestos_por_ot.get(o.get("id"), 0)
        gasto[mes]["terceros"] += (o.get("costo_factura_tercero", 0) or 0) + (o.get("costo_flete_logistica", 0) or 0)
        gasto[mes]["lucro_cesante"] += o.get("costo_lucro_cesante", 0) or 0

    return gasto


def _color_alerta(pct):
    if pct >= 100:
        return "#EF4444", "🔴"
    elif pct >= 90:
        return "#F59E0B", "🟠"
    elif pct >= 80:
        return "#EAB308", "🟡"
    return "#10B981", "🟢"


def _fmt_gs(monto):
    return f"Gs. {monto:,.0f}".replace(",", ".")


def render_presupuesto(usuario):
    st.title("💰 Presupuesto de Mantenimiento")
    st.write("Compará lo que Vitopel te autorizó a gastar contra lo que realmente estás gastando, mes a mes.")

    ots = st.session_state.get("ots", [])
    ot_repuestos = st.session_state.get("ot_repuestos", [])
    repuestos = st.session_state.get("repuestos", [])
    presupuestos = get_presupuestos_cached()

    gasto_por_mes = calcular_gasto_real_por_mes(ots, ot_repuestos, repuestos)
    map_presupuesto = {}  # { 'YYYY-MM-01': {'total': x, 'mano_obra': x, ...} }
    for p in presupuestos:
        mes = p.get("periodo")
        map_presupuesto.setdefault(mes, {})[p.get("categoria")] = p.get("monto", 0)

    # --- SELECCIÓN DE MES A ANALIZAR ---
    hoy = datetime.now().date()
    mes_actual_str = _primer_dia_mes(hoy)

    meses_disponibles = sorted(set(list(gasto_por_mes.keys()) + list(map_presupuesto.keys()) + [mes_actual_str]), reverse=True)
    dict_meses = {datetime.strptime(m, "%Y-%m-%d").strftime("%B %Y").capitalize(): m for m in meses_disponibles}
    mes_sel_nombre = st.selectbox("Mes a analizar", list(dict_meses.keys()), index=0)
    mes_sel = dict_meses[mes_sel_nombre]

    presu_mes = map_presupuesto.get(mes_sel, {})
    gasto_mes = gasto_por_mes.get(mes_sel, {"mano_obra": 0, "repuestos": 0, "terceros": 0, "lucro_cesante": 0})

    # --- CARGAR / EDITAR PRESUPUESTO DEL MES (solo Admin) ---
    if usuario.get("rol") == "admin":
        with st.expander(f"✏️ Cargar / Editar presupuesto de {mes_sel_nombre}"):
            st.caption(
                "Cargá el monto que te dio Vitopel para el mes. Si te dan un solo número global, "
                "completá solo 'Presupuesto Total' y dejá el desglose en 0. Si te lo dan separado "
                "por categoría, completá el desglose — el total se calcula solo con la suma."
            )
            total_actual = presu_mes.get("total", 0)
            mano_obra_actual = presu_mes.get("mano_obra", 0)
            repuestos_actual = presu_mes.get("repuestos", 0)
            terceros_actual = presu_mes.get("terceros", 0)

            usa_desglose = st.checkbox(
                "Vitopel me da el presupuesto desglosado por categoría",
                value=bool(mano_obra_actual or repuestos_actual or terceros_actual),
                key=f"usa_desglose_{mes_sel}"
            )

            if usa_desglose:
                c1, c2, c3 = st.columns(3)
                nuevo_mo = c1.number_input("Mano de Obra (Gs.)", min_value=0, step=100000, value=int(mano_obra_actual), key=f"presu_mo_{mes_sel}")
                nuevo_rep = c2.number_input("Repuestos (Gs.)", min_value=0, step=100000, value=int(repuestos_actual), key=f"presu_rep_{mes_sel}")
                nuevo_ter = c3.number_input("Terceros (Gs.)", min_value=0, step=100000, value=int(terceros_actual), key=f"presu_ter_{mes_sel}")
                nuevo_total = nuevo_mo + nuevo_rep + nuevo_ter
                st.caption(f"Total calculado del desglose: **{_fmt_gs(nuevo_total)}**")
            else:
                nuevo_total = st.number_input("Presupuesto Total del mes (Gs.)", min_value=0, step=100000, value=int(total_actual), key=f"presu_total_{mes_sel}")
                nuevo_mo, nuevo_rep, nuevo_ter = 0, 0, 0

            if st.button("💾 Guardar presupuesto de este mes", key=f"guardar_presu_{mes_sel}"):
                guardar_presupuesto(mes_sel, "total", nuevo_total)
                if usa_desglose:
                    guardar_presupuesto(mes_sel, "mano_obra", nuevo_mo)
                    guardar_presupuesto(mes_sel, "repuestos", nuevo_rep)
                    guardar_presupuesto(mes_sel, "terceros", nuevo_ter)
                get_presupuestos_cached.clear()
                st.success(f"✅ Presupuesto de {mes_sel_nombre} guardado.")
                st.rerun()

    st.markdown("---")

    presupuesto_total = presu_mes.get("total", 0)
    gasto_total = gasto_mes["mano_obra"] + gasto_mes["repuestos"] + gasto_mes["terceros"]

    if presupuesto_total == 0:
        st.warning(f"⚠️ Todavía no cargaste el presupuesto de {mes_sel_nombre}. El gasto real de todos modos se muestra abajo.")
    else:
        pct = round((gasto_total / presupuesto_total) * 100, 1)
        color, icono = _color_alerta(pct)

        st.markdown(f"### {icono} Resumen de {mes_sel_nombre}")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Presupuestado", _fmt_gs(presupuesto_total))
        m2.metric("Gastado", _fmt_gs(gasto_total))
        m3.metric("Disponible", _fmt_gs(max(presupuesto_total - gasto_total, 0)))
        m4.markdown(f"""
        <div style='text-align:center;'>
            <small style='color:#7C8894; font-weight:bold;'>% CONSUMIDO</small>
            <h2 style='color:{color}; margin:4px 0;'>{pct}%</h2>
        </div>
        """, unsafe_allow_html=True)

        st.progress(min(pct / 100, 1.0))

        if pct >= 100:
            st.error(f"🔴 Te pasaste del presupuesto de {mes_sel_nombre} en {_fmt_gs(gasto_total - presupuesto_total)}.")
        elif pct >= 90:
            st.warning(f"🟠 Estás al {pct}% del presupuesto — quedan {_fmt_gs(presupuesto_total - gasto_total)} disponibles.")
        elif pct >= 80:
            st.info(f"🟡 Vas al {pct}% del presupuesto. Empezá a planificar el resto del mes con cuidado.")
        else:
            st.success(f"🟢 Vas bien: {pct}% consumido, {_fmt_gs(presupuesto_total - gasto_total)} disponibles todavía.")

    # --- DESGLOSE POR CATEGORÍA (si está cargado) ---
    tiene_desglose = any(presu_mes.get(c, 0) > 0 for c in CATEGORIAS)
    if tiene_desglose:
        st.markdown("##### 📊 Desglose por categoría")
        for cat in CATEGORIAS:
            presu_cat = presu_mes.get(cat, 0)
            gasto_cat = gasto_mes.get(cat, 0)
            if presu_cat == 0:
                continue
            pct_cat = round((gasto_cat / presu_cat) * 100, 1)
            color_cat, icono_cat = _color_alerta(pct_cat)
            st.markdown(f"""
            <div class='industrial-panel'>
                <strong>{NOMBRES_CATEGORIA[cat]}</strong><br>
                <span>{_fmt_gs(gasto_cat)} de {_fmt_gs(presu_cat)} · <span style='color:{color_cat}; font-weight:bold;'>{icono_cat} {pct_cat}%</span></span>
            </div>
            """, unsafe_allow_html=True)

    # --- LUCRO CESANTE: referencia aparte, no forma parte del presupuesto ---
    if gasto_mes.get("lucro_cesante", 0):
        st.markdown("---")
        st.caption(
            f"ℹ️ Además, este mes se estima un **Lucro Cesante** (impacto en producción por paradas) "
            f"de {_fmt_gs(gasto_mes['lucro_cesante'])}. Es un indicador de impacto, no descuenta del "
            f"presupuesto de mantenimiento — te sirve para argumentar inversión en preventivo."
        )

    # --- HISTORIAL: PRESUPUESTO VS GASTO DE LOS ÚLTIMOS MESES ---
    st.markdown("---")
    st.subheader("📅 Historial Mensual")

    meses_historial = sorted(set(list(gasto_por_mes.keys()) + list(map_presupuesto.keys())), reverse=True)[:12]
    if not meses_historial:
        st.caption("Todavía no hay datos suficientes para mostrar un historial.")
    else:
        tabla = []
        for m in meses_historial:
            g = gasto_por_mes.get(m, {"mano_obra": 0, "repuestos": 0, "terceros": 0})
            p = map_presupuesto.get(m, {})
            gasto_m = g["mano_obra"] + g["repuestos"] + g["terceros"]
            presu_m = p.get("total", 0)
            desvio = gasto_m - presu_m if presu_m else None
            tabla.append({
                "Mes": datetime.strptime(m, "%Y-%m-%d").strftime("%B %Y").capitalize(),
                "Presupuestado": _fmt_gs(presu_m) if presu_m else "—",
                "Gastado": _fmt_gs(gasto_m),
                "Desvío": _fmt_gs(desvio) if desvio is not None else "—",
                "% Consumido": f"{round((gasto_m / presu_m) * 100, 1)}%" if presu_m else "—"
            })
        st.dataframe(tabla, use_container_width=True, hide_index=True)
