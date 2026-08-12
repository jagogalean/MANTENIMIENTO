import streamlit as st
from datetime import datetime
from database.conection import insert_ot, get_ots, get_maquinas_cached


def generar_codigo_ot(ots):
    """Genera el siguiente código consecutivo del año en curso. Ej: OT-2026-0007"""
    year = datetime.now().year
    prefijo = f"OT-{year}-"
    consecutivos = []
    for o in ots:
        cod = o.get("codigo", "") or ""
        if cod.startswith(prefijo):
            try:
                consecutivos.append(int(cod.replace(prefijo, "")))
            except ValueError:
                pass
    siguiente = max(consecutivos) + 1 if consecutivos else 1
    return f"{prefijo}{siguiente:04d}"


def render_reportar_falla(usuario):
    st.title("🚨 Reportar Falla")
    st.write("Contanos qué está pasando con la máquina. Tu reporte va directo al backlog compartido de mantenimiento, para que cualquier técnico lo pueda tomar.")

    maquinas = get_maquinas_cached()
    if not maquinas:
        st.warning("Todavía no hay máquinas registradas en el sistema. Avisale a tu coordinador.")
        return

    with st.form("form_reporte_operador", clear_on_submit=True):
        dict_m = {m["nombre"]: m["id"] for m in maquinas}
        maquina_sel = st.selectbox("Máquina *", options=list(dict_m.keys()))
        descripcion = st.text_area(
            "¿Qué está pasando? *",
            placeholder="Describí lo que observás: ruido raro, olor a quemado, la máquina se detuvo, vibración, etc."
        )
        maquina_parada = st.checkbox("La máquina está parada ahora mismo")

        submit = st.form_submit_button("📨 Enviar Reporte")
        if submit:
            if not descripcion.strip():
                st.error("❌ Describí la falla antes de enviar.")
            else:
                todas_las_ots = get_ots()
                nueva_ot = {
                    "codigo": generar_codigo_ot(todas_las_ots),
                    "maquina_id": dict_m[maquina_sel],
                    "tipo_mantenimiento": "Correctivo",
                    "descripcion": f"[Reporte de operador: {usuario.get('nombre', 'Sin nombre')}] {descripcion}",
                    "estado": "Pendiente",
                    "fecha_inicio": datetime.now().isoformat(),
                    "fecha_fin": None,
                    "horas_paro": 0,
                    "tecnico_id": None,
                    "costo_mano_obra": 0,
                    "requiere_permiso_trabajo": False,
                    "permiso_trabajo_emitido": False,
                    "origen": "operador"
                }
                insert_ot(nueva_ot)
                st.success("✅ Reporte enviado correctamente. El equipo de mantenimiento lo va a ver en su backlog compartido.")
                if maquina_parada:
                    st.info("📌 Marcaste la máquina como parada — si es urgente, avisá también verbalmente a tu supervisor.")

    st.markdown("---")
    st.caption("💡 Este reporte crea automáticamente una Orden de Trabajo Correctiva sin asignar, visible para todos los técnicos en 'Mis OTs → Backlog Compartido'.")