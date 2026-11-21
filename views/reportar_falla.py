"""
Reportar falla: la pantalla del operador (con usuario).
El aviso crea una OT correctiva sin asignar en el backlog compartido.
"""
import streamlit as st

from database.conection import get_maquinas_cached
from database import ots_servicio as S
from views import ui


def render_reportar_falla(usuario):
    ui.encabezado("Reportar falla", "Tu aviso llega directo a mantenimiento como una orden de trabajo.")

    mensaje = st.session_state.pop("reporte_mensaje", None)
    if mensaje:
        st.success(mensaje)

    maquinas = get_maquinas_cached()
    if not maquinas:
        st.warning("Todavía no hay máquinas cargadas. Avisale al coordinador de mantenimiento.")
        return
    mapa = {m["id"]: m for m in sorted(maquinas, key=lambda m: str(m.get("nombre")).casefold())}

    with st.form("form_reporte_operador", clear_on_submit=True):
        maquina_id = st.selectbox("Máquina *", list(mapa.keys()), index=None, placeholder="Escribí para buscar la máquina",
                                  format_func=lambda i: mapa[i]["nombre"])
        descripcion = st.text_area("¿Qué está pasando? *",
                                   placeholder="Ej.: ruido fuerte en el motor, olor a quemado, se detuvo sola")
        parada = st.radio("¿La máquina está parada?", ["No, sigue andando", "Sí, está parada"], horizontal=True)
        enviar = st.form_submit_button("Enviar aviso", type="primary", use_container_width=True)

    if enviar:
        if maquina_id is None or not (descripcion or "").strip():
            st.error("Elegí la máquina y contá qué pasa.")
            return
        esta_parada = parada.startswith("Sí")
        try:
            codigo, _ = S.crear_ot({
                "maquina_id": maquina_id,
                "tipo_mantenimiento": "Correctivo",
                "descripcion": S.con_marca_parada(f"[Aviso de {usuario.get('nombre') or 'operador'}] {descripcion.strip()}",
                                                  esta_parada),
                "estado": "Pendiente",
                "tecnico_id": None,
                "origen": "operador",
            })
        except Exception as e:
            ui.error_amigable("No se pudo enviar el aviso. Probá de nuevo o avisá a tu supervisor.", e)
            return
        texto = f"Aviso enviado ({codigo}). Mantenimiento ya lo ve en su lista."
        if esta_parada:
            texto += " Como la máquina está parada, avisá también a tu supervisor."
        st.session_state["reporte_mensaje"] = texto
        st.rerun()
