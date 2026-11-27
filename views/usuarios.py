"""Usuarios: quién entra a la app y con qué rol."""
import streamlit as st

from database.conection import get_usuarios, insert_usuario, delete_usuario
from views import ui

# "operador" solo reporta fallas; "logistica" carga y ve Productividad; "consulta_asistencia" solo LEE
# la asistencia (sin salarios); "asistencia" tiene acceso completo a Asistencia (con salarios).
# "planificacion" carga la planilla de producción; "ventas" solo la mira.
ROLES = ["admin", "gerente", "tecnico", "operador", "logistica", "asistencia", "consulta_asistencia", "planificacion", "ventas"]
NOMBRE_ROL = {
    "admin": "Coordinador (todo)", "gerente": "Gerencia (solo mira)", "tecnico": "Técnico (sus OTs)",
    "operador": "Operador (reporta fallas)", "logistica": "Logística (productividad)",
    "asistencia": "Asistencia (completo, con salarios)", "consulta_asistencia": "Consulta de asistencia (sin salarios)",
    "planificacion": "Supervisor de producción (carga la planilla)", "ventas": "Ventas (solo mira la producción)",
}


def render_usuarios():
    yo = st.session_state.get("usuario_actual") or {}
    ui.encabezado("Usuarios", "Quién puede entrar a la app y qué ve cada uno.")
    tecnicos = st.session_state.get("tecnicos", [])
    mapa_tec = {t["id"]: t["nombre"] for t in tecnicos}

    mensaje = st.session_state.pop("usr_mensaje", None)
    if mensaje:
        st.success(mensaje)

    try:
        usuarios = get_usuarios()
    except Exception as e:
        ui.error_amigable("No se pudo leer la lista de usuarios.", e)
        return

    with st.expander("Agregar un usuario"):
        st.markdown(
            "1. En Supabase: **Authentication → Users → Add user**, con su email y una contraseña.\n"
            "2. Copiá el **UID** que aparece en la lista de usuarios de Supabase.\n"
            "3. Pegalo acá abajo y elegí el rol."
        )
        with st.form("form_nuevo_usuario", clear_on_submit=True):
            uid = st.text_input("UID de Supabase *", placeholder="3fa85f64-5717-4562-b3fc-2c963f66afa6")
            nombre = st.text_input("Nombre para mostrar *")
            c1, c2 = st.columns(2)
            rol = c1.selectbox("Rol", ROLES, index=2, format_func=lambda r: NOMBRE_ROL[r])
            tecnico_id = c2.selectbox("Técnico vinculado (solo rol Técnico)", [None] + list(mapa_tec.keys()),
                                      format_func=lambda i: "Ninguno" if i is None else mapa_tec[i])
            if st.form_submit_button("Guardar usuario", type="primary"):
                if not uid.strip() or not nombre.strip():
                    st.error("El UID y el nombre son obligatorios.")
                elif rol == "tecnico" and tecnico_id is None:
                    st.error("Un usuario Técnico tiene que estar vinculado a un técnico (así ve sus OTs).")
                else:
                    try:
                        insert_usuario({"id": uid.strip(), "nombre": nombre.strip(), "rol": rol,
                                        "tecnico_id": tecnico_id if rol == "tecnico" else None})
                    except Exception as e:
                        ui.error_amigable("No se pudo guardar. Revisá que el UID exista en Supabase y no esté ya cargado.", e)
                    else:
                        st.session_state["usr_mensaje"] = f"Usuario «{nombre.strip()}» agregado como {NOMBRE_ROL[rol]}."
                        st.rerun()

    if not usuarios:
        ui.estado_vacio("Todavía no hay otros usuarios cargados.")
        return

    for u in sorted(usuarios, key=lambda u: (ROLES.index(u.get("rol")) if u.get("rol") in ROLES else 99, str(u.get("nombre")))):
        with st.container(border=True):
            c1, c2 = st.columns([5, 1.3], vertical_alignment="center")
            extra = ""
            if u.get("rol") == "tecnico":
                extra = f" · Técnico: {ui.texto_md(mapa_tec.get(u.get('tecnico_id'), 'sin vincular'))}"
            c1.markdown(f"**{ui.texto_md(u.get('nombre'))}**  \n:gray[{NOMBRE_ROL.get(u.get('rol'), u.get('rol'))}{extra}]")
            with c2:
                if u.get("id") == yo.get("id"):
                    st.caption("Sos vos")
                elif ui.boton_confirmar("Quitar", f"del_user_{u.get('id')}",
                                        f"¿Quitarle el acceso a **{ui.texto_md(u.get('nombre'))}**? Su cuenta de Supabase no se borra.",
                                        texto_confirmar="Sí, quitar acceso", use_container_width=True):
                    delete_usuario(u.get("id"))
                    st.session_state["usr_mensaje"] = "Acceso quitado."
                    st.rerun()
