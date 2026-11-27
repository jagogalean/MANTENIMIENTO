"""Usuarios: quién entra a la app y con qué rol."""
import streamlit as st

from database.conection import get_usuarios, insert_usuario, delete_usuario, update_usuario
from views import ui

# "operador" solo reporta fallas; "logistica" carga y ve Productividad; "consulta_asistencia" solo LEE
# la asistencia (sin salarios); "asistencia" tiene acceso completo a Asistencia (con salarios).
# "planificacion" carga la planilla de producción; "ventas" solo la mira.
# Un usuario puede tener VARIOS roles (por ejemplo Técnico + Logística): se guardan separados por coma en «rol».
ROLES = ["admin", "gerente", "tecnico", "operador", "logistica", "asistencia", "consulta_asistencia", "planificacion", "ventas"]
NOMBRE_ROL = {
    "admin": "Coordinador (todo)", "gerente": "Gerencia (solo mira)", "tecnico": "Técnico (sus OTs)",
    "operador": "Operador (reporta fallas)", "logistica": "Logística (productividad)",
    "asistencia": "Asistencia (completo, con salarios)", "consulta_asistencia": "Consulta de asistencia (sin salarios)",
    "planificacion": "Coordinador de producción (carga la planilla)", "ventas": "Ventas (solo mira la producción)",
}


def roles_de(u):
    return [r.strip() for r in str(u.get("rol") or "").split(",") if r.strip()]


def nombre_roles(lista):
    return " + ".join(NOMBRE_ROL.get(r, r) for r in lista) or "Sin rol"


def validar_roles(lista, tecnico_id):
    """Devuelve el texto del error, o None si está bien."""
    if not lista:
        return "Elegí al menos un rol."
    if "admin" in lista and len(lista) > 1:
        return "El Coordinador ya ve todo: no hace falta sumarle otros roles."
    if "tecnico" in lista and tecnico_id is None:
        return "Con el rol Técnico hay que elegir el técnico vinculado (así ve sus OTs)."
    return None


def _ordenar(lista):
    return [r for r in ROLES if r in lista]


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
            "3. Pegalo acá abajo y elegí el rol. **Podés elegir más de uno** (por ejemplo Técnico + Logística)."
        )
        with st.form("form_nuevo_usuario", clear_on_submit=True):
            uid = st.text_input("UID de Supabase *", placeholder="3fa85f64-5717-4562-b3fc-2c963f66afa6")
            nombre = st.text_input("Nombre para mostrar *")
            c1, c2 = st.columns(2)
            elegidos = c1.multiselect("Roles (uno o varios)", ROLES, default=["tecnico"], format_func=lambda r: NOMBRE_ROL[r],
                                      placeholder="Elegí uno o más roles")
            tecnico_id = c2.selectbox("Técnico vinculado (solo rol Técnico)", [None] + list(mapa_tec.keys()),
                                      format_func=lambda i: "Ninguno" if i is None else mapa_tec[i])
            if st.form_submit_button("Guardar usuario", type="primary"):
                elegidos = _ordenar(elegidos)
                error = validar_roles(elegidos, tecnico_id)
                if not uid.strip() or not nombre.strip():
                    st.error("El UID y el nombre son obligatorios.")
                elif error:
                    st.error(error)
                else:
                    try:
                        insert_usuario({"id": uid.strip(), "nombre": nombre.strip(), "rol": ",".join(elegidos),
                                        "tecnico_id": tecnico_id if "tecnico" in elegidos else None})
                    except Exception as e:
                        ui.error_amigable("No se pudo guardar. Revisá que el UID exista en Supabase y no esté ya cargado, "
                                          "y que se haya corrido sql/produccion.sql (habilita los roles nuevos y los roles combinados).", e)
                    else:
                        st.session_state["usr_mensaje"] = f"Usuario «{nombre.strip()}» agregado como {nombre_roles(elegidos)}."
                        st.rerun()

    if not usuarios:
        ui.estado_vacio("Todavía no hay otros usuarios cargados.")
        return

    def _orden(u):
        rs = roles_de(u)
        return (ROLES.index(rs[0]) if rs and rs[0] in ROLES else 99, str(u.get("nombre")))

    for u in sorted(usuarios, key=_orden):
        rs = roles_de(u)
        with st.container(border=True):
            c1, c3, c2 = st.columns([5, 1.3, 1.3], vertical_alignment="center")
            extra = ""
            if "tecnico" in rs:
                extra = f" · Técnico: {ui.texto_md(mapa_tec.get(u.get('tecnico_id'), 'sin vincular'))}"
            c1.markdown(f"**{ui.texto_md(u.get('nombre'))}**  \n:gray[{ui.texto_md(nombre_roles(rs))}{extra}]")
            with c3.popover("Roles", use_container_width=True):
                nuevos = st.multiselect("Roles", ROLES, default=[r for r in rs if r in ROLES], format_func=lambda r: NOMBRE_ROL[r],
                                        key=f"usr_roles_{u.get('id')}")
                opciones_tec = [None] + list(mapa_tec.keys())
                actual = u.get("tecnico_id") if u.get("tecnico_id") in mapa_tec else None
                tec = st.selectbox("Técnico vinculado", opciones_tec, index=opciones_tec.index(actual), key=f"usr_tec_{u.get('id')}",
                                   format_func=lambda i: "Ninguno" if i is None else mapa_tec[i])
                if st.button("Guardar roles", type="primary", key=f"usr_guardar_{u.get('id')}", use_container_width=True):
                    nuevos = _ordenar(nuevos)
                    error = validar_roles(nuevos, tec)
                    if u.get("id") == yo.get("id") and "admin" not in nuevos:
                        error = "No podés sacarte a vos mismo el rol de Coordinador."
                    if error:
                        st.error(error)
                    else:
                        try:
                            update_usuario(u.get("id"), {"rol": ",".join(nuevos), "tecnico_id": tec if "tecnico" in nuevos else None})
                        except Exception as e:
                            ui.error_amigable("No se pudo guardar. Revisá que se haya corrido sql/produccion.sql en Supabase.", e)
                        else:
                            st.session_state["usr_mensaje"] = f"Roles de «{u.get('nombre')}»: {nombre_roles(nuevos)}. Lo ve la próxima vez que entre."
                            st.rerun()
            with c2:
                if u.get("id") == yo.get("id"):
                    st.caption("Sos vos")
                elif ui.boton_confirmar("Quitar", f"del_user_{u.get('id')}",
                                        f"¿Quitarle el acceso a **{ui.texto_md(u.get('nombre'))}**? Su cuenta de Supabase no se borra.",
                                        texto_confirmar="Sí, quitar acceso", use_container_width=True):
                    delete_usuario(u.get("id"))
                    st.session_state["usr_mensaje"] = "Acceso quitado."
                    st.rerun()
