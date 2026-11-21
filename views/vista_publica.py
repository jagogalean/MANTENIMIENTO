"""
Ficha pública de una máquina (se abre al escanear su QR, sin iniciar sesión).
Pensada para el celular: equipo, aviso de falla con botones grandes y
próximo preventivo. Todo dato que viene de la base se muestra escapado.
"""
import streamlit as st

from database.conection_publica import get_ficha_publica_equipo, get_planes_publico_equipo, insertar_solicitud_falla
from database.ots_servicio import con_marca_parada
from views import ui

URGENCIA = {"Puede esperar": "Baja", "Hoy": "Media", "Ya mismo": "Alta"}


def render_vista_publica(equipo_id):
    st.caption("VITOPEL · MANTENIMIENTO")
    st.title("Avisar una falla")

    try:
        equipo = get_ficha_publica_equipo(equipo_id)
    except Exception as e:
        ui.error_amigable("No se pudo cargar la ficha del equipo. Avisá directamente a mantenimiento.", e)
        equipo = None

    if not equipo:
        st.error("No encontramos este equipo. Revisá el código QR o avisá directamente a mantenimiento.")
    else:
        with st.container(border=True):
            st.markdown(f"**{ui.texto_md(equipo.get('nombre'))}**")
            st.caption(f"Ubicación: {ui.texto_md(equipo.get('ubicacion') or 'no especificada')}")

    enviado = st.session_state.pop("publico_enviado", False)
    if enviado:
        st.success("Aviso enviado. Mantenimiento lo va a revisar. Gracias.")

    if equipo:
        with st.form("form_reporte_publico", clear_on_submit=True):
            descripcion = st.text_area("¿Qué está pasando? *", placeholder="Ej.: ruido fuerte en el motor, pierde aceite, no arranca")
            parada = st.radio("¿La máquina está parada?", ["No, sigue andando", "Sí, está parada"], horizontal=True)
            urgencia = st.radio("¿Qué tan urgente es?", list(URGENCIA.keys()), index=1, horizontal=True)
            operario = st.text_input("Tu nombre", placeholder="Nombre y apellido (opcional)")
            enviar = st.form_submit_button("Enviar aviso", type="primary", use_container_width=True)
        if enviar:
            if not (descripcion or "").strip():
                st.error("Contá qué está pasando antes de enviar.")
            else:
                try:
                    insertar_solicitud_falla({
                        "equipo_id": equipo_id,
                        "operario": (operario or "").strip() or None,
                        "descripcion": con_marca_parada(descripcion.strip()[:1000], parada.startswith("Sí")),
                        "prioridad": URGENCIA[urgencia],
                        "fecha_reporte": ui.ahora().isoformat(),
                    })
                except Exception as e:
                    ui.error_amigable("No se pudo enviar el aviso. Probá de nuevo o avisá directamente a mantenimiento.", e)
                else:
                    st.session_state["publico_enviado"] = True
                    st.rerun()

        try:
            planes = get_planes_publico_equipo(equipo_id)
        except Exception:
            planes = []
        if planes:
            with st.expander("Mantenimiento preventivo de este equipo"):
                for p in planes:
                    st.markdown(f"**{ui.texto_md(p.get('nombre_plan'))}** · cada {p.get('frecuencia_dias')} días  \n"
                                f"Último: {ui.fecha_corta(p.get('ultima_ejecucion'))} · "
                                f"Próximo: {ui.fecha_corta(p.get('proxima_ejecucion'))}")

    st.write("")
    if st.button("Acceso del personal", type="tertiary"):
        st.session_state["forzar_login_admin"] = True
        st.rerun()
