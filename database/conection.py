import os
import streamlit as st
from supabase import create_client, Client

@st.cache_resource
def init_supabase() -> Client:
    """Inicializa y cachea la conexión con Supabase."""
    # En producción se usan st.secrets o variables de entorno
    url = st.secrets.get("SUPABASE_URL", os.environ.get("SUPABASE_URL", ""))
    key = st.secrets.get("SUPABASE_KEY", os.environ.get("SUPABASE_KEY", ""))
    
    if not url or not key:
        st.error("Faltan las credenciales de Supabase (SUPABASE_URL y SUPABASE_KEY).")
        st.stop()
        
    return create_client(url, key)

supabase: Client = init_supabase()

# ----------------- CRUD MÁQUINAS -----------------
def get_maquinas():
    response = supabase.table("maquinas").select("*").order("id", desc=True).execute()
    return response.data

def insert_maquina(data: dict):
    response = supabase.table("maquinas").insert(data).execute()
    return response.data

def delete_maquina(maquina_id: str):
    response = supabase.table("maquinas").delete().eq("id", maquina_id).execute()
    return response.data

def update_maquina(maquina_id: str, patch: dict):
    response = supabase.table("maquinas").update(patch).eq("id", maquina_id).execute()
    return response.data

# ----------------- CRUD FALLAS -----------------
def get_fallas():
    response = supabase.table("fallas").select("*").order("id", desc=True).execute()
    return response.data

def insert_falla(data: dict):
    response = supabase.table("fallas").insert(data).execute()
    return response.data

def update_falla(falla_id: str, patch: dict):
    response = supabase.table("fallas").update(patch).eq("id", falla_id).execute()
    return response.data

# ----------------- CRUD CHECKLISTS -----------------
def get_checklists():
    response = supabase.table("checklists").select("*").order("id", desc=True).execute()
    return response.data

def insert_checklist(data: dict):
    response = supabase.table("checklists").insert(data).execute()
    return response.data

def delete_checklist(checklist_id: str):
    response = supabase.table("checklists").delete().eq("id", checklist_id).execute()
    return response.data

# ----------------- CRUD TERCEROS -----------------
def get_terceros():
    response = supabase.table("terceros").select("*").order("id", desc=True).execute()
    return response.data

def insert_tercero(data: dict):
    response = supabase.table("terceros").insert(data).execute()
    return response.data

def delete_tercero(tercero_id: str):
    response = supabase.table("terceros").delete().eq("id", tercero_id).execute()
    return response.data

# ----------------- CRUD OTs (Órdenes de Trabajo) -----------------
def get_ots():
    response = supabase.table("ots").select("*").order("id", desc=True).execute()
    return response.data

def insert_ot(data: dict):
    response = supabase.table("ots").insert(data).execute()
    return response.data

def update_ot(ot_id: str, patch: dict):
    response = supabase.table("ots").update(patch).eq("id", ot_id).execute()
    return response.data

def delete_ot(ot_id: str):
    """NUEVO: permite borrar una OT definitivamente. Pensado para uso exclusivo
    de administradores (el control de quién puede llamar a esto se hace en la vista,
    con database.permisos.es_admin)."""
    response = supabase.table("ots").delete().eq("id", ot_id).execute()
    return response.data

# ----------------- CRUD REPUESTOS e INVENTARIO -----------------
def get_repuestos():
    response = supabase.table("repuestos").select("*").order("id", desc=True).execute()
    return response.data

def insert_repuesto(data: dict):
    response = supabase.table("repuestos").insert(data).execute()
    return response.data

def update_repuesto(repuesto_id: str, patch: dict):
    response = supabase.table("repuestos").update(patch).eq("id", repuesto_id).execute()
    return response.data

# (Opcional) Tabla intermedia de consumo de repuestos por OT
def insert_ot_repuesto(data: dict):
    response = supabase.table("ot_repuestos").insert(data).execute()
    return response.data

def get_ot_repuestos():
    response = supabase.table("ot_repuestos").select("*").execute()
    return response.data

# ----------------- AUTENTICACIÓN Y USUARIOS (roles) -----------------
def login_usuario(email: str, password: str):
    return supabase.auth.sign_in_with_password({"email": email, "password": password})

def logout_usuario():
    supabase.auth.sign_out()

def get_usuario_by_id(user_id: str):
    response = supabase.table("usuarios").select("*").eq("id", user_id).execute()
    return response.data[0] if response.data else None

def get_usuarios():
    response = supabase.table("usuarios").select("*").execute()
    return response.data

def insert_usuario(data: dict):
    response = supabase.table("usuarios").insert(data).execute()
    return response.data

def update_usuario(user_id: str, patch: dict):
    response = supabase.table("usuarios").update(patch).eq("id", user_id).execute()
    return response.data

def delete_usuario(user_id: str):
    response = supabase.table("usuarios").delete().eq("id", user_id).execute()
    return response.data

# ----------------- CRUD TÉCNICOS -----------------
def get_tecnicos():
    response = supabase.table("tecnicos").select("*").order("id", desc=True).execute()
    return response.data

def insert_tecnico(data: dict):
    response = supabase.table("tecnicos").insert(data).execute()
    return response.data

def delete_tecnico(tecnico_id: str):
    response = supabase.table("tecnicos").delete().eq("id", tecnico_id).execute()
    return response.data

def update_tecnico(tecnico_id: str, patch: dict):
    response = supabase.table("tecnicos").update(patch).eq("id", tecnico_id).execute()
    return response.data

# ----------------- CRUD PLAN PREVENTIVO (cabecera: máquina + frecuencia) -----------------
def get_planes():
    response = supabase.table("planes_preventivos").select("*").order("proxima_ejecucion", desc=False).execute()
    return response.data

def insert_plan(data: dict):
    response = supabase.table("planes_preventivos").insert(data).execute()
    return response.data

def update_plan(plan_id: str, patch: dict):
    response = supabase.table("planes_preventivos").update(patch).eq("id", plan_id).execute()
    return response.data

def delete_plan(plan_id: str):
    response = supabase.table("planes_preventivos").delete().eq("id", plan_id).execute()
    return response.data

# ----------------- CRUD ACTIVIDADES DENTRO DE UN PLAN -----------------
def get_actividades():
    response = supabase.table("plan_actividades").select("*").execute()
    return response.data

def insert_actividad(data: dict):
    response = supabase.table("plan_actividades").insert(data).execute()
    return response.data

def delete_actividad(actividad_id: str):
    response = supabase.table("plan_actividades").delete().eq("id", actividad_id).execute()
    return response.data

# ----------------- CRUD DOCUMENTOS TÉCNICOS POR MÁQUINA -----------------
def get_documentos():
    response = supabase.table("documentos_maquina").select("*").order("id", desc=True).execute()
    return response.data

def insert_documento(data: dict):
    response = supabase.table("documentos_maquina").insert(data).execute()
    return response.data

def delete_documento(documento_id: str):
    response = supabase.table("documentos_maquina").delete().eq("id", documento_id).execute()
    return response.data

# ----------------- HISTORIAL DE EJECUCIONES DEL PLAN (prevista vs realizada) -----------------
def get_plan_ejecuciones():
    response = supabase.table("plan_ejecuciones").select("*").execute()
    return response.data

def insert_plan_ejecucion(data: dict):
    response = supabase.table("plan_ejecuciones").insert(data).execute()
    return response.data

# ----------------- CONFIGURACIÓN DE EMPRESA (logo/nombre persistentes) -----------------
def get_configuracion_empresa():
    response = supabase.table("configuracion_empresa").select("*").eq("id", 1).execute()
    return response.data[0] if response.data else None

def guardar_configuracion_empresa(nombre_empresa: str, logo_base64: str):
    payload = {"id": 1, "nombre_empresa": nombre_empresa, "logo_base64": logo_base64}
    response = supabase.table("configuracion_empresa").upsert(payload).execute()
    return response.data


# ============================================================
# ============ NUEVO: LECTURAS CON CACHÉ (RENDIMIENTO) ========
# ============================================================
# Catálogos que casi no cambian -> caché larga (5 minutos).
# Se usan en pantallas de alta concurrencia (Mis OTs, OTs) para no golpear
# Supabase en cada click de cada usuario. Cuando alguien edita un catálogo
# desde su propia vista (Máquinas, Técnicos), esa vista sigue refrescando
# st.session_state como siempre; esta caché igual vence sola a los 5 minutos.

@st.cache_data(ttl=300, show_spinner=False)
def get_maquinas_cached():
    return get_maquinas()

@st.cache_data(ttl=300, show_spinner=False)
def get_tecnicos_cached():
    return get_tecnicos()

@st.cache_data(ttl=300, show_spinner=False)
def get_terceros_cached():
    return get_terceros()


# Datos transaccionales (OTs, Stock) -> caché corta (15 segundos).
# Esto evita que dos técnicos vean el backlog "viejo" durante mucho tiempo,
# sin golpear la base de datos en cada rerender de Streamlit. Después de
# cualquier escritura (insert/update/delete), hay que llamar a .clear()
# para que el propio usuario vea el cambio al instante.

@st.cache_data(ttl=15, show_spinner=False)
def get_ots_cached():
    return get_ots()

@st.cache_data(ttl=15, show_spinner=False)
def get_repuestos_cached():
    return get_repuestos()


# ============================================================
# ============ NUEVO: PAGINACIÓN SERVER-SIDE (RENDIMIENTO) ====
# ============================================================
def get_ots_paginado(pagina: int = 1, tamanio: int = 25, estado: str | None = None):
    """
    Trae solo una "página" de OTs desde Supabase (no toda la tabla), usando
    .range() del lado del servidor. Devuelve (filas_de_la_pagina, total_de_filas).

    Se usa para el listado/historial (que crece indefinidamente); NO se usa
    para el Dashboard ni el Asistente del Día, que necesitan ver el 100%
    de los datos para calcular KPIs y armar la agenda.
    """
    desde = (pagina - 1) * tamanio
    hasta = desde + tamanio - 1

    query = supabase.table("ots").select("*", count="exact").order("id", desc=True)
    if estado:
        query = query.eq("estado", estado)

    response = query.range(desde, hasta).execute()
    return response.data, (response.count or 0)


# ============================================================
# ============ NUEVO: RPC TRANSACCIONALES (INTEGRIDAD) ========
# ============================================================
# Estas dos funciones llaman a procedimientos SQL creados en Supabase
# (ver archivo mejoras_cmms.sql) que hacen el chequeo + la escritura en
# una sola transacción atómica, eliminando la condición de carrera que
# existía al hacer "leer stock -> comparar en Python -> escribir" en dos
# pasos separados.

def consumir_repuesto_seguro(ot_id, repuesto_id, cantidad):
    """
    Descuenta stock de un repuesto y registra su consumo en una OT,
    todo en una sola transacción SQL (función consumir_repuesto en Supabase).

    Lanza ValueError("STOCK_INSUFICIENTE") si no hay stock suficiente
    en el momento exacto de guardar (por ejemplo, si otro técnico lo
    consumió un segundo antes).
    """
    try:
        response = supabase.rpc("consumir_repuesto", {
            "p_ot_id": ot_id,
            "p_repuesto_id": repuesto_id,
            "p_cantidad": cantidad
        }).execute()
        return response.data
    except Exception as e:
        if "STOCK_INSUFICIENTE" in str(e):
            raise ValueError("STOCK_INSUFICIENTE")
        raise


def tomar_ot_backlog_seguro(ot_id, tecnico_id):
    """
    Asigna una OT del backlog compartido a un técnico, pero solo si sigue
    sin asignar en ese instante (función tomar_ot_backlog en Supabase).

    Lanza ValueError("OT_YA_TOMADA") si otro técnico ya se la asignó
    un segundo antes.
    """
    try:
        response = supabase.rpc("tomar_ot_backlog", {
            "p_ot_id": ot_id,
            "p_tecnico_id": tecnico_id
        }).execute()
        return response.data
    except Exception as e:
        if "OT_YA_TOMADA" in str(e):
            raise ValueError("OT_YA_TOMADA")
        raise


# ============================================================
# ============ NUEVO: PRESUPUESTO DE MANTENIMIENTO ============
# ============================================================
def get_presupuestos():
    response = supabase.table("presupuestos").select("*").order("periodo", desc=True).execute()
    return response.data

@st.cache_data(ttl=60, show_spinner=False)
def get_presupuestos_cached():
    return get_presupuestos()

def guardar_presupuesto(periodo: str, categoria: str, monto: float):
    """
    Crea o actualiza el presupuesto de un mes + categoría (upsert: si ya
    existe una fila para ese mes y esa categoría, la actualiza en vez de
    duplicarla, gracias al 'unique (periodo, categoria)' de la tabla).

    periodo: string 'YYYY-MM-01' (siempre el día 1 del mes)
    categoria: 'total' | 'mano_obra' | 'repuestos' | 'terceros'
    """
    payload = {"periodo": periodo, "categoria": categoria, "monto": monto}
    response = supabase.table("presupuestos").upsert(payload, on_conflict="periodo,categoria").execute()
    return response.data
