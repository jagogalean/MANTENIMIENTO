"""Planilla de producción publicada para Ventas (tabla produccion_planillas; ver sql/produccion.sql)."""
import streamlit as st

from database.conection import supabase

TABLA = "produccion_planillas"


def publicar(datos, archivo, usuario):
    """Guarda una nueva versión de la planilla. Ventas siempre ve la última."""
    fila = {"archivo": archivo, "cargado_por": usuario,
            "pedidos": datos["pedidos"], "desarrollos": datos["desarrollos"],
            "resumen": {"pedidos": len(datos["pedidos"]["filas"]), "desarrollos": len(datos["desarrollos"]["filas"]),
                        "avisos": datos.get("avisos", [])}}
    supabase.table(TABLA).insert(fila).execute()
    ultima.clear()
    historial.clear()


@st.cache_data(ttl=60, show_spinner=False)
def ultima():
    r = supabase.table(TABLA).select("*").order("id", desc=True).limit(1).execute()
    return (r.data or [None])[0]


@st.cache_data(ttl=60, show_spinner=False)
def historial(cantidad=15):
    r = (supabase.table(TABLA).select("id, creado_en, archivo, cargado_por, resumen")
         .order("id", desc=True).limit(cantidad).execute())
    return sorted(r.data or [], key=lambda x: x.get("id") or 0, reverse=True)
