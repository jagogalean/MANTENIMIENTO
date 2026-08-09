import streamlit as st
from datetime import datetime


def _dias_desde(fecha_iso):
    try:
        fecha = datetime.fromisoformat(fecha_iso.replace("Z", "+00:00")).date()
        return (datetime.now().date() - fecha).days
    except (TypeError, ValueError, AttributeError):
        return None


def _dias_hasta(fecha_str, formato="%Y-%m-%d"):
    try:
        fecha = datetime.strptime(fecha_str, formato).date()
        return (fecha - datetime.now().date()).days
    except (TypeError, ValueError):
        return None


def construir_agenda_del_dia():
    """Arma la lista priorizada de lo que hay que atender hoy, sin IA (fuente de verdad)."""
    maquinas = st.session_state.get("maquinas", [])
    ots = st.session_state.get("ots", [])
    repuestos = st.session_state.get("repuestos", [])
    terceros = st.session_state.get("terceros", [])
    planes = st.session_state.get("planes", [])

    map_maquina = {m["id"]: m for m in maquinas}
    tareas = []

    # 1. OTs pendientes (más peso si la máquina es crítica, si lleva días abierta, o si falta permiso de trabajo)
    for o in ots:
        if o.get("estado") == "Completada":
            continue
        maquina = map_maquina.get(o.get("maquina_id"), {})
        dias_abierta = _dias_desde(o.get("fecha_inicio"))

        prioridad = 0
        if maquina.get("criticidad") == "A":
            prioridad += 2
        if dias_abierta is not None and dias_abierta >= 3:
            prioridad += 1
        if o.get("requiere_permiso_trabajo") and not o.get("permiso_trabajo_emitido"):
            prioridad += 2

        tareas.append({
            "prioridad": prioridad,
            "categoria": "🛠️ OT Pendiente",
            "texto": f"{o.get('codigo')} — {maquina.get('nombre', 'Máquina desconocida')} "
                     f"({o.get('estado')}, abierta hace {dias_abierta if dias_abierta is not None else '?'} día(s))"
                     + (" · ⚠️ falta permiso de trabajo" if o.get("requiere_permiso_trabajo") and not o.get("permiso_trabajo_emitido") else ""),
            "alerta": prioridad >= 3
        })

    # 2. Plan preventivo vencido o por vencer en 7 días
    for p in planes:
        dias = _dias_hasta(p.get("proxima_ejecucion"))
        if dias is None or dias > 7:
            continue
        maquina = map_maquina.get(p.get("maquina_id"), {})
        vencida = dias < 0
        tareas.append({
            "prioridad": 3 if vencida else 1,
            "categoria": "🗓️ Plan Preventivo",
            "texto": f"{maquina.get('nombre', 'Máquina desconocida')} — {p.get('nombre_plan')} "
                     f"({'vencida hace ' + str(-dias) + ' día(s)' if vencida else 'vence en ' + str(dias) + ' día(s)'})",
            "alerta": vencida
        })

    # 3. Repuestos en stock crítico
    for r in repuestos:
        if r.get("stock_actual", 0) <= r.get("stock_minimo", 0):
            tareas.append({
                "prioridad": 2,
                "categoria": "📦 Stock Crítico",
                "texto": f"{r.get('nombre')} — stock actual {r.get('stock_actual')} (mínimo {r.get('stock_minimo')})",
                "alerta": True
            })

    # 4. Vencimientos de terceros/contratos en los próximos 30 días
    for t in terceros:
        dias = _dias_hasta(t.get("proximoVencimiento"))
        if dias is None or dias > 30:
            continue
        vencido = dias < 0
        tareas.append({
            "prioridad": 2 if vencido else 0,
            "categoria": "🚚 Contrato / Tercero",
            "texto": f"{t.get('nombre') or t.get('equipo')} — "
                     f"{'vencido hace ' + str(-dias) + ' día(s)' if vencido else 'vence en ' + str(dias) + ' día(s)'}",
            "alerta": vencido
        })

    tareas.sort(key=lambda x: x["prioridad"], reverse=True)
    return tareas


def generar_resumen_ia(tareas):
    """Redacta la agenda con Gemini. Si falta librería o API key, avisa sin romper la app."""
    try:
        import google.generativeai as genai
    except ImportError:
        return "⚠️ Falta instalar 'google-generativeai'. Agregalo a requirements.txt para activar el resumen con IA."

    api_key = st.secrets.get("GEMINI_API_KEY", "")
    if not api_key:
        return "⚠️ Falta configurar GEMINI_API_KEY en los secrets de Streamlit Cloud para activar el resumen con IA."

    genai.configure(api_key=api_key)
    # Revisá en Google AI Studio si hay un modelo más nuevo disponible; este es el rápido/económico.
    modelo = genai.GenerativeModel("gemini-2.0-flash")

    lista_texto = "\n".join([f"- [{t['categoria']}] {t['texto']}" for t in tareas]) or "Sin pendientes."

    prompt = f"""Sos un asistente para un coordinador de mantenimiento industrial en Paraguay.
Con esta lista de pendientes de hoy, escribí un resumen breve (máximo 6 líneas), en español,
tono directo y profesional, agrupando por prioridad y sugiriendo por dónde arrancar el día.
No inventes datos que no estén en la lista.

Pendientes de hoy:
{lista_texto}
"""
    try:
        respuesta = modelo.generate_content(prompt)
        return respuesta.text
    except Exception as e:
        return f"⚠️ No se pudo generar el resumen con IA: {e}"


def render_asistente():
    st.title("🧭 Asistente del Día")
    hoy = datetime.now().strftime("%d/%m/%Y")
    st.write(f"Agenda priorizada para hoy · {hoy}")

    tareas = construir_agenda_del_dia()

    if not tareas:
        st.success("✅ No hay pendientes urgentes registrados. Buen momento para avanzar en el plan preventivo.")
        return

    urgentes = [t for t in tareas if t["alerta"]]
    st.markdown(f"##### 🔴 {len(urgentes)} ítem(s) urgente(s) de {len(tareas)} totales")

    if st.button("🤖 Generar resumen narrado con IA"):
        with st.spinner("Redactando resumen..."):
            resumen = generar_resumen_ia(tareas)
        st.info(resumen)

    st.markdown("---")
    for t in tareas:
        color = "#EF4444" if t["alerta"] else "#38BDF8"
        st.markdown(f"""
        <div class='industrial-panel' style='border-color:{color};'>
            <small style='color:{color}; font-weight:bold;'>{t['categoria']}</small><br>
            <span>{t['texto']}</span>
        </div>
        """, unsafe_allow_html=True)
