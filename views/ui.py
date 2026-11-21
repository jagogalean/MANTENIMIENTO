"""
Componentes de interfaz comunes del CMMS MANTENIMIENTO.

Todas las pantallas usan estas funciones para verse igual:
encabezado, etiquetas de estado, estados vacíos, errores y formato de montos.
Los colores y la fuente salen de .streamlit/config.toml (tema global).
"""
import html
import logging

import streamlit as st

log = logging.getLogger("cmms")

# Colores de estado (los mismos de la propuesta visual). Se usan en las
# etiquetas :color-badge[...] de Streamlit y en el HTML de transición.
COLOR_ESTADO = {
    "Pendiente": "gray",
    "En Ejecucion": "blue",
    "En Ejecución": "blue",
    "Bloqueada": "orange",
    "Completada": "green",
    "Cerrada": "green",
    "Abierta": "red",
    "Aprobado": "blue",
    "Comprado": "green",
    "Rechazado": "gray",
    "Descartada": "gray",
    "Convertida": "green",
}

# ------------------------------------------------------------------
# Estilos de transición
# ------------------------------------------------------------------
# Las pantallas antiguas todavía tienen algunos colores escritos a mano
# pensados para el fondo oscuro (texto casi blanco, celeste claro). Estas
# reglas los adaptan al tema claro hasta que cada pantalla se rediseñe.
# Cuando todas las pantallas estén migradas, este bloque se puede borrar.
_CSS_TRANSICION = """
<style>
.industrial-panel{background:#FFFFFF;border:1px solid #DCE2E7;border-radius:6px;padding:16px;margin-bottom:12px;color:#17212B}
.industrial-panel h1,.industrial-panel h2,.industrial-panel h3,.industrial-panel h4{color:#17212B}
[style*="#E5E9EC"],[style*="#e5e9ec"],[style*="#C7CFD6"]{color:#17212B !important}
[style*="color:#38BDF8"],[style*="color: #38BDF8"]{color:#0E5A75 !important}
[style*="#7C8894"],[style*="#5A6570"]{color:#5B6773 !important}
[style*="color:#F59E0B"],[style*="color: #F59E0B"],[style*="#F2A93B"]{color:#8A5300 !important}
[style*="color:#10B981"],[style*="color: #10B981"],[style*="color:#22C55E"],[style*="color: #22C55E"]{color:#1E6B22 !important}
[style*="color:#EF4444"],[style*="color: #EF4444"]{color:#B71C1C !important}
[style*="border-color:#EF4444"],[style*="border-color: #EF4444"]{border-color:#E7B4B4 !important}
</style>
"""


def aplicar_estilos():
    """Se llama una sola vez al inicio de app.py, antes de mostrar cualquier pantalla."""
    st.markdown(_CSS_TRANSICION, unsafe_allow_html=True)


# ------------------------------------------------------------------
# Piezas de pantalla
# ------------------------------------------------------------------
def encabezado(titulo, descripcion=None):
    """Título de la pantalla + una línea que explica para qué sirve."""
    st.title(titulo)
    if descripcion:
        st.caption(descripcion)


def etiqueta_estado(estado):
    """Devuelve el estado como etiqueta de color, lista para usar en st.markdown."""
    texto = str(estado or "—")
    color = COLOR_ESTADO.get(texto, "gray")
    texto = texto.replace("[", "(").replace("]", ")")
    return f":{color}-badge[{texto}]"


def estado_vacio(mensaje, ayuda=None):
    """Mensaje para cuando todavía no hay datos: qué falta y qué hacer."""
    st.info(mensaje)
    if ayuda:
        st.caption(ayuda)


def error_amigable(mensaje, excepcion=None):
    """Muestra un error en lenguaje llano y guarda el detalle técnico en el registro del servidor."""
    if excepcion is not None:
        log.exception("%s | %s", mensaje, excepcion)
    st.error(mensaje)


def esc(valor):
    """Escapa texto que viene de la base antes de meterlo en HTML."""
    return html.escape(str(valor if valor is not None else ""))


def formato_gs(valor):
    """Gs. 1.234.567"""
    try:
        return "Gs. " + f"{float(valor or 0):,.0f}".replace(",", ".")
    except (TypeError, ValueError):
        return "Gs. 0"


def con_contador(texto, cantidad):
    """'Órdenes de trabajo' + 3 -> 'Órdenes de trabajo (3)' (sin contador si es cero)."""
    return f"{texto} ({cantidad})" if cantidad else texto
