import streamlit as st
from datetime import datetime, timedelta
from database.conection import (
    insert_plan, update_plan, delete_plan, get_planes,
    insert_actividad, delete_actividad, get_actividades,
    insert_plan_ejecucion, get_plan_ejecuciones,
    insert_ot, get_ots
)


def _generar_codigo_ot(ots):
    """Genera el siguiente código consecutivo del año en curso. Ej: OT-2026-0007"""
    year = datetime.now().year
    prefijo = f"OT-{year}-"
    consecutivos = []
    for o in ots:
        cod = o.get("codigo", "") or ""
        if cod.startswith(prefijo):
            try:
                consecutivos.append(int(cod.replace(prefijo, "")))
            except ValueError:
                pass
    siguiente = max(consecutivos) + 1 if consecutivos else 1
    return f"{prefijo}{siguiente:04d}"


def render_planes():
    st.title("🗓️ Plan de Mantenimiento Preventivo")
    st.write("Un plan agrupa varias actividades bajo una misma frecuencia — ej: 'Extrusora 001, cada 30 días' con 5 actividades adentro.")

    maquinas = st.session_state.get("maquinas", [])
    planes = st.session_state.get("planes", [])
    actividades = st.session_state.get("plan_actividades", [])

    if not maquinas:
        st.warning("⚠️ Registrá al menos una máquina antes de crear un plan preventivo.")
        return

    # --- CREAR NUEVO PLAN (cabecera + actividades) ---
    if "nuevo_plan_actividades" not in st.session_state:
        st.session_state.nuevo_plan_actividades = []

    with st.expander("+ Nuevo Plan Preventivo"):
        dict_m = {m["nombre"]: m["id"] for m in maquinas}
        maquina_sel = st.selectbox("Máquina *", options=list(dict_m.keys()), key="np_maquina")
        nombre_plan = st.text_input("Nombre del Plan *", placeholder="Ej: Preventivo Mensual, Lubricación Semanal")
        frecuencia_dias = st.number_input("Frecuencia (días)", min_value=1, step=1, value=30, key="np_frecuencia")
        ultima_ejecucion = st.date_input("Última ejecución (si ya se hizo antes)", value=None, key="np_ultima")

        st.markdown("**Actividades de este plan:**")
        c1, c2 = st.columns([0.8, 0.2])
        nueva_actividad = c1.text_input("Actividad", placeholder="Ej: Lubricación de rodamientos", key="np_actividad_input")
        c2.write("")
        if c2.button("➕ Agregar"):
            if nueva_actividad.strip():
                st.session_state.nuevo_plan_actividades.append(nueva_actividad.strip())
                st.rerun()

        if st.session_state.nuevo_plan_actividades:
            for idx, act in enumerate(st.session_state.nuevo_plan_actividades):
                col_a, col_x = st.columns([0.85, 0.15])
                col_a.write(f"{idx + 1}. {act}")
                if col_x.button("🗑️", key=f"del_np_act_{idx}"):
                    st.session_state.nuevo_plan_actividades.pop(idx)
                    st.rerun()
        else:
            st.caption("Todavía no agregaste actividades.")

        if st.button("💾 Guardar Plan Preventivo"):
            if not nombre_plan.strip():
                st.error("❌ Ponele un nombre al plan.")
            elif not st.session_state.nuevo_plan_actividades:
                st.error("❌ Agregá al menos una actividad.")
            else:
                base = ultima_ejecucion if ultima_ejecucion else datetime.now().date()
                proxima = base + timedelta(days=int(frecuencia_dias))
                plan_creado = insert_plan({
                    "maquina_id": dict_m[maquina_sel],
                    "nombre_plan": nombre_plan,
                    "frecuencia_dias": int(frecuencia_dias),
                    "ultima_ejecucion": ultima_ejecucion.strftime("%Y-%m-%d") if ultima_ejecucion else None,
                    "proxima_ejecucion": proxima.strftime("%Y-%m-%d")
                })
                plan_id = plan_creado[0]["id"] if plan_creado else None
                for act in st.session_state.nuevo_plan_actividades:
                    insert_actividad({"plan_id": plan_id, "actividad": act})

                st.session_state.planes = get_planes()
                st.session_state.plan_actividades = get_actividades()
                cantidad_cargada = len(st.session_state.nuevo_plan_actividades)
                st.session_state.nuevo_plan_actividades = []
                st.success(f"✅ Plan '{nombre_plan}' creado con {cantidad_cargada} actividad(es).")
                st.rerun()

    st.markdown("---")
    st.subheader("Planes Preventivos Cargados")

    if not planes:
        st.info("Todavía no hay planes preventivos cargados.")
        return

    dict_m_nombre = {m["id"]: m["nombre"] for m in maquinas}
    actividades_por_plan = {}
    for a in actividades:
        actividades_por_plan.setdefault(a.get("plan_id"), []).append(a)

    hoy = datetime.now().date()

    for p in planes:
        try:
            fecha_prox = datetime.strptime(p.get("proxima_ejecucion"), "%Y-%m-%d").date()
        except (TypeError, ValueError):
            fecha_prox = None

        vencido = fecha_prox is not None and fecha_prox < hoy
        proxima_semana = fecha_prox is not None and hoy <= fecha_prox <= hoy + timedelta(days=7)

        if vencido:
            color = "#EF4444"
            estado_txt = f"🔴 Vencido hace {(hoy - fecha_prox).days} día(s)"
        elif proxima_semana:
            color = "#F59E0B"
            estado_txt = f"🟠 Vence en {(fecha_prox - hoy).days} día(s)"
        else:
            color = "#38BDF8"
            estado_txt = f"🟢 Programado para {p.get('proxima_ejecucion')}"

        acts_del_plan = actividades_por_plan.get(p.get("id"), [])

        st.markdown(f"""
        <div class='industrial-panel' style='border-color:{color};'>
            <strong>{dict_m_nombre.get(p.get('maquina_id'), 'Máquina desconocida')}</strong> — {p.get('nombre_plan')}<br>
            <span style='color:{color}; font-weight:bold;'>{estado_txt}</span> · Cada {p.get('frecuencia_dias')} días · {len(acts_del_plan)} actividad(es)
        </div>
        """, unsafe_allow_html=True)

        with st.expander(f"📋 Ver / editar actividades de '{p.get('nombre_plan')}'"):
            if acts_del_plan:
                for a in acts_del_plan:
                    col_a, col_x = st.columns([0.85, 0.15])
                    col_a.write(f"• {a.get('actividad')}")
                    if col_x.button("🗑️", key=f"del_act_{a.get('id')}"):
                        delete_actividad(a.get("id"))
                        st.session_state.plan_actividades = get_actividades()
                        st.rerun()
            else:
                st.caption("Este plan no tiene actividades cargadas.")

            c1, c2 = st.columns([0.8, 0.2])
            nueva_act_existente = c1.text_input("Agregar actividad", key=f"add_act_{p.get('id')}")
            c2.write("")
            if c2.button("➕ Agregar", key=f"btn_add_act_{p.get('id')}"):
                if nueva_act_existente.strip():
                    insert_actividad({"plan_id": p.get("id"), "actividad": nueva_act_existente.strip()})
                    st.session_state.plan_actividades = get_actividades()
                    st.rerun()

        col_ot, col_exec, col_del = st.columns(3)
        with col_ot:
            if st.button("🛠️ Generar OT Preventiva", key=f"gen_ot_plan_{p.get('id')}"):
                lista_acts = "\n".join([f"- {a.get('actividad')}" for a in acts_del_plan])
                desc_ot = f"[Preventivo: {p.get('nombre_plan')}]\nActividades programadas:\n{lista_acts}"
                todas_las_ots = get_ots()
                codigo_ot = _generar_codigo_ot(todas_las_ots)
                
                insert_ot({
                    "codigo": codigo_ot,
                    "maquina_id": p.get("maquina_id"),
                    "tipo_mantenimiento": "Preventivo",
                    "descripcion": desc_ot,
                    "estado": "Pendiente",
                    "fecha_inicio": datetime.now().isoformat(),
                    "fecha_fin": None,
                    "horas_paro": 0,
                    "tecnico_id": None,
                    "costo_mano_obra": 0,
                    "plan_id": p.get("id")
                })
                st.session_state.ots = get_ots()
                st.success(f"✅ Se generó la Orden de Trabajo **{codigo_ot}** para este preventivo. Ya aparece en el Backlog.")
        with col_exec:
            if st.button("✅ Marcar Plan Ejecutado", key=f"exec_plan_{p.get('id')}"):
                nueva_prox = hoy + timedelta(days=p.get("frecuencia_dias", 30))
                insert_plan_ejecucion({
                    "plan_id": p.get("id"),
                    "maquina_id": p.get("maquina_id"),
                    "fecha_programada": p.get("proxima_ejecucion"),
                    "fecha_realizada": hoy.strftime("%Y-%m-%d")
                })
                update_plan(p.get("id"), {
                    "ultima_ejecucion": hoy.strftime("%Y-%m-%d"),
                    "proxima_ejecucion": nueva_prox.strftime("%Y-%m-%d")
                })
                st.session_state.planes = get_planes()
                st.session_state.plan_ejecuciones = get_plan_ejecuciones()
                st.rerun()
        with col_del:
            if st.button("🗑️ Eliminar Plan", key=f"del_plan_{p.get('id')}"):
                delete_plan(p.get("id"))
                st.session_state.planes = get_planes()
                st.session_state.plan_actividades = get_actividades()
                st.rerun()

        st.markdown("<br>", unsafe_allow_html=True)
