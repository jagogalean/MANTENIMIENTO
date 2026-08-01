import streamlit as st

def render_repuestos():
    st.title("📦 Inventario de Repuestos")
    
    repuestos = st.session_state.get("repuestos", [])
    
    # --- FORMULARIO DE CREACIÓN ---
    st.subheader("Añadir Nuevo Repuesto al Stock")
    with st.form("form_nuevo_repuesto", clear_on_submit=True):
        col1, col2 = st.columns(2)
        
        with col1:
            nombre = st.text_input("Nombre del Repuesto", placeholder="Ej: Rodamiento SKF 6204")
            codigo_interno = st.text_input("Código Interno", placeholder="Ej: REP-ROD-001")
            
        with col2:
            stock_actual = st.number_input("Stock Inicial", min_value=0, step=1, value=0)
            costo_unitario = st.number_input("Costo Unitario ($)", min_value=0.0, step=0.01, value=0.0)
            
        submit = st.form_submit_button("Guardar en Inventario")
        
        if submit:
            if not nombre or not codigo_interno:
                st.error("❌ El nombre y el código interno son requeridos.")
            elif any(r.get("codigo_interno") == codigo_interno for r in repuestos):
                st.error("❌ Ese código interno ya existe en el inventario.")
            else:
                nuevo_repuesto = {
                    "id": len(repuestos) + 1, # Reemplazar por la inserción real de Supabase
                    "nombre": nombre,
                    "codigo_interno": codigo_interno,
                    "stock_actual": int(stock_actual),
                    "costo_unitario": float(costo_unitario)
                }
                
                st.session_state.repuestos.append(nuevo_repuesto)
                st.success(f"✅ Repuesto '{nombre}' añadido correctamente.")
                st.rerun()

    # --- TABLA DE STOCK ---
    st.markdown("---")
    st.subheader("Materiales en Almacén")
    if not repuestos:
        st.info("El inventario está vacío actualmente.")
    else:
        st.dataframe(repuestos, use_container_width=True, hide_index=True)