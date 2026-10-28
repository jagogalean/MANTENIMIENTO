"""
Carga masiva del inventario de repuestos desde un Excel.

Pensado para planillas "reales" (con tus propios títulos de columna, filas de
título arriba, varias hojas, números escritos como texto, filas vacías, sin
códigos...). El flujo es:

    leer_excel  ->  sugerir_mapeo  ->  procesar_inventario  ->  insertar_repuestos_lote

Las funciones de lectura y limpieza no tocan la base de datos (se pueden
probar solas). Solo insertar_repuestos_lote habla con Supabase.
"""
import io
import math
import numbers
import re
import unicodedata

import pandas as pd

# Campos del repuesto: (clave interna, texto que ve el usuario)
CAMPOS = [
    ("nombre", "Nombre / descripción del repuesto *"),
    ("codigo_interno", "Código interno (si no tiene, se genera solo)"),
    ("ubicacion", "Ubicación (estante, fila, casillero...)"),
    ("stock_actual", "Stock actual (cantidad contada)"),
    ("stock_minimo", "Stock mínimo"),
    ("costo_unitario", "Costo unitario (Gs.)"),
]
COLUMNAS_PLANTILLA = [clave for clave, _ in CAMPOS]

# Palabras que suelen usarse como título de cada columna (sin tildes, en minúscula)
SINONIMOS = {
    "nombre": ["nombre", "descripcion", "descripcion del repuesto", "repuesto", "item", "articulo",
               "material", "producto", "detalle", "denominacion"],
    "codigo_interno": ["codigo", "codigo interno", "cod", "sku", "referencia", "ref", "parte",
                       "nro parte", "n parte", "part number", "pn", "id"],
    "stock_minimo": ["stock minimo", "minimo", "min", "stock min", "punto de pedido", "nivel minimo",
                     "stock de seguridad"],
    "stock_actual": ["stock actual", "stock", "cantidad", "cant", "existencia", "existencias", "saldo",
                     "qty", "unidades", "inventario", "stock inicial"],
    "costo_unitario": ["costo unitario", "costo", "precio unitario", "precio", "valor", "valor unitario",
                       "p unitario", "costo gs", "precio gs"],
    "ubicacion": ["ubicacion", "lugar", "estante", "deposito", "almacen", "zona", "posicion", "rack",
                  "casillero", "localizacion"],
}
# Orden de asignación: lo más específico primero (así "stock mínimo" no cae en "stock")
ORDEN_SUGERENCIA = ["nombre", "codigo_interno", "stock_minimo", "stock_actual", "costo_unitario", "ubicacion"]

FILAS_DE_TOTALES = {"total", "totales", "subtotal", "total general", "suma", "sumatoria"}
VACIOS = {"", "-", "--", "—", "n/a", "na", "s/d", "sd", "nan", "none", "null", "#n/a"}


# ----------------------------------------------------------------
# Lectura del archivo
# ----------------------------------------------------------------
def normalizar(texto):
    """Minúsculas, sin tildes y sin símbolos: 'Cód. Interno' -> 'cod interno'."""
    t = unicodedata.normalize("NFKD", str(texto if texto is not None else "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


def listar_hojas(contenido: bytes):
    return pd.ExcelFile(io.BytesIO(contenido), engine="openpyxl").sheet_names


def _columnas_unicas(columnas):
    vistas, resultado = {}, []
    for c in columnas:
        nombre = str(c).strip() or "(sin título)"
        n = vistas.get(nombre, 0)
        vistas[nombre] = n + 1
        resultado.append(nombre if n == 0 else f"{nombre} ({n + 1})")
    return resultado


def leer_excel(contenido: bytes, hoja=0, fila_encabezado=1):
    """
    Lee una hoja SIN convertir nada (todo queda como viene en el Excel) y
    descarta filas y columnas totalmente vacías. El índice conserva la
    posición original, para poder informar "fila 37 de tu Excel".
    fila_encabezado: número de fila (1 = la primera) donde están los títulos.
    """
    df = pd.read_excel(io.BytesIO(contenido), sheet_name=hoja, header=fila_encabezado - 1,
                       dtype=object, engine="openpyxl")
    df.columns = _columnas_unicas(df.columns)
    df = df.dropna(how="all").dropna(axis=1, how="all")
    df = df.astype(object).where(df.notna(), None)
    return df


def sugerir_mapeo(columnas):
    """Adivina qué columna del Excel corresponde a cada campo, por el título."""
    norm = {c: normalizar(c) for c in columnas}
    mapeo = {clave: None for clave, _ in CAMPOS}
    usadas = set()

    def asignar(campo, col):
        mapeo[campo] = col
        usadas.add(col)

    for campo in ORDEN_SUGERENCIA:                       # pasada 1: título igual a un sinónimo
        for col, n in norm.items():
            if col not in usadas and n in SINONIMOS[campo]:
                asignar(campo, col)
                break
    for campo in ORDEN_SUGERENCIA:                       # pasada 2: el título contiene un sinónimo
        if mapeo[campo]:
            continue
        for col, n in norm.items():
            if col not in usadas and any(f" {s} " in f" {n} " for s in SINONIMOS[campo]):
                asignar(campo, col)
                break
    return mapeo


# ----------------------------------------------------------------
# Limpieza de valores
# ----------------------------------------------------------------
def limpiar_texto(valor):
    if valor is None:
        return ""
    if isinstance(valor, float):
        if math.isnan(valor):
            return ""
        if valor.is_integer():
            return str(int(valor))          # código 1001.0 -> "1001"
    return re.sub(r"\s+", " ", str(valor)).strip()


def parsear_numero(valor):
    """
    Interpreta un valor de una celda como número. Devuelve (numero, estado):
      estado = "ok" | "vacio" | "invalido"

    Entiende números reales de Excel y también texto como "1.549.258",
    "85,000", "Gs. 12.500", "2,5" o "1.500,75". Regla para separadores con
    un solo punto o coma: si detrás hay exactamente 3 dígitos y delante hasta
    3 (1.500 / 85,000) se toma como separador de miles; si no, como decimal.
    """
    if valor is None:
        return None, "vacio"
    if isinstance(valor, bool):
        return None, "invalido"
    if isinstance(valor, numbers.Real):
        numero = float(valor)
        return (None, "vacio") if math.isnan(numero) else (numero, "ok")

    s = str(valor).strip().lower().replace("\u00a0", " ")
    if s in VACIOS:
        return None, "vacio"
    s = re.sub(r"(gs\.?|guaranies?|₲|us\$|u\$s|usd|\$)", "", s).replace(" ", "")
    if not re.fullmatch(r"-?[\d.,]+", s) or not re.search(r"\d", s):
        return None, "invalido"

    negativo = s.startswith("-")
    s = s.lstrip("-")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")      # 1.549,50
        else:
            s = s.replace(",", "")                        # 1,549.50
    elif "," in s or "." in s:
        sep = "," if "," in s else "."
        partes = s.split(sep)
        if len(partes) > 2:
            s = "".join(partes)                           # 1.549.258
        else:
            entero, dec = partes
            if len(dec) == 3 and 1 <= len(entero) <= 3 and entero != "0":
                s = entero + dec                          # 1.500 / 85,000
            else:
                s = entero + "." + dec                    # 2,5 / 12.50
    try:
        numero = float(s)
    except ValueError:
        return None, "invalido"
    return (-numero if negativo else numero), "ok"


def _redondear(numero):
    """Redondeo 'normal' (2,5 -> 3), no el bancario de Python."""
    return int(math.floor(numero + 0.5))


# ----------------------------------------------------------------
# Validación y armado de las filas a cargar
# ----------------------------------------------------------------
def procesar_inventario(df, mapeo, codigos_existentes, prefijo="REP-", fila_encabezado=1, nombres_existentes=()):
    """
    Convierte el Excel en filas listas para cargar, con control de calidad.

    df: planilla leída con leer_excel.
    mapeo: {campo: columna del Excel o None}.
    codigos_existentes: códigos que ya hay en el inventario (para no duplicar).
    nombres_existentes: nombres que ya hay en el inventario. Sirve para que, si
        volvés a subir el mismo Excel (sin códigos), no se dupliquen los repuestos.

    Devuelve un dict:
      "filas":    repuestos válidos (con 'codigo_auto' = True si el código se generó)
      "omitidas": filas descartadas, cada una con su motivo
      "avisos":   observaciones que no frenan la carga (redondeos, nombres repetidos...)
    """
    existentes = {str(c).strip().casefold() for c in codigos_existentes if c not in (None, "")}
    usados = set(existentes)
    nombres_previos = {re.sub(r"\s+", " ", str(n)).strip().casefold() for n in nombres_existentes if n}
    codigo_en_fila = {}                      # código -> fila de Excel donde apareció primero
    filas, omitidas = [], []
    redondeos_stock, costos_decimales = [], 0
    nombres = {}

    def omitir(fila_excel, nombre, motivo):
        omitidas.append({"fila": fila_excel, "nombre": nombre or "—", "motivo": motivo})

    for idx, fila in df.iterrows():
        fila_excel = int(fila_encabezado) + 1 + int(idx)

        def crudo(campo):
            col = mapeo.get(campo)
            return fila[col] if col else None

        nombre = limpiar_texto(crudo("nombre"))
        codigo = limpiar_texto(crudo("codigo_interno"))
        ubicacion = limpiar_texto(crudo("ubicacion"))
        stock, e_stock = parsear_numero(crudo("stock_actual"))
        minimo, e_min = parsear_numero(crudo("stock_minimo"))
        costo, e_costo = parsear_numero(crudo("costo_unitario"))

        if not (nombre or codigo or ubicacion) and {e_stock, e_min, e_costo} <= {"vacio"}:
            continue                          # fila realmente vacía: se ignora sin avisar

        if not nombre:
            omitir(fila_excel, nombre, "Sin nombre")
            continue
        if normalizar(nombre) in FILAS_DE_TOTALES:
            omitir(fila_excel, nombre, "Parece una fila de totales, no un repuesto")
            continue
        invalido = next(((t, crudo(c)) for t, c, e in (("Stock actual", "stock_actual", e_stock),
                                                         ("Stock mínimo", "stock_minimo", e_min),
                                                         ("Costo unitario", "costo_unitario", e_costo))
                         if e == "invalido"), None)
        if invalido:
            omitir(fila_excel, nombre, f"{invalido[0]} no es un número: «{invalido[1]}»")
            continue
        negativo = next((t for t, v in (("Stock actual", stock), ("Stock mínimo", minimo), ("Costo unitario", costo))
                         if v is not None and v < 0), None)
        if negativo:
            omitir(fila_excel, nombre, f"{negativo} es negativo")
            continue

        clave = codigo.casefold()
        if not codigo and nombre.casefold() in nombres_previos:
            omitir(fila_excel, nombre, "Ya hay un repuesto con ese nombre en tu inventario (si es otro distinto, "
                                       "ponele un código en tu Excel)")
            continue
        if codigo:
            if clave in existentes:
                omitir(fila_excel, nombre, f"El código «{codigo}» ya existe en tu inventario")
                continue
            if clave in codigo_en_fila:
                omitir(fila_excel, nombre, f"Código «{codigo}» repetido (ya está en la fila {codigo_en_fila[clave]})")
                continue
            codigo_en_fila[clave] = fila_excel
            usados.add(clave)

        stock = stock or 0.0
        minimo = minimo or 0.0
        costo = costo or 0.0
        for etiqueta, valor in (("stock", stock), ("mínimo", minimo)):
            if abs(valor - round(valor)) > 1e-9 and len(redondeos_stock) < 500:
                redondeos_stock.append((fila_excel, etiqueta, valor))
        if abs(costo - round(costo)) > 1e-9:
            costos_decimales += 1

        nombres.setdefault(nombre.casefold(), []).append(fila_excel)
        filas.append({
            "fila_excel": fila_excel, "nombre": nombre, "codigo_interno": codigo or None, "codigo_auto": False,
            "ubicacion": ubicacion or None, "stock_actual": _redondear(stock),
            "stock_minimo": _redondear(minimo), "costo_unitario": _redondear(costo),
        })

    # Códigos automáticos: continúan la numeración más alta que ya exista con el mismo prefijo
    patron = re.compile(rf"^{re.escape(prefijo.casefold())}(\d+)$")
    mayor = max([int(m.group(1)) for c in usados if (m := patron.match(c))] or [0])
    siguiente = mayor + 1
    ancho = max(4, len(str(mayor + len(filas))))
    for f in filas:
        if f["codigo_interno"]:
            continue
        while f"{prefijo}{siguiente:0{ancho}d}".casefold() in usados:
            siguiente += 1
        f["codigo_interno"] = f"{prefijo}{siguiente:0{ancho}d}"
        f["codigo_auto"] = True
        usados.add(f["codigo_interno"].casefold())
        siguiente += 1

    avisos = []
    if redondeos_stock:
        ej = ", ".join(f"fila {fx}: {str(v).replace('.', ',')} → {_redondear(v)}" for fx, _, v in redondeos_stock[:4])
        avisos.append(f"{len(redondeos_stock)} cantidad(es) tenían decimales y se redondearon (el sistema trabaja con "
                      f"unidades enteras). Ejemplos: {ej}.")
    if costos_decimales:
        avisos.append(f"{costos_decimales} costo(s) tenían decimales y se redondearon a guaraníes enteros. Si tus precios "
                      "están en dólares, convertilos a guaraníes antes de cargar.")
    repetidos = {n: fs for n, fs in nombres.items() if len(fs) > 1}
    if repetidos:
        avisos.append(f"{len(repetidos)} nombre(s) aparecen más de una vez (con distinto código o sin código): revisá que "
                      "no sean el mismo repuesto cargado dos veces. Ej: fila(s) " + ", ".join(
                          str(x) for x in list(repetidos.values())[0]) + ".")
    return {"filas": filas, "omitidas": omitidas, "avisos": avisos}


# ----------------------------------------------------------------
# Archivos de apoyo
# ----------------------------------------------------------------
def generar_plantilla_excel() -> bytes:
    ejemplo = pd.DataFrame([
        {"nombre": "Rodamiento SKF 6204", "codigo_interno": "REP-0001", "ubicacion": "Estante 1 - Fila 2",
         "stock_actual": 10, "stock_minimo": 2, "costo_unitario": 85000},
        {"nombre": "Correa Poly-V 6PJ850", "codigo_interno": "", "ubicacion": "Estante 1 - Fila 3",
         "stock_actual": 4, "stock_minimo": 1, "costo_unitario": 210000},
    ], columns=COLUMNAS_PLANTILLA)
    ayuda = pd.DataFrame({"Cómo completar": [
        "nombre: obligatorio.",
        "codigo_interno: opcional. Si lo dejás vacío, el sistema le pone uno (REP-0001, REP-0002...).",
        "ubicacion: opcional. Texto libre, por ejemplo 'Estante 2 - Fila 1'.",
        "stock_actual / stock_minimo: números enteros. Vacío = 0.",
        "costo_unitario: en guaraníes, sin símbolo.",
        "No hace falta usar esta plantilla: podés subir tu propio Excel y elegir qué columna es cada cosa.",
    ]})
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        ejemplo.to_excel(writer, index=False, sheet_name="Repuestos")
        ayuda.to_excel(writer, index=False, sheet_name="Instrucciones")
    return buffer.getvalue()


def reporte_filas_con_problemas(filas) -> bytes:
    """Excel con las filas que no se cargaron y por qué (para corregirlas y volver a subir)."""
    df = pd.DataFrame(filas).rename(columns={"fila": "Fila en tu Excel", "nombre": "Nombre", "motivo": "Motivo"})
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="No cargadas")
    return buffer.getvalue()


# ----------------------------------------------------------------
# Carga a la base de datos
# ----------------------------------------------------------------
def _es_error_de_esquema(e):
    t = str(e).lower()
    return ("column" in t and ("schema cache" in t or "does not exist" in t)) or "pgrst204" in t


def _motivo_error(e):
    t = str(e).replace("\n", " ")
    return (t[:200] + "...") if len(t) > 200 else t


def insertar_repuestos_lote(filas, incluir_ubicacion=False, tam_lote=100):
    """
    Guarda los repuestos de a lotes (mucho más rápido que de a uno). Si un lote
    falla, prueba sus filas de a una para saber exactamente cuáles tienen
    problema, sin perder las demás.

    Devuelve (cantidad_cargada, [filas_que_fallaron]).
    Lanza RuntimeError si el problema es de estructura (por ejemplo falta la
    columna 'ubicacion' en la base): en ese caso no tiene sentido seguir.
    """
    from database.conection import supabase

    def armar(f):
        datos = {"nombre": f["nombre"], "codigo_interno": f["codigo_interno"], "stock_actual": f["stock_actual"],
                 "stock_minimo": f["stock_minimo"], "costo_unitario": f["costo_unitario"]}
        if incluir_ubicacion:
            datos["ubicacion"] = f["ubicacion"]
        return datos

    cargados, fallidas = 0, []
    for i in range(0, len(filas), tam_lote):
        lote = filas[i:i + tam_lote]
        try:
            supabase.table("repuestos").insert([armar(f) for f in lote]).execute()
            cargados += len(lote)
            continue
        except Exception as e_lote:
            if _es_error_de_esquema(e_lote):
                raise RuntimeError(
                    "La base de datos no tiene la columna 'ubicacion'. Corré el archivo SQL de esta actualización "
                    f"en Supabase y volvé a intentar. (Detalle: {_motivo_error(e_lote)})")
        for f in lote:
            try:
                supabase.table("repuestos").insert(armar(f)).execute()
                cargados += 1
            except Exception as e:
                fallidas.append({"fila": f["fila_excel"], "nombre": f["nombre"], "motivo": _motivo_error(e)})
    return cargados, fallidas
