"""
Acceso a datos del módulo Comparativo de Cotizaciones.

Usa el mismo cliente de Supabase que el resto de la app (database.conection),
pero vive en un archivo aparte para no tocar conection.py.
"""
import re
import unicodedata
from datetime import datetime
from database.conection import supabase

BUCKET = "cotizaciones"
MONEDAS = ["PYG", "USD"]
ESTADOS = ["Pendiente de envío", "Enviado", "Aprobado", "Comprado", "Rechazado"]


# ----------------------------------------------------------------
# Cálculos (puros, sin base de datos)
# ----------------------------------------------------------------
def calcular_totales(monto, moneda, incluye_iva, iva_pct, tc_ref):
    """
    Lleva una cotización a una base comparable: con IVA incluido y expresada
    en DÓLARES y en GUARANÍES a la vez.

    - Si el precio ya incluye IVA, se respeta tal cual; si no, se le suma el
      IVA indicado (10%, 5% o 0%).
    - tc_ref es UN solo tipo de cambio de referencia para todo el comparativo
      (guaraníes por 1 USD). Se usa para pasar de una moneda a la otra, así la
      tabla en dólares y la tabla en guaraníes siempre dan el mismo orden.

    Devuelve un dict con subtotal_sin_iva_usd/pyg y total_comparable_usd/pyg,
    o None si faltan datos (monto vacío, moneda no admitida o tipo de cambio
    vacío).
    """
    try:
        monto = float(monto or 0)
        iva = float(iva_pct or 0) / 100.0
        tc = float(tc_ref or 0)
    except (TypeError, ValueError):
        return None
    if monto <= 0 or tc <= 0 or moneda not in MONEDAS:
        return None

    if incluye_iva:
        con_iva = monto
        sin_iva = monto / (1.0 + iva)
    else:
        sin_iva = monto
        con_iva = monto * (1.0 + iva)

    if moneda == "USD":
        sin_iva_usd, con_iva_usd = sin_iva, con_iva
        sin_iva_pyg, con_iva_pyg = sin_iva * tc, con_iva * tc
    else:  # PYG
        sin_iva_pyg, con_iva_pyg = sin_iva, con_iva
        sin_iva_usd, con_iva_usd = sin_iva / tc, con_iva / tc

    return {
        "subtotal_sin_iva_usd": round(sin_iva_usd, 2),
        "total_comparable_usd": round(con_iva_usd, 2),
        "subtotal_sin_iva_pyg": int(round(sin_iva_pyg)),
        "total_comparable_pyg": int(round(con_iva_pyg)),
    }


def aplicar_totales(cotizaciones, tc_ref):
    """
    Devuelve copias de las cotizaciones con los totales (USD y Gs.) calculados
    con el tipo de cambio de referencia actual. Si cambiás el tipo de cambio,
    todo se recalcula solo. Devuelve None si el tipo de cambio no es válido o
    alguna cotización no se pudo calcular.
    """
    resultado = []
    for c in cotizaciones:
        t = calcular_totales(c.get("monto"), c.get("moneda"), c.get("incluye_iva"), c.get("iva_pct"), tc_ref)
        if not t:
            return None
        copia = dict(c)
        copia.update(t)
        resultado.append(copia)
    return resultado


def ordenar_con_diferencias(cotizaciones):
    """
    Ordena de menor a mayor total comparable (en dólares) y agrega 'dif_pct':
    cuánto más cara es cada oferta respecto de la más baja (0.0 para la más baja).
    Espera cotizaciones que ya tengan 'total_comparable_usd'.
    """
    validas = [c for c in cotizaciones if c.get("total_comparable_usd")]
    ordenadas = sorted(validas, key=lambda c: float(c["total_comparable_usd"]))
    base = float(ordenadas[0]["total_comparable_usd"]) if ordenadas else None
    resultado = []
    for c in ordenadas:
        copia = dict(c)
        copia["dif_pct"] = round((float(c["total_comparable_usd"]) / base - 1) * 100, 1) if base else None
        resultado.append(copia)
    return resultado


def nombre_seguro(nombre):
    """
    Convierte un nombre de archivo a uno que Supabase Storage acepta
    (sin tildes, sin espacios ni caracteres raros).
    """
    base = unicodedata.normalize("NFKD", nombre or "").encode("ascii", "ignore").decode("ascii")
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")
    return base or "archivo"


# ----------------------------------------------------------------
# Base de datos
# ----------------------------------------------------------------
def generar_codigo_informe():
    """Siguiente código consecutivo del año. Ej: INF-2026-0003"""
    prefijo = f"INF-{datetime.now().year}-"
    resp = supabase.table("comparativos_cotizacion").select("codigo").like("codigo", f"{prefijo}%").execute()
    numeros = []
    for fila in resp.data or []:
        try:
            numeros.append(int((fila.get("codigo") or "").replace(prefijo, "")))
        except ValueError:
            pass
    siguiente = (max(numeros) + 1) if numeros else 1
    return f"{prefijo}{siguiente:04d}"


def insertar_comparativo(data: dict):
    resp = supabase.table("comparativos_cotizacion").insert(data).execute()
    return resp.data[0]


def insertar_cotizaciones(filas: list):
    resp = supabase.table("cotizaciones_proveedor").insert(filas).execute()
    return resp.data


def actualizar_comparativo(comparativo_id, patch: dict):
    resp = supabase.table("comparativos_cotizacion").update(patch).eq("id", comparativo_id).execute()
    return resp.data


def borrar_comparativo(comparativo_id):
    """Borra el comparativo y (por cascade) sus cotizaciones."""
    resp = supabase.table("comparativos_cotizacion").delete().eq("id", comparativo_id).execute()
    return resp.data


def listar_comparativos(limite=30):
    resp = (
        supabase.table("comparativos_cotizacion")
        .select("*")
        .order("fecha_informe", desc=True)
        .limit(limite)
        .execute()
    )
    return resp.data


def listar_cotizaciones(comparativo_ids: list):
    """Trae las cotizaciones de varios comparativos en una sola consulta."""
    if not comparativo_ids:
        return []
    resp = (
        supabase.table("cotizaciones_proveedor")
        .select("*")
        .in_("comparativo_id", comparativo_ids)
        .order("id")
        .execute()
    )
    return resp.data


# ----------------------------------------------------------------
# Archivos (bucket privado)
# ----------------------------------------------------------------
def subir_archivo(ruta, contenido: bytes, content_type: str):
    supabase.storage.from_(BUCKET).upload(
        ruta, contenido, {"content-type": content_type or "application/octet-stream"}
    )
    return ruta


def descargar_archivo(ruta) -> bytes:
    return supabase.storage.from_(BUCKET).download(ruta)


def url_firmada(ruta, segundos=3600):
    """Enlace temporal (1 hora) para ver/descargar un archivo privado."""
    resp = supabase.storage.from_(BUCKET).create_signed_url(ruta, segundos)
    if isinstance(resp, dict):
        return resp.get("signedURL") or resp.get("signedUrl")
    return None
