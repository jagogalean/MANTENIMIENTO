import html
import io
from datetime import date

import pandas as pd
import streamlit as st

from database import terceros_db as db
from database import terceros_logica as L
from database.conection import delete_tercero, get_planes, get_terceros, insert_tercero, update_plan

try:  # vínculo opcional con el módulo de comparativos de cotizaciones
    from database import cotizaciones_db as cdb
except Exception:  # pragma: no cover
    cdb = None

TIPOS_ARCHIVO = ["pdf", "png", "jpg", "jpeg"]
SIN_ASIGNAR = "— sin asignar —"
ICONO = {"alta": "🔴", "media": "🟠", "info": "ℹ️"}
COLOR_PAGO = {"Pagado": "#10B981", "Facturado, sin pagar": "#F59E0B", "Pago parcial": "#F59E0B", "Sin facturar": "#38BDF8",
              "Pagado de más": "#EF4444", "Pagos sin factura": "#EF4444"}
CAMPOS_TERCERO = {"Empresa proveedora": "contacto", "Equipo / servicio": "nombre", "RUC": "ruc", "Teléfono": "telefono",
                  "Correo": "email", "Tipo de servicio": "servicio", "Próximo vencimiento": "proximoVencimiento",
                  "Notas": "notas", "Activo": "activo"}
OBLIGATORIOS = {"contacto", "nombre"}


# ----------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------
def _esc(v):
    return html.escape(str(v)) if v not in (None, "") else "—"


def _fecha_tabla(v):
    """Fecha, Timestamp, NaT o vacío que devuelve una tabla editable -> date o None."""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return L.a_fecha(v.date() if hasattr(v, "date") and not isinstance(v, date) else v)


def _texto(v):
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except (TypeError, ValueError):
        pass
    return str(v).strip()


def etiqueta_tercero(t):
    return f"{t.get('contacto') or '—'} — {t.get('nombre') or '—'}"


def opciones_terceros(terceros):
    """[(etiqueta única, id)] — si dos registros se llaman igual, se agrega el número para distinguirlos."""
    vistos, resultado = {}, []
    for t in terceros:
        e = etiqueta_tercero(t)
        vistos[e] = vistos.get(e, 0) + 1
    usados = {}
    for t in terceros:
        e = etiqueta_tercero(t)
        if vistos[e] > 1:
            usados[e] = usados.get(e, 0) + 1
            e = f"{e} (#{t['id']})"
        resultado.append((e, t["id"]))
    return resultado


def calcular_cambios_terceros(originales: dict, editados: dict):
    """
    originales / editados: {id: {campo_de_la_base: valor}}. Devuelve [(id, parche)] solo con los campos
    que cambiaron. Los campos de texto vacíos se guardan como vacíos (None), salvo empresa y servicio, que
    son obligatorios: si quedan vacíos se devuelve (id, None) para que quien llama avise.
    """
    cambios = []
    for tid, nuevo in editados.items():
        previo = originales.get(tid, {})
        parche = {}
        for campo, valor in nuevo.items():
            if campo == "activo":
                valor = bool(valor)
            elif campo == "proximoVencimiento":
                valor = valor.isoformat() if valor else None
            else:
                valor = _texto(valor)
                if campo in OBLIGATORIOS and not valor:
                    parche = None
                    break
                valor = valor or None
            antes = previo.get(campo)
            if campo == "activo":
                antes = True if antes is None else bool(antes)
            elif campo == "proximoVencimiento":
                antes = (L.a_fecha(antes).isoformat() if L.a_fecha(antes) else None)
            else:
                antes = _texto(antes) or None
            if valor != antes:
                parche[campo] = valor
        if parche is None or parche:
            cambios.append((tid, parche))
    return cambios


def valores_por_defecto(origen, plan, ot, comparativo, mapa_maquinas):
    """Qué se completa solo en el formulario de un trabajo nuevo según su origen."""
    v = {"tercero_id": None, "maquina_id": None, "descripcion": "", "fecha": None, "moneda": "PYG", "presupuesto": 0.0,
         "factura_ot": None}
    if origen.startswith("Preventivo") and plan:
        m = mapa_maquinas.get(plan.get("maquina_id"), {})
        v.update(tercero_id=plan.get("tercero_id"), maquina_id=plan.get("maquina_id"), fecha=L.a_fecha(plan.get("proxima_ejecucion")),
                 descripcion=f"{plan.get('nombre_plan')} — {m.get('nombre') or ''}".strip(" —"),
                 presupuesto=float(plan.get("costo_estimado") or 0))
    elif origen.startswith("Correctivo") and ot:
        v.update(tercero_id=ot.get("proveedor_id"), maquina_id=ot.get("maquina_id"), fecha=L.a_fecha(ot.get("fecha_inicio")),
                 descripcion=f"{ot.get('codigo')}: {ot.get('descripcion') or ''}".strip(": "))
        if ot.get("numero_factura") or float(ot.get("costo_factura_tercero") or 0) > 0:
            v["factura_ot"] = {"numero": ot.get("numero_factura") or "", "monto": float(ot.get("costo_factura_tercero") or 0)}
    if comparativo:
        v["descripcion"] = v["descripcion"] or comparativo.get("objeto") or ""
        v["maquina_id"] = v["maquina_id"] or comparativo.get("maquina_id")
        if comparativo.get("_monto"):
            v["presupuesto"], v["moneda"] = float(comparativo["_monto"]), comparativo.get("_moneda") or "PYG"
    return v


def _formato_numero(moneda):
    return ("%.0f", 1000.0) if moneda == "PYG" else ("%.2f", 10.0)


def _preparar_subidos(archivos):
    """Achica las fotos y valida los PDF. Devuelve (lista_lista_para_subir, [errores], resumen_de_tamaño)."""
    listos, errores, antes, despues = [], [], 0.0, 0.0
    for a in archivos or []:
        r = L.preparar_archivo(a.name, a.getvalue(), getattr(a, "type", None))
        if r.get("error"):
            errores.append(r["error"])
        else:
            listos.append(r)
            antes += r["original_kb"]
            despues += r["final_kb"]
    resumen = f" (de {antes / 1024:.1f} MB a {despues / 1024:.1f} MB)" if listos and antes - despues > 100 else ""
    return listos, errores, resumen


def _refrescar_terceros():
    st.session_state.terceros = get_terceros()


# ----------------------------------------------------------------
# Pantalla
# ----------------------------------------------------------------
def render_terceros():
    st.title("🚚 Terceros y Proveedores")
    st.write("Directorio de proveedores, los trabajos que hacen para vos (preventivos y correctivos), sus facturas, pagos y archivos.")

    usuario = st.session_state.get("usuario_actual") or {}
    if usuario.get("rol") != "admin":
        st.warning("Esta pantalla está disponible solo para el administrador.")
        return

    terceros = st.session_state.get("terceros", [])
    mapa = {t["id"]: t for t in terceros}
    maquinas = st.session_state.get("maquinas", [])
    mapa_maquinas = {m["id"]: m for m in maquinas}

    try:
        trabajos, facturas, pagos, docs = db.listar_trabajos(), db.listar_facturas(), db.listar_pagos(), db.listar_documentos()
        con_trabajos = True
    except Exception:
        trabajos, facturas, pagos, docs, con_trabajos = [], [], [], [], False
        st.warning("Todavía no están creadas las tablas de trabajos, facturas y pagos. Corré el archivo SQL "
                   "`terceros_trabajos.sql` en Supabase. Mientras tanto podés usar el directorio de proveedores.")

    if con_trabajos:
        _resumen_superior(mapa, trabajos, facturas, pagos)

    tabs = st.tabs(["📒 Proveedores", "🧾 Trabajos", "🗂️ Archivos", "💳 Cuentas por pagar", "📅 Servicios programados"])
    with tabs[0]:
        _tab_proveedores(terceros, trabajos)
    with tabs[1]:
        if con_trabajos:
            _tab_trabajos(terceros, mapa, mapa_maquinas, trabajos, facturas, pagos, docs, usuario)
        else:
            st.info("Disponible después de correr el SQL.")
    with tabs[2]:
        if con_trabajos:
            _tab_archivos(mapa, trabajos, facturas, pagos, docs)
        else:
            st.info("Disponible después de correr el SQL.")
    with tabs[3]:
        if con_trabajos:
            _tab_cuentas(mapa, trabajos, facturas, pagos)
        else:
            st.info("Disponible después de correr el SQL.")
    with tabs[4]:
        _tab_servicios(terceros, mapa_maquinas, trabajos)


def _resumen_superior(mapa, trabajos, facturas, pagos):
    c = L.cuentas_por_pagar(mapa, trabajos, facturas, pagos)
    t = c["totales"]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Saldo por pagar (Gs.)", L.fmt_monto(t["PYG"]["saldo"], "PYG"))
    m2.metric("Vencido (Gs.)", L.fmt_monto(t["PYG"]["vencido"], "PYG"))
    m3.metric("Saldo por pagar (USD)", L.fmt_monto(t["USD"]["saldo"], "USD"))
    m4.metric("Facturas vencidas", len(c["vencidas"]))


# ----------------------------------------------------------------
# 1. Proveedores
# ----------------------------------------------------------------
def _tab_proveedores(terceros, trabajos):
    with st.expander("➕ Registrar proveedor / servicio"):
        with st.form("form_tercero_nuevo", clear_on_submit=True):
            c1, c2 = st.columns(2)
            contacto = c1.text_input("Empresa proveedora *", placeholder="Ej: Servicios Industriales SA")
            nombre = c2.text_input("Equipo o servicio *", placeholder="Ej: Caldera de vapor central")
            c3, c4, c5 = st.columns(3)
            ruc = c3.text_input("RUC", placeholder="Ej: 80012345-6")
            telefono = c4.text_input("Teléfono")
            email = c5.text_input("Correo")
            servicio = st.text_input("Tipo de servicio", placeholder="Ej: Calibración, mantenimiento externo")
            venc = st.date_input("Próximo vencimiento / renovación (dejalo vacío si no tiene)", value=None, format="DD/MM/YYYY")
            notas = st.text_area("Notas")
            if st.form_submit_button("Guardar proveedor"):
                if not contacto.strip() or not nombre.strip():
                    st.error("La empresa y el equipo o servicio son obligatorios.")
                elif any(_texto(t.get("contacto")).casefold() == contacto.strip().casefold()
                         and _texto(t.get("nombre")).casefold() == nombre.strip().casefold() for t in terceros):
                    st.error("Ya existe ese proveedor con ese mismo equipo o servicio.")
                else:
                    datos = {"nombre": nombre.strip(), "contacto": contacto.strip(), "ruc": ruc.strip() or None,
                             "servicio": servicio.strip() or None, "proximoVencimiento": venc.isoformat() if venc else None}
                    extra = {"telefono": telefono.strip() or None, "email": email.strip() or None, "notas": notas.strip() or None}
                    try:
                        insert_tercero({**datos, **{k: v for k, v in extra.items() if v}})
                        _refrescar_terceros()
                        st.success("Proveedor guardado.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"No se pudo guardar: {e}")

    if not terceros:
        st.info("Todavía no hay proveedores cargados.")
        return

    st.caption("Editá directamente en la tabla (doble click en una celda) y tocá «Guardar cambios». "
               "«Activo» destilda a los proveedores que ya no usás sin perder su historial.")
    filas, originales = [], {}
    for t in terceros:
        originales[t["id"]] = {c: t.get(c) for c in CAMPOS_TERCERO.values()}
        filas.append({"id": t["id"], "Empresa proveedora": t.get("contacto") or "", "Equipo / servicio": t.get("nombre") or "",
                      "RUC": t.get("ruc") or "", "Teléfono": t.get("telefono") or "", "Correo": t.get("email") or "",
                      "Tipo de servicio": t.get("servicio") or "", "Próximo vencimiento": L.a_fecha(t.get("proximoVencimiento")),
                      "Notas": t.get("notas") or "", "Activo": True if t.get("activo") is None else bool(t.get("activo"))})
    df = pd.DataFrame(filas)
    firma = f"{len(terceros)}|{st.session_state.get('terc_version', 0)}"
    editado = st.data_editor(df, key=f"terc_editor_{firma}", hide_index=True, width="stretch",
                             disabled=["id"], height=min(70 + 36 * len(df), 520),
                             column_config={"id": None, "Próximo vencimiento": st.column_config.DateColumn(format="DD/MM/YYYY"),
                                            "Activo": st.column_config.CheckboxColumn()})
    nuevos = {}
    for _, r in editado.iterrows():
        fila = {}
        for col, campo in CAMPOS_TERCERO.items():
            fila[campo] = _fecha_tabla(r[col]) if campo == "proximoVencimiento" else r[col]
        nuevos[int(r["id"])] = fila
    cambios = calcular_cambios_terceros(originales, nuevos)
    invalidos = [tid for tid, p in cambios if p is None]
    validos = [(tid, p) for tid, p in cambios if p]
    if invalidos:
        st.error("La empresa y el equipo o servicio no pueden quedar vacíos. Corregí esas filas para poder guardar.")
    if st.button(f"💾 Guardar {len(validos)} cambio(s)", disabled=not validos or bool(invalidos), type="primary", key="terc_guardar"):
        errores = 0
        for tid, parche in validos:
            try:
                db.actualizar_tercero(tid, parche)
            except Exception:
                errores += 1
        _refrescar_terceros()
        st.session_state["terc_version"] = st.session_state.get("terc_version", 0) + 1
        st.session_state["terc_flash"] = (("success", f"Se guardaron {len(validos)} cambio(s).") if not errores else
                                          ("warning", f"Se guardaron {len(validos) - errores}; {errores} fallaron (¿corriste el SQL de esta actualización?)."))
        st.rerun()
    flash = st.session_state.pop("terc_flash", None)
    if flash:
        getattr(st, flash[0])(flash[1])

    with st.expander("🗑️ Quitar un proveedor"):
        opciones = opciones_terceros(terceros)
        elegido = st.selectbox("Proveedor a quitar", [e for e, _ in opciones], key="terc_quitar_sel")
        tid = dict(opciones)[elegido]
        con_trabajos = len([t for t in trabajos if t.get("tercero_id") == tid])
        if con_trabajos:
            st.warning(f"Tiene {con_trabajos} trabajo(s) registrados, así que no se puede quitar (se perdería el historial de pagos). "
                       "Destildalo en «Activo» para dejar de usarlo.")
        elif st.checkbox("Confirmo que quiero quitarlo", key="terc_quitar_ok") and st.button("Quitar proveedor", key="terc_quitar_btn"):
            try:
                delete_tercero(tid)
                _refrescar_terceros()
                st.rerun()
            except Exception as e:
                st.error(f"No se pudo quitar: {e}")


# ----------------------------------------------------------------
# 2. Trabajos
# ----------------------------------------------------------------
def _tab_trabajos(terceros, mapa, mapa_maquinas, trabajos, facturas, pagos, docs, usuario):
    fact_por, pagos_por, docs_por = {}, {}, {}
    for f in facturas:
        fact_por.setdefault(f["trabajo_id"], []).append(f)
    for p in pagos:
        pagos_por.setdefault(p["trabajo_id"], []).append(p)
    for d in docs:
        docs_por.setdefault(d["trabajo_id"], []).append(d)

    _form_nuevo_trabajo(terceros, mapa_maquinas, usuario)

    if not trabajos:
        st.info("Todavía no hay trabajos con terceros registrados.")
        return

    resumenes = {t["id"]: L.resumen_trabajo(t, fact_por.get(t["id"], []), pagos_por.get(t["id"], []), docs_por.get(t["id"], []))
                 for t in trabajos}
    st.markdown("---")
    f1, f2, f3, f4 = st.columns(4)
    empresas = sorted({_texto(mapa.get(t["tercero_id"], {}).get("contacto")) or "Sin proveedor" for t in trabajos}, key=str.casefold)
    f_empresa = f1.selectbox("Proveedor", ["Todos"] + empresas, key="tt_f_empresa")
    f_pago = f2.selectbox("Estado de pago", ["Todos"] + L.ESTADOS_PAGO, key="tt_f_pago")
    f_estado = f3.selectbox("Estado del trabajo", ["Todos"] + L.ESTADOS_TRABAJO, key="tt_f_estado")
    f_texto = f4.text_input("Buscar", placeholder="código, equipo o descripción", key="tt_f_texto")

    def pasa(t):
        emp = _texto(mapa.get(t["tercero_id"], {}).get("contacto")) or "Sin proveedor"
        maq = mapa_maquinas.get(t.get("maquina_id"), {}).get("nombre") or ""
        pajar = f"{t.get('codigo')} {t.get('descripcion')} {maq} {emp}".casefold()
        return ((f_empresa == "Todos" or emp == f_empresa) and (f_pago == "Todos" or resumenes[t["id"]]["estado_pago"] == f_pago)
                and (f_estado == "Todos" or t.get("estado") == f_estado) and (not f_texto or f_texto.casefold() in pajar))
    visibles = [t for t in trabajos if pasa(t)]
    limite = st.selectbox("Mostrar", [15, 40, "Todos"], key="tt_limite")
    st.caption(f"{len(visibles)} trabajo(s) con estos filtros.")
    for t in (visibles if limite == "Todos" else visibles[:limite]):
        r = resumenes[t["id"]]
        tercero = mapa.get(t["tercero_id"], {})
        maq = mapa_maquinas.get(t.get("maquina_id"), {}).get("nombre")
        color = COLOR_PAGO.get(r["estado_pago"], "#7C8894")
        if any(a["nivel"] == "alta" for a in r["avisos"]):
            color = "#EF4444"
        tarjeta = (f"<div class='industrial-panel' style='border-color:{color};'>"
                   f"<strong>{_esc(t.get('codigo'))}</strong> — {_esc(tercero.get('contacto'))} · {_esc(tercero.get('nombre'))}<br>"
                   f"<small>{_esc(t.get('descripcion'))}</small><br>"
                   f"<small style='color:#7C8894;'>{_esc(t.get('origen'))} · {_esc(maq) if maq else 'sin equipo'} · "
                   f"{_esc(L.a_fecha(t.get('fecha_trabajo')).strftime('%d/%m/%Y') if L.a_fecha(t.get('fecha_trabajo')) else None)} · "
                   f"Trabajo: {_esc(t.get('estado'))}</small><br>"
                   f"<span>Presupuesto {_esc(L.fmt_monto(r['presupuesto'], r['moneda']))} · Facturado {_esc(L.fmt_monto(r['facturado'], r['moneda']))} · "
                   f"Pagado {_esc(L.fmt_monto(r['pagado'], r['moneda']))} · <strong>Saldo {_esc(L.fmt_monto(r['saldo'], r['moneda']))}</strong></span> "
                   f"<span style='color:{color}; font-weight:bold;'>· {_esc(r['estado_pago'])}</span></div>")
        st.markdown(tarjeta, unsafe_allow_html=True)
        with st.expander(f"Detalle y gestión — {t.get('codigo')}"):
            _detalle_trabajo(t, r, fact_por.get(t["id"], []), pagos_por.get(t["id"], []), docs_por.get(t["id"], []), docs, terceros, mapa_maquinas)


def _form_nuevo_trabajo(terceros, mapa_maquinas, usuario):
    with st.expander("➕ Nuevo trabajo con tercero"):
        activos = [t for t in terceros if t.get("activo") is not False]
        if not activos:
            st.info("Primero cargá al menos un proveedor activo en la pestaña «Proveedores».")
            return
        opciones = opciones_terceros(activos)
        etiquetas = [e for e, _ in opciones]
        id_por_etiqueta = dict(opciones)

        origen = st.radio("¿De dónde viene este trabajo?", ["Preventivo (de un plan)", "Correctivo (de una orden de trabajo)", "Otro"],
                          horizontal=True, key="tt_origen")
        plan = ot = comparativo = None
        if origen.startswith("Preventivo"):
            planes = st.session_state.get("planes", [])
            candidatos = [p for p in planes if p.get("tipo") == "Tercerizado"] or planes
            if not candidatos:
                st.info("No hay planes preventivos cargados.")
            else:
                mapa_terc = {t["id"]: t for t in terceros}
                etq = {f"{mapa_maquinas.get(p.get('maquina_id'), {}).get('codigo') or '?'} · {p.get('nombre_plan')}"
                       + (f" — {mapa_terc[p['tercero_id']].get('contacto')}" if p.get("tercero_id") in mapa_terc else "") + f" (#{p['id']})": p
                       for p in candidatos}
                elegido = st.selectbox("Plan", list(etq.keys()), key="tt_plan_sel")
                plan = etq[elegido]
        elif origen.startswith("Correctivo"):
            ots = list(st.session_state.get("ots", []))
            ots.sort(key=lambda o: (o.get("tipo_ejecucion") != "tercerizado", -int(o.get("id") or 0)))
            if not ots:
                st.info("No hay órdenes de trabajo cargadas.")
            else:
                etq = {f"{o.get('codigo')} · {mapa_maquinas.get(o.get('maquina_id'), {}).get('nombre') or '?'} · "
                       f"{(o.get('descripcion') or '')[:50]}" + (" · tercerizada" if o.get("tipo_ejecucion") == "tercerizado" else ""): o
                       for o in ots[:80]}
                elegido = st.selectbox("Orden de trabajo (las tercerizadas aparecen primero)", list(etq.keys()), key="tt_ot_sel")
                ot = etq[elegido]
        if cdb is not None:
            try:
                comps = cdb.listar_comparativos(limite=30)
            except Exception:
                comps = []
            if comps:
                etq_c = {SIN_ASIGNAR: None, **{f"{c['codigo']} · {c['objeto'][:50]} ({c['estado']})": c for c in comps}}
                eleg = st.selectbox("Viene de un comparativo de cotizaciones (opcional)", list(etq_c.keys()), key="tt_comp_sel")
                comparativo = etq_c[eleg]
                if comparativo and comparativo.get("proveedor_adjudicado") or (comparativo and comparativo.get("proveedor_recomendado")):
                    nombre_prov = comparativo.get("proveedor_adjudicado") or comparativo.get("proveedor_recomendado")
                    cot = next((q for q in cdb.listar_cotizaciones([comparativo["id"]]) if q.get("proveedor") == nombre_prov), None)
                    if cot:
                        comparativo = {**comparativo, "_monto": cot.get("monto"), "_moneda": cot.get("moneda")}

        d = valores_por_defecto(origen, plan, ot, comparativo, mapa_maquinas)
        firma = f"{origen[:4]}|{plan['id'] if plan else ''}|{ot['id'] if ot else ''}|{comparativo['id'] if comparativo else ''}"
        idx_prov = next((i for i, (_, tid) in enumerate(opciones) if tid == d["tercero_id"]), 0)
        maquinas_op = [SIN_ASIGNAR] + [m.get("nombre") for m in mapa_maquinas.values()]
        idx_maq = maquinas_op.index(mapa_maquinas[d["maquina_id"]]["nombre"]) if d["maquina_id"] in mapa_maquinas else 0

        with st.form(f"tt_form_nuevo_{firma}", clear_on_submit=True):
            c1, c2 = st.columns(2)
            prov = c1.selectbox("Proveedor *", etiquetas, index=idx_prov)
            maq = c2.selectbox("Equipo", maquinas_op, index=idx_maq)
            desc = st.text_area("Descripción del trabajo *", value=d["descripcion"])
            c3, c4, c5, c6 = st.columns(4)
            fecha = c3.date_input("Fecha del trabajo", value=d["fecha"], format="DD/MM/YYYY")
            estado = c4.selectbox("Estado", L.ESTADOS_TRABAJO, index=1 if origen != "Otro" else 0)
            moneda = c5.selectbox("Moneda", L.MONEDAS, index=L.MONEDAS.index(d["moneda"]),
                                  format_func=lambda m: "Guaraníes (PYG)" if m == "PYG" else "Dólares (USD)")
            presupuesto = c6.number_input("Presupuesto", min_value=0.0, step=1000.0, value=float(d["presupuesto"]), format="%.2f")
            obs = st.text_input("Observaciones")
            cargar_factura = False
            if d["factura_ot"]:
                cargar_factura = st.checkbox(f"Cargar también la factura que ya tiene la orden de trabajo "
                                             f"({d['factura_ot']['numero'] or 's/n'} — {L.fmt_monto(d['factura_ot']['monto'], moneda)})", value=True)
            fotos = st.file_uploader("Presupuestos del proveedor (foto o PDF, opcional)", type=TIPOS_ARCHIVO, accept_multiple_files=True)
            if st.form_submit_button("Guardar trabajo", type="primary"):
                if not desc.strip():
                    st.error("Escribí una descripción del trabajo.")
                else:
                    listos, errores, resumen = _preparar_subidos(fotos)
                    if errores:
                        st.error(" ".join(errores))
                    else:
                        try:
                            datos = {"codigo": db.generar_codigo_trabajo(), "tercero_id": id_por_etiqueta[prov], "origen": origen.split(" ")[0],
                                     "plan_id": plan["id"] if plan else None, "ot_id": ot["id"] if ot else None,
                                     "maquina_id": next((m["id"] for m in mapa_maquinas.values() if m.get("nombre") == maq), None),
                                     "descripcion": desc.strip(), "fecha_trabajo": fecha.isoformat() if fecha else None, "estado": estado,
                                     "moneda": moneda, "monto_presupuesto": presupuesto, "observaciones": obs.strip() or None,
                                     "creado_por": usuario.get("nombre")}
                            if comparativo:
                                datos["comparativo_id"] = comparativo["id"]
                            trabajo = db.insertar_trabajo(datos)
                            avisos = []
                            if listos:
                                _, errs = db.adjuntar_archivos(trabajo["id"], "Presupuesto", listos)
                                avisos += errs
                            if cargar_factura and d["factura_ot"] and d["factura_ot"]["monto"] > 0:
                                db.insertar_factura({"trabajo_id": trabajo["id"], "numero": d["factura_ot"]["numero"] or None,
                                                     "fecha_factura": date.today().isoformat(), "monto": d["factura_ot"]["monto"]})
                            st.session_state["tt_flash"] = ("success", f"Trabajo {trabajo['codigo']} guardado{resumen}."
                                                            + (" ⚠️ " + " ".join(avisos) if avisos else ""))
                            st.rerun()
                        except Exception as e:
                            st.error(f"No se pudo guardar el trabajo: {e}")
    flash = st.session_state.pop("tt_flash", None)
    if flash:
        getattr(st, flash[0])(flash[1])


def _detalle_trabajo(t, r, facturas_t, pagos_t, docs_t, todos_docs, terceros, mapa_maquinas):
    tid, moneda = t["id"], t["moneda"]
    fm = lambda v: L.fmt_monto(v, moneda)
    fmt_num, paso = _formato_numero(moneda)
    k = lambda s: f"tt{tid}_{s}"

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Presupuesto", fm(r["presupuesto"]))
    m2.metric("Facturado", fm(r["facturado"]))
    m3.metric("Pagado", fm(r["pagado"]))
    m4.metric("Saldo", fm(r["saldo"]))
    for a in r["avisos"]:
        st.markdown(f"{ICONO[a['nivel']]} {a['texto']}")

    # ---------- Archivos ----------
    st.markdown("##### 📎 Archivos")
    if docs_t:
        if st.button("🔗 Ver los archivos (enlaces válidos 1 hora)", key=k("ver")):
            enlaces = {}
            for d in docs_t:
                try:
                    enlaces[d["id"]] = db.url_firmada(d["archivo_path"])
                except Exception:
                    enlaces[d["id"]] = None
            st.session_state[k("links")] = enlaces
        enlaces = st.session_state.get(k("links"), {})
        num_fact = {f["id"]: f.get("numero") or "s/n" for f in facturas_t}
        fecha_pago = {p["id"]: L.a_fecha(p.get("fecha_pago")) for p in pagos_t}
        for d in docs_t:
            extra = ""
            if d.get("factura_id") in num_fact:
                extra = f" · factura {num_fact[d['factura_id']]}"
            elif d.get("pago_id") in fecha_pago and fecha_pago[d["pago_id"]]:
                extra = f" · pago del {fecha_pago[d['pago_id']]:%d/%m/%Y}"
            c_a, c_b = st.columns([0.88, 0.12])
            url = enlaces.get(d["id"])
            c_a.markdown(f"• **{d['tipo']}**{extra} — " + (f"[{d.get('archivo_nombre')}]({url})" if url else str(d.get("archivo_nombre"))))
            if c_b.button("🗑️", key=k(f"deldoc{d['id']}"), help="Quitar este archivo"):
                db.quitar_documento(d)
                st.rerun()
            if url and str(d.get("archivo_nombre", "")).lower().endswith((".jpg", ".jpeg", ".png")):
                st.image(url, width=260)
    else:
        st.caption("Todavía no hay archivos cargados en este trabajo.")
    with st.form(k("form_docs"), clear_on_submit=True):
        c1, c2 = st.columns([0.3, 0.7])
        tipo = c1.selectbox("Tipo", ["Presupuesto", "Informe del proveedor", "Otro"], key=k("doc_tipo"))
        nuevos = c2.file_uploader("Subir presupuestos, informes u otros (foto o PDF)", type=TIPOS_ARCHIVO, accept_multiple_files=True, key=k("up_docs"))
        if st.form_submit_button("Subir archivos", key=k("btn_docs")) and nuevos:
            listos, errores, resumen = _preparar_subidos(nuevos)
            if errores:
                st.error(" ".join(errores))
            else:
                n, errs = db.adjuntar_archivos(tid, tipo, listos)
                st.session_state["tt_flash"] = ("success" if not errs else "warning", f"{n} archivo(s) subido(s){resumen}." + (" " + " ".join(errs) if errs else ""))
                st.rerun()

    # ---------- Facturas ----------
    st.markdown("##### 🧾 Facturas")
    saldo_por = {x["factura_id"]: x for x in r["por_factura"]}
    for f in facturas_t:
        s = saldo_por.get(f["id"], {})
        venc = L.a_fecha(f.get("fecha_vencimiento"))
        pagada = "✅ pagada" if s.get("saldo", 0) <= L.TOLERANCIA else f"saldo {fm(s.get('saldo', 0))}"
        st.markdown(f"• **{f.get('numero') or 's/n'}** · {L.a_fecha(f.get('fecha_factura')) or '—'} · {fm(f['monto'])} · "
                    f"vence {venc.strftime('%d/%m/%Y') if venc else '—'} · {pagada}")
        with st.expander(f"✏️ Editar / quitar la factura {f.get('numero') or 's/n'}"):
            with st.form(k(f"form_fact{f['id']}")):
                a1, a2, a3, a4 = st.columns(4)
                num = a1.text_input("Número", value=f.get("numero") or "")
                fec = a2.date_input("Fecha", value=L.a_fecha(f.get("fecha_factura")), format="DD/MM/YYYY")
                mon = a3.number_input("Monto", min_value=0.0, step=paso, value=float(f["monto"]), format=fmt_num)
                ven = a4.date_input("Vencimiento de pago", value=venc, format="DD/MM/YYYY")
                if st.form_submit_button("Guardar cambios") :
                    if mon <= 0:
                        st.error("El monto debe ser mayor a cero.")
                    else:
                        db.actualizar_factura(f["id"], {"numero": num.strip() or None, "fecha_factura": fec.isoformat() if fec else None,
                                                        "monto": mon, "fecha_vencimiento": ven.isoformat() if ven else None})
                        st.rerun()
            if st.checkbox("Confirmo que quiero quitar esta factura y sus archivos", key=k(f"okf{f['id']}")) and st.button("🗑️ Quitar factura", key=k(f"delf{f['id']}")):
                db.borrar_factura_completa(f["id"], todos_docs)
                st.rerun()
    with st.form(k("form_nueva_factura"), clear_on_submit=True):
        st.markdown("**Agregar factura**")
        a1, a2, a3, a4 = st.columns(4)
        num = a1.text_input("Número", placeholder="001-001-0000123", key=k("nf_num"))
        fec = a2.date_input("Fecha", value=date.today(), format="DD/MM/YYYY", key=k("nf_fecha"))
        mon = a3.number_input("Monto", min_value=0.0, step=paso, format=fmt_num, key=k("nf_monto"))
        ven = a4.date_input("Vencimiento de pago", value=None, format="DD/MM/YYYY", key=k("nf_ven"))
        fotos = st.file_uploader("Foto o PDF de la factura", type=TIPOS_ARCHIVO, accept_multiple_files=True, key=k("up_fact"))
        if st.form_submit_button("Guardar factura", key=k("btn_fact")):
            if mon <= 0:
                st.error("Indicá el monto de la factura.")
            else:
                listos, errores, resumen = _preparar_subidos(fotos)
                if errores:
                    st.error(" ".join(errores))
                else:
                    fila = db.insertar_factura({"trabajo_id": tid, "numero": num.strip() or None, "fecha_factura": fec.isoformat() if fec else None,
                                                "monto": mon, "fecha_vencimiento": ven.isoformat() if ven else None})
                    errs = db.adjuntar_archivos(tid, "Factura", listos, factura_id=fila["id"])[1] if listos else []
                    st.session_state["tt_flash"] = ("success" if not errs else "warning", f"Factura guardada{resumen}." + (" " + " ".join(errs) if errs else ""))
                    st.rerun()

    # ---------- Pagos ----------
    st.markdown("##### 💳 Pagos")
    num_fact = {f["id"]: f.get("numero") or "s/n" for f in facturas_t}
    for p in pagos_t:
        fp = L.a_fecha(p.get("fecha_pago"))
        st.markdown(f"• **{fp.strftime('%d/%m/%Y') if fp else '—'}** · {fm(p['monto'])} · {p.get('medio') or '—'}"
                    + (f" · ref. {p.get('referencia')}" if p.get("referencia") else "")
                    + (f" · factura {num_fact[p['factura_id']]}" if p.get("factura_id") in num_fact else ""))
        with st.expander(f"✏️ Editar / quitar el pago del {fp.strftime('%d/%m/%Y') if fp else '—'}"):
            with st.form(k(f"form_pago{p['id']}")):
                b1, b2, b3, b4 = st.columns(4)
                fec = b1.date_input("Fecha", value=fp, format="DD/MM/YYYY")
                mon = b2.number_input("Monto", min_value=0.0, step=paso, value=float(p["monto"]), format=fmt_num)
                medio = b3.selectbox("Medio", L.MEDIOS_PAGO, index=L.MEDIOS_PAGO.index(p.get("medio")) if p.get("medio") in L.MEDIOS_PAGO else 0)
                ref = b4.text_input("Referencia", value=p.get("referencia") or "")
                if st.form_submit_button("Guardar cambios"):
                    if mon <= 0 or not fec:
                        st.error("Indicá la fecha y un monto mayor a cero.")
                    else:
                        db.actualizar_pago(p["id"], {"fecha_pago": fec.isoformat(), "monto": mon, "medio": medio, "referencia": ref.strip() or None})
                        st.rerun()
            if st.checkbox("Confirmo que quiero quitar este pago y sus comprobantes", key=k(f"okp{p['id']}")) and st.button("🗑️ Quitar pago", key=k(f"delp{p['id']}")):
                db.borrar_pago_completo(p["id"], todos_docs)
                st.rerun()
    with st.form(k("form_nuevo_pago"), clear_on_submit=True):
        st.markdown("**Registrar pago**")
        b1, b2, b3, b4 = st.columns(4)
        fec = b1.date_input("Fecha del pago", value=date.today(), format="DD/MM/YYYY", key=k("np_fecha"))
        mon = b2.number_input("Monto pagado", min_value=0.0, step=paso, format=fmt_num, key=k("np_monto"))
        medio = b3.selectbox("Medio", L.MEDIOS_PAGO, key=k("np_medio"))
        ref = b4.text_input("Referencia / N° de operación", key=k("np_ref"))
        opciones_f = [SIN_ASIGNAR] + [f"{f.get('numero') or 's/n'} ({fm(f['monto'])})" for f in facturas_t]
        fact_sel = st.selectbox("¿A qué factura corresponde? (opcional)", opciones_f, key=k("np_fact"))
        fotos = st.file_uploader("Comprobante del pago (foto o PDF)", type=TIPOS_ARCHIVO, accept_multiple_files=True, key=k("up_pago"))
        if st.form_submit_button("Guardar pago", key=k("btn_pago")):
            if mon <= 0 or not fec:
                st.error("Indicá la fecha y el monto del pago.")
            else:
                listos, errores, resumen = _preparar_subidos(fotos)
                if errores:
                    st.error(" ".join(errores))
                else:
                    fid = facturas_t[opciones_f.index(fact_sel) - 1]["id"] if fact_sel != SIN_ASIGNAR else None
                    fila = db.insertar_pago({"trabajo_id": tid, "factura_id": fid, "fecha_pago": fec.isoformat(), "monto": mon,
                                             "medio": medio, "referencia": ref.strip() or None})
                    errs = db.adjuntar_archivos(tid, "Comprobante de pago", listos, pago_id=fila["id"])[1] if listos else []
                    nuevo = r["pagado"] + mon
                    exceso = nuevo - r["facturado"] > L.TOLERANCIA and r["facturado"] > 0
                    st.session_state["tt_flash"] = ("warning" if (errs or exceso) else "success",
                                                    f"Pago guardado{resumen}." + (" Ojo: con este pago superás lo facturado." if exceso else "")
                                                    + (" " + " ".join(errs) if errs else ""))
                    st.rerun()

    # ---------- Datos del trabajo ----------
    st.markdown("##### ✏️ Datos del trabajo")
    with st.form(k("form_datos")):
        c1, c2, c3 = st.columns(3)
        estado = c1.selectbox("Estado", L.ESTADOS_TRABAJO, index=L.ESTADOS_TRABAJO.index(t["estado"]) if t.get("estado") in L.ESTADOS_TRABAJO else 0)
        fecha = c2.date_input("Fecha del trabajo", value=L.a_fecha(t.get("fecha_trabajo")), format="DD/MM/YYYY")
        bloqueada = bool(facturas_t or pagos_t)
        mon_sel = c3.selectbox("Moneda", L.MONEDAS, index=L.MONEDAS.index(moneda), disabled=bloqueada,
                               help="No se puede cambiar si ya hay facturas o pagos cargados." if bloqueada else None)
        desc = st.text_area("Descripción", value=t.get("descripcion") or "")
        c4, c5 = st.columns(2)
        pres = c4.number_input("Presupuesto", min_value=0.0, step=paso, value=float(t.get("monto_presupuesto") or 0), format=fmt_num)
        obs = c5.text_input("Observaciones", value=t.get("observaciones") or "")
        if st.form_submit_button("Guardar cambios del trabajo"):
            if not desc.strip():
                st.error("La descripción no puede quedar vacía.")
            else:
                db.actualizar_trabajo(tid, {"estado": estado, "fecha_trabajo": fecha.isoformat() if fecha else None, "moneda": mon_sel,
                                            "descripcion": desc.strip(), "monto_presupuesto": pres, "observaciones": obs.strip() or None})
                st.rerun()
    with st.expander("🗑️ Eliminar este trabajo"):
        st.caption("Se borran también sus facturas, pagos y archivos. No se puede deshacer.")
        if st.checkbox("Confirmo que quiero eliminar el trabajo completo", key=k("okdel")) and st.button("Eliminar trabajo", key=k("del")):
            db.borrar_trabajo_completo(tid, todos_docs)
            st.rerun()


# ----------------------------------------------------------------
# 3. Archivos (todos los presupuestos, facturas y comprobantes juntos)
# ----------------------------------------------------------------
ARCHIVOS_POR_PAGINA = 12
ICONO_TIPO = {"Presupuesto": "📝", "Factura": "🧾", "Comprobante de pago": "💳", "Informe del proveedor": "📋", "Otro": "📎"}


def filtrar_documentos(docs, trabajos_por_id, mapa, empresa="Todos", tipo="Todos", trabajo="Todos", texto="", desde=None, hasta=None):
    """Documentos más nuevos primero, filtrados por proveedor, tipo, trabajo, texto (nombre del archivo o descripción) y fechas."""
    palabras = str(texto or "").casefold().split()
    resultado = []
    for d in sorted(docs, key=lambda x: x["id"], reverse=True):
        t = trabajos_por_id.get(d["trabajo_id"], {})
        emp = _texto(mapa.get(t.get("tercero_id"), {}).get("contacto")) or "Sin proveedor"
        if empresa != "Todos" and emp != empresa:
            continue
        if tipo != "Todos" and d.get("tipo") != tipo:
            continue
        if trabajo != "Todos" and t.get("codigo") != trabajo:
            continue
        subido = L.a_fecha(d.get("fecha_subida"))
        if desde and (not subido or subido < desde):
            continue
        if hasta and (not subido or subido > hasta):
            continue
        pajar = f"{d.get('archivo_nombre')} {t.get('descripcion')} {t.get('codigo')} {emp}".casefold()
        if all(p in pajar for p in palabras):
            resultado.append(d)
    return resultado


def _tab_archivos(mapa, trabajos, facturas, pagos, docs):
    if not docs:
        st.info("Todavía no hay archivos cargados. Los presupuestos, facturas y comprobantes que subas en cada trabajo aparecen acá.")
        return
    trabajos_por_id = {t["id"]: t for t in trabajos}
    num_fact = {f["id"]: f.get("numero") or "s/n" for f in facturas}
    fecha_pago = {p["id"]: L.a_fecha(p.get("fecha_pago")) for p in pagos}
    conteo = {}
    for d in docs:
        conteo[d["tipo"]] = conteo.get(d["tipo"], 0) + 1
    st.caption(f"{len(docs)} archivo(s) en total · " + " · ".join(f"{ICONO_TIPO.get(k, '')} {k}: {v}" for k, v in sorted(conteo.items())))

    f1, f2, f3, f4 = st.columns(4)
    empresas = sorted({_texto(mapa.get(t["tercero_id"], {}).get("contacto")) or "Sin proveedor" for t in trabajos}, key=str.casefold)
    f_emp = f1.selectbox("Proveedor", ["Todos"] + empresas, key="arch_f_emp")
    f_tipo = f2.selectbox("Tipo", ["Todos"] + L.TIPOS_DOC, key="arch_f_tipo")
    f_trab = f3.selectbox("Trabajo", ["Todos"] + sorted({t["codigo"] for t in trabajos if t.get("codigo")}, reverse=True), key="arch_f_trab")
    f_txt = f4.text_input("Buscar", placeholder="nombre del archivo o descripción", key="arch_f_txt")
    g1, g2 = st.columns(2)
    f_desde = g1.date_input("Subidos desde", value=None, format="DD/MM/YYYY", key="arch_f_desde")
    f_hasta = g2.date_input("Subidos hasta", value=None, format="DD/MM/YYYY", key="arch_f_hasta")

    resultado = filtrar_documentos(docs, trabajos_por_id, mapa, f_emp, f_tipo, f_trab, f_txt, f_desde, f_hasta)
    if not resultado:
        st.warning("No hay archivos con esos filtros.")
        return
    paginas = max(1, -(-len(resultado) // ARCHIVOS_POR_PAGINA))
    pagina = int(st.number_input(f"Página (de {paginas})", min_value=1, max_value=paginas, value=1, step=1, key="arch_pagina")) if paginas > 1 else 1
    visibles = resultado[(pagina - 1) * ARCHIVOS_POR_PAGINA: pagina * ARCHIVOS_POR_PAGINA]
    st.caption(f"{len(resultado)} archivo(s) con estos filtros · mostrando {len(visibles)}")

    clave = "arch_links"
    if st.button("🖼️ Cargar vistas previas y enlaces de esta página (válidos 1 hora)", key="arch_ver"):
        enlaces = {}
        for d in visibles:
            try:
                enlaces[d["id"]] = db.url_firmada(d["archivo_path"])
            except Exception:
                enlaces[d["id"]] = None
        st.session_state[clave] = enlaces
    enlaces = st.session_state.get(clave, {})

    for fila in range(0, len(visibles), 4):
        cols = st.columns(4)
        for col, d in zip(cols, visibles[fila:fila + 4]):
            t = trabajos_por_id.get(d["trabajo_id"], {})
            emp = _texto(mapa.get(t.get("tercero_id"), {}).get("contacto")) or "Sin proveedor"
            detalle = ""
            if d.get("factura_id") in num_fact:
                detalle = f" · factura {num_fact[d['factura_id']]}"
            elif fecha_pago.get(d.get("pago_id")):
                detalle = f" · pago del {fecha_pago[d['pago_id']]:%d/%m/%Y}"
            subido = L.a_fecha(d.get("fecha_subida"))
            nombre = str(d.get("archivo_nombre") or "")
            url = enlaces.get(d["id"])
            with col:
                if url and nombre.lower().endswith((".jpg", ".jpeg", ".png")):
                    st.image(url, width=220)
                elif url:
                    st.markdown(f"[📄 Abrir PDF]({url})")
                else:
                    st.markdown(f"<div style='font-size:2.2rem; text-align:center;'>{'📄' if nombre.lower().endswith('.pdf') else '🖼️'}</div>", unsafe_allow_html=True)
                st.markdown(f"**{ICONO_TIPO.get(d['tipo'], '')} {d['tipo']}**{detalle}")
                st.caption(f"{emp} · {t.get('codigo') or '—'}" + (f" · {subido:%d/%m/%Y}" if subido else ""))
                if url:
                    st.markdown(f"[{nombre}]({url})")
                else:
                    st.caption(nombre)


# ----------------------------------------------------------------
# 4. Cuentas por pagar
# ----------------------------------------------------------------
def _tab_cuentas(mapa, trabajos, facturas, pagos):
    c = L.cuentas_por_pagar(mapa, trabajos, facturas, pagos)
    if not c["filas"]:
        st.info("Todavía no hay trabajos para mostrar cuentas.")
        return
    st.caption("Los trabajos cancelados no cuentan. Guaraníes y dólares se muestran por separado: nunca se suman entre sí.")
    st.dataframe(pd.DataFrame([{
        "Proveedor": f["empresa"], "Moneda": f["moneda"], "Trabajos": f["trabajos"],
        "Presupuestado": L.fmt_monto(f["presupuesto"], f["moneda"]), "Facturado": L.fmt_monto(f["facturado"], f["moneda"]),
        "Pagado": L.fmt_monto(f["pagado"], f["moneda"]), "Saldo": L.fmt_monto(f["saldo"], f["moneda"]),
        "Vencido": L.fmt_monto(f["vencido"], f["moneda"]),
    } for f in c["filas"]]), hide_index=True, width="stretch")

    if c["vencidas"]:
        st.markdown("##### 🔴 Facturas vencidas sin pagar")
        st.dataframe(pd.DataFrame([{
            "Proveedor": v["empresa"], "Trabajo": v["trabajo"], "Factura": v["factura"] or "s/n", "Venció": f"{v['vencimiento']:%d/%m/%Y}",
            "Días de atraso": v["dias"], "Saldo": L.fmt_monto(v["saldo"], v["moneda"]),
        } for v in c["vencidas"]]), hide_index=True, width="stretch")
    if c["sin_factura"]:
        st.markdown("##### 🟠 Trabajos realizados que todavía no tienen factura")
        st.dataframe(pd.DataFrame([{
            "Proveedor": s["empresa"], "Trabajo": s["trabajo"], "Descripción": s["descripcion"],
            "Presupuesto": L.fmt_monto(s["presupuesto"], s["moneda"]),
        } for s in c["sin_factura"]]), hide_index=True, width="stretch")

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame(c["filas"]).rename(columns={"empresa": "Proveedor", "moneda": "Moneda", "trabajos": "Trabajos", "presupuesto": "Presupuestado",
                                                 "facturado": "Facturado", "pagado": "Pagado", "saldo": "Saldo", "vencido": "Vencido"}
                                        ).to_excel(writer, index=False, sheet_name="Cuentas por proveedor")
        if c["vencidas"]:
            pd.DataFrame(c["vencidas"]).to_excel(writer, index=False, sheet_name="Facturas vencidas")
    st.download_button("⬇️ Descargar estado de cuentas (Excel)", data=buffer.getvalue(), file_name="cuentas_por_pagar_terceros.xlsx", key="dl_cuentas",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ----------------------------------------------------------------
# 5. Servicios programados (planes tercerizados)
# ----------------------------------------------------------------
def _tab_servicios(terceros, mapa_maquinas, trabajos):
    planes = [p for p in st.session_state.get("planes", []) if p.get("tipo") == "Tercerizado"]
    if not planes:
        st.info("No hay planes preventivos tercerizados. Cuando los cargues, acá asignás qué proveedor hace cada uno. "
                "Las fechas se manejan en «📆 Programación de Preventivos».")
        return
    activos = [t for t in terceros if t.get("activo") is not False]
    opciones = opciones_terceros(activos)
    etiqueta_por_id = {tid: e for e, tid in opciones}
    st.caption("Estos son los planes marcados como «Tercerizado». Elegí qué proveedor hace cada uno; la fecha de cada servicio "
               "se maneja en «📆 Programación de Preventivos» (no hace falta cargarla dos veces).")
    conteo = {}
    for t in trabajos:
        if t.get("plan_id"):
            conteo[t["plan_id"]] = conteo.get(t["plan_id"], 0) + 1
    planes.sort(key=lambda p: (L.a_fecha(p.get("proxima_ejecucion")) or date.max, p.get("id")))
    original = {p["id"]: etiqueta_por_id.get(p.get("tercero_id"), SIN_ASIGNAR) for p in planes}
    df = pd.DataFrame([{
        "id": p["id"], "Equipo": mapa_maquinas.get(p.get("maquina_id"), {}).get("codigo") or "?", "Plan": p.get("nombre_plan"),
        "Cada (días)": p.get("frecuencia_dias"),
        "Próxima ejecución": (L.a_fecha(p.get("proxima_ejecucion")).strftime("%d/%m/%Y") if L.a_fecha(p.get("proxima_ejecucion")) else "sin fecha"),
        "Trabajos registrados": conteo.get(p["id"], 0), "Proveedor": original[p["id"]],
    } for p in planes])
    firma = f"{len(planes)}|{st.session_state.get('serv_version', 0)}"
    editado = st.data_editor(df, key=f"serv_editor_{firma}", hide_index=True, width="stretch",
                             disabled=[c for c in df.columns if c != "Proveedor"],
                             column_config={"id": None, "Proveedor": st.column_config.SelectboxColumn(options=[SIN_ASIGNAR] + [e for e, _ in opciones])})
    id_por_etiqueta = dict(opciones)
    cambios = [(int(r["id"]), id_por_etiqueta.get(r["Proveedor"])) for _, r in editado.iterrows()
               if r["Proveedor"] != original[int(r["id"])]]
    if st.button(f"💾 Guardar {len(cambios)} asignación(es)", disabled=not cambios, type="primary", key="serv_guardar"):
        errores = 0
        for pid, tercero_id in cambios:
            try:
                update_plan(pid, {"tercero_id": tercero_id})
            except Exception:
                errores += 1
        st.session_state.planes = get_planes()
        st.session_state["serv_version"] = st.session_state.get("serv_version", 0) + 1
        st.session_state["serv_flash"] = (("success", f"Se guardaron {len(cambios)} asignación(es).") if not errores else
                                          ("warning", f"{errores} no se pudieron guardar (¿corriste el SQL?)."))
        st.rerun()
    flash = st.session_state.pop("serv_flash", None)
    if flash:
        getattr(st, flash[0])(flash[1])
