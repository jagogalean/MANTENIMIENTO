"""Técnicos: personal para asignar a OTs, con su costo hora-hombre."""
import streamlit as st

from database.conection import insert_tecnico, delete_tecnico, get_tecnicos, update_tecnico
from views import ui

TURNOS = ["Mañana", "Tarde", "Noche", "Rotativo"]


def _refrescar():
    st.session_state.tecnicos = get_tecnicos()


def render_tecnicos():
    cab, acc = st.columns([4, 1.2], vertical_alignment="bottom")
    with cab:
        ui.encabezado("Técnicos", "Personal que se asigna a las OTs. El costo hora-hombre se usa para el costo de mano de obra.")
    tecnicos = st.session_state.get("tecnicos", [])

    mensaje = st.session_state.pop("tec_mensaje", None)
    if mensaje:
        st.success(mensaje)

    with acc.popover("+ Nuevo técnico", use_container_width=True):
        with st.form("form_nuevo_tecnico", clear_on_submit=True):
            nombre = st.text_input("Nombre completo *")
            especialidad = st.text_input("Especialidad", placeholder="Eléctrico, mecánico, PLC")
            turno = st.selectbox("Turno", TURNOS)
            costo = st.number_input("Costo hora-hombre (Gs.)", min_value=0, step=1000)
            if st.form_submit_button("Guardar técnico", type="primary"):
                if not nombre.strip():
                    st.error("El nombre es obligatorio.")
                else:
                    insert_tecnico({"nombre": nombre.strip(), "especialidad": especialidad.strip(), "turno": turno,
                                    "costo_hora_hombre": costo})
                    _refrescar()
                    st.session_state["tec_mensaje"] = f"Técnico «{nombre.strip()}» agregado."
                    st.rerun()

    if not tecnicos:
        ui.estado_vacio("Todavía no hay técnicos cargados.", "Usá «+ Nuevo técnico».")
        return

    usados = {o.get("tecnico_id") for o in st.session_state.get("ots", [])}
    for t in tecnicos:
        tid = t.get("id")
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([3, 2, 2, 1.4], vertical_alignment="bottom")
            c1.markdown(f"**{ui.texto_md(t.get('nombre'))}**  \n:gray[{ui.texto_md(t.get('especialidad') or 'Sin especialidad')} · "
                        f"Turno {t.get('turno') or '—'}]")
            costo = c2.number_input("Costo hora-hombre (Gs.)", min_value=0, step=1000, value=int(t.get("costo_hora_hombre") or 0),
                                    key=f"costo_hh_{tid}")
            if c3.button("Guardar costo", key=f"save_costo_hh_{tid}", use_container_width=True,
                         disabled=costo == int(t.get("costo_hora_hombre") or 0)):
                update_tecnico(tid, {"costo_hora_hombre": costo})
                _refrescar()
                st.session_state["tec_mensaje"] = "Costo actualizado."
                st.rerun()
            with c4:
                aviso = "Tiene OTs asignadas: quedarían sin técnico. " if tid in usados else ""
                if ui.boton_confirmar("Quitar", f"del_tec_{tid}", aviso + f"¿Quitar a **{ui.texto_md(t.get('nombre'))}**?",
                                      texto_confirmar="Sí, quitar", use_container_width=True):
                    try:
                        delete_tecnico(tid)
                    except Exception as e:
                        ui.error_amigable("No se pudo quitar: tiene registros asociados.", e)
                    else:
                        _refrescar()
                        st.session_state["tec_mensaje"] = "Técnico quitado."
                        st.rerun()
