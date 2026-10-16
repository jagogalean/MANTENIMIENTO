import streamlit as st
from datetime import datetime
from database.conection import (
    get_solicitudes_compra, insert_solicitud_compra, update_solicitud_compra,
    subir_foto_solicitud_compra, get_repuestos, insert_repuesto, update_repuesto
)
from database.email_utils import enviar_email_solicitud_compra

ESTADOS = ["Pendiente", "Aprobado", "Comprado", "Rechazado"]
ESTADO_COLOR = {"Pendiente": "#F59E0B", "Aprobado": "#38BDF8", "Comprado": "#10B981", "Rechazado": "#EF4444"}
PRIORIDAD_COLOR = {"Baja": "#38BDF8", "Media": "#F59E0B", "Alta": "#EF4444", "Urgente": "#B91C1C"}
MAX_FOTOS = 3


def render_solicitudes_compra(usuario):
    st.title("🛒 Solicitud de Compra (Integrado con OpenOrange)")
    st.write("Cargá los requerimientos para tus compras locales o importaciones. Al marcarlo como 'Comprado', impacta automáticamente en tu stock.")

    maquinas = st.session_state.get("maquinas", [])
    dict_maquinas = {m["nombre"]: m["id"] for m in maquinas}
    repuestos = get_repuestos()

    with st.expander("+ Nueva Solicitud de Compra", expanded=False):
        with st.form("form_solicitud_compra", clear_on_submit=True):
            st.markdown("##### 📄 Datos Generales e Identificación")
            col1, col2, col3 = st.columns(3)
            item = col1.text_input("Ítem / Descripción *", placeholder="Ej: Insulating wool-felt sleeve")
            codigo_articulo_oo = col2.text_input("Código Artículo OpenOrange", placeholder="Ej: 97039804")
            unidad = col3.text_input("Unidad", placeholder="Ej: PC, metros, kg")

            col4, col5, col6 = st.columns(3)
            cantidad = col4.number_input("Cantidad *", min_value=0.0, step=1.0, value=1.0)
            prioridad = col5.selectbox("Prioridad", ["Baja", "Media", "Alta", "Urgente"], index=1)
            concepto = col6.selectbox("Concepto / Tipo", ["Local", "Importación", "Urgente Planta"])

            col7, col8 = st.columns(2)
            nro_oc_openorange = col7.text_input("N° OC OpenOrange (Ej: 1108)", placeholder="Ej: 1108")
            nro_ot_openorange = col8.text_input("N° OT OpenOrange (si aplica)", placeholder="Ej: OT-9920")

            col9, col10 = st.columns(2)
            maquina_sel = col9.selectbox("Máquina relacionada", ["No aplica"] + list(dict_maquinas.keys()))
            fecha_necesaria = col10.date_input("Fecha en que se necesita", value=None)

            justificacion = st.text_area("Justificación / Referencia *", placeholder="Ej: Quotation N° 261001-1422")

            st.markdown("##### 💰 Datos Comerciales y Multimoneda")
            col11, col12, col13 = st.columns(3)
            proveedor_sugerido = col11.text_input("Proveedor sugerido", placeholder="Ej: Reifenhäuser Latina")
            moneda = col12.selectbox("Moneda", ["PYG", "EUR", "USD", "BRL"])
            precio_estimado = col13.number_input("Precio Unitario Estimado", min_value=0.0, step=1.0)

            col14, col15, col16 = st.columns(3)
            costo_flete = col14.number_input("Flete", min_value=0.0, step=1.0)
            costo_seguro = col15.number_input("Seguro", min_value=0.0, step=1.0)
            condicion_pago = col16.text_input("Condición de Pago", placeholder="Ej: 30 days")

            link_referencia = st.text_input("Link o referencia web / Cotización")

            st.markdown("##### ✍️ Circuito de Firmas (Vitopel)")
            col17, col18, col19 = st.columns(3)
            hecho_por = col17.text_input("Hecho por", value=usuario.get("nombre", ""))
            revisado_por = col18.text_input("Revisado por", value="Romina Jara")
            autorizado_por = col19.text_input("Autorizado por", value="Luis Caballero")

            fotos_subidas = st.file_uploader(
                f"Adjuntar Orden de Compra PDF / Fotos (hasta {MAX_FOTOS})", type=["png", "jpg", "jpeg", "pdf"],
                accept_multiple_files=True
            )

            submit = st.form_submit_button("📨 Enviar Solicitud de Compra")
            if submit:
                if not item.strip() or not justificacion.strip() or cantidad <= 0:
                    st.error("❌ Completá al menos el ítem, la cantidad y la justificación.")
                elif fotos_subidas and len(fotos_subidas) > MAX_FOTOS:
                    st.error(f"❌ Máximo {MAX_FOTOS} archivos por solicitud.")
                else:
                    maquina_id = dict_maquinas.get(maquina_sel) if maquina_sel != "No aplica" else None
                    monto_total = (cantidad * precio_estimado) + costo_flete + costo_seguro
                    
                    payload = {
                        "item": item.strip(),
                        "cantidad": cantidad,
                        "unidad": unidad.strip() or None,
                        "justificacion": justificacion.strip(),
                        "maquina_id": maquina_id,
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
                        "condicion_pago": condicion_pago.strip() or None,
                        "costo_flete": costo_flete,
                        "costo_seguro": costo_seguro,
                        "monto_total_oc": monto_total,
                        "hecho_por": hecho_por.strip() or None,
                        "revisado_por": revisado_por.strip() or None,
                        "autorizado_por": autorizado_por.strip() or None,
                        "estado": "Pendiente",
                        "solicitante": usuario.get("nombre"),
                        "fecha_solicitud": datetime.now().isoformat()
                    }
                    creada = insert_solicitud_compra(payload)
                    solicitud_id = creada[0]["id"] if creada else None

                    fotos_para_email = []
                    urls_fotos = []
                    for foto in (fotos_subidas or [])[:MAX_FOTOS]:
                        contenido = foto.getvalue()
                        try:
                            url = subir_foto_solicitud_compra(solicitud_id, foto.name, contenido, foto.type)
                            urls_fotos.append(url)
                        except Exception:
                            pass
                        fotos_para_email.append((foto.name, contenido, foto.type))

                    if urls_fotos:
                        update_solicitud_compra(solicitud_id, {"foto_urls": urls_fotos})

                    payload["maquina_nombre"] = maquina_sel if maquina_id else None
                    try:
                        enviar_email_solicitud_compra(payload, fotos_para_email)
                        st.success("✅ Solicitud guardada y enviada por correo a Compras.")
                    except Exception as e:
                        st.warning(f"⚠️ La solicitud quedó guardada en el sistema, pero no se pudo enviar el correo automáticamente. Detalle: {e}")
                    st.rerun()

    st.markdown("---")
    st.subheader("Seguimiento de Solicitudes")

    solicitudes = get_solicitudes_compra()
    if not solicitudes:
        st.info("Todavía no hay solicitudes de compra cargadas.")
        return

    map_maquina = {m["id"]: m["nombre"] for m in maquinas}

    filtro_estado = st.selectbox("Filtrar por estado", ["Todos"] + ESTADOS, key="filtro_estado_compra")
    solicitudes_filtradas = solicitudes if filtro_estado == "Todos" else [s for s in solicitudes if s.get("estado") == filtro_estado]

    for s in solicitudes_filtradas:
        color_estado = ESTADO_COLOR.get(s.get("estado"), "#7C8894")
        color_prioridad = PRIORIDAD_COLOR.get(s.get("prioridad"), "#7C8894")
        m_nombre = map_maquina.get(s.get("maquina_id"))
        oc_oo = f" · OC OpenOrange #{s.get('nro_oc_openorange')}" if s.get("nro_oc_openorange") else ""

        st.markdown(f"""
        <div class='industrial-panel' style='border-color:{color_estado};'>
            <strong>{s.get('item')}</strong> {oc_oo} — {s.get('cantidad')} {s.get('unidad') or ''} 
            ({s.get('moneda', 'PYG')} {s.get('monto_total_oc', 0):,.2f})
            · <span style='color:{color_prioridad}; font-weight:bold;'>{s.get('prioridad')}</span><br>
            <small>{'Máquina: ' + m_nombre + ' · ' if m_nombre else ''}Solicitado por: {s.get('solicitante') or '—'} · {s.get('fecha_solicitud', '')[:10]}</small><br>
            <span style='color:{color_estado}; font-weight:bold;'>Estado: {s.get('estado')}</span>
        </div>
        """, unsafe_allow_html=True)

        with st.expander(f"Ver detalle / gestionar — {s.get('item')} (OC {s.get('nro_oc_openorange') or 'S/N'})"):
            c_info1, c_info2 = st.columns(2)
            c_info1.write(f"**Justificación:** {s.get('justificacion')}")
            c_info2.write(f"**Concepto:** {s.get('concepto')} | **Condición pago:** {s.get('condicion_pago') or '—'}")
            if s.get("codigo_articulo_oo"):
                st.write(f"**Código Artículo OpenOrange:** `{s.get('codigo_articulo_oo')}`")
            if s.get("proveedor_sugerido"):
                st.write(f"**Proveedor:** {s.get('proveedor_sugerido')}")
            if s.get("hecho_por") or s.get("autorizado_por"):
                st.write(f"✍️ **Firmas:** Hecho: {s.get('hecho_por') or '—'} | Revisado: {s.get('revisado_por') or '—'} | Autorizado: {s.get('autorizado_por') or '—'}")

            if s.get("foto_urls"):
                st.image(s.get("foto_urls"), width=200)

            if usuario.get("rol") == "admin":
                nuevo_estado = st.selectbox(
                    "Cambiar estado", ESTADOS,
                    index=ESTADOS.index(s.get("estado")) if s.get("estado") in ESTADOS else 0,
                    key=f"estado_compra_{s.get('id')}"
                )
                
                # Opción para sumar al stock si pasa a "Comprado" y todavía no se sumó
                sumar_stock = False
                repuesto_destino_id = None
                if nuevo_estado == "Comprado" and not s.get("sumado_al_stock"):
                    st.markdown("##### 📦 Impacto automático en inventario")
                    sumar_stock = st.checkbox("Sumar esta cantidad al stock actual del repuesto", value=True, key=f"sum_stk_{s.get('id')}")
                    if sumar_stock:
                        opciones_rep = {r["nombre"] + " (" + r["codigo_interno"] + ")": r["id"] for r in repuestos}
                        opciones_rep["+ Crear nuevo repuesto con estos datos"] = "NUEVO"
                        rep_elegido = st.selectbox("Vincular a repuesto de stock:", list(opciones_rep.keys()), key=f"rep_el_{s.get('id')}")
                        if rep_elegido != "+ Crear nuevo repuesto con estos datos":
                            repuesto_destino_id = opciones_rep[rep_elegido]

                if st.button("💾 Guardar cambios de compra", key=f"save_estado_compra_{s.get('id')}"):
                    patch = {"estado": nuevo_estado}
                    
                    # Lógica para sumar al stock automáticamente
                    if nuevo_estado == "Comprado" and sumar_stock and not s.get("sumado_al_stock"):
                        cant_comprada = int(s.get("cantidad", 0) or 0)
                        precio_unit = float(s.get("precio_estimado", 0) or 0)
                        
                        if repuesto_destino_id == "NUEVO" or not repuestos:
                            # Crear el repuesto nuevo automáticamente
                            nuevo_rep = {
                                "nombre": s.get("item"),
                                "codigo_interno": s.get("codigo_articulo_oo") or f"OO-{s.get('nro_oc_openorange', 'GEN')}",
                                "codigo_openorange": s.get("codigo_articulo
