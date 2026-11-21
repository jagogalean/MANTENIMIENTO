"""
Reglas de negocio de las Órdenes de Trabajo, en UN solo lugar.

Antes estas reglas estaban repetidas dentro de cada pantalla y cada una
hacía las cosas un poco distinto. Ahora Órdenes de trabajo, Mis OTs,
Reportar falla, Avisos QR y Planes usan estas mismas funciones:

- generar_codigo_ot(): el código se calcula leyendo la base en el momento,
  no una copia de hace 15 segundos (reduce mucho los duplicados, H-06).
- validar_cambio_estado(): el permiso de trabajo es OBLIGATORIO para iniciar
  o completar una OT que lo requiere (H-11). Solo el admin puede forzar,
  y queda anotado.
- cambiar_estado(): al completar una OT preventiva, el plan registra la
  ejecución y calcula la próxima fecha, venga de la pantalla que venga (H-07),
  y siempre con la misma regla de cadencia (H-13).
- registrar_ejecucion_plan(): la regla única de "próxima fecha".
- Máquina parada: se marca con un prefijo en la descripción de la OT, sin
  cambiar la estructura de la base.
"""
from datetime import datetime, timedelta

import streamlit as st

from database.conection import (
    supabase, insert_ot, update_ot, consumir_repuesto_seguro,
    get_ots_cached, get_repuestos_cached, get_planes, update_plan,
    insert_plan_ejecucion, get_plan_ejecuciones,
)

ESTADOS_OT = ["Pendiente", "En Ejecucion", "Bloqueada", "Completada"]
NOMBRE_ESTADO = {"Pendiente": "Pendiente", "En Ejecucion": "En ejecución", "Bloqueada": "Bloqueada",
                 "Completada": "Completada"}
TIPOS_OT = ["Correctivo", "Preventivo", "Predictivo"]
MARCA_PARADA = "[MÁQUINA PARADA]"


def _ahora():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Asuncion")).replace(tzinfo=None)
    except Exception:
        return datetime.now()


# ------------------------------------------------------------------
# Máquina parada
# ------------------------------------------------------------------
def es_parada(ot):
    return str(ot.get("descripcion") or "").startswith(MARCA_PARADA)


def con_marca_parada(texto, parada):
    texto = (texto or "").strip()
    if texto.startswith(MARCA_PARADA):
        texto = texto[len(MARCA_PARADA):].strip()
    return f"{MARCA_PARADA} {texto}" if parada else texto


def descripcion_sin_marca(ot):
    texto = str(ot.get("descripcion") or "")
    return texto[len(MARCA_PARADA):].strip() if texto.startswith(MARCA_PARADA) else texto


# ------------------------------------------------------------------
# Refrescos
# ------------------------------------------------------------------
def refrescar_ots():
    get_ots_cached.clear()
    st.session_state.ots = get_ots_cached()


def refrescar_repuestos():
    get_repuestos_cached.clear()
    st.session_state.repuestos = get_repuestos_cached()


def refrescar_planes():
    st.session_state.planes = get_planes()
    st.session_state.plan_ejecuciones = get_plan_ejecuciones()


# ------------------------------------------------------------------
# Código de OT
# ------------------------------------------------------------------
def generar_codigo_ot():
    """Siguiente código del año, leído de la base en este momento. Ej: OT-2026-0007.

    Nota: todavía no es 100 % a prueba de dos altas en el mismo segundo; para
    eso hace falta una secuencia en PostgreSQL (Etapa 2 del plan técnico).
    """
    prefijo = f"OT-{_ahora().year}-"
    try:
        filas = (supabase.table("ots").select("codigo").like("codigo", f"{prefijo}%")
                 .order("codigo", desc=True).limit(50).execute().data) or []
    except Exception:
        filas = get_ots_cached()
    numeros = []
    for f in filas:
        cod = str(f.get("codigo") or "")
        if cod.startswith(prefijo):
            try:
                numeros.append(int(cod[len(prefijo):]))
            except ValueError:
                pass
    return f"{prefijo}{(max(numeros) + 1 if numeros else 1):04d}"


# ------------------------------------------------------------------
# Alta de OT
# ------------------------------------------------------------------
def crear_ot(datos, carrito=None):
    """Crea la OT y descuenta los repuestos del carrito (cada uno por la RPC atómica).

    datos: dict con maquina_id, tipo_mantenimiento, descripcion, estado, tecnico_id, ...
    carrito: lista de {repuesto_id, nombre, cantidad}
    Devuelve (codigo, lista_de_repuestos_que_no_se_pudieron_descontar).
    """
    codigo = generar_codigo_ot()
    ahora = _ahora()
    fila = {
        "codigo": codigo,
        "estado": "Pendiente",
        "fecha_inicio": ahora.isoformat(),
        "horas_paro": 0,
        "costo_mano_obra": 0,
        "requiere_permiso_trabajo": False,
        "permiso_trabajo_emitido": False,
    }
    fila.update(datos)
    if fila.get("estado") == "Completada" and not fila.get("fecha_fin"):
        fila["fecha_fin"] = ahora.isoformat()
    creada = insert_ot(fila)
    ot_id = creada[0]["id"] if creada else None
    fallidos = []
    for item in carrito or []:
        try:
            consumir_repuesto_seguro(ot_id, item["repuesto_id"], item["cantidad"])
        except ValueError:
            fallidos.append(item.get("nombre") or str(item["repuesto_id"]))
    refrescar_ots()
    if carrito:
        refrescar_repuestos()
    return codigo, fallidos


# ------------------------------------------------------------------
# Cambios de estado
# ------------------------------------------------------------------
def falta_permiso(ot):
    return bool(ot.get("requiere_permiso_trabajo")) and not bool(ot.get("permiso_trabajo_emitido"))


def validar_cambio_estado(ot, nuevo_estado, motivo_bloqueo=None, forzar=False):
    """Devuelve un mensaje de error en lenguaje llano, o None si el cambio es válido."""
    if nuevo_estado not in ESTADOS_OT:
        return "Estado no válido."
    if nuevo_estado == "Bloqueada" and not (motivo_bloqueo or "").strip():
        return "Escribí el motivo del bloqueo (por ejemplo: falta un repuesto)."
    if nuevo_estado in ("En Ejecucion", "Completada") and falta_permiso(ot) and not forzar:
        return ("Esta OT requiere permiso de trabajo y todavía no está emitido. "
                "No se puede iniciar ni completar hasta que se emita.")
    return None


def cambiar_estado(ot, nuevo_estado, motivo_bloqueo=None, extra=None, forzar=False, usuario=None):
    """Aplica el cambio de estado con todas las reglas. Devuelve (ok, mensaje)."""
    error = validar_cambio_estado(ot, nuevo_estado, motivo_bloqueo, forzar)
    if error:
        return False, error
    ahora = _ahora()
    patch = dict(extra or {})
    patch["estado"] = nuevo_estado
    patch["motivo_bloqueo"] = (motivo_bloqueo or "").strip() if nuevo_estado == "Bloqueada" else None
    recien_completada = nuevo_estado == "Completada" and ot.get("estado") != "Completada"
    if recien_completada and not ot.get("fecha_fin"):
        patch["fecha_fin"] = ahora.isoformat()
    if forzar and usuario:
        nota = f"[Cierre forzado por {usuario.get('nombre') or 'administrador'} el {ahora:%d/%m/%Y %H:%M}]"
        patch["descripcion"] = f"{ot.get('descripcion') or ''}\n{nota}".strip()
    update_ot(ot.get("id"), patch)
    if recien_completada:
        registrar_ejecucion_plan(ot)
    refrescar_ots()
    return True, f"{ot.get('codigo')} quedó en «{NOMBRE_ESTADO.get(nuevo_estado, nuevo_estado)}»."


# ------------------------------------------------------------------
# Plan preventivo: regla única de próxima fecha
# ------------------------------------------------------------------
def proxima_fecha_plan(plan, fecha_realizada):
    """Sigue la cadencia programada (fecha programada + frecuencia), no "hoy + frecuencia",
    para que un atraso o un adelanto no desordene el calendario repartido.
    Si se atrasó varios ciclos, salta los vencidos."""
    frecuencia = int(plan.get("frecuencia_dias") or 30)
    try:
        base = datetime.strptime(str(plan.get("proxima_ejecucion"))[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        base = fecha_realizada
    nueva = base + timedelta(days=frecuencia)
    while nueva <= fecha_realizada:
        nueva += timedelta(days=frecuencia)
    return nueva


def registrar_ejecucion_plan(ot_o_plan, es_plan=False):
    """Registra la ejecución del plan y mueve su próxima fecha.

    Recibe una OT (usa su plan_id) o, con es_plan=True, el plan directamente.
    """
    if es_plan:
        plan = ot_o_plan
    else:
        plan_id = ot_o_plan.get("plan_id")
        if not plan_id:
            return False
        planes = st.session_state.get("planes") or get_planes()
        plan = next((p for p in planes if p.get("id") == plan_id), None)
    if not plan:
        return False
    hoy = _ahora().date()
    nueva = proxima_fecha_plan(plan, hoy)
    insert_plan_ejecucion({
        "plan_id": plan.get("id"),
        "maquina_id": plan.get("maquina_id"),
        "fecha_programada": plan.get("proxima_ejecucion"),
        "fecha_realizada": hoy.strftime("%Y-%m-%d"),
    })
    update_plan(plan.get("id"), {
        "ultima_ejecucion": hoy.strftime("%Y-%m-%d"),
        "proxima_ejecucion": nueva.strftime("%Y-%m-%d"),
    })
    refrescar_planes()
    return True
