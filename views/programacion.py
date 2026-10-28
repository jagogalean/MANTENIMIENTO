from datetime import date, timedelta

import pandas as pd
import streamlit as st

from database import programacion as pg
from database.conection import get_planes, update_plan

try:  # presupuesto mensual cargado en el sistema (opcional)
    from database.conection import get_presupuestos_cached
except ImportError:  # pragma: no cover
    get_presupuestos_cached = None

MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
ICONO = {"alta": "🔴", "media": "🟠", "info": "ℹ️"}


# ----------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------
def _fmt_gs(v):
    return f"Gs. {v:,.0f}".replace(",", ".")


def _etiqueta_mes(d):
    return f"{MESES[d.month - 1]} {d.year}"


def _proximo_lunes(hoy):
    return hoy + timedelta(days=(7 - hoy.weekday()) % 7 or 7)


def _a_fecha_tabla(v):
    """Convierte lo que devuelve la tabla editable (fecha, Timestamp, NaT o vacío) a date o None."""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return pg.a_fecha(v.date() if hasattr(v, "date") and not isinstance(v, date) else v)


def calcular_cambios(original: dict, editado: dict):
    """
    original / editado: {id_plan: fecha o None}. Devuelve [(id_plan, 'AAAA-MM-DD' o None)] solo con
    los planes cuya fecha cambió.
    """
    cambios = []
    for pid, nueva in editado.items():
        previa = original.get(pid)
        if nueva != previa:
            cambios.append((pid, nueva.isoformat() if nueva else None))
    return cambios


def _presupuesto_por_mes():
    if get_presupuestos_cached is None:
        return {}
    try:
        filas = get_presupuestos_cached()
    except Exception:
        return {}
    resultado = {}
    for f in filas or []:
        d = pg.a_fecha(f.get("periodo"))
        if d and f.get("categoria") == "total" and f.get("monto"):
            resultado[(d.year, d.month)] = float(f["monto"])
    return resultado


def _guardar_fechas(cambios):
    errores = 0
    for pid, iso in cambios:
        try:
            update_plan(pid, {"proxima_ejecucion": iso})
        except Exception:
            errores += 1
    st.session_state.planes = get_planes()
    return len(cambios) - errores, errores


def _evaluar(planes, mapa, desde, hasta, params, presupuesto):
    ocs = pg.proyectar(planes, mapa, desde, hasta)
    avisos = pg.detectar_avisos(ocs, planes, mapa, desde, hasta, params, presupuesto)
    meses = pg.resumen_mensual(ocs, desde, hasta)
    semanas = pg.carga_semanal(ocs)
    return ocs, avisos, meses, semanas


# ----------------------------------------------------------------
# Pantalla
# ----------------------------------------------------------------
def render_programacion(usuario):
    st.title("🗓️ Programación de Preventivos")
    st.write(
        "Asigná la fecha de arranque de cada plan y mirá cómo queda la carga del año: horas-hombre, paradas y gasto. "
        "El objetivo es que los trabajos pesados y los gastos grandes no caigan todos juntos."
    )
    if usuario.get("rol") != "admin":
        st.warning("Esta pantalla está disponible solo para el administrador.")
        return

    planes = st.session_state.get("planes", [])
    maquinas = st.session_state.get("maquinas", [])
    if not planes:
        st.info("Todavía no hay planes preventivos cargados.")
        return
    mapa = {m["id"]: m for m in maquinas}
    hoy = date.today()

    if not any(p.get("horas_hombre") or p.get("costo_estimado") for p in planes):
        st.warning(
            "Los planes no tienen horas ni costo estimado: sin esos datos el reparto solo puede evitar que coincidan "
            "las fechas. Si cargaste los preventivos con el script de esta actualización, corré también el SQL "
            "de estructura (02) y volvé a entrar."
        )

    # ---------------- Parámetros ----------------
    with st.expander("⚙️ Límites de carga (podés ajustarlos)"):
        c1, c2, c3 = st.columns(3)
        max_hp = c1.number_input("Máx. horas-hombre en parada por semana (por línea)", min_value=1.0, value=30.0, step=5.0,
                                 key="prog_max_hp", help="Una línea es un grupo de equipos que se detienen juntos, por ejemplo toda la COEX.")
        hh_sem = c2.number_input("Horas-hombre disponibles por semana (equipo de mantenimiento)", min_value=1.0, value=40.0,
                                 step=5.0, key="prog_hh_sem")
        tope = c3.number_input("Tope de gasto por mes (Gs.) — 0 = sin tope", min_value=0, value=0, step=1_000_000, key="prog_tope",
                               help="Si cargaste el presupuesto mensual en el sistema, se usa ese. Sin tope, se avisa cuando un mes supera 1,5 veces el promedio.")
    params = {"max_hp_semana": float(max_hp), "hh_semana": float(hh_sem), "tope_mes": float(tope)}
    presupuesto = _presupuesto_por_mes()
    desde, hasta = hoy, hoy + timedelta(days=365)

    # ---------------- Resumen ----------------
    con_fecha = [p for p in planes if pg.a_fecha(p.get("proxima_ejecucion"))]
    sin_fecha = [p for p in planes if not pg.a_fecha(p.get("proxima_ejecucion"))]
    veces = lambda p: 365 / p["frecuencia_dias"] if p.get("frecuencia_dias") else 0
    gasto_anual = sum(float(p.get("costo_estimado") or 0) * veces(p) for p in planes)
    hh_anual = sum(float(p.get("horas_hombre") or 0) * veces(p) for p in planes)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Planes", len(planes))
    m2.metric("Con fecha / sin fecha", f"{len(con_fecha)} / {len(sin_fecha)}")
    m3.metric("Gasto anual estimado", _fmt_gs(gasto_anual))
    m4.metric("Horas-hombre al año", f"{hh_anual:,.0f}".replace(",", "."))

    # ---------------- 1. Tabla editable ----------------
    st.markdown("---")
    st.subheader("1. Fechas de cada plan")
    f1, f2 = st.columns([0.6, 0.4])
    lineas = sorted({pg.linea_de(p, mapa) for p in planes})
    filtro_linea = f1.selectbox("Mostrar", ["Todas las líneas"] + lineas, key="prog_filtro_linea")
    solo_sin_fecha = f2.checkbox("Solo los que no tienen fecha", key="prog_solo_sin_fecha")

    visibles = [p for p in planes
                if (filtro_linea == "Todas las líneas" or pg.linea_de(p, mapa) == filtro_linea)
                and (not solo_sin_fecha or not pg.a_fecha(p.get("proxima_ejecucion")))]
    visibles.sort(key=lambda p: (pg.linea_de(p, mapa), mapa.get(p.get("maquina_id"), {}).get("codigo") or "", p.get("frecuencia_dias") or 0))
    original = {p["id"]: pg.a_fecha(p.get("proxima_ejecucion")) for p in visibles}

    if not visibles:
        st.info("No hay planes con ese filtro.")
    else:
        df = pd.DataFrame([{
            "id": p["id"],
            "Línea": pg.linea_de(p, mapa),
            "Equipo": mapa.get(p.get("maquina_id"), {}).get("codigo") or "?",
            "Plan": p.get("nombre_plan"),
            "Tipo": p.get("tipo") or "Mantenimiento",
            "Cada (días)": p.get("frecuencia_dias"),
            "HH": round(float(p.get("horas_hombre") or 0), 1),
            "HH en parada": round(float(p.get("horas_parada") or 0), 1),
            "Gasto por ejecución (Gs.)": int(float(p.get("costo_estimado") or 0)),
            "Próxima ejecución": original[p["id"]],
        } for p in visibles])
        firma = f"{filtro_linea}|{solo_sin_fecha}|{len(planes)}|{st.session_state.get('prog_version', 0)}"
        editado = st.data_editor(
            df, key=f"prog_editor_{firma}", hide_index=True, width="stretch", height=min(60 + 35 * len(df), 560),
            disabled=[c for c in df.columns if c != "Próxima ejecución"],
            column_config={
                "id": None,
                "Próxima ejecución": st.column_config.DateColumn("Próxima ejecución ✏️", format="DD/MM/YYYY",
                                                                  help="Hacé doble click para elegir la fecha. Se repite cada «Cada (días)»."),
                "Gasto por ejecución (Gs.)": st.column_config.NumberColumn(format="%d"),
            },
        )
        nuevas = {int(r["id"]): _a_fecha_tabla(r["Próxima ejecución"]) for _, r in editado.iterrows()}
        cambios = calcular_cambios(original, nuevas)
        b1, b2 = st.columns([0.35, 0.65])
        if b1.button(f"💾 Guardar {len(cambios)} cambio(s) de fecha", disabled=not cambios, type="primary", key="prog_guardar"):
            ok, err = _guardar_fechas(cambios)
            st.session_state["prog_version"] = st.session_state.get("prog_version", 0) + 1
            st.session_state["prog_flash"] = ("success" if not err else "warning",
                                              f"✅ Se guardaron {ok} fecha(s)." + (f" ⚠️ {err} no se pudieron guardar." if err else ""))
            st.rerun()
        if cambios:
            b2.caption("Tenés cambios sin guardar. Mirá abajo cómo afectan la carga una vez guardados.")
    flash = st.session_state.pop("prog_flash", None)
    if flash:
        getattr(st, flash[0])(flash[1])

    # ---------------- 2. Sugerencia automática ----------------
    st.markdown("---")
    st.subheader("2. Sugerir fechas automáticamente")
    with st.expander("✨ Proponer un reparto (podés aceptarlo, corregirlo o ignorarlo)"):
        st.caption(
            "Reparte los planes a lo largo del año buscando que no se acumulen paradas en la misma línea y semana, "
            "que no se junten muchas horas-hombre y que el gasto quede parejo mes a mes. Los planes grandes "
            "(Gs. 10 M o más, o que superan el máximo de parada) no se proponen antes de 30 días, para dar tiempo a "
            "coordinar la parada y hacer la compra. Las primeras fechas son días hábiles; si una repetición cae sábado o domingo, la hacés el día hábil más cercano."
        )
        s1, s2 = st.columns(2)
        inicio = s1.date_input("Empezar a programar desde", value=_proximo_lunes(hoy), format="DD/MM/YYYY", key="prog_inicio")
        alcance = s2.radio("Qué planes reparto", ["Solo los que no tienen fecha", "Todos (reemplaza las fechas actuales)"], key="prog_alcance")
        if st.button("Calcular propuesta", key="prog_calcular"):
            fijos = {p["id"] for p in con_fecha} if alcance.startswith("Solo") else set()
            propuesta = pg.sugerir_fechas(planes, mapa, inicio, fijos_ids=fijos, params=params)
            st.session_state["prog_propuesta"] = {"fechas": {k: v.isoformat() for k, v in propuesta.items()},
                                                  "inicio": inicio.isoformat(), "alcance": alcance}
        prop = st.session_state.get("prog_propuesta")
        if prop:
            fechas = {k: pg.a_fecha(v) for k, v in prop["fechas"].items()}
            if not fechas:
                st.info("No hay planes para repartir con esa selección.")
            else:
                hipotetico = [{**p, "proxima_ejecucion": fechas.get(p["id"], p.get("proxima_ejecucion"))} for p in planes]
                ini = pg.a_fecha(prop["inicio"])
                _, av_nuevo, meses_n, sem_n = _evaluar(hipotetico, mapa, ini, ini + timedelta(days=365), params, presupuesto)
                _, av_actual, meses_a, sem_a = _evaluar(planes, mapa, ini, ini + timedelta(days=365), params, presupuesto)
                pico = lambda sem: max((v["hp"] for v in sem.values()), default=0)
                st.markdown(f"**Propuesta lista para {len(fechas)} plan(es):**")
                k1, k2, k3 = st.columns(3)
                k1.metric("Avisos graves", len([a for a in av_nuevo if a["severidad"] == "alta"]),
                          delta=len([a for a in av_nuevo if a["severidad"] == "alta"]) - len([a for a in av_actual if a["severidad"] == "alta"]), delta_color="inverse")
                k2.metric("Mes más caro", _fmt_gs(max((m["costo"] for m in meses_n), default=0)))
                k3.metric("Pico de HH en parada (semana)", f"{pico(sem_n):.0f}")
                st.dataframe(pd.DataFrame([{
                    "Línea": pg.linea_de(p, mapa), "Equipo": mapa.get(p.get("maquina_id"), {}).get("codigo"),
                    "Plan": p.get("nombre_plan"), "Cada (días)": p.get("frecuencia_dias"),
                    "Fecha propuesta": f"{DIAS[fechas[p['id']].weekday()]} {fechas[p['id']]:%d/%m/%Y}",
                } for p in sorted(planes, key=lambda p: fechas.get(p["id"], date.max)) if p["id"] in fechas]),
                    hide_index=True, width="stretch", height=320)
                a1, a2 = st.columns(2)
                if a1.button(f"✅ Aplicar las {len(fechas)} fechas propuestas", type="primary", key="prog_aplicar"):
                    cambios = [(pid, f.isoformat()) for pid, f in fechas.items()]
                    ok, err = _guardar_fechas(cambios)
                    st.session_state.pop("prog_propuesta", None)
                    st.session_state["prog_version"] = st.session_state.get("prog_version", 0) + 1
                    st.session_state["prog_flash"] = ("success" if not err else "warning",
                                                      f"✅ Se aplicaron {ok} fecha(s)." + (f" ⚠️ {err} fallaron." if err else ""))
                    st.rerun()
                if a2.button("Descartar propuesta", key="prog_descartar"):
                    st.session_state.pop("prog_propuesta", None)
                    st.rerun()

    # ---------------- 3. Carga proyectada ----------------
    st.markdown("---")
    st.subheader("3. Cómo queda el año")
    if not con_fecha:
        st.info("Todavía ningún plan tiene fecha. Asignalas en la tabla de arriba o usá «Sugerir fechas».")
        return
    ocs, avisos, meses, semanas = _evaluar(planes, mapa, desde, hasta, params, presupuesto)
    if sin_fecha:
        st.caption(f"⚠️ {len(sin_fecha)} plan(es) todavía no tienen fecha y no están incluidos en estos números.")

    tabla = pd.DataFrame([{
        "Mes": _etiqueta_mes(m["mes"]), "Ejecuciones": m["eventos"], "Gasto (Gs.)": round(m["costo"]),
        "Presupuesto del mes (Gs.)": round(presupuesto.get((m["mes"].year, m["mes"].month), 0)) or None,
        "HH": round(m["hh"], 1), "HH en parada": round(m["hp"], 1),
    } for m in meses])
    g1, g2 = st.columns(2)
    g1.markdown("**Gasto por mes (Gs.)**")
    g1.bar_chart(tabla.set_index("Mes")["Gasto (Gs.)"], height=220)
    g2.markdown("**Horas-hombre por mes**")
    g2.bar_chart(tabla.set_index("Mes")[["HH", "HH en parada"]], height=220)
    st.dataframe(tabla, hide_index=True, width="stretch")

    semanas_pesadas = sorted(semanas.items(), key=lambda kv: (kv[1]["hp"], kv[1]["hh"]), reverse=True)[:8]
    with st.expander("📌 Las 8 semanas más cargadas"):
        st.dataframe(pd.DataFrame([{
            "Semana del": f"{lun:%d/%m/%Y}", "Línea": linea, "HH en parada": round(v["hp"], 1), "HH": round(v["hh"], 1),
            "Planes": len(set(v["ids"])),
        } for (lun, linea), v in semanas_pesadas]), hide_index=True, width="stretch")

    # ---------------- 4. Avisos ----------------
    st.markdown("---")
    st.subheader("4. Avisos")
    if not avisos:
        st.success("✅ Con los límites actuales no hay acumulaciones de paradas, semanas sobrecargadas ni meses con gasto alto.")
    else:
        graves = [a for a in avisos if a["severidad"] == "alta"]
        st.write(f"{len(avisos)} aviso(s): {len(graves)} grave(s). Los graves se corrigen moviendo planes a otra semana.")
        for a in avisos[:25]:
            st.markdown(f"{ICONO[a['severidad']]} {a['texto']}")
        if len(avisos) > 25:
            with st.expander(f"Ver los {len(avisos) - 25} avisos restantes"):
                for a in avisos[25:]:
                    st.markdown(f"{ICONO[a['severidad']]} {a['texto']}")
