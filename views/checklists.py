"""
Recepción y entrega de máquina: checklist de turno de primer nivel.
Si se llega escaneando el QR de la máquina, el formulario se abre con esa máquina elegida.
"""
import pandas as pd
import streamlit as st

from database.conection import insert_checklist, delete_checklist, get_checklists
from views import ui

ESTADOS = ["Funcionando", "Parada", "Con observaciones"]


def render_checklists():
    usuario = st.session_state.get("usuario_actual") or {}
    ui.encabezado("Recepción y entrega", "Registro del estado de la máquina al recibirla y al entregarla en cada turno.")

    maquinas = st.session_state.get("maquinas", [])
    if not maquinas:
        ui.estado_vacio("Todavía no hay máquinas cargadas.")
        return
    mapa = {m["id"]: m["nombre"] for m in maquinas}
    ids = list(mapa.keys())

    mensaje = st.session_state.pop("chk_mensaje", None)
    if mensaje:
        st.success(mensaje)

    qr_raw = st.session_state.get("qr_maquina_id")
    indice = None
    if qr_raw is not None:
        try:
            qr_id = int(qr_raw) if ids and isinstance(ids[0], int) else qr_raw
            indice = ids.index(qr_id) if qr_id in ids else None
        except (ValueError, TypeError):
            indice = None

    with st.expander("Nuevo registro de turno", expanded=qr_raw is not None):
        with st.form("form_checklist", clear_on_submit=True):
            maquina_id = st.selectbox("Máquina *", ids, index=indice, placeholder="Escribí para buscar",
                                      format_func=lambda x: mapa[x])
            ahora = ui.ahora()
            c1, c2 = st.columns(2)
            fecha = c1.date_input("Fecha", value=ahora.date(), format="DD/MM/YYYY")
            hora = c2.time_input("Hora", value=ahora.time().replace(second=0, microsecond=0))
            tecnico = st.text_input("Quién inspecciona", value=usuario.get("nombre") or "")
            c3, c4 = st.columns(2)
            recibido = c3.selectbox("Estado al recibir", ESTADOS)
            entregado = c4.selectbox("Estado al entregar", ESTADOS)
            with st.expander("Mediciones (opcional)"):
                c5, c6, c7 = st.columns(3)
                vibracion = c5.text_input("Vibración (mm/s)")
                temperatura = c6.text_input("Temperatura (°C)")
                presion = c7.text_input("Presión (bar)")
            repuestos = st.text_input("Repuestos usados")
            observaciones = st.text_area("Observaciones")
            conformidad = st.checkbox("El operador está conforme con la entrega")
            guardar = st.form_submit_button("Guardar registro", type="primary", use_container_width=True)
        if guardar:
            if maquina_id is None:
                st.error("Elegí la máquina.")
            else:
                try:
                    insert_checklist({
                        "maquina_id": maquina_id, "fecha": fecha.strftime("%Y-%m-%d"), "hora": hora.strftime("%H:%M"),
                        "tecnico": tecnico, "estado_recibido": recibido, "estado_entregado": entregado,
                        "vibracion": vibracion, "temperatura": temperatura, "presion": presion,
                        "repuestos": repuestos, "observaciones": observaciones, "conformidad": conformidad,
                    })
                except Exception as e:
                    ui.error_amigable("No se pudo guardar el registro.", e)
                else:
                    st.session_state.checklists = get_checklists()
                    st.session_state.pop("qr_maquina_id", None)
                    st.session_state.pop("forzar_vista", None)
                    st.query_params.clear()
                    st.session_state["chk_mensaje"] = "Registro guardado."
                    st.rerun()

    registros = st.session_state.get("checklists", [])
    if not registros:
        ui.estado_vacio("Todavía no hay registros de recepción y entrega.")
        return

    filtro = st.selectbox("Máquina", [None] + ids, format_func=lambda x: "Todas las máquinas" if x is None else mapa[x],
                          key="chk_filtro", label_visibility="collapsed")
    lista = [c for c in registros if filtro is None or c.get("maquina_id") == filtro]
    lista = sorted(lista, key=lambda c: (str(c.get("fecha") or ""), str(c.get("hora") or "")), reverse=True)
    df = pd.DataFrame([{
        "id": c.get("id"), "Fecha": ui.fecha_corta(c.get("fecha")), "Hora": c.get("hora"),
        "Máquina": mapa.get(c.get("maquina_id"), "—"), "Inspeccionó": c.get("tecnico") or "—",
        "Recibida": c.get("estado_recibido"), "Entregada": c.get("estado_entregado"),
        "Conforme": "Sí" if c.get("conformidad") else "No", "Observaciones": (c.get("observaciones") or "")[:60],
    } for c in lista])
    evento = st.dataframe(df, hide_index=True, use_container_width=True, on_select="rerun", selection_mode="single-row",
                          key="chk_tabla", column_order=[c for c in df.columns if c != "id"])

    # Borrar: solo el coordinador, con confirmación
    if usuario.get("rol") == "admin":
        filas = evento.selection.rows if evento and evento.selection else []
        if filas and filas[0] < len(df):
            fila = df.iloc[filas[0]]
            valor = fila["id"]
            cid = valor.item() if hasattr(valor, "item") else valor
            if ui.boton_confirmar("Borrar registro seleccionado", f"del_c_{cid}",
                                  f"¿Borrar el registro de **{ui.texto_md(fila['Máquina'])}** del {fila['Fecha']}?",
                                  texto_confirmar="Sí, borrar"):
                delete_checklist(cid)
                st.session_state.checklists = get_checklists()
                st.session_state["chk_mensaje"] = "Registro borrado."
                st.rerun()
        else:
            st.caption("Para borrar un registro, seleccionalo en la tabla.")
