"""
Acceso a datos de la ronda para la PÁGINA PÚBLICA que abre el operador al escanear el QR.
Usa la clave pública (anon): solo puede leer las rutinas activas, ver los nombres de los operadores, verificar un PIN,
subir una foto y enviar una ronda. Las reglas de seguridad están en rutinas.sql.
"""
import uuid
from datetime import datetime

from database.conection_publica import supabase_publico

BUCKET_REF = "rutinas-ref"
BUCKET_EVIDENCIA = "rutinas-evidencia"


def obtener_zona(zona_id):
    r = supabase_publico.table("rut_zonas").select("*").eq("id", zona_id).execute().data
    return r[0] if r else None


def operadores():
    return supabase_publico.table("rut_operadores_publico").select("*").order("nombre").execute().data


def cargar_rutinas(zona_id):
    """Rutinas activas de la zona con sus puntos de control, pasos y fotos: [{..item.., puntos, pasos, fotos}]."""
    items = supabase_publico.table("rut_items").select("*").eq("zona_id", zona_id).order("orden").order("id").execute().data
    if not items:
        return []
    ids = [i["id"] for i in items]
    puntos = supabase_publico.table("rut_puntos").select("*").in_("item_id", ids).order("orden").order("id").execute().data
    pasos = supabase_publico.table("rut_pasos").select("*").in_("item_id", ids).order("orden").order("id").execute().data
    fotos = supabase_publico.table("rut_fotos").select("*").in_("item_id", ids).order("orden").order("id").execute().data
    for it in items:
        it["puntos"] = [p for p in puntos if p["item_id"] == it["id"]]
        it["pasos"] = [p for p in pasos if p["item_id"] == it["id"]]
        it["fotos"] = [f for f in fotos if f["item_id"] == it["id"]]
    return items


def url_foto(ruta):
    return supabase_publico.storage.from_(BUCKET_REF).get_public_url(ruta)


def iniciar_sesion(operador_id, pin):
    """Devuelve {'estado': ok|mal|bloqueado|sin_pin|inactivo, ...}. El PIN se verifica dentro de la base."""
    return supabase_publico.rpc("rut_iniciar_sesion", {"p_operador_id": operador_id, "p_pin": pin}).execute().data


def items_hechos(token, zona_id, desde, hasta):
    return supabase_publico.rpc("rut_items_hechos", {"p_token": token, "p_zona": zona_id, "p_desde": desde.isoformat(), "p_hasta": hasta.isoformat()}).execute().data or []


def subir_evidencia(zona_id, contenido, content_type="image/jpeg"):
    ruta = f"ev/{zona_id}/{datetime.now():%Y%m%d}/{uuid.uuid4().hex}.jpg"
    supabase_publico.storage.from_(BUCKET_EVIDENCIA).upload(ruta, contenido, {"content-type": content_type})
    return ruta


def guardar_ronda(token, ronda_uuid, zona_id, fecha, respuestas):
    """Envía la ronda completa. Devuelve {'estado': ok|sesion_invalida, 'fallas': [...]}."""
    return supabase_publico.rpc("rut_guardar_ejecucion", {"p": {"token": token, "uuid": ronda_uuid, "zona_id": zona_id, "fecha": fecha.isoformat(),
                                                                "respuestas": respuestas}}).execute().data
