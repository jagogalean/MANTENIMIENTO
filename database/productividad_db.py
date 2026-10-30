"""
Acceso a datos de Productividad (catálogos, registros por turno, setups, paradas y rechazos).
Usa el mismo cliente de Supabase que el resto de la app (database.conection).
"""
from database.conection import supabase

LOTE = 150          # cuántos registros se consultan por vez (para no armar direcciones web demasiado largas)


# ----------------------------------------------------------------
# Catálogos
# ----------------------------------------------------------------
def listar_catalogo():
    return supabase.table("prod_catalogos").select("*").order("tipo").order("orden").order("id").execute().data


def insertar_catalogo(data: dict):
    return supabase.table("prod_catalogos").insert(data).execute().data[0]


def actualizar_catalogo(item_id, patch: dict):
    return supabase.table("prod_catalogos").update(patch).eq("id", item_id).execute().data


def listar_familias():
    return supabase.table("prod_familias").select("*").order("id").execute().data


def insertar_familia(data: dict):
    return supabase.table("prod_familias").insert(data).execute().data[0]


def actualizar_familia(familia_id, patch: dict):
    return supabase.table("prod_familias").update(patch).eq("id", familia_id).execute().data


# ----------------------------------------------------------------
# Registros
# ----------------------------------------------------------------
def listar_turnos(desde=None, hasta=None):
    q = supabase.table("prod_turnos").select("*")
    if desde:
        q = q.gte("fecha", desde.isoformat())
    if hasta:
        q = q.lte("fecha", hasta.isoformat())
    return q.order("fecha", desc=True).order("hora_inicio", desc=True).execute().data


def _hijos(tabla, turno_ids):
    filas = []
    for i in range(0, len(turno_ids), LOTE):
        lote = turno_ids[i:i + LOTE]
        filas += supabase.table(tabla).select("*").in_("turno_id", lote).order("inicio" if tabla != "prod_rechazos" else "id").execute().data
    return filas


def listar_todo(desde=None, hasta=None):
    """Registros del período con sus setups, paradas y rechazos: (turnos, setups, paradas, rechazos)."""
    turnos = listar_turnos(desde, hasta)
    ids = [t["id"] for t in turnos]
    if not ids:
        return turnos, [], [], []
    return turnos, _hijos("prod_setups", ids), _hijos("prod_paradas", ids), _hijos("prod_rechazos", ids)


def construir_payload(turno, evaluacion, rechazos, usuario, turno_id=None):
    """
    Arma lo que recibe la función prod_guardar_turno de Supabase. 'evaluacion' es el resultado de
    productividad_logica.evaluar_formulario (con los setups y paradas ya ubicados en fecha y hora).
    """
    iso = lambda v: v.isoformat() if v is not None else None
    return {
        "id": turno_id,
        "fecha": iso(turno["fecha"]), "hora_inicio": turno["hora_inicio"].strftime("%H:%M:%S"), "hora_fin": turno["hora_fin"].strftime("%H:%M:%S"),
        "op": str(turno["op"]).strip(), "item": (turno.get("item") or "").strip(), "operador": turno["operador"],
        "producto": (turno.get("producto") or "").strip(), "ancho_cm": turno.get("ancho_cm"), "espesor_um": turno.get("espesor_um"),
        "densidad": turno.get("densidad"), "familia": turno.get("familia"), "maquina": turno.get("maquina"), "barrera": turno.get("barrera"),
        "color": turno.get("color"), "kg_producidos": turno.get("kg_producidos") or 0, "scrap_refile_kg": turno.get("scrap_refile_kg") or 0,
        "observaciones": (turno.get("observaciones") or "").strip(), "usuario": (usuario or {}).get("nombre"),
        "setups": [{"tipo": s.get("tipo"), "inicio": s["inicio"].isoformat(), "fin": s["fin"].isoformat(),
                    "scrap_kg": s.get("scrap_kg") or 0, "observaciones": (s.get("observaciones") or "").strip()} for s in evaluacion["setups"]],
        "paradas": [{"tipo_falla": p.get("tipo_falla"), "sistema": p.get("sistema") or "", "detalle": (p.get("detalle") or "").strip(),
                     "categoria": p.get("categoria") or "", "inicio": p["inicio"].isoformat(), "fin": p["fin"].isoformat()} for p in evaluacion["paradas"]],
        "rechazos": [{"kg": r.get("kg") or 0, "motivo": r.get("motivo")} for r in rechazos if (r.get("kg") or 0) > 0 or r.get("motivo")],
    }


def guardar_turno(payload):
    """Crea o actualiza un registro completo (con sus setups, paradas y rechazos) de una sola vez. Devuelve su id."""
    return supabase.rpc("prod_guardar_turno", {"p": payload}).execute().data


def borrar_turno(turno_id):
    return supabase.table("prod_turnos").delete().eq("id", turno_id).execute().data
