import streamlit as st
import qrcode
import json
from io import BytesIO
from database.conection import (
    supabase, insert_maquina, delete_maquina, get_maquinas, update_maquina,
    insert_documento, delete_documento, get_documentos,
    insert_plan, get_planes, insert_actividad, get_actividades
)
from datetime import datetime, timedelta

CRIT_LABELS = {"A": "🔴 Crítica", "B": "🟠 Importante", "C": "🔵 Menor"}


def _obtener_url_base_automatica() -> str:
    """
    Obtiene la URL pública de la app automáticamente sin que el usuario tenga que
    escribirla cada vez:
    1) Primero mira si ya está guardada en session_state o en st.secrets['APP_URL'].
    2) Si no, intenta detectarla sola desde el navegador (st.context.headers).
    """
    if st.session_state.get("app_base_url"):
        return st.session_state["app_base_url"].rstrip("/")

    url_secret = st.secrets.get("APP_URL", "")
    if url_secret:
        return url_secret.rstrip("/")

    try:
        headers = st.context.headers
        host = headers.get("Host") or headers.get("X-Forwarded-Host")
        proto = headers.get("X-Forwarded-Proto", "https")
        if host and "localhost" not in host and "127.0.0.1" not in host:
            return f"{proto}://{host}".rstrip("/")
    except Exception:
        pass

    return "https://mi-app.streamlit.app"


def generar_qr_png(url: str) -> bytes:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def generar_pdf_etiquetas_qr(maquinas, base_url: str) -> BytesIO:
    """
    Genera un PDF listo para imprimir y recortar con las etiquetas QR de Reporte
    de Fallas (?equipo=ID) de todas las máquinas registradas.
    """
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=1.2 * cm, bottomMargin=1.2 * cm)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("Etiquetas QR de Equipos — Reporte Rápido de Fallas", styles["Title"]))
    story.append(Paragraph("Escanee el código QR con la cámara del celular para ver la ficha y reportar averías sin iniciar sesión.", styles["Normal"]))
    story.append(Spacer(1, 14))

    celda_style = ParagraphStyle("CeldaQR", parent=styles["Normal"], fontSize=10, leading=13, alignment=1)

    filas_tabla = []
    fila_actual = []

    for m in maquinas:
        url_publica = f"{base_url.rstrip('/')}/?equipo={m.get('id')}"
        qr_bytes = generar_qr_png(url_publica)
        img_qr = Image(BytesIO(qr_bytes), width=4.2 * cm, height=4.2 * cm)
        img_qr.hAlign = "CENTER"

        tag_str = f"<br/><b>Tag:</b> {m.get('tag')}" if m.get("tag") else ""
        sec_str = f"<br/><font size=8 color='#555555'>{m.get('seccion') or ''}</font>"
        texto_etiqueta = Paragraph(
            f"<b>{m.get('nombre')}</b><br/>[{m.get('codigo')}] (ID: {m.get('id')}){tag_str}{sec_str}",
            celda_style
        )

        subtabla = Table([[img_qr], [texto_etiqueta]], colWidths=[5.5 * cm])
        subtabla.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#2A323A")),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))

        fila_actual.append(subtabla)
        if len(fila_actual) == 3:
            filas_tabla.append(fila_actual)
            fila_actual = []

    if fila_actual:
        while len(fila_actual) < 3:
            fila_actual.append("")
        filas_tabla.append(fila_actual)

    if filas_tabla:
        tabla_principal = Table(filas_tabla, colWidths=[6.2 * cm, 6.2 * cm, 6.2 * cm])
        tabla_principal.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ]))
        story.append(tabla_principal)

    doc.build(story)
    buffer.seek(0)
    return buffer


def extraer_texto_pdf(archivo_pdf) -> str:
    import pdfplumber  # import perezoso: solo pesa en memoria si de verdad se analiza un manual
    texto = []
    with pdfplumber.open(archivo_pdf) as pdf:
        for pagina in pdf.pages[:40]:  # límite de 40 páginas para no exceder el contexto de la IA
            texto.append(pagina.extract_text() or "")
    return "\n".join(texto)


def generar_plan_con_ia(texto_manual: str, api_key: str):
    """Devuelve (lista_de_tareas, error). lista_de_tareas es [{'tarea':..,'frecuencia_dias':..}, ...]"""
    try:
        import google.generativeai as genai
    except ImportError:
        return None, "Falta instalar 'google-generativeai'. Agregalo a requirements.txt."

    if not api_key:
        return None, "Falta la API Key de Gemini."

    genai.configure(api_key=api_key)
    modelo = genai.GenerativeModel("gemini-2.0-flash")

    prompt = f"""Sos un ingeniero de mantenimiento industrial. Te paso el texto extraído de un
manual técnico de una máquina. Identificá las tareas de mantenimiento preventivo
recomendadas por el fabricante y su frecuencia recomendada, convertida a DÍAS
(si el manual dice "cada 500 horas" y no hay dato de uso diario, estimá una
frecuencia en días razonable para uso industrial estándar, y decilo en el
campo 'nota').

Respondé ÚNICAMENTE con JSON válido, sin texto adicional ni backticks, con esta forma exacta:
{{"tareas": [{{"tarea": "string", "frecuencia_dias": number, "nota": "string opcional"}}]}}

Si no encontrás información clara de mantenimiento preventivo en el texto, devolvé {{"tareas": []}}.

Texto del manual (puede estar incompleto o truncado):
---
{texto_manual[:15000]}
---
"""
    try:
        respuesta = modelo.generate_content(prompt)
        texto_resp = respuesta.text.strip()
        texto_resp = texto_resp.replace("```json", "").replace("```", "").strip()
        data = json.loads(texto_resp)
        return data.get("tareas", []), None
    except json.JSONDecodeError:
        return None, "La IA no devolvió un JSON válido. Probá de nuevo o con un manual más corto."
    except Exception as e:
        return None, f"No se pudo generar el plan: {e}"


def render_maquinas():
    st.title("Máquinas")
    st.write("Inventario base, criticidad operacional y generación automática de etiquetas QR.")

    url_detectada = _obtener_url_base_automatica()

    with st.expander("⚙️ URL de los códigos QR (detectada automáticamente) y Catálogo PDF"):
        nueva_url = st.text_input(
            "URL pública de tu app en Streamlit Cloud",
            value=url_detectada,
            help="Se detecta sola cuando abrís la app en Streamlit Cloud. Todos los QR usan esta dirección."
        )
        st.session_state["app_base_url"] = nueva_url.rstrip("/")

        if st.session_state.maquinas:
            pdf_qrs = generar_pdf_etiquetas_qr(st.session_state.maquinas, st.session_state["app_base_url"])
            st.download_button(
                "🖨️ Descargar Plancha PDF con TODOS los QR de Reporte de Fallas (Listo para Imprimir)",
                data=pdf_qrs,
                file_name=f"Etiquetas_QR_Maquinas_{datetime.now().strftime('%Y%m%d')}.pdf",
                mime="application/pdf",
                use_container_width=True
            )

    base_url = st.session_state.get("app_base_url") or url_detectada

    # --- MOSTRAR EL QR RECIÉN CREADO AUTOMÁTICAMENTE SI SE ACABA DE DAR DE ALTA UNA MÁQUINA ---
    maquina_recien_creada = st.session_state.get("maquina_recien_creada")
    if maquina_recien_creada:
        url_qr_nuevo = f"{base_url.rstrip('/')}/?equipo={maquina_recien_creada.get('id')}"
        qr_bytes_nuevo = generar_qr_png(url_qr_nuevo)
        st.success(f"✅ Máquina **{maquina_recien_creada.get('nombre')}** creada con éxito. Su código QR se generó automáticamente:")
        col_qr_img, col_qr_info = st.columns([0.25, 0.75])
        with col_qr_img:
            st.image(qr_bytes_nuevo, width=160)
        with col_qr_info:
            st.markdown(f"**Equipo:** {maquina_recien_creada.get('nombre')} (`{maquina_recien_creada.get('codigo')}`)")
            st.markdown(f"**Link directo para reportar fallas:** `{url_qr_nuevo}`")
            st.download_button(
                "⬇️ Descargar Etiqueta QR (PNG)",
                data=qr_bytes_nuevo,
                file_name=f"QR_Fallas_{maquina_recien_creada.get('codigo')}_{maquina_recien_creada.get('id')}.png",
                mime="image/png",
                key="dl_qr_recien_creada"
            )
            if st.button("✖️ Cerrar aviso", key="cerrar_aviso_qr"):
                del st.session_state["maquina_recien_creada"]
                st.rerun()
        st.markdown("---")

    # Formulario desplegable mediante checkbox de Streamlit
    if st.checkbox("+ Nueva Máquina"):
        with st.form("form_nueva_maquina", clear_on_submit=True):
            tag = st.text_input("Tag *", placeholder="Ej: 50000000", help="El número que va pegado físicamente en la máquina (el que lee el QR).")
            nombre = st.text_input("Nombre *", placeholder="Ej: Extrusora 02")
            codigo = st.text_input("Código Único *", placeholder="Ej: EXT-002")
            seccion = st.text_input("Sección / Área", placeholder="Ej: Planta A - Línea 2")
            criticidad = st.selectbox("Criticidad", ["A", "B", "C"], format_func=lambda x: CRIT_LABELS[x])
            costo_hora_parada = st.number_input(
                "Costo por Hora de Parada (Gs.)", min_value=0, step=1000, value=0,
                help="Lucro cesante: cuánto cuesta cada hora que esta máquina está parada."
            )

            submit = st.form_submit_button("Guardar Máquina y Generar QR Automático")
            if submit:
                if not nombre.strip() or not codigo.strip():
                    st.error("El nombre y el código de la máquina son obligatorios.")
                else:
                    # El ID no se envía en el payload ya que Supabase lo genera automáticamente como BIGINT
                    payload = {
                        "tag": tag.strip() or None,
                        "nombre": nombre,
                        "codigo": codigo,
                        "seccion": seccion,
                        "criticidad": criticidad,
                        "costo_hora_parada": costo_hora_parada
                    }
                    creada = insert_maquina(payload)
                    st.session_state.maquinas = get_maquinas()
                    if creada:
                        st.session_state["maquina_recien_creada"] = creada[0]
                    st.rerun()

    # Listado en Interfaz Industrial
    st.markdown("<br>", unsafe_allow_html=True)
    if not st.session_state.maquinas:
        st.info("Todavía no has cargado ninguna máquina.")
    else:
        for m in st.session_state.maquinas:
            col_info, col_action = st.columns([0.85, 0.15])
            with col_info:
                costo_parada_fmt = f"{m.get('costo_hora_parada', 0) or 0:,.0f}".replace(",", ".")
                tag_txt = f" <small style='color:#F2A93B;'>Tag: {m.get('tag')}</small>" if m.get("tag") else ""
                st.markdown(f"""
                <div class='industrial-panel'>
                    <strong>{m.get('nombre')}</strong> <small style='color:#38BDF8;'>[{m.get('codigo')}]</small>{tag_txt} — 
                    <small style='color:#7C8894;'>{m.get('seccion') or 'sin sección'}</small><br>
                    <span>Criticidad: {CRIT_LABELS.get(m.get('criticidad'), m.get('criticidad'))} · Costo Hora de Parada: Gs. {costo_parada_fmt}</span>
                </div>
                """, unsafe_allow_html=True)
            with col_action:
                # Se utiliza el ID numérico de Supabase para la clave del botón
                if st.button("🗑️ Eliminar", key=f"del_m_{m.get('id')}"):
                    delete_maquina(m.get('id'))
                    st.session_state.maquinas = get_maquinas()
                    st.rerun()

            with st.expander(f"✏️ Editar datos de {m.get('nombre')}"):
                col_e1, col_e2 = st.columns(2)
                nuevo_tag = col_e1.text_input("Tag", value=m.get("tag") or "", key=f"edit_tag_{m.get('id')}")
                nuevo_nombre = col_e2.text_input("Nombre", value=m.get("nombre") or "", key=f"edit_nombre_{m.get('id')}")
                col_e3, col_e4 = st.columns(2)
                nuevo_codigo = col_e3.text_input("Código Único", value=m.get("codigo") or "", key=f"edit_codigo_{m.get('id')}")
                nueva_seccion = col_e4.text_input("Sección / Área", value=m.get("seccion") or "", key=f"edit_seccion_{m.get('id')}")
                nueva_criticidad = st.selectbox(
                    "Criticidad", ["A", "B", "C"], format_func=lambda x: CRIT_LABELS[x],
                    index=["A", "B", "C"].index(m.get("criticidad")) if m.get("criticidad") in ["A", "B", "C"] else 0,
                    key=f"edit_criticidad_{m.get('id')}"
                )
                if st.button("💾 Guardar cambios", key=f"save_edit_maquina_{m.get('id')}"):
                    if not nuevo_nombre.strip() or not nuevo_codigo.strip():
                        st.error("El nombre y el código son obligatorios.")
                    else:
                        update_maquina(m.get("id"), {
                            "tag": nuevo_tag.strip() or None,
                            "nombre": nuevo_nombre,
                            "codigo": nuevo_codigo,
                            "seccion": nueva_seccion,
                            "criticidad": nueva_criticidad
                        })
                        st.session_state.maquinas = get_maquinas()
                        st.success("✅ Máquina actualizada.")
                        st.rerun()

            with st.expander(f"💰 Editar costo de hora de parada de {m.get('nombre')}"):
                nuevo_costo_parada = st.number_input(
                    "Costo por Hora de Parada (Gs.)", min_value=0, step=1000,
                    value=int(m.get("costo_hora_parada", 0) or 0),
                    key=f"costo_parada_{m.get('id')}"
                )
                if st.button("💾 Guardar", key=f"save_costo_parada_{m.get('id')}"):
                    update_maquina(m.get("id"), {"costo_hora_parada": nuevo_costo_parada})
                    st.session_state.maquinas = get_maquinas()
                    st.success("✅ Costo actualizado.")
                    st.rerun()

            # --- DOCUMENTACIÓN TÉCNICA (manuales, planos, fichas) ---
            docs_maquina = [d for d in st.session_state.get("documentos", []) if d.get("maquina_id") == m.get("id")]
            with st.expander(f"📎 Documentos técnicos ({len(docs_maquina)})"):
                if docs_maquina:
                    for d in docs_maquina:
                        col_d, col_x = st.columns([0.85, 0.15])
                        col_d.markdown(f"[{d.get('nombre_archivo')}]({d.get('url')}) · {d.get('tipo') or 'General'}")
                        if col_x.button("🗑️", key=f"del_doc_{d.get('id')}"):
                            delete_documento(d.get('id'))
                            st.session_state.documentos = get_documentos()
                            st.rerun()
                else:
                    st.caption("Sin documentos cargados todavía.")

                with st.form(f"form_doc_{m.get('id')}", clear_on_submit=True):
                    nombre_doc = st.text_input("Nombre del documento", placeholder="Ej: Manual eléctrico Extrusora 02")
                    url_doc = st.text_input("Link (Google Drive, OneDrive, etc.)")
                    tipo_doc = st.selectbox("Tipo", ["Manual", "Plano", "Ficha Técnica", "Foto", "Otro"], key=f"tipo_doc_{m.get('id')}")
                    if st.form_submit_button("Adjuntar documento"):
                        if not nombre_doc.strip() or not url_doc.strip():
                            st.error("❌ Nombre y link son obligatorios.")
                        else:
                            insert_documento({
                                "maquina_id": m.get("id"),
                                "nombre_archivo": nombre_doc,
                                "url": url_doc,
                                "tipo": tipo_doc
                            })
                            st.session_state.documentos = get_documentos()
                            st.success("✅ Documento adjuntado.")
                            st.rerun()

            # --- CÓDIGOS QR AUTOMÁTICOS (REPORTE DE FALLAS SIN LOGIN + CHECKLIST DE TURNO) ---
            with st.expander(f"📱 Códigos QR de {m.get('nombre')} (Listos para descargar)"):
                c_qr1, c_qr2 = st.columns(2)

                with c_qr1:
                    st.markdown("**🚨 QR Público — Reportar Falla (Sin Login)**")
                    st.caption("Pegar en la máquina: abre la ficha pública y permite reportar averías desde cualquier celular.")
                    url_qr_falla = f"{base_url.rstrip('/')}/?equipo={m.get('id')}"
                    qr_bytes_falla = generar_qr_png(url_qr_falla)
                    st.image(qr_bytes_falla, width=180)
                    st.code(url_qr_falla, language=None)
                    st.download_button(
                        "⬇️ Descargar QR de Reporte de Fallas (PNG)",
                        data=qr_bytes_falla,
                        file_name=f"QR_Fallas_{m.get('codigo')}_{m.get('id')}.png",
                        mime="image/png",
                        key=f"dl_qr_falla_{m.get('id')}"
                    )

                with c_qr2:
                    st.markdown("**📋 QR Interno — Recepción / Entrega de Turno**")
                    st.caption("Para técnicos/inspectores logueados: salta directo al formulario de checklist de la máquina.")
                    url_qr_chk = f"{base_url.rstrip('/')}/?maquina_id={m.get('id')}&vista=checklist"
                    qr_bytes_chk = generar_qr_png(url_qr_chk)
                    st.image(qr_bytes_chk, width=180)
                    st.code(url_qr_chk, language=None)
                    st.download_button(
                        "⬇️ Descargar QR de Checklist (PNG)",
                        data=qr_bytes_chk,
                        file_name=f"QR_Checklist_{m.get('codigo')}_{m.get('id')}.png",
                        mime="image/png",
                        key=f"dl_qr_chk_{m.get('id')}"
                    )

            # --- GENERAR PLAN PREVENTIVO CON IA A PARTIR DEL MANUAL ---
            with st.expander("🤖 Generar Plan Preventivo con IA (desde el manual)"):
                api_key_secret = st.secrets.get("GEMINI_API_KEY", "")
                if api_key_secret:
                    api_key_usar = api_key_secret
                    st.caption("Usando la GEMINI_API_KEY configurada en los secrets de la app.")
                else:
                    api_key_usar = st.text_input(
                        "Pegá tu API Key de Gemini (solo para esta sesión, no se guarda)",
                        type="password",
                        key=f"api_key_{m.get('id')}",
                        help="Se recomienda configurarla en Streamlit Cloud > Settings > Secrets como GEMINI_API_KEY en vez de pegarla acá cada vez."
                    )

                manual_pdf = st.file_uploader(
                    "Subí el manual del fabricante (PDF)", type=["pdf"], key=f"manual_pdf_{m.get('id')}"
                )

                if st.button("🔍 Analizar manual y sugerir plan", key=f"analizar_{m.get('id')}"):
                    if not manual_pdf:
                        st.error("❌ Subí un PDF primero.")
                    elif not api_key_usar:
                        st.error("❌ Falta la API Key de Gemini.")
                    else:
                        with st.spinner("Leyendo el manual y consultando la IA..."):
                            texto_manual = extraer_texto_pdf(manual_pdf)
                            if not texto_manual.strip():
                                st.error("❌ No se pudo extraer texto del PDF (¿es un escaneo sin OCR?).")
                            else:
                                tareas_sugeridas, error = generar_plan_con_ia(texto_manual, api_key_usar)
                                if error:
                                    st.error(f"❌ {error}")
                                elif not tareas_sugeridas:
                                    st.warning("La IA no encontró tareas de mantenimiento preventivo claras en este manual.")
                                else:
                                    st.session_state[f"tareas_ia_{m.get('id')}"] = tareas_sugeridas

                tareas_ia = st.session_state.get(f"tareas_ia_{m.get('id')}")
                if tareas_ia:
                    st.write("**Tareas sugeridas — revisá y ajustá antes de cargarlas:**")
                    tareas_editadas = st.data_editor(
                        tareas_ia,
                        column_config={
                            "tarea": "Tarea",
                            "frecuencia_dias": st.column_config.NumberColumn("Frecuencia (días)", min_value=1, step=1),
                            "nota": "Nota de la IA"
                        },
                        num_rows="dynamic",
                        key=f"editor_ia_{m.get('id')}",
                        use_container_width=True
                    )
                    if st.button("✅ Cargar estas tareas al Plan Preventivo", key=f"cargar_ia_{m.get('id')}"):
                        hoy = datetime.now().date()
                        grupos_por_frecuencia = {}
                        for t in tareas_editadas:
                            if not t.get("tarea") or not t.get("frecuencia_dias"):
                                continue
                            grupos_por_frecuencia.setdefault(int(t["frecuencia_dias"]), []).append(t["tarea"])

                        planes_creados = 0
                        for frecuencia, lista_actividades in grupos_por_frecuencia.items():
                            proxima = hoy + timedelta(days=frecuencia)
                            plan_creado = insert_plan({
                                "maquina_id": m.get("id"),
                                "nombre_plan": f"Preventivo cada {frecuencia} días (según manual)",
                                "frecuencia_dias": frecuencia,
                                "ultima_ejecucion": None,
                                "proxima_ejecucion": proxima.strftime("%Y-%m-%d")
                            })
                            plan_id = plan_creado[0]["id"] if plan_creado else None
                            for actividad in lista_actividades:
                                insert_actividad({"plan_id": plan_id, "actividad": actividad})
                            planes_creados += 1

                        st.session_state.planes = get_planes()
                        st.session_state.plan_actividades = get_actividades()
                        del st.session_state[f"tareas_ia_{m.get('id')}"]
                        st.success(f"✅ {planes_creados} plan(es) preventivo(s) creado(s) en {m.get('nombre')}, agrupando {len(tareas_editadas)} actividad(es) por frecuencia.")
                        st.rerun()
