import streamlit as st
from datetime import datetime, date, time, timedelta
from database.conection import (
    insert_ot, update_ot, get_ots, get_repuestos,
    get_ots_cached, get_repuestos_cached, get_ots_paginado,
    delete_ot, consumir_repuesto_seguro,
    get_planes, update_plan, insert_plan_ejecucion, get_plan_ejecuciones
)
from database.permisos import es_admin


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


def calcular_costo_ot(tipo_ejecucion, horas_trabajadas=0, costo_hora_hombre=0, costo_repuestos=0,
                       costo_factura_tercero=0, costo_flete_logistica=0,
                       fecha_inicio_parada=None, fecha_fin_parada=None, costo_hora_parada=0):
    """Calcula el desglose de costos de una OT, sea interna o tercerizada.

    - Interno: Costo Directo = mano de obra (horas × costo_hora_hombre) + repuestos.
    - Tercerizado: Costo Directo = factura del proveedor + flete/logística.
    - Siempre: Lucro Cesante = horas de parada × costo_hora_parada de la máquina.
    - Costo Total = Costo Directo + Lucro Cesante.
    """
    horas_parada = 0.0
    if fecha_inicio_parada and fecha_fin_parada and fecha_fin_parada > fecha_inicio_parada:
        horas_parada = (fecha_fin_parada - fecha_inicio_parada).total_seconds() / 3600

    costo_lucro_cesante = horas_parada * (costo_hora_parada or 0)

    if tipo_ejecucion == "interno":
        costo_mano_obra = (horas_trabajadas or 0) * (costo_hora_hombre or 0)
        costo_directo = costo_mano_obra + (costo_repuestos or 0)
    else:  # tercerizado
        costo_mano_obra = 0
        costo_directo = (costo_factura_tercero or 0) + (costo_flete_logistica or 0)

    costo_total = costo_directo + costo_lucro_cesante

    return {
        "horas_parada": round(horas_parada, 2),
        "costo_mano_obra": round(costo_mano_obra, 2),
        "costo_directo": round(costo_directo, 2),
        "costo_lucro_cesante": round(costo_lucro_cesante, 2),
        "costo_total": round(costo_total, 2)
    }


ESTADOS_OT = ["Pendiente", "En Ejecucion", "Bloqueada", "Completada"]


def _refrescar_ots():
    """NUEVO: limpia la caché corta de OTs y refresca session_state, para que
    este usuario vea el cambio al instante y el resto lo vea apenas venza
    la caché (máximo 15 segundos)."""
    get_ots_cached.clear()
    st.session_state.ots = get_ots_cached()


def _refrescar_repuestos():
    get_repuestos_cached.clear()
    st.session_state.repuestos = get_repuestos_cached()


def _sincronizar_cierre_preventivo(ot_obj):
    """Si la OT que se acaba de cerrar proviene de un Plan Preventivo (plan_id),
    actualiza automáticamente la fecha del plan y registra la ejecución."""
    plan_id = ot_obj.get("plan_id")
    if not plan_id:
        return
    planes = st.session_state.get("planes") or get_planes()
    plan = next((p for p in planes if p.get("id") == plan_id), None)
    if not plan:
        return
    hoy = datetime.now().date()
    frecuencia = int(plan.get("frecuencia_dias", 30) or 30)
    nueva_prox = hoy + timedelta(days=frecuencia)
    try:
        insert_plan_ejecucion({
            "plan_id": plan_id,
            "maquina_id": plan.get("maquina_id"),
            "fecha_programada": plan.get("proxima_ejecucion"),
            "fecha_realizada": hoy.strftime("%Y-%m-%d")
        })
        update_plan(plan_id, {
            "ultima_ejecucion": hoy.strftime("%Y-%m-%d"),
            "proxima_ejecucion": nueva_prox.strftime("%Y-%m-%d")
        })
        st.session_state.planes = get_planes()
        st.session_state.plan_ejecuciones = get_plan_ejecuciones()
    except Exception:
        pass


def render_ots(usuario):
    st.title("⚙️ Gestión de Órdenes de Trabajo (OT)")

    maquinas = st.session_state.get("maquinas", [])
    # NUEVO: ots y repuestos se leen con caché corta (15s) en vez de depender
    # únicamente de la foto tomada al iniciar sesión, para que esta pantalla
    # (la más concurrida junto con Mis OTs) refleje cambios de otros usuarios
    # casi en tiempo real.
    ots = get_ots_cached()
    repuestos = get_repuestos_cached()
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
            nro_ot_openorange = st.text_input("N° OT OpenOrange (opcional)", placeholder="Ej: OT-OO-1045")
            nro_oc_openorange = st.text_input("N° OC OpenOrange asociada (opcional)", placeholder="Ej: 1108")

        with col2:
            estado = st.selectbox("Estado Inicial", options=["Pendiente", "En Ejecucion", "Completada"])
            horas_paro = st.number_input("Horas de Paro (Afectación a Disponibilidad)", min_value=0.0, step=0.5)
            dict_tecnicos = {t["nombre"]: t["id"] for t in tecnicos}
            tecnico_sel = st.selectbox("Técnico Asignado", options=["Sin asignar (backlog compartido)"] + list(dict_tecnicos.keys()))
            costo_mano_obra = st.number_input("Costo de Mano de Obra (Gs.)", min_value=0, step=1000)

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
                        "tecnico_id": dict_tecnicos.get(tecnico_sel),
                        "costo_mano_obra": costo_mano_obra,
                        "requiere_permiso_trabajo": requiere_permiso,
                        "permiso_trabajo_emitido": permiso_emitido,
                        "nro_ot_openorange": nro_ot_openorange.strip() or None,
                        "nro_oc_openorange": nro_oc_openorange.strip() or None
                    }
                    ot_creada = insert_ot(nueva_ot)
                    ot_id = ot_creada[0]["id"] if ot_creada else None

                    # NUEVO: el descuento de stock + registro de consumo por cada
                    # repuesto del carrito ahora pasa por la función RPC
                    # transaccional consumir_repuesto_seguro (ver Fase 1 del plan),
                    # que valida y descuenta stock en un único paso atómico en
                    # vez de "leer -> comparar en Python -> escribir" por separado.
                    error_stock = False
                    for item in st.session_state.ot_carrito:
                        try:
                            consumir_repuesto_seguro(ot_id, item["repuesto_id"], item["cantidad"])
                        except ValueError:
                            error_stock = True
                            st.error(f"❌ '{item['nombre']}' se quedó sin stock suficiente justo en este instante.")

                    _refrescar_ots()
                    _refrescar_repuestos()
                    st.session_state.ot_carrito = []
                    if error_stock:
                        st.warning("⚠️ La OT se creó, pero algún repuesto no pudo descontarse por falta de stock. Revisalo en 'Modificar OT Existente'.")
                    else:
                        st.success(f"✅ Orden {codigo_generado} registrada exitosamente.")
                    if tecnico_sel == "Sin asignar (backlog compartido)":
                        st.info("📌 Quedó en el backlog compartido — cualquier técnico la puede tomar desde 'Mis OTs'.")
                    if requiere_permiso and not permiso_emitido:
                        st.warning("⚠️ Recordá emitir y firmar el Permiso de Trabajo antes de iniciar la tarea en campo.")
                    st.rerun()

    # --- MODIFICAR OT EXISTENTE (cambiar estado, asignar repuestos, cerrar, bloquear) ---
    st.markdown("---")
    st.subheader("✏️ Modificar OT Existente")

    if not ots:
        st.caption("Todavía no hay OTs creadas para modificar.")
    else:
        map_m_nombre = {m["id"]: m["nombre"] for m in maquinas}
        dict_ots = {f"{o.get('codigo')} — {map_m_nombre.get(o.get('maquina_id'), '?')} ({o.get('estado')})": o for o in ots}
        ot_sel_key = st.selectbox("Seleccionar OT", options=list(dict_ots.keys()))
        ot_actual = dict_ots[ot_sel_key]

        col1, col2 = st.columns(2)
        with col1:
            nuevo_estado = st.selectbox(
                "Estado", ESTADOS_OT,
                index=ESTADOS_OT.index(ot_actual.get("estado")) if ot_actual.get("estado") in ESTADOS_OT else 0,
                key=f"edit_estado_{ot_actual.get('id')}"
            )
            dict_tecnicos_edit = {t["nombre"]: t["id"] for t in tecnicos}
            nombre_tec_actual = next((n for n, i in dict_tecnicos_edit.items() if i == ot_actual.get("tecnico_id")), "Sin asignar")
            opciones_tec = ["Sin asignar"] + list(dict_tecnicos_edit.keys())
            tecnico_edit_sel = st.selectbox(
                "Técnico Asignado", opciones_tec,
                index=opciones_tec.index(nombre_tec_actual) if nombre_tec_actual in opciones_tec else 0,
                key=f"edit_tec_{ot_actual.get('id')}"
            )
            edit_ot_oo = st.text_input(
                "N° OT OpenOrange", value=ot_actual.get("nro_ot_openorange") or "",
                key=f"edit_ot_oo_{ot_actual.get('id')}"
            )
        with col2:
            nuevo_costo_mo = st.number_input(
                "Costo de Mano de Obra (Gs.)", min_value=0, step=1000,
                value=int(ot_actual.get("costo_mano_obra", 0) or 0),
                key=f"edit_costo_{ot_actual.get('id')}"
            )
            edit_oc_oo = st.text_input(
                "N° OC OpenOrange asociada", value=ot_actual.get("nro_oc_openorange") or "",
                key=f"edit_oc_oo_{ot_actual.get('id')}"
            )
            if ot_actual.get("requiere_permiso_trabajo"):
                permiso_emitido_edit = st.checkbox(
                    "✅ Permiso de trabajo emitido y firmado",
                    value=bool(ot_actual.get("permiso_trabajo_emitido")),
                    key=f"edit_permiso_{ot_actual.get('id')}"
                )
            else:
                permiso_emitido_edit = ot_actual.get("permiso_trabajo_emitido", False)

        motivo_bloqueo_edit = ot_actual.get("motivo_bloqueo", "") or ""
        if nuevo_estado == "Bloqueada":
            motivo_bloqueo_edit = st.text_area(
                "🚧 Motivo del bloqueo *", value=motivo_bloqueo_edit,
                placeholder="Ej: Falta rodamiento SKF 6204, esperando aprobación de compra, etc.",
                key=f"motivo_bloqueo_{ot_actual.get('id')}"
            )

        with st.expander(f"🔩 Agregar repuestos usados en {ot_actual.get('codigo')}"):
            if repuestos:
                dict_rep_edit = {r["nombre"]: r for r in repuestos}
                c1, c2, c3 = st.columns([0.5, 0.25, 0.25])
                rep_sel_edit = c1.selectbox("Repuesto", list(dict_rep_edit.keys()), key=f"edit_rep_sel_{ot_actual.get('id')}")
                cant_sel_edit = c2.number_input("Cantidad", min_value=1, step=1, key=f"edit_rep_cant_{ot_actual.get('id')}")
                c3.write("")
                c3.write("")
                if c3.button("➕ Registrar consumo", key=f"edit_rep_btn_{ot_actual.get('id')}"):
                    rep = dict_rep_edit[rep_sel_edit]
                    # NUEVO: misma función RPC transaccional que en la creación de OT.
                    try:
                        consumir_repuesto_seguro(ot_actual.get("id"), rep["id"], cant_sel_edit)
                        _refrescar_repuestos()
                        st.success(f"✅ Se descontaron {cant_sel_edit} unidad(es) de '{rep['nombre']}' del stock.")
                        st.rerun()
                    except ValueError:
                        st.error(f"❌ Stock insuficiente para '{rep['nombre']}' en este instante.")
            else:
                st.caption("No hay repuestos cargados en el inventario.")

        if st.button("💾 Guardar Cambios en la OT", key=f"edit_save_{ot_actual.get('id')}"):
            if nuevo_estado == "Bloqueada" and not motivo_bloqueo_edit.strip():
                st.error("❌ Ingresá el motivo del bloqueo antes de guardar.")
            else:
                patch = {
                    "estado": nuevo_estado,
                    "tecnico_id": dict_tecnicos_edit.get(tecnico_edit_sel) if tecnico_edit_sel != "Sin asignar" else None,
                    "costo_mano_obra": nuevo_costo_mo,
                    "permiso_trabajo_emitido": permiso_emitido_edit,
                    "motivo_bloqueo": motivo_bloqueo_edit if nuevo_estado == "Bloqueada" else None,
                    "nro_ot_openorange": edit_ot_oo.strip() or None,
                    "nro_oc_openorange": edit_oc_oo.strip() or None
                }
                recien_completada = (nuevo_estado == "Completada" and ot_actual.get("estado") != "Completada")
                if nuevo_estado == "Completada" and not ot_actual.get("fecha_fin"):
                    patch["fecha_fin"] = datetime.now().isoformat()
                update_ot(ot_actual.get("id"), patch)
                if recien_completada:
                    _sincronizar_cierre_preventivo(ot_actual)
                _refrescar_ots()
                st.success(f"✅ {ot_actual.get('codigo')} actualizada correctamente.")
                st.rerun()

        # ------------------------------------------------------------
        # NUEVO: Bloque de Superusuario — solo visible para rol "admin".
        # Permite forzar el cierre de una OT saltándose las validaciones
        # normales (motivo de bloqueo, permiso de trabajo) y eliminar
        # una OT definitivamente. Pensado para casos excepcionales
        # (OT cargada por error, decisión gerencial de cerrar igual).
        # ------------------------------------------------------------
        if es_admin(usuario):
            st.markdown("---")
            st.markdown("##### 🛡️ Acciones de Administrador")
            st.caption("Estas acciones ignoran las validaciones normales del flujo de OT. Usalas con criterio.")
            col_forzar, col_borrar = st.columns(2)
            with col_forzar:
                if st.button("⚡ Forzar Cierre de esta OT", key=f"forzar_{ot_actual.get('id')}"):
                    update_ot(ot_actual.get("id"), {
                        "estado": "Completada",
                        "fecha_fin": datetime.now().isoformat(),
                        "motivo_bloqueo": None
                    })
                    _sincronizar_cierre_preventivo(ot_actual)
                    _refrescar_ots()
                    st.warning(f"⚡ {ot_actual.get('codigo')} fue cerrada por un administrador, sin pasar por las validaciones normales.")
                    st.rerun()
            with col_borrar:
                confirmar_borrado = st.checkbox("Confirmo que quiero eliminar esta OT", key=f"confirmar_borrado_{ot_actual.get('id')}")
                if st.button("🗑️ Eliminar OT Definitivamente", key=f"borrar_{ot_actual.get('id')}", disabled=not confirmar_borrado):
                    delete_ot(ot_actual.get
