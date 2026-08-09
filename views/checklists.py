import streamlit as st
from datetime import datetime
from database.conection import insert_checklist, delete_checklist, get_checklists

def render_checklists():
    st.title("Recepción / Entrega de Máquina")
    st.write("Checklists Operacionales de primer nivel.")
    
    if not st.session_state.maquinas:
        st.warning("Carga al menos una máquina primero.")
        return

    # Si se llegó acá escaneando el QR de una máquina, saltar directo al formulario
    qr_maquina_id_raw = st.session_state.get("qr_maquina_id")
    viene_de_qr = qr_maquina_id_raw is not None

    mostrar_form = st.checkbox("+ Nuevo Registro de Turno", value=viene_de_qr)
    if mostrar_form:
        with st.form("form_checklist", clear_on_submit=True):
            dict_m = {m["id"]: m["nombre"] for m in st.session_state.maquinas}
            ids_maquinas = list(dict_m.keys())

            index_default = 0
            if viene_de_qr:
                try:
                    qr_id_tipado = int(qr_maquina_id_raw) if isinstance(ids_maquinas[0], int) else qr_maquina_id_raw
                    if qr_id_tipado in ids_maquinas:
                        index_default = ids_maquinas.index(qr_id_tipado)
                except (ValueError, IndexError):
                    pass

            maquina_id = st.selectbox("Máquina *", ids_maquinas, format_func=lambda x: dict_m[x], index=index_default)
            
            c1, c2 = st.columns(2)
            fecha = c1.date_input("Fecha", value=datetime.now().date()).strftime("%Y-%m-%d")
            hora = c2.time_input("Hora", value=datetime.now().time()).strftime("%H:%M")
            
            tecnico = st.text_input("Técnico / Operador Inspector")
            
            c3, c4 = st.columns(2)
            est_recibido = c3.selectbox("Estado al recibir", ["Funcionando", "Parada", "Con observaciones"])
            est_entregado = c4.selectbox("Estado al entregar", ["Funcionando", "Parada", "Con observaciones"])
            
            c5, c6, c7 = st.columns(3)
            vibracion = c5.text_input("Vibración (mm/s)")
            temperatura = c6.text_input("Temperatura (°C)")
            presion = c7.text_input("Presión (bar)")
            
            repuestos_usados = st.text_input("Repuestos Utilizados")
            observaciones = st.text_area("Observaciones Generales")
            conformidad = st.checkbox("Operador conforme con la entrega técnica de la línea")
            
            submit = st.form_submit_button("Guardar Inspección")
            if submit:
                payload = {
                    "maquina_id": maquina_id, "fecha": fecha, "hora": hora,
                    "tecnico": tecnico, "estado_recibido": est_recibido, "estado_entregado": est_entregado,
                    "vibracion": vibracion, "temperatura": temperatura, "presion": presion,
                    "repuestos": repuestos_usados, "observaciones": observaciones, "conformidad": conformidad
                }
                insert_checklist(payload)
                st.session_state.checklists = get_checklists()
                st.session_state.pop("qr_maquina_id", None)
                st.session_state.pop("forzar_vista", None)
                st.query_params.clear()
                st.success("Checklist almacenado correctamente.")
                st.rerun()

    # Historial de checkouts
    st.markdown("<br>", unsafe_allow_html=True)
    if not st.session_state.checklists:
        st.info("No hay checklists registrados en este ciclo.")
    else:
        dict_m = {m["id"]: m["nombre"] for m in st.session_state.maquinas}
        for c in st.session_state.checklists:
            m_nom = dict_m.get(c.get("maquina_id"), "Máquina Desconocida")
            conf_txt = "🟢 Conforme" if c.get("conformidad") else "🟠 Sin Conformidad"
            
            col_l, col_r = st.columns([0.85, 0.15])
            with col_l:
                st.markdown(f"""
                <div class='industrial-panel'>
                    <strong>{m_nom}</strong> — <small>{c.get('fecha')} {c.get('hora')} · {c.get('tecnico') or '—'}</small><br>
                    <span>Recibida: {c.get('estado_recibido')} ➔ Entregada: {c.get('estado_entregado')}</span><br>
                    <strong>Conformidad del operador: {conf_txt}</strong>
                </div>
                """, unsafe_allow_html=True)
            with col_r:
                if st.button("🗑️ Borrar", key=f"del_c_{c.get('id')}"):
                    delete_checklist(c.get('id'))
                    st.session_state.checklists = get_checklists()
                    st.rerun()
