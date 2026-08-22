"""
generar_qr.py
--------------------------------------------------------------
Script standalone para generar las etiquetas QR de tus equipos.
NO es parte de la app de Streamlit — se corre aparte, en tu propia
computadora, cada vez que das de alta un equipo nuevo (o para generar
todo el lote inicial de una sola vez).

Instalación (una sola vez):
    pip install "qrcode[pil]"

Uso — un solo equipo:
    python generar_qr.py 50000000 "Extrusora 01"

Uso — un lote completo (genera uno por cada ID en el rango, incluido el final):
    python generar_qr.py --rango 50000000 50000010

Las imágenes se guardan en una carpeta "qr_equipos/" al lado de este script,
listas para imprimir y pegar en cada máquina.
--------------------------------------------------------------
"""
import argparse
import os
import qrcode

# 👉 Reemplazá esto por la URL real de tu app en Streamlit Cloud
#    (la que ves en el navegador cuando entrás a tu app ya desplegada).
URL_BASE = "https://mi-saas.streamlit.app"

CARPETA_SALIDA = "qr_equipos"


def generar_qr_equipo(equipo_id: int, nombre: str = "") -> str:
    """Genera el QR de un equipo y devuelve la ruta del archivo PNG creado."""
    url = f"{URL_BASE}/?equipo={equipo_id}"

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=12,
        border=4
    )
    qr.add_data(url)
    qr.make(fit=True)
    imagen = qr.make_image(fill_color="black", back_color="white")

    os.makedirs(CARPETA_SALIDA, exist_ok=True)
    nombre_archivo = str(equipo_id)
    if nombre:
        nombre_archivo += "_" + nombre.strip().replace(" ", "_")
    ruta = os.path.join(CARPETA_SALIDA, f"{nombre_archivo}.png")

    imagen.save(ruta)
    print(f"✅ QR generado: {ruta}  →  {url}")
    return ruta


def main():
    parser = argparse.ArgumentParser(description="Generador de códigos QR para equipos de planta.")
    parser.add_argument("equipo_id", nargs="?", type=int, help="ID numérico del equipo (ej: 50000000)")
    parser.add_argument("nombre", nargs="?", default="", help="Nombre del equipo (opcional, solo para el nombre del archivo)")
    parser.add_argument("--rango", nargs=2, type=int, metavar=("DESDE", "HASTA"),
                         help="Generar un lote completo, ej: --rango 50000000 50000010")
    args = parser.parse_args()

    if args.rango:
        desde, hasta = args.rango
        for equipo_id in range(desde, hasta + 1):
            generar_qr_equipo(equipo_id)
        print(f"\n✅ Listo: {hasta - desde + 1} códigos QR generados en la carpeta '{CARPETA_SALIDA}/'.")
    elif args.equipo_id:
        generar_qr_equipo(args.equipo_id, args.nombre)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
