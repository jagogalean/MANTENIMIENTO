import streamlit as st
import pandas as pd
import io
from database.conection import insert_repuesto, update_repuesto, get_repuestos, get_repuestos_cached

COLUMNAS_PLANTILLA = ["nombre", "codigo_interno", "codigo_openorange", "stock_actual", "stock_minimo", "costo_unitario"]


def _generar_plantilla_excel():
    """Arma el archivo de plantilla en memoria (mismo formato que pide el alta manual)."""
    df_ejemplo = pd.DataFrame([
        {"nombre": "Rodamiento SKF 6204", "codigo_interno": "REP-ROD-001", "codigo_openorange": "97039804", "stock_actual": 10, "stock_minimo": 2, "costo_unitario": 85000},
        {"nombre": "Correa Poly-V 6PJ850", "codigo_interno": "REP-COR-002", "codigo_openorange": "97069990", "stock_actual": 4, "stock_minimo": 1, "costo_unitario": 210000},
    ], columns=COLUMNAS_PLANTILLA)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df_ejemplo.to_excel(writer, index=False, sheet_name="Repuestos")
    return buffer.getvalue()


def render_repuestos():
    st.title("📦 Inventario de Repuestos (Integrado con OpenOrange)")

    repuestos = st.session_state.get("repuestos", [])

    # --- REPUESTOS CRÍTICOS (stock en o por debajo del mínimo) ---
    criticos = [r for r in repuestos if r.get("stock_actual", 0) <= r.get("stock_minimo", 0)]
    if criticos:
        st.markdown("##### 🚨 Repuestos en nivel crítico de stock")
        for r in criticos:
            oo_txt = f" · <small style='color:#38BDF8;'>OpenOrange: {r.get('codigo_openorange')}</small>" if r.get("codigo_openorange") else ""
            st.markdown(f"""
            <div class='industrial-panel' style='border-color:#EF4444;'>
                <strong>{r.get('nombre')}</strong> <small style='color:#7C8894;'>[{r.get('codigo_interno')}]</small>{oo_txt}<br>
                <span style='color:#EF4444; font-weight:bold;'>Stock actual: {r.get('stock_actual')} / Mínimo: {r.get('stock_minimo')}</span>
            </div>
            """, unsafe_allow_html=True)
        st.markdown("---")

    # --- CARGA MASIVA DESDE EXCEL (para el inventario inicial) ---
    with st.expander("📤 Cargar varios repuestos de una vez desde Excel"):
        st.caption("Ideal para cargar el inventario completo de una sola vez. Usá la plantilla para no tener que acomodar columnas después.")

        st.download_button(
            "⬇️ Descargar plantilla de Excel",
            data=_generar_plantilla_excel(),
            file_name="plantilla_repuestos.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

        archivo_excel = st.file_uploader("Subir planilla completa (.xlsx)", type=["xlsx"], key="uploader_repuestos_excel")

        if archivo_excel:
            try:
                df = pd.read_excel(archivo_excel, engine="openpyxl")
                df.columns = [str(c).strip().lower() for c in df.columns]
            except Exception as e:
                st.error(f"❌ No se pudo leer el archivo. ¿Es un .xlsx válido? Detalle: {e}")
                df = None

            if df is not None:
                # Si el usuario sube una planilla vieja sin 'codigo_openorange', la creamos vacía para no fallar
                if "codigo_openorange" not in df.columns:
                    df["codigo_openorange"] = ""

                columnas_requeridas = ["nombre", "codigo_interno", "stock_actual", "stock_minimo", "costo_unitario"]
                columnas_faltantes = [c for c in columnas_requeridas if c not in df.columns]
                if columnas_faltantes:
                    st.error(f"❌ Al archivo le faltan estas columnas: {', '.join(columnas_faltantes)}. Usá la plantilla de arriba como base.")
                else:
                    df = df[COLUMNAS_PLANTILLA].copy()
                    df["nombre"] = df["nombre"].astype(str).str.strip()
                    df["codigo_interno"] = df["codigo_interno"].astype(str).str.strip()
                    df["codigo_openorange"] = df["codigo_openorange"].fillna("").astype(str).str.strip()

                    # Validaciones antes de mostrar la vista previa
                    errores = []
                    codigos_existentes = {r.get("codigo_interno") for r in repuestos}
                    df_vacios = df[(df["nombre"] == "") | (df["nombre"] == "nan") | (df["codigo_interno"] == "") | (df["codigo_interno"] == "nan")]
                    if not df_vacios.empty:
                        errores.append(f"{len(df_vacios)} fila(s) sin nombre o código interno (se van a omitir).")

                    df = df[(df["nombre"] != "") & (df["nombre"] != "nan") & (df["codigo_interno"] != "") & (df["codigo_interno"] != "nan")]

                    duplicados_en_archivo = df[df.duplicated(subset=["codigo_interno"], keep=False)]
                    if not duplicados_en_archivo.empty:
                        errores.append(f"{duplicados_en_archivo['codigo_interno'].nunique()} código(s) interno(s) repetidos dentro del mismo archivo.")

                    ya_existen = df[df["codigo_interno"].isin(codigos_existentes)]
                    if not ya_existen.empty:
                        errores.append(f"{len(ya_existen)} código(s) interno(s) ya existen en tu inventario actual (se van a omitir para no duplicar).")

                    df_para_cargar = df[~df["codigo_interno"].isin(codigos_existentes)].drop_duplicates(subset=["codigo_interno"], keep="first")

                    for msg in errores:
                        st.warning(f"⚠️ {msg}")

                    st.write(f"**Vista previa — se van a cargar {len(df_para_cargar)} repuesto(s):**")
                    st.dataframe(df_para_cargar, use_container_width=True, hide_index=True)

                    if len(df_para_cargar) > 0:
                        if st.button(f"✅ Confirmar carga de {len(df_para_cargar)} repuesto(s)"):
                            cargados, fallidos = 0, 0
                            for _, fila in df_para_cargar.iterrows():
                                try:
                                    cod_oo = fila["codigo_openorange"]
                                    if cod_oo in ("", "nan", "None"):
                                        cod_oo = None
                                    insert_repuesto({
                                        "nombre": fila["nombre"],
                                        "codigo_interno": fila["codigo_interno"],
                                        "codigo_openorange": cod_oo,
                                        "stock_actual": int(fila["stock_actual"]) if pd.notna(fila["stock_actual"]) else 0,
                                        "stock_minimo": int(fila["stock_minimo"]) if pd.notna(fila["stock_minimo"]) else 0,
                                        "costo_unitario": int(fila["costo_unitario"]) if pd.notna(fila["costo_unitario"]) else 0
                                    })
                                    cargados += 1
                                except Exception:
                                    fallidos += 1
                            get_repuestos_cached.clear()
                            st.session_state.repuestos = get_repuestos()
                            if fallidos:
                                st.warning(f"✅ Se cargaron {cargados} repuesto(s). {fallidos} no se pudieron guardar.")
                            else:
                                st.success(f"✅ Se cargaron {cargados} repuesto(s) correctamente.")
                            st.rerun()

    st.markdown("---")

    # --- FORMULARIO DE CREACIÓN ---
    st.subheader("Añadir Nuevo Repuesto al Stock")
    with st.form("form_nuevo_repuesto", clear_on_submit=True):
        col1, col2 = st.columns(2)

        with col1:
            nombre = st.text_input("Nombre del Repuesto *", placeholder="Ej: Insulating wool-felt sleeve / Rodamiento SKF 6204")
            codigo_interno = st.text_input("Código Interno *", placeholder="Ej: REP-ROD-001")
            codigo_openorange = st.text_input("Artículo Nro en OpenOrange (opcional)", placeholder="Ej: 97039804")

        with col2:
            stock_actual = st.number_input("Stock Inicial", min_value=0, step=1, value=0)
            stock_minimo = st.number_input("Stock Mínimo (dispara alerta de crítico)", min_value=0, step=1, value=0)
            costo_unitario = st.number_input("Costo Unitario (Gs.)", min_value=0, step=100, value=0)

        submit = st.form_submit_button("Guardar en Inventario")

        if submit:
            if not nombre or not codigo_interno:
                st.error("❌ El nombre y el código interno son requeridos.")
            elif any(r.get("codigo_interno") == codigo_interno for r in repuestos):
                st.error("❌ Ese código interno ya existe en el inventario.")
            else:
                nuevo_repuesto = {
                    "nombre": nombre.strip(),
                    "codigo_interno": codigo_interno.strip(),
                    "codigo_openorange": codigo_openorange.strip() or None,
                    "stock_actual": int(stock_actual),
                    "stock_minimo": int(stock_minimo),
                    "costo_unitario": int(costo_unitario)
                }
                insert_repuesto(nuevo_repuesto)
                get_repuestos_cached.clear()
                st.session_state.repuestos = get_repuestos()
                st.success(f"✅ Repuesto '{nombre}' añadido correctamente.")
                st.rerun()

    # --- AJUSTE RÁPIDO DE STOCK / OPENORANGE ---
    if repuestos:
        with st.expander("✏️ Ajustar Stock, Costo o Código OpenOrange de un Repuesto existente"):
            dict_rep = {f"{r.get('nombre')} [{r.get('codigo_interno')}] — Stock: {r.get('stock_actual', 0)}": r for r in repuestos}
            rep_sel_lbl = st.selectbox("Seleccionar repuesto a editar", list(dict_rep.keys()))
            r_edit = dict_rep[rep_sel_lbl]

            c_e1, c_e2, c_e3, c_e4 = st.columns(4)
            nuevo_stk = c_e1.number_input("Stock Actual", min_value=0, step=1, value=int(r_edit.get("stock_actual", 0) or 0), key=f"stk_{r_edit['id']}")
            nuevo_min = c_e2.number_input("Stock Mínimo", min_value=0, step=1, value=int(r_edit.get("stock_minimo", 0) or 0), key=f"min_{r_edit['id']}")
            nuevo_costo = c_e3.number_input("Costo Unitario (Gs.)", min_value=0, step=1000, value=int(r_edit.get("costo_unitario", 0) or 0), key=f"cst_{r_edit['id']}")
            nuevo_oo = c_e4.text_input("Artículo Nro OpenOrange", value=r_edit.get("codigo_openorange") or "", key=f"oo_{r_edit['id']}")

            if st.button("💾 Guardar ajuste de repuesto", key=f"btn_save_rep_{r_edit['id']}"):
                update_repuesto(r_edit["id"], {
                    "stock_actual": int(nuevo_stk),
                    "stock_minimo": int(nuevo_min),
                    "costo_unitario": int(nuevo_costo),
                    "codigo_openorange": nuevo_oo.strip() or None
                })
                get_repuestos_cached.clear()
                st.session_state.repuestos = get_repuestos()
                st.success(f"✅ '{r_edit.get('nombre')}' actualizado correctamente.")
                st.rerun()

    # --- TABLA DE STOCK ---
    st.markdown("---")
    st.subheader("Materiales en Almacén")
    if not repuestos:
        st.info("El inventario está vacío actualmente.")
    else:
        st.dataframe(repuestos, use_container_width=True, hide_index=True)
