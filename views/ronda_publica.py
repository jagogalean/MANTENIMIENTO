"""
Página que abre el operador al escanear el QR de una zona (sin iniciar sesión en la app).
Flujo: elige su nombre y escribe su PIN -> ve lo que toca hoy -> hace un control por vez (paso a paso, fotos, respuesta) -> resumen -> envía.
"""
import uuid

import streamlit as st

from database import rutinas_logica as R
from database import rutinas_publica as DB

ICONO = {"OK": "✅", "NO_OK": "❌", "NA": "➖"}
OPCIONES = {"OK": "OK", "No OK": "NO_OK", "No aplica": "NA"}
CLAVES = ("rp_sesion", "rp_fase", "rp_cola", "rp_idx", "rp_resp", "rp_uuid", "rp_rutas", "rp_final")


@st.cache_data(ttl=60, show_spinner=False)
def _cargar(zona_id):
    return DB.obtener_zona(zona_id), DB.cargar_rutinas(zona_id), DB.operadores()


def _reiniciar(todo=True):
    for k in CLAVES if todo else ("rp_fase", "rp_cola", "rp_idx", "rp_resp", "rp_uuid", "rp_rutas", "rp_final"):
        st.session_state.pop(k, None)


def render_ronda_publica(zona_id):
    s = st.session_state
    try:
        zona_id = int(zona_id)
    except (TypeError, ValueError):
        st.error("Este QR no es válido.")
        return
    if s.get("rp_zona") != zona_id:
        _reiniciar()
        s["rp_zona"] = zona_id
    try:
        zona, rutinas, operadores = _cargar(zona_id)
    except Exception as e:
        st.error("No se pudo abrir la ronda. Avisale al administrador y mostrale este detalle:")
        st.code(f"{type(e).__name__}: {e}", language=None)
        return
    if not zona:
        st.error("Este QR no corresponde a una zona activa. Avisale al administrador.")
        return
    st.title(f"📋 Ronda — {zona['nombre']}")
    if not rutinas:
        st.info("Esta zona todavía no tiene controles cargados.")
        return

    sesion = s.get("rp_sesion")
    if not sesion:
        _ingreso(operadores)
        return
    c1, c2 = st.columns([0.7, 0.3])
    c1.markdown(f"👷 **{sesion['nombre']}**")
    if c2.button("Salir", key="rp_salir"):
        _reiniciar()
        st.rerun()

    fase = s.get("rp_fase", "lista")
    if fase == "ronda":
        _control(zona, rutinas)
    elif fase == "resumen":
        _resumen(zona, rutinas)
    elif fase == "fin":
        _fin()
    else:
        _lista(zona, rutinas)


# ----------------------------------------------------------------
# 1. Ingreso
# ----------------------------------------------------------------
def _ingreso(operadores):
    st.write("Elegí tu nombre y escribí tu PIN de 4 números.")
    if not operadores:
        st.warning("Todavía no hay operadores cargados. Avisale al administrador.")
        return
    nombres = {o["nombre"]: o["id"] for o in operadores}
    nombre = st.selectbox("¿Quién sos?", list(nombres), index=None, placeholder="Elegí tu nombre", key="rp_nombre")
    pin = st.text_input("PIN (4 números)", type="password", max_chars=4, key="rp_pin")
    if st.button("Entrar", type="primary", key="rp_entrar"):
        if not nombre:
            st.error("Elegí tu nombre.")
        elif not R.pin_valido(pin):
            st.error("El PIN tiene que ser de 4 números.")
        else:
            try:
                r = DB.iniciar_sesion(nombres[nombre], pin) or {}
            except Exception as e:
                st.error(f"No se pudo verificar el PIN: {e}")
                return
            estado = r.get("estado")
            if estado == "ok":
                st.session_state["rp_sesion"] = {"token": r["token"], "nombre": r["nombre"], "operador_id": r["operador_id"]}
                st.rerun()
            elif estado == "mal":
                st.error(f"PIN incorrecto. Te quedan {r.get('restantes')} intento(s).")
            elif estado == "bloqueado":
                st.error(f"Demasiados intentos. Esperá {r.get('minutos', 15)} minutos o pedile al administrador que te desbloquee.")
            elif estado == "sin_pin":
                st.warning("Todavía no tenés un PIN. Pedíselo al administrador.")
            else:
                st.error("Ese usuario no está habilitado. Hablá con el administrador.")


# ----------------------------------------------------------------
# 2. Lista de lo que toca
# ----------------------------------------------------------------
def _lista(zona, rutinas):
    s = st.session_state
    hoy = R.hoy_paraguay()
    try:
        hechos = DB.items_hechos(s["rp_sesion"]["token"], zona["id"], R.lunes_de(hoy), hoy)
    except Exception:
        hechos = []
    estados = R.estado_items(rutinas, hechos, hoy)
    pendientes = [e for e in estados if e["estado"] == "pendiente"]
    st.progress((len(estados) - len(pendientes)) / len(estados), text=f"{len(estados) - len(pendientes)} de {len(estados)} controles al día")
    for e in estados:
        it = e["item"]
        etiqueta = f"{it.get('codigo') or ''} · {it['titulo']}".strip(" ·")
        meta = ("Semanal" if it.get("frecuencia") == "Semanal" else "Diaria") + (f" · ~{it['duracion_min']} min" if it.get("duracion_min") else "")
        with st.container(border=True):
            if e["estado"] == "hecho":
                st.markdown(f"✅ **{etiqueta}**  \n<small>{meta} · Hecho por {e['hecho_por']} a las {e['hora']} ({R.ETIQUETA_RESULTADO.get(e['resultado'], '')})</small>", unsafe_allow_html=True)
            else:
                st.markdown(f"⬜ **{etiqueta}**  \n<small>{meta}</small>", unsafe_allow_html=True)
    incluir = False
    if pendientes:
        if len(pendientes) < len(estados):
            incluir = st.toggle("Incluir también los ya hechos", key="rp_incluir")
        elegidos = estados if incluir else pendientes
        if st.button(f"▶️ Empezar la ronda ({len(elegidos)} control{'es' if len(elegidos) != 1 else ''})", type="primary", key="rp_empezar"):
            s["rp_cola"] = [e["item"]["id"] for e in elegidos]
            s["rp_idx"], s["rp_resp"], s["rp_rutas"], s["rp_uuid"], s["rp_fase"] = 0, {}, {}, str(uuid.uuid4()), "ronda"
            st.rerun()
    else:
        st.success("🎉 Está todo al día en esta zona.")
        if st.button("Repetir la ronda igual", key="rp_repetir"):
            s["rp_cola"] = [e["item"]["id"] for e in estados]
            s["rp_idx"], s["rp_resp"], s["rp_rutas"], s["rp_uuid"], s["rp_fase"] = 0, {}, {}, str(uuid.uuid4()), "ronda"
            st.rerun()


# ----------------------------------------------------------------
# 3. Un control por vez
# ----------------------------------------------------------------
def _mostrar_foto(f):
    try:
        url = DB.url_foto(f["ruta"])
    except Exception:
        st.caption("(no se pudo cargar una foto)")
        return
    try:
        st.image(url, caption=f.get("leyenda") or None, width="stretch")
    except TypeError:                                   # versiones viejas de Streamlit
        st.image(url, caption=f.get("leyenda") or None, use_container_width=True)


def _instrucciones(it):
    if it.get("seguridad"):
        st.warning(f"⚠️ **Seguridad:** {it['seguridad']}")
    with st.expander("📘 Cómo se hace", expanded=True):
        fotos_paso = [f for f in it["fotos"] if f.get("tipo") == "paso"]
        for f in [f for f in fotos_paso if f.get("paso_orden") is None]:
            _mostrar_foto(f)
        if it["pasos"]:
            for p in it["pasos"]:
                st.markdown(f"**{p['orden']}.** {p['texto']}")
                for f in [f for f in fotos_paso if f.get("paso_orden") == p["orden"]]:
                    _mostrar_foto(f)
        else:
            st.info("Todavía no hay instrucciones cargadas para este control. Consultá con tu supervisor.")
        ok = [f for f in it["fotos"] if f.get("tipo") == "ok"]
        mal = [f for f in it["fotos"] if f.get("tipo") == "mal"]
        if ok or mal:
            ca, cb = st.columns(2)
            with ca:
                if ok:
                    st.markdown("**✅ Así debe verse**")
                    for f in ok:
                        _mostrar_foto(f)
            with cb:
                if mal:
                    st.markdown("**❌ Así NO debe verse**")
                    for f in mal:
                        _mostrar_foto(f)
        if it.get("herramientas"):
            st.caption(f"🧰 Herramientas: {it['herramientas']}")
    if it.get("criterio"):
        st.info(f"🎯 **Está bien si:** {it['criterio']}")


def _control(zona, rutinas):
    s = st.session_state
    por_id = {r["id"]: r for r in rutinas}
    cola = s["rp_cola"]
    idx = s["rp_idx"]
    it = por_id[cola[idx]]
    previo = s["rp_resp"].get(it["id"], {"puntos": {}, "comentario": "", "foto": None})
    st.progress(idx / len(cola), text=f"Control {idx + 1} de {len(cola)}")
    st.subheader(f"{it.get('codigo') or ''} · {it['titulo']}".strip(" ·"))
    st.caption(("Semanal" if it.get("frecuencia") == "Semanal" else "Diaria") + (f" · ~{it['duracion_min']} min" if it.get("duracion_min") else "")
               + (f" · {it['condicion']}" if it.get("condicion") else ""))
    _instrucciones(it)

    st.markdown("### Tu respuesta")
    puntos = it["puntos"]
    respuestas = {}
    for p in (puntos or [None]):
        pid = p["id"] if p else None
        ant = previo["puntos"].get(pid, {})
        k = f"rp_{it['id']}_{pid}"
        if p is None or p["tipo"] != "numero":
            etiqueta = p["texto"] if p else "¿Está todo OK en este control?"
            nombres = list(OPCIONES)
            idx_prev = next((i for i, n in enumerate(nombres) if OPCIONES[n] == ant.get("resultado")), None)
            elegido = st.radio(etiqueta, nombres, index=idx_prev, horizontal=True, key=k)
            respuestas[pid] = {"resultado": OPCIONES.get(elegido)}
        else:
            u = f" ({p['unidad']})" if p.get("unidad") else ""
            rango = R.texto_rango(p)
            c1, c2 = st.columns([0.65, 0.35])
            valor = c1.number_input(f"{p['texto']}{u}", value=ant.get("valor"), step=0.1, format="%g", key=k, help=f"Permitido: {rango}" if rango else None)
            na = c2.checkbox("No aplica", value=ant.get("resultado") == "NA", key=k + "_na")
            if rango:
                c1.caption(f"Permitido: {rango}")
            respuestas[pid] = {"resultado": "NA"} if na else {"valor": valor}
            if not na and valor is not None and R.fuera_de_rango(p, valor):
                st.error(f"⚠️ {R.fmt_num(valor)}{u} está FUERA del rango permitido ({rango}).")

    foto_prev = previo.get("foto")
    sin_foto_eval = bool(foto_prev)
    ev0 = R.evaluar_item(it, puntos, respuestas, "x" * 3, sin_foto_eval)
    hay_problema = bool(ev0["problemas"])
    comentario = st.text_area("¿Qué viste? (obligatorio si hay un problema)" if hay_problema else "Comentario (opcional)", value=previo.get("comentario", ""), key=f"rp_{it['id']}_com")
    archivo = st.file_uploader("📷 Foto del problema (o de evidencia)", type=["jpg", "jpeg", "png"], key=f"rp_{it['id']}_foto")
    foto = foto_prev
    if archivo is not None:
        try:
            foto = R.preparar_foto(archivo.getvalue())[0]
        except Exception:
            st.error("No se pudo leer esa foto. Probá con otra.")
    elif foto_prev:
        st.caption("📷 Ya hay una foto guardada para este control.")
    ev = R.evaluar_item(it, puntos, respuestas, comentario, bool(foto))
    if ev["problemas"]:
        if it.get("maquina_id"):
            st.warning("Hay un problema: al enviar la ronda se le avisa automáticamente a mantenimiento.")
        else:
            st.warning("Hay un problema: queda registrado en la ronda (este control no tiene un equipo asociado para avisar automáticamente).")
    for f in ev["faltan"]:
        st.caption(f"👉 {f}")

    def guardar():
        s["rp_resp"][it["id"]] = {"puntos": respuestas, "comentario": comentario, "foto": foto}

    b1, b2 = st.columns(2)
    if idx > 0 and b1.button("⬅️ Anterior", key=f"rp_ant_{it['id']}"):
        guardar()
        s["rp_idx"] = idx - 1
        st.rerun()
    etiqueta_sig = "Guardar y seguir ➡️" if idx + 1 < len(cola) else "Guardar y revisar ✅"
    if b2.button(etiqueta_sig, type="primary", disabled=bool(ev["faltan"]), key=f"rp_sig_{it['id']}"):
        guardar()
        if idx + 1 < len(cola):
            s["rp_idx"] = idx + 1
        else:
            s["rp_fase"] = "resumen"
        st.rerun()
    if st.button("Cancelar la ronda", key=f"rp_cancel_{it['id']}"):
        _reiniciar(todo=False)
        st.rerun()


# ----------------------------------------------------------------
# 4. Resumen y envío
# ----------------------------------------------------------------
def _evaluar_guardado(it, guardado):
    return R.evaluar_item(it, it["puntos"], guardado["puntos"], guardado.get("comentario", ""), bool(guardado.get("foto")))


def _resumen(zona, rutinas):
    s = st.session_state
    por_id = {r["id"]: r for r in rutinas}
    st.subheader("Revisá antes de enviar")
    hay = []
    for iid in s["rp_cola"]:
        it, g = por_id[iid], s["rp_resp"].get(iid)
        if not g:
            continue
        ev = _evaluar_guardado(it, g)
        with st.container(border=True):
            st.markdown(f"{ICONO[ev['resultado']]} **{it.get('codigo') or ''} {it['titulo']}** — {R.ETIQUETA_RESULTADO[ev['resultado']]}")
            for p in ev["problemas"]:
                st.markdown(f"&nbsp;&nbsp;&nbsp;❌ {p}")
            if g.get("comentario"):
                st.caption(g["comentario"])
        if ev["resultado"] == "NO_OK":
            hay.append(it)
    if hay:
        avisables = [i for i in hay if i.get("maquina_id")]
        st.warning(f"Se va a avisar a mantenimiento de {len(avisables)} problema(s)." if avisables else "Hay problemas anotados.")
    b1, b2 = st.columns(2)
    if b1.button("⬅️ Volver", key="rp_volver"):
        s["rp_fase"], s["rp_idx"] = "ronda", len(s["rp_cola"]) - 1
        st.rerun()
    if b2.button("✅ Enviar ronda", type="primary", key="rp_enviar"):
        _enviar(zona, por_id)


def _enviar(zona, por_id):
    s = st.session_state
    sesion = s["rp_sesion"]
    try:
        with st.spinner("Enviando…"):
            payload = []
            for iid in s["rp_cola"]:
                it, g = por_id[iid], s["rp_resp"].get(iid)
                if not g:
                    continue
                if g.get("foto") and iid not in s["rp_rutas"]:
                    s["rp_rutas"][iid] = DB.subir_evidencia(zona["id"], g["foto"])
                payload.append(R.armar_respuesta(it, zona["nombre"], _evaluar_guardado(it, g), g.get("comentario", ""), s["rp_rutas"].get(iid)))
            r = DB.guardar_ronda(sesion["token"], s["rp_uuid"], zona["id"], R.hoy_paraguay(), payload) or {}
    except Exception as e:
        st.error(f"No se pudo enviar: {e}. Tus respuestas siguen acá: tocá «Enviar ronda» de nuevo.")
        return
    if r.get("estado") == "ok":
        s["rp_final"] = {"fallas": len(r.get("fallas") or []), "controles": len(payload)}
        s["rp_fase"] = "fin"
        st.cache_data.clear()
        st.rerun()
    elif r.get("estado") == "sesion_invalida":
        s.pop("rp_sesion", None)
        st.error("Tu sesión venció. Entrá de nuevo con tu PIN (tus respuestas se conservan).")
        st.rerun()
    else:
        st.error("No se pudo guardar la ronda. Probá de nuevo.")


def _fin():
    s = st.session_state
    f = s.get("rp_final", {"fallas": 0, "controles": 0})
    st.success(f"✅ Ronda enviada ({f['controles']} controles). ¡Gracias, {s['rp_sesion']['nombre']}!")
    if f["fallas"]:
        st.warning(f"Se le avisó a mantenimiento de {f['fallas']} problema(s).")
    if st.button("Volver a la lista", type="primary", key="rp_volver_lista"):
        _reiniciar(todo=False)
        st.rerun()
