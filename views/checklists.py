import streamlit as st
import uuid
from datetime import datetime
from database.conection import insert_checklist, delete_checklist, get_checklists

def render_checklists():
    st.title("Recepción / Entrega de Máquina")
    st.write("Checklists Operacionales de primer nivel.")
    
    if not st.session_state.maquinas:
        st.warning("Carga al menos una máquina primero.")
        return
        
    if st.checkbox("+ Nuevo Registro de Turno"):
        with st.form("form_checklist", clear_on_submit=True):
            dict_m = {m["id"]: m["nombre"] for m in st.session_state.maquinas}
            maquina_id = st.selectbox("Máquina *", list(dict_m.keys()), format_func=lambda x: dict_m[x])
            
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
            
            repuestos = st.text_input("Repuestos Utilizados")
            observaciones = st.text_area("Observaciones Generales")
            conformidad = st.checkbox("Operador conforme con la entrega técnica de la línea")
            
            submit = st.form_submit_button("Guardar Inspección")
            if submit:
                new_id = str(uuid.uuid4())
                payload = {
                    "id": new_id, "maquinaId": maquina_id, "fecha": fecha, "hora": hora,
                    "tecnico": tecnico, "estadoRecibido": est_recibido, "estadoEntregado": est_entregado,
                    "vibracion": vibracion, "temperatura": temperatura, "presion": presion,
                    "repuestos": repuestos, "observaciones": observaciones, "conformidad": conformidad
                }
                insert_checklist(payload)
                st.session_state.checklists = get_checklists()
                st.success("Checklist almacenado correctamente.")
                st.rerun()

    # Historial de checkouts
    st.markdown("<br>", unsafe_allow_html=True)
    if not st.session_state.checklists:
        st.info("No hay checklists registrados en este ciclo.")
    else:
        dict_m = {m["id"]: m["nombre"] for m in st.session_state.maquinas}
        for c in st.session_state.checklists:
            m_nom = dict_m.get(c.get("maquinaId"), "Máquina Desconocida")
            conf_txt = "🟢 Conforme" if c.get("conformidad") else "🟠 Sin Conformidad"
            
            col_l, col_r = st.columns([0.85, 0.15])
            with col_l:
                st.markdown(f"""
                <div class='industrial-panel'>
                    <strong>{m_nom}</strong> — <small>{c.get('fecha')} {c.get('hora')} · {c.get('tecnico') or '—'}</small><br>
                    <span>Recibida: {c.get('estadoRecibido')} ➔ Entregada: {c.get('estadoEntregado')}</span><br>
                    <strong>Conformidad del operador: {conf_txt}</strong>
                </div>
                """, unsafe_allow_html=True)
            with col_r:
                if st.button("🗑️ Borrar", key=f"del_c_{c.get('id')}"):
                    delete_checklist(c.get('id'))
                    st.session_state.checklists = get_checklists()
                    st.rerun()