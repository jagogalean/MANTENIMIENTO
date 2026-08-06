import streamlit as st
import base64
import calendar
from io import BytesIO
from datetime import datetime, date, timedelta

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from openpyxl.drawing.image import Image as XLImage

MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
         "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
DIAS_SEMANA_ABR = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


def _dias_programados_en_mes(ultima_ejecucion_str, frecuencia_dias, anio, mes):
    """Devuelve el conjunto de números de día del mes en que cae la tarea,
    proyectando hacia adelante desde la última ejecución (o desde el día 1
    del mes si nunca se ejecutó) en pasos de 'frecuencia_dias'."""
    primer_dia_mes = date(anio, mes, 1)
    ultimo_dia_num = calendar.monthrange(anio, mes)[1]
    fin_mes = date(anio, mes, ultimo_dia_num)

    if not frecuencia_dias or frecuencia_dias <= 0:
        return set()

    if ultima_ejecucion_str:
        try:
            ancla = datetime.strptime(ultima_ejecucion_str, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            ancla = primer_dia_mes
    else:
        ancla = primer_dia_mes

    # Adelantar el ancla hasta la primera ocurrencia dentro o después del mes buscado
    if ancla < primer_dia_mes:
        pasos = (primer_dia_mes - ancla).days // frecuencia_dias
        cursor = ancla + timedelta(days=pasos * frecuencia_dias)
        while cursor < primer_dia_mes:
            cursor += timedelta(days=frecuencia_dias)
    else:
        cursor = ancla

    dias = set()
    while cursor <= fin_mes:
        if cursor >= primer_dia_mes:
            dias.add(cursor.day)
        cursor += timedelta(days=frecuencia_dias)
    return dias


def generar_excel_calendario_preventivo(tareas, anio, mes, nombre_empresa="", logo_bytes=None, titulo_maquina="Todas las Máquinas"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Preventivo"

    ultimo_dia = calendar.monthrange(anio, mes)[1]

    col_actividad, col_maquina, col_frecuencia, primera_col_dia = 1, 2, 3, 4
    ultima_col_dia = primera_col_dia + ultimo_dia - 1

    fill_header = PatternFill("solid", fgColor="12171B")
    fill_finde = PatternFill("solid", fgColor="FDE68A")
    fill_abr = PatternFill("solid", fgColor="E5E9EC")
    fill_marcado = PatternFill("solid", fgColor="38BDF8")

    # --- Título y membrete ---
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ultima_col_dia)
    celda_titulo = ws.cell(row=1, column=1, value=f"Programa de Mantenimientos Preventivos — {titulo_maquina}")
    celda_titulo.font = Font(size=15, bold=True)
    celda_titulo.alignment = Alignment(horizontal="center")

    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=ultima_col_dia)
    celda_sub = ws.cell(row=2, column=1, value=f"{nombre_empresa}  ·  Mes: {MESES[mes - 1]} {anio}" if nombre_empresa else f"Mes: {MESES[mes - 1]} {anio}")
    celda_sub.font = Font(size=11, italic=True)
    celda_sub.alignment = Alignment(horizontal="center")

    if logo_bytes:
        try:
            img_buf = BytesIO(logo_bytes)
            xl_img = XLImage(img_buf)
            xl_img.width = 55
            xl_img.height = 55
            ws.add_image(xl_img, "A1")
        except Exception:
            pass

    ws.row_dimensions[1].height = 28
    ws.row_dimensions[2].height = 18

    # --- Encabezados de tabla ---
    fila_header = 4
    ws.cell(row=fila_header, column=col_actividad, value="Actividad").font = Font(bold=True, color="FFFFFF")
    ws.cell(row=fila_header, column=col_maquina, value="Máquina").font = Font(bold=True, color="FFFFFF")
    ws.cell(row=fila_header, column=col_frecuencia, value="Frecuencia (días)").font = Font(bold=True, color="FFFFFF")
    for c in range(1, col_frecuencia + 1):
        ws.cell(row=fila_header, column=c).fill = fill_header
        ws.merge_cells(start_row=fila_header, start_column=c, end_row=fila_header + 1, end_column=c)
        ws.cell(row=fila_header, column=c).alignment = Alignment(vertical="center", wrap_text=True)

    for i in range(ultimo_dia):
        dia_num = i + 1
        fecha = date(anio, mes, dia_num)
        col = primera_col_dia + i
        es_finde = fecha.weekday() >= 5

        celda_num = ws.cell(row=fila_header, column=col, value=dia_num)
        celda_num.alignment = Alignment(horizontal="center")
        celda_num.fill = fill_finde if es_finde else fill_header
        celda_num.font = Font(bold=True, size=9, color="000000" if es_finde else "FFFFFF")

        celda_abr = ws.cell(row=fila_header + 1, column=col, value=DIAS_SEMANA_ABR[fecha.weekday()])
        celda_abr.alignment = Alignment(horizontal="center")
        celda_abr.font = Font(size=8, italic=True)
        celda_abr.fill = fill_finde if es_finde else fill_abr

        ws.column_dimensions[get_column_letter(col)].width = 4

    # --- Filas de tareas ---
    fila_actual = fila_header + 2
    for t in tareas:
        ws.cell(row=fila_actual, column=col_actividad, value=t["tarea"])
        ws.cell(row=fila_actual, column=col_maquina, value=t["maquina"])
        ws.cell(row=fila_actual, column=col_frecuencia, value=t["frecuencia_dias"])

        dias_marcados = _dias_programados_en_mes(t.get("ultima_ejecucion"), t["frecuencia_dias"], anio, mes)
        for i in range(ultimo_dia):
            dia_num = i + 1
            col = primera_col_dia + i
            if dia_num in dias_marcados:
                celda = ws.cell(row=fila_actual, column=col, value="X")
                celda.fill = fill_marcado
                celda.alignment = Alignment(horizontal="center")
                celda.font = Font(bold=True)
        fila_actual += 1

    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 20
    ws.column_dimensions["C"].width = 14
    ws.freeze_panes = ws.cell(row=fila_header + 2, column=primera_col_dia)

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


def render_calendario():
    st.title("📅 Calendario de Mantenimiento Preventivo")
    st.write("Generá el programa mensual tipo Gantt — por una máquina o para todas juntas.")

    maquinas = st.session_state.get("maquinas", [])
    planes = st.session_state.get("planes", [])

    if not maquinas:
        st.warning("Registrá al menos una máquina primero.")
        return
    if not planes:
        st.warning("Todavía no hay tareas cargadas en '🗓️ Plan Preventivo'. Cargá al menos una para poder generar el calendario.")
        return

    dict_maquinas = {m["nombre"]: m["id"] for m in maquinas}
    opciones_maquina = ["Todas las Máquinas"] + list(dict_maquinas.keys())

    col1, col2, col3 = st.columns(3)
    maquina_sel = col1.selectbox("Máquina", opciones_maquina)
    mes_sel = col2.selectbox("Mes", list(range(1, 13)), index=datetime.now().month - 1, format_func=lambda m: MESES[m - 1])
    anio_sel = col3.number_input("Año", min_value=2020, max_value=2100, value=datetime.now().year, step=1)

    config_empresa = st.session_state.get("config_empresa", {}) or {}
    nombre_empresa = config_empresa.get("nombre_empresa", "") or ""
    logo_bytes = base64.b64decode(config_empresa["logo_base64"]) if config_empresa.get("logo_base64") else None
    if not nombre_empresa and not logo_bytes:
        st.caption("💡 Podés cargar el logo y nombre de tu empresa una sola vez en '📑 Reportes' → Membrete, y se va a usar acá también.")

    if st.button("📥 Generar Calendario"):
        map_m_nombre = {m["id"]: m["nombre"] for m in maquinas}

        if maquina_sel == "Todas las Máquinas":
            tareas_filtradas = planes
            titulo_maquina = "Todas las Máquinas"
        else:
            m_id = dict_maquinas[maquina_sel]
            tareas_filtradas = [p for p in planes if p.get("maquina_id") == m_id]
            titulo_maquina = maquina_sel

        if not tareas_filtradas:
            st.warning("No hay tareas de plan preventivo para esa máquina.")
            return

        tareas_data = [{
            "tarea": t.get("tarea"),
            "maquina": map_m_nombre.get(t.get("maquina_id"), "?"),
            "frecuencia_dias": t.get("frecuencia_dias", 30),
            "ultima_ejecucion": t.get("ultima_ejecucion")
        } for t in tareas_filtradas]

        buffer = generar_excel_calendario_preventivo(tareas_data, anio_sel, mes_sel, nombre_empresa, logo_bytes, titulo_maquina)
        st.download_button(
            "⬇️ Descargar Calendario_Preventivo.xlsx",
            data=buffer,
            file_name=f"Calendario_Preventivo_{anio_sel}_{mes_sel:02d}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        st.success("✅ Calendario generado.")