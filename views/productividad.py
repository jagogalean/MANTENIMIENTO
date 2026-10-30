import html
import io
from datetime import date, time, timedelta

import pandas as pd
import streamlit as st

from database import productividad_db as db
from database import productividad_logica as P

PRESETS = {
    "06:00 a 14:30": (time(6, 0), time(14, 30)), "14:30 a 22:30": (time(14, 30), time(22, 30)), "22:30 a 06:00": (time(22, 30), time(6, 0)),
    "06:00 a 18:00": (time(6, 0), time(18, 0)), "18:00 a 06:00": (time(18, 0), time(6, 0)),
}
SIN_FAMILIA = "— sin familia —"
PERIODOS = ["Este mes", "Mes anterior", "Últimos 90 días", "Este año", "Todo", "Elegir fechas"]


# ----------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------
def _n(v):
    try:
        if v is None or pd.isna(v):
            return 0.0
    except (TypeError, ValueError):
        pass
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _vacio(v):
    if v is None:
        return True
    try:
        if pd.isna(v):
            return True
    except (TypeError, ValueError):
        pass
    return isinstance(v, str) and not v.strip()


def _txt(v):
    return "" if _vacio(v) else str(v).strip()


def _hora(v):
    if _vacio(v):
        return None
    return P.a_hora(v)


def _fmt(v, dec=1, suf=""):
    if v is None:
        return "—"
    return f"{v:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".") + suf


def _esc(v):
    return html.escape(str(v)) if v not in (None, "") else "—"


def filas_desde_df(df, columnas):
    """
    Pasa lo que devuelve una tabla editable a una lista de dicts. columnas: {nombre_en_pantalla: clave}.
    Las filas completamente vacías se descartan (la tabla siempre trae una fila en blanco para agregar).
    """
    filas = []
    if df is None:
        return filas
    for _, r in df.iterrows():
        fila = {clave: r.get(col) for col, clave in columnas.items()}
        if all(_vacio(v) or (isinstance(v, (int, float)) and _n(v) == 0) for v in fila.values()):
            continue
        filas.append(fila)
    return filas


def _clave(clave, campo):
    return f"pt_{clave}_{st.session_state.get('prod_form_v', 0)}_{campo}"


def _invalidar(todo=True):
    st.session_state["prod_datos_v"] = st.session_state.get("prod_datos_v", 0) + 1
    st.session_state["prod_form_v"] = st.session_state.get("prod_form_v", 0) + 1
    if todo:
        st.session_state["prod_cat_v"] = st.session_state.get("prod_cat_v", 0) + 1


@st.cache_data(ttl=60, show_spinner=False)
def _catalogos_cache(version):
    return db.listar_catalogo(), db.listar_familias()


@st.cache_data(ttl=60, show_spinner=False)
def _periodo_cache(desde, hasta, version):
    return db.listar_todo(P.a_fecha(desde), P.a_fecha(hasta))


def armar_catalogos(items, familias):
    """Listas activas para los desplegables, más las categorías de cada tipo de falla."""
    act = lambda tipo: [i for i in items if i["tipo"] == tipo and i.get("activo") is not False]
    return {
        "operadores": [i["nombre"] for i in act("operador")],
        "tipos_falla": [i["nombre"] for i in act("tipo_falla")],
        "categoria_falla": {i["nombre"]: i.get("categoria") for i in items if i["tipo"] == "tipo_falla"},
        "sistemas": [i["nombre"] for i in act("sistema_falla")],
        "tipos_setup": [i["nombre"] for i in act("tipo_setup")],
        "motivos": [i["nombre"] for i in act("motivo_rechazo")],
        "familias": {f["codigo"]: f for f in familias if f.get("activo") is not False},
        "familias_todas": {f["codigo"]: f for f in familias},
    }


def _rango_periodo(opcion, hoy, d1=None, d2=None):
    if opcion == "Este mes":
        return hoy.replace(day=1), hoy
    if opcion == "Mes anterior":
        fin = hoy.replace(day=1) - timedelta(days=1)
        return fin.replace(day=1), fin
    if opcion == "Últimos 90 días":
        return hoy - timedelta(days=90), hoy
    if opcion == "Este año":
        return date(hoy.year, 1, 1), hoy
    if opcion == "Elegir fechas":
        return d1, d2
    return None, None


# ----------------------------------------------------------------
# Pantalla
# ----------------------------------------------------------------
def render_productividad(usuario):
    st.title("🏭 Productividad")
    if not P.puede_ver(usuario):
        st.warning("No tenés acceso a esta pantalla.")
        return
    try:
        items, familias = _catalogos_cache(st.session_state.get("prod_cat_v", 0))
    except Exception:
        st.warning("Todavía no están creadas las tablas de Productividad. Corré en Supabase los archivos "
                   "`productividad.sql` y `productividad_catalogos.sql`.")
        return
    cat = armar_catalogos(items, familias)

    secciones = []
    if P.puede_cargar(usuario):
        secciones.append("📝 Cargar turno")
    secciones += ["📋 Registros", "📊 Indicadores"]
    if P.puede_administrar(usuario):
        secciones.append("⚙️ Catálogos")
    if not P.puede_cargar(usuario):
        st.caption("Tu usuario puede ver los registros y los indicadores. La carga la hace logística.")
    seccion = st.radio("Sección", secciones, horizontal=True, label_visibility="collapsed", key="prod_seccion")
    flash = st.session_state.pop("prod_flash", None)
    if flash:
        getattr(st, flash[0])(flash[1])

    if seccion.startswith("📝"):
        _seccion_cargar(usuario, cat)
    elif seccion.startswith("📋"):
        _seccion_registros(usuario, cat)
    elif seccion.startswith("📊"):
        _seccion_indicadores(usuario)
    else:
        _seccion_catalogos(cat, items, familias)


# ----------------------------------------------------------------
# Formulario de un registro (sirve para cargar uno nuevo y para editar uno existente)
# ----------------------------------------------------------------
def _df_setups(filas=None):
    cols = {"Tipo de setup": "object", "Inicio": "object", "Fin": "object", "Scrap (kg)": "float64", "Observaciones": "object"}
    if not filas:
        return pd.DataFrame({c: pd.Series(dtype=t) for c, t in cols.items()})
    return pd.DataFrame([{"Tipo de setup": f.get("tipo"), "Inicio": f["inicio"].time(), "Fin": f["fin"].time(),
                          "Scrap (kg)": float(f.get("scrap_kg") or 0), "Observaciones": f.get("observaciones") or ""} for f in filas])


def _df_paradas(filas=None):
    cols = {"Tipo de falla": "object", "Sistema": "object", "Inicio": "object", "Fin": "object", "Detalle": "object"}
    if not filas:
        return pd.DataFrame({c: pd.Series(dtype=t) for c, t in cols.items()})
    return pd.DataFrame([{"Tipo de falla": f.get("tipo_falla"), "Sistema": f.get("sistema"), "Inicio": f["inicio"].time(), "Fin": f["fin"].time(),
                          "Detalle": f.get("detalle") or ""} for f in filas])


def _df_rechazos(filas=None):
    cols = {"Kg": "float64", "Motivo": "object"}
    if not filas:
        return pd.DataFrame({c: pd.Series(dtype=t) for c, t in cols.items()})
    return pd.DataFrame([{"Kg": float(f.get("kg") or 0), "Motivo": f.get("motivo")} for f in filas])


def _formulario(usuario, cat, clave, existente=None):
    """existente: registro enriquecido (ver productividad_logica.enriquecer) o None para uno nuevo."""
    t = existente or {}
    editando = existente is not None
    k = lambda campo: _clave(clave, campo)

    # --- Horario: las horas se guardan en el estado para poder aplicar un turno habitual con un click
    k_ini, k_fin = k("hini"), k("hfin")
    if k_ini not in st.session_state:
        st.session_state[k_ini] = P.a_hora(t.get("hora_inicio")) or time(6, 0)
        st.session_state[k_fin] = P.a_hora(t.get("hora_fin")) or time(14, 30)

    def aplicar_preset():
        p = PRESETS.get(st.session_state.get(k("preset")))
        if p:
            st.session_state[k_ini], st.session_state[k_fin] = p

    c1, c2, c3, c4 = st.columns([1.2, 1, 1, 1.4])
    fecha = c1.date_input("Fecha en que EMPIEZA el turno", value=P.a_fecha(t.get("fecha")) or P.hoy_paraguay(), format="DD/MM/YYYY", key=k("fecha"))
    h_ini = c2.time_input("Hora de inicio", key=k_ini, step=300)
    h_fin = c3.time_input("Hora de fin", key=k_fin, step=300)
    c4.selectbox("Turno habitual (completa las horas)", ["Elegir…"] + list(PRESETS), key=k("preset"), on_change=aplicar_preset)
    if h_ini != h_fin:
        i, f = P.limites_turno(fecha, h_ini, h_fin)
        st.caption(f"Duración del turno: **{P.horas(f - i):.1f} h**" + (" (termina al día siguiente)" if f.date() != i.date() else ""))

    c5, c6, c7 = st.columns(3)
    operadores = list(cat["operadores"])
    if t.get("operador") and t["operador"] not in operadores:
        operadores.append(t["operador"])
    operador = c5.selectbox("Operador *", operadores or ["(cargá operadores en Catálogos)"],
                            index=operadores.index(t["operador"]) if t.get("operador") in operadores else 0, key=k("operador"))
    op = c6.text_input("N° de OP *", value=str(t.get("op") or ""), key=k("op"))
    item = c7.text_input("Item (opcional)", value=t.get("item") or "", key=k("item"))

    c8, c9, c10, c11 = st.columns([2, 1, 1, 1])
    producto = c8.text_input("Producto", value=t.get("producto") or "", placeholder="Ej: FILM LAMINA 960X85 PA BCO", key=k("producto"))
    ancho = c9.number_input("Ancho (cm)", min_value=0.0, step=1.0, value=float(t.get("ancho_cm") or 0), key=k("ancho"))
    espesor = c10.number_input("Espesor (µm)", min_value=0.0, step=1.0, value=float(t.get("espesor_um") or 0), key=k("espesor"))
    densidad = c11.number_input("Densidad", min_value=0.01, step=0.01, value=float(t.get("densidad") or P.DENSIDAD_DEFECTO), format="%.2f", key=k("densidad"),
                                help="0,92 por defecto (la del Excel). Cambiala si el material es otro.")

    codigos = list(cat["familias"])
    if t.get("familia") and t["familia"] not in codigos:
        codigos.append(t["familia"])
    c12, c13, c14 = st.columns([1, 1, 1])
    familia = c12.selectbox("Familia del producto", [SIN_FAMILIA] + codigos, index=(codigos.index(t["familia"]) + 1) if t.get("familia") in codigos else 0, key=k("familia"))
    fam = cat["familias_todas"].get(familia, {}) if familia != SIN_FAMILIA else {}
    if fam:
        c13.caption(f"Máquina: **{fam.get('maquina') or '—'}**")
        c14.caption(f"{fam.get('barrera') or '—'} · {fam.get('color') or '—'}")
    c15, c16 = st.columns(2)
    kg = c15.number_input("Kilos producidos (kg)", min_value=0.0, step=10.0, value=float(t.get("kg_producidos") or 0), key=k("kg"))
    refile = c16.number_input("Scrap por refile (kg)", min_value=0.0, step=1.0, value=float(t.get("scrap_refile_kg") or 0), key=k("refile"))
    obs = st.text_input("Observaciones", value=t.get("observaciones") or "", key=k("obs"))

    # --- Listas: setups, paradas y rechazos (tantos como haya)
    st.markdown("**🔧 Preparaciones (setups)** — agregá una fila por cada una")
    ed_s = st.data_editor(_df_setups(t.get("setups")), num_rows="dynamic", hide_index=True, width="stretch", key=k("setups"), column_config={
        "Tipo de setup": st.column_config.SelectboxColumn(options=cat["tipos_setup"]),
        "Inicio": st.column_config.TimeColumn(format="HH:mm", step=60), "Fin": st.column_config.TimeColumn(format="HH:mm", step=60),
        "Scrap (kg)": st.column_config.NumberColumn(min_value=0.0, format="%.1f")})
    st.markdown("**⛔ Paradas / fallas** — una fila por cada parada")
    ed_p = st.data_editor(_df_paradas(t.get("paradas")), num_rows="dynamic", hide_index=True, width="stretch", key=k("paradas"), column_config={
        "Tipo de falla": st.column_config.SelectboxColumn(options=cat["tipos_falla"]),
        "Sistema": st.column_config.SelectboxColumn(options=cat["sistemas"]),
        "Inicio": st.column_config.TimeColumn(format="HH:mm", step=60), "Fin": st.column_config.TimeColumn(format="HH:mm", step=60)})
    st.markdown("**🗑️ Kilos rechazados**")
    ed_r = st.data_editor(_df_rechazos(t.get("rechazos")), num_rows="dynamic", hide_index=True, width="stretch", key=k("rechazos"), column_config={
        "Kg": st.column_config.NumberColumn(min_value=0.0, format="%.1f"), "Motivo": st.column_config.SelectboxColumn(options=cat["motivos"])})

    # --- Qué se está cargando, en vivo
    setups = filas_desde_df(ed_s, {"Tipo de setup": "tipo", "Inicio": "hora_inicio", "Fin": "hora_fin", "Scrap (kg)": "scrap_kg", "Observaciones": "observaciones"})
    paradas = filas_desde_df(ed_p, {"Tipo de falla": "tipo_falla", "Sistema": "sistema", "Inicio": "hora_inicio", "Fin": "hora_fin", "Detalle": "detalle"})
    rechazos = filas_desde_df(ed_r, {"Kg": "kg", "Motivo": "motivo"})
    for lista in (setups, paradas):
        for f in lista:
            f["hora_inicio"], f["hora_fin"] = _hora(f.get("hora_inicio")), _hora(f.get("hora_fin"))
            for c in ("tipo", "tipo_falla", "sistema", "observaciones", "detalle"):
                if c in f:
                    f[c] = _txt(f[c]) or None
    for f in setups:
        f["scrap_kg"] = _n(f.get("scrap_kg"))
    for f in rechazos:
        f["kg"], f["motivo"] = _n(f.get("kg")), _txt(f.get("motivo")) or None
    turno = {"fecha": fecha, "hora_inicio": h_ini, "hora_fin": h_fin, "op": op.strip(), "item": item.strip(), "operador": operador,
             "producto": producto.strip(), "ancho_cm": ancho or None, "espesor_um": espesor or None, "densidad": densidad,
             "familia": None if familia == SIN_FAMILIA else familia, "maquina": fam.get("maquina"), "barrera": fam.get("barrera"),
             "color": fam.get("color"), "kg_producidos": kg, "scrap_refile_kg": refile, "observaciones": obs.strip()}
    ev = P.evaluar_formulario(turno, setups, paradas, rechazos, cat["categoria_falla"])
    errores = list(ev["errores"])
    if not op.strip():
        errores.append("Falta el número de OP.")
    if not operadores or operador.startswith("("):
        errores.append("No hay operadores cargados: agregalos en Catálogos o con «Agregar operador o familia».")

    _resumen_vivo(ev["calculo"])
    for e in errores:
        st.error(e)
    for a in ev["avisos"]:
        st.warning(a)

    guardar = st.button("💾 Guardar cambios" if editando else "💾 Guardar turno", type="primary", disabled=bool(errores), key=k("guardar"))
    if guardar:
        try:
            existentes = db.listar_turnos(fecha - timedelta(days=1), fecha + timedelta(days=1))
            pisados = P.solapa_con(turno, existentes, ignorar_id=t.get("id"))
        except Exception as e:
            st.error(f"No se pudo verificar si el horario se superpone con otro registro: {e}")
            return
        if pisados:
            x = pisados[0]
            st.error(f"{operador} ya tiene cargado otro registro que se superpone: OP {x.get('op')}, {P.a_fecha(x.get('fecha')):%d/%m/%Y} "
                     f"de {P.a_hora(x.get('hora_inicio')):%H:%M} a {P.a_hora(x.get('hora_fin')):%H:%M}. Editá ese registro en «📋 Registros» o corregí el horario.")
            return
        try:
            payload = db.construir_payload(turno, ev, rechazos, usuario, turno_id=t.get("id"))
            db.guardar_turno(payload)
        except Exception as e:
            st.error(f"No se pudo guardar: {e}")
            return
        _invalidar(todo=False)
        st.session_state["prod_flash"] = ("success", f"✅ Turno guardado: OP {op.strip()}, {operador}, {fecha:%d/%m/%Y}.")
        st.rerun()
    return turno


def _resumen_vivo(c):
    if not c:
        return
    m = st.columns(7)
    m[0].metric("Horas del turno", _fmt(c["horas_turno"], 1))
    m[1].metric("Setup", _fmt(c["h_setup"], 1, " h"))
    m[2].metric("Paradas", _fmt(c["h_parada"], 1, " h"))
    m[3].metric("Producción neta", _fmt(c["h_prod"], 1, " h"))
    m[4].metric("kg por hora", _fmt(c["kg_h"], 0))
    m[5].metric("Metros lineales", _fmt(c["metros"], 0))
    m[6].metric("Scrap total", _fmt(c["pct_scrap"], 1, " %"), help=f"{_fmt(c['scrap_total'], 1)} kg: setup + refile + rechazos")


def _seccion_cargar(usuario, cat):
    st.write("Cargá un tramo de trabajo: un operador, en una OP, durante un horario. Si cambia la OP a mitad del turno, cargá un registro por cada una.")
    with st.expander("➕ Agregar operador o familia que no está en la lista"):
        a1, a2 = st.columns(2)
        with a1.form("prod_form_operador", clear_on_submit=True):
            nombre = st.text_input("Nombre del operador")
            if st.form_submit_button("Agregar operador"):
                if not nombre.strip():
                    st.error("Escribí el nombre.")
                elif nombre.strip().casefold() in [o.casefold() for o in cat["operadores"]]:
                    st.error("Ese operador ya existe.")
                else:
                    db.insertar_catalogo({"tipo": "operador", "nombre": nombre.strip(), "activo": True, "orden": len(cat["operadores"]) + 1})
                    _invalidar()
                    st.rerun()
        with a2.form("prod_form_familia", clear_on_submit=True):
            codigo = st.text_input("Código de la familia", placeholder="Ej: M45")
            f1, f2, f3 = st.columns(3)
            maquina = f1.text_input("Máquina", placeholder="MONO / RFH")
            barrera = f2.text_input("Barrera", placeholder="Barrera / Sin Barrera")
            color = f3.text_input("Color", placeholder="Cristal / Blanco")
            if st.form_submit_button("Agregar familia"):
                if not codigo.strip():
                    st.error("Escribí el código.")
                elif codigo.strip().casefold() in [c.casefold() for c in cat["familias_todas"]]:
                    st.error("Esa familia ya existe.")
                else:
                    db.insertar_familia({"codigo": codigo.strip(), "maquina": maquina.strip() or None, "barrera": barrera.strip() or None, "color": color.strip() or None})
                    _invalidar()
                    st.rerun()
    _formulario(usuario, cat, "n")


# ----------------------------------------------------------------
# Período y datos (compartido por Registros e Indicadores)
# ----------------------------------------------------------------
def _elegir_periodo(clave):
    hoy = P.hoy_paraguay()
    c1, c2, c3 = st.columns([1.2, 1, 1])
    opcion = c1.selectbox("Período", PERIODOS, key=f"prod_per_{clave}")
    d1 = d2 = None
    if opcion == "Elegir fechas":
        d1 = c2.date_input("Desde", value=hoy.replace(day=1), format="DD/MM/YYYY", key=f"prod_d1_{clave}")
        d2 = c3.date_input("Hasta", value=hoy, format="DD/MM/YYYY", key=f"prod_d2_{clave}")
    desde, hasta = _rango_periodo(opcion, hoy, d1, d2)
    return desde, hasta, opcion


def _cargar_datos(desde, hasta):
    try:
        turnos, setups, paradas, rechazos = _periodo_cache(desde.isoformat() if desde else None, hasta.isoformat() if hasta else None,
                                                         st.session_state.get("prod_datos_v", 0))
    except Exception as e:
        st.error(f"No se pudieron leer los registros: {e}")
        return []
    return P.enriquecer(turnos, setups, paradas, rechazos)


# ----------------------------------------------------------------
# Registros
# ----------------------------------------------------------------
def _fila_registro(t):
    c = t["calculo"]
    return {"Fecha": t["inicio"].strftime("%d/%m/%Y"), "Inicio": t["inicio"].strftime("%H:%M"), "Fin": t["fin"].strftime("%H:%M"), "OP": t.get("op"),
            "Operador": t.get("operador"), "Producto": t.get("producto"), "Familia": t.get("familia"), "Máquina": t.get("maquina"),
            "Kg": c["kg"], "Metros lineales": round(c["metros"]), "Horas turno": c["horas_turno"], "Horas setup": c["h_setup"],
            "Horas parada": c["h_parada"], "Horas producción": c["h_prod"], "kg/h": round(c["kg_h"], 1) if c["kg_h"] else None,
            "Scrap total (kg)": round(c["scrap_total"], 1), "% scrap": round(c["pct_scrap"], 1) if c["pct_scrap"] is not None else None,
            "Cargó": t.get("creado_por")}


def _excel_registros(enr):
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as w:
        pd.DataFrame([_fila_registro(t) for t in enr]).to_excel(w, index=False, sheet_name="Registros")
        pd.DataFrame([{"OP": t.get("op"), "Operador": t.get("operador"), "Fecha": t["inicio"].strftime("%d/%m/%Y"), "Tipo": s.get("tipo"),
                       "Inicio": s["inicio"].strftime("%d/%m %H:%M"), "Fin": s["fin"].strftime("%d/%m %H:%M"),
                       "Horas": P.horas(s["fin"] - s["inicio"]), "Scrap (kg)": s.get("scrap_kg")} for t in enr for s in t["setups"]]
                     ).to_excel(w, index=False, sheet_name="Setups")
        pd.DataFrame([{"OP": t.get("op"), "Operador": t.get("operador"), "Fecha": t["inicio"].strftime("%d/%m/%Y"), "Tipo de falla": p.get("tipo_falla"),
                       "Categoría": p.get("categoria"), "Sistema": p.get("sistema"), "Detalle": p.get("detalle"), "Inicio": p["inicio"].strftime("%d/%m %H:%M"),
                       "Fin": p["fin"].strftime("%d/%m %H:%M"), "Horas": P.horas(p["fin"] - p["inicio"])} for t in enr for p in t["paradas"]]
                     ).to_excel(w, index=False, sheet_name="Paradas")
        pd.DataFrame([{"OP": t.get("op"), "Operador": t.get("operador"), "Fecha": t["inicio"].strftime("%d/%m/%Y"), "Kg": r.get("kg"), "Motivo": r.get("motivo")}
                      for t in enr for r in t["rechazos"]]).to_excel(w, index=False, sheet_name="Rechazos")
    return buffer.getvalue()


def _seccion_registros(usuario, cat):
    desde, hasta, _ = _elegir_periodo("reg")
    enr = _cargar_datos(desde, hasta)
    f1, f2, f3 = st.columns(3)
    operadores = sorted({t.get("operador") for t in enr if t.get("operador")}, key=str.casefold)
    f_op = f1.selectbox("Operador", ["Todos"] + operadores, key="prod_reg_operador")
    f_texto = f2.text_input("Buscar", placeholder="OP, producto o familia", key="prod_reg_texto")
    limite = f3.selectbox("Mostrar", [25, 60, "Todos"], key="prod_reg_limite")
    visibles = [t for t in enr if (f_op == "Todos" or t.get("operador") == f_op)
                and (not f_texto or f_texto.casefold() in f"{t.get('op')} {t.get('producto')} {t.get('familia')}".casefold())]
    visibles.sort(key=lambda t: t["inicio"], reverse=True)
    if not visibles:
        st.info("No hay registros en este período con esos filtros.")
        return
    st.caption(f"{len(visibles)} registro(s).")
    st.download_button("⬇️ Descargar a Excel (registros, setups, paradas y rechazos)", data=_excel_registros(visibles), key="prod_dl_reg",
                       file_name="productividad_registros.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    mostrados = visibles if limite == "Todos" else visibles[:limite]
    st.dataframe(pd.DataFrame([_fila_registro(t) for t in mostrados]), hide_index=True, width="stretch")
    etiquetas = {f"OP {t.get('op')} · {t.get('operador')} · {t['inicio']:%d/%m/%Y %H:%M} (#{t['id']})": t for t in mostrados}
    sel = st.selectbox("Abrir un registro para ver o editar", ["— elegí uno —"] + list(etiquetas), key="prod_reg_sel")
    t = etiquetas.get(sel)
    if not t:
        return
    st.markdown("---")
    if P.puede_cargar(usuario):
        st.markdown(f"**✏️ Editando: OP {t.get('op')} · {t.get('operador')}** — cargó {t.get('creado_por') or '—'}"
                    + (f", modificó {t.get('modificado_por')}" if t.get("modificado_por") else ""))
        _formulario(usuario, cat, f"e{t['id']}", existente=t)
        if P.puede_borrar(usuario, t):
            if st.checkbox("Confirmo que quiero borrar este registro completo", key=f"prod_okdel_{t['id']}") and st.button("🗑️ Borrar registro", key=f"prod_del_{t['id']}"):
                db.borrar_turno(t["id"])
                _invalidar(todo=False)
                st.session_state["prod_flash"] = ("success", "Registro borrado.")
                st.rerun()
    else:
        _detalle_solo_lectura(t)


def _detalle_solo_lectura(t):
    c = t["calculo"]
    _resumen_vivo(c)
    if t["setups"]:
        st.markdown("**Setups**")
        st.dataframe(pd.DataFrame([{"Tipo": s.get("tipo"), "Inicio": f"{s['inicio']:%H:%M}", "Fin": f"{s['fin']:%H:%M}", "Scrap (kg)": s.get("scrap_kg")} for s in t["setups"]]),
                     hide_index=True, width="stretch")
    if t["paradas"]:
        st.markdown("**Paradas**")
        st.dataframe(pd.DataFrame([{"Tipo": p.get("tipo_falla"), "Sistema": p.get("sistema"), "Inicio": f"{p['inicio']:%H:%M}", "Fin": f"{p['fin']:%H:%M}",
                                    "Detalle": p.get("detalle")} for p in t["paradas"]]), hide_index=True, width="stretch")
    if t["rechazos"]:
        st.markdown("**Rechazos**")
        st.dataframe(pd.DataFrame([{"Kg": r.get("kg"), "Motivo": r.get("motivo")} for r in t["rechazos"]]), hide_index=True, width="stretch")
    if t.get("observaciones"):
        st.caption(f"Observaciones: {t['observaciones']}")
    st.caption(f"Cargó: {t.get('creado_por') or '—'}")


# ----------------------------------------------------------------
# Indicadores
# ----------------------------------------------------------------
def _grafico(df, x, y, horizontal=True):
    try:
        st.bar_chart(df, x=x, y=y, horizontal=horizontal, height=max(180, 28 * len(df)) if horizontal else 260)
    except TypeError:
        st.bar_chart(df.set_index(x)[y])


def _seccion_indicadores(usuario):
    desde, hasta, opcion = _elegir_periodo("ind")
    enr = _cargar_datos(desde, hasta)
    if not enr:
        st.info("No hay registros en este período.")
        return
    f1, f2, f3 = st.columns(3)
    f_op = f1.multiselect("Operadores", sorted({t.get("operador") for t in enr if t.get("operador")}, key=str.casefold), key="prod_ind_operador")
    f_fam = f2.multiselect("Familias", sorted({t.get("familia") for t in enr if t.get("familia")}), key="prod_ind_familia")
    f_maq = f3.multiselect("Máquina", sorted({t.get("maquina") for t in enr if t.get("maquina")}), key="prod_ind_maquina")
    enr = [t for t in enr if (not f_op or t.get("operador") in f_op) and (not f_fam or t.get("familia") in f_fam) and (not f_maq or t.get("maquina") in f_maq)]
    if not enr:
        st.info("No hay registros con esos filtros.")
        return
    kp = P.kpis(enr)
    a = st.columns(5)
    a[0].metric("Registros", kp["tramos"])
    a[1].metric("Horas de turno", _fmt(kp["horas_turno"], 1))
    a[2].metric("Producción neta", _fmt(kp["pct_prod"], 1, " %"))
    a[3].metric("Setup", _fmt(kp["pct_setup"], 1, " %"))
    a[4].metric("Paradas", _fmt(kp["pct_parada"], 1, " %"))
    b = st.columns(5)
    b[0].metric("Kg producidos", _fmt(kp["kg"], 0))
    b[1].metric("kg por hora", _fmt(kp["kg_h"], 0), help="Kilos ÷ horas de producción neta (sin setup ni paradas)")
    b[2].metric("Metros lineales", _fmt(kp["metros"], 0))
    b[3].metric("Scrap total (kg)", _fmt(kp["scrap_total"], 0))
    b[4].metric("% scrap", _fmt(kp["pct_scrap"], 1, " %"), help="Scrap ÷ (kilos producidos + scrap). Scrap = setup + refile + rechazos.")

    t_par, t_prod, t_scrap, t_setup, t_evol = st.tabs(["⛔ Paradas", "🏭 Producción", "🗑️ Scrap y rechazos", "🔧 Setup", "📈 Evolución"])
    with t_par:
        cats = st.multiselect("Categorías de parada", P.CATEGORIAS_PARADA, default=P.CATEGORIAS_PARADA, key="prod_ind_cats",
                              help="Técnica = fallas de mantenimiento. No programada = domingo, feriado, falta de materia prima, de ventas o de personal.")
        sel = cats or None
        for titulo, por, top in (("Por causa (tipo de falla)", "tipo_falla", None), ("Por sistema", "sistema", 15)):
            filas = P.pareto(enr, por=por, categorias=sel, top=top)
            st.markdown(f"**{titulo}**")
            if not filas:
                st.caption("Sin paradas en este período.")
                continue
            df = pd.DataFrame([{"Causa" if por == "tipo_falla" else "Sistema": f["clave"], "Horas": f["horas"], "Paradas": f["cantidad"],
                                "% del total": f["pct"], "% acumulado": f["acumulado"]} for f in filas])
            _grafico(df, df.columns[0], "Horas")
            st.dataframe(df, hide_index=True, width="stretch")
    with t_prod:
        campo = st.selectbox("Agrupar por", ["Operador", "Familia", "OP", "Producto", "Máquina"], key="prod_ind_grupo")
        filas = P.por_grupo(enr, {"Operador": "operador", "Familia": "familia", "OP": "op", "Producto": "producto", "Máquina": "maquina"}[campo])
        df = pd.DataFrame([{campo: f["clave"], "Registros": f["tramos"], "Horas de producción": f["h_prod"], "Kg": f["kg"], "kg/h": f["kg_h"], "% scrap": f["pct_scrap"]} for f in filas])
        if not df.dropna(subset=["kg/h"]).empty:
            _grafico(df.dropna(subset=["kg/h"]), campo, "kg/h")
        st.dataframe(df, hide_index=True, width="stretch")
    with t_scrap:
        filas = P.scrap_por_motivo(enr)
        st.markdown("**De dónde sale el scrap**")
        df = pd.DataFrame([{"Origen": f["clave"], "Kg": f["kg"], "% del scrap": f["pct"]} for f in filas])
        _grafico(df, "Origen", "Kg")
        st.dataframe(df, hide_index=True, width="stretch")
        st.markdown("**% de scrap por familia**")
        fam = pd.DataFrame([{"Familia": f["clave"], "Kg producidos": f["kg"], "% scrap": f["pct_scrap"]} for f in P.por_grupo(enr, "familia")])
        st.dataframe(fam, hide_index=True, width="stretch")
    with t_setup:
        filas = P.setup_por_tipo(enr)
        if not filas:
            st.caption("Sin setups en este período.")
        else:
            df = pd.DataFrame([{"Tipo de setup": f["clave"], "Cantidad": f["cantidad"], "Horas totales": f["horas"], "Horas promedio": f["horas_prom"],
                                "Scrap total (kg)": f["scrap"], "Scrap promedio (kg)": f["scrap_prom"]} for f in filas])
            _grafico(df, "Tipo de setup", "Horas promedio")
            st.dataframe(df, hide_index=True, width="stretch")
    with t_evol:
        filas = P.evolucion_mensual(enr)
        df = pd.DataFrame([{"Mes": f["mes"], "Registros": f["tramos"], "Horas de turno": f["h_turno"], "Horas de producción": f["h_prod"], "Horas de setup": f["h_setup"],
                            "Horas de parada": f["h_parada"], "Kg": f["kg"], "kg/h": f["kg_h"], "% scrap": f["pct_scrap"]} for f in filas])
        if len(df) > 1:
            _grafico(df, "Mes", "kg/h", horizontal=False)
        st.dataframe(df, hide_index=True, width="stretch")


# ----------------------------------------------------------------
# Catálogos (solo administrador)
# ----------------------------------------------------------------
def _seccion_catalogos(cat, items, familias):
    st.write("Las listas que aparecen en los desplegables. Cambiar un nombre acá **no** cambia los registros ya cargados (guardan el texto de cuando se cargaron).")
    opciones = list(P.TIPOS_CATALOGO.items()) + [("familia", "Familias de producto")]
    nombre_tipo = st.radio("Catálogo", [n for _, n in opciones], horizontal=True, key="prod_cat_sel")
    tipo = next(t for t, n in opciones if n == nombre_tipo)
    if tipo == "familia":
        _catalogo_familias(familias)
    else:
        _catalogo_simple(tipo, nombre_tipo, items)


def _catalogo_simple(tipo, titulo, items):
    propios = [i for i in items if i["tipo"] == tipo]
    con_categoria = tipo == "tipo_falla"
    with st.expander(f"➕ Agregar a «{titulo}»"):
        with st.form(f"prod_alta_{tipo}", clear_on_submit=True):
            nombre = st.text_input("Nombre")
            categoria = st.selectbox("Categoría", P.CATEGORIAS_PARADA) if con_categoria else None
            if st.form_submit_button("Agregar"):
                if not nombre.strip():
                    st.error("Escribí el nombre.")
                elif nombre.strip().casefold() in [i["nombre"].casefold() for i in propios]:
                    st.error("Ya existe.")
                else:
                    db.insertar_catalogo({"tipo": tipo, "nombre": nombre.strip(), "categoria": categoria, "activo": True,
                                          "orden": max([i.get("orden") or 0 for i in propios] + [0]) + 1})
                    _invalidar()
                    st.rerun()
    mostrar = st.radio("Mostrar", ["Activos", "Inactivos", "Todos"], horizontal=True, key=f"prod_cat_ver_{tipo}")
    vista = [i for i in propios if mostrar == "Todos" or (mostrar == "Activos") == (i.get("activo") is not False)]
    if not vista:
        st.info("No hay elementos con ese filtro.")
        return
    columnas = {"id": [i["id"] for i in vista], "Nombre": [i["nombre"] for i in vista]}
    if con_categoria:
        columnas["Categoría"] = [i.get("categoria") or P.CATEGORIAS_PARADA[0] for i in vista]
    columnas["Activo"] = [i.get("activo") is not False for i in vista]
    df = pd.DataFrame(columnas)
    cfg = {"id": None, "Activo": st.column_config.CheckboxColumn()}
    if con_categoria:
        cfg["Categoría"] = st.column_config.SelectboxColumn(options=P.CATEGORIAS_PARADA)
    firma = f"{tipo}|{mostrar}|{st.session_state.get('prod_cat_v', 0)}"
    ed = st.data_editor(df, hide_index=True, width="stretch", disabled=["id"], column_config=cfg, key=f"prod_cat_ed_{firma}",
                        height=min(80 + 36 * len(df), 520))
    por_id = {i["id"]: i for i in vista}
    cambios = []
    for _, r in ed.iterrows():
        i = por_id[int(r["id"])]
        parche = {}
        if _txt(r["Nombre"]) and _txt(r["Nombre"]) != i["nombre"]:
            parche["nombre"] = _txt(r["Nombre"])
        if con_categoria and r["Categoría"] != (i.get("categoria") or P.CATEGORIAS_PARADA[0]):
            parche["categoria"] = r["Categoría"]
        if bool(r["Activo"]) != (i.get("activo") is not False):
            parche["activo"] = bool(r["Activo"])
        if parche:
            cambios.append((i["id"], parche))
    if st.button(f"💾 Guardar {len(cambios)} cambio(s)", disabled=not cambios, type="primary", key=f"prod_cat_guardar_{tipo}"):
        errores = 0
        for item_id, parche in cambios:
            try:
                db.actualizar_catalogo(item_id, parche)
            except Exception:
                errores += 1
        _invalidar()
        st.session_state["prod_flash"] = (("success", f"Se guardaron {len(cambios)} cambio(s).") if not errores else ("warning", f"{errores} no se pudieron guardar (¿nombre repetido?)."))
        st.rerun()


def _catalogo_familias(familias):
    with st.expander("➕ Agregar familia"):
        with st.form("prod_alta_familia", clear_on_submit=True):
            codigo = st.text_input("Código", placeholder="Ej: M45")
            a, b, c = st.columns(3)
            maquina, barrera, color = a.text_input("Máquina"), b.text_input("Barrera"), c.text_input("Color")
            if st.form_submit_button("Agregar"):
                if not codigo.strip():
                    st.error("Escribí el código.")
                elif codigo.strip().casefold() in [f["codigo"].casefold() for f in familias]:
                    st.error("Esa familia ya existe.")
                else:
                    db.insertar_familia({"codigo": codigo.strip(), "maquina": maquina.strip() or None, "barrera": barrera.strip() or None, "color": color.strip() or None})
                    _invalidar()
                    st.rerun()
    df = pd.DataFrame([{"id": f["id"], "Código": f["codigo"], "Máquina": f.get("maquina") or "", "Barrera": f.get("barrera") or "", "Color": f.get("color") or "",
                        "Activa": f.get("activo") is not False} for f in familias])
    if df.empty:
        st.info("Todavía no hay familias.")
        return
    ed = st.data_editor(df, hide_index=True, width="stretch", disabled=["id"], column_config={"id": None, "Activa": st.column_config.CheckboxColumn()},
                        key=f"prod_fam_ed_{st.session_state.get('prod_cat_v', 0)}", height=min(80 + 36 * len(df), 520))
    por_id = {f["id"]: f for f in familias}
    cambios = []
    for _, r in ed.iterrows():
        f = por_id[int(r["id"])]
        parche = {}
        for col, campo in (("Código", "codigo"), ("Máquina", "maquina"), ("Barrera", "barrera"), ("Color", "color")):
            nuevo = _txt(r[col]) or None
            if campo == "codigo" and not nuevo:
                continue
            if nuevo != (f.get(campo) or None):
                parche[campo] = nuevo
        if bool(r["Activa"]) != (f.get("activo") is not False):
            parche["activo"] = bool(r["Activa"])
        if parche:
            cambios.append((f["id"], parche))
    if st.button(f"💾 Guardar {len(cambios)} cambio(s)", disabled=not cambios, type="primary", key="prod_fam_guardar"):
        errores = 0
        for fid, parche in cambios:
            try:
                db.actualizar_familia(fid, parche)
            except Exception:
                errores += 1
        _invalidar()
        st.session_state["prod_flash"] = (("success", f"Se guardaron {len(cambios)} cambio(s).") if not errores else ("warning", f"{errores} no se pudieron guardar (¿código repetido?)."))
        st.rerun()
