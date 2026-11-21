import unicodedata
import streamlit as st
import qrcode
import json
from io import BytesIO
from database.conection import insert_maquina, delete_maquina, get_maquinas, update_maquina, insert_documento, delete_documento, get_documentos, insert_plan, get_planes, insert_actividad, get_actividades
from datetime import timedelta

import pandas as pd

from database import ots_servicio as S
from views import ui

CRIT_LABELS = {"A": "A · Crítica", "B": "B · Importante", "C": "C · Menor"}
CRIT_COLOR = {"A": "red", "B": "orange", "C": "blue"}
LIMITE_RESULTADOS = 25


def _normalizar(texto):
    """Minúsculas y sin tildes: 'Cañón' y 'canon' se encuentran entre sí."""
    base = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode("ascii")
    return base.casefold()


def buscar_maquinas(maquinas, texto="", seccion="Todas", criticidad="Todas"):
    """Máquinas que cumplen el texto (todas las palabras, en nombre, código, tag, sección, línea o descripción), la sección y la criticidad."""
    palabras = _normalizar(texto).split()
    resultado = []
    for m in maquinas:
        if seccion != "Todas" and (m.get("seccion") or "—") != seccion:
            continue
        if criticidad != "Todas" and m.get("criticidad") != criticidad:
            continue
        pajar = _normalizar(" ".join(str(m.get(c) or "") for c in ("nombre", "codigo", "tag", "seccion", "linea", "descripcion")))
        if all(p in pajar for p in palabras):
            resultado.append(m)
    return resultado


@st.cache_data(show_spinner=False)
def generar_qr_png(url: str) -> bytes:
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


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
    modelo = genai.GenerativeModel(st.secrets.get("GEMINI_MODEL", "gemini-3.5-flash"))

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

def _url_base():
    return (st.session_state.get("app_base_url") or st.secrets.get("APP_BASE_URL", "") or "").rstrip("/")


def _refrescar_maquinas():
    st.session_state.maquinas = get_maquinas()
    try:
        from database.conection import get_maquinas_cached
        get_maquinas_cached.clear()
    except Exception:
        pass


@st.dialog("Nueva máquina")
def _dialogo_nueva():
    tag = st.text_input("Tag", placeholder="Ej.: 50000000", help="El número pegado físicamente en la máquina.")
    nombre = st.text_input("Nombre *", placeholder="Ej.: COEX – Enrollador")
    c1, c2 = st.columns(2)
    codigo = c1.text_input("Código único *", placeholder="Ej.: EXT-ENR-01")
    seccion = c2.text_input("Sección / área", placeholder="Ej.: COEX")
    c3, c4 = st.columns(2)
    criticidad = c3.selectbox("Criticidad", ["A", "B", "C"], index=1, format_func=lambda x: CRIT_LABELS[x])
    costo = c4.number_input("Costo por hora de parada (Gs.)", min_value=0, step=100000,
                            help="Lucro cesante: cuánto cuesta cada hora que esta máquina está parada.")
    if st.button("Guardar máquina", type="primary", use_container_width=True):
        existentes = {str(m.get("codigo") or "").strip().casefold() for m in st.session_state.get("maquinas", [])}
        if not nombre.strip() or not codigo.strip():
            st.error("El nombre y el código son obligatorios.")
            return
        if codigo.strip().casefold() in existentes:
            st.error("Ya hay una máquina con ese código.")
            return
        try:
            insert_maquina({"tag": tag.strip() or None, "nombre": nombre.strip(), "codigo": codigo.strip(),
                            "seccion": seccion.strip(), "criticidad": criticidad, "costo_hora_parada": costo})
        except Exception as e:
            ui.error_amigable("No se pudo guardar la máquina.", e)
            return
        _refrescar_maquinas()
        st.session_state["maq_mensaje"] = f"Máquina «{nombre.strip()}» guardada."
        st.rerun()


def _resumen_por_maquina(maquinas):
    """OTs abiertas, parada y próximo preventivo de cada máquina."""
    ots = st.session_state.get("ots", [])
    planes = st.session_state.get("planes", [])
    datos = {m["id"]: {"abiertas": 0, "parada": False, "proximo": None} for m in maquinas}
    for o in ots:
        d = datos.get(o.get("maquina_id"))
        if d is not None and o.get("estado") != "Completada":
            d["abiertas"] += 1
            d["parada"] = d["parada"] or S.es_parada(o)
    for p in planes:
        d = datos.get(p.get("maquina_id"))
        f = ui.a_fecha(p.get("proxima_ejecucion"))
        if d is not None and f and (d["proximo"] is None or f < d["proximo"]):
            d["proximo"] = f
    return datos


def _lista(todas):
    datos = _resumen_por_maquina(todas)
    c1, c2, c3 = st.columns([3, 1.5, 1.5])
    texto = c1.text_input("Buscar", placeholder="Nombre, código, tag, sección o descripción", key="maq_buscar",
                          label_visibility="collapsed")
    secciones = sorted({(m.get("seccion") or "—") for m in todas}, key=str.casefold)
    seccion = c2.selectbox("Sección", ["Todas"] + secciones, key="maq_f_seccion", label_visibility="collapsed",
                           format_func=lambda x: "Todas las secciones" if x == "Todas" else x)
    crit = c3.selectbox("Criticidad", ["Todas", "A", "B", "C"], key="maq_f_crit", label_visibility="collapsed",
                        format_func=lambda x: "Toda criticidad" if x == "Todas" else CRIT_LABELS[x])
    lista = buscar_maquinas(todas, texto, seccion, crit)
    lista = sorted(lista, key=lambda m: (not datos[m["id"]]["parada"], str(m.get("seccion") or ""), str(m.get("nombre") or "").casefold()))
    if not lista:
        ui.estado_vacio("Ninguna máquina coincide con la búsqueda.")
        return
    hoy = ui.hoy()
    df = pd.DataFrame([{
        "id": m["id"],
        "Código": m.get("codigo"),
        "Máquina": m.get("nombre"),
        "Sección": m.get("seccion") or "—",
        "Criticidad": m.get("criticidad") or "—",
        "Estado": "Parada" if datos[m["id"]]["parada"] else "Operando",
        "OTs abiertas": datos[m["id"]]["abiertas"],
        "Próximo preventivo": (("Vencido " if datos[m["id"]]["proximo"] < hoy else "") + datos[m["id"]]["proximo"].strftime("%d/%m/%Y"))
                              if datos[m["id"]]["proximo"] else "—",
    } for m in lista])
    evento = st.dataframe(df, hide_index=True, use_container_width=True, on_select="rerun", selection_mode="single-row",
                          key="maq_tabla", column_order=[c for c in df.columns if c != "id"],
                          height=min(38 + 35 * len(df), 600))
    st.caption(f"{len(lista)} de {len(todas)} máquinas. Tocá una fila para abrir su ficha.")
    filas = evento.selection.rows if evento and evento.selection else []
    if filas and filas[0] < len(df):
        valor = df.iloc[filas[0]]["id"]
        st.session_state["maq_sel_id"] = valor.item() if hasattr(valor, "item") else valor
        st.rerun()


def _ficha(m):
    mid = m["id"]
    hoy = ui.hoy()
    ots = [o for o in st.session_state.get("ots", []) if o.get("maquina_id") == mid]
    planes = [p for p in st.session_state.get("planes", []) if p.get("maquina_id") == mid]
    abiertas = [o for o in ots if o.get("estado") != "Completada"]
    parada = any(S.es_parada(o) for o in abiertas)

    if st.button("← Volver a la lista", type="tertiary"):
        st.session_state.pop("maq_sel_id", None)
        st.session_state.pop("maq_tabla", None)
        st.rerun()
    st.subheader(m.get("nombre") or "Máquina")
    st.caption(" · ".join(x for x in [m.get("codigo"), f"Tag {m.get('tag')}" if m.get("tag") else None,
                                       m.get("seccion")] if x))
    st.markdown((":red-badge[Parada]" if parada else ":green-badge[Operando]")
                + f" :{CRIT_COLOR.get(m.get('criticidad'), 'gray')}-badge[Criticidad {m.get('criticidad') or '—'}]"
                + f" :gray-badge[Parada: {ui.formato_gs(m.get('costo_hora_parada'))} / h]")

    proximas = sorted([f for f in (ui.a_fecha(p.get("proxima_ejecucion")) for p in planes) if f])
    inicio_mes = hoy.replace(day=1)
    paro_mes = sum(float(o.get("horas_paro") or 0) for o in ots if (ui.a_fecha(o.get("fecha_inicio")) or inicio_mes.replace(year=1900)) >= inicio_mes)
    costo_anio = sum(float(o.get("costo_total_ot") or o.get("costo_mano_obra") or 0) for o in ots
                     if (ui.a_fecha(o.get("fecha_inicio")) or hoy.replace(year=1900)).year == hoy.year)
    k1, k2, k3, k4 = st.columns(4)
    with k1, st.container(border=True):
        st.metric("OTs abiertas", len(abiertas))
    with k2, st.container(border=True):
        st.metric("Próximo preventivo", proximas[0].strftime("%d/%m") if proximas else "—")
        if proximas and proximas[0] < hoy:
            st.caption(f"Vencido hace {(hoy - proximas[0]).days} días")
    with k3, st.container(border=True):
        st.metric(f"Paro · {ui.nombre_mes(hoy)}", f"{paro_mes:.1f} h")
    with k4, st.container(border=True):
        st.metric(f"Costo OTs · {hoy.year}", ui.formato_gs(costo_anio))

    docs = [d for d in st.session_state.get("documentos", []) if d.get("maquina_id") == mid]
    t_res, t_datos, t_docs, t_qr, t_ia = st.tabs(["Resumen", "Datos", f"Documentos ({len(docs)})", "Códigos QR", "Plan con IA"])

    with t_res:
        izq, der = st.columns([3, 2], gap="medium")
        with izq:
            st.markdown("**Últimas OTs**")
            if not ots:
                st.caption("Esta máquina todavía no tiene OTs.")
            else:
                st.dataframe([{
                    "Código": o.get("codigo"), "Fecha": ui.fecha_corta(o.get("fecha_inicio")),
                    "Tipo": o.get("tipo_mantenimiento"), "Estado": S.NOMBRE_ESTADO.get(o.get("estado"), o.get("estado")),
                    "Trabajo": S.descripcion_sin_marca(o)[:60], "Paro (h)": float(o.get("horas_paro") or 0),
                } for o in sorted(ots, key=lambda o: -(o.get("id") or 0))[:10]], hide_index=True, use_container_width=True)
        with der:
            st.markdown("**Planes preventivos**")
            if not planes:
                st.caption("Sin planes preventivos. Podés generarlos en la pestaña «Plan con IA» o en Preventivo.")
            for p in sorted(planes, key=lambda p: str(p.get("proxima_ejecucion") or "9999")):
                f = ui.a_fecha(p.get("proxima_ejecucion"))
                if f is None:
                    marca = ":gray-badge[Sin fecha]"
                elif f < hoy:
                    marca = f":red-badge[Vencido {(hoy - f).days} d]"
                elif (f - hoy).days <= 7:
                    marca = f":orange-badge[{f:%d/%m}]"
                else:
                    marca = f":blue-badge[{f:%d/%m/%Y}]"
                st.markdown(f"{ui.texto_md(p.get('nombre_plan'))} · cada {p.get('frecuencia_dias')} d {marca}")

    with t_datos:
        c1, c2 = st.columns(2)
        tag = c1.text_input("Tag", value=m.get("tag") or "", key=f"edit_tag_{mid}")
        nombre = c2.text_input("Nombre *", value=m.get("nombre") or "", key=f"edit_nombre_{mid}")
        c3, c4 = st.columns(2)
        codigo = c3.text_input("Código único *", value=m.get("codigo") or "", key=f"edit_codigo_{mid}")
        seccion = c4.text_input("Sección / área", value=m.get("seccion") or "", key=f"edit_seccion_{mid}")
        c5, c6 = st.columns(2)
        criticidad = c5.selectbox("Criticidad", ["A", "B", "C"], format_func=lambda x: CRIT_LABELS[x],
                                  index=["A", "B", "C"].index(m.get("criticidad")) if m.get("criticidad") in ["A", "B", "C"] else 0,
                                  key=f"edit_criticidad_{mid}")
        costo = c6.number_input("Costo por hora de parada (Gs.)", min_value=0, step=100000,
                                value=int(m.get("costo_hora_parada") or 0), key=f"costo_parada_{mid}")
        b1, b2 = st.columns([1, 1])
        if b1.button("Guardar cambios", type="primary", key=f"save_edit_maquina_{mid}", use_container_width=True):
            if not nombre.strip() or not codigo.strip():
                st.error("El nombre y el código son obligatorios.")
            else:
                try:
                    update_maquina(mid, {"tag": tag.strip() or None, "nombre": nombre.strip(), "codigo": codigo.strip(),
                                         "seccion": seccion.strip(), "criticidad": criticidad, "costo_hora_parada": costo})
                except Exception as e:
                    ui.error_amigable("No se pudieron guardar los cambios.", e)
                else:
                    _refrescar_maquinas()
                    st.session_state["maq_mensaje"] = "Máquina actualizada."
                    st.rerun()
        with b2:
            aviso = (f"Esta máquina tiene {len(ots)} OT(s) y {len(planes)} plan(es). Si la eliminás, podés perder ese historial. "
                     if (ots or planes) else "")
            if ui.boton_confirmar("Eliminar máquina", f"del_m_{mid}",
                                  aviso + f"¿Eliminar **{ui.texto_md(m.get('nombre'))}** definitivamente?",
                                  texto_confirmar="Sí, eliminar", use_container_width=True):
                try:
                    delete_maquina(mid)
                except Exception as e:
                    ui.error_amigable("No se pudo eliminar: la máquina tiene registros asociados.", e)
                else:
                    _refrescar_maquinas()
                    st.session_state.pop("maq_sel_id", None)
                    st.session_state["maq_mensaje"] = "Máquina eliminada."
                    st.rerun()

    with t_docs:
        if not docs:
            st.caption("Sin documentos todavía.")
        for d in docs:
            c_d, c_x = st.columns([5, 1], vertical_alignment="center")
            c_d.markdown(f"[{ui.texto_md(d.get('nombre_archivo'))}]({d.get('url')}) · {ui.texto_md(d.get('tipo') or 'General')}"
                         if str(d.get("url") or "").startswith(("http://", "https://"))
                         else f"{ui.texto_md(d.get('nombre_archivo'))} · {ui.texto_md(d.get('url'))}")
            with c_x:
                if ui.boton_confirmar("Quitar", f"del_doc_{d.get('id')}", "¿Quitar este documento de la ficha?",
                                      texto_confirmar="Sí, quitar"):
                    delete_documento(d.get("id"))
                    st.session_state.documentos = get_documentos()
                    st.rerun()
        with st.form(f"form_doc_{mid}", clear_on_submit=True):
            st.markdown("**Agregar documento**")
            c1, c2 = st.columns(2)
            nombre_doc = c1.text_input("Nombre", placeholder="Ej.: Manual eléctrico")
            tipo_doc = c2.selectbox("Tipo", ["Manual", "Plano", "Ficha Técnica", "Foto", "Otro"])
            url_doc = st.text_input("Enlace (Google Drive, OneDrive, etc.)", placeholder="https://...")
            if st.form_submit_button("Agregar documento"):
                if not nombre_doc.strip() or not url_doc.strip():
                    st.error("El nombre y el enlace son obligatorios.")
                else:
                    insert_documento({"maquina_id": mid, "nombre_archivo": nombre_doc.strip(), "url": url_doc.strip(), "tipo": tipo_doc})
                    st.session_state.documentos = get_documentos()
                    st.session_state["maq_mensaje"] = "Documento agregado."
                    st.rerun()

    with t_qr:
        base = _url_base()
        if not base:
            st.warning("Falta la dirección de la app. Cargala abajo o, mejor, en los secrets como APP_BASE_URL.")
        with st.expander("Dirección de la app para los QR", expanded=not base):
            st.session_state["app_base_url"] = st.text_input("URL de la app", value=base, placeholder="https://tu-app.streamlit.app",
                                                             key=f"url_qr_{mid}")
            st.caption("Lo que escribís acá dura solo esta sesión. Para dejarlo fijo, agregalo en los secrets: APP_BASE_URL = \"https://...\"")
        base = _url_base()
        if base:
            q1, q2 = st.columns(2)
            for col, titulo, url, archivo, clave in (
                (q1, "Avisar una falla (sin iniciar sesión)", f"{base}/?equipo={mid}", f"QR_FALLAS_{m.get('codigo')}.png", f"dl_qr_falla_{mid}"),
                (q2, "Recepción / entrega", f"{base}/?maquina_id={mid}&vista=checklist", f"QR_{m.get('codigo')}.png", f"dl_qr_{mid}"),
            ):
                with col, st.container(border=True):
                    st.markdown(f"**{titulo}**")
                    png = generar_qr_png(url)
                    st.image(png, width=180)
                    st.code(url, language=None)
                    st.download_button("Descargar PNG", data=png, file_name=archivo, mime="image/png", key=clave)

    with t_ia:
        api_key = st.secrets.get("GEMINI_API_KEY", "")
        if not api_key:
            api_key = st.text_input("API key de Gemini (solo para esta sesión)", type="password", key=f"api_key_{mid}",
                                    help="Conviene configurarla en los secrets como GEMINI_API_KEY.")
        st.caption("Subí el manual del fabricante en PDF. La IA propone tareas y frecuencias; vos las revisás antes de cargarlas.")
        manual = st.file_uploader("Manual (PDF)", type=["pdf"], key=f"manual_pdf_{mid}")
        if st.button("Analizar manual", key=f"analizar_{mid}", disabled=manual is None):
            if not api_key:
                st.error("Falta la API key de Gemini.")
            else:
                with st.spinner("Leyendo el manual y consultando la IA..."):
                    texto_manual = extraer_texto_pdf(manual)
                    if not texto_manual.strip():
                        st.error("No se pudo leer texto del PDF (¿es un escaneo sin OCR?).")
                    else:
                        tareas, error = generar_plan_con_ia(texto_manual, api_key)
                        if error:
                            st.error(error)
                        elif not tareas:
                            st.warning("La IA no encontró tareas de preventivo claras en este manual.")
                        else:
                            st.session_state[f"tareas_ia_{mid}"] = tareas
        tareas_ia = st.session_state.get(f"tareas_ia_{mid}")
        if tareas_ia:
            st.markdown("**Tareas sugeridas** (revisalas y ajustalas antes de cargar)")
            editadas = st.data_editor(tareas_ia, num_rows="dynamic", key=f"editor_ia_{mid}", use_container_width=True,
                                      column_config={"tarea": "Tarea",
                                                     "frecuencia_dias": st.column_config.NumberColumn("Frecuencia (días)", min_value=1, step=1),
                                                     "nota": "Nota de la IA"})
            if st.button("Cargar como planes preventivos", type="primary", key=f"cargar_ia_{mid}"):
                grupos = {}
                for t in editadas:
                    if t.get("tarea") and t.get("frecuencia_dias"):
                        grupos.setdefault(int(t["frecuencia_dias"]), []).append(t["tarea"])
                for frecuencia, actividades in grupos.items():
                    creado = insert_plan({"maquina_id": mid, "nombre_plan": f"Preventivo cada {frecuencia} días (según manual)",
                                          "frecuencia_dias": frecuencia, "ultima_ejecucion": None,
                                          "proxima_ejecucion": (hoy + timedelta(days=frecuencia)).strftime("%Y-%m-%d")})
                    plan_id = creado[0]["id"] if creado else None
                    for a in actividades:
                        insert_actividad({"plan_id": plan_id, "actividad": a})
                st.session_state.planes = get_planes()
                st.session_state.plan_actividades = get_actividades()
                del st.session_state[f"tareas_ia_{mid}"]
                st.session_state["maq_mensaje"] = f"{len(grupos)} plan(es) creado(s), agrupados por frecuencia."
                st.rerun()


def render_maquinas():
    cab, acc = st.columns([4, 1.2], vertical_alignment="bottom")
    with cab:
        ui.encabezado("Máquinas", "Buscá una máquina para ver su estado, historial, planes, documentos y códigos QR.")
    if acc.button("+ Nueva máquina", type="primary", use_container_width=True):
        _dialogo_nueva()

    mensaje = st.session_state.pop("maq_mensaje", None)
    if mensaje:
        st.toast(mensaje, icon=":material/check_circle:")

    todas = st.session_state.get("maquinas", [])
    if not todas:
        ui.estado_vacio("Todavía no hay máquinas cargadas.", "Usá «+ Nueva máquina» para cargar la primera.")
        return
    seleccion = st.session_state.get("maq_sel_id")
    maquina = next((m for m in todas if m["id"] == seleccion), None) if seleccion is not None else None
    if maquina:
        _ficha(maquina)
    else:
        _lista(todas)
