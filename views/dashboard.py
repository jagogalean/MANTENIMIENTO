import streamlit as st
from datetime import datetime

def days_until(date_str):
    if not date_str: return None
    try:
        diff = datetime.strptime(date_str, "%Y-%m-%d").date() - datetime.date(datetime.now())
        return diff.days
    except:
        return None

def calcular_kpis_industriales(maquinas, fallas, ots):
    total_maquinas = len(maquinas)
    
    # 1. MTTR: Promedio de horas que toman las OTs Correctivas Completadas
    ots_correctivas = [o for o in ots if o.get("tipo_mantenimiento") == "Correctivo" and o.get("estado") == "Completada"]
    horas_totales_reparacion = 0
    
    for ot in ots_correctivas:
        fi = ot.get("fecha_inicio")
        ff = ot.get("fecha_fin")
        if fi and ff:
            try:
                # Soporta formatos ISO con o sin zona horaria de Supabase
                dt_fi = datetime.fromisoformat(fi.replace("Z", "+00:00"))
                dt_ff = datetime.fromisoformat(ff.replace("Z", "+00:00"))
                horas_totales_reparacion += (dt_ff - dt_fi).total_seconds() / 3600
            except:
                pass
                
    mttr = round(horas_totales_reparacion / len(ots_correctivas), 1) if ots_correctivas else 0.0

    # 2. MTBF & Disponibilidad Operacional
    # Basado en un periodo estándar de 720 horas operativas al mes por activo
    horas_periodo_planta = 720 * max(total_maquinas, 1)
    horas_paro_totales = sum([float(o.get("horas_paro") or 0) for o in ots])
    
    # MTBF: Tiempo total operado dividido el número de fallas registradas
    fallas_totales = len(fallas)
    tiempo_operacion = horas_periodo_planta - horas_paro_totales
    
    if fallas_totales > 0:
        mtbf = round(tiempo_operacion / fallas_totales, 1) if tiempo_operacion > 0 else 0.0
    else:
        mtbf = 720.0 # Con cero fallas, el tiempo entre fallas es el periodo completo
        
    # Disponibilidad: Relación del tiempo real operado frente al teórico esperado
    if horas_periodo_planta > 0:
        disponibilidad = round((tiempo_operacion / horas_periodo_planta) * 100, 1)
    else:
        disponibilidad = 100.0
        
    return {
        "mttr": mttr,
        "mtbf": mtbf,
        "disponibilidad": disponibilidad,
        "horas_paro": horas_paro_totales
    }

def calcular_ranking_maquinas(maquinas, ots, ot_repuestos, repuestos):
    """Top máquinas por costo total (mano de obra + repuestos) y horas de paro."""
    map_maquina = {m["id"]: m["nombre"] for m in maquinas}
    map_costo_repuesto = {r["id"]: r.get("costo_unitario", 0) for r in repuestos}

    costo_repuestos_por_ot = {}
    for orr in ot_repuestos:
        ot_id = orr.get("ot_id")
        costo = orr.get("cantidad_usada", 0) * map_costo_repuesto.get(orr.get("repuesto_id"), 0)
        costo_repuestos_por_ot[ot_id] = costo_repuestos_por_ot.get(ot_id, 0) + costo

    acumulado = {}
    for o in ots:
        m_id = o.get("maquina_id")
        m_nombre = map_maquina.get(m_id, "Desconocida")
        if m_nombre not in acumulado:
            acumulado[m_nombre] = {"nombre": m_nombre, "costo_total": 0, "horas_paro": 0}
        acumulado[m_nombre]["costo_total"] += (o.get("costo_mano_obra", 0) or 0) + costo_repuestos_por_ot.get(o.get("id"), 0)
        acumulado[m_nombre]["horas_paro"] += o.get("horas_paro", 0) or 0

    ranking = sorted(acumulado.values(), key=lambda x: x["costo_total"], reverse=True)
    return ranking[:5]


def render_dashboard():
    st.title("Panel General")
    st.subheader("Indicadores clave de fiabilidad y estado del plan de mantenimiento.")
    
    # Recuperación segura del estado de sesión
    maquinas = st.session_state.get("maquinas", [])
    fallas = st.session_state.get("fallas", [])
    terceros = st.session_state.get("terceros", [])
    ots = st.session_state.get("ots", [])
    
    abiertas = [f for f in fallas if f.get("estado") != "Cerrada"]
    dict_maquinas = {m["id"]: m for m in maquinas}
    
    # Filtrar fallas críticas abiertas basándose en la criticidad 'A' de la máquina vinculada
    crit_abiertas = [f for f in abiertas if dict_maquinas.get(f.get("maquina_id"), {}).get("criticidad") == "A"]
    
    # Alertas de vencimiento de terceros
    vencidos = [t for t in terceros if days_until(t.get("proximoVencimiento")) is not None and days_until(t.get("proximoVencimiento")) < 0]
    proximos = [t for t in terceros if days_until(t.get("proximoVencimiento")) is not None and 0 <= days_until(t.get("proximoVencimiento")) <= 30]
    
    # Procesamiento de métricas avanzadas
    kpis = calcular_kpis_industriales(maquinas, fallas, ots)
    ot_repuestos = st.session_state.get("ot_repuestos", [])
    repuestos = st.session_state.get("repuestos", [])
    ranking_maquinas = calcular_ranking_maquinas(maquinas, ots, ot_repuestos, repuestos)
    
    # --- FILA SUPERIOR: MÓDULOS DEL NEGOCIO ---
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Máquinas Registradas", len(maquinas))
    col2.metric("Fallas Abiertas", len(abiertas))
    col3.metric("Críticas sin Cerrar", len(crit_abiertas))
    col4.metric("Vencimientos ≤30 días", len(proximos) + len(vencidos))
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # --- FILA CENTRAL: KPIS DE FIABILIDAD MANTENIMIENTO ---
    st.markdown("### 📊 Indicadores de Control Operacional (KPIs)")
    kpi_col1, kpi_col2, kpi_col3, kpi_col4 = st.columns(4)
    
    with kpi_col1:
        st.markdown(f"""
        <div class='industrial-panel' style='text-align: center;'>
            <small style='color: #7C8894; font-weight: bold;'>DISPONIBILIDAD</small>
            <h2 style='color: #10B981; margin: 8px 0;'>{kpis['disponibilidad']}%</h2>
            <small style='color: #5A6570;'>Tiempo operativo</small>
        </div>
        """, unsafe_allow_html=True)
        
    with kpi_col2:
        color_mttr = "#EF4444" if kpis['mttr'] > 4.0 else "#38BDF8"
        st.markdown(f"""
        <div class='industrial-panel' style='text-align: center;'>
            <small style='color: #7C8894; font-weight: bold;'>MTTR</small>
            <h2 style='color: {color_mttr}; margin: 8px 0;'>{kpis['mttr']} hrs</h2>
            <small style='color: #5A6570;'>Tiempo medio de reparación</small>
        </div>
        """, unsafe_allow_html=True)
        
    with kpi_col3:
        st.markdown(f"""
        <div class='industrial-panel' style='text-align: center;'>
            <small style='color: #7C8894; font-weight: bold;'>MTBF</small>
            <h2 style='color: #F59E0B; margin: 8px 0;'>{kpis['mtbf']} hrs</h2>
            <small style='color: #5A6570;'>Tiempo medio entre fallas</small>
        </div>
        """, unsafe_allow_html=True)
        
    with kpi_col4:
        st.markdown(f"""
        <div class='industrial-panel' style='text-align: center;'>
            <small style='color: #7C8894; font-weight: bold;'>TIEMPO TOTAL DE PARO</small>
            <h2 style='color: #E5E9EC; margin: 8px 0;'>{kpis['horas_paro']} hrs</h2>
            <small style='color: #5A6570;'>Acumulado horas muerto</small>
        </div>
        """, unsafe_allow_html=True)
        
    st.markdown("<br>", unsafe_allow_html=True)
    
    # --- FILA INFERIOR: BLOQUES COMPLEMENTARIOS ---
    c_left, c_right = st.columns(2)
    
    with c_left:
        st.markdown("<div class='industrial-panel'>", unsafe_allow_html=True)
        st.markdown("<h4>Fallas Críticas Abiertas (Activos A)</h4>", unsafe_allow_html=True)
        if not crit_abiertas:
            st.text("Sin fallas críticas pendientes en máquinas prioritarias.")
        else:
            for f in crit_abiertas[:5]:
                m_nom = dict_maquinas.get(f.get("maquina_id"), {}).get("nombre", "⚠️ Desconocida")
                st.markdown(f"🚨 **{m_nom}**: {f.get('descripcion')[:40]}...")
        st.markdown("</div>", unsafe_allow_html=True)
        
    with c_right:
        st.markdown("<div class='industrial-panel'>", unsafe_allow_html=True)
        st.markdown("<h4>Alertas y Contratos de Terceros</h4>", unsafe_allow_html=True)
        all_venc = vencidos + proximos
        if not all_venc:
            st.text("Sin vencimientos próximos en contratos de servicio.")
        else:
            for t in all_venc[:5]:
                d = days_until(t.get("proximoVencimiento"))
                lbl = f"Vencido hace {-d}d" if d < 0 else f"En {d}d"
                color_lbl = "#EF4444" if d < 0 else "#F59E0B"
                st.markdown(f"📦 **{t.get('nombre')}** ({t.get('servicio') or 'Soporte'}) — <span style='color:{color_lbl}; font-weight:bold;'>{lbl}</span>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    # --- RANKING: MÁQUINAS QUE MÁS CONSUMEN RECURSOS ---
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### 💰 Top Máquinas por Costo y Paro Acumulado")
    if not ranking_maquinas:
        st.info("Todavía no hay costos ni horas de paro registrados en OTs.")
    else:
        for r in ranking_maquinas:
            st.markdown(f"""
            <div class='industrial-panel'>
                <strong>{r['nombre']}</strong><br>
                <span>Costo acumulado: <strong>${r['costo_total']:,.2f}</strong> · Horas de paro: <strong>{r['horas_paro']}</strong></span>
            </div>
            """, unsafe_allow_html=True)
