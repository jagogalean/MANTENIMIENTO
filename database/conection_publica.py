"""
Cliente de Supabase SEPARADO del principal, exclusivo para la vista pública
(la que se ve al escanear un QR, sin necesidad de iniciar sesión).

Por qué separado: este cliente usa la clave ANON (pública) de Supabase, que
es segura de exponer porque las políticas RLS (Row Level Security) son las
que realmente limitan lo que puede hacer — no la clave en sí. Nunca se usa
acá la clave privilegiada (service_role) que usa el resto de la app.

Requiere un secret nuevo en Streamlit Cloud (Settings -> Secrets):
    SUPABASE_ANON_KEY = "..."
Lo sacás de Supabase -> tu proyecto -> Settings -> API -> "anon / public".
(Es distinto del SUPABASE_KEY que ya tenés configurado para el resto de la app.)
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


supabase_publico: Client = init_supabase_publico()


def get_ficha_publica_equipo(equipo_id):
    """
    Trae la ficha pública de un equipo desde la vista 'equipos_publico'
    (nombre, ubicación, último y próximo preventivo). Esta vista NO expone
    costo_hora_parada ni criticidad — esos son datos internos de gestión.
    Devuelve None si el equipo no existe.
    """
    response = supabase_publico.table("equipos_publico").select("*").eq("id", equipo_id).execute()
    return response.data[0] if response.data else None


def insertar_solicitud_falla(data: dict):
    """
    Inserta un reporte público de avería (sin login). Siempre queda en
    estado 'Pendiente' — la política RLS de Supabase también lo obliga,
    esto es una segunda capa de seguridad del lado de la app.
    """
    data["estado"] = "Pendiente"
    response = supabase_publico.table("solicitudes_falla").insert(data).execute()
    return response.data
