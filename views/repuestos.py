import streamlit as st
from database.conection import insert_repuesto, get_repuestos


def render_repuestos():
    st.title("📦 Inventario de Repuestos")

    repuestos = st.session_state.get("repuestos", [])

    # --- REPUESTOS CRÍTICOS (stock en o por debajo del mínimo) ---
    criticos = [r for r in repuestos if r.get("stock_actual", 0) <= r.get("stock_minimo", 0)]
    if criticos:
        st.markdown("##### 🚨 Repuestos en nivel crítico de stock")
        for r in criticos:
            st.markdown(f"""
            <div class='industrial-panel' style='border-color:#EF4444;'>
                <strong>{r.get('nombre')}</strong> <small style='color:#7C8894;'>[{r.get('codigo_interno')}]</small><br>
                <span style='color:#EF4444; font-weight:bold;'>Stock actual: {r.get('stock_actual')} / Mínimo: {r.get('stock_minimo')}</span>
            </div>
            """, unsafe_allow_html=True)
        st.markdown("---")

    # --- FORMULARIO DE CREACIÓN ---
    st.subheader("Añadir Nuevo Repuesto al Stock")
    with st.form("form_nuevo_repuesto", clear_on_submit=True):
        col1, col2 = st.columns(2)

        with col1:
            nombre = st.text_input("Nombre del Repuesto", placeholder="Ej: Rodamiento SKF 6204")
            codigo_interno = st.text_input("Código Interno", placeholder="Ej: REP-ROD-001")

        with col2:
            stock_actual = st.number_input("Stock Inicial", min_value=0, step=1, value=0)
            costo_unitario = st.number_input("Costo Unitario (Gs.)", min_value=0, step=100, value=0)

        stock_minimo = st.number_input("Stock Mínimo (dispara alerta de crítico)", min_value=0, step=1, value=0)

        submit = st.form_submit_button("Guardar en Inventario")

        if submit:
            if not nombre or not codigo_interno:
                st.error("❌ El nombre y el código interno son requeridos.")
            elif any(r.get("codigo_interno") == codigo_interno for r in repuestos):
                st.error("❌ Ese código interno ya existe en el inventario.")
            else:
                nuevo_repuesto = {
                    "nombre": nombre,
                    "codigo_interno": codigo_interno,
                    "stock_actual": int(stock_actual),
                    "stock_minimo": int(stock_minimo),
                    "costo_unitario": int(costo_unitario)
                }
                insert_repuesto(nuevo_repuesto)
                st.session_state.repuestos = get_repuestos()
                st.success(f"✅ Repuesto '{nombre}' añadido correctamente.")
                st.rerun()

    # --- TABLA DE STOCK ---
    st.markdown("---")
    st.subheader("Materiales en Almacén")
    if not repuestos:
        st.info("El inventario está vacío actualmente.")
    else:
        st.dataframe(repuestos, use_container_width=True, hide_index=True)
