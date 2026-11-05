"""Sugerencia de BORRADOR de paso a paso con la IA (Gemini). Siempre lo revisa una persona antes de guardarlo."""
import streamlit as st

from database import rutinas_logica as R


def sugerir_pasos(prompt):
    """Devuelve la lista de pasos sugeridos. Lanza una excepción con un mensaje claro si no se puede."""
    clave = st.secrets.get("GEMINI_API_KEY", "")
    if not clave:
        raise RuntimeError("Falta configurar GEMINI_API_KEY en los secrets.")
    modelo = st.secrets.get("GEMINI_MODEL", "gemini-3.5-flash")
    import google.generativeai as genai
    genai.configure(api_key=clave)
    texto = genai.GenerativeModel(modelo).generate_content(prompt).text
    pasos = R.pasos_desde_texto(texto)
    if not pasos:
        raise RuntimeError("La IA no devolvió pasos que se puedan usar. Probá de nuevo.")
    return pasos[:12]
