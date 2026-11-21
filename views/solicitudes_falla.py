"""
Avisos QR: lo que reporta cualquier persona que escanea el QR de una máquina,
sin iniciar sesión. Se revisan acá y se convierten en OT o se descartan.
Todo el texto que escribe el público se muestra escapado (sin HTML ni enlaces).
"""
import streamlit as st

from database.conection import supabase
from database import ots_servicio as S
from views import ui

ORDEN_PRIORIDAD = {"Alta": 0, "Media": 1, "Baja": 2}
COLOR_PRIORIDAD = {"Alta": "red", "Media": "orange", "Baja": "gray"}


def get_solicitudes_falla():
    response = supabase.table("solicitudes_falla").select("*").order("fecha_reporte", desc=True).execute()
    return response.data


def update_solicitud_falla(solicitud_id, patch: dict):
    response = supabase.table("solicitudes_falla").update(patch).eq("id", solicitud_id).execute()
    return response.data


def _convertir(s):
    operario = (s.get("operario") or "").strip()
    texto = str(s.get("descripcion") or "")
    parada = texto.startswith(S.MARCA_PARADA)
    if parada:
        texto = texto[len(S.MARCA_PARADA):].strip()
    descripcion = f"[Aviso QR{' de ' + operario if operario else ''}] {texto}"
    codigo, _ = S.crear_ot({
        "maquina_id": s.get("equipo_id"),
        "tipo_mantenimiento": "Correctivo",
        "descripcion": S.con_marca_parada(descripcion, parada),
        "estado": "Pendiente",
        "tecnico_id": None,
        "origen": "qr_publico",
    })
    nueva = next((o for o in st.session_state.get("ots", []) if o.get("codigo") == codigo), None)
    update_solicitud_falla(s.get("id"), {"estado": "Convertido a OT", "ot_id": nueva.get("id") if nueva else None})
    return codigo


def render_solicitudes_falla(mostrar_titulo=True):
    if mostrar_titulo:
        ui.encabezado("Avisos QR", "Avisos enviados desde el QR de cada máquina, sin iniciar sesión.")
    else:
        st.caption("Avisos enviados desde el QR de cada máquina. Convertilos en OT o descartalos.")

    mapa_maq = {m["id"]: m.get("nombre") for m in st.session_state.get("maquinas", [])}
    try:
        solicitudes = get_solicitudes_falla()
    except Exception as e:
        ui.error_amigable("No se pudieron leer los avisos QR.", e)
        return

    pendientes = sorted([s for s in solicitudes if s.get("estado") == "Pendiente"],
                        key=lambda s: (not str(s.get("descripcion") or "").startswith(S.MARCA_PARADA),
                                       ORDEN_PRIORIDAD.get(s.get("prioridad"), 3)))
    gestionados = [s for s in solicitudes if s.get("estado") != "Pendiente"]

    if not pendientes:
        st.success("No hay avisos pendientes de revisión.")

    for s in pendientes:
        sid = s.get("id")
        texto = str(s.get("descripcion") or "")
        parada = texto.startswith(S.MARCA_PARADA)
        if parada:
            texto = texto[len(S.MARCA_PARADA):].strip()
        prioridad = s.get("prioridad") or "—"
        with st.container(border=True):
            c_txt, c_acc = st.columns([3, 1.4], vertical_alignment="center")
            with c_txt:
                etiquetas = f":{COLOR_PRIORIDAD.get(prioridad, 'gray')}-badge[Prioridad {prioridad}]"
                if parada:
                    etiquetas = ":red-badge[Máquina parada] " + etiquetas
                st.markdown(f"**{ui.texto_md(mapa_maq.get(s.get('equipo_id'), 'Equipo #' + str(s.get('equipo_id'))))}** {etiquetas}")
                st.markdown(ui.texto_md(texto) or "_(sin descripción)_")
                st.caption(f"{str(s.get('fecha_reporte') or '')[:16].replace('T', ' ')} · "
                           f"Avisó: {ui.texto_md(s.get('operario') or 'sin nombre')}")
            with c_acc:
                if st.button("Convertir en OT", key=f"convertir_{sid}", type="primary", use_container_width=True):
                    try:
                        codigo = _convertir(s)
                    except Exception as e:
                        ui.error_amigable("No se pudo crear la OT a partir del aviso.", e)
                    else:
                        st.toast(f"Se creó {codigo} en el backlog compartido.", icon=":material/check_circle:")
                        st.rerun()
                if ui.boton_confirmar("Descartar", f"descartar_{sid}",
                                      "¿Descartar este aviso? No se crea ninguna OT.", texto_confirmar="Sí, descartar",
                                      use_container_width=True):
                    update_solicitud_falla(sid, {"estado": "Descartado"})
                    st.rerun()

    if gestionados:
        with st.expander(f"Avisos ya gestionados ({len(gestionados)})"):
            filas = [{
                "Fecha": str(s.get("fecha_reporte") or "")[:10],
                "Máquina": mapa_maq.get(s.get("equipo_id"), f"#{s.get('equipo_id')}"),
                "Aviso": str(s.get("descripcion") or "").replace(S.MARCA_PARADA, "").strip()[:80],
                "Resultado": s.get("estado"),
            } for s in gestionados]
            st.dataframe(filas, hide_index=True, use_container_width=True)
