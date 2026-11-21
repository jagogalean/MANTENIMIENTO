import hashlib

import pandas as pd
import streamlit as st

from database import inventario_excel as inv
from database.conection import insert_repuesto, get_repuestos, update_repuesto
from views import ui

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
    with st.expander("Importar inventario desde Excel", expanded=False):
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
FILTROS = ["Todos", "Bajo mínimo", "Sin stock", "Sin ubicación"]


def _estado(r):
    stock, minimo = r.get("stock_actual") or 0, r.get("stock_minimo") or 0
    if stock <= 0:
        return "Sin stock"
    if stock <= minimo:
        return "Bajo mínimo"
    return "Disponible"


def _filtrar(repuestos, texto, filtro):
    lista = repuestos
    if texto:
        palabras = texto.casefold().split()
        lista = [r for r in lista if all(p in " ".join(str(r.get(c) or "") for c in ("nombre", "codigo_interno", "ubicacion")).casefold()
                                         for p in palabras)]
    if filtro == "Bajo mínimo":
        lista = [r for r in lista if _estado(r) != "Disponible"]
    elif filtro == "Sin stock":
        lista = [r for r in lista if _estado(r) == "Sin stock"]
    elif filtro == "Sin ubicación":
        lista = [r for r in lista if not (r.get("ubicacion") or "").strip()]
    orden = {"Sin stock": 0, "Bajo mínimo": 1, "Disponible": 2}
    return sorted(lista, key=lambda r: (orden[_estado(r)], str(r.get("nombre") or "").casefold()))


@st.dialog("Nuevo repuesto")
def _dialogo_nuevo(repuestos):
    nombre = st.text_input("Nombre *", placeholder="Ej.: Rodamiento SKF 6204")
    c1, c2 = st.columns(2)
    codigo = c1.text_input("Código interno *", placeholder="Ej.: REP-0142")
    ubicacion = c2.text_input("Ubicación", placeholder="Ej.: Estante 1 – Fila 3")
    c3, c4, c5 = st.columns(3)
    stock = c3.number_input("Stock inicial", min_value=0, step=1)
    minimo = c4.number_input("Stock mínimo", min_value=0, step=1)
    costo = c5.number_input("Costo unitario (Gs.)", min_value=0, step=1000)
    if st.button("Guardar repuesto", type="primary", use_container_width=True):
        if not nombre.strip() or not codigo.strip():
            st.error("El nombre y el código son obligatorios.")
            return
        if any(str(r.get("codigo_interno") or "").strip().casefold() == codigo.strip().casefold() for r in repuestos):
            st.error("Ese código ya existe en el inventario.")
            return
        fila = {"nombre": nombre.strip(), "codigo_interno": codigo.strip(), "stock_actual": int(stock),
                "stock_minimo": int(minimo), "costo_unitario": int(costo)}
        if ubicacion.strip():  # solo si se completó: funciona aunque la columna todavía no exista
            fila["ubicacion"] = ubicacion.strip()
        try:
            insert_repuesto(fila)
        except Exception as e:
            ui.error_amigable("No se pudo guardar el repuesto. Si cargaste ubicación, puede faltar esa columna en la base.", e)
            return
        _refrescar_repuestos()
        st.session_state["rep_mensaje"] = f"Repuesto «{nombre.strip()}» agregado."
        st.rerun()


def _editor(r, repuestos):
    rid = r["id"]
    with st.container(border=True):
        st.markdown(f"**{ui.texto_md(r.get('nombre'))}**")
        st.caption(f"{r.get('codigo_interno') or '—'} · {_estado(r)}")
        nombre = st.text_input("Nombre", value=r.get("nombre") or "", key=f"rep_nom_{rid}")
        c1, c2 = st.columns(2)
        codigo = c1.text_input("Código interno", value=r.get("codigo_interno") or "", key=f"rep_cod_{rid}")
        ubicacion = c2.text_input("Ubicación", value=r.get("ubicacion") or "", key=f"rep_ubi_{rid}")
        c3, c4 = st.columns(2)
        minimo = c3.number_input("Stock mínimo", min_value=0, step=1, value=int(r.get("stock_minimo") or 0), key=f"rep_min_{rid}")
        costo = c4.number_input("Costo unitario (Gs.)", min_value=0, step=1000, value=int(r.get("costo_unitario") or 0), key=f"rep_cos_{rid}")
        stock = st.number_input("Stock actual (ajuste de inventario)", min_value=0, step=1, value=int(r.get("stock_actual") or 0),
                                key=f"rep_stk_{rid}", help="Usalo solo para corregir después de un conteo físico. "
                                                          "Los consumos de las OTs descuentan solos.")
        if st.button("Guardar cambios", type="primary", key=f"rep_guardar_{rid}", use_container_width=True):
            if not nombre.strip() or not codigo.strip():
                st.error("El nombre y el código son obligatorios.")
                return
            if any(x["id"] != rid and str(x.get("codigo_interno") or "").strip().casefold() == codigo.strip().casefold() for x in repuestos):
                st.error("Ese código ya lo usa otro repuesto.")
                return
            patch = {}
            for campo, valor in (("nombre", nombre.strip()), ("codigo_interno", codigo.strip()), ("stock_minimo", int(minimo)),
                                 ("costo_unitario", int(costo)), ("stock_actual", int(stock))):
                if valor != r.get(campo):
                    patch[campo] = valor
            if (ubicacion.strip() or None) != ((r.get("ubicacion") or "").strip() or None):
                patch["ubicacion"] = ubicacion.strip() or None
            if not patch:
                st.info("No había cambios.")
                return
            try:
                update_repuesto(rid, patch)
            except Exception as e:
                ui.error_amigable("No se pudieron guardar los cambios.", e)
                return
            _refrescar_repuestos()
            st.session_state["rep_mensaje"] = "Repuesto actualizado."
            st.rerun()


def _tarjetas(lista):
    """Vista de consulta (celular): tarjeta por repuesto con stock y ubicación."""
    color = {"Sin stock": "red", "Bajo mínimo": "orange", "Disponible": "green"}
    for r in lista[:40]:
        with st.container(border=True):
            c1, c2 = st.columns([3, 2], vertical_alignment="center")
            c1.markdown(f"**{ui.texto_md(r.get('nombre'))}**  \n:gray[{ui.texto_md(r.get('codigo_interno') or '—')}]")
            c2.markdown(f":{color[_estado(r)]}-badge[{_estado(r)}]")
            c3, c4 = st.columns(2)
            c3.markdown(f":gray[Stock]  \n**{r.get('stock_actual') or 0}** · mín. {r.get('stock_minimo') or 0}")
            c4.markdown(f":gray[Ubicación]  \n**{ui.texto_md(r.get('ubicacion') or 'Sin ubicación')}**")
    if len(lista) > 40:
        st.caption(f"Se muestran 40 de {len(lista)}. Afiná la búsqueda.")


def render_repuestos(modo_consulta=False):
    repuestos = st.session_state.get("repuestos", [])
    if modo_consulta:
        ui.encabezado("Repuestos", "Consultá stock y ubicación por código o nombre.")
    else:
        cab, acc = st.columns([4, 1.2], vertical_alignment="bottom")
        with cab:
            ui.encabezado("Repuestos", "Stock, mínimos y ubicación. Tocá un repuesto para editarlo.")
        if acc.button("+ Nuevo repuesto", type="primary", use_container_width=True):
            _dialogo_nuevo(repuestos)

    mensaje = st.session_state.pop("rep_mensaje", None)
    if mensaje:
        st.toast(mensaje, icon=":material/check_circle:")
    if not modo_consulta:
        _render_resultado_anterior()

    if not repuestos:
        ui.estado_vacio("Todavía no hay repuestos cargados.",
                        None if modo_consulta else "Agregá uno con «+ Nuevo repuesto» o importá tu planilla desde Excel (abajo).")
    else:
        texto = st.text_input("Buscar", placeholder="Código, nombre o ubicación", key="rep_buscar", label_visibility="collapsed")
        bajos = len([r for r in repuestos if _estado(r) != "Disponible"])
        filtro = st.pills("Filtro", FILTROS, default="Todos", key="rep_filtro", label_visibility="collapsed",
                          format_func=lambda f: f"Bajo mínimo ({bajos})" if f == "Bajo mínimo" else f) or "Todos"
        lista = _filtrar(repuestos, texto, filtro)
        if not lista:
            ui.estado_vacio("Ningún repuesto coincide con la búsqueda.")
        elif modo_consulta:
            st.caption(f"{len(lista)} resultado(s)")
            _tarjetas(lista)
        else:
            izq, der = st.columns([3, 2], gap="medium")
            with izq:
                df = pd.DataFrame([{
                    "id": r["id"], "Código": r.get("codigo_interno") or "—", "Repuesto": r.get("nombre"),
                    "Stock": r.get("stock_actual") or 0, "Mínimo": r.get("stock_minimo") or 0,
                    "Ubicación": r.get("ubicacion") or "—", "Costo unit.": ui.formato_gs(r.get("costo_unitario")),
                    "Estado": _estado(r),
                } for r in lista])
                evento = st.dataframe(df, hide_index=True, use_container_width=True, on_select="rerun", selection_mode="single-row",
                                      key="rep_tabla", column_order=[c for c in df.columns if c != "id"],
                                      height=min(38 + 35 * len(df), 600))
                st.caption(f"{len(lista)} de {len(repuestos)} repuestos.")
                filas = evento.selection.rows if evento and evento.selection else []
                sel = None
                if filas and filas[0] < len(df):
                    valor = df.iloc[filas[0]]["id"]
                    sel = valor.item() if hasattr(valor, "item") else valor
            with der:
                elegido = next((r for r in repuestos if r["id"] == sel), None)
                if elegido:
                    _editor(elegido, repuestos)
                else:
                    with st.container(border=True):
                        st.caption("Elegí un repuesto de la lista para editar sus datos, mínimo, ubicación o hacer un ajuste de inventario.")

    if not modo_consulta:
        st.divider()
        _render_importador(repuestos)
