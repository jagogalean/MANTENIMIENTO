import streamlit as st
from database.conection import insert_tercero, delete_tercero, get_terceros

def render_terceros():
    st.title("🚚 Terceros y Proveedores")
    st.write("Empresas externas: contratos con vencimiento (calibraciones, mantenimiento) y proveedores que facturan OTs.")

    if st.checkbox("+ Registrar Tercero / Proveedor"):
        with st.form("form_terceros", clear_on_submit=True):
            nombre = st.text_input("Equipo / Nombre del Servicio *", placeholder="Ej: Caldera de Vapor Central (o el nombre de la empresa, si es solo un proveedor)")
            contacto = st.text_input("Empresa Proveedora / Contacto *", placeholder="Ej: Servicios Industriales SA")
            ruc = st.text_input("RUC", placeholder="Ej: 80012345-6")
            servicio = st.text_input("Tipo de Servicio", placeholder="Ej: Calibración, Mantenimiento externo")

            tiene_vencimiento = st.checkbox("¿Este servicio tiene fecha de vencimiento/renovación?", value=True)
            proximo_venc = None
            if tiene_vencimiento:
                proximo_venc = st.date_input("Próximo Vencimiento / Calibración").strftime("%Y-%m-%d")

            submit = st.form_submit_button("Guardar Registro")
            if submit:
                if not nombre.strip() or not contacto.strip():
                    st.error("El nombre y la empresa/contacto son obligatorios.")
                else:
                    payload = {
                        "nombre": nombre,
                        "contacto": contacto,
                        "ruc": ruc,
                        "servicio": servicio,
                        "proximoVencimiento": proximo_venc
                    }
                    insert_tercero(payload)
                    st.session_state.terceros = get_terceros()
                    st.success("Registro almacenado.")
                    st.rerun()

    # Despliegue de Elementos
    st.markdown("<br>", unsafe_allow_html=True)
    if not st.session_state.terceros:
        st.info("Sin registros de terceros/proveedores.")
    else:
        for t in st.session_state.terceros:
            col_d, col_a = st.columns([0.85, 0.15])
            with col_d:
                venc_txt = f"<span style='color: #F2A93B;'>Próxima Intervención: {t.get('proximoVencimiento')}</span>" if t.get("proximoVencimiento") else "<span style='color: #7C8894;'>Sin vencimiento asociado</span>"
                st.markdown(f"""
                <div class='industrial-panel'>
                    <strong>{t.get('nombre')}</strong> — <small>Proveedor: {t.get('contacto') or '—'}</small>
                    {f" · <small style='color:#7C8894;'>RUC: {t.get('ruc')}</small>" if t.get('ruc') else ""}
                    {f" · <small style='color:#7C8894;'>{t.get('servicio')}</small>" if t.get('servicio') else ""}<br>
                    {venc_txt}
                </div>
                """, unsafe_allow_html=True)
            with col_a:
                if st.button("🗑️ Quitar", key=f"del_t_{t.get('id')}"):
                    delete_tercero(t.get('id'))
                    st.session_state.terceros = get_terceros()
                    st.rerun()
