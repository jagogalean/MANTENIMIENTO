import streamlit as st
from datetime import datetime
from database.conection_publica import get_ficha_publica_equipo, insertar_solicitud_falla


def _fmt_fecha(fecha_str):
    if not fecha_str:
        return "No hay uno programado"
    try:
        return datetime.strptime(fecha_str, "%Y-%m-%d").strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return fecha_str


def render_vista_publica(equipo_id):
    """
    Pantalla pública que se muestra cuando alguien escanea el QR de una
    máquina (URL con ?equipo=ID). No requiere iniciar sesión.
    """
    st.markdown(
        "<div style='color:#38BDF8; font-family:monospace; font-size:16px; font-weight:bold; "
        "letter-spacing:2px;'>⚙️ MANTENIMIENTO — Ficha del Equipo</div>",
        unsafe_allow_html=True
    )
    st.markdown("<br>", unsafe_allow_html=True)

    equipo = get_ficha_publica_equipo(equipo_id)

    if not equipo:
        st.error(f"❌ No se encontró ningún equipo con el ID **{equipo_id}**. Verificá el código QR o avisale directamente a mantenimiento.")
    else:
        st.markdown(f"""
        <div class='industrial-panel'>
            <h3 style='margin-top:0; color:#E5E9EC;'>{equipo.get('nombre')}</h3>
            <span>🏷️ <strong>ID:</strong> {equipo.get('id')}</span><br>
            <span>📍 <strong>Ubicación:</strong> {equipo.get('ubicacion') or 'No especificada'}</span><br>
            <span>🛠️ <strong>Último preventivo:</strong> {_fmt_fecha(equipo.get('ultimo_preventivo'))}</span><br>
            <span>🗓️ <strong>Próximo preventivo:</strong> {_fmt_fecha(equipo.get('proximo_preventivo'))}</span>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")
    st.subheader("🚨 Reportar Avería / Falla")
    st.caption("Contanos qué está pasando con esta máquina. No hace falta iniciar sesión.")

    with st.form("form_reporte_publico", clear_on_submit=True):
        operario = st.text_input("Tu nombre / sector (opcional)", placeholder="Ej: Juan - Línea 2")
        descripcion = st.text_area("Descripción del problema *", placeholder="¿Qué está pasando? Ruido, olor, parada, vibración, etc.")
        prioridad = st.selectbox("Prioridad", ["Baja", "Media", "Alta"], index=1)

        submit = st.form_submit_button("📨 Enviar Reporte")
        if submit:
            if not descripcion.strip():
                st.error("❌ Describí el problema antes de enviar.")
            elif not equipo:
                st.error("❌ No se puede reportar: no se encontró el equipo.")
            else:
                try:
                    insertar_solicitud_falla({
                        "equipo_id": equipo_id,
                        "operario": operario.strip() or None,
                        "descripcion": descripcion.strip(),
                        "prioridad": prioridad,
                        "fecha_reporte": datetime.now().isoformat()
                    })
                    st.success("✅ Reporte enviado correctamente. El equipo de mantenimiento lo va a revisar.")
                except Exception as e:
                    st.error(f"❌ No se pudo enviar el reporte. Intentá de nuevo o avisá directamente a mantenimiento. ({e})")

    st.markdown("---")
    col_a, col_b, col_c = st.columns([0.3, 0.4, 0.3])
    with col_b:
        if st.button("🔐 Acceso Administrativo / Iniciar Sesión", use_container_width=True):
            # Esta bandera hace que app.py ignore el parámetro ?equipo= de la URL
            # y muestre la pantalla de login normal, sin perder el contexto.
            st.session_state["forzar_login_admin"] = True
            st.rerun()
