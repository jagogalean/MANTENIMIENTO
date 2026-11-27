"""
Producción para Ventas: la Planilla de Planificación de la Producción, fácil de leer.

· Ventas (solo mira): tarjetas grandes por pedido con TODAS las columnas de la planilla, o la tabla completa.
· Supervisor de producción (rol «planificacion») y Coordinador: además cargan y publican la planilla.
"""
import pandas as pd
import streamlit as st

from database import produccion_db as db
from database import produccion_logica as L
from views import ui

_CSS = """
<style>
.st-key-prod_vista p, .st-key-prod_vista li {font-size:1.08rem}
.st-key-prod_vista h3 {font-size:1.35rem}
.st-key-prod_vista [data-testid="stMetricValue"], .st-key-prod_vista [data-testid="stMetricValue"] p {font-size:1.9rem; font-weight:600}
.st-key-prod_vista [data-testid="stMetricLabel"] p {font-size:1rem}
</style>
"""

ORDEN_ESTADO = {L.ATRASADO: 0, L.EN_PRODUCCION: 1, L.PROGRAMADO: 2, L.SIN_FECHA: 3, L.TERMINADO: 4}


def render_produccion(usuario=None):
    usuario = usuario or st.session_state.get("usuario_actual") or {}
    puede_cargar = usuario.get("rol") in ("admin", "planificacion")
    st.markdown(_CSS, unsafe_allow_html=True)
    if puede_cargar:
        modo = st.segmented_control("Modo", ["Ver producción", "Cargar planilla"], default="Ver producción",
                                    key="prod_modo", label_visibility="collapsed") or "Ver producción"
        if modo == "Cargar planilla":
            _cargar(usuario)
            return
    _ver()


# ----------------------------------------------------------------
# Carga (supervisor)
# ----------------------------------------------------------------
def _cargar(usuario):
    ui.encabezado("Cargar planilla de producción", "Arrastrá la planilla de planificación: se revisa y, si está bien, se publica para Ventas.")
    n = st.session_state.get("prod_up_n", 0)
    archivo = st.file_uploader("Planilla de Planificación de la Producción (.xlsx)", type=["xlsx", "xlsm"], key=f"prod_up_{n}")
    if archivo is not None:
        try:
            datos = L.leer_planilla(archivo.getvalue())
        except ValueError as e:
            st.error(str(e))
            datos = None
        if datos:
            ahora = ui.ahora()
            st.success(f"Leída: {len(datos['pedidos']['filas'])} pedidos y {len(datos['desarrollos']['filas'])} desarrollos.")
            for a in datos["avisos"]:
                st.warning(a)
            atrasados = [L.resumen_fila(f, datos[h]["columnas"], ahora) for h in L.HOJAS for f in datos[h]["filas"]]
            atrasados = [r for r in atrasados if r["estado"] == L.ATRASADO]
            if atrasados:
                st.warning(f"{len(atrasados)} fila(s) siguen pendientes con la fecha de fin ya pasada: Ventas las verá como «Atrasado». "
                           "Si ya terminaron, poné «Finalizado» en Proceso antes de publicar.")
            for h, titulo in L.HOJAS.items():
                if datos[h]["filas"]:
                    with st.expander(f"Ver {titulo.lower()} leídos ({len(datos[h]['filas'])})"):
                        st.dataframe(_tabla(datos[h], ahora), hide_index=True, width="stretch")
            if st.button("Publicar para Ventas", type="primary", key="prod_publicar"):
                try:
                    db.publicar(datos, archivo.name, usuario.get("nombre") or "")
                except Exception as e:
                    st.error(f"No se pudo publicar: {e}. Revisá que se haya corrido sql/produccion.sql en Supabase.")
                    return
                st.session_state["prod_up_n"] = n + 1
                st.session_state["prod_flash"] = "Planilla publicada. Ventas ya ve esta versión."
                st.rerun()
    if st.session_state.get("prod_flash"):
        st.success(st.session_state.pop("prod_flash"))
    st.subheader("Publicaciones anteriores")
    try:
        hist = db.historial()
    except Exception as e:
        ui.error_amigable("No se pudo leer el historial de publicaciones.", e)
        return
    if not hist:
        ui.estado_vacio("Todavía no se publicó ninguna planilla.")
        return
    st.dataframe(pd.DataFrame([{"Fecha": L.fecha_amigable(_local(h.get("creado_en")), ui.ahora()), "Archivo": h.get("archivo"),
                                "Cargó": h.get("cargado_por"), "Pedidos": (h.get("resumen") or {}).get("pedidos"),
                                "Desarrollos": (h.get("resumen") or {}).get("desarrollos")} for h in hist]),
                 hide_index=True, width="stretch")


def _local(valor):
    """Hora de la base (UTC) -> hora de Asunción, sin zona."""
    d = L.a_datetime(str(valor).replace("Z", "+00:00")) if valor else None
    if d and d.tzinfo:
        try:
            from zoneinfo import ZoneInfo
            d = d.astimezone(ZoneInfo("America/Asuncion")).replace(tzinfo=None)
        except Exception:
            d = d.replace(tzinfo=None)
    return d


# ----------------------------------------------------------------
# Vista (Ventas)
# ----------------------------------------------------------------
def _ver():
    with st.container(key="prod_vista"):
        try:
            pub = db.ultima()
        except Exception as e:
            ui.error_amigable("No se pudo leer la planilla de producción.", e)
            return
        st.title("Producción")
        if not pub:
            ui.estado_vacio("Todavía no hay planilla publicada. Cuando el supervisor la cargue, aparece acá.")
            return
        ahora = ui.ahora()
        st.caption(f"Datos de planta publicados {L.fecha_amigable(_local(pub.get('creado_en')), ahora)}"
                   + (f" por {pub['cargado_por']}" if pub.get("cargado_por") else "") + ".")
        hojas = {h: pub.get(h) or {"columnas": [], "filas": []} for h in L.HOJAS}
        hoja = st.segmented_control("Hoja", [f"{t} ({len(hojas[h]['filas'])})" for h, t in L.HOJAS.items()],
                                    default=f"Pedidos ({len(hojas['pedidos']['filas'])})", key="prod_hoja",
                                    label_visibility="collapsed") or f"Pedidos ({len(hojas['pedidos']['filas'])})"
        clave = "pedidos" if hoja.startswith("Pedidos") else "desarrollos"
        datos = hojas[clave]
        filas = [(f, L.resumen_fila(f, datos["columnas"], ahora)) for f in datos["filas"]]
        if not filas:
            ui.estado_vacio("Esta hoja no tiene filas en la planilla publicada.")
            return

        en_curso = [r for _, r in filas if r["estado"] != L.TERMINADO]
        m = st.columns(2)
        m[0].metric("Listo para retirar", L.kg(sum(r["disponible"] for _, r in filas)))
        m[1].metric("En producción ahora", sum(1 for r in en_curso if r["estado"] == L.EN_PRODUCCION))
        m = st.columns(2)
        m[0].metric("Programados", sum(1 for r in en_curso if r["estado"] == L.PROGRAMADO))
        m[1].metric("Atrasados", sum(1 for r in en_curso if r["estado"] == L.ATRASADO))

        clientes = sorted({str(r["cliente"]) for _, r in filas})
        cliente = st.selectbox("Cliente", ["Todos los clientes"] + clientes, key=f"prod_cliente_{clave}")
        cual = st.segmented_control("Mostrar", ["En curso", "Terminados", "Todos"], default="En curso",
                                    key=f"prod_estado_{clave}", label_visibility="collapsed") or "En curso"
        vista = st.segmented_control("Cómo verlo", ["Tarjetas", "Tabla completa"], default="Tarjetas",
                                     key="prod_como", label_visibility="collapsed") or "Tarjetas"

        elegidas = [(f, r) for f, r in filas if cliente == "Todos los clientes" or str(r["cliente"]) == cliente]
        if cual == "En curso":
            elegidas = [(f, r) for f, r in elegidas if r["estado"] != L.TERMINADO]
        elif cual == "Terminados":
            elegidas = [(f, r) for f, r in elegidas if r["estado"] == L.TERMINADO]
        elegidas.sort(key=lambda x: (ORDEN_ESTADO[x[1]["estado"]], x[1]["fin"] or x[1]["inicio"] or ahora)
                      if x[1]["estado"] != L.TERMINADO else (9, -(x[1]["fin"] or ahora).timestamp()))
        if not elegidas:
            ui.estado_vacio("No hay filas para ese cliente con este filtro. Probá con «Todos».")
            return
        if vista == "Tabla completa":
            st.dataframe(_tabla({"columnas": datos["columnas"], "filas": [f for f, _ in elegidas]}, ahora),
                         hide_index=True, width="stretch")
            return
        for fila, r in elegidas:
            _tarjeta(fila, r, datos["columnas"], ahora)


def _tarjeta(fila, r, columnas, ahora):
    with st.container(border=True):
        oc = L.texto_celda(next((c for c in columnas if L.es_columna(c, "oc", columnas)), ""), r["oc"], columnas, ahora) if r["oc"] else ""
        st.markdown(f"### {ui.texto_md(r['cliente'])}")
        st.markdown(f":{L.COLOR[r['estado']]}-badge[{r['estado']}]" + (f"  ·  OC {ui.texto_md(oc)}" if oc else "")
                    + f"  ·  {ui.texto_md(r['codigo'] or '')} {ui.texto_md(r['referencia'] or '')}")
        st.progress(r["avance"], text=f"Hecho {L.kg(r['producido'])} de {L.kg(r['solicitado'])} ({r['avance'] * 100:.0f} %)")
        if r["estado"] == L.EN_PRODUCCION:
            st.markdown(f":orange[**Termina {L.fecha_amigable(r['fin'], ahora)}**]")
        elif r["estado"] == L.PROGRAMADO:
            st.markdown(f":blue[**Empieza {L.fecha_amigable(r['inicio'], ahora)} · listo {L.fecha_amigable(r['fin'], ahora)}**]")
        elif r["estado"] == L.ATRASADO:
            st.markdown(f":red[**Tenía que terminar {L.fecha_amigable(r['fin'], ahora)}: consultá a planta**]")
        if r["disponible"] > 0:
            st.markdown(f":green[**Puede retirar {L.kg(r['disponible'])}**]")
        # TODAS las columnas de la planilla, en su orden
        # de a dos por renglón: en la compu quedan en 2 columnas y en el celular se apilan en el MISMO orden que la planilla
        for i in range(0, len(columnas), 2):
            for celda, col in zip(st.columns(2), columnas[i:i + 2]):
                celda.markdown(f":gray[{ui.texto_md(col)}]  \n**{ui.texto_md(L.texto_celda(col, fila.get(col), columnas, ahora))}**")


def _tabla(datos, ahora):
    columnas = datos["columnas"]
    df = pd.DataFrame([{c: L.texto_celda(c, f.get(c), columnas, ahora) for c in columnas} for f in datos["filas"]], columns=columnas)
    df.insert(1, "Estado", [L.resumen_fila(f, columnas, ahora)["estado"] for f in datos["filas"]])
    return df
