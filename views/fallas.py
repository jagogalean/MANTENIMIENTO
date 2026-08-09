import streamlit as st
from datetime import datetime
from database.conection import insert_falla, update_falla, get_fallas

def render_fallas():
    st.title("Fallas y Análisis de Causa Raíz (RCA)")
    
    if not st.session_state.maquinas:
        st.warning("Carga al menos una máquina antes de registrar fallas.")
        return

    # Vista de detalle de falla única para RCA
    if "falla_abierta_id" in st.session_state and st.session_state.falla_abierta_id:
        render_falla_detalle(st.session_state.falla_abierta_id)
        return

    # Formulario para registrar fallas
    if st.checkbox("+ Registrar Nueva Falla"):
        with st.form("form_nueva_falla", clear_on_submit=True):
            dict_m = {m["id"]: m["nombre"] for m in st.session_state.maquinas}
            maquina_id = st.selectbox("Seleccione la Máquina *", list(dict_m.keys()), format_func=lambda x: dict_m[x])
            fecha = st.date_input("Fecha", value=datetime.now().date()).strftime("%Y-%m-%d")
            tecnico = st.text_input("Técnico Asignado")
            sintomas = st.text_input("Síntomas Previos", placeholder="¿Hubo algún aviso antes?")
            descripcion = st.text_area("Descripción de la Falla *", placeholder="¿Qué ocurrió y qué daños se observan?")
            
            submit = st.form_submit_button("Registrar Falla")
            if submit:
                if not descripcion.strip():
                    st.error("La descripción es obligatoria.")
                else:
                    payload = {
                        "maquina_id": maquina_id, "fecha_deteccion": fecha, "tecnico": tecnico,
                        "sintomas": sintomas, "descripcion": descripcion, "estado": "Abierta",
                        "metodo_rca": None, "rca": {}, "causa_raiz": "", "accion": ""
                    }
                    insert_falla(payload)
                    st.session_state.fallas = get_fallas()
                    st.success("Falla registrada correctamente.")
                    st.rerun()

    # Tabla General de Control de Fallas
    st.markdown("<br>", unsafe_allow_html=True)
    if not st.session_state.fallas:
        st.info("No hay registros de fallas activos.")
    else:
        dict_m = {m["id"]: m["nombre"] for m in st.session_state.maquinas}
        for f in st.session_state.fallas:
            m_nombre = dict_m.get(f.get("maquina_id"), "Máquina Desconocida")
            
            col_t, col_b = st.columns([0.8, 0.2])
            with col_t:
                st.markdown(f"""
                <div class='industrial-panel'>
                    <strong>{m_nombre}</strong> — <small>{f.get('fecha_deteccion')}</small><br>
                    <span style='color: #C7CFD6;'>{(f.get('descripcion') or '')[:80]}...</span><br>
                    <span>Estado: <code>{f.get('estado')}</code></span>
                </div>
                """, unsafe_allow_html=True)
            with col_b:
                if st.button("🔍 Analizar / RCA", key=f"view_{f.get('id')}"):
                    st.session_state.falla_abierta_id = f.get("id")
                    st.rerun()

def render_falla_detalle(falla_id):
    falla = next((f for f in st.session_state.fallas if f["id"] == falla_id), None)
    if not falla:
        st.session_state.falla_abierta_id = None
        st.rerun()
        
    if st.button("⬅️ Volver al listado"):
        st.session_state.falla_abierta_id = None
        st.rerun()
        
    dict_m = {m["id"]: m for m in st.session_state.maquinas}
    m = dict_m.get(falla.get("maquina_id"), {})
    
    st.subheader(f"Análisis Falla: {m.get('nombre', '—')}")
    st.info(f"**Descripción:** {falla.get('descripcion')}\n\n**Fecha:** {falla.get('fecha_deteccion')} | **Técnico:** {falla.get('tecnico')}")
    
    # 1. Selección de metodología RCA
    metodo = falla.get("metodo_rca")
    if not metodo:
        st.write("### Seleccione el método de análisis de causa raíz")
        c1, c2 = st.columns(2)
        if c1.button("5 Porqués (Fallas Directas)"):
            update_falla(falla_id, {"metodo_rca": "5porques", "estado": "En análisis"})
            st.session_state.fallas = get_fallas()
            st.rerun()
        if c2.button("Ishikawa (6M - Complejas)"):
            update_falla(falla_id, {"metodo_rca": "ishikawa", "estado": "En análisis"})
            st.session_state.fallas = get_fallas()
            st.rerun()
            
    # 2. Renderizado dinámico de la estructura JSONB guardada en Supabase
    else:
        rca_data = falla.get("rca") or {}
        is_closed = falla.get("estado") == "Cerrada"
        
        with st.form("form_rca_execution"):
            st.write(f"### Análisis mediante: {metodo.upper()}")
            
            if metodo == "5porques":
                p1 = st.text_input("Por qué 1", value=rca_data.get("porque1", ""), disabled=is_closed)
                p2 = st.text_input("Por qué 2", value=rca_data.get("porque2", ""), disabled=is_closed)
                p3 = st.text_input("Por qué 3", value=rca_data.get("porque3", ""), disabled=is_closed)
                p4 = st.text_input("Por qué 4", value=rca_data.get("porque4", ""), disabled=is_closed)
                p5 = st.text_input("Por qué 5", value=rca_data.get("porque5", ""), disabled=is_closed)
                new_rca = {"porque1": p1, "porque2": p2, "porque3": p3, "porque4": p4, "porque5": p5}
            else:
                m1 = st.text_input("Método", value=rca_data.get("metodo", ""), disabled=is_closed)
                m2 = st.text_input("Máquina", value=rca_data.get("maquina", ""), disabled=is_closed)
                m3 = st.text_input("Mano de Obra", value=rca_data.get("manoObra", ""), disabled=is_closed)
                m4 = st.text_input("Material", value=rca_data.get("material", ""), disabled=is_closed)
                m5 = st.text_input("Medición", value=rca_data.get("medicion", ""), disabled=is_closed)
                m6 = st.text_input("Medio Ambiente", value=rca_data.get("medioAmbiente", ""), disabled=is_closed)
                new_rca = {"metodo": m1, "maquina": m2, "manoObra": m3, "material": m4, "medicion": m5, "medioAmbiente": m6}
                
            st.write("### Conclusión y Cierre de Orden")
            causa_raiz = st.text_area("Causa Raíz Identificada *", value=falla.get("causa_raiz", ""), disabled=is_closed)
            accion = st.text_area("Acción Correctiva / Preventiva *", value=falla.get("accion", ""), disabled=is_closed)
            
            if not is_closed:
                save_rca = st.form_submit_button("🔒 Cerrar Falla Definitivamente")
                if save_rca:
                    if not causa_raiz.strip() or not accion.strip():
                        st.error("Debe definir la causa raíz y las acciones correspondientes para el cierre.")
                    else:
                        patch = {"rca": new_rca, "causa_raiz": causa_raiz, "accion": accion, "estado": "Cerrada"}
                        update_falla(falla_id, patch)
                        st.session_state.fallas = get_fallas()
                        st.success("Falla analizada y archivada correctamente.")
                        st.session_state.falla_abierta_id = None
                        st.rerun()
            else:
                st.success("✅ Esta falla se encuentra actualmente Cerrada.")
