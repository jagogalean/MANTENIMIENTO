"""
Órdenes de trabajo: lista con búsqueda -> detalle al costado.

- La lista muestra lo que hace falta para decidir (estado, máquina, técnico,
  antigüedad, alertas). Al tocar una fila se abre su detalle.
- El detalle tiene pestañas: Estado · Repuestos · Costos · Más acciones.
- "+ Nueva OT" abre una ventana con el formulario de alta.
- Todas las reglas (permiso de trabajo, cierre de preventivos, código de OT)
  viven en database/ots_servicio.py y son las mismas que usa Mis OTs.
"""
from datetime import datetime

import pandas as pd
import streamlit as st

from database.conection import (
    update_ot, delete_ot, consumir_repuesto_seguro, get_ots_cached, get_repuestos_cached,
    get_ots_paginado, get_ot_repuestos,
)
from database.permisos import es_admin
from database import ots_servicio as S
from views import ui

ESTADOS_OT = S.ESTADOS_OT  # se mantiene el nombre por compatibilidad


def calcular_costo_ot(tipo_ejecucion, horas_trabajadas=0, costo_hora_hombre=0, costo_repuestos=0,
                      costo_factura_tercero=0, costo_flete_logistica=0,
                      fecha_inicio_parada=None, fecha_fin_parada=None, costo_hora_parada=0):
    """Desglose de costos de una OT, interna o tercerizada.

    - Interno: Costo Directo = mano de obra (horas × costo hora-hombre) + repuestos.
    - Tercerizado: Costo Directo = factura del proveedor + flete/logística.
    - Siempre: Lucro Cesante = horas de parada × costo hora de parada de la máquina.
    - Costo Total = Costo Directo + Lucro Cesante.
    """
    horas_parada = 0.0
    if fecha_inicio_parada and fecha_fin_parada and fecha_fin_parada > fecha_inicio_parada:
        horas_parada = (fecha_fin_parada - fecha_inicio_parada).total_seconds() / 3600
    costo_lucro_cesante = horas_parada * (costo_hora_parada or 0)
    if tipo_ejecucion == "interno":
        costo_mano_obra = (horas_trabajadas or 0) * (costo_hora_hombre or 0)
        costo_directo = costo_mano_obra + (costo_repuestos or 0)
    else:
        costo_mano_obra = 0
        costo_directo = (costo_factura_tercero or 0) + (costo_flete_logistica or 0)
    return {
        "horas_parada": round(horas_parada, 2),
        "costo_mano_obra": round(costo_mano_obra, 2),
        "costo_directo": round(costo_directo, 2),
        "costo_lucro_cesante": round(costo_lucro_cesante, 2),
        "costo_total": round(costo_directo + costo_lucro_cesante, 2),
    }


# ------------------------------------------------------------------
# Ayudas
# ------------------------------------------------------------------
def _antiguedad(ot, ahora):
    d = ui.a_datetime(ot.get("fecha_inicio"))
    if not d:
        return ""
    horas = (ahora - d).total_seconds() / 3600
    if horas < 1:
        return "min"
    if horas < 48:
        return f"{horas:.0f} h"
    return f"{horas / 24:.0f} d"


def _alertas(ot):
    partes = []
    if S.es_parada(ot) and ot.get("estado") != "Completada":
        partes.append("Máquina parada")
    if S.falta_permiso(ot) and ot.get("estado") != "Completada":
        partes.append("Falta permiso")
    if ot.get("estado") == "Bloqueada" and ot.get("motivo_bloqueo"):
        partes.append(str(ot.get("motivo_bloqueo"))[:40])
    return " · ".join(partes)


def _etiqueta_repuesto(r):
    codigo = r.get("codigo_interno") or f"#{r.get('id')}"
    return f"{codigo} — {r.get('nombre')} (stock {r.get('stock_actual') or 0})"


def _consumos_de(ot_id):
    return [c for c in st.session_state.get("ot_repuestos", []) if c.get("ot_id") == ot_id]


def _refrescar_consumos():
    st.session_state.ot_repuestos = get_ot_repuestos()


# ------------------------------------------------------------------
# Alta de OT (ventana)
# ------------------------------------------------------------------
@st.dialog("Nueva orden de trabajo", width="large")
def _dialogo_nueva_ot(usuario):
    maquinas = st.session_state.get("maquinas", [])
    tecnicos = st.session_state.get("tecnicos", [])
    repuestos = get_repuestos_cached()
    mapa_maq = {m["id"]: m for m in maquinas}
    mapa_tec = {t["id"]: t for t in tecnicos}

    maquina_id = st.selectbox(
        "Máquina *", list(mapa_maq.keys()), index=None, placeholder="Escribí para buscar la máquina",
        format_func=lambda i: f"{mapa_maq[i].get('codigo') or ''} {mapa_maq[i].get('nombre')}".strip(),
    )
    c1, c2 = st.columns(2)
    tipo = c1.segmented_control("Tipo *", S.TIPOS_OT, default="Correctivo", key="nueva_ot_tipo")
    tecnico_id = c2.selectbox("Técnico", [None] + list(mapa_tec.keys()),
                              format_func=lambda i: "Sin asignar (backlog compartido)" if i is None else mapa_tec[i]["nombre"])
    descripcion = st.text_area("¿Qué hay que hacer? *", placeholder="Ej.: cambiar correa del enrollador, ruido en rodamiento lado operador")

    c3, c4 = st.columns(2)
    parada = c3.toggle("La máquina está parada", value=False)
    estado = c4.segmented_control("Estado inicial", ["Pendiente", "En Ejecucion"], default="Pendiente",
                                  format_func=lambda e: S.NOMBRE_ESTADO[e], key="nueva_ot_estado")
    c5, c6 = st.columns(2)
    requiere = c5.toggle("Requiere permiso de trabajo", help="LOTO, trabajo en altura, eléctrico, espacio confinado")
    emitido = c6.toggle("El permiso ya está emitido", disabled=not requiere)

    st.markdown("**Repuestos a usar** (opcional; se descuentan del stock al guardar)")
    etiquetas = {_etiqueta_repuesto(r): r for r in repuestos}
    tabla = st.data_editor(
        pd.DataFrame({"Repuesto": pd.Series([], dtype="object"), "Cantidad": pd.Series([], dtype="int")}),
        num_rows="dynamic", use_container_width=True, hide_index=True, key="nueva_ot_repuestos",
        column_config={
            "Repuesto": st.column_config.SelectboxColumn("Repuesto", options=list(etiquetas.keys()), required=True, width="large"),
            "Cantidad": st.column_config.NumberColumn("Cantidad", min_value=1, step=1, default=1, required=True),
        },
    )
    with st.expander("Datos de OpenOrange (opcional)"):
        nro_ot = st.text_input("N° OT OpenOrange")
        nro_oc = st.text_input("N° OC OpenOrange asociada")

    b1, b2 = st.columns(2)
    if b1.button("Cancelar", use_container_width=True):
        st.rerun()
    if b2.button("Crear OT", type="primary", use_container_width=True):
        errores = []
        if maquina_id is None:
            errores.append("Elegí la máquina.")
        if not (descripcion or "").strip():
            errores.append("Describí el trabajo.")
        if estado == "En Ejecucion" and requiere and not emitido:
            errores.append("No se puede iniciar sin el permiso de trabajo emitido. Dejala en «Pendiente».")
        carrito = []
        for _, fila in tabla.dropna().iterrows():
            r = etiquetas.get(fila["Repuesto"])
            if r:
                carrito.append({"repuesto_id": r["id"], "nombre": r["nombre"], "cantidad": int(fila["Cantidad"])})
        for item in carrito:
            disponible = next((r.get("stock_actual") or 0 for r in repuestos if r["id"] == item["repuesto_id"]), 0)
            pedido = sum(i["cantidad"] for i in carrito if i["repuesto_id"] == item["repuesto_id"])
            if pedido > disponible:
                errores.append(f"No hay stock suficiente de {item['nombre']}: hay {disponible}, pediste {pedido}.")
        if errores:
            for e in dict.fromkeys(errores):
                st.error(e)
            return
        try:
            codigo, fallidos = S.crear_ot({
                "maquina_id": maquina_id,
                "tipo_mantenimiento": tipo or "Correctivo",
                "descripcion": S.con_marca_parada(descripcion, parada),
                "estado": estado or "Pendiente",
                "tecnico_id": tecnico_id,
                "requiere_permiso_trabajo": requiere,
                "permiso_trabajo_emitido": bool(requiere and emitido),
                "nro_ot_openorange": (nro_ot or "").strip() or None,
                "nro_oc_openorange": (nro_oc or "").strip() or None,
            }, carrito)
        except Exception as e:
            ui.error_amigable("No se pudo crear la OT. Probá de nuevo; si sigue fallando, avisá al administrador.", e)
            return
        if carrito:
            _refrescar_consumos()
        mensaje = f"OT {codigo} creada."
        if fallidos:
            mensaje += f" Sin stock al guardar: {', '.join(fallidos)}. Revisalo en la pestaña Repuestos."
        st.session_state["ots_mensaje"] = mensaje
        st.session_state["ot_sel_codigo"] = codigo
        st.rerun()


# ------------------------------------------------------------------
# Detalle de una OT
# ------------------------------------------------------------------
def _detalle(ot, usuario):
    maquinas = {m["id"]: m for m in st.session_state.get("maquinas", [])}
    tecnicos = {t["id"]: t for t in st.session_state.get("tecnicos", [])}
    maquina = maquinas.get(ot.get("maquina_id"), {})
    oid = ot.get("id")
    admin = es_admin(usuario)

    with st.container(border=True):
        st.caption(f"{ot.get('codigo')} · {ot.get('tipo_mantenimiento') or '—'} · abierta el {ui.fecha_corta(ot.get('fecha_inicio'))}")
        st.markdown(f"#### {ui.texto_md(S.descripcion_sin_marca(ot).splitlines()[0][:90] if S.descripcion_sin_marca(ot) else 'Sin descripción')}")
        etiquetas = [ui.etiqueta_estado(S.NOMBRE_ESTADO.get(ot.get("estado"), ot.get("estado")))]
        if S.es_parada(ot) and ot.get("estado") != "Completada":
            etiquetas.append(":red-badge[Máquina parada]")
        if ot.get("requiere_permiso_trabajo"):
            etiquetas.append(":green-badge[Permiso emitido]" if ot.get("permiso_trabajo_emitido") else ":red-badge[Falta permiso]")
        st.markdown(f"**{ui.texto_md(maquina.get('nombre', 'Máquina'))}** · Criticidad {maquina.get('criticidad') or '—'}  \n" + " ".join(etiquetas))
        if ot.get("estado") == "Bloqueada" and ot.get("motivo_bloqueo"):
            st.warning(f"Bloqueada: {ui.texto_md(ot.get('motivo_bloqueo'))}")

        pestanas = ["Estado", f"Repuestos ({len(_consumos_de(oid))})", "Costos"] + (["Más acciones"] if admin else [])
        tabs = st.tabs(pestanas)

        # --- Estado ---
        with tabs[0]:
            nuevo_estado = st.segmented_control(
                "Estado", S.ESTADOS_OT, default=ot.get("estado") if ot.get("estado") in S.ESTADOS_OT else "Pendiente",
                format_func=lambda e: S.NOMBRE_ESTADO[e], key=f"ot_estado_{oid}")
            motivo = ot.get("motivo_bloqueo") or ""
            if nuevo_estado == "Bloqueada":
                motivo = st.text_input("Motivo del bloqueo *", value=motivo, key=f"ot_motivo_{oid}",
                                       placeholder="Ej.: falta rodamiento 6204, espera aprobación de compra")
            c1, c2 = st.columns(2)
            tec_ids = [None] + list(tecnicos.keys())
            tecnico_id = c1.selectbox("Técnico", tec_ids,
                                      index=tec_ids.index(ot.get("tecnico_id")) if ot.get("tecnico_id") in tec_ids else 0,
                                      format_func=lambda i: "Sin asignar" if i is None else tecnicos[i]["nombre"],
                                      key=f"ot_tec_{oid}")
            parada = c2.toggle("Máquina parada", value=S.es_parada(ot), key=f"ot_parada_{oid}")
            c3, c4 = st.columns(2)
            requiere = c3.toggle("Requiere permiso de trabajo", value=bool(ot.get("requiere_permiso_trabajo")),
                                 key=f"ot_req_{oid}")
            emitido = c4.toggle("Permiso emitido y firmado", value=bool(ot.get("permiso_trabajo_emitido")),
                                disabled=not requiere, key=f"ot_emit_{oid}")
            descripcion = st.text_area("Descripción del trabajo", value=S.descripcion_sin_marca(ot), key=f"ot_desc_{oid}")
            c5, c6 = st.columns(2)
            nro_ot = c5.text_input("N° OT OpenOrange", value=ot.get("nro_ot_openorange") or "", key=f"ot_oo_{oid}")
            nro_oc = c6.text_input("N° OC OpenOrange", value=ot.get("nro_oc_openorange") or "", key=f"ot_oc_{oid}")

            if st.button("Guardar cambios", type="primary", key=f"ot_guardar_{oid}", use_container_width=True):
                extra = {}
                nueva_desc = S.con_marca_parada(descripcion, parada)
                if nueva_desc != (ot.get("descripcion") or ""):
                    extra["descripcion"] = nueva_desc
                if tecnico_id != ot.get("tecnico_id"):
                    extra["tecnico_id"] = tecnico_id
                if requiere != bool(ot.get("requiere_permiso_trabajo")):
                    extra["requiere_permiso_trabajo"] = requiere
                if bool(requiere and emitido) != bool(ot.get("permiso_trabajo_emitido")):
                    extra["permiso_trabajo_emitido"] = bool(requiere and emitido)
                for campo, valor in (("nro_ot_openorange", nro_ot), ("nro_oc_openorange", nro_oc)):
                    if ((valor or "").strip() or None) != (ot.get(campo) or None):
                        extra[campo] = (valor or "").strip() or None
                ot_con_cambios = {**ot, **extra}
                try:
                    if (nuevo_estado or ot.get("estado")) != ot.get("estado") or (nuevo_estado == "Bloqueada" and motivo != (ot.get("motivo_bloqueo") or "")):
                        ok, msg = S.cambiar_estado(ot_con_cambios, nuevo_estado, motivo_bloqueo=motivo, extra=extra)
                    elif extra:
                        update_ot(oid, extra)
                        S.refrescar_ots()
                        ok, msg = True, f"{ot.get('codigo')} actualizada."
                    else:
                        ok, msg = True, "No había cambios para guardar."
                except Exception as e:
                    ui.error_amigable("No se pudieron guardar los cambios.", e)
                else:
                    if ok:
                        st.session_state["ots_mensaje"] = msg
                        st.rerun()
                    else:
                        st.error(msg)

        # --- Repuestos ---
        with tabs[1]:
            repuestos = get_repuestos_cached()
            mapa_rep = {r["id"]: r for r in repuestos}
            consumos = _consumos_de(oid)
            if consumos:
                filas = []
                for c in consumos:
                    r = mapa_rep.get(c.get("repuesto_id"), {})
                    filas.append({"Repuesto": r.get("nombre", f"#{c.get('repuesto_id')}"),
                                  "Cantidad": c.get("cantidad_usada"),
                                  "Costo actual": ui.formato_gs((c.get("cantidad_usada") or 0) * (r.get("costo_unitario") or 0))})
                st.dataframe(filas, hide_index=True, use_container_width=True)
            else:
                st.caption("Todavía no se registraron repuestos en esta OT.")
            if repuestos and ot.get("estado") != "Completada":
                ids = [r["id"] for r in repuestos]
                c1, c2 = st.columns([3, 1])
                rep_id = c1.selectbox("Agregar repuesto", ids, index=None, placeholder="Buscar por código o nombre",
                                      format_func=lambda i: _etiqueta_repuesto(mapa_rep[i]), key=f"ot_rep_sel_{oid}")
                cantidad = c2.number_input("Cantidad", min_value=1, step=1, key=f"ot_rep_cant_{oid}")
                if st.button("Registrar consumo", key=f"ot_rep_btn_{oid}", disabled=rep_id is None):
                    try:
                        consumir_repuesto_seguro(oid, rep_id, cantidad)
                    except ValueError:
                        st.error(f"No hay stock suficiente de {mapa_rep[rep_id]['nombre']} en este momento.")
                    except Exception as e:
                        ui.error_amigable("No se pudo registrar el consumo.", e)
                    else:
                        S.refrescar_repuestos()
                        _refrescar_consumos()
                        st.session_state["ots_mensaje"] = f"Se descontaron {cantidad} de {mapa_rep[rep_id]['nombre']}."
                        st.rerun()

        # --- Costos (precargados con lo que ya tiene la OT: no pisa datos al revisar) ---
        with tabs[2]:
            _costos(ot, maquina, tecnicos)

        # --- Más acciones (solo admin) ---
        if admin:
            with tabs[3]:
                st.caption("Acciones excepcionales. Quedan anotadas en la descripción de la OT.")
                if ot.get("estado") != "Completada":
                    if ui.boton_confirmar("Forzar cierre", f"ot_forzar_{oid}",
                                          "Cierra la OT aunque falte el permiso o tenga bloqueo. ¿Confirmás?",
                                          texto_confirmar="Sí, forzar cierre", use_container_width=True):
                        ok, msg = S.cambiar_estado(ot, "Completada", forzar=True, usuario=usuario)
                        st.session_state["ots_mensaje"] = msg
                        st.rerun()
                if ui.boton_confirmar("Eliminar OT", f"ot_borrar_{oid}",
                                      f"Se elimina **{ot.get('codigo')}** definitivamente. No se puede deshacer.",
                                      texto_confirmar="Sí, eliminar", use_container_width=True):
                    try:
                        delete_ot(oid)
                    except Exception as e:
                        ui.error_amigable("No se pudo eliminar la OT (puede tener repuestos o costos asociados).", e)
                    else:
                        S.refrescar_ots()
                        st.session_state.pop("ot_sel_codigo", None)
                        st.session_state["ots_mensaje"] = f"{ot.get('codigo')} eliminada."
                        st.rerun()


def _costos(ot, maquina, tecnicos):
    oid = ot.get("id")
    repuestos = {r["id"]: r for r in get_repuestos_cached()}
    costo_repuestos = sum((c.get("cantidad_usada") or 0) * (repuestos.get(c.get("repuesto_id"), {}).get("costo_unitario") or 0)
                          for c in _consumos_de(oid))
    tipo = st.segmented_control("Ejecución", ["interno", "tercerizado"],
                                default=ot.get("tipo_ejecucion") if ot.get("tipo_ejecucion") in ("interno", "tercerizado") else "interno",
                                format_func=lambda x: "Interna" if x == "interno" else "Tercerizada", key=f"costo_tipo_{oid}") or "interno"

    # Parada: precargada con lo guardado; si no hay, desde que se abrió la OT hasta su cierre (o ahora)
    ini = ui.a_datetime(ot.get("fecha_inicio_parada")) or ui.a_datetime(ot.get("fecha_inicio")) or ui.ahora()
    fin = ui.a_datetime(ot.get("fecha_fin_parada")) or ui.a_datetime(ot.get("fecha_fin")) or ui.ahora()
    hubo_parada = st.toggle("Hubo parada de máquina", value=bool(ot.get("fecha_inicio_parada")) or S.es_parada(ot),
                            key=f"costo_hubo_{oid}")
    ini_dt = fin_dt = None
    if hubo_parada:
        c1, c2, c3, c4 = st.columns(4)
        f_ini = c1.date_input("Inicio de parada", value=ini.date(), format="DD/MM/YYYY", key=f"costo_fi_{oid}")
        h_ini = c2.time_input("Hora", value=ini.time().replace(second=0, microsecond=0), key=f"costo_hi_{oid}")
        f_fin = c3.date_input("Fin de parada", value=fin.date(), format="DD/MM/YYYY", key=f"costo_ff_{oid}")
        h_fin = c4.time_input("Hora ", value=fin.time().replace(second=0, microsecond=0), key=f"costo_hf_{oid}")
        ini_dt, fin_dt = datetime.combine(f_ini, h_ini), datetime.combine(f_fin, h_fin)
        if fin_dt <= ini_dt:
            st.error("El fin de la parada tiene que ser posterior al inicio.")

    proveedor_id, numero_factura, monto_factura, flete = ot.get("proveedor_id"), ot.get("numero_factura") or "", 0, 0
    horas, tecnico_id = 0.0, ot.get("tecnico_id")
    if tipo == "interno":
        tec_ids = list(tecnicos.keys())
        if not tec_ids:
            st.warning("Cargá técnicos con su costo hora-hombre en Configuración → Técnicos.")
        else:
            c1, c2 = st.columns(2)
            tecnico_id = c1.selectbox("Técnico", tec_ids, index=tec_ids.index(tecnico_id) if tecnico_id in tec_ids else 0,
                                      format_func=lambda i: f"{tecnicos[i]['nombre']} ({ui.formato_gs(tecnicos[i].get('costo_hora_hombre'))}/h)",
                                      key=f"costo_tec_{oid}")
            hh = float(tecnicos[tecnico_id].get("costo_hora_hombre") or 0)
            horas_previas = round(float(ot.get("costo_mano_obra") or 0) / hh, 1) if hh else 0.0
            horas = c2.number_input("Horas trabajadas", min_value=0.0, step=0.5, value=horas_previas, key=f"costo_horas_{oid}")
    else:
        prov = [t for t in st.session_state.get("terceros", []) if t.get("contacto")]
        mapa_prov = {t["id"]: t for t in prov}
        if not prov:
            st.warning("Cargá el proveedor primero en Almacén y compras → Terceros.")
        else:
            ids = list(mapa_prov.keys())
            proveedor_id = st.selectbox("Proveedor", ids, index=ids.index(proveedor_id) if proveedor_id in ids else 0,
                                        format_func=lambda i: f"{mapa_prov[i]['contacto']} ({mapa_prov[i].get('ruc') or 'sin RUC'})",
                                        key=f"costo_prov_{oid}")
        c1, c2, c3 = st.columns(3)
        numero_factura = c1.text_input("N° de factura", value=numero_factura, key=f"costo_nf_{oid}")
        monto_factura = c2.number_input("Monto factura (Gs.)", min_value=0, step=1000,
                                        value=int(ot.get("costo_factura_tercero") or 0), key=f"costo_mf_{oid}")
        flete = c3.number_input("Flete / logística (Gs.)", min_value=0, step=1000,
                                value=int(ot.get("costo_flete_logistica") or 0), key=f"costo_fl_{oid}")

    r = calcular_costo_ot(
        tipo_ejecucion=tipo, horas_trabajadas=horas,
        costo_hora_hombre=float(tecnicos.get(tecnico_id, {}).get("costo_hora_hombre") or 0),
        costo_repuestos=costo_repuestos, costo_factura_tercero=monto_factura, costo_flete_logistica=flete,
        fecha_inicio_parada=ini_dt, fecha_fin_parada=fin_dt,
        costo_hora_parada=maquina.get("costo_hora_parada") or 0,
    )
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Parada", f"{r['horas_parada']:.1f} h")
    m2.metric("Costo directo", ui.formato_gs(r["costo_directo"]))
    m3.metric("Lucro cesante", ui.formato_gs(r["costo_lucro_cesante"]))
    m4.metric("Total OT", ui.formato_gs(r["costo_total"]))
    if costo_repuestos:
        st.caption(f"Incluye {ui.formato_gs(costo_repuestos)} de repuestos consumidos en esta OT.")

    if st.button("Guardar costos", type="primary", key=f"costo_guardar_{oid}", use_container_width=True,
                 disabled=bool(hubo_parada and fin_dt and ini_dt and fin_dt <= ini_dt)):
        patch = {
            "tipo_ejecucion": tipo,
            "costo_lucro_cesante": r["costo_lucro_cesante"],
            "costo_total_ot": r["costo_total"],
            "horas_paro": r["horas_parada"],
            "fecha_inicio_parada": ini_dt.isoformat() if ini_dt else None,
            "fecha_fin_parada": fin_dt.isoformat() if fin_dt else None,
        }
        if tipo == "interno":
            patch["costo_mano_obra"] = r["costo_mano_obra"]
            if tecnico_id is not None:
                patch["tecnico_id"] = tecnico_id
            patch.update({"costo_factura_tercero": 0, "costo_flete_logistica": 0})
        else:
            patch.update({"proveedor_id": proveedor_id, "numero_factura": numero_factura,
                          "costo_factura_tercero": monto_factura, "costo_flete_logistica": flete, "costo_mano_obra": 0})
        try:
            update_ot(oid, patch)
        except Exception as e:
            ui.error_amigable("No se pudieron guardar los costos.", e)
        else:
            S.refrescar_ots()
            st.session_state["ots_mensaje"] = f"Costos de {ot.get('codigo')} guardados: {ui.formato_gs(r['costo_total'])}."
            st.rerun()


# ------------------------------------------------------------------
# Pantalla
# ------------------------------------------------------------------
FILTROS = ["Abiertas", "Bloqueadas", "Sin asignar", "Máquina parada", "Completadas"]


def render_ots(usuario, mostrar_titulo=True):
    if mostrar_titulo:
        ui.encabezado("Órdenes de trabajo", "Buscá una OT, tocala y actualizala en el panel de la derecha.")

    maquinas = st.session_state.get("maquinas", [])
    tecnicos = {t["id"]: t["nombre"] for t in st.session_state.get("tecnicos", [])}
    mapa_maq = {m["id"]: m for m in maquinas}
    if not maquinas:
        ui.estado_vacio("Todavía no hay máquinas cargadas.", "Cargá al menos una en Activos → Máquinas para poder crear OTs.")
        return

    mensaje = st.session_state.pop("ots_mensaje", None)
    if mensaje:
        st.toast(mensaje, icon=":material/check_circle:")
        st.success(mensaje)

    if st.session_state.pop("ots_abrir_nueva", False):
        _dialogo_nueva_ot(usuario)

    c_busq, c_maq, c_nueva = st.columns([3, 2, 1.2], vertical_alignment="bottom")
    texto = c_busq.text_input("Buscar", placeholder="Código, máquina, descripción o N° OpenOrange",
                              key="ots_buscar", label_visibility="collapsed")
    ids_maq = [None] + [m["id"] for m in sorted(maquinas, key=lambda m: str(m.get("nombre")).casefold())]
    maq_filtro = c_maq.selectbox("Máquina", ids_maq, key="ots_maquina", label_visibility="collapsed",
                                 format_func=lambda i: "Todas las máquinas" if i is None else mapa_maq[i]["nombre"])
    if c_nueva.button("+ Nueva OT", type="primary", use_container_width=True):
        _dialogo_nueva_ot(usuario)

    filtro = st.pills("Mostrar", FILTROS, default="Abiertas", key="ots_filtro", label_visibility="collapsed") or "Abiertas"

    ahora = ui.ahora()
    if filtro == "Completadas":
        if "ots_pagina" not in st.session_state:
            st.session_state.ots_pagina = 1
        lista, total = get_ots_paginado(pagina=st.session_state.ots_pagina, tamanio=25, estado="Completada")
    else:
        lista = [o for o in get_ots_cached() if o.get("estado") != "Completada"]
        if filtro == "Bloqueadas":
            lista = [o for o in lista if o.get("estado") == "Bloqueada"]
        elif filtro == "Sin asignar":
            lista = [o for o in lista if o.get("tecnico_id") is None]
        elif filtro == "Máquina parada":
            lista = [o for o in lista if S.es_parada(o)]
        total = None
    if maq_filtro is not None:
        lista = [o for o in lista if o.get("maquina_id") == maq_filtro]
    if texto:
        t = texto.casefold().strip()
        lista = [o for o in lista if t in " ".join(str(x) for x in (
            o.get("codigo"), mapa_maq.get(o.get("maquina_id"), {}).get("nombre"), o.get("descripcion"),
            o.get("nro_ot_openorange"), o.get("nro_oc_openorange"))).casefold()]
    lista = sorted(lista, key=lambda o: (not S.es_parada(o), o.get("estado") != "Bloqueada", -(o.get("id") or 0)))

    izq, der = st.columns([3, 2], gap="medium")
    with izq:
        if not lista:
            ui.estado_vacio("No hay OTs con este filtro.", "Probá con «Abiertas» o borrá la búsqueda.")
            seleccionada = None
        else:
            df = pd.DataFrame([{
                "id": o.get("id"),
                "Código": o.get("codigo"),
                "Máquina": mapa_maq.get(o.get("maquina_id"), {}).get("nombre", "—"),
                "Tipo": o.get("tipo_mantenimiento") or "—",
                "Estado": S.NOMBRE_ESTADO.get(o.get("estado"), o.get("estado")),
                "Técnico": tecnicos.get(o.get("tecnico_id"), "Sin asignar"),
                "Abierta": _antiguedad(o, ahora),
                "Alertas": _alertas(o),
            } for o in lista])
            evento = st.dataframe(
                df, hide_index=True, use_container_width=True, on_select="rerun", selection_mode="single-row",
                key="ots_tabla", column_order=["Código", "Máquina", "Tipo", "Estado", "Técnico", "Abierta", "Alertas"],
                height=min(38 + 35 * len(df), 560),
            )
            filas = evento.selection.rows if evento and evento.selection else []
            if filas and filas[0] < len(df):
                st.session_state["ot_sel_codigo"] = df.iloc[filas[0]]["Código"]
            codigo_sel = st.session_state.get("ot_sel_codigo")
            seleccionada = next((o for o in lista if o.get("codigo") == codigo_sel), None)
            if total is not None:
                paginas = max(1, -(-total // 25))
                p1, p2, p3 = st.columns([1, 2, 1])
                if p1.button("Anterior", disabled=st.session_state.ots_pagina <= 1, use_container_width=True):
                    st.session_state.ots_pagina -= 1
                    st.rerun()
                p2.caption(f"Página {st.session_state.ots_pagina} de {paginas} · {total} OTs completadas")
                if p3.button("Siguiente", disabled=st.session_state.ots_pagina >= paginas, use_container_width=True):
                    st.session_state.ots_pagina += 1
                    st.rerun()
            else:
                st.caption(f"{len(lista)} OT(s). Tocá una fila para ver y editar el detalle.")
    with der:
        if seleccionada:
            _detalle(seleccionada, usuario)
        else:
            with st.container(border=True):
                st.caption("Elegí una OT de la lista para ver el detalle, cambiar su estado, cargar repuestos o costos.")
