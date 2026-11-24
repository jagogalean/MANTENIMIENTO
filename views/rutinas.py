import random
from datetime import timedelta

import pandas as pd
import streamlit as st

from database import excel_marca as M
from database import rutinas_db as db
from database import rutinas_excel as RX
from database import rutinas_logica as R

TIPOS_PUNTO = {"OK / No OK": "ok", "Valor medido": "numero"}
TIPO_A_TEXTO = {v: k for k, v in TIPOS_PUNTO.items()}
TIPOS_FOTO = {"Paso del paso a paso": "paso", "Así debe verse (OK)": "ok", "Así NO debe verse (mal)": "mal"}
CONDICIONES = ["En marcha", "Parada programada", "Parada + LOTO"]
GENERAL = "General (no es de un paso)"
PERIODOS = ["Últimos 7 días", "Últimos 30 días", "Este mes", "Elegir fechas"]


def _v():
    return st.session_state.get("rut_v", 0)


def _invalidar():
    st.session_state["rut_v"] = _v() + 1


def _flash(tipo, texto):
    st.session_state["rut_flash"] = (tipo, texto)


@st.cache_data(ttl=30, show_spinner=False)
def _cargar_config(version):
    return {"zonas": db.listar_zonas(), "items": db.listar_items(), "puntos": db.listar_puntos(), "pasos": db.listar_pasos(),
            "fotos": db.listar_fotos(), "operadores": db.listar_operadores()}


AVISO_CLAVE = ("la app no tiene permiso para escribir en las tablas de rutinas. En Streamlit → Settings → Secrets, "
               "SUPABASE_KEY tiene que ser la clave **secreta** de Supabase (service_role o sb_secret_…), no la pública (anon o sb_publishable_…). "
               "Cambiala, guardá y reiniciá la app.")


def _es_permiso(e):
    texto = str(e)
    return "42501" in texto or "row-level security" in texto or "permission denied" in texto or "Unauthorized" in texto


def _motivo(e):
    """El error de Supabase traducido: si es de permisos (RLS), dice qué hacer."""
    return AVISO_CLAVE if _es_permiso(e) else str(e)


def _mostrar_error(titulo, e):
    st.warning(titulo)
    st.code(f"{type(e).__name__}: {e}", language=None)
    if isinstance(e, AttributeError) and "has no attribute" in str(e):
        st.error("Esto significa que un archivo de tu repositorio está incompleto o es de otra versión. Volvé a subirlo (LISTA_DE_ARCHIVOS.txt dice cuántas líneas tiene que mostrar GitHub).")


def faltantes(item, puntos, pasos, fotos):
    """Qué le falta completar a una rutina para que el operador la tenga fácil."""
    f = []
    if not [p for p in pasos if p["item_id"] == item["id"]]:
        f.append("paso a paso")
    if not [x for x in fotos if x["item_id"] == item["id"]]:
        f.append("fotos")
    sin_rango = [p for p in puntos if p["item_id"] == item["id"] and p["tipo"] == "numero" and p.get("minimo") is None and p.get("maximo") is None]
    if sin_rango:
        f.append(f"rango de {len(sin_rango)} valor(es)")
    if not item.get("maquina_id"):
        f.append("equipo")
    return f


# ----------------------------------------------------------------
# Pantalla
# ----------------------------------------------------------------
def render_rutinas(usuario):
    st.title("Rutinas del operador")
    st.write("Rondas de control que hacen los operadores escaneando un QR: paso a paso con fotos, lecturas con rango y aviso automático de fallas.")
    rol = (usuario or {}).get("rol")
    if rol not in ("admin", "gerente"):
        st.warning("Esta pantalla está disponible solo para el administrador y el gerente.")
        return
    es_admin = rol == "admin"
    try:
        d = _cargar_config(_v())
    except Exception as e:
        _mostrar_error("No se pudieron leer las tablas de rutinas. Si nunca corriste `rutinas.sql` en Supabase, corrélo (y después `rutinas_carga_inicial.sql`). "
                       "Si ya lo habías corrido, el motivo real está en el detalle de abajo.", e)
        return
    clave = db.rol_de_la_clave(st.secrets.get("SUPABASE_KEY", ""))
    if clave and clave != "service_role":
        st.warning(f"Tu SUPABASE_KEY es la clave pública («{clave}»): con ella no se pueden guardar rutinas, pasos ni fotos. " + AVISO_CLAVE)
    secciones = ["📊 Cumplimiento"] + (["📋 Rutinas", "👷 Operadores y PIN", "🖨️ QR de las zonas"] if es_admin else [])
    seccion = st.radio("Sección", secciones, horizontal=True, label_visibility="collapsed", key="rut_seccion")
    flash = st.session_state.pop("rut_flash", None)
    if flash:
        getattr(st, flash[0])(flash[1])
    if seccion.startswith("📊"):
        _seccion_cumplimiento(d, (usuario or {}).get('nombre'))
    elif seccion.startswith("📋"):
        _seccion_rutinas(d)
    elif seccion.startswith("👷"):
        _seccion_operadores(d)
    else:
        _seccion_qr(d)


# ----------------------------------------------------------------
# Rutinas (editor)
# ----------------------------------------------------------------
def _seccion_rutinas(d):
    zonas, items = d["zonas"], d["items"]
    with st.expander("⚙️ Zonas (cada zona tiene su QR)"):
        with st.form("rut_form_zona", clear_on_submit=True):
            nombre = st.text_input("Nueva zona", placeholder="Ej: 2.º Piso")
            if st.form_submit_button("Agregar zona"):
                if not nombre.strip():
                    st.error("Escribí el nombre.")
                elif nombre.strip().casefold() in [z["nombre"].casefold() for z in zonas]:
                    st.error("Ya existe una zona con ese nombre.")
                else:
                    db.insertar_zona({"nombre": nombre.strip(), "orden": max([z.get("orden") or 0 for z in zonas] + [0]) + 1})
                    _invalidar()
                    st.rerun()
        if zonas:
            df = pd.DataFrame([{"id": z["id"], "Zona": z["nombre"], "Orden": z.get("orden") or 0, "Activa": z.get("activo") is not False} for z in zonas])
            ed = st.data_editor(df, hide_index=True, width="stretch", disabled=["id"], column_config={"id": None, "Activa": st.column_config.CheckboxColumn()},
                                key=f"rut_zonas_ed_{_v()}")
            cambios = []
            por_id = {z["id"]: z for z in zonas}
            for _, r in ed.iterrows():
                z = por_id[int(r["id"])]
                p = {}
                if str(r["Zona"]).strip() and str(r["Zona"]).strip() != z["nombre"]:
                    p["nombre"] = str(r["Zona"]).strip()
                if int(r["Orden"]) != (z.get("orden") or 0):
                    p["orden"] = int(r["Orden"])
                if bool(r["Activa"]) != (z.get("activo") is not False):
                    p["activo"] = bool(r["Activa"])
                if p:
                    cambios.append((z["id"], p))
            if st.button(f"💾 Guardar {len(cambios)} cambio(s) de zonas", disabled=not cambios, key="rut_zonas_guardar"):
                errores = 0
                for zid, p in cambios:
                    try:
                        db.actualizar_zona(zid, p)
                    except Exception:
                        errores += 1
                _invalidar()
                _flash("success" if not errores else "warning", f"Se guardaron {len(cambios) - errores} cambio(s)." + (f" {errores} fallaron (¿nombre repetido?)." if errores else ""))
                st.rerun()
    if not zonas:
        st.info("Todavía no hay zonas. Agregá la primera arriba, o corré `rutinas_carga_inicial.sql`.")
        return
    nombres = {z["nombre"]: z for z in zonas}
    zona = nombres[st.selectbox("Zona", list(nombres), key="rut_zona_sel")]
    items_z = [i for i in items if i["zona_id"] == zona["id"]]
    if items_z:
        st.dataframe(pd.DataFrame([{
            "Código": i.get("codigo"), "Rutina": i["titulo"], "Frecuencia": i["frecuencia"], "Puntos": len([p for p in d["puntos"] if p["item_id"] == i["id"]]),
            "Pasos": len([p for p in d["pasos"] if p["item_id"] == i["id"]]), "Fotos": len([f for f in d["fotos"] if f["item_id"] == i["id"]]),
            "Le falta": ", ".join(faltantes(i, d["puntos"], d["pasos"], d["fotos"])) or "✅ completa", "Activa": "sí" if i.get("activo") is not False else "no"} for i in items_z]),
            hide_index=True, width="stretch")
    nueva = "➕ Nueva rutina"
    etiquetas = {f"{i.get('codigo') or ''} · {i['titulo']}".strip(" ·"): i for i in items_z}
    elegida = st.selectbox("Elegí la rutina para editar", [nueva] + list(etiquetas), key=f"rut_item_sel_{zona['id']}")
    if elegida == nueva:
        _form_item(None, zona, d)
    else:
        _editor_item(etiquetas[elegida], zona, d)


def _form_item(item, zona, d):
    t = item or {}
    maquinas = st.session_state.get("maquinas", [])
    opciones_maq = {"— sin equipo (no se avisa la falla) —": None}
    opciones_maq.update({f"{m.get('codigo') or '?'} · {m.get('nombre')}": m["id"] for m in maquinas})
    etiqueta_actual = next((k for k, v in opciones_maq.items() if v == t.get("maquina_id")), list(opciones_maq)[0])
    with st.form(f"rut_form_item_{t.get('id', 'nuevo')}"):
        c1, c2 = st.columns([0.25, 0.75])
        codigo = c1.text_input("Código", value=t.get("codigo") or "", placeholder="AU-023")
        titulo = c2.text_input("Qué tiene que hacer el operador *", value=t.get("titulo") or "")
        maq = st.selectbox("Equipo (a quién se le avisa si falla)", list(opciones_maq), index=list(opciones_maq).index(etiqueta_actual))
        c3, c4, c5 = st.columns(3)
        frecuencia = c3.radio("Frecuencia", ["Diaria", "Semanal"], index=0 if t.get("frecuencia", "Diaria") == "Diaria" else 1, horizontal=True)
        duracion = c4.number_input("Minutos aprox.", min_value=0, step=1, value=int(t.get("duracion_min") or 0))
        cond_op = CONDICIONES + ([t["condicion"]] if t.get("condicion") and t["condicion"] not in CONDICIONES else [])
        condicion = c5.selectbox("Condición de la máquina", cond_op, index=cond_op.index(t["condicion"]) if t.get("condicion") in cond_op else 0)
        seguridad = st.text_area("Seguridad (se muestra destacada)", value=t.get("seguridad") or "")
        c6, c7 = st.columns(2)
        herramientas = c6.text_input("Herramientas", value=t.get("herramientas") or "")
        criterio = c7.text_input("Está bien si… (criterio)", value=t.get("criterio") or "")
        c8, c9, c10 = st.columns(3)
        critico = c8.checkbox("Es crítica (si falla, el aviso sale con prioridad ALTA)", value=bool(t.get("critico")))
        foto_req = c9.checkbox("Pedir foto obligatoria si sale «No OK»", value=bool(t.get("foto_requerida_no_ok")))
        activo = c10.checkbox("Activa (la ve el operador)", value=t.get("activo") is not False)
        if st.form_submit_button("💾 Guardar rutina" if item else "➕ Crear rutina", type="primary"):
            if not titulo.strip():
                st.error("Escribí qué tiene que hacer el operador.")
            else:
                datos = {"zona_id": zona["id"], "maquina_id": opciones_maq[maq], "codigo": codigo.strip() or None, "titulo": titulo.strip(), "frecuencia": frecuencia,
                         "duracion_min": int(duracion) or None, "condicion": condicion, "seguridad": seguridad.strip() or None, "herramientas": herramientas.strip() or None,
                         "criterio": criterio.strip() or None, "critico": critico, "foto_requerida_no_ok": foto_req, "activo": activo}
                try:
                    if item:
                        db.actualizar_item(item["id"], datos)
                    else:
                        datos["orden"] = max([i.get("orden") or 0 for i in d["items"] if i["zona_id"] == zona["id"]] + [0]) + 1
                        db.insertar_item(datos)
                except Exception as e:
                    st.error(f"No se pudo guardar: {_motivo(e)}")
                    return
                _invalidar()
                _flash("success", "Rutina guardada." if item else "Rutina creada. Ahora elegila en la lista para cargarle puntos de control, pasos y fotos.")
                st.rerun()


def _editor_item(item, zona, d):
    iid = item["id"]
    falta = faltantes(item, d["puntos"], d["pasos"], d["fotos"])
    st.caption("✅ Esta rutina está completa." if not falta else "Le falta: " + ", ".join(falta) + ".")
    t_datos, t_puntos, t_pasos, t_fotos, t_borrar = st.tabs(["📝 Datos", "🎯 Puntos de control", "📘 Paso a paso", "🖼️ Fotos", "🗑️ Eliminar"])
    with t_datos:
        _form_item(item, zona, d)
    with t_puntos:
        _tab_puntos(item, d)
    with t_pasos:
        _tab_pasos(item, zona, d)
    with t_fotos:
        _tab_fotos(item, d)
    with t_borrar:
        st.caption("Se borran también sus puntos, pasos y fotos. El historial de rondas ya hechas se conserva.")
        if st.checkbox("Confirmo que quiero eliminar esta rutina", key=f"rut_okdel_{iid}") and st.button("Eliminar rutina", key=f"rut_del_{iid}"):
            try:
                db.borrar_item(iid, d["fotos"])
            except Exception as e:
                st.error(f"No se pudo eliminar: {_motivo(e)}")
                return
            _invalidar()
            _flash("success", "Rutina eliminada.")
            st.rerun()


def _tab_puntos(item, d):
    iid = item["id"]
    st.write("Lo que el operador responde en esta rutina. Si no cargás ninguno, responde un único «OK / No OK». "
             "Para un valor medido, poné el **mínimo y/o máximo** permitido: si lo supera, la app lo marca y avisa sola.")
    propios = [p for p in d["puntos"] if p["item_id"] == iid]
    df = pd.DataFrame([{"Qué controlar": p["texto"], "Tipo": TIPO_A_TEXTO.get(p["tipo"], "OK / No OK"), "Unidad": p.get("unidad") or "", "Mínimo": p.get("minimo"), "Máximo": p.get("maximo")}
                       for p in propios] or [], columns=["Qué controlar", "Tipo", "Unidad", "Mínimo", "Máximo"])
    ed = st.data_editor(df, num_rows="dynamic", hide_index=True, width="stretch", key=f"rut_puntos_ed_{iid}_{_v()}", column_config={
        "Tipo": st.column_config.SelectboxColumn(options=list(TIPOS_PUNTO), default="OK / No OK"),
        "Mínimo": st.column_config.NumberColumn(format="%g"), "Máximo": st.column_config.NumberColumn(format="%g")})
    filas, errores = [], []
    for i, r in ed.iterrows():
        texto = "" if pd.isna(r["Qué controlar"]) else str(r["Qué controlar"]).strip()
        if not texto:
            continue
        tipo = TIPOS_PUNTO.get(r["Tipo"], "ok") if not pd.isna(r["Tipo"]) else "ok"
        mn = None if pd.isna(r["Mínimo"]) else float(r["Mínimo"])
        mx = None if pd.isna(r["Máximo"]) else float(r["Máximo"])
        if tipo == "ok" and (mn is not None or mx is not None):
            errores.append(f"«{texto}»: un OK / No OK no lleva mínimo ni máximo (cambialo a «Valor medido»).")
        if mn is not None and mx is not None and mn > mx:
            errores.append(f"«{texto}»: el mínimo no puede ser mayor que el máximo.")
        filas.append({"texto": texto, "tipo": tipo, "unidad": "" if pd.isna(r["Unidad"]) else str(r["Unidad"]).strip(), "minimo": mn, "maximo": mx})
    for e in errores:
        st.error(e)
    if st.button("💾 Guardar puntos de control", type="primary", disabled=bool(errores), key=f"rut_puntos_guardar_{iid}"):
        try:
            db.reemplazar_puntos(iid, filas, d["puntos"])
        except Exception as e:
            st.error(f"No se pudo guardar: {_motivo(e)}")
            return
        _invalidar()
        _flash("success", f"Se guardaron {len(filas)} punto(s) de control.")
        st.rerun()


def _tab_pasos(item, zona, d):
    iid = item["id"]
    propios = [p for p in d["pasos"] if p["item_id"] == iid]
    clave = f"rut_pasos_txt_{iid}"
    if clave not in st.session_state:
        st.session_state[clave] = "\n".join(p["texto"] for p in propios)
    st.write("Escribí **un paso por renglón**, en el orden en que se hacen. Cortos y claros: lo lee un operador parado frente a la máquina, desde el celular. "
             "Después, en «Fotos», podés poner una foto en cada paso.")
    if st.button("✨ Sugerir un borrador con IA", key=f"rut_ia_{iid}", help="La IA propone un paso a paso a partir del título y el criterio. Es solo un borrador: revisalo con alguien que conozca el equipo."):
        try:
            from database import rutinas_ia
            pasos = rutinas_ia.sugerir_pasos(R.prompt_pasos(zona["nombre"], item, [p for p in d["puntos"] if p["item_id"] == iid]))
        except Exception as e:
            st.error(f"No se pudo pedir el borrador: {e}")
        else:
            st.session_state[clave] = "\n".join(pasos)
            st.session_state["rut_ia_aviso"] = iid
            st.rerun()
    if st.session_state.get("rut_ia_aviso") == iid:
        st.warning("Este es un BORRADOR de la IA: corregilo con alguien que conozca el equipo antes de guardar.")
    texto = st.text_area("Pasos (uno por renglón)", key=clave, height=220)
    pasos = R.pasos_desde_texto(texto)
    st.caption(f"{len(pasos)} paso(s).")
    if st.button("💾 Guardar el paso a paso", type="primary", key=f"rut_pasos_guardar_{iid}"):
        try:
            db.reemplazar_pasos(iid, pasos, d["pasos"])
        except Exception as e:
            st.error(f"No se pudo guardar: {_motivo(e)}")
            return
        st.session_state.pop("rut_ia_aviso", None)
        _invalidar()
        _flash("success", f"Se guardaron {len(pasos)} paso(s)." + (" Las fotos de pasos que ya cargaste siguen ligadas al número de paso: revisalas si cambiaste el orden." if [f for f in d["fotos"] if f["item_id"] == iid and f["tipo"] == "paso"] else ""))
        st.rerun()


def _tab_fotos(item, d):
    iid = item["id"]
    propias = [f for f in d["fotos"] if f["item_id"] == iid]
    pasos = [p for p in d["pasos"] if p["item_id"] == iid]
    st.write("Fotos que ve el operador en su celular: de cada **paso**, de **así debe verse (OK)** y de **así NO debe verse (mal)**. "
             "Desde el celular, tocá «Browse files» y elegí «Cámara» para sacarlas ahí mismo, frente al equipo.")
    for f in propias:
        with st.expander(f"{ {v: k for k, v in TIPOS_FOTO.items()}.get(f['tipo']) } · {'paso ' + str(f['paso_orden']) if f.get('paso_orden') else 'general'} · {f.get('leyenda') or 'sin leyenda'}"):
            try:
                st.image(db.url_publica(f["ruta"]), width=260)
            except Exception:
                st.caption("(no se pudo mostrar la foto)")
            c1, c2 = st.columns([0.7, 0.3])
            nueva = c1.text_input("Leyenda", value=f.get("leyenda") or "", key=f"rut_ley_{f['id']}")
            if c1.button("Guardar leyenda", key=f"rut_leyg_{f['id']}") and nueva != (f.get("leyenda") or ""):
                db.actualizar_foto(f["id"], {"leyenda": nueva.strip() or None})
                _invalidar()
                st.rerun()
            if c2.button("🗑️ Quitar", key=f"rut_fdel_{f['id']}"):
                db.borrar_foto(f)
                _invalidar()
                st.rerun()
    # Sin formulario: así la foto elegida se ve enseguida (en el celular, dentro de un formulario no se notaba si había quedado cargada).
    n = st.session_state.get(f"rut_up_n_{iid}", 0)                       # cambia la clave para vaciar el selector después de subir
    archivos = st.file_uploader("Fotos (de la galería o sacándolas con la cámara)", accept_multiple_files=True, key=f"rut_up_{iid}_{n}",
                                help="Acepta cualquier foto del celular (JPG, PNG, HEIC, WEBP). Se achica sola.")
    with st.expander("¿No te abre la cámara o no queda la foto? Sacala desde acá"):
        camara = st.camera_input("Sacar la foto", key=f"rut_cam_{iid}_{n}", label_visibility="collapsed")
    elegidas = list(archivos or []) + ([camara] if camara is not None else [])
    listas, errores = [], []
    for a in elegidas:
        try:
            listas.append((a.name, *R.preparar_foto(a.getvalue())))
        except Exception as e:
            errores.append(f"«{a.name}» no se pudo leer ({type(e).__name__}). Probá con otra o sacala con la cámara.")
    for err in errores:
        st.error(err)
    if listas:
        st.success(f"✅ {len(listas)} foto(s) lista(s) para subir.")
        cols = st.columns(min(4, len(listas)))
        for k, (_, contenido, _) in enumerate(listas):
            cols[k % len(cols)].image(contenido, width=140)
    c1, c2 = st.columns(2)
    tipo = c1.selectbox("¿Qué muestra?", list(TIPOS_FOTO), key=f"rut_ftipo_{iid}")
    opciones_paso = [GENERAL] + [f"Paso {p['orden']}: {p['texto'][:50]}" for p in pasos]
    paso = c2.selectbox("¿De qué paso? (solo si es «Paso del paso a paso»)", opciones_paso, key=f"rut_fpaso_{iid}",
                        disabled=TIPOS_FOTO[tipo] != "paso")
    if TIPOS_FOTO[tipo] == "paso" and not pasos:
        st.caption("Todavía no hay pasos guardados: la foto va como general. Guardá el paso a paso primero si querés ligarla a un paso.")
    leyenda = st.text_input("Leyenda (opcional)", placeholder="Ej: Abrir esta tapa con la llave 13", key=f"rut_fley_{iid}_{n}")
    if st.button("📤 Subir fotos", type="primary", key=f"rut_fsubir_{iid}"):
        if not listas:
            st.warning("No hay ninguna foto elegida. Tocá «Browse files» (o la cámara de arriba) y esperá a ver la foto antes de subir.")
        else:
            paso_orden = None if paso == GENERAL or TIPOS_FOTO[tipo] != "paso" else pasos[opciones_paso.index(paso) - 1]["orden"]
            ok, fallas = 0, []
            for nombre, contenido, ct in listas:
                try:
                    db.subir_foto_ref(iid, contenido, ct, TIPOS_FOTO[tipo], paso_orden, leyenda, len(propias) + ok + 1)
                    ok += 1
                except Exception as e:
                    fallas.append(f"«{nombre}»: {_motivo(e)}")
            st.session_state[f"rut_up_n_{iid}"] = n + 1
            _invalidar()
            _flash("success" if not fallas else "warning", f"Se subieron {ok} foto(s)." + (" No se pudieron subir: " + " ".join(fallas) if fallas else ""))
            st.rerun()


# ----------------------------------------------------------------
# Operadores y PIN
# ----------------------------------------------------------------
def _seccion_operadores(d):
    ops = d["operadores"]
    st.write("Cada operador entra con su **nombre y un PIN de 4 números**. El PIN se guarda cifrado: no se puede volver a ver, solo cambiar. "
             "Con 5 errores seguidos el operador queda bloqueado 15 minutos.")
    with st.form("rut_form_operador", clear_on_submit=True):
        nombre = st.text_input("Agregar un operador", placeholder="Nombre y apellido")
        if st.form_submit_button("Agregar"):
            if not db.nombre_valido(nombre):
                st.error("Escribí el nombre.")
            elif nombre.strip().casefold() in [o["nombre"].casefold() for o in ops]:
                st.error("Ya existe ese operador.")
            else:
                db.insertar_operador(nombre)
                _invalidar()
                _flash("success", f"Operador «{nombre.strip()}» agregado. Ahora ponele un PIN.")
                st.rerun()
    if not ops:
        st.info("Todavía no hay operadores.")
        return
    ahora = pd.Timestamp.now(tz="UTC")

    def estado(o):
        b = o.get("bloqueado_hasta")
        if b and pd.Timestamp(b) > ahora:
            return "🔒 bloqueado"
        return "✅ activo" if o.get("activo") is not False else "⛔ de baja"
    st.dataframe(pd.DataFrame([{"Operador": o["nombre"], "Estado": estado(o), "PIN": "✅ puesto" if o["tiene_pin"] else "❌ falta"} for o in ops]), hide_index=True, width="stretch")
    por_nombre = {o["nombre"]: o for o in ops}
    o = por_nombre[st.selectbox("Operador", list(por_nombre), key="rut_op_sel")]
    c1, c2, c3 = st.columns(3)
    clave_pin = f"rut_pin_{o['id']}"
    if c1.button("🎲 Sugerir un PIN", key=f"rut_pin_azar_{o['id']}"):
        usados = {"0000", "1111", "2222", "3333", "4444", "5555", "6666", "7777", "8888", "9999", "1234", "4321", "1212"}
        pin = next(p for p in (f"{random.randint(0, 9999):04d}" for _ in range(200)) if p not in usados)
        st.session_state[clave_pin] = pin
        st.rerun()
    pin = st.text_input(f"PIN de {o['nombre']} (4 números)", max_chars=4, key=clave_pin)
    if st.button("🔑 Guardar PIN (también lo desbloquea)", type="primary", key=f"rut_pin_g_{o['id']}"):
        if not R.pin_valido(pin):
            st.error("El PIN tiene que ser de exactamente 4 números.")
        else:
            try:
                db.establecer_pin(o["id"], pin)
            except Exception as e:
                st.error(f"No se pudo guardar el PIN: {_motivo(e)}")
                return
            _invalidar()
            st.session_state.pop(clave_pin, None)
            _flash("success", f"✅ PIN de {o['nombre']}: **{pin}**. Anotalo y entregáselo: después no se puede volver a ver (solo cambiar).")
            st.rerun()
    if c2.button("🔓 Desbloquear", key=f"rut_desb_{o['id']}"):
        db.desbloquear_operador(o["id"])
        _invalidar()
        _flash("success", f"{o['nombre']} desbloqueado.")
        st.rerun()
    if c3.button("Reactivar" if o.get("activo") is False else "Dar de baja", key=f"rut_baja_{o['id']}"):
        db.actualizar_operador(o["id"], {"activo": o.get("activo") is False})
        _invalidar()
        st.rerun()


# ----------------------------------------------------------------
# QR de las zonas
# ----------------------------------------------------------------
@st.cache_data(show_spinner=False)
def _qr_cache(url):
    return R.qr_png(url)


def _seccion_qr(d):
    base = st.text_input("Dirección de tu app", value=st.session_state.get("rut_base_url") or st.secrets.get("APP_BASE_URL", ""), placeholder="https://tu-app.streamlit.app",
                         help="Es la dirección que ves en el navegador. Para que quede fija, guardala en los secrets como APP_BASE_URL.", key="rut_base_input")
    st.session_state["rut_base_url"] = base
    if not base.strip():
        st.warning("Escribí la dirección de tu app para generar los QR.")
        return
    zonas = [z for z in d["zonas"] if z.get("activo") is not False]
    if not zonas:
        st.info("No hay zonas activas.")
        return
    st.write("Imprimí una etiqueta por zona (idealmente plastificada) y pegala donde el operador empieza su ronda. **Probá cada QR con tu celular antes de pegarlo.**")
    paquete = []
    for z in zonas:
        url = R.url_ronda(base, z["id"])
        items_z = [i for i in d["items"] if i["zona_id"] == z["id"] and i.get("activo") is not False]
        paquete.append({"nombre": z["nombre"], "url": url, "items": items_z})
        c1, c2 = st.columns([0.3, 0.7])
        c1.image(_qr_cache(url), width=150)
        c2.markdown(f"**{z['nombre']}** — {len(items_z)} rutina(s)")
        c2.code(url, language=None)
        c2.download_button("⬇️ Descargar el QR (PNG)", data=_qr_cache(url), file_name=f"QR_ronda_{z['nombre'].replace(' ', '_')}.png", mime="image/png", key=f"rut_qr_png_{z['id']}")
    try:
        pdf = R.pdf_etiquetas(paquete)
        st.download_button("🖨️ Descargar el PDF con las etiquetas de todas las zonas", data=pdf, file_name="etiquetas_rondas_QR.pdf", mime="application/pdf", type="primary", key="rut_qr_pdf")
    except Exception as e:
        st.error(f"No se pudo armar el PDF: {e}")


# ----------------------------------------------------------------
# Cumplimiento
# ----------------------------------------------------------------
def _periodo():
    hoy = R.hoy_paraguay()
    c1, c2, c3 = st.columns([1.2, 1, 1])
    op = c1.selectbox("Período", PERIODOS, key="rut_periodo")
    if op == "Últimos 7 días":
        return hoy - timedelta(days=6), hoy
    if op == "Últimos 30 días":
        return hoy - timedelta(days=29), hoy
    if op == "Este mes":
        return hoy.replace(day=1), hoy
    return c2.date_input("Desde", value=hoy - timedelta(days=6), format="DD/MM/YYYY", key="rut_d1"), c3.date_input("Hasta", value=hoy, format="DD/MM/YYYY", key="rut_d2")


@st.cache_data(ttl=30, show_spinner=False)
def _cargar_resultados(desde, hasta, version):
    ejec = db.listar_ejecuciones(R.a_fecha(desde), R.a_fecha(hasta))
    return ejec, db.listar_respuestas([e["id"] for e in ejec]) if ejec else []


def filas_respuestas(ejec, resp):
    """Respuestas con la fecha, la zona y el operador de la ronda a la que pertenecen."""
    por_id = {e["id"]: e for e in ejec}
    return [{**r, "fecha": por_id[r["ejecucion_id"]]["fecha"], "zona": por_id[r["ejecucion_id"]].get("zona_nombre"), "operador": por_id[r["ejecucion_id"]]["operador_nombre"],
             "ronda_hora": por_id[r["ejecucion_id"]].get("creado_en")} for r in resp if r["ejecucion_id"] in por_id]


def _hora(valor):
    h = M.hora_local(valor)
    return f"{h:%H:%M}" if h else ""


def _estado_de_hoy(d, items):
    """Arriba de todo, sin importar el período: ¿qué se hizo hoy (y esta semana, las semanales) y qué falta?, zona por zona."""
    hoy = R.hoy_paraguay()
    try:
        ejec, resp = _cargar_resultados(R.lunes_de(hoy).isoformat(), hoy.isoformat(), _v())
    except Exception as e:
        _mostrar_error("No se pudieron leer las rondas de hoy.", e)
        return
    hechos = [{"item_id": r.get("item_id"), "fecha": r["fecha"], "operador": r["operador"], "resultado": r["resultado"], "hora": r.get("ronda_hora")}
              for r in filas_respuestas(ejec, resp)]
    activos = [i for i in items if i.get("activo") is not False]
    if not activos:
        st.info("Todavía no hay rutinas activas. Cargalas en la pestaña «Rutinas».")
        return
    estados = R.estado_items(activos, hechos, hoy)
    hechos_n = sum(1 for e in estados if e["estado"] == "hecho")
    st.subheader(f"Hoy, {hoy:%d/%m}: {hechos_n} de {len(estados)} controles hechos")
    st.caption("Diarias: lo de hoy. Semanales: lo de esta semana (lunes a domingo).")
    st.progress(hechos_n / len(estados) if estados else 0)
    zonas_orden = [z["nombre"] for z in d["zonas"]]
    por_zona = {}
    for e in estados:
        por_zona.setdefault(e["item"].get("zona_nombre") or "(sin zona)", []).append(e)
    nombres = sorted(por_zona, key=lambda z: zonas_orden.index(z) if z in zonas_orden else 999)
    cols = st.columns(min(3, len(nombres)) or 1)
    for n, zona in enumerate(nombres):
        lista = por_zona[zona]
        hz = sum(1 for e in lista if e["estado"] == "hecho")
        color = "green" if hz == len(lista) else ("red" if hz == 0 else "orange")
        with cols[n % len(cols)], st.container(border=True):
            st.markdown(f"**{zona}** :{color}-badge[{hz} de {len(lista)}]")
            for e in lista:
                it = e["item"]
                nombre = f"{it.get('codigo') or ''} {it.get('titulo') or ''}".strip()
                sem = " · semanal" if it.get("frecuencia") == "Semanal" else ""
                if e["estado"] == "hecho":
                    marca = "❌ con problema" if e["resultado"] == "NO_OK" else "✅"
                    cuando = f"{e['fecha_hecho']:%d/%m} " if it.get("frecuencia") == "Semanal" and e.get("fecha_hecho") else ""
                    st.markdown(f"{marca} {nombre}  \n:gray[{e['hecho_por'] or ''} · {cuando}{_hora(e['hora'])}{sem}]")
                else:
                    st.markdown(f":orange[⏳ {nombre}]  \n:gray[No se hizo todavía{sem}]")


def _grilla(detalle, desde, hasta):
    """Tabla rutina × día con ✅ (se hizo), ❌ (no se hizo) y vacío (no tocaba)."""
    diarias = [f for f in detalle if f["frecuencia"] != "Semanal"]
    semanales = [f for f in detalle if f["frecuencia"] == "Semanal"]
    if (hasta - desde).days > 31:
        st.info("La grilla muestra hasta 31 días. Para períodos más largos usá «Lo que faltó» o el Excel.")
        return
    if diarias:
        st.markdown("**Rutinas diarias**")
        dias = sorted({f["fecha"] for f in diarias})
        filas = {}
        for f in diarias:
            clave = (f["zona"], f"{f['codigo'] or ''} {f['control'] or ''}".strip())
            filas.setdefault(clave, {"Zona": clave[0], "Rutina": clave[1]})[f"{f['fecha']:%d/%m}"] = "✅" if f["hecho"] else "❌"
        df = pd.DataFrame(list(filas.values()), columns=["Zona", "Rutina"] + [f"{x:%d/%m}" for x in dias]).fillna("")
        st.dataframe(df, hide_index=True, width="stretch")
    if semanales:
        st.markdown("**Rutinas semanales** (columna = semana que empieza ese lunes)")
        semanas = sorted({f["semana"] for f in semanales})
        filas = {}
        for f in semanales:
            clave = (f["zona"], f"{f['codigo'] or ''} {f['control'] or ''}".strip())
            filas.setdefault(clave, {"Zona": clave[0], "Rutina": clave[1]})[f"Sem. {f['semana']:%d/%m}"] = "✅" if f["hecho"] else "❌"
        df = pd.DataFrame(list(filas.values()), columns=["Zona", "Rutina"] + [f"Sem. {x:%d/%m}" for x in semanas]).fillna("")
        st.dataframe(df, hide_index=True, width="stretch")
    if not diarias and not semanales:
        st.caption("En este período no tocaba ningún control.")
    else:
        st.caption("✅ se hizo · ❌ no se hizo · vacío: no tocaba (la rutina todavía no existía o es un día futuro)")


def _seccion_cumplimiento(d, usuario_nombre=None):
    zonas = {z["id"]: z["nombre"] for z in d["zonas"]}
    items = [{**i, "zona_nombre": zonas.get(i["zona_id"])} for i in d["items"]]
    _estado_de_hoy(d, items)
    st.divider()

    st.subheader("Período")
    desde, hasta = _periodo()
    if hasta < desde:
        st.error("La fecha «Hasta» no puede ser anterior a «Desde».")
        return
    try:
        ejec, resp = _cargar_resultados(desde.isoformat(), hasta.isoformat(), _v())
    except Exception as e:
        _mostrar_error("No se pudieron leer las rondas.", e)
        return
    filas = filas_respuestas(ejec, resp)
    cum = R.cumplimiento(items, filas, desde, hasta)
    detalle = R.detalle_cumplimiento(items, filas, desde, hasta)
    faltaron = [f for f in detalle if not f["hecho"]]
    problemas = [r for r in filas if r["resultado"] == "NO_OK"]
    m = st.columns(4)
    m[0].metric("Cumplimiento", f"{cum['total']['pct']:.0f} %" if cum["total"]["pct"] is not None else "—", help="Controles hechos ÷ controles que tocaban en el período")
    m[1].metric("Controles hechos", f"{cum['total']['hechas']} de {cum['total']['esperadas']}")
    m[2].metric("No se hicieron", len(faltaron))
    m[3].metric("Problemas detectados", len(problemas))

    c_xl, c_pbi = st.columns([1, 1], vertical_alignment="center")
    if items:
        try:
            excel = RX.excel_periodo(ejec, filas, desde, hasta, usuario_nombre, detalle=detalle)
            c_xl.download_button("⬇️ Generar Excel del período", data=excel, file_name=M.nombre_archivo("Rondas", desde, hasta), key="rut_excel", type="primary",
                                 mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True,
                                 help="Con la marca de la empresa y una tabla por hoja, lista para Power BI. Incluye «Cumplimiento»: se hizo o no, control por control.")
        except Exception as e:
            c_xl.warning(f"No se pudo armar el Excel: {e}")
    with c_pbi.popover("Conectar con Power BI", use_container_width=True):
        st.markdown("Power BI puede leer los datos **directo de la base**, sin Excel, y actualizarse solo. "
                    "Las vistas son `pbi.rutinas_cumplimiento`, `pbi.rutinas_rondas`, `pbi.rutinas_controles` y `pbi.rutinas_lecturas`.")
        st.caption("Instalación: archivo sql/powerbi_vistas.sql (una vez, en Supabase) y los pasos de sql/GUIA_POWERBI.md.")

    vista = st.segmented_control("Ver", ["¿Se hizo?", f"Lo que faltó ({len(faltaron)})", "Por zona", "Por operador", f"Problemas ({len(problemas)})"],
                                 default="¿Se hizo?", key="rut_cum_vista", label_visibility="collapsed") or "¿Se hizo?"
    if vista == "¿Se hizo?":
        _grilla(detalle, desde, hasta)
        if len(cum["por_dia"]) > 1:
            df = pd.DataFrame([{"Día": f"{dia:%d/%m}", "Cumplimiento %": v["pct"]} for dia, v in cum["por_dia"].items() if v["pct"] is not None])
            if not df.empty:
                st.markdown("**Cumplimiento por día (%)**")
                st.bar_chart(df, x="Día", y="Cumplimiento %")
    elif vista.startswith("Lo que faltó"):
        if not faltaron:
            st.success("Se hizo todo lo que tocaba en el período.")
        else:
            st.dataframe(pd.DataFrame([{"Fecha": f"{f['fecha']:%d/%m/%Y}" if f["frecuencia"] != "Semanal" else f"Semana del {f['semana']:%d/%m}",
                                        "Zona": f["zona"], "Código": f["codigo"], "Rutina": f["control"], "Frecuencia": f["frecuencia"]}
                                       for f in sorted(faltaron, key=lambda x: x["fecha"], reverse=True)]), hide_index=True, width="stretch")
    elif vista == "Por zona":
        if cum["por_zona"]:
            st.dataframe(pd.DataFrame([{"Zona": z, "Tocaban": v["esperadas"], "Hechos": v["hechas"], "No se hicieron": v["esperadas"] - v["hechas"],
                                        "Cumplimiento %": v["pct"]} for z, v in cum["por_zona"].items()]), hide_index=True, width="stretch")
        else:
            st.caption("Sin rutinas en el período.")
    elif vista == "Por operador":
        if not filas:
            st.caption("Nadie envió rondas en el período.")
        else:
            por_op = {}
            for r in filas:
                o = por_op.setdefault(r["operador"], {"Operador": r["operador"], "Controles": 0, "Problemas": 0, "Rondas": set()})
                o["Controles"] += 1
                o["Problemas"] += 1 if r["resultado"] == "NO_OK" else 0
                o["Rondas"].add(r["ejecucion_id"])
            st.dataframe(pd.DataFrame([{**{k: v for k, v in o.items() if k != "Rondas"}, "Rondas": len(o["Rondas"])} for o in por_op.values()]), hide_index=True, width="stretch")
    else:
        _problemas(problemas)
    _lecturas(d, filas)


def _problemas(problemas):
    if not problemas:
        st.success("No se detectaron problemas en el período.")
        return
    st.dataframe(pd.DataFrame([{"Fecha": R.a_fecha(r["fecha"]).strftime("%d/%m/%Y"), "Zona": r["zona"], "Control": f"{r.get('item_codigo') or ''} {r['item_titulo']}".strip(),
                                "Operador": r["operador"], "Qué pasó": "; ".join(f"{x['texto']}" + (f": {R.fmt_num(x['valor'])}" if x.get("valor") is not None else "")
                                                                                  for x in (r.get("detalle") or []) if x.get("resultado") == "NO_OK") or "—",
                                "Comentario": r.get("comentario"), "Reporte de falla": r.get("falla_id"), "Foto": "sí" if r.get("foto_ruta") else ""} for r in problemas]),
                 hide_index=True, width="stretch")
    con_foto = [r for r in problemas if r.get("foto_ruta")]
    if con_foto:
        etq = {f"{R.a_fecha(r['fecha']):%d/%m} · {r['zona']} · {r['item_titulo'][:40]} · {r['operador']}": r for r in con_foto}
        elegido = st.selectbox("Ver la foto de un problema", list(etq), key="rut_ver_foto")
        if st.button("📷 Mostrar la foto", key="rut_ver_foto_btn"):
            try:
                st.image(db.url_evidencia(etq[elegido]["foto_ruta"]), width=420)
            except Exception as e:
                st.error(f"No se pudo abrir la foto: {e}")


def _lecturas(d, filas):
    numericos = [(i, p) for i in d["items"] for p in d["puntos"] if p["item_id"] == i["id"] and p["tipo"] == "numero"]
    if not numericos or not filas:
        return
    with st.expander("📈 Lecturas en el tiempo (presión, temperatura, horas…)"):
        etq = {f"{i.get('codigo') or ''} · {p['texto']}": (i, p) for i, p in numericos}
        i, p = etq[st.selectbox("Lectura", list(etq), key="rut_lectura_sel")]
        serie = R.serie_lecturas(filas, i["id"], p["texto"])
        if not serie:
            st.info("Todavía no hay lecturas de este punto en el período.")
            return
        df = pd.DataFrame([{"Fecha": f"{f:%d/%m}", "Valor": v, "Fuera de rango": "sí" if fr else "", "Operador": o} for f, v, fr, o in serie])
        graf = df[["Fecha", "Valor"]].copy()
        if p.get("minimo") is not None:
            graf["Mínimo"] = float(p["minimo"])
        if p.get("maximo") is not None:
            graf["Máximo"] = float(p["maximo"])
        st.line_chart(graf, x="Fecha", y=[c for c in graf.columns if c != "Fecha"])
        st.dataframe(df, hide_index=True, width="stretch")
