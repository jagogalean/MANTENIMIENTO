import streamlit as st
from datetime import datetime
from database.conection import insert_ot, update_ot, get_ots, update_repuesto, get_repuestos, insert_ot_repuesto

ESTADOS_OT = ["Pendiente", "En Ejecucion", "Bloqueada", "Completada"]


def generar_codigo_ot(ots):
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


def _dias_abierta(fecha_inicio_iso):
    try:
        fecha = datetime.fromisoformat(fecha_inicio_iso.replace("Z", "+00:00"))
        return (datetime.now(fecha.tzinfo) - fecha).days
    except (TypeError, ValueError, AttributeError):
        return None


def _render_form_estado_y_cierre(o, repuestos, key_prefix):
    """Formulario compartido para actualizar estado / bloquear / cerrar y
    registrar repuestos, usado tanto en 'Mis OTs' como en el Backlog."""
    nuevo_estado = st.selectbox(
        "Estado de la OT", ESTADOS_OT,
        index=ESTADOS_OT.index(o.get("estado")) if o.get("estado") in ESTADOS_OT else 0,
        key=f"{key_prefix}_estado_{o.get('id')}"
    )

    motivo_bloqueo = o.get("motivo_bloqueo", "") or ""
    if nuevo_estado == "Bloqueada":
        motivo_bloqueo = st.text_area(
            "🚧 ¿Por qué no se puede cerrar? *",
            value=motivo_bloqueo,
            placeholder="Ej: Falta el rodamiento SKF 6204, esperando repuesto del proveedor.",
            key=f"{key_prefix}_motivo_{o.get('id')}"
        )

    fecha_fin_dt = None
    if nuevo_estado == "Completada":
        c1, c2 = st.columns(2)
        fecha_fin_sel = c1.date_input("Fecha de cierre", value=datetime.now().date(), key=f"{key_prefix}_fecha_fin_{o.get('id')}")
        hora_fin_sel = c2.time_input("Hora de fin", value=datetime.now().time(), key=f"{key_prefix}_hora_fin_{o.get('id')}")
        fecha_fin_dt = datetime.combine(fecha_fin_sel, hora_fin_sel)

    with st.expander(f"🔩 Registrar repuestos usados en {o.get('codigo')}"):
        if repuestos:
            dict_repuestos = {r["nombre"]: r for r in repuestos}
            c1, c2 = st.columns(2)
            r_sel = c1.selectbox("Repuesto", list(dict_repuestos.keys()), key=f"{key_prefix}_rep_sel_{o.get('id')}")
            cant_sel = c2.number_input("Cantidad", min_value=1, step=1, key=f"{key_prefix}_rep_cant_{o.get('id')}")
            if st.button("➕ Registrar consumo", key=f"{key_prefix}_rep_btn_{o.get('id')}"):
                rep = dict_repuestos[r_sel]
                if cant_sel > rep.get("stock_actual", 0):
                    st.error(f"❌ Stock insuficiente. Disponible: {rep.get('stock_actual', 0)}.")
                else:
                    update_repuesto(rep["id"], {"stock_actual": rep["stock_actual"] - cant_sel})
                    insert_ot_repuesto({"ot_id": o.get("id"), "repuesto_id": rep["id"], "cantidad_usada": cant_sel})
                    st.session_state.repuestos = get_repuestos()
                    st.success("✅ Consumo registrado y descontado del stock.")
                    st.rerun()
        else:
            st.caption("No hay repuestos cargados en el inventario.")

    if st.button("💾 Guardar cambios de estado", key=f"{key_prefix}_save_{o.get('id')}"):
        if nuevo_estado == "Bloqueada" and not motivo_bloqueo.strip():
            st.error("❌ Contá por qué no se puede cerrar antes de guardar.")
        else:
            patch = {"estado": nuevo_estado, "motivo_bloqueo": motivo_bloqueo if nuevo_estado == "Bloqueada" else None}
            if nuevo_estado == "Completada":
                patch["fecha_fin"] = fecha_fin_dt.isoformat()
            update_ot(o.get("id"), patch)
            st.session_state.ots = get_ots()
            st.success(f"✅ {o.get('codigo')} actualizada a '{nuevo_estado}'.")
            st.rerun()


def render_mis_ots(usuario):
    st.title("👷 Mis Órdenes de Trabajo")

    tecnico_id = usuario.get("tecnico_id")
    if not tecnico_id:
        st.warning("Tu usuario no está vinculado a ningún técnico todavía. Pedile al administrador que te vincule en '🔐 Usuarios'.")
        return

    maquinas = st.session_state.get("maquinas", [])
    map_maquina = {m["id"]: m["nombre"] for m in maquinas}
    repuestos = st.session_state.get("repuestos", [])
    todas_las_ots = st.session_state.get("ots", [])

    # --- REPORTAR UNA FALLA / CREAR OT CORRECTIVA ---
    with st.expander("🆕 Reportar Falla / Crear OT Correctiva"):
        if not maquinas:
            st.warning("Todavía no hay máquinas registradas.")
        else:
            with st.form("form_correctivo_tecnico", clear_on_submit=True):
                dict_maquinas = {m["nombre"]: m["id"] for m in maquinas}
                maquina_sel = st.selectbox("Máquina", options=list(dict_maquinas.keys()))
                descripcion = st.text_area("Descripción del problema / trabajo realizado")

                c1, c2 = st.columns(2)
                fecha_hoy = c1.date_input("Fecha", value=datetime.now().date())
                hora_inicio = c2.time_input("Hora de inicio", value=datetime.now().time())

                horas_paro = st.number_input("Horas de Paro (si la máquina se detuvo)", min_value=0.0, step=0.5)

                asignacion = st.radio(
                    "¿Qué hacés con esta OT?",
                    ["Me la asigno y la trabajo yo", "Dejarla en el backlog compartido (para que cualquiera la tome)"],
                    key="asignacion_nueva_ot"
                )

                submit = st.form_submit_button("Crear OT Correctiva")
                if submit:
                    if not descripcion.strip():
                        st.error("❌ Describí el problema antes de guardar.")
                    else:
                        codigo_generado = generar_codigo_ot(todas_las_ots)
                        fecha_inicio_dt = datetime.combine(fecha_hoy, hora_inicio)
                        me_la_asigno = asignacion.startswith("Me la asigno")
                        nueva_ot = {
                            "codigo": codigo_generado,
                            "maquina_id": dict_maquinas[maquina_sel],
                            "tipo_mantenimiento": "Correctivo",
                            "descripcion": descripcion,
                            "estado": "En Ejecucion" if me_la_asigno else "Pendiente",
                            "fecha_inicio": fecha_inicio_dt.isoformat(),
                            "fecha_fin": None,
                            "horas_paro": horas_paro,
                            "tecnico_id": tecnico_id if me_la_asigno else None,
                            "costo_mano_obra": 0,
                            "requiere_permiso_trabajo": False,
                            "permiso_trabajo_emitido": False
                        }
                        insert_ot(nueva_ot)
                        st.session_state.ots = get_ots()
                        if me_la_asigno:
                            st.success(f"✅ OT {codigo_generado} creada y asignada a vos.")
                        else:
                            st.success(f"✅ OT {codigo_generado} creada en el backlog compartido.")
                        st.rerun()

    st.markdown("---")

    # --- BACKLOG COMPARTIDO: OTs sin asignar, cualquiera las puede tomar ---
    backlog = [o for o in todas_las_ots if o.get("tecnico_id") is None and o.get("estado") != "Completada"]
    backlog_con_dias = []
    for o in backlog:
        dias = _dias_abierta(o.get("fecha_inicio"))
        backlog_con_dias.append((dias if dias is not None else 0, o))
    backlog_con_dias.sort(key=lambda x: x[0], reverse=True)

    urgentes_backlog = len([d for d, _ in backlog_con_dias if d >= 2])
    titulo_backlog = f"🗂️ Backlog Compartido — sin asignar ({len(backlog)})"
    if urgentes_backlog:
        titulo_backlog = f"🚨 {titulo_backlog} · {urgentes_backlog} con 2+ días sin moverse"

    with st.expander(titulo_backlog, expanded=urgentes_backlog > 0):
        if not backlog_con_dias:
            st.caption("No hay OTs sin asignar en este momento. 🎉")
        else:
            for dias, o in backlog_con_dias:
                color = "#EF4444" if dias >= 2 else "#F59E0B" if dias >= 1 else "#38BDF8"
                st.markdown(f"""
                <div class='industrial-panel' style='border-color:{color};'>
                    <strong>{o.get('codigo')}</strong> — {map_maquina.get(o.get('maquina_id'), 'Desconocida')}<br>
                    <span>{o.get('tipo_mantenimiento')} · {o.get('descripcion')}</span><br>
                    <span style='color:{color}; font-weight:bold;'>⏳ Cargada hace {dias} día(s) y sin tomar</span>
                </div>
                """, unsafe_allow_html=True)
                if st.button("🙋 Tomar esta OT", key=f"tomar_{o.get('id')}"):
                    update_ot(o.get("id"), {"tecnico_id": tecnico_id, "estado": "En Ejecucion"})
                    st.session_state.ots = get_ots()
                    st.success(f"✅ Te asignaste la OT {o.get('codigo')}.")
                    st.rerun()
                st.markdown("---")

    # --- MIS OTs ASIGNADAS ---
    mis_ots = [o for o in todas_las_ots if o.get("tecnico_id") == tecnico_id]

    if not mis_ots:
        st.info("No tenés Órdenes de Trabajo asignadas por el momento.")
        return

    pendientes = [o for o in mis_ots if o.get("estado") != "Completada"]
    completadas = [o for o in mis_ots if o.get("estado") == "Completada"]

    st.markdown(f"##### 🔧 {len(pendientes)} pendiente(s) · ✅ {len(completadas)} completada(s)")
    st.markdown("---")

    if not pendientes:
        st.success("✅ No tenés OTs pendientes. ¡Buen trabajo!")

    for o in pendientes:
        dias = _dias_abierta(o.get("fecha_inicio"))
        st.markdown(f"""
        <div class='industrial-panel'>
            <strong>{o.get('codigo')}</strong> — {map_maquina.get(o.get('maquina_id'), 'Desconocida')}<br>
            <span>{o.get('tipo_mantenimiento')} · {o.get('descripcion')}</span>
            {f"<br><span style='color:#F59E0B;'>⏳ Abierta hace {dias} día(s)</span>" if dias is not None and dias >= 2 else ""}
        </div>
        """, unsafe_allow_html=True)

        if o.get("estado") == "Bloqueada":
            st.error(f"🚧 Bloqueada: {o.get('motivo_bloqueo') or 'sin motivo especificado'}")

        if o.get("requiere_permiso_trabajo") and not o.get("permiso_trabajo_emitido"):
            st.warning("⚠️ Esta tarea requiere Permiso de Trabajo y todavía no fue emitido. Confirmá con tu coordinador antes de empezar.")

        _render_form_estado_y_cierre(o, repuestos, key_prefix="mis")
        st.markdown("---")

    if completadas:
        with st.expander(f"✅ Ver mis OTs completadas ({len(completadas)})"):
            for o in completadas:
                st.markdown(f"- **{o.get('codigo')}** — {map_maquina.get(o.get('maquina_id'), 'Desconocida')} · {o.get('descripcion')}")
