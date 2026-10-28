import hashlib

import pandas as pd
import streamlit as st

from database import inventario_excel as inv
from database.conection import insert_repuesto, get_repuestos

try:  # la caché corta de repuestos existe en las versiones nuevas de conection.py
    from database.conection import get_repuestos_cached
except ImportError:  # pragma: no cover
    get_repuestos_cached = None

NINGUNA = "— no usar —"


def _refrescar_repuestos():
    if get_repuestos_cached is not None:
        get_repuestos_cached.clear()
    st.session_state.repuestos = get_repuestos()


def _vista_texto(df):
    """Para mostrar una planilla cruda sin que Streamlit se queje de tipos mezclados."""
    return df.map(lambda v: "" if v is None else str(v))


# ----------------------------------------------------------------
# Importador de inventario desde Excel
# ----------------------------------------------------------------
def _render_resultado_anterior():
    """Muestra el resultado de la última carga (queda visible después de recargar la pantalla)."""
    res = st.session_state.pop("inv_resultado", None)
    if not res:
        return
    if res["fallidas"]:
        st.warning(f"✅ Se cargaron {res['cargados']} repuesto(s). ⚠️ {len(res['fallidas'])} no se pudieron guardar.")
        st.dataframe(pd.DataFrame(res["fallidas"]).rename(columns={"fila": "Fila en tu Excel", "nombre": "Nombre", "motivo": "Motivo"}),
                     hide_index=True, width="stretch")
        st.download_button("⬇️ Descargar las que fallaron", data=inv.reporte_filas_con_problemas(res["fallidas"]),
                           file_name="repuestos_no_cargados.xlsx", key="dl_fallidas",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        st.success(f"✅ Se cargaron {res['cargados']} repuesto(s) correctamente"
                   + (f" ({res['automaticos']} con código generado automáticamente)." if res["automaticos"] else "."))
    if res.get("omitidas"):
        st.info(f"Además, {res['omitidas']} fila(s) de tu Excel no se cargaron por problemas en los datos "
                "(las viste en la vista previa).")


def _render_importador(repuestos):
    st.session_state.setdefault("inv_n", 0)
    with st.expander("📤 Cargar mi inventario desde Excel", expanded=False):
        st.caption(
            "Subí tu planilla tal como la tenés: no hace falta renombrar columnas ni tener códigos. "
            "Vas a elegir qué columna es cada dato, ver una vista previa y recién ahí confirmar."
        )
        st.download_button(
            "⬇️ Descargar plantilla de ejemplo (opcional)", data=inv.generar_plantilla_excel(),
            file_name="plantilla_repuestos.xlsx", key="dl_plantilla_inv",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        archivo = st.file_uploader("Tu planilla de inventario (.xlsx)", type=["xlsx"],
                                   key=f"inv_archivo_{st.session_state['inv_n']}",
                                   help="Si tu archivo es un .xls antiguo, abrilo en Excel y guardalo como .xlsx.")
        if not archivo:
            return

        contenido = archivo.getvalue()
        try:
            hojas = inv.listar_hojas(contenido)
        except Exception as e:
            st.error(f"❌ No se pudo abrir el archivo. ¿Es un .xlsx válido? Detalle: {e}")
            return

        c1, c2 = st.columns([0.65, 0.35])
        hoja = c1.selectbox("Hoja del Excel", hojas, key="inv_hoja")
        fila_titulos = int(c2.number_input("Fila donde están los títulos", min_value=1, value=1, step=1, key="inv_fila",
                                           help="1 = la primera fila. Subila si tu planilla tiene un título o filas vacías arriba."))
        try:
            df = inv.leer_excel(contenido, hoja, fila_titulos)
        except Exception as e:
            st.error(f"❌ No se pudo leer esa hoja con esos datos. Probá con otra fila de títulos. Detalle: {e}")
            return
        if df.empty:
            st.warning("No hay datos debajo de esa fila de títulos. Revisá la hoja y la fila elegidas.")
            return

        st.markdown(f"**Vista de tu hoja** — {len(df)} fila(s) con datos. Los títulos que leí están en la primera línea:")
        st.dataframe(_vista_texto(df.head(6)), hide_index=True, width="stretch")

        # ---- Qué columna es cada dato (con sugerencia automática) ----
        firma = hashlib.md5(f"{archivo.name}|{len(contenido)}|{hoja}|{fila_titulos}".encode()).hexdigest()[:8]
        columnas = list(df.columns)
        opciones = [NINGUNA] + columnas
        sugerido = inv.sugerir_mapeo(columnas)
        st.markdown("**¿Qué columna es cada dato?** Ya intenté adivinarlo por los títulos; corregilo si hace falta.")
        mapeo = {}
        celdas = st.columns(3)
        for i, (campo, etiqueta) in enumerate(inv.CAMPOS):
            sug = sugerido.get(campo)
            elegido = celdas[i % 3].selectbox(
                etiqueta, opciones, index=opciones.index(sug) if sug in opciones else 0, key=f"inv_map_{campo}_{firma}")
            mapeo[campo] = None if elegido == NINGUNA else elegido
        st.caption("Para guardar la **ubicación** hace falta haber corrido el SQL de esta actualización en Supabase.")

        usadas = [c for c in mapeo.values() if c]
        if len(usadas) != len(set(usadas)):
            st.warning("⚠️ Elegiste la misma columna para dos datos distintos. Revisá la selección.")
        if not mapeo["nombre"]:
            st.error("Elegí la columna del **nombre** del repuesto para poder continuar.")
            return

        prefijo = st.text_input("Prefijo para los códigos automáticos", value="REP-", key="inv_prefijo",
                                help="Se usa solo para los repuestos que no traen código: REP-0001, REP-0002...")

        # ---- Control de calidad y vista previa ----
        resultado = inv.procesar_inventario(df, mapeo, [r.get("codigo_interno") for r in repuestos],
                                            prefijo=prefijo or "REP-", fila_encabezado=fila_titulos,
                                            nombres_existentes=[r.get("nombre") for r in repuestos])
        filas, omitidas, avisos = resultado["filas"], resultado["omitidas"], resultado["avisos"]
        automaticos = sum(1 for f in filas if f["codigo_auto"])

        st.markdown("---")
        m1, m2, m3 = st.columns(3)
        m1.metric("Se van a cargar", len(filas))
        m2.metric("No se cargan", len(omitidas))
        m3.metric("Códigos automáticos", automaticos)
        for aviso in avisos:
            st.warning(f"⚠️ {aviso}")

        if omitidas:
            with st.expander(f"Ver las {len(omitidas)} fila(s) que NO se van a cargar y por qué"):
                st.dataframe(pd.DataFrame(omitidas).rename(columns={"fila": "Fila en tu Excel", "nombre": "Nombre", "motivo": "Motivo"}),
                             hide_index=True, width="stretch")
                st.download_button("⬇️ Descargar esta lista (para corregirla en tu Excel)",
                                   data=inv.reporte_filas_con_problemas(omitidas), file_name="filas_con_problemas.xlsx",
                                   key="dl_omitidas", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        if not filas:
            st.info("No hay repuestos válidos para cargar con esta selección.")
            return

        st.markdown(f"**Vista previa — así se van a guardar los {len(filas)} repuesto(s):**")
        st.dataframe(pd.DataFrame([{
            "Fila Excel": f["fila_excel"], "Nombre": f["nombre"],
            "Código": f["codigo_interno"] + (" (auto)" if f["codigo_auto"] else ""),
            "Ubicación": f["ubicacion"] or "", "Stock": f["stock_actual"], "Mínimo": f["stock_minimo"],
            "Costo (Gs.)": f["costo_unitario"],
        } for f in filas]), hide_index=True, width="stretch")

        if st.button(f"✅ Confirmar: cargar {len(filas)} repuesto(s)", type="primary", key="inv_confirmar"):
            with st.spinner("Cargando el inventario..."):
                try:
                    cargados, fallidas = inv.insertar_repuestos_lote(filas, incluir_ubicacion=bool(mapeo["ubicacion"]))
                except RuntimeError as e:
                    st.error(f"❌ {e}")
                    return
                except Exception as e:
                    st.error(f"❌ No se pudo cargar el inventario: {e}")
                    return
            _refrescar_repuestos()
            st.session_state["inv_resultado"] = {"cargados": cargados, "fallidas": fallidas,
                                                 "automaticos": automaticos, "omitidas": len(omitidas)}
            st.session_state["inv_n"] += 1       # vacía el cargador de archivos
            st.rerun()


# ----------------------------------------------------------------
# Pantalla
# ----------------------------------------------------------------
def render_repuestos():
    st.title("📦 Inventario de Repuestos")

    repuestos = st.session_state.get("repuestos", [])

    # --- REPUESTOS CRÍTICOS (stock en o por debajo del mínimo) ---
    criticos = [r for r in repuestos if r.get("stock_actual", 0) <= r.get("stock_minimo", 0)]
    if criticos:
        st.markdown("##### 🚨 Repuestos en nivel crítico de stock")
        for r in criticos:
            ubicacion = f"<br><small style='color:#7C8894;'>📍 {r.get('ubicacion')}</small>" if r.get("ubicacion") else ""
            st.markdown(f"""
            <div class='industrial-panel' style='border-color:#EF4444;'>
                <strong>{r.get('nombre')}</strong> <small style='color:#7C8894;'>[{r.get('codigo_interno')}]</small><br>
                <span style='color:#EF4444; font-weight:bold;'>Stock actual: {r.get('stock_actual')} / Mínimo: {r.get('stock_minimo')}</span>{ubicacion}
            </div>
            """, unsafe_allow_html=True)
        st.markdown("---")

    # --- CARGA MASIVA DESDE EXCEL (para el inventario inicial) ---
    _render_resultado_anterior()
    _render_importador(repuestos)

    st.markdown("---")

    # --- FORMULARIO DE CREACIÓN ---
    st.subheader("Añadir Nuevo Repuesto al Stock")
    with st.form("form_nuevo_repuesto", clear_on_submit=True):
        col1, col2 = st.columns(2)

        with col1:
            nombre = st.text_input("Nombre del Repuesto", placeholder="Ej: Rodamiento SKF 6204")
            codigo_interno = st.text_input("Código Interno", placeholder="Ej: REP-ROD-001")
            ubicacion = st.text_input("Ubicación (opcional)", placeholder="Ej: Estante 1 - Fila 3")

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
                if ubicacion.strip():  # solo se envía si se completó: así funciona aunque todavía no hayas corrido el SQL
                    nuevo_repuesto["ubicacion"] = ubicacion.strip()
                insert_repuesto(nuevo_repuesto)
                _refrescar_repuestos()
                st.success(f"✅ Repuesto '{nombre}' añadido correctamente.")
                st.rerun()

    # --- TABLA DE STOCK ---
    st.markdown("---")
    st.subheader("Materiales en Almacén")
    if not repuestos:
        st.info("El inventario está vacío actualmente.")
    else:
        st.dataframe(repuestos, width="stretch", hide_index=True)
