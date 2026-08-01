import streamlit as st
from database.conection import insert_tecnico, delete_tecnico, get_tecnicos


def render_tecnicos():
    st.title("👷 Técnicos / Cuadrillas")
    st.write("Personal disponible para asignar a Órdenes de Trabajo.")

    tecnicos = st.session_state.get("tecnicos", [])

    if st.checkbox("+ Nuevo Técnico"):
        with st.form("form_nuevo_tecnico", clear_on_submit=True):
            nombre = st.text_input("Nombre completo *", placeholder="Ej: Carlos Benítez")
            especialidad = st.text_input("Especialidad", placeholder="Ej: Electricista, Mecánico, PLC")
            turno = st.selectbox("Turno", ["Mañana", "Tarde", "Noche", "Rotativo"])

            submit = st.form_submit_button("Guardar Técnico")
            if submit:
                if not nombre.strip():
                    st.error("❌ El nombre es obligatorio.")
                else:
                    insert_tecnico({"nombre": nombre, "especialidad": especialidad, "turno": turno})
                    st.session_state.tecnicos = get_tecnicos()
                    st.success(f"✅ Técnico '{nombre}' agregado correctamente.")
                    st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)
    if not tecnicos:
        st.info("Todavía no hay técnicos registrados.")
    else:
        for t in tecnicos:
            col_i, col_a = st.columns([0.85, 0.15])
            with col_i:
                st.markdown(f"""
                <div class='industrial-panel'>
                    <strong>{t.get('nombre')}</strong> — <small style='color:#38BDF8;'>{t.get('especialidad') or 'Sin especialidad definida'}</small><br>
                    <span>Turno: {t.get('turno')}</span>
                </div>
                """, unsafe_allow_html=True)
            with col_a:
                if st.button("🗑️ Quitar", key=f"del_tec_{t.get('id')}"):
                    delete_tecnico(t.get('id'))
                    st.session_state.tecnicos = get_tecnicos()
                    st.rerun()