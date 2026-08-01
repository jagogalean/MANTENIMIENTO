import streamlit as st
from datetime import datetime

def render_ots():
    st.title("⚙️ Gestión de Órdenes de Trabajo (OT)")
    
    # Asegurar estados de sesión
    maquinas = st.session_state.get("maquinas", [])
    ots = st.session_state.get("ots", [])
    
    if not maquinas:
        st.warning("⚠️ Debes registrar al menos una máquina antes de crear una OT.")
        return

    # --- FORMULARIO DE CREACIÓN ---
    st.subheader("Crear Nueva Orden de Trabajo")
    with st.form("form_nueva_ot", clear_on_submit=True):
        col1, col2 = st.columns(2)
        
        with col1:
            codigo = st.text_input("Código de la OT", placeholder="Ej: OT-2026-001")
            # Mapeo de máquinas para el selectbox
            dict_maquinas = {m["nombre"]: m["id"] for m in maquinas}
            maquina_sel = st.selectbox("Seleccionar Máquina", options=list(dict_maquinas.keys()))
            tipo = st.selectbox("Tipo de Mantenimiento", options=["Preventivo", "Correctivo", "Predictivo"])
        
        with col2:
            estado = st.selectbox("Estado Inicial", options=["Pendiente", "En Ejecucion", "Completada"])
            horas_paro = st.number_input("Horas de Paro (Afectación a Disponibilidad)", min_value=0.0, step=0.5)
            descripcion = st.text_area("Descripción del Trabajo / Alcance")
            
        submit = st.form_submit_button("Registrar Orden de Trabajo")
        
        if submit:
            if not codigo or not descripcion:
                st.error("❌ El código y la descripción son obligatorios.")
            else:
                nueva_ot = {
                    "id": len(ots) + 1, # Reemplazar por la inserción real de Supabase
                    "created_at": datetime.now().isoformat(),
                    "codigo": codigo,
                    "maquina_id": dict_maquinas[maquina_sel],
                    "tipo_mantenimiento": tipo,
                    "descripcion": descripcion,
                    "estado": estado,
                    "fecha_inicio": datetime.now().isoformat(),
                    "fecha_fin": datetime.now().isoformat() if estado == "Completada" else None,
                    "horas_paro": horas_paro
                }
                
                # Simulación de inserción en el estado local (aquí usarías supabase.table().insert())
                st.session_state.ots.append(nueva_ot)
                st.success(f"✅ Orden {codigo} registrada exitosamente.")
                st.rerun()

    # --- HISTORIAL / TABLA DE OTS ---
    st.markdown("---")
    st.subheader("Historial de Órdenes de Trabajo")
    if not ots:
        st.info("No hay órdenes de trabajo registradas.")
    else:
        # Formatear datos para mostrar en una tabla limpia
        tabla_ots = []
        map_m_nombre = {m["id"]: m["nombre"] for m in maquinas}
        
        for o in ots:
            tabla_ots.append({
                "Código": o.get("codigo"),
                "Máquina": map_m_nombre.get(o.get("maquina_id"), "Desconocida"),
                "Tipo": o.get("tipo_mantenimiento"),
                "Estado": o.get("estado"),
                "Horas Paro": o.get("horas_paro"),
                "Descripción": o.get("descripcion")
            })
        st.dataframe(tabla_ots, use_container_width=True)