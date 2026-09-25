import streamlit as st
from datetime import datetime
from database.conection import (
    get_solicitudes_compra, insert_solicitud_compra, update_solicitud_compra,
    subir_foto_solicitud_compra
)
from database.email_utils import enviar_email_solicitud_compra

ESTADOS = ["Pendiente", "Aprobado", "Comprado", "Rechazado"]
ESTADO_COLOR = {"Pendiente": "#F59E0B", "Aprobado": "#38BDF8", "Comprado": "#10B981", "Rechazado": "#EF4444"}
PRIORIDAD_COLOR = {"Baja": "#38BDF8", "Media": "#F59E0B", "Alta": "#EF4444", "Urgente": "#B91C1C"}
MAX_FOTOS = 3


def render_solicitudes_compra(usuario):
    st.title("🛒 Solicitud de Compra")
    st.write("Cargá lo que necesitás — se guarda en el sistema y se manda por correo a Compras en el mismo paso.")

    maquinas = st.session_state.get("maquinas", [])
    dict_maquinas = {m["nombre"]: m["id"] for m in maquinas}

    with st.expander("+ Nueva Solicitud de Compra", expanded=False):
        with st.form("form_solicitud_compra", clear_on_submit=True):
            col1, col2 = st.columns(2)
            item = col1.text_input("Ítem / Descripción *", placeholder="Ej: Rodamiento SKF 6204")
            unidad = col2.text_input("Unidad de medida", placeholder="Ej: unidad, metros, litros, kg")

            col3, col4 = st.columns(2)
            cantidad = col3.number_input("Cantidad *", min_value=0.0, step=1.0)
            prioridad = col4.selectbox("Prioridad", ["Baja", "Media", "Alta", "Urgente"], index=1)

            col5, col6 = st.columns(2)
            maquina_sel = col5.selectbox("Máquina relacionada (opcional)", ["No aplica"] + list(dict_maquinas.keys()))
            fecha_necesaria = col6.date_input("Fecha en que se necesita", value=None)

            justificacion = st.text_area("Justificación *", placeholder="¿Para qué se necesita? ¿Qué pasa si no se compra?")

            st.markdown("**Datos comerciales (si los tenés a mano, opcional)**")
            col7, col8 = st.columns(2)
            proveedor_sugerido = col7.text_input("Proveedor sugerido")
            precio_estimado = col8.number_input("Precio estimado (Gs.)", min_value=0, step=1000)
            link_referencia = st.text_input("Link o referencia del producto")

            fotos_subidas = st.file_uploader(
                f"Fotos (hasta {MAX_FOTOS})", type=["png", "jpg", "jpeg"],
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
                        "estado": "Pendiente",
                        "solicitante": usuario.get("nombre"),
                        "fecha_solicitud": datetime.now().isoformat()
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

    map_maquina = {m["id"]: m["nombre"] for m in maquinas}

    filtro_estado = st.selectbox("Filtrar por estado", ["Todos"] + ESTADOS, key="filtro_estado_compra")
    solicitudes_filtradas = solicitudes if filtro_estado == "Todos" else [s for s in solicitudes if s.get("estado") == filtro_estado]

    for s in solicitudes_filtradas:
        color_estado = ESTADO_COLOR.get(s.get("estado"), "#7C8894")
        color_prioridad = PRIORIDAD_COLOR.get(s.get("prioridad"), "#7C8894")
        m_nombre = map_maquina.get(s.get("maquina_id"))

        st.markdown(f"""
        <div class='industrial-panel' style='border-color:{color_estado};'>
            <strong>{s.get('item')}</strong> — {s.get('cantidad')} {s.get('unidad') or ''}
            · <span style='color:{color_prioridad}; font-weight:bold;'>{s.get('prioridad')}</span><br>
            <small>{'Máquina: ' + m_nombre + ' · ' if m_nombre else ''}Solicitado por: {s.get('solicitante') or '—'} · {s.get('fecha_solicitud', '')[:10]}</small><br>
            <span style='color:{color_estado}; font-weight:bold;'>Estado: {s.get('estado')}</span>
        </div>
        """, unsafe_allow_html=True)

        with st.expander(f"Ver detalle / gestionar — {s.get('item')}"):
            st.write(f"**Justificación:** {s.get('justificacion')}")
            if s.get("proveedor_sugerido"):
                st.write(f"**Proveedor sugerido:** {s.get('proveedor_sugerido')}")
            if s.get("precio_estimado"):
                st.write(f"**Precio estimado:** Gs. {s.get('precio_estimado'):,.0f}".replace(",", "."))
            if s.get("link_referencia"):
                st.write(f"**Referencia:** {s.get('link_referencia')}")
            if s.get("foto_urls"):
                st.image(s.get("foto_urls"), width=150)

            if usuario.get("rol") == "admin":
                nuevo_estado = st.selectbox(
                    "Cambiar estado", ESTADOS,
                    index=ESTADOS.index(s.get("estado")) if s.get("estado") in ESTADOS else 0,
                    key=f"estado_compra_{s.get('id')}"
                )
                if st.button("💾 Guardar estado", key=f"save_estado_compra_{s.get('id')}"):
                    update_solicitud_compra(s.get("id"), {"estado": nuevo_estado})
                    st.success("✅ Estado actualizado.")
                    st.rerun()
