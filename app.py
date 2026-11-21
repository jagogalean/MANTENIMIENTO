import logging
from datetime import datetime

import streamlit as st

from database.conection import (
    get_maquinas, get_fallas, get_checklists, get_terceros, get_ots, get_repuestos,
    get_tecnicos, get_planes, get_documentos, get_ot_repuestos,
    login_usuario, logout_usuario, get_usuario_by_id, get_configuracion_empresa,
    get_actividades, get_plan_ejecuciones
)
from views import ui
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
from views.solicitudes_falla import render_solicitudes_falla, get_solicitudes_falla
from views.solicitudes_compra import render_solicitudes_compra
from views.comparativo_cotizaciones import render_comparativo_cotizaciones
from views.programacion import render_programacion
from views.asistencia import render_asistencia
from views.productividad import render_productividad

# Módulos opcionales: si falta algún archivo, la app sigue funcionando y solo
# esa pantalla avisa qué falta.
try:
    from views.asistencia_consulta import render_asistencia_consulta
except ImportError as _error_consulta:
    _motivo_consulta = str(_error_consulta)

    def render_asistencia_consulta(usuario):
        st.title("Asistencia (consulta)")
        st.error("Falta el archivo views/asistencia_consulta.py en el repositorio.")
        st.code(_motivo_consulta)

try:
    from views.rutinas import render_rutinas
except ImportError as _error_rutinas:
    _motivo_rutinas = str(_error_rutinas)

    def render_rutinas(usuario):
        st.title("Rutinas del operador")
        st.error("Faltan archivos de las rutinas (views/rutinas.py y database/rutinas_*.py).")
        st.code(_motivo_rutinas)

try:
    from views.ronda_publica import render_ronda_publica
except ImportError as _error_ronda:
    _motivo_ronda = str(_error_ronda)

    def render_ronda_publica(zona_id):
        st.title("Ronda")
        st.error("Esta página todavía no está instalada. Avisale al administrador.")
        st.code(_motivo_ronda)


logging.basicConfig(level=logging.INFO)

st.set_page_config(
    page_title="Mantenimiento · Vitopel",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="expanded",
)
ui.aplicar_estilos()

# ============================================================
# PÁGINAS PÚBLICAS (QR, sin iniciar sesión) — van antes del login a propósito.
# ?equipo=X  -> ficha pública de la máquina + formulario de aviso
# ?ronda=X   -> ronda del operador (se identifica con su PIN)
# El botón "Acceso del personal" activa forzar_login_admin para ver el login.
# ============================================================
equipo_qr_id = st.query_params.get("equipo")
if equipo_qr_id and not st.session_state.get("forzar_login_admin"):
    try:
        equipo_id_normalizado = int(equipo_qr_id)
    except (TypeError, ValueError):
        equipo_id_normalizado = equipo_qr_id
    render_vista_publica(equipo_id_normalizado)
    st.stop()

ronda_qr_id = st.query_params.get("ronda")
if ronda_qr_id and not st.session_state.get("forzar_login_admin"):
    render_ronda_publica(ronda_qr_id)
    st.stop()

# ============================================================
# INICIO DE SESIÓN (Supabase Auth)
# ============================================================
if "usuario_actual" not in st.session_state:
    st.session_state.usuario_actual = None

if not st.session_state.usuario_actual:
    _, centro, _ = st.columns([1, 1.1, 1])
    with centro:
        st.write("")
        st.write("")
        st.title("Mantenimiento")
        st.caption("Vitopel · Planta Paraguay")
        with st.form("form_login"):
            email = st.text_input("Email", placeholder="nombre@vitopelparaguay.com")
            password = st.text_input("Contraseña", type="password")
            ingresar = st.form_submit_button("Ingresar", type="primary", use_container_width=True)

        if ingresar:
            if not email or not password:
                st.error("Completá el email y la contraseña.")
            else:
                try:
                    with st.spinner("Verificando..."):
                        resultado = login_usuario(email.strip(), password)
                        perfil = get_usuario_by_id(resultado.user.id)
                except Exception as e:
                    ui.error_amigable("No se pudo iniciar sesión. Revisá el email y la contraseña.", e)
                else:
                    if not perfil:
                        st.warning("Tu cuenta existe pero todavía no tiene un rol asignado. "
                                   "Pedile al coordinador que te cargue en Configuración → Usuarios.")
                    else:
                        st.session_state.usuario_actual = perfil
                        st.rerun()
    st.stop()

usuario = st.session_state.usuario_actual
rol = usuario.get("rol", "tecnico")

# ============================================================
# DATOS EN MEMORIA DE LA SESIÓN
# (se mantiene igual que antes; se optimiza en la tanda 3)
# ============================================================
_CARGAS = {
    "maquinas": get_maquinas,
    "fallas": get_fallas,
    "checklists": get_checklists,
    "terceros": get_terceros,
    "ots": get_ots,
    "repuestos": get_repuestos,
    "tecnicos": get_tecnicos,
    "planes": get_planes,
    "documentos": get_documentos,
    "ot_repuestos": get_ot_repuestos,
    "plan_actividades": get_actividades,
    "plan_ejecuciones": get_plan_ejecuciones,
}
for _clave, _funcion in _CARGAS.items():
    if _clave not in st.session_state:
        st.session_state[_clave] = _funcion()
if "config_empresa" not in st.session_state:
    st.session_state.config_empresa = get_configuracion_empresa() or {}


# ============================================================
# CONTADORES DEL MENÚ
# ============================================================
def _dias_hasta(fecha_str):
    try:
        return (datetime.strptime(fecha_str, "%Y-%m-%d").date() - datetime.now().date()).days
    except (TypeError, ValueError):
        return None


fallas_abiertas = len([f for f in st.session_state.fallas if f.get("estado") != "Cerrada"])
venc_terceros = len([t for t in st.session_state.terceros
                     if _dias_hasta(t.get("proximoVencimiento")) is not None
                     and _dias_hasta(t.get("proximoVencimiento")) <= 30])
stock_critico = len([r for r in st.session_state.repuestos
                     if (r.get("stock_actual") or 0) <= (r.get("stock_minimo") or 0)])
preventivos_proximos = len([p for p in st.session_state.planes
                            if _dias_hasta(p.get("proxima_ejecucion")) is not None
                            and _dias_hasta(p.get("proxima_ejecucion")) <= 7])
backlog_sin_asignar = len([o for o in st.session_state.ots
                           if o.get("tecnico_id") is None and o.get("estado") != "Completada"])
ots_bloqueadas = len([o for o in st.session_state.ots if o.get("estado") == "Bloqueada"])

avisos_qr_pendientes = 0
if rol == "admin":
    try:
        avisos_qr_pendientes = len([s for s in get_solicitudes_falla() if s.get("estado") == "Pendiente"])
    except Exception as e:
        logging.getLogger("cmms").warning("No se pudo contar los avisos QR: %s", e)
st.session_state.solicitudes_qr_pendientes = avisos_qr_pendientes

mis_ots_pendientes = 0
if rol == "tecnico" and usuario.get("tecnico_id"):
    mis_ots_pendientes = len([o for o in st.session_state.ots
                              if o.get("tecnico_id") == usuario.get("tecnico_id")
                              and o.get("estado") != "Completada"]) + backlog_sin_asignar


# ============================================================
# PANTALLAS
# Cada pantalla es una función sin argumentos para st.navigation.
# ============================================================
def pagina_inicio():
    ui.encabezado("Inicio", f"{datetime.now().strftime('%d/%m/%Y')} · Lo que necesita atención primero")
    render_asistente(mostrar_titulo=False)
    st.divider()
    st.subheader("Indicadores")
    render_dashboard(mostrar_titulo=False)


def pagina_agenda_tecnico():
    ui.encabezado("Agenda del día", "Pendientes de toda la planta, ordenados por urgencia.")
    render_asistente(mostrar_titulo=False)


def pagina_ots():
    ui.encabezado("Órdenes de trabajo", "Creá, actualizá y cerrá OTs. Los avisos que llegan por QR están en su propia vista.")
    opciones = ["Órdenes", ui.con_contador("Avisos QR", avisos_qr_pendientes)]
    vista = st.segmented_control("Vista", opciones, default=opciones[0], key="ots_vista",
                                 label_visibility="collapsed")
    if vista == opciones[1]:
        render_solicitudes_falla(mostrar_titulo=False)
    else:
        render_ots(usuario, mostrar_titulo=False)


def pagina_preventivo():
    ui.encabezado("Preventivo", "Qué toca hacer, cuándo, y cómo queda repartida la carga.")
    opciones = ["Planes", "Programación del año", "Calendario"]
    vista = st.segmented_control("Vista", opciones, default=opciones[0], key="prev_vista",
                                 label_visibility="collapsed")
    if vista == "Programación del año":
        render_programacion(usuario, mostrar_titulo=False)
    elif vista == "Calendario":
        render_calendario(mostrar_titulo=False)
    else:
        render_planes(mostrar_titulo=False)


def pagina_rutinas():
    render_rutinas(usuario)


def pagina_mis_ots():
    render_mis_ots(usuario)


def pagina_reportar_falla():
    render_reportar_falla(usuario)


def pagina_compras():
    render_solicitudes_compra(usuario)


def pagina_comparativo():
    render_comparativo_cotizaciones(usuario)


def pagina_presupuesto():
    render_presupuesto(usuario)


def pagina_productividad():
    render_productividad(usuario)


def pagina_asistencia():
    render_asistencia(usuario)


def pagina_asistencia_consulta():
    render_asistencia_consulta(usuario)


# Si alguien escaneó el QR de Recepción/Entrega (?maquina_id=X&vista=checklist),
# esa pantalla se abre directamente.
desde_qr_checklist = False
if "maquina_id" in st.query_params:
    st.session_state["qr_maquina_id"] = st.query_params["maquina_id"]
    desde_qr_checklist = st.query_params.get("vista") == "checklist"


def P(funcion, titulo, icono, ruta, default=False):
    return st.Page(funcion, title=titulo, icon=icono, url_path=ruta, default=default)


p_inicio = P(pagina_inicio, "Inicio", ":material/home:", "inicio", default=not desde_qr_checklist)
p_ots = P(pagina_ots, ui.con_contador("Órdenes de trabajo", backlog_sin_asignar + ots_bloqueadas + avisos_qr_pendientes),
          ":material/build:", "ordenes")
p_preventivo = P(pagina_preventivo, ui.con_contador("Preventivo", preventivos_proximos), ":material/event_repeat:", "preventivo")
p_rutinas = P(pagina_rutinas, "Rutinas del operador", ":material/fact_check:", "rutinas")
p_maquinas = P(render_maquinas, "Máquinas", ":material/precision_manufacturing:", "maquinas")
p_fallas = P(render_fallas, ui.con_contador("Fallas y RCA", fallas_abiertas), ":material/troubleshoot:", "fallas")
p_recepcion = P(render_checklists, "Recepción y entrega", ":material/swap_horiz:", "recepcion",
                default=desde_qr_checklist and rol in ("admin", "tecnico"))
p_repuestos = P(render_repuestos, ui.con_contador("Repuestos", stock_critico), ":material/inventory_2:", "repuestos")
p_compras = P(pagina_compras, "Solicitudes de compra", ":material/shopping_cart:", "compras")
p_comparativo = P(pagina_comparativo, "Comparativo de cotizaciones", ":material/balance:", "cotizaciones")
p_terceros = P(render_terceros, ui.con_contador("Terceros", venc_terceros), ":material/local_shipping:", "terceros")
p_presupuesto = P(pagina_presupuesto, "Presupuesto", ":material/account_balance_wallet:", "presupuesto")
p_reportes = P(render_reportes, "Reportes", ":material/description:", "reportes")
p_productividad = P(pagina_productividad, "Productividad", ":material/factory:", "productividad")
p_asistencia = P(pagina_asistencia, "Asistencia y horas extras", ":material/schedule:", "asistencia")
p_tecnicos = P(render_tecnicos, "Técnicos", ":material/engineering:", "tecnicos")
p_usuarios = P(render_usuarios, "Usuarios", ":material/manage_accounts:", "usuarios")

if rol == "admin":
    paginas = {
        "": [p_inicio],
        "Trabajo": [p_ots, p_preventivo, p_rutinas],
        "Activos": [p_maquinas, p_fallas, p_recepcion],
        "Almacén y compras": [p_repuestos, p_compras, p_comparativo, p_terceros],
        "Gestión": [p_presupuesto, p_reportes, p_productividad, p_asistencia],
        "Configuración": [p_tecnicos, p_usuarios],
    }
elif rol == "gerente":
    paginas = {
        "": [p_inicio],
        "Gestión": [p_presupuesto, p_reportes, p_productividad],
        "Trabajo": [p_rutinas],
    }
elif rol == "tecnico":
    paginas = [
        P(pagina_mis_ots, ui.con_contador("Mis OTs", mis_ots_pendientes), ":material/assignment_ind:", "mis-ots",
          default=not desde_qr_checklist),
        p_recepcion,
        P(pagina_agenda_tecnico, "Agenda del día", ":material/today:", "agenda"),
    ]
elif rol == "operador":
    paginas = [P(pagina_reportar_falla, "Reportar falla", ":material/campaign:", "reportar", default=True)]
elif rol == "logistica":
    paginas = [P(pagina_productividad, "Productividad", ":material/factory:", "productividad", default=True)]
elif rol == "asistencia":
    paginas = [P(pagina_asistencia, "Asistencia y horas extras", ":material/schedule:", "asistencia", default=True)]
elif rol == "consulta_asistencia":
    paginas = [P(pagina_asistencia_consulta, "Asistencia (consulta)", ":material/schedule:", "asistencia-consulta",
                 default=True)]
else:
    paginas = [P(pagina_mis_ots, "Mis OTs", ":material/assignment_ind:", "mis-ots", default=True)]

navegacion = st.navigation(paginas)

# ============================================================
# BARRA LATERAL: usuario y cierre de sesión (debajo del menú)
# ============================================================
NOMBRE_ROL = {
    "admin": "Coordinador", "gerente": "Gerencia", "tecnico": "Técnico", "operador": "Operador",
    "logistica": "Logística", "asistencia": "Asistencia", "consulta_asistencia": "Consulta de asistencia",
}
with st.sidebar:
    st.divider()
    st.markdown(f"**{usuario.get('nombre') or 'Usuario'}**")
    st.caption(f"{NOMBRE_ROL.get(rol, rol)} · Mantenimiento Vitopel")
    if st.button("Cerrar sesión", icon=":material/logout:", use_container_width=True):
        logout_usuario()
        st.session_state.clear()
        st.rerun()

navegacion.run()
