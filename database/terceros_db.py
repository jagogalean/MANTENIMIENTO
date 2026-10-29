"""
Acceso a datos de los trabajos con terceros (trabajos, facturas, pagos y documentos) y a los
archivos (fotos/PDF) guardados en un espacio privado de Supabase.

Usa el mismo cliente de Supabase que el resto de la app (database.conection).
"""
from datetime import datetime

from database.conection import supabase
from database.terceros_logica import nombre_seguro

BUCKET = "terceros"


# ----------------------------------------------------------------
# Proveedores (tabla terceros que ya existía)
# ----------------------------------------------------------------
def actualizar_tercero(tercero_id, patch: dict):
    return supabase.table("terceros").update(patch).eq("id", tercero_id).execute().data


# ----------------------------------------------------------------
# Trabajos
# ----------------------------------------------------------------
def generar_codigo_trabajo():
    """Siguiente código consecutivo del año. Ej: TT-2026-0007"""
    prefijo = f"TT-{datetime.now().year}-"
    resp = supabase.table("trabajos_terceros").select("codigo").like("codigo", f"{prefijo}%").execute()
    numeros = []
    for fila in resp.data or []:
        try:
            numeros.append(int((fila.get("codigo") or "").replace(prefijo, "")))
        except ValueError:
            pass
    return f"{prefijo}{(max(numeros) + 1 if numeros else 1):04d}"


def listar_trabajos():
    return supabase.table("trabajos_terceros").select("*").order("id", desc=True).execute().data


def insertar_trabajo(data: dict):
    return supabase.table("trabajos_terceros").insert(data).execute().data[0]


def actualizar_trabajo(trabajo_id, patch: dict):
    return supabase.table("trabajos_terceros").update(patch).eq("id", trabajo_id).execute().data


def borrar_trabajo(trabajo_id):
    return supabase.table("trabajos_terceros").delete().eq("id", trabajo_id).execute().data


# ----------------------------------------------------------------
# Facturas y pagos
# ----------------------------------------------------------------
def listar_facturas():
    return supabase.table("facturas_terceros").select("*").order("id").execute().data


def insertar_factura(data: dict):
    return supabase.table("facturas_terceros").insert(data).execute().data[0]


def actualizar_factura(factura_id, patch: dict):
    return supabase.table("facturas_terceros").update(patch).eq("id", factura_id).execute().data


def borrar_factura(factura_id):
    return supabase.table("facturas_terceros").delete().eq("id", factura_id).execute().data


def listar_pagos():
    return supabase.table("pagos_terceros").select("*").order("id").execute().data


def insertar_pago(data: dict):
    return supabase.table("pagos_terceros").insert(data).execute().data[0]


def actualizar_pago(pago_id, patch: dict):
    return supabase.table("pagos_terceros").update(patch).eq("id", pago_id).execute().data


def borrar_pago(pago_id):
    return supabase.table("pagos_terceros").delete().eq("id", pago_id).execute().data


# ----------------------------------------------------------------
# Documentos (fotos y PDF)
# ----------------------------------------------------------------
def listar_documentos():
    return supabase.table("documentos_terceros").select("*").order("id").execute().data


def insertar_documento(data: dict):
    return supabase.table("documentos_terceros").insert(data).execute().data[0]


def borrar_documento(documento_id):
    return supabase.table("documentos_terceros").delete().eq("id", documento_id).execute().data


def subir_archivo(ruta, contenido: bytes, content_type: str):
    supabase.storage.from_(BUCKET).upload(ruta, contenido, {"content-type": content_type or "application/octet-stream"})
    return ruta


def url_firmada(ruta, segundos=3600):
    """Enlace temporal (1 hora) para ver un archivo privado."""
    resp = supabase.storage.from_(BUCKET).create_signed_url(ruta, segundos)
    if isinstance(resp, dict):
        return resp.get("signedURL") or resp.get("signedUrl")
    return None


def borrar_archivos(rutas):
    """Borra archivos del espacio privado. Si alguno falla, sigue con el resto (no frena el borrado de los datos)."""
    rutas = [r for r in rutas if r]
    if not rutas:
        return 0
    try:
        supabase.storage.from_(BUCKET).remove(rutas)
        return len(rutas)
    except Exception:
        return 0


def adjuntar_archivos(trabajo_id, tipo, archivos, factura_id=None, pago_id=None):
    """
    Sube archivos ya preparados (ver terceros_logica.preparar_archivo) y registra cada uno como
    documento del trabajo. Devuelve (cantidad_subida, [errores]). Un archivo que falla no frena a los demás.
    """
    subidos, errores = 0, []
    sello = datetime.now().strftime("%Y%m%d%H%M%S")
    for i, a in enumerate(archivos, 1):
        ruta = f"{trabajo_id}/{nombre_seguro(tipo)}_{sello}_{i}_{nombre_seguro(a['nombre'])}"
        try:
            subir_archivo(ruta, a["contenido"], a["content_type"])
        except Exception as e:
            errores.append(f"«{a['nombre']}»: no se pudo subir ({e})")
            continue
        try:
            insertar_documento({"trabajo_id": trabajo_id, "tipo": tipo, "factura_id": factura_id, "pago_id": pago_id,
                                "archivo_path": ruta, "archivo_nombre": a["nombre"]})
            subidos += 1
        except Exception as e:
            borrar_archivos([ruta])
            errores.append(f"«{a['nombre']}»: se subió pero no se pudo registrar ({e})")
    return subidos, errores


def quitar_documento(documento):
    """Borra el archivo y su registro."""
    borrar_archivos([documento.get("archivo_path")])
    borrar_documento(documento["id"])


def borrar_trabajo_completo(trabajo_id, documentos):
    """Borra los archivos del trabajo y después el trabajo (sus facturas, pagos y documentos se borran en cascada)."""
    borrar_archivos([d.get("archivo_path") for d in documentos if d.get("trabajo_id") == trabajo_id])
    borrar_trabajo(trabajo_id)


def borrar_factura_completa(factura_id, documentos):
    borrar_archivos([d.get("archivo_path") for d in documentos if d.get("factura_id") == factura_id])
    borrar_factura(factura_id)


def borrar_pago_completo(pago_id, documentos):
    borrar_archivos([d.get("archivo_path") for d in documentos if d.get("pago_id") == pago_id])
    borrar_pago(pago_id)
