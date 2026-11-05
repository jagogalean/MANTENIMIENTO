"""
Acceso a datos de las rutinas del operador para el ADMINISTRADOR (usa el cliente principal de Supabase).
La página que abre el operador usa otro archivo (rutinas_publica.py) con la clave pública.
"""
import re
from datetime import datetime

from database.conection import supabase

BUCKET_REF = "rutinas-ref"                 # público: fotos de referencia
BUCKET_EVIDENCIA = "rutinas-evidencia"     # privado: fotos que saca el operador
LOTE = 150


# ---------------- Zonas ----------------
def listar_zonas():
    return supabase.table("rut_zonas").select("*").order("orden").order("id").execute().data


def insertar_zona(data):
    return supabase.table("rut_zonas").insert(data).execute().data[0]


def actualizar_zona(zona_id, patch):
    return supabase.table("rut_zonas").update(patch).eq("id", zona_id).execute().data


# ---------------- Rutinas (ítems) ----------------
def listar_items():
    return supabase.table("rut_items").select("*").order("zona_id").order("orden").order("id").execute().data


def insertar_item(data):
    return supabase.table("rut_items").insert(data).execute().data[0]


def actualizar_item(item_id, patch):
    return supabase.table("rut_items").update(patch).eq("id", item_id).execute().data


def borrar_item(item_id, fotos):
    """Borra la rutina, sus puntos, pasos y fotos (y los archivos de las fotos). El historial de rondas conserva su copia del título."""
    borrar_archivos(BUCKET_REF, [f["ruta"] for f in fotos if f.get("item_id") == item_id])
    return supabase.table("rut_items").delete().eq("id", item_id).execute().data


# ---------------- Puntos de control y pasos ----------------
def listar_puntos():
    return supabase.table("rut_puntos").select("*").order("item_id").order("orden").order("id").execute().data


def listar_pasos():
    return supabase.table("rut_pasos").select("*").order("item_id").order("orden").order("id").execute().data


def _reemplazar(tabla, item_id, filas, existentes):
    """Inserta las filas nuevas y DESPUÉS borra las viejas: si algo falla, no se pierde lo que había."""
    ids_viejos = [e["id"] for e in existentes if e.get("item_id") == item_id]
    if filas:
        supabase.table(tabla).insert(filas).execute()
    if ids_viejos:
        supabase.table(tabla).delete().in_("id", ids_viejos).execute()


def reemplazar_puntos(item_id, puntos, existentes):
    filas = [{"item_id": item_id, "texto": p["texto"], "tipo": p.get("tipo") or "ok", "unidad": p.get("unidad") or None,
              "minimo": p.get("minimo"), "maximo": p.get("maximo"), "orden": i} for i, p in enumerate(puntos, 1)]
    _reemplazar("rut_puntos", item_id, filas, existentes)


def reemplazar_pasos(item_id, pasos, existentes):
    _reemplazar("rut_pasos", item_id, [{"item_id": item_id, "orden": i, "texto": t} for i, t in enumerate(pasos, 1)], existentes)


# ---------------- Fotos de referencia ----------------
def listar_fotos():
    return supabase.table("rut_fotos").select("*").order("item_id").order("orden").order("id").execute().data


def subir_foto_ref(item_id, contenido, content_type, tipo, paso_orden, leyenda, orden):
    ruta = f"ref/{item_id}/{datetime.now():%Y%m%d%H%M%S%f}.jpg"
    supabase.storage.from_(BUCKET_REF).upload(ruta, contenido, {"content-type": content_type})
    try:
        return supabase.table("rut_fotos").insert({"item_id": item_id, "tipo": tipo, "paso_orden": paso_orden, "ruta": ruta,
                                                   "leyenda": leyenda or None, "orden": orden}).execute().data[0]
    except Exception:
        borrar_archivos(BUCKET_REF, [ruta])
        raise


def actualizar_foto(foto_id, patch):
    return supabase.table("rut_fotos").update(patch).eq("id", foto_id).execute().data


def borrar_foto(foto):
    borrar_archivos(BUCKET_REF, [foto.get("ruta")])
    return supabase.table("rut_fotos").delete().eq("id", foto["id"]).execute().data


def url_publica(ruta):
    return supabase.storage.from_(BUCKET_REF).get_public_url(ruta)


def borrar_archivos(bucket, rutas):
    rutas = [r for r in rutas if r]
    if not rutas:
        return 0
    try:
        supabase.storage.from_(bucket).remove(rutas)
        return len(rutas)
    except Exception:
        return 0


# ---------------- Operadores y PIN ----------------
def listar_operadores():
    filas = supabase.table("rut_operadores").select("*").order("nombre").execute().data
    # el PIN cifrado NO sale de acá: solo se informa si tiene o no
    return [{**{k: v for k, v in f.items() if k != "pin_hash"}, "tiene_pin": bool(f.get("pin_hash"))} for f in filas]


def insertar_operador(nombre):
    return supabase.table("rut_operadores").insert({"nombre": nombre.strip()}).execute().data[0]


def actualizar_operador(operador_id, patch):
    return supabase.table("rut_operadores").update(patch).eq("id", operador_id).execute().data


def establecer_pin(operador_id, pin):
    """Pone o cambia el PIN (4 números). Lo cifra la base de datos; también desbloquea al operador."""
    return supabase.rpc("rut_establecer_pin", {"p_operador_id": operador_id, "p_pin": pin}).execute()


def desbloquear_operador(operador_id):
    return supabase.table("rut_operadores").update({"intentos_fallidos": 0, "bloqueado_hasta": None}).eq("id", operador_id).execute().data


# ---------------- Rondas hechas ----------------
def listar_ejecuciones(desde, hasta):
    q = supabase.table("rut_ejecuciones").select("*")
    if desde:
        q = q.gte("fecha", desde.isoformat())
    if hasta:
        q = q.lte("fecha", hasta.isoformat())
    return q.order("fecha", desc=True).order("id", desc=True).execute().data


def listar_respuestas(ejecucion_ids):
    filas = []
    for i in range(0, len(ejecucion_ids), LOTE):
        filas += supabase.table("rut_respuestas").select("*").in_("ejecucion_id", ejecucion_ids[i:i + LOTE]).order("id").execute().data
    return filas


def url_evidencia(ruta, segundos=3600):
    resp = supabase.storage.from_(BUCKET_EVIDENCIA).create_signed_url(ruta, segundos)
    return (resp.get("signedURL") or resp.get("signedUrl")) if isinstance(resp, dict) else None


# ---------------- Lectura de la clave ----------------
def rol_de_la_clave(clave):
    """Lee, sin conectarse, el rol que trae la clave de Supabase (service_role o anon). None si no se puede leer."""
    try:
        import base64
        import json
        parte = str(clave).split(".")[1]
        parte += "=" * (-len(parte) % 4)
        return json.loads(base64.urlsafe_b64decode(parte)).get("role")
    except Exception:
        return None


def nombre_valido(nombre):
    return bool(re.fullmatch(r".{2,60}", (nombre or "").strip()))
