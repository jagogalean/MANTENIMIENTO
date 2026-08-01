import streamlit as st
from database.conection import insert_maquina, delete_maquina, get_maquinas

CRIT_LABELS = {"A": "🔴 Crítica", "B": "🟠 Importante", "C": "🔵 Menor"}

def render_maquinas():
    st.title("Máquinas")
    st.write("Inventario base y criticidad operacional.")
    
    # Formulario desplegable mediante checkbox de Streamlit
    if st.checkbox("+ Nueva Máquina"):
        with st.form("form_nueva_maquina", clear_on_submit=True):
            nombre = st.text_input("Nombre / Tag *", placeholder="Ej: Extrusora 02")
            codigo = st.text_input("Código Único *", placeholder="Ej: EXT-002")
            seccion = st.text_input("Sección / Área", placeholder="Ej: Planta A - Línea 2")
            criticidad = st.selectbox("Criticidad", ["A", "B", "C"], format_func=lambda x: CRIT_LABELS[x])
            
            submit = st.form_submit_button("Guardar Máquina")
            if submit:
                if not nombre.strip() or not codigo.strip():
                    st.error("El nombre y el código de la máquina son obligatorios.")
                else:
                    # El ID no se envía en el payload ya que Supabase lo genera automáticamente como BIGINT
                    payload = {
                        "nombre": nombre,
                        "codigo": codigo,
                        "seccion": seccion,
                        "criticidad": criticidad
                    }
                    insert_maquina(payload)
                    st.session_state.maquinas = get_maquinas()
                    st.success(f"Máquina '{nombre}' guardada con éxito.")
                    st.rerun()

    # Listado en Interfaz Industrial
    st.markdown("<br>", unsafe_allow_html=True)
    if not st.session_state.maquinas:
        st.info("Todavía no has cargado ninguna máquina.")
    else:
        for m in st.session_state.maquinas:
            col_info, col_action = st.columns([0.85, 0.15])
            with col_info:
                st.markdown(f"""
                <div class='industrial-panel'>
                    <strong>{m.get('nombre')}</strong> <small style='color:#38BDF8;'>[{m.get('codigo')}]</small> — 
                    <small style='color:#7C8894;'>{m.get('seccion') or 'sin sección'}</small><br>
                    <span>Criticidad: {CRIT_LABELS.get(m.get('criticidad'), m.get('criticidad'))}</span>
                </div>
                """, unsafe_allow_html=True)
            with col_action:
                # Se utiliza el ID numérico de Supabase para la clave del botón
                if st.button("🗑️ Eliminar", key=f"del_m_{m.get('id')}"):
                    delete_maquina(m.get('id'))
                    st.session_state.maquinas = get_maquinas()
                    st.rerun()