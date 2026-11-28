"""
Excel de Productividad IGUAL a la planilla de logística (Productividad.xlsx) que lee el Power BI «Productividad Vitopel 1.5».

· Hoja «Producción»: las mismas 44 columnas, en el mismo orden y con los mismos nombres.
· Hoja «Base de datos»: las listas (fallas, sistemas, máquinas, operadores, setups, motivos y familias).

Cómo se arma cada renglón (la planilla tiene 1 setup, 1 falla y 1 rechazo por renglón; el CMMS permite varios por turno):
· Un turno con varios setups, fallas o rechazos sale en varios renglones seguidos: el 1.º con el 1.º de cada lista, etc.
· Los totales del TURNO (horas de turno, planificadas, operativas, producción, kilos, metros y refile) van solo en el
  primer renglón del turno, para que Power BI no los sume dos veces. Setup, falla y rechazo van en su renglón.
· Todos los renglones llevan «Fecha inicio de Fallas» (aunque el turno no tenga fallas, con 0 horas), porque el
  Power BI descarta los renglones sin esa fecha.
· Las horas van como hora de Excel (12:00 = 0,5 día), igual que en la planilla: el Power BI las pasa a horas.
"""
import io
from datetime import datetime
from itertools import zip_longest

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from database import productividad_logica as P

COLUMNAS = ['Año', 'Mes', 'Día', 'No. OP', 'Operador', 'Hora Inicio de Turno', 'Hora fin de Turno', 'Total de Horas de Turno',
            'Total Horas Planificadas', 'Total Horas Operativas', 'Item', 'Producto', 'Ancho (mm)', 'Espesor Mic (mm)', 'Densidad (kg/m3)',
            'Metros Lineales Producidos (m)', 'Kilos Producidos', 'Scrap de Setup (kg)', 'Tipo de Setup', 'Scrap por Refile (kg)',
            'Familia del Producto', 'Tipo de Producto', 'Color del Producto', 'Maquina', 'Fecha inicio de Setup', 'Hora Inicio de Setup',
            'Fecha fin de Setup', 'Hora fin de Setup', 'Total de Horas de Setup', 'Fecha inicio de Producción', 'Hora Inicio de Producción',
            'Fecha fin de Producción', 'Hora fin de Producción', 'Total de Horas de Producción', 'Kilos Rechazados', 'Motivo de Rechazo',
            'Fecha inicio de Fallas', 'Hora Inicio de Fallas', 'Fecha fin de Fallas', 'Hora fin de Fallas', 'Total de Horas de Fallas',
            'Total Parada no Planificada', 'Tipo de Fallas', 'Sistema de Fallas']

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

FORMATO = {}
for c in COLUMNAS:
    if c == "Día" or c.startswith("Fecha"):
        FORMATO[c] = "dd/mm/yyyy"
    elif c.startswith("Hora"):
        FORMATO[c] = "hh:mm"
    elif c.startswith("Total"):
        FORMATO[c] = "[h]:mm"
    elif c in ("Metros Lineales Producidos (m)", "Kilos Producidos", "Scrap de Setup (kg)", "Scrap por Refile (kg)", "Kilos Rechazados"):
        FORMATO[c] = "#,##0.0"
    elif c == "Densidad (kg/m3)":
        FORMATO[c] = "0.00"


def _dia(d):
    """Fecha de Excel (sin hora)."""
    return datetime(d.year, d.month, d.day) if d else None


def _horas_excel(h):
    """Horas -> fracción de día (como guarda Excel un 12:00). None si no hay valor."""
    return None if h is None else round(h / 24.0, 8)


def _op(v):
    s = str(v or "").strip()
    return int(s) if s.isdigit() else (s or None)


def _num(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def filas_turno(t):
    """Renglones de la hoja «Producción» para un turno enriquecido (ver productividad_logica.enriquecer)."""
    c = t["calculo"]
    ini, fin = t["inicio"], t["fin"]
    base = {
        "Año": ini.year, "Mes": MESES[ini.month - 1], "Día": _dia(ini.date()), "No. OP": _op(t.get("op")), "Operador": t.get("operador"),
        "Hora Inicio de Turno": ini.time().replace(second=0, microsecond=0), "Hora fin de Turno": fin.time().replace(second=0, microsecond=0),
        "Item": t.get("item") or None, "Producto": t.get("producto") or None,
        "Ancho (mm)": round(_num(t.get("ancho_cm")) * 10, 1) if _num(t.get("ancho_cm")) else None,
        "Espesor Mic (mm)": _num(t.get("espesor_um")), "Densidad (kg/m3)": _num(t.get("densidad")) or P.DENSIDAD_DEFECTO,
        "Familia del Producto": t.get("familia"), "Tipo de Producto": t.get("barrera"), "Color del Producto": t.get("color"), "Maquina": t.get("maquina"),
    }
    # Producción: desde el fin de la preparación inicial (si el turno arranca con un setup) hasta el fin del turno
    setups = sorted(t["setups"], key=lambda s: s["inicio"])
    ini_prod = setups[0]["fin"] if setups and setups[0]["inicio"] <= ini else ini
    totales = {
        "Total de Horas de Turno": _horas_excel(c["horas_turno"]), "Total Horas Planificadas": _horas_excel(c["h_planificadas"]),
        "Total Horas Operativas": _horas_excel(c["h_operativas"]),
        "Metros Lineales Producidos (m)": round(c["metros"], 1) if c["metros"] else None, "Kilos Producidos": c["kg"] or None,
        "Scrap por Refile (kg)": c["scrap_refile"] or None,
        "Fecha inicio de Producción": _dia(ini_prod.date()), "Hora Inicio de Producción": ini_prod.time().replace(second=0, microsecond=0),
        "Fecha fin de Producción": _dia(fin.date()), "Hora fin de Producción": fin.time().replace(second=0, microsecond=0),
        "Total de Horas de Producción": _horas_excel(max(c["h_prod"], 0)),
    }
    paradas = sorted(t["paradas"], key=lambda p: p["inicio"])
    filas = []
    combinados = list(zip_longest(setups, paradas, t["rechazos"])) or [(None, None, None)]
    for i, (s, p, r) in enumerate(combinados):
        f = dict(base)
        if i == 0:
            f.update(totales)
        if s:
            f.update({"Tipo de Setup": s.get("tipo"), "Scrap de Setup (kg)": _num(s.get("scrap_kg")),
                      "Fecha inicio de Setup": _dia(s["inicio"].date()), "Hora Inicio de Setup": s["inicio"].time().replace(second=0, microsecond=0),
                      "Fecha fin de Setup": _dia(s["fin"].date()), "Hora fin de Setup": s["fin"].time().replace(second=0, microsecond=0),
                      "Total de Horas de Setup": _horas_excel(P.horas(s["fin"] - s["inicio"]))})
        if p:
            h = P.horas(p["fin"] - p["inicio"])
            f.update({"Fecha inicio de Fallas": _dia(p["inicio"].date()), "Hora Inicio de Fallas": p["inicio"].time().replace(second=0, microsecond=0),
                      "Fecha fin de Fallas": _dia(p["fin"].date()), "Hora fin de Fallas": p["fin"].time().replace(second=0, microsecond=0),
                      "Total de Horas de Fallas": _horas_excel(h), "Total Parada no Planificada": _horas_excel(h),
                      "Tipo de Fallas": p.get("tipo_falla"), "Sistema de Fallas": p.get("sistema") or None})
        else:
            # sin falla en este renglón: igual lleva la fecha (el Power BI descarta renglones sin «Fecha inicio de Fallas»)
            f.update({"Fecha inicio de Fallas": _dia(ini.date()), "Fecha fin de Fallas": _dia(ini.date()),
                      "Total de Horas de Fallas": 0, "Total Parada no Planificada": 0})
        if r:
            f.update({"Kilos Rechazados": _num(r.get("kg")), "Motivo de Rechazo": r.get("motivo")})
        filas.append(f)
    return filas


def _base_de_datos(ws, catalogo, familias):
    activos = [i for i in catalogo if i.get("activo") is not False]
    lista = lambda tipo: [i.get("nombre") for i in activos if i.get("tipo") == tipo]
    fams = [f for f in familias if f.get("activo") is not False]
    columnas = [("Tipos de Fallas", lista("tipo_falla")), ("Sitema de Fallas", lista("sistema_falla")),
                ("Maquinas", sorted({f.get("maquina") for f in fams if f.get("maquina")})), ("Operadores", lista("operador")),
                ("Tipos de Setup", lista("tipo_setup")), ("Motivo de Rechazo del Producto", lista("motivo_rechazo")),
                ("Familias", [f.get("codigo") for f in fams]), ("Maquina", [f.get("maquina") for f in fams]),
                ("HB", [f.get("barrera") for f in fams]), ("Tipo", [f.get("color") for f in fams])]
    for j, (titulo, valores) in enumerate(columnas, 1):
        ws.cell(row=1, column=j, value=titulo).font = Font(bold=True)
        for i, v in enumerate(valores, 2):
            ws.cell(row=i, column=j, value=v)
        ws.column_dimensions[get_column_letter(j)].width = max(14, min(40, len(titulo) + 4))
    ws.freeze_panes = "A2"


def excel_planilla(enr, catalogo, familias):
    """enr: turnos enriquecidos. Devuelve los bytes del .xlsx con las hojas «Producción» y «Base de datos»."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Producción"
    encabezado = PatternFill("solid", fgColor="0E5A75")
    for j, col in enumerate(COLUMNAS, 1):
        celda = ws.cell(row=1, column=j, value=col)
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = encabezado
        celda.alignment = Alignment(wrap_text=True, vertical="center")
        ws.column_dimensions[get_column_letter(j)].width = 12 if (col.startswith("Hora") or col.startswith("Total")) else 15
    for c in ("Producto", "Operador", "Tipo de Fallas", "Sistema de Fallas", "Motivo de Rechazo"):
        ws.column_dimensions[get_column_letter(COLUMNAS.index(c) + 1)].width = 26
    ws.row_dimensions[1].height = 45
    fila = 2
    for t in sorted(enr, key=lambda x: (x["inicio"], str(x.get("operador")))):
        for f in filas_turno(t):
            for j, col in enumerate(COLUMNAS, 1):
                v = f.get(col)
                celda = ws.cell(row=fila, column=j, value=v)
                if v is not None and col in FORMATO:
                    celda.number_format = FORMATO[col]
            fila += 1
    ws.freeze_panes = "F2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNAS))}{max(fila - 1, 1)}"
    _base_de_datos(wb.create_sheet("Base de datos"), catalogo, familias)
    salida = io.BytesIO()
    wb.save(salida)
    return salida.getvalue()
