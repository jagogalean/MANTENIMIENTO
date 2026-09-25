"""
Envío de emails para el módulo de Solicitud de Compra.

Usa una cuenta de Gmail dedicada (con "Contraseña de aplicación", no la
contraseña normal) para mandar el pedido por correo a compras.

Requiere estos secrets en Streamlit Cloud (Settings -> Secrets):
    SMTP_USER = "tu-cuenta-dedicada@gmail.com"
    SMTP_PASSWORD = "la contraseña de aplicación de 16 letras"

(SMTP_HOST y SMTP_PORT ya vienen con el valor correcto de Gmail por
defecto, no hace falta cargarlos salvo que cambien de proveedor.)
"""
import smtplib
import streamlit as st
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

DESTINATARIOS = [
    "bmorales@vitopelparaguay.com",
    "rjara@vitopelparaguay.com",
    "icaballero@vitopelparaguay.com",
    "mmelo@vitopelargentina.com",
]


def _fmt_gs(monto):
    if not monto:
        return "-"
    try:
        return f"Gs. {float(monto):,.0f}".replace(",", ".")
    except (TypeError, ValueError):
        return str(monto)


def enviar_email_solicitud_compra(solicitud: dict, fotos: list):
    """
    Manda el email de una solicitud de compra a los destinatarios fijos.

    solicitud: diccionario con los datos ya guardados en la base.
    fotos: lista de tuplas (nombre_archivo, bytes, content_type), hasta 3.

    Lanza una excepción si falla el envío (la pantalla que llama a esto
    debe capturarla y avisar al usuario sin perder el pedido, que ya
    quedó guardado en la base antes de intentar mandar el mail).
    """
    smtp_host = st.secrets.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(st.secrets.get("SMTP_PORT", 587))
    smtp_user = st.secrets.get("SMTP_USER", "")
    smtp_password = st.secrets.get("SMTP_PASSWORD", "")

    if not smtp_user or not smtp_password:
        raise ValueError("Faltan SMTP_USER y/o SMTP_PASSWORD en los secrets de Streamlit.")

    msg = MIMEMultipart()
    msg["Subject"] = f"Solicitud de Compra — {solicitud.get('item')} ({solicitud.get('prioridad')})"
    msg["From"] = smtp_user
    msg["To"] = ", ".join(DESTINATARIOS)

    cuerpo = f"""Nueva solicitud de compra desde el sistema de Mantenimiento de Vitopel.

Ítem: {solicitud.get('item')}
Cantidad: {solicitud.get('cantidad')} {solicitud.get('unidad') or ''}
Prioridad: {solicitud.get('prioridad')}
Fecha en que se necesita: {solicitud.get('fecha_necesaria') or 'No especificada'}
Máquina relacionada: {solicitud.get('maquina_nombre') or 'No aplica'}

Justificación:
{solicitud.get('justificacion')}

Proveedor sugerido: {solicitud.get('proveedor_sugerido') or '-'}
Precio estimado: {_fmt_gs(solicitud.get('precio_estimado'))}
Referencia / Link: {solicitud.get('link_referencia') or '-'}

Solicitado por: {solicitud.get('solicitante') or '-'}
Fecha de solicitud: {solicitud.get('fecha_solicitud', '')[:16].replace('T', ' ')}
"""
    msg.attach(MIMEText(cuerpo, "plain"))

    for nombre, contenido, content_type in fotos:
        subtype = (content_type.split("/")[-1] if content_type else "jpeg") or "jpeg"
        img = MIMEImage(contenido, _subtype=subtype, name=nombre)
        img.add_header("Content-Disposition", "attachment", filename=nombre)
        msg.attach(img)

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_user, DESTINATARIOS, msg.as_string())
