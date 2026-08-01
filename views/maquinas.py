import streamlit as st
import qrcode
from io import BytesIO
from database.conection import insert_maquina, delete_maquina, get_maquinas, insert_documento, delete_documento, get_documentos

CRIT_LABELS = {"A": "🔴 Crítica", "B": "🟠 Importante", "C": "🔵 Menor"}


def generar_qr_png(url: str) -> bytes:
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def render_maquinas():
    st.title("Máquinas")
    st.write("Inventario base y criticidad operacional.")

    with st.expander("⚙️ Configurar URL de la app (para los QR de Recepción/Entrega)"):
        st.session_state["app_base_url"] = st.text_input(
            "URL pública de tu app en Streamlit Cloud",
            value=st.session_state.get("app_base_url", ""),
            placeholder="https://tu-app.streamlit.app"
        )
        st.caption("Se necesita una sola vez. Es la URL que ves en el navegador cuando abrís tu app ya desplegada.")
    
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

            # --- DOCUMENTACIÓN TÉCNICA (manuales, planos, fichas) ---
            docs_maquina = [d for d in st.session_state.get("documentos", []) if d.get("maquina_id") == m.get("id")]
            with st.expander(f"📎 Documentos técnicos ({len(docs_maquina)})"):
                if docs_maquina:
                    for d in docs_maquina:
                        col_d, col_x = st.columns([0.85, 0.15])
                        col_d.markdown(f"[{d.get('nombre_archivo')}]({d.get('url')}) · {d.get('tipo') or 'General'}")
                        if col_x.button("🗑️", key=f"del_doc_{d.get('id')}"):
                            delete_documento(d.get('id'))
                            st.session_state.documentos = get_documentos()
                            st.rerun()
                else:
                    st.caption("Sin documentos cargados todavía.")

                with st.form(f"form_doc_{m.get('id')}", clear_on_submit=True):
                    nombre_doc = st.text_input("Nombre del documento", placeholder="Ej: Manual eléctrico Extrusora 02")
                    url_doc = st.text_input("Link (Google Drive, OneDrive, etc.)")
                    tipo_doc = st.selectbox("Tipo", ["Manual", "Plano", "Ficha Técnica", "Foto", "Otro"], key=f"tipo_doc_{m.get('id')}")
                    if st.form_submit_button("Adjuntar documento"):
                        if not nombre_doc.strip() or not url_doc.strip():
                            st.error("❌ Nombre y link son obligatorios.")
                        else:
                            insert_documento({
                                "maquina_id": m.get("id"),
                                "nombre_archivo": nombre_doc,
                                "url": url_doc,
                                "tipo": tipo_doc
                            })
                            st.session_state.documentos = get_documentos()
                            st.success("✅ Documento adjuntado.")
                            st.rerun()

            # --- QR PARA RECEPCIÓN / ENTREGA DESDE LA MÁQUINA ---
            with st.expander("📱 Código QR de Recepción / Entrega"):
                base_url = st.session_state.get("app_base_url", "")
                if not base_url:
                    st.warning("Configurá la URL de tu app arriba (⚙️ Configurar URL) para poder generar el QR.")
                else:
                    url_qr = f"{base_url.rstrip('/')}/?maquina_id={m.get('id')}&vista=checklist"
                    qr_bytes = generar_qr_png(url_qr)
                    st.image(qr_bytes, caption=f"Escanear para Recepción/Entrega de {m.get('nombre')}", width=200)
                    st.code(url_qr, language=None)
                    st.download_button(
                        "⬇️ Descargar QR (PNG)",
                        data=qr_bytes,
                        file_name=f"QR_{m.get('codigo')}.png",
                        mime="image/png",
                        key=f"dl_qr_{m.get('id')}"
                    )
