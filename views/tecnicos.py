import streamlit as st
from database.conection import insert_tecnico, delete_tecnico, get_tecnicos, update_tecnico


def render_tecnicos():
    st.title("👷 Técnicos / Cuadrillas")
    st.write("Personal disponible para asignar a Órdenes de Trabajo.")

    tecnicos = st.session_state.get("tecnicos", [])

    if st.checkbox("+ Nuevo Técnico"):
        with st.form("form_nuevo_tecnico", clear_on_submit=True):
            nombre = st.text_input("Nombre completo *", placeholder="Ej: Carlos Benítez")
            especialidad = st.text_input("Especialidad", placeholder="Ej: Electricista, Mecánico, PLC")
            turno = st.selectbox("Turno", ["Mañana", "Tarde", "Noche", "Rotativo"])
            costo_hora_hombre = st.number_input("Costo Hora-Hombre (Gs.)", min_value=0, step=1000, value=0,
                                                 help="Se usa para calcular el costo de mano de obra en OTs internas.")

            submit = st.form_submit_button("Guardar Técnico")
            if submit:
                if not nombre.strip():
                    st.error("❌ El nombre es obligatorio.")
                else:
                    insert_tecnico({
                        "nombre": nombre, "especialidad": especialidad, "turno": turno,
                        "costo_hora_hombre": costo_hora_hombre
                    })
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
                costo_hh = t.get("costo_hora_hombre", 0) or 0
                costo_hh_fmt = f"{costo_hh:,.0f}".replace(",", ".")
                st.markdown(f"""
                <div class='industrial-panel'>
                    <strong>{t.get('nombre')}</strong> — <small style='color:#38BDF8;'>{t.get('especialidad') or 'Sin especialidad definida'}</small><br>
                    <span>Turno: {t.get('turno')} · Costo Hora-Hombre: Gs. {costo_hh_fmt}</span>
                </div>
                """, unsafe_allow_html=True)
            with col_a:
                if st.button("🗑️ Quitar", key=f"del_tec_{t.get('id')}"):
                    delete_tecnico(t.get('id'))
                    st.session_state.tecnicos = get_tecnicos()
                    st.rerun()

            with st.expander(f"💰 Editar costo hora-hombre de {t.get('nombre')}"):
                nuevo_costo = st.number_input(
                    "Costo Hora-Hombre (Gs.)", min_value=0, step=1000,
                    value=int(t.get("costo_hora_hombre", 0) or 0),
                    key=f"costo_hh_{t.get('id')}"
                )
                if st.button("💾 Guardar", key=f"save_costo_hh_{t.get('id')}"):
                    update_tecnico(t.get("id"), {"costo_hora_hombre": nuevo_costo})
                    st.session_state.tecnicos = get_tecnicos()
                    st.success("✅ Costo actualizado.")
                    st.rerun()
