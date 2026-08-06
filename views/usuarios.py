import streamlit as st
from database.conection import get_usuarios, insert_usuario, delete_usuario

ROLES = ["admin", "gerente", "tecnico"]


def render_usuarios():
    st.title("🔐 Usuarios del Sistema")
    st.info(
        "Paso previo: creá el usuario en Supabase → Authentication → Users → Add User "
        "(con email y contraseña). Copiá el UID que te genera y pegalo acá para asignarle un rol."
    )

    tecnicos = st.session_state.get("tecnicos", [])
    usuarios = get_usuarios()

    with st.expander("+ Vincular nuevo usuario a un rol"):
        with st.form("form_nuevo_usuario", clear_on_submit=True):
            uid = st.text_input("UID de Supabase Auth *", placeholder="Ej: 3fa85f64-5717-4562-b3fc-2c963f66afa6")
            nombre = st.text_input("Nombre para mostrar *")
            rol = st.selectbox("Rol", ROLES)
            dict_tec = {t["nombre"]: t["id"] for t in tecnicos}
            tecnico_sel = st.selectbox("Vincular a Técnico (solo si el rol es 'tecnico')", ["Ninguno"] + list(dict_tec.keys()))

            if st.form_submit_button("Guardar Usuario"):
                if not uid.strip() or not nombre.strip():
                    st.error("❌ El UID y el nombre son obligatorios.")
                elif rol == "tecnico" and tecnico_sel == "Ninguno":
                    st.error("❌ Un usuario con rol 'tecnico' debe estar vinculado a un técnico (así filtra sus OTs).")
                else:
                    try:
                        insert_usuario({
                            "id": uid.strip(),
                            "nombre": nombre,
                            "rol": rol,
                            "tecnico_id": dict_tec.get(tecnico_sel) if tecnico_sel != "Ninguno" else None
                        })
                        st.success(f"✅ Usuario '{nombre}' vinculado como {rol}.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ No se pudo guardar. ¿El UID ya existe en Supabase Auth? Detalle: {e}")

    st.markdown("---")
    st.subheader("Usuarios Actuales")

    if not usuarios:
        st.info("Todavía no hay usuarios vinculados (aparte de vos, que ya estás logueado).")
        return

    dict_tec_nombre = {t["id"]: t["nombre"] for t in tecnicos}
    for u in usuarios:
        col_i, col_a = st.columns([0.8, 0.2])
        with col_i:
            tec_txt = ""
            if u.get("rol") == "tecnico":
                tec_txt = f" · Técnico vinculado: {dict_tec_nombre.get(u.get('tecnico_id'), '⚠️ sin vincular')}"
            st.markdown(f"""
            <div class='industrial-panel'>
                <strong>{u.get('nombre')}</strong> — <small style='color:#38BDF8;'>{str(u.get('rol')).upper()}</small>{tec_txt}
            </div>
            """, unsafe_allow_html=True)
        with col_a:
            if st.button("🗑️ Quitar", key=f"del_user_{u.get('id')}"):
                delete_usuario(u.get("id"))
                st.rerun()
