import base64
import html
import mimetypes
from datetime import datetime

import pandas as pd
import streamlit as st

from database import cotizaciones_db as db
from database.conection import get_solicitudes_compra
from database.cotizaciones_ia import extraer_datos_cotizacion, generar_borrador_analisis
from database.cotizaciones_informe import (
    MAX_ADJUNTOS_MB, enviar_email_informe, fmt_gs, fmt_monto, fmt_tc, fmt_usd, generar_informe_pdf,
)

MAX_COTIZACIONES = 6
IVA_INCLUIDO = "Precio con IVA incluido"
IVA_NO_INCLUIDO = "Precio sin IVA (se le suma)"
ESTADO_COLOR = {
    "Pendiente de envío": "#F59E0B", "Enviado": "#38BDF8", "Aprobado": "#10B981",
    "Comprado": "#10B981", "Rechazado": "#EF4444",
}

# Valores iniciales del formulario de "agregar cotización"
NQ_DEFAULTS = {
    "nq_proveedor": "", "nq_nro": "", "nq_validez": 0, "nq_moneda": "PYG",
    "nq_monto": 0.0, "nq_iva_modo": IVA_INCLUIDO, "nq_iva_pct": 10, "nq_plazo": "",
    "nq_garantia": "", "nq_pago": "", "nq_alcance": "", "nq_obs": "",
}


# ----------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------
@st.cache_data(ttl=30, show_spinner=False)
def _solicitudes_cached():
    return get_solicitudes_compra()


def _esc(valor):
    return html.escape(str(valor)) if valor not in (None, "") else "—"


def _tipo_mime(archivo):
    return archivo.type or mimetypes.guess_type(archivo.name)[0] or "application/octet-stream"


def _logo_y_empresa():
    config = st.session_state.get("config_empresa", {}) or {}
    logo = None
    if config.get("logo_base64"):
        try:
            logo = base64.b64decode(config["logo_base64"])
        except Exception:
            logo = None
    return config.get("nombre_empresa") or "", logo


def _reset_formulario_cotizacion():
    for clave, valor in NQ_DEFAULTS.items():
        st.session_state[clave] = valor
    st.session_state["nq_fecha"] = None


def _reset_todo():
    _reset_formulario_cotizacion()
    st.session_state["cmp_cotis"] = []
    for clave in ("cmp_objeto", "cmp_descripcion", "cmp_analisis", "cmp_justif"):
        st.session_state[clave] = ""
    st.session_state["cmp_maquina"] = "No aplica"
    st.session_state["cmp_solicitud"] = "Ninguna"
    st.session_state["cmp_tc_ref"] = 0.0      # el tipo de cambio cambia todos los días: se pide de nuevo
    st.session_state["cmp_tc_fuente"] = ""
    st.session_state.pop("cmp_prov_rec", None)
    st.session_state.pop("cmp_preview", None)
    st.session_state["cmp_revisado"] = False
    st.session_state["nq_n"] = st.session_state.get("nq_n", 0) + 1


# ----------------------------------------------------------------
# Callbacks (modifican widgets que ya existen en pantalla)
# ----------------------------------------------------------------
def _cb_agregar_cotizacion():
    ss = st.session_state
    cotis = ss["cmp_cotis"]

    def error(texto):
        ss["nq_msg"] = ("error", texto)

    if len(cotis) >= MAX_COTIZACIONES:
        return error(f"Máximo {MAX_COTIZACIONES} cotizaciones por comparativo.")

    proveedor = (ss.get("nq_proveedor") or "").strip()
    monto = float(ss.get("nq_monto") or 0)
    moneda = ss.get("nq_moneda", "PYG")
    tc_ref = float(ss.get("cmp_tc_ref") or 0)
    incluye_iva = ss.get("nq_iva_modo") == IVA_INCLUIDO
    iva_pct = int(ss.get("nq_iva_pct", 10))

    if not proveedor:
        return error("Indicá el nombre del proveedor.")
    if monto <= 0:
        return error("Indicá el monto total de la cotización.")
    if tc_ref <= 0:
        return error("Indicá primero el tipo de cambio de referencia (guaraníes por 1 USD), arriba de las cotizaciones.")

    if not db.calcular_totales(monto, moneda, incluye_iva, iva_pct, tc_ref):
        return error("No se pudo calcular el total comparable. Revisá monto, moneda y tipo de cambio.")

    # Nombres únicos: si el proveedor ya está, se marca como alternativa
    existentes = {c["proveedor"] for c in cotis}
    nombre, n = proveedor, 2
    while nombre in existentes:
        nombre = f"{proveedor} (alt. {n})"
        n += 1

    archivo = ss.get(f"nq_archivo_{ss['nq_n']}")
    fecha = ss.get("nq_fecha")
    cotis.append({
        "proveedor": nombre,
        "nro_cotizacion": (ss.get("nq_nro") or "").strip() or None,
        "fecha_cotizacion": fecha.strftime("%Y-%m-%d") if fecha else None,
        "validez_dias": int(ss.get("nq_validez") or 0) or None,
        "moneda": moneda,
        "monto": monto,
        "incluye_iva": incluye_iva,
        "iva_pct": iva_pct,
        "plazo_entrega": (ss.get("nq_plazo") or "").strip() or None,
        "garantia": (ss.get("nq_garantia") or "").strip() or None,
        "forma_pago": (ss.get("nq_pago") or "").strip() or None,
        "alcance": (ss.get("nq_alcance") or "").strip() or None,
        "observaciones": (ss.get("nq_obs") or "").strip() or None,
        "archivo_nombre": archivo.name if archivo else None,
        "archivo_bytes": archivo.getvalue() if archivo else None,
        "archivo_tipo": _tipo_mime(archivo) if archivo else None,
    })
    ss.pop("cmp_preview", None)
    _reset_formulario_cotizacion()
    ss["nq_n"] += 1  # cambia la clave del cargador de archivos para vaciarlo
    ss["nq_msg"] = ("success", f"✅ Cotización de «{nombre}» agregada.")


def _cb_quitar_cotizacion(indice):
    cotis = st.session_state["cmp_cotis"]
    if 0 <= indice < len(cotis):
        cotis.pop(indice)
    st.session_state.pop("cmp_preview", None)


# ----------------------------------------------------------------
# Pantalla
# ----------------------------------------------------------------
def render_comparativo_cotizaciones(usuario):
    st.title("⚖️ Comparativo de Cotizaciones")
    st.write(
        "Cargá 2 o más cotizaciones de proveedores, compará en igualdad de condiciones (moneda e IVA) "
        "y generá un informe técnico que se envía a Compras."
    )

    if usuario.get("rol") != "admin":
        st.warning("Este módulo está disponible solo para el administrador.")
        return

    tab_nuevo, tab_historial = st.tabs(["➕ Nuevo comparativo", "📚 Historial"])
    with tab_nuevo:
        _render_nuevo(usuario)
    with tab_historial:
        _render_historial()


def _render_nuevo(usuario):
    ss = st.session_state

    # Limpieza pendiente (después de guardar): se hace ANTES de crear los widgets
    if ss.pop("cmp_reset_pending", False):
        _reset_todo()

    ss.setdefault("cmp_cotis", [])
    ss.setdefault("nq_n", 0)
    ss.setdefault("nq_fecha", None)
    for clave, valor in NQ_DEFAULTS.items():
        ss.setdefault(clave, valor)
    for clave in ("cmp_objeto", "cmp_descripcion", "cmp_analisis", "cmp_justif"):
        ss.setdefault(clave, "")
    ss.setdefault("cmp_maquina", "No aplica")
    ss.setdefault("cmp_solicitud", "Ninguna")
    ss.setdefault("cmp_cargo", "Coordinador de Mantenimiento")
    ss.setdefault("cmp_tc_ref", 0.0)
    ss.setdefault("cmp_tc_fuente", "")

    # Mensaje de lo último que se guardó/envió
    flash = ss.pop("cmp_flash", None)
    if flash:
        getattr(st, flash[0])(flash[1])
        if ss.get("cmp_ultimo_pdf"):
            st.download_button(
                "⬇️ Descargar el informe generado", data=ss["cmp_ultimo_pdf"]["bytes"],
                file_name=ss["cmp_ultimo_pdf"]["nombre"], mime="application/pdf", key="dl_ultimo_pdf",
            )

    # ---------- 1. La necesidad ----------
    st.subheader("1. ¿Qué se necesita comprar o contratar?")
    st.text_input("Objeto *", key="cmp_objeto",
                  placeholder="Ej: Reparación de reductor de la extrusora / Compra de cilindro neumático")
    st.text_area("Detalle (opcional)", key="cmp_descripcion",
                 placeholder="Especificaciones técnicas, cantidad, motivo...")

    maquinas = ss.get("maquinas", [])
    opciones_maquina = ["No aplica"] + [m["nombre"] for m in maquinas]
    if ss["cmp_maquina"] not in opciones_maquina:
        ss["cmp_maquina"] = "No aplica"

    try:
        solicitudes = _solicitudes_cached()
    except Exception:
        solicitudes = []
    mapa_solicitudes = {f"#{s['id']} — {s['item']} ({s['estado']})": s for s in solicitudes[:40]}
    opciones_solicitud = ["Ninguna"] + list(mapa_solicitudes.keys())
    if ss["cmp_solicitud"] not in opciones_solicitud:
        ss["cmp_solicitud"] = "Ninguna"

    c1, c2 = st.columns(2)
    c1.selectbox("Máquina relacionada (opcional)", opciones_maquina, key="cmp_maquina")
    c2.selectbox("Vincular a una Solicitud de Compra (opcional)", opciones_solicitud, key="cmp_solicitud")

    # ---------- 2. Agregar cotizaciones ----------
    st.markdown("---")
    st.subheader("2. Cotizaciones recibidas")
    cotis = ss["cmp_cotis"]

    st.caption(
        "Los totales se comparan en **dólares y en guaraníes** con IVA incluido, usando un único tipo de cambio "
        "de referencia para todas las ofertas (así el orden y las diferencias son iguales en ambas monedas)."
    )
    tc1, tc2 = st.columns([0.4, 0.6])
    tc1.number_input("Tipo de cambio de referencia (Gs. por 1 USD) *", min_value=0.0, step=10.0,
                     format="%.2f", key="cmp_tc_ref")
    tc2.text_input("Fuente / fecha del tipo de cambio (opcional)", key="cmp_tc_fuente",
                   placeholder="Ej: BCP, 21/10/2026 — o cotización del día de la compra")
    tc_ref = float(ss.get("cmp_tc_ref") or 0)

    if len(cotis) < MAX_COTIZACIONES:
        with st.container(border=True):
            st.markdown(f"**Agregar cotización {len(cotis) + 1}**")
            archivo = st.file_uploader(
                "Archivo de la cotización (PDF o foto; también se admite Word/Excel solo como adjunto)",
                type=["pdf", "png", "jpg", "jpeg", "docx", "xlsx"], key=f"nq_archivo_{ss['nq_n']}",
            )

            if st.button("🤖 Leer los datos con IA", disabled=archivo is None, key="btn_leer_ia"):
                with st.spinner("Leyendo la cotización..."):
                    try:
                        datos = extraer_datos_cotizacion(archivo.getvalue(), _tipo_mime(archivo))
                    except Exception as e:
                        st.error(f"No se pudo leer con IA: {e} — podés cargar los datos a mano.")
                    else:
                        _aplicar_extraccion(datos)
                        st.success("Datos leídos. ⚠️ Revisá cada campo contra el documento antes de agregar: la IA puede equivocarse.")

            f1, f2, f3 = st.columns(3)
            f1.text_input("Proveedor *", key="nq_proveedor")
            f2.text_input("N° de cotización", key="nq_nro")
            f3.date_input("Fecha de la cotización", value=None, key="nq_fecha", format="DD/MM/YYYY")

            g1, g2, g3 = st.columns(3)
            g1.selectbox("Moneda de la oferta", db.MONEDAS, key="nq_moneda",
                         format_func=lambda m: "Guaraníes (PYG)" if m == "PYG" else "Dólares (USD)")
            g2.number_input("Monto total *", min_value=0.0, step=1000.0, format="%.2f", key="nq_monto")
            g3.number_input("Validez (días)", min_value=0, step=1, key="nq_validez")

            h1, h2 = st.columns(2)
            h1.selectbox("IVA", [IVA_INCLUIDO, IVA_NO_INCLUIDO], key="nq_iva_modo")
            h2.selectbox("Porcentaje de IVA", [10, 5, 0], key="nq_iva_pct",
                         format_func=lambda x: "Exento (0%)" if x == 0 else f"{x}%")

            i1, i2, i3 = st.columns(3)
            i1.text_input("Plazo de entrega", key="nq_plazo", placeholder="Ej: 15 días hábiles")
            i2.text_input("Garantía", key="nq_garantia", placeholder="Ej: 6 meses")
            i3.text_input("Forma de pago", key="nq_pago", placeholder="Ej: 30 días fecha factura")
            st.text_area("Alcance (qué incluye la oferta)", key="nq_alcance", height=80)
            st.text_input("Observaciones", key="nq_obs")

            st.button("➕ Agregar esta cotización", key="btn_agregar_cot", on_click=_cb_agregar_cotizacion)

    mensaje = ss.pop("nq_msg", None)
    if mensaje:
        getattr(st, mensaje[0])(mensaje[1])

    # ---------- Cotizaciones agregadas + tabla comparativa ----------
    cotis_calc = db.aplicar_totales(cotis, tc_ref) if (cotis and tc_ref > 0) else None
    if cotis:
        st.markdown("**Cotizaciones agregadas**")
        for i, c in enumerate(cotis):
            col_a, col_b = st.columns([0.88, 0.12])
            linea = f"{i + 1}. **{c['proveedor']}** — {fmt_monto(c['monto'], c['moneda'])}"
            if cotis_calc:
                linea += f" → comparable {fmt_usd(cotis_calc[i]['total_comparable_usd'])} ({fmt_gs(cotis_calc[i]['total_comparable_pyg'])})"
            if c.get("archivo_nombre"):
                linea += f" · 📎 {c['archivo_nombre']}"
            col_a.write(linea)
            col_b.button("🗑️", key=f"cmp_del_{i}", on_click=_cb_quitar_cotizacion, args=(i,))

    if len(cotis) < 2:
        st.info("Agregá al menos 2 cotizaciones para poder comparar y generar el informe.")
        return
    if not cotis_calc:
        st.warning("Indicá el tipo de cambio de referencia (arriba) para ver el cuadro comparativo en dólares y guaraníes.")
        return

    ordenadas = db.ordenar_con_diferencias(cotis_calc)
    st.markdown(f"**Cuadro comparativo** (de menor a mayor precio, con IVA incluido · tipo de cambio: {fmt_tc(tc_ref)} por USD)")
    st.dataframe(pd.DataFrame([{
        "#": pos,
        "Proveedor": c["proveedor"],
        "Oferta original": fmt_monto(c["monto"], c["moneda"]),
        "IVA": "incluido" if c["incluye_iva"] else f"no incluido ({c['iva_pct']}%)",
        "Total comparable (USD)": fmt_usd(c["total_comparable_usd"]),
        "Equivale a (Gs.)": fmt_gs(c["total_comparable_pyg"]),
        "Dif. vs. más baja": "Más baja" if not c["dif_pct"] else f"+{c['dif_pct']}%",
        "Plazo": c.get("plazo_entrega") or "—",
        "Garantía": c.get("garantia") or "—",
        "Pago": c.get("forma_pago") or "—",
    } for pos, c in enumerate(ordenadas, 1)]), width="stretch", hide_index=True)

    # ---------- 3. Análisis y recomendación ----------
    st.markdown("---")
    st.subheader("3. Análisis y recomendación")
    nombres = [c["proveedor"] for c in cotis]

    if st.button("🤖 Generar borrador de análisis y recomendación", key="btn_borrador"):
        if not ss["cmp_objeto"].strip():
            st.warning("Completá primero el objeto de la compra (arriba).")
        else:
            with st.spinner("Redactando el borrador..."):
                try:
                    borrador = generar_borrador_analisis(ss["cmp_objeto"], ss["cmp_descripcion"], ordenadas, tc_ref)
                except Exception as e:
                    st.error(f"No se pudo generar el borrador: {e} — podés redactarlo a mano.")
                else:
                    ss["cmp_analisis"] = borrador["analisis"]
                    ss["cmp_justif"] = borrador["justificacion"]
                    ss["cmp_prov_rec"] = borrador["proveedor_recomendado"]
                    st.success("Borrador generado. Es solo una propuesta: leelo, corregilo y decidí vos.")

    if ss.get("cmp_prov_rec") not in nombres:
        ss["cmp_prov_rec"] = ordenadas[0]["proveedor"]  # por defecto, la más baja

    st.text_area("Análisis comparativo *", key="cmp_analisis", height=170)
    st.selectbox("Proveedor recomendado *", nombres, key="cmp_prov_rec")
    st.text_area("Justificación de la recomendación *", key="cmp_justif", height=120)
    st.text_input("Cargo (aparece en la firma del informe)", key="cmp_cargo")

    # ---------- 4. Informe y envío ----------
    st.markdown("---")
    st.subheader("4. Informe y envío")

    def armar_informe(codigo):
        solicitud = mapa_solicitudes.get(ss["cmp_solicitud"])
        return {
            "codigo": codigo,
            "fecha": datetime.now(),
            "objeto": ss["cmp_objeto"].strip(),
            "descripcion": ss["cmp_descripcion"].strip(),
            "maquina_nombre": None if ss["cmp_maquina"] == "No aplica" else ss["cmp_maquina"],
            "solicitud_ref": (f"Solicitud de Compra #{solicitud['id']} — {solicitud['item']}" if solicitud else None),
            "tipo_cambio_ref": tc_ref,
            "tipo_cambio_fuente": ss["cmp_tc_fuente"].strip() or None,
            "analisis": ss["cmp_analisis"].strip(),
            "proveedor_recomendado": ss["cmp_prov_rec"],
            "justificacion": ss["cmp_justif"].strip(),
            "elaborado_por": usuario.get("nombre"),
            "cargo": ss["cmp_cargo"].strip(),
        }

    empresa, logo = _logo_y_empresa()
    total_mb = sum(len(c["archivo_bytes"]) for c in cotis if c.get("archivo_bytes")) / 1024 / 1024
    if total_mb > MAX_ADJUNTOS_MB - 2:
        st.warning(f"Los archivos adjuntos pesan {total_mb:.1f} MB. El correo admite hasta ~{MAX_ADJUNTOS_MB} MB en total.")

    if st.button("📄 Generar vista previa del informe (PDF)", key="btn_preview"):
        if not ss["cmp_objeto"].strip():
            st.warning("Completá el objeto de la compra.")
        else:
            ss["cmp_preview"] = generar_informe_pdf(armar_informe("BORRADOR"), ordenadas, empresa, logo)
    if ss.get("cmp_preview"):
        st.download_button("⬇️ Descargar vista previa", data=ss["cmp_preview"],
                           file_name="vista_previa_informe.pdf", mime="application/pdf", key="dl_preview")

    revisado = st.checkbox(
        "Revisé los montos, monedas, IVA y condiciones de cada cotización contra los documentos originales",
        key="cmp_revisado",
    )
    if st.button("📨 Guardar y enviar a Compras", type="primary", key="btn_enviar", disabled=not revisado):
        faltantes = []
        if not ss["cmp_objeto"].strip():
            faltantes.append("el objeto")
        if not ss["cmp_analisis"].strip():
            faltantes.append("el análisis")
        if not ss["cmp_justif"].strip():
            faltantes.append("la justificación")
        if not ss["cmp_cargo"].strip():
            faltantes.append("el cargo")
        if faltantes:
            st.error("Completá " + ", ".join(faltantes) + ".")
        else:
            with st.spinner("Guardando, generando el PDF y enviando el correo..."):
                resultado = _guardar_y_enviar(usuario, cotis_calc, ordenadas, armar_informe, mapa_solicitudes, empresa, logo)
            if resultado.get("error_fatal"):
                st.error(resultado["error_fatal"])
            else:
                ss["cmp_ultimo_pdf"] = {"bytes": resultado["pdf"], "nombre": resultado["pdf_nombre"]}
                if resultado["email_ok"]:
                    ss["cmp_flash"] = ("success", f"✅ Informe {resultado['codigo']} guardado y enviado a Compras.")
                else:
                    ss["cmp_flash"] = ("warning", (
                        f"⚠️ El informe {resultado['codigo']} quedó guardado, pero el correo no se pudo enviar: "
                        f"{resultado['email_error']} Podés reintentar el envío desde la pestaña Historial."))
                for aviso in resultado.get("avisos", []):
                    ss["cmp_flash"] = (ss["cmp_flash"][0], ss["cmp_flash"][1] + f"\n\n{aviso}")
                ss["cmp_reset_pending"] = True
                st.rerun()


def _aplicar_extraccion(datos):
    """Vuelca lo que leyó la IA en los campos del formulario (solo lo que encontró)."""
    ss = st.session_state
    mapeo_texto = {
        "nq_proveedor": "proveedor", "nq_nro": "nro_cotizacion", "nq_plazo": "plazo_entrega",
        "nq_garantia": "garantia", "nq_pago": "forma_pago", "nq_alcance": "alcance", "nq_obs": "observaciones",
    }
    for clave, campo in mapeo_texto.items():
        if datos.get(campo):
            ss[clave] = str(datos[campo])
    if datos.get("fecha_cotizacion"):
        ss["nq_fecha"] = datos["fecha_cotizacion"]
    if datos.get("validez_dias") is not None:
        ss["nq_validez"] = int(datos["validez_dias"])
    if datos.get("moneda") in db.MONEDAS:
        ss["nq_moneda"] = datos["moneda"]
    if datos.get("monto_total"):
        ss["nq_monto"] = float(datos["monto_total"])
    if datos.get("incluye_iva") is not None:
        ss["nq_iva_modo"] = IVA_INCLUIDO if datos["incluye_iva"] else IVA_NO_INCLUIDO
    if datos.get("iva_pct") in (0, 5, 10):
        ss["nq_iva_pct"] = int(datos["iva_pct"])


def _guardar_y_enviar(usuario, cotis, ordenadas, armar_informe, mapa_solicitudes, empresa, logo):
    """
    Orden de operaciones (pensado para no perder nada si algo falla):
      1) guardar cabecera y cotizaciones en la base  2) subir archivos
      3) generar el PDF y subirlo                    4) enviar el correo
    El comparativo queda guardado aunque el envío falle.
    """
    ss = st.session_state
    avisos = []
    try:
        codigo = db.generar_codigo_informe()
        informe = armar_informe(codigo)
        solicitud = mapa_solicitudes.get(ss["cmp_solicitud"])
        maquina = next((m for m in ss.get("maquinas", []) if m["nombre"] == ss["cmp_maquina"]), None)

        fila = db.insertar_comparativo({
            "codigo": codigo,
            "objeto": informe["objeto"],
            "descripcion": informe["descripcion"] or None,
            "maquina_id": maquina["id"] if maquina else None,
            "solicitud_compra_id": solicitud["id"] if solicitud else None,
            "tipo_cambio_ref": informe["tipo_cambio_ref"],
            "tipo_cambio_fuente": informe["tipo_cambio_fuente"],
            "analisis": informe["analisis"],
            "proveedor_recomendado": informe["proveedor_recomendado"],
            "justificacion": informe["justificacion"],
            "estado": "Pendiente de envío",
            "elaborado_por": informe["elaborado_por"],
            "cargo": informe["cargo"],
            "fecha_informe": informe["fecha"].isoformat(),
        })
    except Exception as e:
        return {"error_fatal": f"❌ No se pudo guardar el comparativo: {e}"}

    comparativo_id = fila["id"]
    try:
        filas_cotizaciones = []
        for i, c in enumerate(cotis, 1):
            ruta = None
            if c.get("archivo_bytes"):
                ruta_prueba = f"{comparativo_id}/cotizacion_{i}_{db.nombre_seguro(c['archivo_nombre'])}"
                try:
                    db.subir_archivo(ruta_prueba, c["archivo_bytes"], c["archivo_tipo"])
                    ruta = ruta_prueba
                except Exception as e:
                    avisos.append(f"⚠️ No se pudo guardar el archivo de «{c['proveedor']}» en el sistema ({e}); igual va adjunto al correo.")
            filas_cotizaciones.append({
                "comparativo_id": comparativo_id,
                **{k: c[k] for k in (
                    "proveedor", "nro_cotizacion", "fecha_cotizacion", "validez_dias", "moneda",
                    "monto", "incluye_iva", "iva_pct", "subtotal_sin_iva_pyg", "subtotal_sin_iva_usd",
                    "total_comparable_pyg", "total_comparable_usd",
                    "plazo_entrega", "garantia", "forma_pago", "alcance", "observaciones", "archivo_nombre")},
                "archivo_path": ruta,
            })
        db.insertar_cotizaciones(filas_cotizaciones)
    except Exception as e:
        try:
            db.borrar_comparativo(comparativo_id)
        except Exception:
            pass
        return {"error_fatal": f"❌ No se pudieron guardar las cotizaciones (no se guardó nada): {e}"}

    pdf = generar_informe_pdf(informe, ordenadas, empresa, logo)
    pdf_nombre = f"Informe_{codigo}.pdf"
    try:
        ruta_pdf = db.subir_archivo(f"{comparativo_id}/{pdf_nombre}", pdf, "application/pdf")
        db.actualizar_comparativo(comparativo_id, {"informe_pdf_path": ruta_pdf})
    except Exception as e:
        avisos.append(f"⚠️ El PDF no se pudo guardar en el sistema ({e}). Descargalo ahora, porque no quedará almacenado.")

    adjuntos = [(c["archivo_nombre"], c["archivo_bytes"], c["archivo_tipo"]) for c in cotis if c.get("archivo_bytes")]
    email_ok, email_error = True, ""
    try:
        enviar_email_informe(informe, ordenadas, pdf, pdf_nombre, adjuntos)
        db.actualizar_comparativo(comparativo_id, {"estado": "Enviado", "email_enviado": True})
    except Exception as e:
        email_ok, email_error = False, str(e)

    return {"codigo": codigo, "pdf": pdf, "pdf_nombre": pdf_nombre, "email_ok": email_ok,
            "email_error": email_error, "avisos": avisos}


# ----------------------------------------------------------------
# Historial
# ----------------------------------------------------------------
def _render_historial():
    try:
        comparativos = db.listar_comparativos()
    except Exception as e:
        st.error(f"No se pudo leer el historial (¿corriste el SQL del módulo?): {e}")
        return
    if not comparativos:
        st.info("Todavía no hay comparativos guardados.")
        return

    cotizaciones = db.listar_cotizaciones([c["id"] for c in comparativos])
    por_comparativo = {}
    for q in cotizaciones:
        por_comparativo.setdefault(q["comparativo_id"], []).append(q)

    filtro = st.selectbox("Filtrar por estado", ["Todos"] + db.ESTADOS, key="hist_cmp_filtro")
    for c in comparativos:
        if filtro != "Todos" and c["estado"] != filtro:
            continue
        color = ESTADO_COLOR.get(c["estado"], "#7C8894")
        quotes = por_comparativo.get(c["id"], [])
        panel = (
            f"<div class='industrial-panel' style='border-color:{color};'>"
            f"<strong>{_esc(c['codigo'])}</strong> — {_esc(c['objeto'])}<br>"
            f"<small>{_esc((c.get('fecha_informe') or '')[:10])} · {len(quotes)} cotización(es) · "
            f"Recomendado: {_esc(c.get('proveedor_recomendado'))}"
            + (f" · Adjudicado: {_esc(c['proveedor_adjudicado'])}" if c.get("proveedor_adjudicado") else "")
            + f"</small><br><span style='color:{color}; font-weight:bold;'>Estado: {_esc(c['estado'])}</span>"
            "</div>"
        )
        st.markdown(panel, unsafe_allow_html=True)

        with st.expander(f"Ver detalle / gestionar — {c['codigo']}"):
            if quotes:
                ordenadas = db.ordenar_con_diferencias(quotes)
                st.dataframe(pd.DataFrame([{
                    "Proveedor": q["proveedor"], "Oferta original": fmt_monto(q["monto"], q["moneda"]),
                    "Total comparable (USD)": fmt_usd(q["total_comparable_usd"]),
                    "Equivale a (Gs.)": fmt_gs(q["total_comparable_pyg"]),
                    "Dif. vs. más baja": "Más baja" if not q["dif_pct"] else f"+{q['dif_pct']}%",
                    "Plazo": q.get("plazo_entrega") or "—", "Garantía": q.get("garantia") or "—",
                    "Pago": q.get("forma_pago") or "—",
                } for q in ordenadas]), width="stretch", hide_index=True)
            if c.get("tipo_cambio_ref"):
                st.caption(
                    f"Tipo de cambio de referencia: {fmt_tc(c['tipo_cambio_ref'])} por USD"
                    + (f" ({c['tipo_cambio_fuente']})" if c.get("tipo_cambio_fuente") else "")
                )
            st.write(f"**Análisis:** {c.get('analisis') or '—'}")
            st.write(f"**Justificación:** {c.get('justificacion') or '—'}")
            st.caption(f"Elaborado por {c.get('elaborado_por') or '—'} ({c.get('cargo') or '—'})")

            if st.button("🔗 Obtener enlaces a los archivos (válidos 1 hora)", key=f"hist_links_{c['id']}"):
                enlaces = []
                if c.get("informe_pdf_path"):
                    enlaces.append(("Informe PDF", c["informe_pdf_path"]))
                enlaces += [(f"Cotización — {q['proveedor']}", q["archivo_path"]) for q in quotes if q.get("archivo_path")]
                if not enlaces:
                    st.info("No hay archivos guardados para este comparativo.")
                for etiqueta, ruta in enlaces:
                    try:
                        st.markdown(f"- [{etiqueta}]({db.url_firmada(ruta)})")
                    except Exception as e:
                        st.warning(f"No se pudo generar el enlace de «{etiqueta}»: {e}")

            if not c.get("email_enviado"):
                if st.button("📨 Reintentar envío del correo", key=f"hist_retry_{c['id']}"):
                    _reintentar_envio(c, quotes)

            nombres = [q["proveedor"] for q in quotes]
            colA, colB = st.columns(2)
            nuevo_estado = colA.selectbox(
                "Estado", db.ESTADOS, index=db.ESTADOS.index(c["estado"]) if c["estado"] in db.ESTADOS else 0,
                key=f"hist_estado_{c['id']}")
            opciones_adj = ["—"] + nombres
            actual_adj = c.get("proveedor_adjudicado") if c.get("proveedor_adjudicado") in nombres else "—"
            nuevo_adj = colB.selectbox("Proveedor adjudicado (decisión final)", opciones_adj,
                                       index=opciones_adj.index(actual_adj), key=f"hist_adj_{c['id']}")
            if st.button("💾 Guardar seguimiento", key=f"hist_save_{c['id']}"):
                db.actualizar_comparativo(c["id"], {
                    "estado": nuevo_estado, "proveedor_adjudicado": None if nuevo_adj == "—" else nuevo_adj})
                st.success("✅ Seguimiento actualizado.")
                st.rerun()


def _reintentar_envio(c, quotes):
    """Vuelve a enviar un informe ya guardado (baja el PDF y los archivos desde el almacenamiento)."""
    if not c.get("informe_pdf_path"):
        st.error("Este informe no tiene el PDF guardado en el sistema, no se puede reenviar automáticamente.")
        return
    with st.spinner("Reenviando..."):
        try:
            pdf = db.descargar_archivo(c["informe_pdf_path"])
            adjuntos = []
            for q in quotes:
                if q.get("archivo_path"):
                    contenido = db.descargar_archivo(q["archivo_path"])
                    adjuntos.append((q["archivo_nombre"] or "cotizacion", contenido,
                                     mimetypes.guess_type(q["archivo_nombre"] or "")[0]))
            maquina = next((m for m in st.session_state.get("maquinas", []) if m["id"] == c.get("maquina_id")), None)
            informe = {
                "codigo": c["codigo"], "objeto": c["objeto"], "maquina_nombre": maquina["nombre"] if maquina else None,
                "solicitud_ref": None, "tipo_cambio_ref": c.get("tipo_cambio_ref"),
                "tipo_cambio_fuente": c.get("tipo_cambio_fuente"),
                "proveedor_recomendado": c.get("proveedor_recomendado"),
                "justificacion": c.get("justificacion"), "elaborado_por": c.get("elaborado_por"), "cargo": c.get("cargo"),
            }
            enviar_email_informe(informe, db.ordenar_con_diferencias(quotes), pdf, f"Informe_{c['codigo']}.pdf", adjuntos)
            db.actualizar_comparativo(c["id"], {"estado": "Enviado", "email_enviado": True})
        except Exception as e:
            st.error(f"No se pudo reenviar: {e}")
            return
    st.success("✅ Correo enviado.")
    st.rerun()
