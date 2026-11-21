import streamlit as st
from database.conection import insert_falla, update_falla, get_fallas
from views import ui

def render_fallas():
    ui.encabezado("Fallas y RCA", "Registro de fallas y análisis de causa raíz (5 porqués, Ishikawa).")

    if not st.session_state.maquinas:
        ui.estado_vacio("Todavía no hay máquinas cargadas.")
        return

    # Detalle de una falla (análisis RCA)
    if st.session_state.get("falla_abierta_id"):
        render_falla_detalle(st.session_state.falla_abierta_id)
        return

    dict_m = {m["id"]: m["nombre"] for m in st.session_state.maquinas}
    with st.expander("Registrar nueva falla"):
        with st.form("form_nueva_falla", clear_on_submit=True):
            maquina_id = st.selectbox("Máquina *", list(dict_m.keys()), index=None, placeholder="Escribí para buscar",
                                      format_func=lambda x: dict_m[x])
            c1, c2 = st.columns(2)
            fecha = c1.date_input("Fecha", value=ui.hoy(), format="DD/MM/YYYY")
            tecnico = c2.text_input("Técnico asignado")
            sintomas = st.text_input("Síntomas previos", placeholder="¿Hubo algún aviso antes?")
            descripcion = st.text_area("Descripción de la falla *", placeholder="¿Qué ocurrió y qué daños se observan?")
            if st.form_submit_button("Registrar falla", type="primary"):
                if maquina_id is None or not descripcion.strip():
                    st.error("Elegí la máquina y describí la falla.")
                else:
                    insert_falla({
                        "maquina_id": maquina_id, "fecha_deteccion": fecha.strftime("%Y-%m-%d"), "tecnico": tecnico,
                        "sintomas": sintomas, "descripcion": descripcion, "estado": "Abierta",
                        "metodo_rca": None, "rca": {}, "causa_raiz": "", "accion": ""
                    })
                    st.session_state.fallas = get_fallas()
                    st.success("Falla registrada.")
                    st.rerun()

    fallas = st.session_state.fallas
    if not fallas:
        ui.estado_vacio("No hay fallas registradas.")
        return
    filtro = st.pills("Estado", ["Abiertas", "Cerradas", "Todas"], default="Abiertas", key="fallas_filtro",
                      label_visibility="collapsed") or "Abiertas"
    lista = [f for f in fallas if filtro == "Todas" or (f.get("estado") == "Cerrada") == (filtro == "Cerradas")]
    lista = sorted(lista, key=lambda f: str(f.get("fecha_deteccion") or ""), reverse=True)
    if not lista:
        st.caption("No hay fallas con este filtro.")
    for f in lista:
        with st.container(border=True):
            c1, c2 = st.columns([5, 1.4], vertical_alignment="center")
            c1.markdown(f"**{ui.texto_md(dict_m.get(f.get('maquina_id'), 'Máquina'))}** · {ui.fecha_corta(f.get('fecha_deteccion'))} "
                        f"{ui.etiqueta_estado(f.get('estado'))}  \n{ui.texto_md((f.get('descripcion') or '')[:120])}")
            if c2.button("Analizar" if f.get("estado") != "Cerrada" else "Ver análisis", key=f"view_{f.get('id')}",
                         use_container_width=True):
                st.session_state.falla_abierta_id = f.get("id")
                st.rerun()


def render_falla_detalle(falla_id):
    falla = next((f for f in st.session_state.fallas if f["id"] == falla_id), None)
    if not falla:
        st.session_state.falla_abierta_id = None
        st.rerun()
        
    if st.button("← Volver al listado", type="tertiary"):
        st.session_state.falla_abierta_id = None
        st.rerun()
        
    dict_m = {m["id"]: m for m in st.session_state.maquinas}
    m = dict_m.get(falla.get("maquina_id"), {})
    
    st.subheader(f"Análisis Falla: {m.get('nombre', '—')}")
    st.info(f"**Descripción:** {ui.texto_md(falla.get('descripcion'))}\n\n**Fecha:** {ui.fecha_corta(falla.get('fecha_deteccion'))} · **Técnico:** {ui.texto_md(falla.get('tecnico') or '—')}")
    
    # 1. Selección de metodología RCA
    metodo = falla.get("metodo_rca")
    if not metodo:
        st.write("### Seleccione el método de análisis de causa raíz")
        c1, c2 = st.columns(2)
        if c1.button("5 Porqués (Fallas Directas)"):
            update_falla(falla_id, {"metodo_rca": "5porques", "estado": "En análisis"})
            st.session_state.fallas = get_fallas()
            st.rerun()
        if c2.button("Ishikawa (6M - Complejas)"):
            update_falla(falla_id, {"metodo_rca": "ishikawa", "estado": "En análisis"})
            st.session_state.fallas = get_fallas()
            st.rerun()
            
    # 2. Renderizado dinámico de la estructura JSONB guardada en Supabase
    else:
        rca_data = falla.get("rca") or {}
        is_closed = falla.get("estado") == "Cerrada"
        
        with st.form("form_rca_execution"):
            st.write(f"### Análisis mediante: {metodo.upper()}")
            
            if metodo == "5porques":
                p1 = st.text_input("Por qué 1", value=rca_data.get("porque1", ""), disabled=is_closed)
                p2 = st.text_input("Por qué 2", value=rca_data.get("porque2", ""), disabled=is_closed)
                p3 = st.text_input("Por qué 3", value=rca_data.get("porque3", ""), disabled=is_closed)
                p4 = st.text_input("Por qué 4", value=rca_data.get("porque4", ""), disabled=is_closed)
                p5 = st.text_input("Por qué 5", value=rca_data.get("porque5", ""), disabled=is_closed)
                new_rca = {"porque1": p1, "porque2": p2, "porque3": p3, "porque4": p4, "porque5": p5}
            else:
                m1 = st.text_input("Método", value=rca_data.get("metodo", ""), disabled=is_closed)
                m2 = st.text_input("Máquina", value=rca_data.get("maquina", ""), disabled=is_closed)
                m3 = st.text_input("Mano de Obra", value=rca_data.get("manoObra", ""), disabled=is_closed)
                m4 = st.text_input("Material", value=rca_data.get("material", ""), disabled=is_closed)
                m5 = st.text_input("Medición", value=rca_data.get("medicion", ""), disabled=is_closed)
                m6 = st.text_input("Medio Ambiente", value=rca_data.get("medioAmbiente", ""), disabled=is_closed)
                new_rca = {"metodo": m1, "maquina": m2, "manoObra": m3, "material": m4, "medicion": m5, "medioAmbiente": m6}
                
            st.write("### Conclusión y Cierre de Orden")
            causa_raiz = st.text_area("Causa Raíz Identificada *", value=falla.get("causa_raiz", ""), disabled=is_closed)
            accion = st.text_area("Acción Correctiva / Preventiva *", value=falla.get("accion", ""), disabled=is_closed)
            
            if not is_closed:
                save_rca = st.form_submit_button("Cerrar falla", type="primary")
                if save_rca:
                    if not causa_raiz.strip() or not accion.strip():
                        st.error("Debe definir la causa raíz y las acciones correspondientes para el cierre.")
                    else:
                        patch = {"rca": new_rca, "causa_raiz": causa_raiz, "accion": accion, "estado": "Cerrada"}
                        update_falla(falla_id, patch)
                        st.session_state.fallas = get_fallas()
                        st.success("Falla analizada y archivada correctamente.")
                        st.session_state.falla_abierta_id = None
                        st.rerun()
            else:
                st.form_submit_button("Falla cerrada", disabled=True)
                st.success("Esta falla está cerrada.")
