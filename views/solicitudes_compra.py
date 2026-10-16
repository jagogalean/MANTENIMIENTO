import streamlit as st
from datetime import datetime
from database.conection import (
    get_solicitudes_compra, insert_solicitud_compra, update_solicitud_compra,
    subir_foto_solicitud_compra, get_repuestos, insert_repuesto, update_repuesto,
    get_repuestos_cached, get_ots, update_ot, get_ots_cached
)
from database.email_utils import enviar_email_solicitud_compra

ESTADOS = ["Pendiente", "Aprobado", "Comprado", "Rechazado"]
ESTADO_COLOR = {"Pendiente": "#F59E0B", "Aprobado": "#38BDF8", "Comprado": "#10B981", "Rechazado": "#EF4444"}
PRIORIDAD_COLOR = {"Baja": "#38BDF8", "Media": "#F59E0B", "Alta": "#EF4444", "Urgente": "#B91C1C"}
MAX_FOTOS = 3


def render_solicitudes_compra(usuario):
    st.title("🛒 Solicitud de Compra (Integrado con OpenOrange)")
    st.write("Cargá lo que necesitás — se guarda en el sistema, se vincula con OpenOrange / OTs y se manda por correo a Compras en el mismo paso.")

    maquinas = st.session_state.get("maquinas", [])
    dict_maquinas = {m["nombre"]: m["id"] for m in maquinas}
    map_maquina = {m["id"]: m["nombre"] for m in maquinas}
    repuestos = get_repuestos()
    ots_actuales = get_ots()

    # Diccionario de OTs activas o bloqueadas para poder vincular la compra
    ots_abiertas = [o for o in ots_actuales if o.get("estado") != "Completada"]
    dict_ots_vincular = {
        f"{o.get('codigo')} — {map_maquina.get(o.get('maquina_id'), '?')} ({o.get('estado')})": o["id"]
        for o in ots_abiertas
    }

    with st.expander("+ Nueva Solicitud de Compra", expanded=False):
        with st.form("form_solicitud_compra", clear_on_submit=True):
            st.markdown("##### 📄 Datos del Ítem y Vínculo con OpenOrange / OT")
            col1, col2, col3 = st.columns(3)
            item = col1.text_input("Ítem / Descripción *", placeholder="Ej: Insulating wool-felt sleeve for basket")
            codigo_articulo_oo = col2.text_input("Artículo Nro (OpenOrange)", placeholder="Ej: 97039804")
            unidad = col3.text_input("Unidad de medida", placeholder="Ej: PC, unidad, metros, kg")

            col4, col5, col6 = st.columns(3)
            cantidad = col4.number_input("Cantidad *", min_value=0.0, step=1.0, value=1.0)
            prioridad = col5.selectbox("Prioridad", ["Baja", "Media", "Alta", "Urgente"], index=1)
            concepto = col6.selectbox("Concepto", ["Local", "Importación", "Servicio Técnico"])

            col7, col8, col9 = st.columns(3)
            nro_oc_openorange = col7.text_input("N° Orden de Compra OpenOrange", placeholder="Ej: 1108")
            nro_ot_openorange = col8.text_input("N° OT en OpenOrange (opcional)", placeholder="Ej: OT-OO-4510")
            ot_interna_sel = col9.selectbox(
                "OT Interna vinculada (opcional)",
                ["Ninguna"] + list(dict_ots_vincular.keys()),
                help="Si esta compra es para destrabar una OT interna bloqueada o pendiente, elegila acá."
            )

            col10, col11 = st.columns(2)
            maquina_sel = col10.selectbox("Máquina relacionada (opcional)", ["No aplica"] + list(dict_maquinas.keys()))
            fecha_necesaria = col11.date_input("Fecha en que se necesita", value=None)

            justificacion = st.text_area("Justificación *", placeholder="¿Para qué se necesita? ¿Qué pasa si no se compra?")

            st.markdown("##### 💰 Datos Comerciales y Multimoneda (Según OC OpenOrange)")
            col12, col13, col14 = st.columns(3)
            proveedor_sugerido = col12.text_input("Proveedor sugerido", placeholder="Ej: Reifenhäuser Latina SpA")
            moneda = col13.selectbox("Moneda", ["PYG", "EUR", "USD", "BRL"])
            precio_estimado = col14.number_input("Precio Unitario", min_value=0.0, step=0.01)

            col15, col16, col17 = st.columns(3)
            costo_flete = col15.number_input("Flete (en la misma moneda)", min_value=0.0, step=0.01)
            costo_seguro = col16.number_input("Seguro (en la misma moneda)", min_value=0.0, step=0.01)
            condicion_pago = col17.text_input("Condición de Pago", placeholder="Ej: 30 days")

            col18, col19 = st.columns(2)
            cotizacion_referencia = col18.text_input("Referencia / Quotation N°", placeholder="Ej: Quotation N° 261001-1422")
            link_referencia = col19.text_input("Link o referencia del producto")

            st.markdown("##### ✍️ Circuito de Firmas (Vitopel)")
            col20, col21, col22 = st.columns(3)
            hecho_por = col20.text_input("Hecho por", placeholder="Ej: Belén Morales")
            revisado_por = col21.text_input("Revisado por", value="Romina Jara")
            autorizado_por = col22.text_input("Autorizado por", value="Luis Caballero")

            fotos_subidas = st.file_uploader(
                f"Fotos de muestra o captura de la OC (hasta {MAX_FOTOS} imágenes PNG/JPG)",
                type=["png", "jpg", "jpeg"],
                accept_multiple_files=True
            )

            submit = st.form_submit_button("📨 Enviar Solicitud")
            if submit:
                if not item.strip() or not justificacion.strip() or cantidad <= 0:
                    st.error("❌ Completá al menos el ítem, la cantidad y la justificación.")
                elif fotos_subidas and len(fotos_subidas) > MAX_FOTOS:
                    st.error(f"❌ Máximo {MAX_FOTOS} fotos por solicitud.")
                else:
                    maquina_id = dict_maquinas.get(maquina_sel) if maquina_sel != "No aplica" else None
                    ot_id_vinc = dict_ots_vincular.get(ot_interna_sel) if ot_interna_sel != "Ninguna" else None
                    subtotal = float(cantidad) * float(precio_estimado or 0)
                    monto_total_oc = subtotal + float(costo_flete or 0) + float(costo_seguro or 0)

                    payload = {
                        "item": item.strip(),
                        "cantidad": cantidad,
                        "unidad": unidad.strip() or None,
                        "justificacion": justificacion.strip(),
                        "maquina_id": maquina_id,
                        "ot_id": ot_id_vinc,
                        "prioridad": prioridad,
                        "fecha_necesaria": fecha_necesaria.strftime("%Y-%m-%d") if fecha_necesaria else None,
                        "proveedor_sugerido": proveedor_sugerido.strip() or None,
                        "precio_estimado": precio_estimado or None,
                        "link_referencia": link_referencia.strip() or None,
                        "nro_oc_openorange": nro_oc_openorange.strip() or None,
                        "nro_ot_openorange": nro_ot_openorange.strip() or None,
                        "codigo_articulo_oo": codigo_articulo_oo.strip() or None,
                        "concepto": concepto,
                        "moneda": moneda,
                        "cotizacion_referencia": cotizacion_referencia.strip() or None,
                        "condicion_pago": condicion_pago.strip() or None,
                        "costo_flete": costo_flete or 0,
                        "costo_seguro": costo_seguro or 0,
                        "monto_total_oc": monto_total_oc,
                        "hecho_por": hecho_por.strip() or None,
                        "revisado_por": revisado_por.strip() or None,
                        "autorizado_por": autorizado_por.strip() or None,
                        "estado": "Pendiente",
                        "solicitante": usuario.get("nombre"),
                        "fecha_solicitud": datetime.now().isoformat(),
                        "sumado_al_stock": False
                    }
                    creada = insert_solicitud_compra(payload)
                    solicitud_id = creada[0]["id"] if creada else None

                    # Subir fotos (si hay) y armar la lista para adjuntar al mail
                    fotos_para_email = []
                    urls_fotos = []
                    for foto in (fotos_subidas or [])[:MAX_FOTOS]:
                        contenido = foto.getvalue()
                        try:
                            url = subir_foto_solicitud_compra(solicitud_id, foto.name, contenido, foto.type)
                            urls_fotos.append(url)
                        except Exception:
                            pass  # si falla subir una foto puntual, no frenamos el resto del proceso
                        fotos_para_email.append((foto.name, contenido, foto.type))

                    if urls_fotos:
                        update_solicitud_compra(solicitud_id, {"foto_urls": urls_fotos})

                    payload["maquina_nombre"] = maquina_sel if maquina_id else None
                    try:
                        enviar_email_solicitud_compra(payload, fotos_para_email)
                        st.success("✅ Solicitud guardada y enviada por correo a Compras.")
                    except Exception as e:
                        st.warning(f"⚠️ La solicitud quedó guardada en el sistema, pero no se pudo enviar el correo automáticamente. Avisá a Compras por otro medio. Detalle: {e}")
                    st.rerun()

    st.markdown("---")
    st.subheader("Seguimiento de Solicitudes")

    solicitudes = get_solicitudes_compra()
    if not solicitudes:
        st.info("Todavía no hay solicitudes de compra cargadas.")
        return

    map_ot_cod = {o["id"]: o.get("codigo") for o in ots_actuales}

    filtro_estado = st.selectbox("Filtrar por estado", ["Todos"] + ESTADOS, key="filtro_estado_compra")
    solicitudes_filtradas = solicitudes if filtro_estado == "Todos" else [s for s in solicitudes if s.get("estado") == filtro_estado]

    for s in solicitudes_filtradas:
        color_estado = ESTADO_COLOR.get(s.get("estado"), "#7C8894")
        color_prioridad = PRIORIDAD_COLOR.get(s.get("prioridad"), "#7C8894")
        m_nombre = map_maquina.get(s.get("maquina_id"))
        ot_cod = map_ot_cod.get(s.get("ot_id"))
        moneda_sc = s.get("moneda") or "PYG"
        monto_sc = s.get("monto_total_oc") or s.get("precio_estimado") or 0

        etiquetas_extra = []
        if s.get("nro_oc_openorange"):
            etiquetas_extra.append(f"OC OpenOrange #{s.get('nro_oc_openorange')}")
        if s.get("codigo_articulo_oo"):
            etiquetas_extra.append(f"Art: {s.get('codigo_articulo_oo')}")
        if ot_cod:
            etiquetas_extra.append(f"OT: {ot_cod}")
        txt_extra = " · ".join(etiquetas_extra)

        st.markdown(f"""
        <div class='industrial-panel' style='border-color:{color_estado};'>
            <strong>{s.get('item')}</strong> — {s.get('cantidad')} {s.get('unidad') or ''}
            · <span style='color:{color_prioridad}; font-weight:bold;'>{s.get('prioridad')}</span>
            {f" · <small style='color:#38BDF8;'>[{txt_extra}]</small>" if txt_extra else ""}<br>
            <small>{'Máquina: ' + m_nombre + ' · ' if m_nombre else ''}Solicitado por: {s.get('solicitante') or '—'} · {s.get('fecha_solicitud', '')[:10]} · Total: {moneda_sc} {monto_sc:,.2f}</small><br>
            <span style='color:{color_estado}; font-weight:bold;'>Estado: {s.get('estado')}</span>
            {" · ✅ <em>Ya sumado al Stock</em>" if s.get("sumado_al_stock") else ""}
        </div>
        """, unsafe_allow_html=True)

        with st.expander(f"Ver detalle / gestionar — {s.get('item')}"):
            st.write(f"**Justificación:** {s.get('justificacion')}")
            if s.get("proveedor_sugerido"):
                st.write(f"**Proveedor sugerido:** {s.get('proveedor_sugerido')} ({s.get('concepto') or 'Local'})")
            if s.get("cotizacion_referencia") or s.get("condicion_pago"):
                st.write(f"**Referencia / Cotización:** {s.get('cotizacion_referencia') or '—'} · **Pago:** {s.get('condicion_pago') or '—'}")
            if s.get("precio_estimado"):
                st.write(
                    f"**Precio Unit.:** {moneda_sc} {float(s.get('precio_estimado') or 0):,.2f} | "
                    f"**Flete:** {moneda_sc} {float(s.get('costo_flete') or 0):,.2f} | "
                    f"**Seguro:** {moneda_sc} {float(s.get('costo_seguro') or 0):,.2f} | "
                    f"**Total OC:** {moneda_sc} {float(s.get('monto_total_oc') or 0):,.2f}"
                )
            if s.get("hecho_por") or s.get("revisado_por") or s.get("autorizado_por"):
                st.write(f"**Firmas:** Hecho por: `{s.get('hecho_por') or '—'}` · Revisado por: `{s.get('revisado_por') or '—'}` · Autorizado por: `{s.get('autorizado_por') or '—'}`")
            if s.get("link_referencia"):
                st.write(f"**Referencia web:** {s.get('link_referencia')}")
            if s.get("foto_urls"):
                st.image(s.get("foto_urls"), width=180)

            if usuario.get("rol") == "admin":
                st.markdown("---")
                col_adm1, col_adm2 = st.columns(2)
                nuevo_estado = col_adm1.selectbox(
                    "Cambiar estado", ESTADOS,
                    index=ESTADOS.index(s.get("estado")) if s.get("estado") in ESTADOS else 0,
                    key=f"estado_compra_{s.get('id')}"
                )
                nueva_oc_oo = col_adm2.text_input(
                    "N° OC OpenOrange (si ya salió la OC)",
                    value=s.get("nro_oc_openorange") or "",
                    key=f"oc_oo_edit_{s.get('id')}"
                )

                # Si pasa a "Comprado" y aún no fue sumado al stock, ofrecer sumarlo con 1 clic
                sumar_stock = False
                modo_stock = None
                repuesto_id_elegido = None
                costo_unit_gs = int(float(s.get("precio_estimado") or 0))

                if nuevo_estado == "Comprado" and not s.get("sumado_al_stock"):
                    st.markdown("##### 📦 Recepción en Almacén (Impacto en Stock)")
                    sumar_stock = st.checkbox(
                        f"Sumar {s.get('cantidad')} unidad(es) al inventario de Repuestos ahora",
                        value=True,
                        key=f"chk_sum_stk_{s.get('id')}"
                    )
                    if sumar_stock:
                        opciones_rep = {"➕ Crear como repuesto NUEVO en el inventario": "NUEVO"}
                        for r in repuestos:
                            etiqueta = f"{r['nombre']} [{r['codigo_interno']}] (Stock actual: {r.get('stock_actual', 0)})"
                            opciones_rep[etiqueta] = r["id"]

                        seleccion_rep = st.selectbox(
                            "¿A qué repuesto del inventario corresponde?",
                            list(opciones_rep.keys()),
                            key=f"sel_rep_stk_{s.get('id')}"
                        )
                        valor_sel = opciones_rep[seleccion_rep]
                        if valor_sel == "NUEVO":
                            modo_stock = "NUEVO"
                        else:
                            modo_stock = "EXISTENTE"
                            repuesto_id_elegido = valor_sel

                        if moneda_sc != "PYG":
                            costo_unit_gs = st.number_input(
                                f"Costo unitario convertido a Guaraníes (Gs.) para el inventario (Precio original: {moneda_sc} {s.get('precio_estimado')})",
                                min_value=0, step=1000, value=0,
                                key=f"conv_gs_{s.get('id')}"
                            )

                if st.button("💾 Guardar estado y actualizar", key=f"save_estado_compra_{s.get('id')}"):
                    patch = {
                        "estado": nuevo_estado,
                        "nro_oc_openorange": nueva_oc_oo.strip() or None
                    }

                    if nuevo_estado == "Comprado" and sumar_stock and not s.get("sumado_al_stock"):
                        cant_int = int(round(float(s.get("cantidad") or 0)))
                        if modo_stock == "NUEVO":
                            cod_interno_nuevo = (
                                s.get("codigo_articulo_oo")
                                or (f"OO-{nueva_oc_oo.strip()}" if nueva_oc_oo.strip() else f"REP-SC-{s.get('id')}")
                            )
                            creado_rep = insert_repuesto({
                                "nombre": s.get("item"),
                                "codigo_interno": cod_interno_nuevo,
                                "codigo_openorange": s.get("codigo_articulo_oo"),
                                "stock_actual": cant_int,
                                "stock_minimo": 1,
                                "costo_unitario": int(costo_unit_gs)
                            })
                            if creado_rep:
                                patch["repuesto_id"] = creado_rep[0].get("id")
                        elif modo_stock == "EXISTENTE" and repuesto_id_elegido:
                            rep_obj = next((r for r in repuestos if r["id"] == repuesto_id_elegido), None)
                            if rep_obj:
                                nuevo_stock = int(rep_obj.get("stock_actual", 0)) + cant_int
                                patch_rep = {"stock_actual": nuevo_stock}
                                if costo_unit_gs > 0:
                                    patch_rep["costo_unitario"] = int(costo_unit_gs)
                                if s.get("codigo_articulo_oo") and not rep_obj.get("codigo_openorange"):
                                    patch_rep["codigo_openorange"] = s.get("codigo_articulo_oo")
                                update_repuesto(repuesto_id_elegido, patch_rep)
                                patch["repuesto_id"] = repuesto_id_elegido

                        patch["sumado_al_stock"] = True
                        patch["fecha_recepcion"] = datetime.now().strftime("%Y-%m-%d")
                        get_repuestos_cached.clear()
                        st.session_state.repuestos = get_repuestos()

                    update_solicitud_compra(s.get("id"), patch)

                    # Si estaba vinculada a una OT Bloqueada y ya se compró, ofrecer desbloquearla
                    if nuevo_estado == "Comprado" and s.get("ot_id"):
                        update_ot(s.get("ot_id"), {"estado": "Pendiente", "motivo_bloqueo": None})
                        get_ots_cached.clear()
                        st.session_state.ots = get_ots()
                        st.info(f"🔓 La OT vinculada ({ot_cod}) fue desbloqueada y pasó a estado 'Pendiente' porque ya llegó su repuesto.")

                    st.success("✅ Solicitud actualizada correctamente.")
                    st.rerun()
