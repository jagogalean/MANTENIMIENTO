"""
Planes preventivos: tabla con el estado de cada plan (vencido, próximo, al día)
y un panel al costado para trabajar el plan elegido: crear su OT, marcarlo
ejecutado, editar actividades o eliminarlo.

La próxima fecha siempre se calcula con la misma regla de cadencia
(database/ots_servicio.py), venga de esta pantalla o del cierre de una OT.
"""
from datetime import timedelta

import pandas as pd
import streamlit as st

from database.conection import (
    insert_plan, update_plan, delete_plan, get_planes, insert_actividad, delete_actividad, get_actividades,
)
from database import ots_servicio as S
from views import ui

FILTROS = ["Vencidos", "Próximos 7 días", "Al día", "Sin fecha", "Todos"]


def _estado_plan(p, hoy):
    f = ui.a_fecha(p.get("proxima_ejecucion"))
    if f is None:
        return "Sin fecha", None
    if f < hoy:
        return "Vencidos", f"Vencido hace {(hoy - f).days} d"
    if (f - hoy).days <= 7:
        return "Próximos 7 días", "Vence hoy" if f == hoy else f"Vence en {(f - hoy).days} d"
    return "Al día", f"{f:%d/%m/%Y}"


def _refrescar():
    st.session_state.planes = get_planes()
    st.session_state.plan_actividades = get_actividades()


@st.dialog("Nuevo plan preventivo", width="large")
def _dialogo_nuevo(maquinas):
    mapa = {m["id"]: m for m in maquinas}
    maquina_id = st.selectbox("Máquina *", list(mapa.keys()), index=None, placeholder="Escribí para buscar",
                              format_func=lambda i: mapa[i]["nombre"])
    nombre = st.text_input("Nombre del plan *", placeholder="Ej.: Lubricación mensual")
    c1, c2 = st.columns(2)
    frecuencia = c1.number_input("Frecuencia (días) *", min_value=1, step=1, value=30)
    ultima = c2.date_input("Última vez que se hizo (opcional)", value=None, format="DD/MM/YYYY")
    actividades = st.text_area("Actividades * (una por línea)", height=140,
                               placeholder="Lubricar rodamientos lado operador\nRevisar tensión de correas\nLimpiar filtros")
    st.caption("La próxima fecha se calcula desde la última ejecución (o desde hoy). Después la podés repartir en «Programación del año».")
    if st.button("Guardar plan", type="primary", use_container_width=True):
        lista = [a.strip() for a in (actividades or "").splitlines() if a.strip()]
        if maquina_id is None or not nombre.strip() or not lista:
            st.error("Completá máquina, nombre y al menos una actividad.")
            return
        base = ultima or ui.hoy()
        try:
            creado = insert_plan({"maquina_id": maquina_id, "nombre_plan": nombre.strip(), "frecuencia_dias": int(frecuencia),
                                  "ultima_ejecucion": ultima.strftime("%Y-%m-%d") if ultima else None,
                                  "proxima_ejecucion": (base + timedelta(days=int(frecuencia))).strftime("%Y-%m-%d")})
            plan_id = creado[0]["id"] if creado else None
            for a in lista:
                insert_actividad({"plan_id": plan_id, "actividad": a})
        except Exception as e:
            ui.error_amigable("No se pudo guardar el plan.", e)
            return
        _refrescar()
        st.session_state["planes_mensaje"] = f"Plan «{nombre.strip()}» creado con {len(lista)} actividad(es)."
        st.rerun()


def _panel(p, maquina, actividades, hoy):
    pid = p.get("id")
    _, texto_estado = _estado_plan(p, hoy)
    ot_abierta = next((o for o in st.session_state.get("ots", [])
                       if o.get("plan_id") == pid and o.get("estado") != "Completada"), None)
    with st.container(border=True):
        st.markdown(f"**{ui.texto_md(p.get('nombre_plan'))}**")
        st.caption(f"{maquina.get('nombre', 'Máquina')} · cada {p.get('frecuencia_dias')} días · "
                   f"última: {ui.fecha_corta(p.get('ultima_ejecucion'))} · próxima: {ui.fecha_corta(p.get('proxima_ejecucion'))}")
        if texto_estado:
            st.markdown(f":{'red' if 'Vencido' in texto_estado else 'blue'}-badge[{texto_estado}]")

        if ot_abierta:
            st.info(f"Ya tiene una OT abierta: {ot_abierta.get('codigo')} ({S.NOMBRE_ESTADO.get(ot_abierta.get('estado'))}). "
                    "Al completarla, el plan avanza solo.")
        else:
            c1, c2 = st.columns(2)
            if c1.button("Crear OT", type="primary", key=f"plan_ot_{pid}", use_container_width=True):
                acts = "\n".join(f"- {a.get('actividad')}" for a in actividades)
                try:
                    codigo, _ = S.crear_ot({
                        "maquina_id": p.get("maquina_id"), "tipo_mantenimiento": "Preventivo", "plan_id": pid,
                        "descripcion": f"{p.get('nombre_plan')}\n{acts}".strip(), "estado": "Pendiente", "tecnico_id": None,
                    })
                except Exception as e:
                    ui.error_amigable("No se pudo crear la OT del plan.", e)
                else:
                    st.session_state["planes_mensaje"] = f"Se creó {codigo}. Al completarla, el plan avanza solo."
                    st.rerun()
            if ui.boton_confirmar("Marcar ejecutado", f"exec_plan_{pid}",
                                  "Registra que el plan se hizo hoy (sin OT) y calcula la próxima fecha. ¿Confirmás?",
                                  texto_confirmar="Sí, marcar ejecutado", use_container_width=True):
                S.registrar_ejecucion_plan(p, es_plan=True)
                st.session_state["planes_mensaje"] = "Plan marcado como ejecutado."
                st.rerun()

        st.markdown("**Actividades**")
        if not actividades:
            st.caption("Este plan no tiene actividades.")
        for a in actividades:
            ca, cx = st.columns([6, 1], vertical_alignment="center")
            ca.markdown(f"- {ui.texto_md(a.get('actividad'))}")
            if cx.button("Quitar", key=f"del_act_{a.get('id')}", type="tertiary"):
                delete_actividad(a.get("id"))
                st.session_state.plan_actividades = get_actividades()
                st.rerun()
        c1, c2 = st.columns([4, 1], vertical_alignment="bottom")
        nueva = c1.text_input("Agregar actividad", key=f"add_act_{pid}")
        if c2.button("Agregar", key=f"btn_add_act_{pid}", use_container_width=True) and nueva.strip():
            insert_actividad({"plan_id": pid, "actividad": nueva.strip()})
            st.session_state.plan_actividades = get_actividades()
            st.rerun()

        with st.expander("Editar plan"):
            nombre = st.text_input("Nombre", value=p.get("nombre_plan") or "", key=f"plan_nom_{pid}")
            c1, c2 = st.columns(2)
            frecuencia = c1.number_input("Frecuencia (días)", min_value=1, step=1, value=int(p.get("frecuencia_dias") or 30),
                                         key=f"plan_frec_{pid}")
            proxima = c2.date_input("Próxima ejecución", value=ui.a_fecha(p.get("proxima_ejecucion")), format="DD/MM/YYYY",
                                    key=f"plan_prox_{pid}")
            if st.button("Guardar plan", key=f"plan_guardar_{pid}"):
                if not nombre.strip():
                    st.error("El nombre no puede quedar vacío.")
                else:
                    update_plan(pid, {"nombre_plan": nombre.strip(), "frecuencia_dias": int(frecuencia),
                                      "proxima_ejecucion": proxima.strftime("%Y-%m-%d") if proxima else None})
                    _refrescar()
                    st.session_state["planes_mensaje"] = "Plan actualizado."
                    st.rerun()
            if ui.boton_confirmar("Eliminar plan", f"del_plan_{pid}",
                                  f"Se eliminan el plan y sus {len(actividades)} actividades. No se puede deshacer.",
                                  texto_confirmar="Sí, eliminar"):
                try:
                    delete_plan(pid)
                except Exception as e:
                    ui.error_amigable("No se pudo eliminar el plan (puede tener OTs o ejecuciones asociadas).", e)
                else:
                    _refrescar()
                    st.session_state["planes_mensaje"] = "Plan eliminado."
                    st.rerun()


def render_planes(mostrar_titulo=True):
    if mostrar_titulo:
        ui.encabezado("Planes preventivos")
    maquinas = st.session_state.get("maquinas", [])
    planes = st.session_state.get("planes", [])
    actividades = st.session_state.get("plan_actividades", [])
    mapa_maq = {m["id"]: m for m in maquinas}
    hoy = ui.hoy()

    if not maquinas:
        ui.estado_vacio("Todavía no hay máquinas.", "Cargá al menos una en Activos → Máquinas para crear planes.")
        return

    mensaje = st.session_state.pop("planes_mensaje", None)
    if mensaje:
        st.toast(mensaje, icon=":material/check_circle:")
        st.success(mensaje)

    conteo = {f: 0 for f in FILTROS}
    for p in planes:
        conteo[_estado_plan(p, hoy)[0]] += 1
    conteo["Todos"] = len(planes)

    c_f, c_s, c_n = st.columns([4, 1.6, 1.2], vertical_alignment="bottom")
    filtro = c_f.pills("Estado", FILTROS, default="Vencidos" if conteo["Vencidos"] else "Todos", key="planes_filtro",
                       format_func=lambda f: f"{f} {conteo[f]}", label_visibility="collapsed") or "Todos"
    secciones = sorted({(m.get("seccion") or "—") for m in maquinas}, key=str.casefold)
    seccion = c_s.selectbox("Sección", ["Todas"] + secciones, key="planes_seccion", label_visibility="collapsed",
                            format_func=lambda x: "Todas las secciones" if x == "Todas" else x)
    if c_n.button("+ Nuevo plan", type="primary", use_container_width=True):
        _dialogo_nuevo(maquinas)

    lista = [p for p in planes if filtro == "Todos" or _estado_plan(p, hoy)[0] == filtro]
    if seccion != "Todas":
        lista = [p for p in lista if (mapa_maq.get(p.get("maquina_id"), {}).get("seccion") or "—") == seccion]
    lista = sorted(lista, key=lambda p: str(p.get("proxima_ejecucion") or "9999"))

    if not lista:
        ui.estado_vacio("No hay planes con este filtro." if planes else "Todavía no hay planes preventivos.",
                        "Usá «+ Nuevo plan» o generalos desde el manual en la ficha de la máquina." if not planes else None)
        return

    acts_por_plan = {}
    for a in actividades:
        acts_por_plan.setdefault(a.get("plan_id"), []).append(a)

    izq, der = st.columns([3, 2], gap="medium")
    with izq:
        df = pd.DataFrame([{
            "id": p.get("id"),
            "Plan": p.get("nombre_plan"),
            "Máquina": mapa_maq.get(p.get("maquina_id"), {}).get("nombre", "—"),
            "Frecuencia": f"{p.get('frecuencia_dias')} d",
            "Próxima": ui.fecha_corta(p.get("proxima_ejecucion")),
            "Estado": _estado_plan(p, hoy)[1] or "Sin fecha",
            "Horas": float(p.get("horas_hombre") or 0) or None,
            "Actividades": len(acts_por_plan.get(p.get("id"), [])),
        } for p in lista])
        evento = st.dataframe(df, hide_index=True, use_container_width=True, on_select="rerun", selection_mode="single-row",
                              key="planes_tabla", column_order=[c for c in df.columns if c != "id"],
                              height=min(38 + 35 * len(df), 600))
        st.caption(f"{len(lista)} plan(es). Tocá uno para crear su OT, marcarlo ejecutado o editarlo.")
        filas = evento.selection.rows if evento and evento.selection else []
        sel = None
        if filas and filas[0] < len(df):
            valor = df.iloc[filas[0]]["id"]
            sel = valor.item() if hasattr(valor, "item") else valor
    with der:
        plan = next((p for p in lista if p.get("id") == sel), None)
        if plan:
            _panel(plan, mapa_maq.get(plan.get("maquina_id"), {}), acts_por_plan.get(plan.get("id"), []), hoy)
        else:
            with st.container(border=True):
                st.caption("Elegí un plan de la lista para trabajarlo.")
