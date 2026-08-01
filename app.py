import streamlit as st
# Esta es la ruta corregida sin el ".connection" intermedio
from database.conection import get_maquinas, get_fallas, get_checklists, get_terceros, get_ots, get_repuestos
from views.dashboard import render_dashboard
from views.maquinas import render_maquinas
from views.fallas import render_fallas
from views.checklists import render_checklists
from views.terceros import render_terceros
from views.ots import render_ots
from views.repuestos import render_repuestos
from datetime import datetime

# Configuración de página
st.set_page_config(
    page_title="CMMS Industrial MVP",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Estética Industrial Oscura Personalizada
st.markdown("""
    <style>
        /* Estilos base fondo y contenedores */
        .stApp { background-color: #12171B; color: #E5E9EC; }
        [data-testid="stSidebar"] { background-color: #0E1216; border-right: 1px solid #22282E; }
        
        /* Contenedores tipo Panel del MVP */
        .industrial-panel {
            background-color: #1B2127;
            border: 1px solid #2A323A;
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 12px;
        }
        
        /* CORRECCIÓN: Forzar texto claro y legible en el menú de la barra lateral */
        [data-testid="stSidebar"] .stRadio div[role="radiogroup"] label {
            color: #E5E9EC !important;
            font-size: 14px !important;
            }
        
        /* Modificación de Inputs globales de Streamlit para acoplar al tema */
        .stTextInput>div>div>input, .stSelectbox>div>div>div, .stTextArea>div>div>textarea {
            background-color: #12171B !important;
            border: 1px solid #2A323A !important;
            color: #E5E9EC !important;
        }
    </style>
""", unsafe_allow_html=True)

# Inicializar Estados de Sesión en Memoria (Sincronizados con Supabase)
if "maquinas" not in st.session_state:
    st.session_state.maquinas = get_maquinas()
if "fallas" not in st.session_state:
    st.session_state.fallas = get_fallas()
if "checklists" not in st.session_state:
    st.session_state.checklists = get_checklists()
if "terceros" not in st.session_state:
    st.session_state.terceros = get_terceros()
if "ots" not in st.session_state:
    st.session_state.ots = get_ots()
if "repuestos" not in st.session_state:
    st.session_state.repuestos = get_repuestos()

# Helpers de cálculo de alertas para Badges de Navegación
def days_until(date_str):
    if not date_str: return None
    try:
        diff = datetime.strptime(date_str, "%Y-%m-%d").date() - datetime.date(datetime.now())
        return diff.days
    except:
        return None

fallas_abiertas = len([f for f in st.session_state.fallas if f.get("estado") != "Cerrada"])
venc_proximos = len([t for t in st.session_state.terceros if days_until(t.get("proximoVencimiento")) is not None and days_until(t.get("proximoVencimiento")) <= 30])

# Sidebar de Navegación Nativa
with st.sidebar:
    st.markdown("<div style='color: #38BDF8; font-family: monospace; font-size: 14px; font-weight: bold; letter-spacing: 2px;'>⚙️ MANTENIMIENTO by Javier Galeano</div>", unsafe_allow_html=True)
    st.markdown("<div style='color: #5A6570; font-family: monospace; font-size: 10px; margin-bottom: 20px;'>MVP · v0.1 (Python)</div>", unsafe_allow_html=True)
    
    # Textos corregidos y limpios para el menú
    lbl_fallas = f"🚨 Fallas / RCA ({fallas_abiertas})" if fallas_abiertas > 0 else "📋 Fallas / RCA"
    lbl_terceros = f"🚚 Terceros ({venc_proximos})" if venc_proximos > 0 else "📦 Terceros"
    
    opcion = st.radio(
        "Menú de Navegación",
        ["Panel General", "Máquinas", "🛠️ Órdenes de Trabajo", "🔩 Repuestos / Stock", lbl_fallas, "Recepción / Entrega", lbl_terceros],
        label_visibility="collapsed"
    )

# Enrutamiento de Módulos (Views)
if "Panel General" in opcion:
    render_dashboard()
elif "Máquinas" in opcion:
    render_maquinas()
elif "Órdenes de Trabajo" in opcion:
    render_ots()
elif "Repuestos" in opcion:
    render_repuestos()
elif "Fallas" in opcion:
    render_fallas()
elif "Recepción" in opcion:
    render_checklists()
elif "Terceros" in opcion:
    render_terceros()