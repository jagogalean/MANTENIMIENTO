"""
Lógica de los trabajos con terceros (sin Streamlit ni base de datos: se puede probar sola).

Cada trabajo tiene una moneda (PYG o USD). Los montos de un trabajo, sus facturas y sus pagos están
siempre en esa misma moneda. Entre trabajos de monedas distintas NUNCA se suman: los totales se
muestran por separado, uno por moneda.
"""
import collections
import io
import re
import unicodedata
from datetime import date, datetime

TOLERANCIA = 0.01
MONEDAS = ["PYG", "USD"]
TIPOS_DOC = ["Presupuesto", "Factura", "Comprobante de pago", "Informe del proveedor", "Otro"]
ESTADOS_TRABAJO = ["Cotizando", "Aprobado", "Realizado", "Cancelado"]
ESTADOS_PAGO = ["Sin facturar", "Facturado, sin pagar", "Pago parcial", "Pagado", "Pagado de más", "Pagos sin factura"]
MEDIOS_PAGO = ["Transferencia", "Efectivo", "Cheque", "Otro"]


# ----------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------
def _n(valor):
    try:
        return float(valor or 0)
    except (TypeError, ValueError):
        return 0.0


def a_fecha(valor):
    if valor is None or valor == "":
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    try:
        return datetime.strptime(str(valor)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def fmt_monto(valor, moneda):
    """Gs. 1.234.567  /  USD 1.234,56"""
    v = _n(valor)
    if moneda == "USD":
        return "USD " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return "Gs. " + f"{v:,.0f}".replace(",", ".")


def nombre_seguro(nombre):
    """Nombre de archivo que Supabase Storage acepta (sin tildes, espacios ni símbolos raros)."""
    base = unicodedata.normalize("NFKD", nombre or "").encode("ascii", "ignore").decode("ascii")
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")
    return base or "archivo"


# ----------------------------------------------------------------
# Estado de pago y saldos
# ----------------------------------------------------------------
def estado_pago(facturado, pagado):
    facturado, pagado = _n(facturado), _n(pagado)
    if facturado <= TOLERANCIA:
        return "Pagos sin factura" if pagado > TOLERANCIA else "Sin facturar"
    if pagado <= TOLERANCIA:
        return "Facturado, sin pagar"
    if pagado < facturado - TOLERANCIA:
        return "Pago parcial"
    if pagado <= facturado + TOLERANCIA:
        return "Pagado"
    return "Pagado de más"


def saldos_por_factura(facturas, pagos):
    """
    Reparte los pagos entre las facturas:
      1) un pago asignado a una factura se descuenta de esa factura (hasta su monto);
      2) lo que sobre, y los pagos sin factura asignada, se aplican a las facturas en orden de
         vencimiento (la más antigua primero).
    Devuelve (lista de facturas con 'pagado' y 'saldo', sobrante que no corresponde a ninguna factura).
    """
    filas = {f["id"]: {"factura_id": f["id"], "numero": f.get("numero"), "monto": _n(f.get("monto")),
                       "vencimiento": a_fecha(f.get("fecha_vencimiento")), "fecha": a_fecha(f.get("fecha_factura")),
                       "pagado": 0.0} for f in facturas}
    pool = 0.0
    for p in pagos:
        monto = _n(p.get("monto"))
        fid = p.get("factura_id")
        if fid in filas:
            disponible = filas[fid]["monto"] - filas[fid]["pagado"]
            aplicado = min(monto, max(disponible, 0.0))
            filas[fid]["pagado"] += aplicado
            pool += monto - aplicado
        else:
            pool += monto
    for fila in sorted(filas.values(), key=lambda r: (r["vencimiento"] or r["fecha"] or date.max, r["factura_id"])):
        if pool <= TOLERANCIA:
            break
        aplicado = min(pool, max(fila["monto"] - fila["pagado"], 0.0))
        fila["pagado"] += aplicado
        pool -= aplicado
    resultado = list(filas.values())
    for fila in resultado:
        fila["saldo"] = round(fila["monto"] - fila["pagado"], 2)
        fila["pagado"] = round(fila["pagado"], 2)
    return resultado, round(max(pool, 0.0), 2)


def resumen_trabajo(trabajo, facturas, pagos, documentos=(), hoy=None):
    """
    Números y avisos de un trabajo. 'facturas', 'pagos' y 'documentos' son solo los de ese trabajo.
    Avisos: {"nivel": "alta" | "media" | "info", "texto": ...}
    """
    hoy = hoy or date.today()
    moneda = trabajo.get("moneda") or "PYG"
    presupuesto = _n(trabajo.get("monto_presupuesto"))
    facturado = round(sum(_n(f.get("monto")) for f in facturas), 2)
    pagado = round(sum(_n(p.get("monto")) for p in pagos), 2)
    saldo = round(facturado - pagado, 2)
    estado = estado_pago(facturado, pagado)
    por_factura, sobrante = saldos_por_factura(facturas, pagos)
    fm = lambda v: fmt_monto(v, moneda)
    avisos = []

    for f in por_factura:
        if f["saldo"] > TOLERANCIA and f["vencimiento"] and f["vencimiento"] < hoy:
            avisos.append({"nivel": "alta", "texto": f"La factura {f['numero'] or '(sin número)'} venció el "
                           f"{f['vencimiento']:%d/%m/%Y} y tiene un saldo de {fm(f['saldo'])} sin pagar."})
    if estado == "Pagado de más":
        avisos.append({"nivel": "alta", "texto": f"Se pagó {fm(pagado - facturado)} más de lo facturado. Revisá los pagos."})
    if estado == "Pagos sin factura":
        avisos.append({"nivel": "media", "texto": "Hay pagos registrados pero ninguna factura cargada."})
    if presupuesto > TOLERANCIA and facturado > presupuesto * 1.01:
        exceso = facturado - presupuesto
        avisos.append({"nivel": "media", "texto": f"Lo facturado ({fm(facturado)}) supera el presupuesto ({fm(presupuesto)}) "
                       f"en {fm(exceso)} ({exceso / presupuesto * 100:.1f}%)."})
    if presupuesto <= TOLERANCIA and facturado > TOLERANCIA:
        avisos.append({"nivel": "info", "texto": "Este trabajo no tiene presupuesto cargado, no se puede comparar con la factura."})
    if trabajo.get("estado") == "Realizado" and facturado <= TOLERANCIA and pagado <= TOLERANCIA:
        avisos.append({"nivel": "media", "texto": "El trabajo figura como realizado pero todavía no tiene factura cargada."})

    con_foto_factura = {d.get("factura_id") for d in documentos if d.get("tipo") == "Factura"}
    for f in facturas:
        if f["id"] not in con_foto_factura:
            avisos.append({"nivel": "info", "texto": f"Falta la foto o PDF de la factura {f.get('numero') or '(sin número)'}."})
    con_comprobante = {d.get("pago_id") for d in documentos if d.get("tipo") == "Comprobante de pago"}
    for p in pagos:
        if p["id"] not in con_comprobante:
            avisos.append({"nivel": "info", "texto": f"Falta el comprobante del pago del {a_fecha(p.get('fecha_pago')):%d/%m/%Y} "
                           f"({fm(_n(p.get('monto')))})." if a_fecha(p.get("fecha_pago")) else "Falta el comprobante de un pago."})

    orden = {"alta": 0, "media": 1, "info": 2}
    return {"moneda": moneda, "presupuesto": presupuesto, "facturado": facturado, "pagado": pagado, "saldo": saldo,
            "estado_pago": estado, "por_factura": por_factura, "sobrante": sobrante,
            "avisos": sorted(avisos, key=lambda a: orden[a["nivel"]])}


# ----------------------------------------------------------------
# Cuentas por pagar (por proveedor y por moneda)
# ----------------------------------------------------------------
def _clave_empresa(tercero):
    return re.sub(r"\s+", " ", str((tercero or {}).get("contacto") or (tercero or {}).get("nombre") or "Sin proveedor")).strip().casefold()


def cuentas_por_pagar(terceros_por_id, trabajos, facturas, pagos, hoy=None):
    """
    Estado de cuenta por proveedor (agrupando los registros de la misma empresa) y por moneda.
    Los trabajos cancelados no cuentan. Devuelve:
      filas:      [{empresa, moneda, trabajos, presupuesto, facturado, pagado, saldo, vencido}]
      totales:    {moneda: {facturado, pagado, saldo, vencido}}
      vencidas:   facturas vencidas con saldo
      sin_factura: trabajos realizados que todavía no tienen ninguna factura
    """
    hoy = hoy or date.today()
    fact_por_trabajo, pagos_por_trabajo = collections.defaultdict(list), collections.defaultdict(list)
    for f in facturas:
        fact_por_trabajo[f["trabajo_id"]].append(f)
    for p in pagos:
        pagos_por_trabajo[p["trabajo_id"]].append(p)

    acum = {}
    nombre_visible = {}                       # una misma empresa se muestra siempre con el mismo nombre
    vencidas, sin_factura = [], []
    for t in trabajos:
        if t.get("estado") == "Cancelado":
            continue
        tercero = terceros_por_id.get(t.get("tercero_id"), {})
        empresa = nombre_visible.setdefault(
            _clave_empresa(tercero), str(tercero.get("contacto") or tercero.get("nombre") or "Sin proveedor").strip())
        moneda = t.get("moneda") or "PYG"
        r = resumen_trabajo(t, fact_por_trabajo[t["id"]], pagos_por_trabajo[t["id"]], hoy=hoy)
        fila = acum.setdefault((_clave_empresa(tercero), moneda), {"empresa": empresa, "moneda": moneda, "trabajos": 0,
                                                                    "presupuesto": 0.0, "facturado": 0.0, "pagado": 0.0,
                                                                    "saldo": 0.0, "vencido": 0.0})
        fila["trabajos"] += 1
        fila["presupuesto"] += r["presupuesto"]
        fila["facturado"] += r["facturado"]
        fila["pagado"] += r["pagado"]
        fila["saldo"] += r["saldo"]
        for f in r["por_factura"]:
            if f["saldo"] > TOLERANCIA and f["vencimiento"] and f["vencimiento"] < hoy:
                fila["vencido"] += f["saldo"]
                vencidas.append({"trabajo": t.get("codigo"), "empresa": empresa, "factura": f["numero"], "moneda": moneda,
                                 "vencimiento": f["vencimiento"], "saldo": f["saldo"], "dias": (hoy - f["vencimiento"]).days})
        if t.get("estado") == "Realizado" and r["facturado"] <= TOLERANCIA and r["pagado"] <= TOLERANCIA:
            sin_factura.append({"trabajo": t.get("codigo"), "empresa": empresa, "descripcion": t.get("descripcion"),
                                "moneda": moneda, "presupuesto": r["presupuesto"]})

    filas = sorted(acum.values(), key=lambda r: (-r["saldo"], r["empresa"].casefold()))
    for fila in filas:
        for k in ("presupuesto", "facturado", "pagado", "saldo", "vencido"):
            fila[k] = round(fila[k], 2)
    totales = {m: {"facturado": 0.0, "pagado": 0.0, "saldo": 0.0, "vencido": 0.0} for m in MONEDAS}
    for fila in filas:
        for k in ("facturado", "pagado", "saldo", "vencido"):
            totales[fila["moneda"]][k] = round(totales[fila["moneda"]][k] + fila[k], 2)
    return {"filas": filas, "totales": totales, "vencidas": sorted(vencidas, key=lambda v: v["vencimiento"]),
            "sin_factura": sin_factura}


# ----------------------------------------------------------------
# Fotos de facturas: achicar antes de subir (el plan gratis de Supabase da 1 GB para archivos)
# ----------------------------------------------------------------
MAX_PDF_MB = 15


def preparar_archivo(nombre, contenido: bytes, content_type=None, max_lado=1600, calidad=80):
    """
    Prepara un archivo para subirlo. Las fotos se achican (máx. 1600 px, JPEG calidad 80) y se enderezan
    según la orientación del celular; los PDF se dejan tal cual. Devuelve un dict con
    nombre, contenido, content_type, original_kb, final_kb o con 'error'.
    """
    ext = (nombre or "").rsplit(".", 1)[-1].lower() if "." in (nombre or "") else ""
    original_kb = len(contenido) / 1024
    if ext == "pdf" or content_type == "application/pdf":
        if len(contenido) > MAX_PDF_MB * 1024 * 1024:
            return {"error": f"El PDF «{nombre}» pesa {original_kb / 1024:.1f} MB y el máximo es {MAX_PDF_MB} MB."}
        return {"nombre": nombre, "contenido": contenido, "content_type": "application/pdf",
                "original_kb": original_kb, "final_kb": original_kb}
    try:
        from PIL import Image, ImageOps
        imagen = ImageOps.exif_transpose(Image.open(io.BytesIO(contenido)))
        if imagen.mode in ("RGBA", "LA", "P"):
            imagen = imagen.convert("RGBA")
            fondo = Image.new("RGB", imagen.size, (255, 255, 255))
            fondo.paste(imagen, mask=imagen.split()[-1])
            imagen = fondo
        else:
            imagen = imagen.convert("RGB")
        imagen.thumbnail((max_lado, max_lado))
        salida = io.BytesIO()
        imagen.save(salida, "JPEG", quality=calidad, optimize=True)
        achicada = salida.getvalue()
    except Exception as e:
        return {"error": f"No se pudo leer la imagen «{nombre}»: {e}"}
    if len(achicada) >= len(contenido) and ext in ("jpg", "jpeg"):
        achicada = contenido                    # ya era liviana: se deja como estaba
    base = (nombre or "foto").rsplit(".", 1)[0]
    return {"nombre": f"{base}.jpg", "contenido": achicada, "content_type": "image/jpeg",
            "original_kb": original_kb, "final_kb": len(achicada) / 1024}
