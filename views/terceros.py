import streamlit as st
from database.conection import insert_tercero, delete_tercero, get_terceros

def render_terceros():
    st.title("Terceros y Contratos Externos")
    st.write("Seguimiento a vencimientos de calibraciones o asistencias técnicas externas.")

    if st.checkbox("+ Registrar Equipo / Proveedor Externo"):
        with st.form("form_terceros", clear_on_submit=True):
            nombre = st.text_input("Equipo / Nombre del Servicio *", placeholder="Ej: Caldera de Vapor Central")
            contacto = st.text_input("Empresa Proveedora / Contacto")
            servicio = st.text_input("Tipo de Servicio", placeholder="Ej: Calibración, Mantenimiento externo")
            proximo_venc = st.date_input("Próximo Vencimiento / Calibración").strftime("%Y-%m-%d")

            submit = st.form_submit_button("Guardar Registro Técnico")
            if submit:
                if not nombre.strip():
                    st.error("El nombre del equipo es mandatorio.")
                else:
                    payload = {
                        "nombre": nombre,
                        "contacto": contacto,
                        "servicio": servicio,
                        "proximoVencimiento": proximo_venc
                    }
                    insert_tercero(payload)
                    st.session_state.terceros = get_terceros()
                    st.success("Registro de contratista almacenado.")
                    st.rerun()

    # Despliegue de Elementos
    st.markdown("<br>", unsafe_allow_html=True)
    if not st.session_state.terceros:
        st.info("Sin registros de soporte externo.")
    else:
        for t in st.session_state.terceros:
            col_d, col_a = st.columns([0.85, 0.15])
            with col_d:
                st.markdown(f"""
                <div class='industrial-panel'>
                    <strong>{t.get('nombre')}</strong> — <small>Proveedor: {t.get('contacto') or '—'}</small>
                    {f" · <small style='color:#7C8894;'>{t.get('servicio')}</small>" if t.get('servicio') else ""}<br>
                    <span style='color: #F2A93B;'>Próxima Intervención: {t.get('proximoVencimiento')}</span>
                </div>
                """, unsafe_allow_html=True)
            with col_a:
                if st.button("🗑️ Quitar", key=f"del_t_{t.get('id')}"):
                    delete_tercero(t.get('id'))
                    st.session_state.terceros = get_terceros()
                    st.rerun()
