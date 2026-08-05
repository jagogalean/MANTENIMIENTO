import streamlit as st
from datetime import datetime
from database.conection import update_ot, get_ots, update_repuesto, get_repuestos, insert_ot_repuesto


def render_mis_ots(usuario):
    st.title("👷 Mis Órdenes de Trabajo")

    tecnico_id = usuario.get("tecnico_id")
    if not tecnico_id:
        st.warning("Tu usuario no está vinculado a ningún técnico todavía. Pedile al administrador que te vincule en '🔐 Usuarios'.")
        return

    maquinas = st.session_state.get("maquinas", [])
    map_maquina = {m["id"]: m["nombre"] for m in maquinas}
    repuestos = st.session_state.get("repuestos", [])

    mis_ots = [o for o in st.session_state.get("ots", []) if o.get("tecnico_id") == tecnico_id]

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
        st.markdown(f"""
        <div class='industrial-panel'>
            <strong>{o.get('codigo')}</strong> — {map_maquina.get(o.get('maquina_id'), 'Desconocida')}<br>
            <span>{o.get('tipo_mantenimiento')} · {o.get('descripcion')}</span>
        </div>
        """, unsafe_allow_html=True)

        if o.get("requiere_permiso_trabajo") and not o.get("permiso_trabajo_emitido"):
            st.warning("⚠️ Esta tarea requiere Permiso de Trabajo y todavía no fue emitido. Confirmá con tu coordinador antes de empezar.")

        estados = ["Pendiente", "En Ejecucion", "Completada"]
        nuevo_estado = st.selectbox(
            "Estado de la OT", estados,
            index=estados.index(o.get("estado")) if o.get("estado") in estados else 0,
            key=f"estado_{o.get('id')}"
        )

        with st.expander(f"🔩 Registrar repuestos usados en {o.get('codigo')}"):
            if repuestos:
                dict_repuestos = {r["nombre"]: r for r in repuestos}
                c1, c2 = st.columns(2)
                r_sel = c1.selectbox("Repuesto", list(dict_repuestos.keys()), key=f"rep_sel_{o.get('id')}")
                cant_sel = c2.number_input("Cantidad", min_value=1, step=1, key=f"rep_cant_{o.get('id')}")
                if st.button("➕ Registrar consumo", key=f"rep_btn_{o.get('id')}"):
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

        if st.button("💾 Guardar cambios de estado", key=f"save_{o.get('id')}"):
            patch = {"estado": nuevo_estado}
            if nuevo_estado == "Completada":
                patch["fecha_fin"] = datetime.now().isoformat()
            update_ot(o.get("id"), patch)
            st.session_state.ots = get_ots()
            st.success(f"✅ {o.get('codigo')} actualizada a '{nuevo_estado}'.")
            st.rerun()

        st.markdown("---")

    if completadas:
        with st.expander(f"✅ Ver mis OTs completadas ({len(completadas)})"):
            for o in completadas:
                st.markdown(f"- **{o.get('codigo')}** — {map_maquina.get(o.get('maquina_id'), 'Desconocida')} · {o.get('descripcion')}")