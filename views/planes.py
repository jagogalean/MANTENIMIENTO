import streamlit as st
from datetime import datetime, timedelta
from database.conection import insert_plan, update_plan, delete_plan, get_planes


def render_planes():
    st.title("🗓️ Plan de Mantenimiento Preventivo")
    st.write("Tareas recurrentes por máquina, para dejar de trabajar solo de forma reactiva.")

    maquinas = st.session_state.get("maquinas", [])
    planes = st.session_state.get("planes", [])

    if not maquinas:
        st.warning("⚠️ Registrá al menos una máquina antes de crear un plan preventivo.")
        return

    if st.checkbox("+ Nueva Tarea de Plan Preventivo"):
        with st.form("form_nuevo_plan", clear_on_submit=True):
            dict_m = {m["nombre"]: m["id"] for m in maquinas}
            maquina_sel = st.selectbox("Máquina *", options=list(dict_m.keys()))
            tarea = st.text_input("Tarea *", placeholder="Ej: Lubricación de rodamientos")
            frecuencia_dias = st.number_input("Frecuencia (días)", min_value=1, step=1, value=30)
            ultima_ejecucion = st.date_input("Última ejecución (si ya se hizo antes)", value=None)

            submit = st.form_submit_button("Guardar Tarea")
            if submit:
                if not tarea.strip():
                    st.error("❌ La tarea es obligatoria.")
                else:
                    base = ultima_ejecucion if ultima_ejecucion else datetime.now().date()
                    proxima = base + timedelta(days=int(frecuencia_dias))
                    payload = {
                        "maquina_id": dict_m[maquina_sel],
                        "tarea": tarea,
                        "frecuencia_dias": int(frecuencia_dias),
                        "ultima_ejecucion": ultima_ejecucion.strftime("%Y-%m-%d") if ultima_ejecucion else None,
                        "proxima_ejecucion": proxima.strftime("%Y-%m-%d")
                    }
                    insert_plan(payload)
                    st.session_state.planes = get_planes()
                    st.success(f"✅ Tarea '{tarea}' agregada al plan preventivo.")
                    st.rerun()

    st.markdown("---")
    st.subheader("Tareas Programadas")

    if not planes:
        st.info("Todavía no hay tareas de mantenimiento preventivo cargadas.")
        return

    dict_m = {m["id"]: m["nombre"] for m in maquinas}
    hoy = datetime.now().date()

    for p in planes:
        try:
            fecha_prox = datetime.strptime(p.get("proxima_ejecucion"), "%Y-%m-%d").date()
        except (TypeError, ValueError):
            fecha_prox = None

        vencida = fecha_prox is not None and fecha_prox < hoy
        proxima_semana = fecha_prox is not None and hoy <= fecha_prox <= hoy + timedelta(days=7)

        if vencida:
            color = "#EF4444"
            estado_txt = f"🔴 Vencida hace {(hoy - fecha_prox).days} día(s)"
        elif proxima_semana:
            color = "#F59E0B"
            estado_txt = f"🟠 Vence en {(fecha_prox - hoy).days} día(s)"
        else:
            color = "#38BDF8"
            estado_txt = f"🟢 Programada para {p.get('proxima_ejecucion')}"

        col_i, col_a = st.columns([0.8, 0.2])
        with col_i:
            st.markdown(f"""
            <div class='industrial-panel' style='border-color:{color};'>
                <strong>{dict_m.get(p.get('maquina_id'), 'Máquina desconocida')}</strong> — {p.get('tarea')}<br>
                <span style='color:{color}; font-weight:bold;'>{estado_txt}</span> · Cada {p.get('frecuencia_dias')} días
            </div>
            """, unsafe_allow_html=True)
        with col_a:
            if st.button("✅ Marcar Ejecutada", key=f"exec_plan_{p.get('id')}"):
                nueva_prox = hoy + timedelta(days=p.get("frecuencia_dias", 30))
                update_plan(p.get("id"), {
                    "ultima_ejecucion": hoy.strftime("%Y-%m-%d"),
                    "proxima_ejecucion": nueva_prox.strftime("%Y-%m-%d")
                })
                st.session_state.planes = get_planes()
                st.rerun()
            if st.button("🗑️ Eliminar", key=f"del_plan_{p.get('id')}"):
                delete_plan(p.get("id"))
                st.session_state.planes = get_planes()
                st.rerun()