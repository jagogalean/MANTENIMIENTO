"""
ESTÁNDAR ÚNICO DE EXCEL — Vitopel · Mantenimiento.

Todo Excel que genere la app se arma con estas funciones, para que todos tengan la misma estructura y la misma marca:

  · Hoja «Leeme» (la portada): marca (logo o nombre), título, quién y cuándo lo generó, período, índice de tablas y cómo usarlo en Power BI.
  · Una hoja por TABLA DE DATOS: títulos en la fila 1, sin celdas combinadas, sin totales ni fórmulas, con fechas y números reales,
    como tabla de Excel con nombre (Power BI la ve directo). Cada hoja lleva la marca en la pestaña (color) y en el encabezado de impresión.
  · Hoja «Calendario» (opcional) y hoja «Diccionario» (qué significa cada columna de cada tabla).
  · Las hojas se relacionan por identificadores (ronda_id, empleado_id, …), nunca por nombres.

Para poner el logo: guardá el archivo como  assets/logo_vitopel.png  (o .jpg) en el repositorio. Si no está, se usa el nombre de la empresa.
Los colores y el nombre se cambian acá abajo (MARCA).
"""
import io
import os
from datetime import datetime, timedelta

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

MARCA = {"empresa": "VITOPEL", "area": "Mantenimiento", "sistema": "MANTENIMIENTO · Gestión de mantenimiento",
         "color": "1F3A5F",          # azul oscuro: encabezados y banda de la portada
         "acento": "F28C28",         # naranja: detalles
         "claro": "EAF0F7",          # fondo suave
         "pestana_datos": "1F3A5F", "pestana_apoyo": "7F8C9B", "pestana_ayuda": "F28C28"}
RUTAS_LOGO = ("assets/logo_vitopel.png", "assets/logo_vitopel.jpg", "assets/logo_vitopel.jpeg", "logo_vitopel.png")

FORMATOS = {"texto": None, "entero": "0", "decimal": "0.00", "fecha": "dd/mm/yyyy", "hora": "hh:mm", "fechahora": "dd/mm/yyyy hh:mm",
            "porcentaje": "0.0", "logico": None}
TIPOS = {"texto": "Texto", "entero": "Número entero", "decimal": "Número decimal", "fecha": "Fecha", "hora": "Hora", "fechahora": "Fecha y hora",
         "porcentaje": "Número (porcentaje, 0 a 100)", "logico": "Verdadero/Falso"}
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def hoy_paraguay():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Asuncion"))
    except Exception:
        return datetime.utcnow() - timedelta(hours=3)


def hora_local(valor):
    """'2026-10-30T17:03:11+00:00' (UTC, como guarda la base) -> datetime en hora de Paraguay, sin zona."""
    if valor in (None, ""):
        return None
    try:
        d = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        return d
    try:
        from zoneinfo import ZoneInfo
        return d.astimezone(ZoneInfo("America/Asuncion")).replace(tzinfo=None)
    except Exception:
        return (d - timedelta(hours=3)).replace(tzinfo=None)


def nombre_archivo(modulo, desde=None, hasta=None):
    """Nombre uniforme: Vitopel_Mantenimiento_<Modulo>_<desde>_<hasta>.xlsx (o con la fecha de hoy si no hay período)."""
    import re
    import unicodedata
    plano = unicodedata.normalize("NFKD", modulo).encode("ascii", "ignore").decode()
    limpio = re.sub(r"[^A-Za-z0-9]+", "_", plano).strip("_")
    if desde and hasta:
        tramo = f"{desde:%Y%m%d}_{hasta:%Y%m%d}"
    else:
        tramo = f"{hoy_paraguay():%Y%m%d}"
    return f"Vitopel_Mantenimiento_{limpio}_{tramo}.xlsx"


def _logo():
    """Logo para el encabezado. Primero busca el archivo en assets/; si no está,
    usa el logo cargado en la app (Reportes → Membrete), así hay UN solo lugar
    donde cambiarlo para todos los Excel y PDF."""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for r in RUTAS_LOGO:
        for raiz in (base, os.getcwd()):
            p = os.path.join(raiz, r)
            if os.path.isfile(p):
                return p
    return _logo_del_membrete()


def _logo_del_membrete():
    try:
        import base64
        import streamlit as st
        config = st.session_state.get("config_empresa") if hasattr(st, "session_state") else None
        if not config:
            from database.conection import get_configuracion_empresa
            config = get_configuracion_empresa() or {}
        datos = (config or {}).get("logo_base64")
        return io.BytesIO(base64.b64decode(datos)) if datos else None
    except Exception:
        return None


# ----------------------------------------------------------------
# Hojas
# ----------------------------------------------------------------
def hoja_tabla(wb, hoja, tabla, spec, filas, rol="datos"):
    """Una hoja = una tabla de Excel con nombre. spec: [(columna, descripcion, formato)]. rol: datos | apoyo | ayuda (solo cambia el color de la pestaña)."""
    ws = wb.create_sheet(hoja)
    columnas = [c for c, _, _ in spec]
    ws.append(columnas)
    for f in filas:
        ws.append([f.get(c) for c in columnas])
    relleno = PatternFill("solid", fgColor=MARCA["color"])
    borde = Border(bottom=Side(style="medium", color=MARCA["acento"]))
    for i, (c, _, fmt) in enumerate(spec, start=1):
        celda = ws.cell(row=1, column=i)
        celda.font, celda.fill, celda.border = Font(bold=True, color="FFFFFF"), relleno, borde
        celda.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        formato = FORMATOS.get(fmt)
        if formato:
            for fila in range(2, len(filas) + 2):
                ws.cell(row=fila, column=i).number_format = formato
        ancho = max([len(str(c))] + [len(str(f.get(c))) for f in filas[:300] if f.get(c) is not None] + [8])
        ws.column_dimensions[get_column_letter(i)].width = min(ancho + 3, 50)
    ws.row_dimensions[1].height = 24
    ws.freeze_panes = "A2"
    ws.sheet_properties.tabColor = MARCA["pestana_" + rol]
    ws.oddHeader.left.text = f"{MARCA['empresa']} · {MARCA['area']}"
    ws.oddHeader.right.text = hoja
    ws.oddFooter.center.text = "Página &P de &N"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
    ws.sheet_properties.pageSetUpPr = openpyxl.worksheet.properties.PageSetupProperties(fitToPage=True)
    ws.print_title_rows = "1:1"
    if filas:                                                    # una tabla de Excel necesita al menos una fila de datos
        t = Table(displayName=tabla, ref=f"A1:{get_column_letter(len(columnas))}{len(filas) + 1}")
        t.tableStyleInfo = TableStyleInfo(name="TableStyleLight9", showRowStripes=True)
        ws.add_table(t)
    return ws


def portada(wb, titulo, usuario_nombre, rango, tablas, notas=()):
    """Primera hoja del libro (con la marca). tablas: [(nombre_de_tabla, descripcion)]."""
    ws = wb.active
    ws.title = "Leeme"
    ws.sheet_view.showGridLines = False
    ws.sheet_properties.tabColor = MARCA["acento"]
    ws.column_dimensions["A"].width = 3
    ws.column_dimensions["B"].width = 34
    ws.column_dimensions["C"].width = 110
    banda = PatternFill("solid", fgColor=MARCA["color"])
    for fila in (1, 2, 3):
        for col in (1, 2, 3):
            ws.cell(row=fila, column=col).fill = banda
    ws.row_dimensions[1].height, ws.row_dimensions[2].height, ws.row_dimensions[3].height = 22, 30, 22
    ws["B2"] = MARCA["empresa"]
    ws["B2"].font = Font(bold=True, size=24, color="FFFFFF")
    ws["C2"] = f"{MARCA['area']} · {MARCA['sistema'].split('·')[-1].strip()}"
    ws["C2"].font = Font(size=13, color="FFFFFF")
    ws["C2"].alignment = Alignment(vertical="center")
    logo = _logo()
    if logo:
        try:
            from openpyxl.drawing.image import Image
            img = Image(logo)
            alto = 64
            img.width, img.height = img.width * alto / img.height, alto
            ws.add_image(img, "C1")
            ws["C2"] = None
        except Exception:
            pass
    ws["B5"] = titulo
    ws["B5"].font = Font(bold=True, size=16, color=MARCA["color"])
    ahora = hoy_paraguay()
    datos = [("Generado", f"{ahora:%d/%m/%Y} a las {ahora:%H:%M} (hora de Paraguay)"), ("Generado por", usuario_nombre or "—"), ("Datos", rango)]
    fila = 7
    for k, v in datos:
        ws.cell(row=fila, column=2, value=k).font = Font(bold=True)
        ws.cell(row=fila, column=3, value=v)
        fila += 1
    fila += 1
    ws.cell(row=fila, column=2, value="TABLAS DE ESTE ARCHIVO").font = Font(bold=True, color="FFFFFF")
    ws.cell(row=fila, column=2).fill = ws.cell(row=fila, column=3).fill = PatternFill("solid", fgColor=MARCA["acento"])
    fila += 1
    for n, d in tablas:
        ws.cell(row=fila, column=2, value=n).font = Font(bold=True, color=MARCA["color"])
        ws.cell(row=fila, column=3, value=d).alignment = Alignment(wrap_text=True, vertical="top")
        fila += 1
    fila += 1
    ws.cell(row=fila, column=2, value="CÓMO USARLO EN POWER BI").font = Font(bold=True, color="FFFFFF")
    ws.cell(row=fila, column=2).fill = ws.cell(row=fila, column=3).fill = PatternFill("solid", fgColor=MARCA["acento"])
    fila += 1
    pasos = ["1. Power BI Desktop → Obtener datos → Libro de Excel → elegí este archivo.",
             "2. Marcá las TABLAS (no las hojas) que quieras; tienen el mismo nombre que figura arriba. «Leeme» y «Diccionario» se pueden dejar afuera.",
             "3. Las tablas se relacionan por los identificadores que indica el Diccionario (por ejemplo ronda_id) y por la fecha con la tabla Calendario.",
             "4. Para actualizar: descargá el archivo de nuevo, guardalo con el MISMO nombre en la MISMA carpeta y en Power BI tocá «Actualizar»."]
    for p in pasos:
        ws.cell(row=fila, column=2, value=p)
        fila += 1
    if notas:
        fila += 1
        ws.cell(row=fila, column=2, value="NOTAS").font = Font(bold=True, color="FFFFFF")
        ws.cell(row=fila, column=2).fill = ws.cell(row=fila, column=3).fill = PatternFill("solid", fgColor=MARCA["acento"])
        fila += 1
        for n in notas:
            ws.cell(row=fila, column=2, value="· " + n)
            fila += 1
    fila += 1
    ws.cell(row=fila, column=2, value=f"{MARCA['empresa']} · {MARCA['area']} — documento generado automáticamente, no modificar las hojas de datos.").font = Font(italic=True, color="7F8C9B")
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
    ws.sheet_properties.pageSetUpPr = openpyxl.worksheet.properties.PageSetupProperties(fitToPage=True)
    wb.properties.creator = f"{MARCA['empresa']} · {MARCA['area']}"
    wb.properties.title = titulo
    wb.properties.company = MARCA["empresa"]
    wb.properties.lastModifiedBy = usuario_nombre or MARCA["empresa"]


def diccionario(wb, specs):
    filas = [{"tabla": t, "columna": c, "descripcion": d, "tipo": TIPOS[f]} for t, spec in specs.items() for c, d, f in spec]
    hoja_tabla(wb, "Diccionario", "Diccionario", [("tabla", "", "texto"), ("columna", "", "texto"), ("descripcion", "", "texto"), ("tipo", "", "texto")], filas, rol="ayuda")


SPEC_CALENDARIO = [
    ("fecha", "Día (clave para relacionar con las demás tablas)", "fecha"), ("anio", "Año", "entero"), ("mes", "Número de mes (1 a 12)", "entero"),
    ("nombre_mes", "Nombre del mes", "texto"), ("periodo", "Año y mes (AAAA-MM), útil para ordenar y agrupar", "texto"), ("trimestre", "Trimestre (1 a 4)", "entero"),
    ("semana_iso", "Número de semana ISO", "entero"), ("dia_semana_num", "Día de la semana: 1 = lunes … 7 = domingo", "entero"),
    ("dia_semana", "Nombre del día de la semana", "texto"), ("es_domingo", "Verdadero si es domingo", "logico"),
    ("es_feriado", "Verdadero si es feriado (según los feriados cargados en la app)", "logico"), ("motivo_feriado", "Motivo del feriado", "texto")]


def calendario(desde, hasta, feriados=None):
    """Una fila por día entre desde y hasta. 'feriados' = {fecha: motivo}."""
    feriados = feriados or {}
    filas, d = [], desde
    while d <= hasta:
        filas.append({"fecha": d, "anio": d.year, "mes": d.month, "nombre_mes": MESES[d.month - 1], "periodo": f"{d.year}-{d.month:02d}",
                      "trimestre": (d.month - 1) // 3 + 1, "semana_iso": d.isocalendar()[1], "dia_semana_num": d.isoweekday(),
                      "dia_semana": DIAS[d.weekday()], "es_domingo": d.weekday() == 6, "es_feriado": d in feriados, "motivo_feriado": feriados.get(d)})
        d += timedelta(days=1)
    return filas


def a_bytes(wb):
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def libro(titulo, usuario_nombre, rango, tablas, specs, datos, notas=(), con_calendario=None, feriados=None):
    """
    Arma un libro completo con el estándar. tablas: [(hoja, tabla, descripcion)]. specs/datos: {tabla: spec/filas}.
    con_calendario: (desde, hasta) para agregar la hoja Calendario.
    """
    wb = openpyxl.Workbook()
    indice = [(t, d) for _, t, d in tablas]
    if con_calendario:
        indice.append(("Calendario", "Un renglón por día del período (para agrupar por mes, semana, día de la semana)."))
    indice.append(("Diccionario", "Qué significa cada columna de cada tabla."))
    portada(wb, titulo, usuario_nombre, rango, indice, notas)
    todos = dict(specs)
    for hoja, tabla, _ in tablas:
        hoja_tabla(wb, hoja, tabla, specs[tabla], datos.get(tabla, []))
    if con_calendario:
        hoja_tabla(wb, "Calendario", "Calendario", SPEC_CALENDARIO, calendario(con_calendario[0], con_calendario[1], feriados), rol="apoyo")
        todos["Calendario"] = SPEC_CALENDARIO
    diccionario(wb, todos)
    return a_bytes(wb)
