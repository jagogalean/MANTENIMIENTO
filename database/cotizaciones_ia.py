"""
IA (Gemini) para el módulo Comparativo de Cotizaciones.

Reglas de diseño:
- La IA NUNCA calcula totales: los montos comparables los calcula Python
  (database.cotizaciones_db.calcular_totales) y la IA solo los narra.
- Todo lo que la IA devuelve es un BORRADOR: el usuario lo revisa y lo
  corrige antes de guardar o enviar nada.

El nombre del modelo se puede cambiar sin tocar código, con un secret:
    GEMINI_MODEL = "gemini-3.5-flash"
(Google retira modelos seguido; si algún día da error de modelo, solo
cambiás ese secret.)
"""
import json
import re
from datetime import datetime
import streamlit as st

MONEDAS_VALIDAS = ("PYG", "USD")
MODELOS_POR_DEFECTO = ("gemini-3.5-flash", "gemini-3.1-flash-lite")


def _modelos_candidatos():
    elegido = st.secrets.get("GEMINI_MODEL", "")
    lista = [elegido] if elegido else []
    for m in MODELOS_POR_DEFECTO:
        if m not in lista:
            lista.append(m)
    return lista


def _llamar_gemini(contenido):
    """Prueba los modelos en orden y devuelve el texto de la primera respuesta válida."""
    try:
        import google.generativeai as genai
    except ImportError:
        raise RuntimeError("Falta instalar 'google-generativeai' en requirements.txt.")

    api_key = st.secrets.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("Falta configurar GEMINI_API_KEY en los secrets de Streamlit.")
    genai.configure(api_key=api_key)

    ultimo_error = None
    for nombre in _modelos_candidatos():
        try:
            modelo = genai.GenerativeModel(nombre)
            respuesta = modelo.generate_content(
                contenido, generation_config={"response_mime_type": "application/json"}
            )
            return respuesta.text
        except Exception as e:  # probamos el siguiente modelo
            ultimo_error = e
    raise RuntimeError(f"Gemini no respondió con ninguno de los modelos probados. Último error: {ultimo_error}")


def _parsear_json(texto):
    limpio = re.sub(r"^```(?:json)?|```$", "", (texto or "").strip(), flags=re.MULTILINE).strip()
    return json.loads(limpio)


def _a_numero(valor):
    if valor is None or valor == "":
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    try:
        return float(str(valor).replace(".", "").replace(",", ".")) if "," in str(valor) else float(valor)
    except ValueError:
        return None


# ----------------------------------------------------------------
# 1) Leer una cotización (PDF o foto)
# ----------------------------------------------------------------
PROMPT_EXTRACCION = """Sos un asistente administrativo en Paraguay que lee cotizaciones de proveedores.
Leé el documento adjunto y devolvé SOLO un JSON con estas claves exactas:

- "proveedor": nombre de la empresa que cotiza
- "nro_cotizacion": número o referencia de la cotización
- "fecha_cotizacion": fecha en formato YYYY-MM-DD
- "validez_dias": validez de la oferta en días (número entero)
- "moneda": PYG (guaraníes) o USD (dólares). Si la cotización está en otra moneda, poné null
- "monto_total": el TOTAL FINAL de la cotización como número (punto decimal, sin símbolos ni separadores de miles)
- "incluye_iva": true si el monto total ya incluye IVA, false si el IVA se suma aparte, null si no se ve
- "iva_pct": porcentaje de IVA aplicado (10, 5 o 0), null si no se ve
- "plazo_entrega": plazo de entrega tal como figura (texto)
- "garantia": garantía tal como figura (texto)
- "forma_pago": condiciones/forma de pago (texto)
- "alcance": resumen breve (1-2 líneas) de lo que se cotiza
- "observaciones": aclaraciones relevantes (texto)

Reglas estrictas:
- En Paraguay los montos usan PUNTO como separador de miles y COMA para decimales
  (ej: "1.549.258" son 1549258). Devolvé el número ya convertido.
- Si un dato no aparece en el documento, poné null. NO inventes ni estimes nada.
- No calcules ni sumes: copiá lo que dice el documento."""


def extraer_datos_cotizacion(contenido: bytes, mime_type: str):
    """
    Lee una cotización (PDF o imagen) y devuelve un dict con los campos
    detectados (None donde no se encontró). Lanza RuntimeError si falla.
    """
    if mime_type not in ("application/pdf", "image/png", "image/jpeg"):
        raise RuntimeError("La IA solo puede leer PDF, PNG o JPG. Para otros formatos cargá los datos a mano.")

    texto = _llamar_gemini([PROMPT_EXTRACCION, {"mime_type": mime_type, "data": contenido}])
    try:
        crudo = _parsear_json(texto)
    except (json.JSONDecodeError, ValueError):
        raise RuntimeError("La IA devolvió una respuesta que no se pudo interpretar. Probá de nuevo o cargá los datos a mano.")
    if isinstance(crudo, list) and crudo:
        crudo = crudo[0]
    if not isinstance(crudo, dict):
        raise RuntimeError("La IA no devolvió datos utilizables.")

    # Normalizar tipos (la IA a veces devuelve números como texto)
    moneda = str(crudo.get("moneda") or "").upper().strip()
    fecha = None
    if crudo.get("fecha_cotizacion"):
        try:
            fecha = datetime.strptime(str(crudo["fecha_cotizacion"])[:10], "%Y-%m-%d").date()
        except ValueError:
            fecha = None
    validez = _a_numero(crudo.get("validez_dias"))
    iva = _a_numero(crudo.get("iva_pct"))

    return {
        "proveedor": (crudo.get("proveedor") or None),
        "nro_cotizacion": (str(crudo["nro_cotizacion"]) if crudo.get("nro_cotizacion") else None),
        "fecha_cotizacion": fecha,
        "validez_dias": int(validez) if validez is not None else None,
        "moneda": moneda if moneda in MONEDAS_VALIDAS else None,
        "monto_total": _a_numero(crudo.get("monto_total")),
        "incluye_iva": crudo.get("incluye_iva") if isinstance(crudo.get("incluye_iva"), bool) else None,
        "iva_pct": int(iva) if iva in (0, 5, 10) else None,
        "plazo_entrega": crudo.get("plazo_entrega") or None,
        "garantia": crudo.get("garantia") or None,
        "forma_pago": crudo.get("forma_pago") or None,
        "alcance": crudo.get("alcance") or None,
        "observaciones": crudo.get("observaciones") or None,
    }


# ----------------------------------------------------------------
# 2) Borrador de análisis y recomendación
# ----------------------------------------------------------------
def _fmt_gs(valor):
    return f"Gs. {valor:,.0f}".replace(",", ".")


def _fmt_usd(valor):
    texto = f"{float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"USD {texto}"


def generar_borrador_analisis(objeto, descripcion, cotizaciones_ordenadas, tipo_cambio_ref):
    """
    cotizaciones_ordenadas: salida de cotizaciones_db.ordenar_con_diferencias
    (ya con totales comparables en USD y Gs. y diferencia porcentual calculados).
    tipo_cambio_ref: guaraníes por 1 USD usado para todo el comparativo.

    Devuelve {"analisis", "proveedor_recomendado", "justificacion"}.
    """
    nombres = [c["proveedor"] for c in cotizaciones_ordenadas]
    lineas = []
    for c in cotizaciones_ordenadas:
        lineas.append(
            f"- {c['proveedor']}: total comparable {_fmt_usd(c['total_comparable_usd'])} "
            f"(equivale a {_fmt_gs(c['total_comparable_pyg'])}; IVA incluido); "
            f"{'es la oferta más baja' if not c.get('dif_pct') else 'es ' + str(c['dif_pct']) + '% más cara que la más baja'}; "
            f"oferta original {c.get('moneda')} {c.get('monto')}; "
            f"plazo de entrega: {c.get('plazo_entrega') or 'no informado'}; "
            f"garantía: {c.get('garantia') or 'no informada'}; "
            f"forma de pago: {c.get('forma_pago') or 'no informada'}; "
            f"validez: {str(c.get('validez_dias')) + ' días' if c.get('validez_dias') else 'no informada'}; "
            f"alcance: {c.get('alcance') or 'no informado'}; "
            f"observaciones: {c.get('observaciones') or 'ninguna'}"
        )

    tipo_cambio_ref = f"{float(tipo_cambio_ref):,.0f}".replace(",", ".")
    prompt = f"""Sos un coordinador de mantenimiento industrial en Paraguay y redactás un informe técnico-económico.

Necesidad: {objeto}
Detalle: {descripcion or 'sin detalle adicional'}

Cotizaciones recibidas (ya normalizadas por el sistema con un único tipo de cambio de referencia de Gs. {tipo_cambio_ref} por USD: los totales comparables y los porcentajes ya están calculados, usalos tal cual y NO recalcules nada):
{chr(10).join(lineas)}

Tarea: redactá en español formal, en tono impersonal, un análisis breve (máximo 180 palabras) que compare las ofertas en precio, plazo, garantía, forma de pago, validez y diferencias de alcance que afecten la comparación. Después proponé UN proveedor recomendado y justificá la elección.

Reglas estrictas:
- Los destinatarios del informe trabajan principalmente en dólares: expresá los montos en USD y mencioná guaraníes solo si aporta.
- Usá SOLO los datos de arriba. Si un dato no fue informado, decilo; no lo inventes.
- Si las ofertas no son comparables por diferencias de alcance, indicalo.
- "proveedor_recomendado" debe ser EXACTAMENTE uno de estos nombres: {json.dumps(nombres, ensure_ascii=False)}

Devolvé SOLO un JSON con las claves: "analisis", "proveedor_recomendado", "justificacion"."""

    texto = _llamar_gemini(prompt)
    try:
        crudo = _parsear_json(texto)
    except (json.JSONDecodeError, ValueError):
        raise RuntimeError("La IA devolvió una respuesta que no se pudo interpretar. Probá de nuevo.")
    if isinstance(crudo, list) and crudo:
        crudo = crudo[0]

    recomendado = crudo.get("proveedor_recomendado")
    if recomendado not in nombres:
        recomendado = nombres[0] if nombres else None  # por defecto, la más baja (el usuario puede cambiarla)

    return {
        "analisis": (crudo.get("analisis") or "").strip(),
        "proveedor_recomendado": recomendado,
        "justificacion": (crudo.get("justificacion") or "").strip(),
    }
