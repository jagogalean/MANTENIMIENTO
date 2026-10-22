"""
Informe técnico (PDF) y envío por correo del Comparativo de Cotizaciones.

Los destinatarios salen de database.email_utils.DESTINATARIOS (la misma
lista que usa Solicitud de Compra): si cambiás los correos ahí, se
actualizan los dos módulos.
"""
import smtplib
from datetime import datetime
from io import BytesIO
from xml.sax.saxutils import escape
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import streamlit as st

from database.email_utils import DESTINATARIOS

# Gmail rechaza mensajes de más de ~25 MB (el adjunto crece ~33% al codificarse).
MAX_ADJUNTOS_MB = 17


# ----------------------------------------------------------------
# Formatos
# ----------------------------------------------------------------
def fmt_gs(valor):
    if valor is None:
        return "—"
    return f"Gs. {valor:,.0f}".replace(",", ".")


def fmt_usd(valor):
    """Dólares con formato paraguayo/argentino: USD 1.180,00"""
    if valor is None:
        return "—"
    s = f"{float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"USD {s}"


def fmt_tc(valor):
    """Tipo de cambio: Gs. 7.450 (sin decimales si es entero)."""
    if valor is None:
        return "—"
    v = float(valor)
    return fmt_gs(v) if v == int(v) else f"Gs. {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_monto(monto, moneda):
    """Monto en su moneda original, con formato paraguayo (1.234,56)."""
    if monto is None:
        return "—"
    if moneda == "PYG":
        return fmt_gs(monto)
    s = f"{float(monto):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{moneda} {s}"


def _fmt_fecha(valor):
    if not valor:
        return "—"
    if isinstance(valor, str):
        try:
            return datetime.fromisoformat(valor.replace("Z", "+00:00")).strftime("%d/%m/%Y")
        except ValueError:
            return valor
    return valor.strftime("%d/%m/%Y")


def _iva_texto(c):
    pct = int(c.get("iva_pct") or 0)
    if pct == 0:
        return "Exento / sin IVA"
    return f"IVA {pct}% " + ("incluido en el precio" if c.get("incluye_iva") else "no incluido (se suma al precio)")


# ----------------------------------------------------------------
# PDF
# ----------------------------------------------------------------
def generar_informe_pdf(informe: dict, cotizaciones_ordenadas: list, nombre_empresa="", logo_bytes=None) -> bytes:
    """
    informe: codigo, fecha, objeto, descripcion, maquina_nombre, solicitud_ref,
             analisis, proveedor_recomendado, justificacion, elaborado_por, cargo
    cotizaciones_ordenadas: lista ya ordenada de menor a mayor total comparable
             (con 'dif_pct'), como la devuelve cotizaciones_db.ordenar_con_diferencias.
    """
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_JUSTIFY, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    AZUL = colors.HexColor("#1F3A5F")
    GRIS = colors.HexColor("#D5DBE1")
    ZEBRA = colors.HexColor("#F4F6F8")
    VERDE = colors.HexColor("#E3F3E7")

    base = getSampleStyleSheet()
    normal = ParagraphStyle("normal", parent=base["Normal"], fontName="Helvetica", fontSize=9.5, leading=13)
    justif = ParagraphStyle("justif", parent=normal, alignment=TA_JUSTIFY)
    chico = ParagraphStyle("chico", parent=normal, fontSize=8, leading=10)
    chico_b = ParagraphStyle("chico_b", parent=chico, fontName="Helvetica-Bold")
    th = ParagraphStyle("th", parent=chico, fontName="Helvetica-Bold", textColor=colors.white)
    titulo = ParagraphStyle("titulo", parent=base["Title"], fontName="Helvetica-Bold", fontSize=14, leading=17,
                            textColor=AZUL, alignment=TA_RIGHT, spaceAfter=2)
    derecha = ParagraphStyle("derecha", parent=normal, alignment=TA_RIGHT)
    h2 = ParagraphStyle("h2", parent=normal, fontName="Helvetica-Bold", fontSize=11, leading=14,
                        textColor=AZUL, spaceBefore=10, spaceAfter=4)
    nota = ParagraphStyle("nota", parent=chico, textColor=colors.HexColor("#555555"))

    def P(texto, estilo=normal):
        t = escape(str(texto)) if texto not in (None, "") else "—"
        return Paragraph(t.replace("\n", "<br/>"), estilo)

    recomendado = informe.get("proveedor_recomendado")
    empresa = nombre_empresa or "Vitopel"
    historia = []

    # --- Encabezado: logo + empresa | título + código + fecha ---
    izquierda = [P(empresa, ParagraphStyle("emp", parent=normal, fontName="Helvetica-Bold", fontSize=12))]
    if logo_bytes:
        try:
            iw, ih = ImageReader(BytesIO(logo_bytes)).getSize()
            escala = min(4.0 * cm / iw, 1.6 * cm / ih)
            izquierda.insert(0, Image(BytesIO(logo_bytes), width=iw * escala, height=ih * escala, hAlign="LEFT"))
        except Exception:
            pass
    derecha_bloque = [
        Paragraph("INFORME TÉCNICO<br/>COMPARATIVO DE COTIZACIONES", titulo),
        P(f"N° {informe.get('codigo')}", derecha),
        P(f"Fecha: {_fmt_fecha(informe.get('fecha'))}", derecha),
    ]
    cabecera = Table([[izquierda, derecha_bloque]], colWidths=[7.5 * cm, 9.5 * cm])
    cabecera.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 1.2, AZUL),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    historia += [cabecera, Spacer(1, 8)]

    # --- Datos generales ---
    datos = [
        [P("Área", chico_b), P("Mantenimiento", chico), P("Elaborado por", chico_b), P(informe.get("elaborado_por"), chico)],
        [P("Equipo / máquina", chico_b), P(informe.get("maquina_nombre") or "No aplica", chico),
         P("Cargo", chico_b), P(informe.get("cargo"), chico)],
        [P("Referencia", chico_b), P(informe.get("solicitud_ref") or "—", chico),
         P("Cotizaciones comparadas", chico_b), P(str(len(cotizaciones_ordenadas)), chico)],
        [P("Tipo de cambio de referencia", chico_b), P(f"{fmt_tc(informe.get('tipo_cambio_ref'))} por 1 USD", chico),
         P("Fuente del tipo de cambio", chico_b), P(informe.get("tipo_cambio_fuente"), chico)],
    ]
    t_datos = Table(datos, colWidths=[3.2 * cm, 5.3 * cm, 3.4 * cm, 5.1 * cm])
    t_datos.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, GRIS),
        ("BACKGROUND", (0, 0), (0, -1), ZEBRA),
        ("BACKGROUND", (2, 0), (2, -1), ZEBRA),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    historia.append(t_datos)

    # --- 1. Objeto ---
    historia.append(Paragraph("1. Objeto", h2))
    historia.append(P(informe.get("objeto"), justif))
    if informe.get("descripcion"):
        historia += [Spacer(1, 3), P(informe.get("descripcion"), justif)]

    # --- 2. Cuadro comparativo ---
    historia.append(Paragraph("2. Cuadro comparativo", h2))
    filas = [[P("#", th), P("Proveedor", th), P("Total comparable (USD, IVA incl.)", th), P("Equivale a (Gs.)", th),
              P("Dif. vs. más baja", th), P("Plazo de entrega", th), P("Garantía", th), P("Forma de pago", th)]]
    for pos, c in enumerate(cotizaciones_ordenadas, 1):
        dif = "Más baja" if not c.get("dif_pct") else f"+{c['dif_pct']}%".replace(".", ",")
        nombre = c["proveedor"] + ("  (recomendada)" if c["proveedor"] == recomendado else "")
        filas.append([P(str(pos), chico), P(nombre, chico_b if c["proveedor"] == recomendado else chico),
                      P(fmt_usd(c.get("total_comparable_usd")), chico_b), P(fmt_gs(c.get("total_comparable_pyg")), chico),
                      P(dif, chico), P(c.get("plazo_entrega"), chico), P(c.get("garantia"), chico), P(c.get("forma_pago"), chico)])
    t_comp = Table(filas, colWidths=[0.7 * cm, 3.2 * cm, 2.5 * cm, 2.7 * cm, 1.6 * cm, 2.3 * cm, 1.9 * cm, 2.1 * cm], repeatRows=1)
    estilo_comp = [
        ("BACKGROUND", (0, 0), (-1, 0), AZUL),
        ("GRID", (0, 0), (-1, -1), 0.4, GRIS),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for i, c in enumerate(cotizaciones_ordenadas, 1):
        if c["proveedor"] == recomendado:
            estilo_comp.append(("BACKGROUND", (0, i), (-1, i), VERDE))
        elif i % 2 == 0:
            estilo_comp.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
    t_comp.setStyle(TableStyle(estilo_comp))
    historia.append(t_comp)

    pie_nota = (
        "Los totales comparables incluyen IVA y están expresados en dólares estadounidenses (USD), con su equivalente en "
        f"guaraníes (Gs.). Se aplicó un único tipo de cambio de referencia a todas las ofertas: {fmt_tc(informe.get('tipo_cambio_ref'))} "
        "por 1 USD" + (f" ({informe.get('tipo_cambio_fuente')})." if informe.get("tipo_cambio_fuente") else ".")
    )
    historia += [Spacer(1, 3), Paragraph(escape(pie_nota), nota)]

    # --- Detalle por proveedor ---
    historia.append(Paragraph("Detalle de cada oferta", h2))
    for c in cotizaciones_ordenadas:
        bloque = [
            [P(c["proveedor"], th), ""],
            [P("N° de cotización", chico_b), P(c.get("nro_cotizacion"), chico)],
            [P("Fecha / validez", chico_b),
             P(f"{_fmt_fecha(c.get('fecha_cotizacion'))} · validez: "
               f"{str(c.get('validez_dias')) + ' días' if c.get('validez_dias') else 'no informada'}", chico)],
            [P("Oferta original", chico_b), P(f"{fmt_monto(c.get('monto'), c.get('moneda'))} — {_iva_texto(c)}", chico)],
            [P("Total comparable", chico_b),
             P(f"{fmt_usd(c.get('total_comparable_usd'))}  (equivale a {fmt_gs(c.get('total_comparable_pyg'))})", chico_b)],
            [P("Alcance", chico_b), P(c.get("alcance"), chico)],
            [P("Observaciones", chico_b), P(c.get("observaciones"), chico)],
            [P("Documento adjunto", chico_b), P(c.get("archivo_nombre") or "Sin archivo adjunto", chico)],
        ]
        t_det = Table(bloque, colWidths=[4.0 * cm, 13.0 * cm])
        t_det.setStyle(TableStyle([
            ("SPAN", (0, 0), (1, 0)),
            ("BACKGROUND", (0, 0), (-1, 0), AZUL),
            ("GRID", (0, 0), (-1, -1), 0.4, GRIS),
            ("BACKGROUND", (0, 1), (0, -1), ZEBRA),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        historia += [KeepTogether([t_det]), Spacer(1, 6)]

    # --- 3. Análisis ---
    historia.append(Paragraph("3. Análisis", h2))
    historia.append(P(informe.get("analisis"), justif))

    # --- 4. Recomendación ---
    historia.append(Paragraph("4. Recomendación", h2))
    historia.append(P(f"Se recomienda la oferta de: {recomendado or '—'}", ParagraphStyle(
        "rec", parent=normal, fontName="Helvetica-Bold")))
    historia += [Spacer(1, 3), P(informe.get("justificacion"), justif)]

    # --- 5. Anexos ---
    historia.append(Paragraph("5. Anexos", h2))
    anexos = [c.get("archivo_nombre") for c in cotizaciones_ordenadas if c.get("archivo_nombre")]
    if anexos:
        for i, nombre in enumerate(anexos, 1):
            historia.append(P(f"Anexo {i}: {nombre}", normal))
    else:
        historia.append(P("No se adjuntaron documentos.", normal))

    # --- Firma ---
    firma = Table([
        [""],
        [P(informe.get("elaborado_por"), ParagraphStyle("f1", parent=normal, fontName="Helvetica-Bold", alignment=1))],
        [P(informe.get("cargo"), ParagraphStyle("f2", parent=normal, alignment=1))],
        [P(empresa, ParagraphStyle("f3", parent=normal, alignment=1))],
    ], colWidths=[7 * cm], rowHeights=[1.6 * cm, None, None, None])
    firma.setStyle(TableStyle([("LINEABOVE", (0, 1), (0, 1), 0.8, colors.black)]))
    historia += [Spacer(1, 12), KeepTogether([firma])]

    # --- Pie de página ---
    codigo = informe.get("codigo")

    def pie(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.drawString(2 * cm, 1.2 * cm, f"Informe N° {codigo} — {empresa} · Mantenimiento")
        canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Página {doc.page}")
        canvas.restoreState()

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=1.8 * cm, bottomMargin=2 * cm,
                            title=f"Informe {codigo}", author=informe.get("elaborado_por") or "")
    doc.build(historia, onFirstPage=pie, onLaterPages=pie)
    return buffer.getvalue()


# ----------------------------------------------------------------
# Correo
# ----------------------------------------------------------------
def _adjuntar(msg, nombre, contenido, content_type):
    tipo = content_type or "application/octet-stream"
    maintype, _, subtype = tipo.partition("/")
    parte = MIMEBase(maintype or "application", subtype or "octet-stream")
    parte.set_payload(contenido)
    encoders.encode_base64(parte)
    parte.add_header("Content-Disposition", "attachment", filename=nombre)
    msg.attach(parte)


def enviar_email_informe(informe: dict, cotizaciones_ordenadas: list, pdf_bytes: bytes, pdf_nombre: str, adjuntos: list):
    """
    Envía el informe a los destinatarios fijos.

    adjuntos: lista de (nombre, bytes, content_type) con las cotizaciones originales.
    Lanza ValueError / excepciones de smtplib si algo falla; quien llama
    decide cómo avisar (el comparativo ya queda guardado antes de enviar).
    """
    smtp_host = st.secrets.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(st.secrets.get("SMTP_PORT", 587))
    smtp_user = st.secrets.get("SMTP_USER", "")
    smtp_password = st.secrets.get("SMTP_PASSWORD", "")
    if not smtp_user or not smtp_password:
        raise ValueError("Faltan SMTP_USER y/o SMTP_PASSWORD en los secrets de Streamlit.")

    total_bytes = len(pdf_bytes) + sum(len(a[1]) for a in adjuntos)
    if total_bytes > MAX_ADJUNTOS_MB * 1024 * 1024:
        raise ValueError(
            f"Los adjuntos pesan {total_bytes / 1024 / 1024:.1f} MB y el máximo para correo es {MAX_ADJUNTOS_MB} MB. "
            "Reducí el tamaño de los archivos o enviá el PDF por otro medio."
        )

    resumen = []
    for pos, c in enumerate(cotizaciones_ordenadas, 1):
        extra = "" if not c.get("dif_pct") else f" (+{str(c['dif_pct']).replace('.', ',')}% vs. la más baja)"
        resumen.append(f"  {pos}. {c['proveedor']}: {fmt_usd(c.get('total_comparable_usd'))} "
                       f"(equivale a {fmt_gs(c.get('total_comparable_pyg'))}){extra}")

    cuerpo = f"""Se adjunta el Informe Técnico {informe.get('codigo')} — Comparativo de Cotizaciones, elaborado por el área de Mantenimiento.

Objeto: {informe.get('objeto')}
Equipo / máquina: {informe.get('maquina_nombre') or 'No aplica'}
Referencia: {informe.get('solicitud_ref') or '—'}

Ofertas recibidas (totales comparables con IVA incluido, en dólares y su equivalente en guaraníes):
{chr(10).join(resumen)}

Tipo de cambio de referencia usado para todas las ofertas: {fmt_tc(informe.get('tipo_cambio_ref'))} por 1 USD{' (' + informe.get('tipo_cambio_fuente') + ')' if informe.get('tipo_cambio_fuente') else ''}.

Proveedor recomendado: {informe.get('proveedor_recomendado')}

Justificación:
{informe.get('justificacion')}

Adjuntos: el informe en PDF y las cotizaciones originales de cada proveedor.

Elaborado por: {informe.get('elaborado_por')} — {informe.get('cargo')}
(Mensaje generado automáticamente desde el sistema de Mantenimiento.)
"""

    msg = MIMEMultipart()
    msg["Subject"] = f"Informe Técnico {informe.get('codigo')} — Comparativo de cotizaciones: {informe.get('objeto')}"
    msg["From"] = smtp_user
    msg["To"] = ", ".join(DESTINATARIOS)
    msg.attach(MIMEText(cuerpo, "plain", "utf-8"))

    _adjuntar(msg, pdf_nombre, pdf_bytes, "application/pdf")
    for nombre, contenido, content_type in adjuntos:
        _adjuntar(msg, nombre, contenido, content_type)

    with smtplib.SMTP(smtp_host, smtp_port, timeout=60) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_user, DESTINATARIOS, msg.as_string())
