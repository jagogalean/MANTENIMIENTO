import streamlit as st
from database.conection import (
    get_maquinas, get_fallas, get_checklists, get_terceros, get_ots, get_repuestos,
    get_tecnicos, get_planes, get_documentos, get_ot_repuestos,
    login_usuario, logout_usuario, get_usuario_by_id, get_configuracion_empresa,
    get_actividades, get_plan_ejecuciones
)
from views.dashboard import render_dashboard
from views.maquinas import render_maquinas
from views.fallas import render_fallas
from views.checklists import render_checklists
from views.terceros import render_terceros
from views.ots import render_ots
from views.repuestos import render_repuestos
from views.tecnicos import render_tecnicos
from views.planes import render_planes
from views.reportes import render_reportes
from views.asistente import render_asistente
from views.usuarios import render_usuarios
from views.mis_ots import render_mis_ots
from views.calendario import render_calendario
from views.reportar_falla import render_reportar_falla
from views.presupuesto import render_presupuesto
from views.vista_publica import render_vista_publica
from views.solicitudes_falla import render_solicitudes_falla
from views.solicitudes_compra import render_solicitudes_compra
from views.disco_externo import render_disco_externo  # NUEVO: Sincronizador con Disco E: y Power BI
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
        .stApp { background-color: #12171B; color: #E5E9EC; }
        [data-testid="stSidebar"] { background-color: #0E1216; border-right: 1px solid #22282E; }
        .industrial-panel {
            background-color: #1B2127;
            border: 1px solid #2A323A;
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 12px;
        }
        [data-testid="stSidebar"] .stRadio div[role="radiogroup"] label {
            color: #E5E9EC !important;
            font-size: 14px !important;
        }
        .stTextInput>div>div>input, .stSelectbox>div>div>div, .stTextArea>div>div>textarea {
            background-color: #12171B !important;
            border: 1px solid #2A323A !important;
            color: #E5E9EC !important;
        }
    </style>
""", unsafe_allow_html=True)

# DESVÍO PÚBLICO (QR sin login)
equipo_qr_id = st.query_params.get("equipo")
if equipo_qr_id and not st.session_state.get("forzar_login_admin"):
    try:
        equipo_id_normalizado = int(equipo_qr_id)
    except (TypeError, ValueError):
        equipo_id_normalizado = equipo_qr_id
    render_vista_publica(equipo_id_normalizado)
    st.stop()

# LOGIN (Supabase Auth)
if "usuario_actual" not in st.session_state:
    st.session_state.usuario_actual = None

if not st.session_state.usuario_actual:
    st.markdown("<div style='color: #38BDF8; font-family: monospace; font-size: 20px; font-weight: bold; letter-spacing: 2px;'>⚙️ MANTENIMIENTO</div>", unsafe_allow_html=True)
    st.subheader("Iniciar Sesión")

    with st.form("form_login"):
        email = st.text_input("Email")
        password = st.text_input("Contraseña", type="password")
        submit = st.form_submit_button("Ingresar")

        if submit:
            try:
                resultado = login_usuario(email, password)
                user_id = resultado.user.id
                perfil = get_usuario_by_id(user_id)
                if not perfil:
                    st.error("Tu cuenta existe pero todavía no tiene un rol asignado. Pedile al administrador que te cargue en '🔐 Usuarios'.")
                else:
                    st.session_state.usuario_actual = perfil
                    st.rerun()
            except Exception as e:
                st.error(f"❌ No se pudo iniciar sesión. Verificá tu email y contraseña. Detalle: {e}")

    st.stop()

usuario = st.session_state.usuario_actual
rol = usuario.get("rol", "tecnico")

# Inicializar Estados de Sesión en Memoria
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
if "tecnicos" not in st.session_state:
    st.session_state.tecnicos = get_tecnicos()
if "planes" not in st.session_state:
    st.session_state.planes = get_planes()
if "documentos" not in st.session_state:
    st.session_state.documentos = get_documentos()
if "ot_repuestos" not in st.session_state:
    st.session_state.ot_repuestos = get_ot_repuestos()
if "config_empresa" not in st.session_state:
    st.session_state.config_empresa = get_configuracion_empresa() or {}
if "plan_actividades" not in st.session_state:
    st.session_state.plan_actividades = get_actividades()
if "plan_ejecuciones" not in st.session_state:
    st.session_state.plan_ejecuciones = get_plan_ejecuciones()

def days_until(date_str):
    if not date_str: return None
    try:
        diff = datetime.strptime(date_str, "%Y-%m-%d").date() - datetime.date(datetime.now())
        return diff.days
    except:
        return None

fallas_abiertas = len([f for f in st.session_state.fallas if f.get("estado") != "Cerrada"])
venc_proximos = len([t for t in st.session_state.terceros if days_until(t.get("proximoVencimiento")) is not None and days_until(t.get("proximoVencimiento")) <= 30])
criticos_stock = len([r for r in st.session_state.repuestos if r.get("stock_actual", 0) <= r.get("stock_minimo", 0)])

def _dias_plan(fecha_str):
    try:
        return (datetime.strptime(fecha_str, "%Y-%m-%d").date() - datetime.now().date()).days
    except (TypeError, ValueError):
        return None

planes_vencidos = len([p for p in st.session_state.planes if _dias_plan(p.get("proxima_ejecucion")) is not None and _dias_plan(p.get("proxima_ejecucion")) <= 7])

if rol == "admin":
    from views.solicitudes_falla import get_solicitudes_falla
    st.session_state.solicitudes_qr_pendientes = len([
        s for s in get_solicitudes_falla() if s.get("estado") == "Pendiente"
    ])

mis_ots_pendientes = 0
if rol == "tecnico" and usuario.get("tecnico_id"):
    mis_ots_pendientes = len([
        o for o in st.session_state.ots
        if o.get("tecnico_id") == usuario.get("tecnico_id") and o.get("estado") != "Completada"
    ])

backlog_sin_asignar = len([
    o for o in st.session_state.ots
    if o.get("tecnico_id") is None and o.get("estado") != "Completada"
])
ots_bloqueadas = len([o for o in st.session_state.ots if o.get("estado") == "Bloqueada"])

if rol == "tecnico":
    mis_ots_pendientes += backlog_sin_asignar

query_params = st.query_params
if "maquina_id" in query_params:
    st.session_state["qr_maquina_id"] = query_params["maquina_id"]
    if query_params.get("vista") == "checklist":
        st.session_state["forzar_vista"] = "Recepción / Entrega"

with st.sidebar:
    st.markdown("<div style='color: #38BDF8; font-family: monospace; font-size: 14px; font-weight: bold; letter-spacing: 2px;'>⚙️ MANTENIMIENTO by Javier Galeano</div>", unsafe_allow_html=True)
    st.markdown("<div style='color: #5A6570; font-family: monospace; font-size: 10px; margin-bottom: 4px;'>MVP · v0.3 (Hybrid + OpenOrange)</div>", unsafe_allow_html=True)
    st.markdown(f"<div style='color: #E5E9EC; font-size: 13px; margin-bottom: 16px;'>👤 {usuario.get('nombre')} · <span style='color:#38BDF8;'>{rol.upper()}</span></div>", unsafe_allow_html=True)

    if st.button("🚪 Cerrar Sesión"):
        logout_usuario()
        st.session_state.usuario_actual = None
        st.rerun()

    st.markdown("---")

    lbl_fallas = f"🚨 Fallas / RCA ({fallas_abiertas})" if fallas_abiertas > 0 else "📋 Fallas / RCA"
    lbl_terceros = f"🚚 Terceros ({venc_proximos})" if venc_proximos > 0 else "📦 Terceros"
    lbl_repuestos = f"🚨 Repuestos / Stock ({criticos_stock})" if criticos_stock > 0 else "🔩 Repuestos / Stock"
    lbl_planes = f"🚨 Plan Preventivo ({planes_vencidos})" if planes_vencidos > 0 else "🗓️ Plan Preventivo"
    lbl_mis_ots = f"🚨 Mis OTs ({mis_ots_pendientes})" if mis_ots_pendientes > 0 else "👷 Mis OTs"

    alertas_ot = backlog_sin_asignar + ots_bloqueadas
    lbl_ots = f"🚨 Órdenes de Trabajo ({alertas_ot})" if alertas_ot > 0 else "🛠️ Órdenes de Trabajo"

    solicitudes_qr_pendientes = st.session_state.get("solicitudes_qr_pendientes", 0)
    lbl_solicitudes_qr = f"🚨 Reportes QR ({solicitudes_qr_pendientes})" if solicitudes_qr_pendientes > 0 else "📨 Reportes QR"

    if rol == "admin":
        opciones_menu = [
            "🧭 Asistente del Día", "Panel General", "Máquinas", lbl_ots, lbl_repuestos,
            lbl_fallas, lbl_solicitudes_qr, "🛒 Solicitud de Compra", "Recepción / Entrega",
            lbl_terceros, lbl_planes, "📅 Calendario Preventivo", "👷 Técnicos",
            "💰 Presupuesto", "📑 Reportes", "💾 Disco Externo & Power BI", "🔐 Usuarios"
        ]
    elif rol == "gerente":
        opciones_menu = ["Panel General", "💰 Presupuesto", "📑 Reportes"]
    elif rol == "operador":
        opciones_menu = ["🚨 Reportar Falla"]
    else:
        opciones_menu = ["🧭 Asistente del Día", lbl_mis_ots, "Recepción / Entrega"]

    indice_default = 0
    forzar_vista = st.session_state.get("forzar_vista")
    if forzar_vista:
        for i, op in enumerate(opciones_menu):
            if forzar_vista in op or op in forzar_vista:
                indice_default = i
                break

    opcion = st.radio(
        "Menú de Navegación",
        opciones_menu,
        index=indice_default,
        label_visibility="collapsed"
    )

if "Asistente" in opcion:
    render_asistente()
elif "Mis OTs" in opcion:
    render_mis_ots(usuario)
elif "Reportar Falla" in opcion:
    render_reportar_falla(usuario)
elif "Presupuesto" in opcion:
    render_presupuesto(usuario)
elif "Reportes QR" in opcion:
    render_solicitudes_falla()
elif "Solicitud de Compra" in opcion:
    render_solicitudes_compra(usuario)
elif "Disco Externo" in opcion:
    render_disco_externo()
elif "Panel General" in opcion:
    render_dashboard()
elif "Máquinas" in opcion:
    render_maquinas()
elif "Órdenes de Trabajo" in opcion:
    render_ots(usuario)
elif "Repuestos" in opcion:
    render_repuestos()
elif "Fallas" in opcion:
    render_fallas()
elif "Recepción" in opcion:
    render_checklists()
elif "Terceros" in opcion:
    render_terceros()
elif "Plan Preventivo" in opcion:
    render_planes()
elif "Calendario Preventivo" in opcion:
    render_calendario()
elif "Técnicos" in opcion:
    render_tecnicos()
elif "Reportes" in opcion:
    render_reportes()
elif "Usuarios" in opcion:
    render_usuarios()
