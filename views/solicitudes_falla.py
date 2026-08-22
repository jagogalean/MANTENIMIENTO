import streamlit as st
from datetime import datetime
from database.conection import supabase, insert_ot, get_ots

PRIORIDAD_COLOR = {"Alta": "#EF4444", "Media": "#F59E0B", "Baja": "#38BDF8"}


def get_solicitudes_falla():
    response = supabase.table("solicitudes_falla").select("*").order("fecha_reporte", desc=True).execute()
    return response.data


def update_solicitud_falla(solicitud_id, patch: dict):
    response = supabase.table("solicitudes_falla").update(patch).eq("id", solicitud_id).execute()
    return response.data


def _generar_codigo_ot(ots):
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


def render_solicitudes_falla():
    st.title("📨 Reportes desde QR (sin login)")
    st.write("Reportes enviados por cualquiera que escaneó el QR de una máquina, sin necesidad de iniciar sesión.")

    maquinas = st.session_state.get("maquinas", [])
    map_maquina = {m["id"]: m["nombre"] for m in maquinas}
    solicitudes = get_solicitudes_falla()

    pendientes = [s for s in solicitudes if s.get("estado") == "Pendiente"]
    gestionadas = [s for s in solicitudes if s.get("estado") != "Pendiente"]

    st.markdown(f"##### 🔴 {len(pendientes)} pendiente(s) de revisión")

    if not pendientes:
        st.success("✅ No hay reportes públicos pendientes de revisión.")
    else:
        for s in pendientes:
            color = PRIORIDAD_COLOR.get(s.get("prioridad"), "#38BDF8")
            m_nombre = map_maquina.get(s.get("equipo_id"), f"Equipo #{s.get('equipo_id')}")
            st.markdown(f"""
            <div class='industrial-panel' style='border-color:{color};'>
                <strong>{m_nombre}</strong> — <span style='color:{color}; font-weight:bold;'>Prioridad {s.get('prioridad')}</span><br>
                <small>{s.get('fecha_reporte', '')[:16].replace('T', ' ')} · Reportado por: {s.get('operario') or 'Anónimo'}</small><br>
                <span>{s.get('descripcion')}</span>
            </div>
            """, unsafe_allow_html=True)

            col1, col2 = st.columns(2)
            with col1:
                if st.button("✅ Convertir en Orden de Trabajo", key=f"convertir_{s.get('id')}"):
                    todas_las_ots = get_ots()
                    codigo = _generar_codigo_ot(todas_las_ots)
                    nueva_ot = {
                        "codigo": codigo,
                        "maquina_id": s.get("equipo_id"),
                        "tipo_mantenimiento": "Correctivo",
                        "descripcion": f"[Reporte QR público{' — ' + s.get('operario') if s.get('operario') else ''}] {s.get('descripcion')}",
                        "estado": "Pendiente",
                        "fecha_inicio": datetime.now().isoformat(),
                        "fecha_fin": None,
                        "horas_paro": 0,
                        "tecnico_id": None,
                        "costo_mano_obra": 0,
                        "requiere_permiso_trabajo": False,
                        "permiso_trabajo_emitido": False,
                        "origen": "qr_publico"
                    }
                    ot_creada = insert_ot(nueva_ot)
                    ot_id = ot_creada[0]["id"] if ot_creada else None
                    update_solicitud_falla(s.get("id"), {"estado": "Convertido a OT", "ot_id": ot_id})
                    st.session_state.ots = get_ots()
                    st.success(f"✅ Se creó la OT {codigo} en el backlog compartido.")
                    st.rerun()
            with col2:
                if st.button("🗑️ Descartar (no requiere acción)", key=f"descartar_{s.get('id')}"):
                    update_solicitud_falla(s.get("id"), {"estado": "Descartado"})
                    st.rerun()
            st.markdown("---")

    if gestionadas:
        with st.expander(f"📋 Ver reportes ya gestionados ({len(gestionadas)})"):
            for s in gestionadas:
                m_nombre = map_maquina.get(s.get("equipo_id"), f"Equipo #{s.get('equipo_id')}")
                st.markdown(f"- **{m_nombre}** — {s.get('descripcion')[:60]}... · Estado: `{s.get('estado')}`")
