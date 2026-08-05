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

# ----------------- CRUD PLAN DE MANTENIMIENTO PREVENTIVO -----------------
def get_planes():
    response = supabase.table("planes_mantenimiento").select("*").order("proxima_ejecucion", desc=False).execute()
    return response.data

def insert_plan(data: dict):
    response = supabase.table("planes_mantenimiento").insert(data).execute()
    return response.data

def update_plan(plan_id: str, patch: dict):
    response = supabase.table("planes_mantenimiento").update(patch).eq("id", plan_id).execute()
    return response.data

def delete_plan(plan_id: str):
    response = supabase.table("planes_mantenimiento").delete().eq("id", plan_id).execute()
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
