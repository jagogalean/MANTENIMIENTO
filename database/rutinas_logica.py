"""
Lógica de las rutinas del operador (sin Streamlit ni base de datos: se puede probar sola).

Conceptos:
- Zona: un lugar físico con su QR (Planta Baja, 1er Piso...). Reúne las rutinas de varios equipos.
- Rutina (ítem): una tarea del operador, con su frecuencia (Diaria o Semanal), su paso a paso y sus fotos.
- Punto de control: lo que el operador responde dentro de una rutina. Puede ser «OK / No OK / No aplica»
  o un valor medido (con unidad y un rango aceptable opcional).
- Un ítem sin puntos de control se responde con un único OK / No OK / No aplica.
"""
import collections
import io
import re
from datetime import date, datetime, timedelta

RESULTADOS = ("OK", "NO_OK", "NA")
ETIQUETA_RESULTADO = {"OK": "OK", "NO_OK": "No OK", "NA": "No aplica"}
MAX_FALLA = 900


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def a_fecha(v):
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def hoy_paraguay():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Asuncion")).date()
    except Exception:
        return (datetime.utcnow() - timedelta(hours=3)).date()


def lunes_de(f):
    return f - timedelta(days=f.weekday())


def fmt_num(v, dec=1):
    """7,5 / 12 (sin ceros de más, con coma decimal)."""
    n = _num(v)
    if n is None:
        return "—"
    return (f"{n:.{dec}f}".rstrip("0").rstrip(".") if dec else f"{n:.0f}").replace(".", ",")


def pin_valido(pin):
    return bool(re.fullmatch(r"[0-9]{4}", str(pin or "")))


def url_ronda(base_url, zona_id):
    return f"{str(base_url or '').rstrip('/')}/?ronda={zona_id}"


# ----------------------------------------------------------------
# Qué toca hacer hoy
# ----------------------------------------------------------------
def estado_items(items, hechos, hoy):
    """
    Para cada ítem activo de la zona dice si ya se hizo en su período: la rutina DIARIA, hoy; la SEMANAL, en la semana de hoy (lunes a domingo).
    hechos: [{item_id, fecha, operador, resultado, hora}]. Devuelve [{item, estado, hecho_por, hora, resultado}] en el orden de los ítems.
    """
    lunes = lunes_de(hoy)
    domingo = lunes + timedelta(days=6)
    ultimo = {}
    for h in hechos:
        d = a_fecha(h.get("fecha"))
        if d is None:
            continue
        ultimo[(h["item_id"], d)] = h
    salida = []
    for it in items:
        if it.get("activo") is False:
            continue
        if it.get("frecuencia") == "Semanal":
            candidatos = [h for (iid, d), h in ultimo.items() if iid == it["id"] and lunes <= d <= domingo]
        else:
            candidatos = [h for (iid, d), h in ultimo.items() if iid == it["id"] and d == hoy]
        h = max(candidatos, key=lambda x: (a_fecha(x.get("fecha")), x.get("hora") or "")) if candidatos else None
        salida.append({"item": it, "estado": "hecho" if h else "pendiente", "hecho_por": h.get("operador") if h else None,
                       "hora": h.get("hora") if h else None, "resultado": h.get("resultado") if h else None,
                       "fecha_hecho": a_fecha(h.get("fecha")) if h else None})
    return salida


# ----------------------------------------------------------------
# Evaluación de lo que responde el operador
# ----------------------------------------------------------------
def fuera_de_rango(punto, valor):
    v = _num(valor)
    if v is None or punto.get("tipo") != "numero":
        return False
    mn, mx = _num(punto.get("minimo")), _num(punto.get("maximo"))
    return (mn is not None and v < mn) or (mx is not None and v > mx)


def texto_rango(punto):
    mn, mx = _num(punto.get("minimo")), _num(punto.get("maximo"))
    u = f" {punto['unidad']}" if punto.get("unidad") else ""
    if mn is not None and mx is not None:
        return f"{fmt_num(mn)} a {fmt_num(mx)}{u}"
    if mn is not None:
        return f"mínimo {fmt_num(mn)}{u}"
    if mx is not None:
        return f"máximo {fmt_num(mx)}{u}"
    return None


def evaluar_item(item, puntos, respuestas, comentario="", tiene_foto=False):
    """
    respuestas: {punto_id: {"resultado": OK/NO_OK/NA, "valor": número}} para los puntos de control; para un ítem SIN puntos,
    {None: {"resultado": ...}}. Devuelve:
      resultado   OK / NO_OK / NA (el del ítem completo)
      detalle     lista con cada punto: texto, tipo, unidad, resultado, valor, fuera_rango, rango
      problemas   frases de lo que salió mal
      faltan      qué falta responder (para no dejar avanzar)
    """
    faltan, detalle, problemas = [], [], []
    lista = puntos or [{"id": None, "texto": item.get("titulo"), "tipo": "ok"}]
    for p in lista:
        r = respuestas.get(p.get("id")) or {}
        res, val = r.get("resultado"), _num(r.get("valor"))
        fila = {"punto_id": p.get("id"), "texto": p.get("texto"), "tipo": p.get("tipo") or "ok", "unidad": p.get("unidad"), "resultado": None,
                "valor": None, "fuera_rango": False, "rango": texto_rango(p)}
        if (p.get("tipo") or "ok") == "numero":
            if res == "NA":
                fila["resultado"] = "NA"
            elif val is None:
                faltan.append(f"Escribí el valor de «{p.get('texto')}» (o marcá «No aplica»).")
            else:
                fila["valor"] = val
                fila["fuera_rango"] = fuera_de_rango(p, val)
                fila["resultado"] = "NO_OK" if fila["fuera_rango"] else "OK"
        else:
            if res not in RESULTADOS:
                faltan.append(f"Elegí OK, No OK o No aplica en «{p.get('texto')}».")
            else:
                fila["resultado"] = res
        if fila["resultado"] == "NO_OK":
            if fila["tipo"] == "numero":
                problemas.append(f"{p.get('texto')}: {fmt_num(fila['valor'])}{' ' + p['unidad'] if p.get('unidad') else ''} (fuera de {fila['rango']})")
            else:
                problemas.append(f"{p.get('texto')}: No OK")
        detalle.append(fila)
    contestados = [d["resultado"] for d in detalle if d["resultado"]]
    if problemas:
        resultado = "NO_OK"
    elif contestados and any(r in ("OK",) for r in contestados):
        resultado = "OK"
    else:
        resultado = "NA"
    if problemas and len((comentario or "").strip()) < 3:
        faltan.append("Contá qué viste (escribí un comentario) porque hay un problema.")
    if problemas and item.get("foto_requerida_no_ok") and not tiene_foto:
        faltan.append("Sacá una foto del problema (esta rutina la pide).")
    return {"resultado": resultado, "detalle": detalle, "problemas": problemas, "faltan": faltan}


def texto_falla(zona_nombre, item, evaluacion, comentario):
    """Texto del reporte de falla que se crea solo cuando algo sale mal."""
    t = f"Ronda «{zona_nombre}» — {item.get('codigo') or ''} {item.get('titulo')}".replace("  ", " ")
    if evaluacion["problemas"]:
        t += ". Problemas: " + "; ".join(evaluacion["problemas"])
    if (comentario or "").strip():
        t += f". Comentario del operador: {comentario.strip()}"
    return t[:MAX_FALLA]


def armar_respuesta(item, zona_nombre, evaluacion, comentario, foto_ruta):
    """Lo que se envía a la base por cada ítem respondido."""
    r = {"item_id": item["id"], "item_titulo": item.get("titulo"), "resultado": evaluacion["resultado"], "detalle": evaluacion["detalle"],
         "comentario": (comentario or "").strip() or None, "foto_ruta": foto_ruta}
    if evaluacion["resultado"] == "NO_OK":
        r["falla_texto"] = texto_falla(zona_nombre, item, evaluacion, comentario)
    return r


# ----------------------------------------------------------------
# Cumplimiento y lecturas (para el panel del administrador)
# ----------------------------------------------------------------
def cumplimiento(items, respuestas, desde, hasta):
    """
    Cuánto se hizo de lo que tocaba entre dos fechas.
      - Una rutina DIARIA toca todos los días del período; la SEMANAL, una vez por semana (lunes a domingo, solo las semanas completas
        dentro del período; la semana en curso cuenta solo si ya tiene algo hecho o terminó).
      - Solo cuentan las rutinas activas, y desde el día en que se crearon.
    respuestas: [{item_id, fecha, resultado, operador}]. Devuelve {por_zona, por_dia, por_item, total, pendientes_hoy}.
    """
    hoy = hoy_paraguay()
    hechas = collections.defaultdict(set)                  # item_id -> fechas hechas
    for r in respuestas:
        d = a_fecha(r.get("fecha"))
        if d and r.get("item_id") is not None:
            hechas[r["item_id"]].add(d)
    dias = [desde + timedelta(days=i) for i in range((hasta - desde).days + 1)]
    por_zona = collections.defaultdict(lambda: {"esperadas": 0, "hechas": 0})
    por_dia = collections.defaultdict(lambda: {"esperadas": 0, "hechas": 0})
    por_item = {}
    for it in items:
        if it.get("activo") is False:
            continue
        creado = a_fecha(it.get("creado_en")) or desde
        zona = it.get("zona_nombre") or "(sin zona)"
        esp = hec = 0
        if it.get("frecuencia") == "Semanal":
            semanas = sorted({lunes_de(d) for d in dias})
            for lunes in semanas:
                fin = lunes + timedelta(days=6)
                dentro = max(desde, lunes) == lunes and min(hasta, fin) == fin                 # semana completa dentro del período
                if fin < creado:
                    continue
                hecho = any(lunes <= d <= fin for d in hechas.get(it["id"], ()))
                if not dentro and not hecho:
                    continue
                if lunes <= hoy <= fin and not hecho:                                          # la semana en curso todavía puede cumplirse
                    continue
                esp += 1
                hec += 1 if hecho else 0
                clave = fin if fin <= hasta else hasta
                por_dia[clave]["esperadas"] += 1
                por_dia[clave]["hechas"] += 1 if hecho else 0
        else:
            for d in dias:
                if d < creado or d > hoy:
                    continue
                esp += 1
                hecho = d in hechas.get(it["id"], ())
                hec += 1 if hecho else 0
                por_dia[d]["esperadas"] += 1
                por_dia[d]["hechas"] += 1 if hecho else 0
        por_zona[zona]["esperadas"] += esp
        por_zona[zona]["hechas"] += hec
        por_item[it["id"]] = {"codigo": it.get("codigo"), "titulo": it.get("titulo"), "zona": zona, "frecuencia": it.get("frecuencia"), "esperadas": esp, "hechas": hec}
    pct = lambda h, e: round(h / e * 100, 1) if e else None
    total = {"esperadas": sum(z["esperadas"] for z in por_zona.values()), "hechas": sum(z["hechas"] for z in por_zona.values())}
    total["pct"] = pct(total["hechas"], total["esperadas"])
    pendientes = [{"zona": it.get("zona_nombre"), "codigo": it.get("codigo"), "titulo": it.get("titulo"), "frecuencia": it.get("frecuencia")}
                  for it in items if it.get("activo") is not False and (
                      (it.get("frecuencia") != "Semanal" and hoy not in hechas.get(it["id"], ())) or
                      (it.get("frecuencia") == "Semanal" and not any(lunes_de(hoy) <= d <= lunes_de(hoy) + timedelta(days=6) for d in hechas.get(it["id"], ()))))]
    return {"por_zona": {z: {**v, "pct": pct(v["hechas"], v["esperadas"])} for z, v in por_zona.items()},
            "por_dia": {d: {**v, "pct": pct(v["hechas"], v["esperadas"])} for d, v in sorted(por_dia.items())},
            "por_item": por_item, "total": total, "pendientes_hoy": pendientes}


def serie_lecturas(respuestas, item_id, punto_texto):
    """Valores medidos de un punto a lo largo del tiempo: [(fecha, valor, fuera_rango, operador)]."""
    serie = []
    for r in respuestas:
        if r.get("item_id") != item_id:
            continue
        for d in r.get("detalle") or []:
            if d.get("texto") == punto_texto and d.get("tipo") == "numero" and d.get("valor") is not None:
                serie.append((a_fecha(r.get("fecha")), float(d["valor"]), bool(d.get("fuera_rango")), r.get("operador")))
    return sorted(serie, key=lambda s: (s[0] or date.min))


# ----------------------------------------------------------------
# Textos y fotos
# ----------------------------------------------------------------
def pasos_desde_texto(texto):
    """Un paso por renglón; se quitan numeraciones y viñetas ('1.', '2)', '-', '•')."""
    pasos = []
    for linea in str(texto or "").splitlines():
        limpio = re.sub(r"^\s*(?:\d+\s*[.)\-:]|[-•*·])\s*", "", linea).strip()
        if limpio:
            pasos.append(limpio)
    return pasos


def preparar_foto(contenido: bytes, max_lado=1600, calidad=80):
    """Achica una foto de celular (máx. 1600 px, JPEG calidad 80), la endereza según como se sacó y devuelve (bytes, content_type)."""
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
    return salida.getvalue(), "image/jpeg"


def prompt_pasos(zona, item, puntos):
    """Pedido a la IA para que sugiera un BORRADOR de paso a paso (siempre lo revisa una persona)."""
    pts = "; ".join(p["texto"] + (f" ({p['unidad']})" if p.get("unidad") else "") for p in puntos) or "sin puntos de control"
    return (f"Sos un técnico de mantenimiento industrial en una planta de film plástico. Escribí el paso a paso para que un OPERADOR (no un técnico) haga esta rutina de control:\n"
            f"Zona: {zona}\nRutina: {item.get('titulo')}\nCondición de la máquina: {item.get('condicion') or 'no indicada'}\nCriterio de aceptación: {item.get('criterio') or 'no indicado'}\n"
            f"Puntos a controlar: {pts}\n\nReglas: entre 4 y 8 pasos cortos, en español rioplatense simple, un paso por renglón, numerados, empezando por la seguridad. "
            f"No inventes valores numéricos ni marcas. Si algo depende del equipo, decí «según la placa del equipo» o «según la receta». Respondé SOLO con la lista numerada.")


# ----------------------------------------------------------------
# QR e imprimibles
# ----------------------------------------------------------------
def qr_png(url, caja=10):
    import qrcode
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=caja, border=3)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def pdf_etiquetas(zonas, titulo="RONDA DEL OPERADOR"):
    """
    Una página A4 por zona, lista para imprimir y plastificar: nombre de la zona, QR grande, los pasos para usarlo y la lista de rutinas.
    zonas: [{nombre, url, items: [{codigo, titulo, frecuencia}]}]
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    ancho, alto = A4
    for z in zonas:
        c.setFillColorRGB(0.12, 0.23, 0.37)
        c.rect(0, alto - 3.2 * cm, ancho, 3.2 * cm, fill=1, stroke=0)
        c.setFillColorRGB(1, 1, 1)
        c.setFont("Helvetica-Bold", 14)
        c.drawCentredString(ancho / 2, alto - 1.3 * cm, titulo)
        c.setFont("Helvetica-Bold", 30)
        c.drawCentredString(ancho / 2, alto - 2.6 * cm, z["nombre"])
        qr = ImageReader(io.BytesIO(qr_png(z["url"], caja=12)))
        lado = 11.5 * cm
        c.drawImage(qr, (ancho - lado) / 2, alto - 3.8 * cm - lado, lado, lado)
        c.setFillColorRGB(0, 0, 0)
        c.setFont("Helvetica-Bold", 16)
        y = alto - 4.6 * cm - lado
        c.drawCentredString(ancho / 2, y, "Escaneá con la cámara del celular")
        c.setFont("Helvetica", 13)
        for i, paso in enumerate(("1. Elegí tu nombre y escribí tu PIN.", "2. Hacé cada control en orden: leé los pasos y mirá las fotos.", "3. Si algo está mal, marcá «No OK» y sacá una foto.", "4. Tocá «Enviar ronda» al terminar."), 1):
            c.drawCentredString(ancho / 2, y - i * 0.75 * cm, paso)
        y -= 5.2 * cm
        c.setFont("Helvetica-Bold", 11)
        c.drawString(2.2 * cm, y, f"Rutinas de esta zona ({len(z.get('items', []))}):")
        c.setFont("Helvetica", 9.5)
        y -= 0.55 * cm
        for it in z.get("items", [])[:14]:
            marca = "Diaria" if it.get("frecuencia") != "Semanal" else "Semanal"
            texto = f"{it.get('codigo') or '':<7} [{marca}] {it.get('titulo') or ''}"
            c.drawString(2.2 * cm, y, texto[:112])
            y -= 0.48 * cm
        c.setFont("Helvetica", 8)
        c.setFillColorRGB(0.4, 0.4, 0.4)
        c.drawCentredString(ancho / 2, 1.0 * cm, z["url"])
        c.showPage()
    c.save()
    return buf.getvalue()
