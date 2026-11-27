"""
Planilla de Planificación de la Producción → datos para la pantalla de Ventas.

Lee el Excel que carga el supervisor (hojas PEDIDOS y DESARROLLOS), descarta las filas vacías,
convierte fechas y números, y deja TODAS las columnas de la planilla en su orden original.
Además calcula, por fila, el estado que entiende una vendedora: Terminado, En producción,
Programado o Atrasado, y cuánto puede retirar el cliente.

No depende de Streamlit ni de la base: se puede probar solo.
"""
import io
import re
import unicodedata
from datetime import date, datetime, time

HOJAS = {"pedidos": "Pedidos", "desarrollos": "Desarrollos"}


def normalizar(texto):
    """'N°  OC' -> 'n oc' ; 'Fecha planificada de finalización' -> 'fecha planificada de finalizacion'."""
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


# Columnas que la pantalla usa para calcular el estado (se buscan por palabras clave, así
# soporta pequeños cambios de nombre entre hojas: «finalización» / «fin», etc.)
CLAVES = {
    "cliente": lambda n: n == "cliente",
    "oc": lambda n: n in ("n oc", "no oc", "nro oc", "oc", "n de oc"),
    "solicitado": lambda n: n.startswith("kg solicitado"),
    "producido": lambda n: "kg producido" in n and not n.startswith("diferencia"),
    "pendiente": lambda n: n.startswith("saldo pendiente") or n.startswith("diferencia de kg solicitado"),
    "entregado": lambda n: n.startswith("kg entregado"),
    "disponible": lambda n: n.startswith("saldo prod") or n.startswith("diferencia de kg entregado"),
    "estado_entrega": lambda n: n.startswith("estado de entrega"),
    "codigo": lambda n: n == "codigo",
    "referencia": lambda n: n == "referencia",
    "inicio": lambda n: n.startswith("fecha planificada de inicio"),
    "fin": lambda n: n.startswith("fecha planificada de fin"),
    "fin_real": lambda n: n.startswith("fecha de finalizacion real"),
    "proceso": lambda n: n == "proceso",
}


def _mapear(columnas):
    mapa = {}
    for col in columnas:
        n = normalizar(col)
        for clave, prueba in CLAVES.items():
            if clave not in mapa and prueba(n):
                mapa[clave] = col
    return mapa


def _valor(v):
    """Excel -> valor guardable en JSON. Horas 00:00 sueltas y celdas en blanco = vacío."""
    if v is None or isinstance(v, time):
        return None                                   # en la planilla, 00:00 sin fecha significa «todavía no»
    if isinstance(v, str):
        v = v.strip()
        return v or None
    if isinstance(v, datetime):
        return v.replace(microsecond=0).isoformat()
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day).isoformat()
    if isinstance(v, float):
        return round(v, 2)
    return v


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def a_datetime(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v))
    except ValueError:
        return None


def _fila_valida(fila, mapa):
    cliente = fila.get(mapa.get("cliente"))
    if not isinstance(cliente, str) or not cliente.strip():
        return False
    return any(_num(fila.get(mapa.get(c))) for c in ("solicitado", "producido")) or bool(fila.get(mapa.get("codigo")))


def leer_planilla(contenido: bytes):
    """
    Devuelve {"pedidos": {"columnas": [...], "filas": [...]}, "desarrollos": {...}, "avisos": [...]}.
    Lanza ValueError con un mensaje claro si el archivo no es la planilla esperada.
    """
    import openpyxl
    try:
        libro = openpyxl.load_workbook(io.BytesIO(contenido), data_only=True, read_only=True)
    except Exception as e:
        raise ValueError(f"No se pudo abrir el archivo como Excel (.xlsx): {type(e).__name__}.")
    por_nombre = {normalizar(h.title): h for h in libro.worksheets}
    salida, avisos = {}, []
    for clave, titulo in HOJAS.items():
        hoja = por_nombre.get(clave)
        if hoja is None:
            salida[clave] = {"columnas": [], "filas": []}
            avisos.append(f"No se encontró la hoja «{titulo.upper()}»: esa parte queda vacía.")
            continue
        filas_excel = hoja.iter_rows(values_only=True)
        encabezado = next(filas_excel, None) or []
        columnas = [str(c).strip() for c in encabezado if c is not None and str(c).strip()]
        indices = [i for i, c in enumerate(encabezado) if c is not None and str(c).strip()]
        mapa = _mapear(columnas)
        if "cliente" not in mapa:
            raise ValueError(f"La hoja «{hoja.title}» no tiene la columna «Cliente» en la primera fila.")
        filas = []
        for r in filas_excel:
            fila = {col: _valor(r[i] if i < len(r) else None) for col, i in zip(columnas, indices)}
            if _fila_valida(fila, mapa):
                filas.append(fila)
        salida[clave] = {"columnas": columnas, "filas": filas}
    libro.close()
    if not any(salida[c]["filas"] for c in HOJAS):
        raise ValueError("La planilla no tiene ninguna fila con cliente cargado.")
    return {**salida, "avisos": avisos}


# ----------------------------------------------------------------
# Estado de cada fila (lo que ve la vendedora)
# ----------------------------------------------------------------
TERMINADO, EN_PRODUCCION, PROGRAMADO, ATRASADO, SIN_FECHA = "Terminado", "En producción", "Programado", "Atrasado", "Sin fecha"
COLOR = {TERMINADO: "green", EN_PRODUCCION: "orange", PROGRAMADO: "blue", ATRASADO: "red", SIN_FECHA: "gray"}


def resumen_fila(fila, columnas, ahora):
    """Datos calculados de una fila: estado, avance %, kg para retirar, fechas."""
    m = _mapear(columnas)
    g = lambda k: fila.get(m[k]) if k in m else None
    solicitado, producido = _num(g("solicitado")) or 0, _num(g("producido")) or 0
    disponible = max(_num(g("disponible")) or 0, 0)
    inicio, fin = a_datetime(g("inicio")), a_datetime(g("fin"))
    proceso = normalizar(g("proceso"))
    if proceso.startswith("finaliz"):
        estado = TERMINADO
    elif inicio and fin:
        estado = PROGRAMADO if ahora < inicio else (EN_PRODUCCION if ahora <= fin else ATRASADO)
    else:
        estado = SIN_FECHA
    # siempre float entre 0.0 y 1.0: st.progress toma un ENTERO como porcentaje (1 = 1 %), por eso antes «100 %» se veía casi vacío
    avance = float(min(producido / solicitado, 1.0)) if solicitado else (1.0 if estado == TERMINADO else 0.0)
    return {"cliente": g("cliente"), "oc": g("oc"), "codigo": g("codigo"), "referencia": g("referencia"),
            "solicitado": solicitado, "producido": producido, "disponible": disponible, "estado": estado,
            "avance": avance, "inicio": inicio, "fin": fin}


def es_columna(columna, clave, columnas):
    return _mapear(columnas).get(clave) == columna


def es_numero_kg(columna):
    return "kg" in normalizar(columna) or normalizar(columna).startswith("saldo")


def es_fecha(columna):
    return normalizar(columna).startswith("fecha")


# ----------------------------------------------------------------
# Formato para la pantalla (es-PY: 1.234,5)
# ----------------------------------------------------------------
DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


def kg(v):
    n = _num(v)
    if n is None:
        return "—"
    texto = f"{n:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return (texto[:-2] if texto.endswith(",0") else texto) + " kg"


def fecha_amigable(v, ahora, con_hora=True):
    """'hoy 19:00', 'mañana 03:20', 'jue 26/11 18:00'. Sin hora si es 00:00."""
    d = v if isinstance(v, datetime) else a_datetime(v)
    if not d:
        return "—"
    hora = f" {d:%H:%M}" if con_hora and (d.hour or d.minute) else ""
    dias = (d.date() - ahora.date()).days
    if dias == 0:
        return "hoy" + hora
    if dias == 1:
        return "mañana" + hora
    if dias == -1:
        return "ayer" + hora
    return f"{DIAS[d.weekday()]} {d:%d/%m}" + (f"/{d:%y}" if d.year != ahora.year else "") + hora


def texto_celda(columna, valor, columnas, ahora):
    """Cómo se muestra cada dato en la tarjeta, respetando todas las columnas de la planilla."""
    if valor is None or valor == "":
        return "—"
    if es_fecha(columna):
        return fecha_amigable(valor, ahora)
    if es_columna(columna, "oc", columnas):
        return str(int(valor)) if isinstance(valor, (int, float)) else str(valor)
    if isinstance(valor, (int, float)) and es_numero_kg(columna):
        if (es_columna(columna, "pendiente", columnas) or es_columna(columna, "disponible", columnas)) and valor < 0:
            return f"completo (se hizo {kg(-valor)} de más)"
        return kg(valor)
    if isinstance(valor, float):
        return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return str(valor)
