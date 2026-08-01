import streamlit as st
from datetime import datetime
from database.conection import insert_ot, get_ots, update_repuesto, get_repuestos, insert_ot_repuesto


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


def render_ots():
    st.title("⚙️ Gestión de Órdenes de Trabajo (OT)")

    maquinas = st.session_state.get("maquinas", [])
    ots = st.session_state.get("ots", [])
    repuestos = st.session_state.get("repuestos", [])
    tecnicos = st.session_state.get("tecnicos", [])

    if not maquinas:
        st.warning("⚠️ Debes registrar al menos una máquina antes de crear una OT.")
        return

    # Carrito de repuestos a consumir en esta OT (vive fuera del form porque necesita reactividad)
    if "ot_carrito" not in st.session_state:
        st.session_state.ot_carrito = []  # lista de {repuesto_id, nombre, cantidad}

    st.subheader("Crear Nueva Orden de Trabajo")

    codigo_generado = generar_codigo_ot(ots)
    st.text_input("Código de la OT (autogenerado)", value=codigo_generado, disabled=True)

    # --- Selección de repuestos a utilizar (interactiva, fuera del form) ---
    st.markdown("##### 🔩 Repuestos a utilizar en esta OT")
    if not repuestos:
        st.caption("No hay repuestos cargados en el inventario todavía.")
    else:
        dict_repuestos = {r["nombre"]: r for r in repuestos}
        c1, c2, c3 = st.columns([0.5, 0.25, 0.25])
        repuesto_sel = c1.selectbox("Repuesto", options=list(dict_repuestos.keys()), key="ot_rep_sel")
        cantidad_sel = c2.number_input("Cantidad", min_value=1, step=1, key="ot_rep_cant")
        c3.write("")
        c3.write("")
        if c3.button("➕ Agregar a la OT"):
            rep = dict_repuestos[repuesto_sel]
            disponible = rep.get("stock_actual", 0)
            ya_reservado = sum(i["cantidad"] for i in st.session_state.ot_carrito if i["repuesto_id"] == rep["id"])
            if cantidad_sel + ya_reservado > disponible:
                st.error(f"❌ Stock insuficiente. Disponible: {disponible}, ya reservado en esta OT: {ya_reservado}.")
            else:
                st.session_state.ot_carrito.append({
                    "repuesto_id": rep["id"],
                    "nombre": rep["nombre"],
                    "cantidad": cantidad_sel
                })
                st.rerun()

    if st.session_state.ot_carrito:
        st.write("**Repuestos agregados a esta OT:**")
        for idx, item in enumerate(st.session_state.ot_carrito):
            col_i, col_x = st.columns([0.85, 0.15])
            col_i.write(f"- {item['nombre']} × {item['cantidad']}")
            if col_x.button("🗑️", key=f"del_carrito_{idx}"):
                st.session_state.ot_carrito.pop(idx)
                st.rerun()

    st.markdown("---")

    # --- FORMULARIO PRINCIPAL DE LA OT ---
    with st.form("form_nueva_ot", clear_on_submit=True):
        col1, col2 = st.columns(2)

        with col1:
            dict_maquinas = {m["nombre"]: m["id"] for m in maquinas}
            maquina_sel = st.selectbox("Seleccionar Máquina", options=list(dict_maquinas.keys()))
            tipo = st.selectbox("Tipo de Mantenimiento", options=["Preventivo", "Correctivo", "Predictivo"])

        with col2:
            estado = st.selectbox("Estado Inicial", options=["Pendiente", "En Ejecucion", "Completada"])
            horas_paro = st.number_input("Horas de Paro (Afectación a Disponibilidad)", min_value=0.0, step=0.5)
            dict_tecnicos = {t["nombre"]: t["id"] for t in tecnicos}
            tecnico_sel = st.selectbox("Técnico Asignado", options=["Sin asignar"] + list(dict_tecnicos.keys()))
            costo_mano_obra = st.number_input("Costo de Mano de Obra ($)", min_value=0.0, step=1.0)

        descripcion = st.text_area("Descripción del Trabajo / Alcance")

        requiere_permiso = st.checkbox("⚠️ Esta OT requiere Permiso de Trabajo (LOTO / trabajo en altura / eléctrico)")
        permiso_emitido = False
        if requiere_permiso:
            permiso_emitido = st.checkbox("✅ El permiso de trabajo ya fue emitido y firmado")

        submit = st.form_submit_button("Registrar Orden de Trabajo")

        if submit:
            if not descripcion:
                st.error("❌ La descripción es obligatoria.")
            else:
                # Revalidar stock contra Supabase justo antes de guardar (pudo cambiar desde otra sesión)
                repuestos_actuales = {r["id"]: r for r in get_repuestos()}
                stock_ok = True
                for item in st.session_state.ot_carrito:
                    rep_actual = repuestos_actuales.get(item["repuesto_id"])
                    if not rep_actual or rep_actual.get("stock_actual", 0) < item["cantidad"]:
                        st.error(f"❌ Stock insuficiente para '{item['nombre']}' al momento de guardar.")
                        stock_ok = False

                if stock_ok:
                    nueva_ot = {
                        "codigo": codigo_generado,
                        "maquina_id": dict_maquinas[maquina_sel],
                        "tipo_mantenimiento": tipo,
                        "descripcion": descripcion,
                        "estado": estado,
                        "fecha_inicio": datetime.now().isoformat(),
                        "fecha_fin": datetime.now().isoformat() if estado == "Completada" else None,
                        "horas_paro": horas_paro,
                        "tecnico_id": dict_tecnicos.get(tecnico_sel) if tecnico_sel != "Sin asignar" else None,
                        "costo_mano_obra": costo_mano_obra,
                        "requiere_permiso_trabajo": requiere_permiso,
                        "permiso_trabajo_emitido": permiso_emitido
                    }
                    ot_creada = insert_ot(nueva_ot)
                    ot_id = ot_creada[0]["id"] if ot_creada else None

                    # Descontar stock y registrar el consumo de cada repuesto del carrito
                    for item in st.session_state.ot_carrito:
                        rep_actual = repuestos_actuales[item["repuesto_id"]]
                        nuevo_stock = rep_actual["stock_actual"] - item["cantidad"]
                        update_repuesto(item["repuesto_id"], {"stock_actual": nuevo_stock})
                        insert_ot_repuesto({
                            "ot_id": ot_id,
                            "repuesto_id": item["repuesto_id"],
                            "cantidad_usada": item["cantidad"]
                        })

                    st.session_state.ots = get_ots()
                    st.session_state.repuestos = get_repuestos()
                    st.session_state.ot_carrito = []
                    st.success(f"✅ Orden {codigo_generado} registrada exitosamente.")
                    if requiere_permiso and not permiso_emitido:
                        st.warning("⚠️ Recordá emitir y firmar el Permiso de Trabajo antes de iniciar la tarea en campo.")
                    st.rerun()

    # --- HISTORIAL / TABLA DE OTS ---
    st.markdown("---")
    st.subheader("Historial de Órdenes de Trabajo")
    if not ots:
        st.info("No hay órdenes de trabajo registradas.")
    else:
        tabla_ots = []
        map_m_nombre = {m["id"]: m["nombre"] for m in maquinas}
        map_tec_nombre = {t["id"]: t["nombre"] for t in tecnicos}
        for o in ots:
            tabla_ots.append({
                "Código": o.get("codigo"),
                "Máquina": map_m_nombre.get(o.get("maquina_id"), "Desconocida"),
                "Tipo": o.get("tipo_mantenimiento"),
                "Estado": o.get("estado"),
                "Técnico": map_tec_nombre.get(o.get("tecnico_id"), "Sin asignar"),
                "Horas Paro": o.get("horas_paro"),
                "Costo M.O.": o.get("costo_mano_obra", 0),
                "Permiso Trabajo": "✅" if o.get("permiso_trabajo_emitido") else ("⚠️ Pendiente" if o.get("requiere_permiso_trabajo") else "—"),
                "Descripción": o.get("descripcion")
            })
        st.dataframe(tabla_ots, use_container_width=True)
