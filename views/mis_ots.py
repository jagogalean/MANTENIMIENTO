"""
Mis OTs: la pantalla del técnico, pensada para el celular.

Tres vistas: Mías (lo que tengo que hacer), Libres (backlog para tomar) y
Hechas. Cada tarjeta tiene UNA acción principal grande (Iniciar, Completar o
Reanudar) y el resto en botones secundarios.

Reglas (las mismas que en Órdenes de trabajo, en database/ots_servicio.py):
- Sin permiso de trabajo emitido no se puede iniciar ni completar (H-11).
- Al completar una OT preventiva, el plan registra la ejecución y avanza
  su fecha (antes eso solo pasaba desde la pantalla del administrador, H-07).
"""
from datetime import datetime

import streamlit as st

from database.conection import (
    get_ots_cached, get_repuestos_cached, consumir_repuesto_seguro, tomar_ot_backlog_seguro, get_ot_repuestos,
)
from database import ots_servicio as S
from views import ui

ORDEN_ESTADO = {"En Ejecucion": 0, "Pendiente": 1, "Bloqueada": 2}


def _antiguedad(ot, ahora):
    d = ui.a_datetime(ot.get("fecha_inicio"))
    if not d:
        return ""
    horas = (ahora - d).total_seconds() / 3600
    return f"hace {horas:.0f} h" if horas < 48 else f"hace {horas / 24:.0f} días"


def _aplicar(ot, nuevo_estado, motivo=None, extra=None):
    try:
        ok, msg = S.cambiar_estado(ot, nuevo_estado, motivo_bloqueo=motivo, extra=extra)
    except Exception as e:
        ui.error_amigable("No se pudo guardar el cambio. Revisá la conexión y probá de nuevo.", e)
        return
    if ok:
        st.session_state["misots_mensaje"] = msg
        st.rerun()
    else:
        st.error(msg)


def _tarjeta_mia(ot, mapa_maq, repuestos, ahora):
    oid = ot.get("id")
    estado = ot.get("estado")
    maquina = mapa_maq.get(ot.get("maquina_id"), {})
    with st.container(border=True):
        c1, c2 = st.columns([3, 2], vertical_alignment="center")
        c1.caption(f"{ot.get('codigo')} · {ot.get('tipo_mantenimiento') or ''}")
        c2.markdown(ui.etiqueta_estado(S.NOMBRE_ESTADO.get(estado, estado)))
        st.markdown(f"**{ui.texto_md(maquina.get('nombre', 'Máquina'))}**")
        st.markdown(ui.texto_md(S.descripcion_sin_marca(ot)) or "_(sin descripción)_")
        st.caption(_antiguedad(ot, ahora))
        if S.es_parada(ot):
            st.markdown(":red-badge[Máquina parada]")
        if S.falta_permiso(ot):
            st.error("Falta el permiso de trabajo. No iniciar hasta que el coordinador lo emita.",
                     icon=":material/block:")
        if estado == "Bloqueada":
            st.warning(f"Bloqueada: {ui.texto_md(ot.get('motivo_bloqueo') or 'sin motivo')}")

        # Acción principal
        if estado == "Pendiente":
            if st.button("Iniciar", key=f"mis_iniciar_{oid}", type="primary", use_container_width=True,
                         disabled=S.falta_permiso(ot)):
                _aplicar(ot, "En Ejecucion")
        elif estado == "En Ejecucion":
            if st.button("Completar", key=f"mis_completar_{oid}", type="primary", use_container_width=True,
                         disabled=S.falta_permiso(ot)):
                _aplicar(ot, "Completada")
        elif estado == "Bloqueada":
            if st.button("Reanudar", key=f"mis_reanudar_{oid}", type="primary", use_container_width=True,
                         disabled=S.falta_permiso(ot)):
                _aplicar(ot, "En Ejecucion")

        # Acciones secundarias
        b1, b2, b3 = st.columns(3)
        with b1.popover("+ Repuesto", use_container_width=True):
            if not repuestos:
                st.caption("No hay repuestos cargados.")
            else:
                mapa_rep = {r["id"]: r for r in repuestos}
                rep_id = st.selectbox("Repuesto", list(mapa_rep.keys()), index=None, placeholder="Buscar",
                                      format_func=lambda i: f"{mapa_rep[i].get('codigo_interno') or ''} {mapa_rep[i]['nombre']} "
                                                            f"(stock {mapa_rep[i].get('stock_actual') or 0})".strip(),
                                      key=f"mis_rep_{oid}")
                cant = st.number_input("Cantidad", min_value=1, step=1, key=f"mis_cant_{oid}")
                if st.button("Registrar", key=f"mis_rep_btn_{oid}", type="primary", disabled=rep_id is None):
                    try:
                        consumir_repuesto_seguro(oid, rep_id, cant)
                    except ValueError:
                        st.error("No hay stock suficiente en este momento.")
                    except Exception as e:
                        ui.error_amigable("No se pudo registrar el repuesto.", e)
                    else:
                        S.refrescar_repuestos()
                        st.session_state.ot_repuestos = get_ot_repuestos()
                        st.session_state["misots_mensaje"] = f"Se descontaron {cant} de {mapa_rep[rep_id]['nombre']}."
                        st.rerun()
        if estado != "Bloqueada":
            with b2.popover("Bloquear", use_container_width=True):
                motivo = st.text_input("¿Por qué no se puede seguir?", key=f"mis_motivo_{oid}",
                                       placeholder="Ej.: falta el rodamiento 6204")
                if st.button("Marcar bloqueada", key=f"mis_bloq_{oid}", type="primary"):
                    _aplicar(ot, "Bloqueada", motivo=motivo)
        if estado in ("En Ejecucion", "Bloqueada"):
            with b3.popover("Cerrar con fecha", use_container_width=True):
                st.caption("Si terminaste antes y lo cargás ahora.")
                f = st.date_input("Fecha de cierre", value=ahora.date(), format="DD/MM/YYYY", key=f"mis_ff_{oid}")
                h = st.time_input("Hora", value=ahora.time().replace(second=0, microsecond=0), key=f"mis_hf_{oid}")
                if st.button("Completar", key=f"mis_cerrar_fecha_{oid}", type="primary", disabled=S.falta_permiso(ot)):
                    _aplicar(ot, "Completada", extra={"fecha_fin": datetime.combine(f, h).isoformat()})


@st.dialog("Avisar una falla")
def _dialogo_aviso(usuario):
    maquinas = st.session_state.get("maquinas", [])
    mapa = {m["id"]: m for m in maquinas}
    ahora = ui.ahora()
    maquina_id = st.selectbox("Máquina *", list(mapa.keys()), index=None, placeholder="Escribí para buscar",
                              format_func=lambda i: mapa[i]["nombre"])
    descripcion = st.text_area("¿Qué pasa? *", placeholder="Ej.: pierde aceite el reductor")
    parada = st.toggle("La máquina está parada")
    me_la_asigno = st.toggle("Me la asigno y la trabajo yo", value=True)
    with st.expander("Más datos (opcional)"):
        c1, c2 = st.columns(2)
        fecha = c1.date_input("Fecha de inicio", value=ahora.date(), format="DD/MM/YYYY")
        hora = c2.time_input("Hora", value=ahora.time().replace(second=0, microsecond=0))
        horas_paro = st.number_input("Horas de paro (si ya se sabe)", min_value=0.0, step=0.5)
    if st.button("Crear OT", type="primary", use_container_width=True):
        if maquina_id is None or not (descripcion or "").strip():
            st.error("Elegí la máquina y describí el problema.")
            return
        try:
            codigo, _ = S.crear_ot({
                "maquina_id": maquina_id,
                "tipo_mantenimiento": "Correctivo",
                "descripcion": S.con_marca_parada(descripcion, parada),
                "estado": "En Ejecucion" if me_la_asigno else "Pendiente",
                "fecha_inicio": datetime.combine(fecha, hora).isoformat(),
                "horas_paro": horas_paro,
                "tecnico_id": usuario.get("tecnico_id") if me_la_asigno else None,
                "origen": "tecnico",
            })
        except Exception as e:
            ui.error_amigable("No se pudo crear la OT.", e)
            return
        st.session_state["misots_mensaje"] = (f"OT {codigo} creada y asignada a vos." if me_la_asigno
                                              else f"OT {codigo} creada en el backlog compartido.")
        st.rerun()


def render_mis_ots(usuario):
    tecnico_id = usuario.get("tecnico_id")
    ui.encabezado("Mis OTs", usuario.get("nombre") or "")
    if not tecnico_id:
        st.warning("Tu usuario no está vinculado a un técnico. Pedile al coordinador que lo vincule en Configuración → Usuarios.")
        return

    mensaje = st.session_state.pop("misots_mensaje", None)
    if mensaje:
        st.toast(mensaje, icon=":material/check_circle:")
        st.success(mensaje)

    ahora = ui.ahora()
    mapa_maq = {m["id"]: m for m in st.session_state.get("maquinas", [])}
    repuestos = get_repuestos_cached()
    todas = get_ots_cached()
    mias = sorted([o for o in todas if o.get("tecnico_id") == tecnico_id and o.get("estado") != "Completada"],
                  key=lambda o: (not S.es_parada(o), ORDEN_ESTADO.get(o.get("estado"), 9), o.get("id") or 0))
    libres = sorted([o for o in todas if o.get("tecnico_id") is None and o.get("estado") != "Completada"],
                    key=lambda o: (not S.es_parada(o), o.get("id") or 0))
    hechas = sorted([o for o in todas if o.get("tecnico_id") == tecnico_id and o.get("estado") == "Completada"],
                    key=lambda o: str(o.get("fecha_fin") or ""), reverse=True)

    opciones = [f"Mías · {len(mias)}", f"Libres · {len(libres)}", "Hechas"]
    if st.session_state.get("misots_vista") not in opciones:
        st.session_state["misots_vista"] = opciones[0]
    vista = st.segmented_control("Vista", opciones, key="misots_vista", label_visibility="collapsed") or opciones[0]

    if st.button("+ Avisar una falla nueva", use_container_width=True):
        _dialogo_aviso(usuario)

    if vista == opciones[0]:
        if not mias:
            st.success("No tenés OTs pendientes. Mirá en «Libres» si hay algo para tomar.")
        for o in mias:
            _tarjeta_mia(o, mapa_maq, repuestos, ahora)

    elif vista == opciones[1]:
        if not libres:
            st.success("No hay OTs sin asignar.")
        for o in libres:
            with st.container(border=True):
                st.caption(f"{o.get('codigo')} · {o.get('tipo_mantenimiento') or ''} · {_antiguedad(o, ahora)}")
                st.markdown(f"**{ui.texto_md(mapa_maq.get(o.get('maquina_id'), {}).get('nombre', 'Máquina'))}**"
                            + ("  :red-badge[Máquina parada]" if S.es_parada(o) else ""))
                st.markdown(ui.texto_md(S.descripcion_sin_marca(o)) or "_(sin descripción)_")
                if st.button("Tomar esta OT", key=f"tomar_{o.get('id')}", type="primary", use_container_width=True):
                    try:
                        tomar_ot_backlog_seguro(o.get("id"), tecnico_id)
                    except ValueError:
                        st.warning("Otro técnico la tomó justo antes que vos.")
                    except Exception as e:
                        ui.error_amigable("No se pudo tomar la OT.", e)
                    else:
                        S.refrescar_ots()
                        st.session_state["misots_mensaje"] = f"Te asignaste {o.get('codigo')}."
                        st.rerun()

    else:
        if not hechas:
            st.caption("Todavía no completaste OTs.")
        else:
            st.dataframe([{
                "Código": o.get("codigo"),
                "Máquina": mapa_maq.get(o.get("maquina_id"), {}).get("nombre", "—"),
                "Cerrada": ui.fecha_corta(o.get("fecha_fin")),
                "Trabajo": S.descripcion_sin_marca(o)[:60],
            } for o in hechas[:30]], hide_index=True, use_container_width=True)
