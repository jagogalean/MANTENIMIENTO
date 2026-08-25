"""
Cliente de Supabase SEPARADO del principal, exclusivo para la vista pública
(la que se ve al escanear un QR, sin necesidad de iniciar sesión).
"""
import os
import streamlit as st
from supabase import create_client, Client

@st.cache_resource
def init_supabase_publico() -> Client:
    url = st.secrets.get("SUPABASE_URL", os.environ.get("SUPABASE_URL", ""))
    anon_key = st.secrets.get("SUPABASE_ANON_KEY", os.environ.get("SUPABASE_ANON_KEY", ""))

    if not url or not anon_key:
        st.error("Faltan las credenciales públicas de Supabase (SUPABASE_URL y SUPABASE_ANON_KEY) en los secrets.")
        st.stop()

    return create_client(url, anon_key)


@st.cache_resource
def init_supabase_admin() -> Client:
    url = st.secrets.get("SUPABASE_URL", os.environ.get("SUPABASE_URL", ""))
    # Usa la clave principal/service_role para bypass de RLS
    service_key = st.secrets.get("SUPABASE_KEY", os.environ.get("SUPABASE_KEY", ""))

    if not url or not service_key:
        st.error("Falta la credencial principal (SUPABASE_KEY) en los secrets.")
        st.stop()

    return create_client(url, service_key)


supabase_publico: Client = init_supabase_publico()
supabase_admin: Client = init_supabase_admin()


def get_ficha_publica_equipo(equipo_id):
    """
    Trae la ficha pública de un equipo desde la vista 'equipos_publico'
    (nombre, ubicación, último y próximo preventivo).
    """
    response = supabase_publico.table("equipos_publico").select("*").eq("id", equipo_id).execute()
    return response.data[0] if response.data else None


def insertar_solicitud_falla(data: dict):
    """
    Inserta un reporte público de avería utilizando el cliente con permisos
    para omitir bloqueos de RLS y secuencias.
    """
    data["estado"] = "Pendiente"
    response = supabase_admin.table("solicitudes_falla").insert(data).execute()
    return response.data


def get_info_debug():
    """
    TEMPORAL — solo para depurar el error de RLS.
    """
    url = st.secrets.get("SUPABASE_URL", os.environ.get("SUPABASE_URL", ""))
    anon_key = st.secrets.get("SUPABASE_ANON_KEY", os.environ.get("SUPABASE_ANON_KEY", ""))
    if len(anon_key) > 20:
        key_enmascarada = f"{anon_key[:8]}...{anon_key[-6:]} (largo: {len(anon_key)})"
    else:
        key_enmascarada = f"⚠️ MUY CORTA O VACÍA: '{anon_key}'"
    return {"url": url, "anon_key_enmascarada": key_enmascarada}
