import os
import io
import json
import zipfile
import sqlite3
import urllib.request
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
from database.conection import (
    get_maquinas, get_ots, get_repuestos, get_ot_repuestos,
    get_fallas, get_checklists, get_terceros, get_tecnicos,
    get_planes, get_actividades, get_plan_ejecuciones,
    get_presupuestos, get_solicitudes_compra,
    delete_ot, delete_ot_repuestos_por_ot, delete_falla,
    delete_checklist, delete_solicitud_compra,
    borrar_fotos_storage_solicitud, get_ots_cached
)

RUTA_DISCO_DEFAULT = r"E:\CMMS_Datos"


def _parse_fecha(fecha_str):
    if not fecha_str:
        return None
    try:
        limpia = str(fecha_str).replace("Z", "+00:00")[:19]
        if "T" in limpia:
            return datetime.fromisoformat(limpia).date()
        return datetime.strptime(limpia[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def _combinar_historico(df_existente: pd.DataFrame, df_nuevo: pd.DataFrame, col_id: str = "id") -> pd.DataFrame:
    """
    Une lo que ya estaba guardado en el Disco Externo E: con lo nuevo que viene de Supabase.
    Si una fila se actualizó (ej. una OT pasó de Pendiente a Completada), pisa la versión vieja
    con la nueva, pero NUNCA borra las filas históricas que ya se habían purgado de Supabase.
    """
    if df_existente is None or df_existente.empty:
        return df_nuevo
    if df_nuevo is None or df_nuevo.empty:
        return df_existente
    combinado = pd.concat([df_existente, df_nuevo], ignore_index=True)
    if col_id in combinado.columns:
        combinado = combinado.drop_duplicates(subset=[col_id], keep="last")
        combinado = combinado.sort_values(by=col_id, ascending=False)
    return combinado


def _serializar_columnas_complejas(df: pd.DataFrame) -> pd.DataFrame:
    """Convierte listas o diccionarios (como rca o foto_urls) a texto JSON para que Excel y SQLite no fallen."""
    df_limpio = df.copy()
    for col in df_limpio.columns:
        df_limpio[col] = df_limpio[col].apply(
            lambda x: json.dumps(x, ensure_ascii=False) if isinstance(x, (dict, list)) else x
        )
    return df_limpio


def sincronizar_en_disco_externo(ruta_base: str):
    """
    Guarda y acumula todas las tablas en:
    1) Archivos Excel limpios e individuales en E:\\CMMS_Datos\\PowerBI_Excel\\
    2) Base de datos completa SQLite en E:\\CMMS_Datos\\cmms_historico.db
    3) Descarga las fotos de las Solicitudes de Compra en E:\\CMMS_Datos\\Fotos_Compras\\
    """
    carpeta_excel = os.path.join(ruta_base, "PowerBI_Excel")
    carpeta_fotos = os.path.join(ruta_base, "Fotos_Compras")
    ruta_sqlite = os.path.join(ruta_base, "cmms_historico.db")

    os.makedirs(carpeta_excel, exist_ok=True)
    os.makedirs(carpeta_fotos, exist_ok=True)

    # 1. Traer foto fresca de Supabase
    maquinas = get_maquinas()
    tecnicos = get_tecnicos()
    repuestos = get_repuestos()
    ots = get_ots()
    ot_repuestos = get_ot_repuestos()
    fallas = get_fallas()
    checklists = get_checklists()
    terceros = get_terceros()
    planes = get_planes()
    actividades = get_actividades()
    ejecuciones = get_plan_ejecuciones()
    presupuestos = get_presupuestos()
    solicitudes_compra = get_solicitudes_compra()

    # Mapas de nombres para enriquecer las tablas de Power BI
    map_maq = {m["id"]: m.get("nombre") for m in maquinas}
    map_maq_cod = {m["id"]: m.get("codigo") for m in maquinas}
    map_maq_sec = {m["id"]: m.get("seccion") for m in maquinas}
    map_tec = {t["id"]: t.get("nombre") for t in tecnicos}
    map_rep_nom = {r["id"]: r.get("nombre") for r in repuestos}
    map_rep_cod = {r["id"]: r.get("codigo_interno") for r in repuestos}
    map_rep_oo = {r["id"]: r.get("codigo_openorange") for r in repuestos}
    map_rep_costo = {r["id"]: r.get("costo_unitario", 0) for r in repuestos}

    # Enriquecer OTs para Power BI
    for o in ots:
        o["maquina_nombre"] = map_maq.get(o.get("maquina_id"), "Desconocida")
        o["maquina_codigo"] = map_maq_cod.get(o.get("maquina_id"), "")
        o["seccion"] = map_maq_sec.get(o.get("maquina_id"), "")
        o["tecnico_nombre"] = map_tec.get(o.get("tecnico_id"), "Sin asignar")

    # Enriquecer Consumo de Repuestos por OT para Power BI
    for orr in ot_repuestos:
        rid = orr.get("repuesto_id")
        cant = orr.get("cantidad_usada", 0) or 0
        costo_u = map_rep_costo.get(rid, 0) or 0
        orr["repuesto_nombre"] = map_rep_nom.get(rid, "Desconocido")
        orr["codigo_interno"] = map_rep_cod.get(rid, "")
        orr["codigo_openorange"] = map_rep_oo.get(rid, "")
        orr["costo_unitario_gs"] = costo_u
        orr["costo_total_gs"] = cant * costo_u

    # Enriquecer Solicitudes de Compra y descargar fotos al disco E:
    for sc in solicitudes_compra:
        sc["maquina_nombre"] = map_maq.get(sc.get("maquina_id"), "No aplica")
        urls = sc.get("foto_urls") or []
        if isinstance(urls, list) and urls:
            carpeta_sc = os.path.join(carpeta_fotos, f"SC_{sc.get('id')}")
            os.makedirs(carpeta_sc, exist_ok=True)
            for idx, url in enumerate(urls):
                try:
                    ext = ".jpg" if ".jpg" in url.lower() or ".jpeg" in url.lower() else ".png"
                    archivo_local = os.path.join(carpeta_sc, f"foto_{idx+1}{ext}")
                    if not os.path.exists(archivo_local):
                        urllib.request.urlretrieve(url, archivo_local)
                except Exception:
                    pass

    tablas = {
        "Maquinas": (pd.DataFrame(maquinas), "id", False),
        "Tecnicos": (pd.DataFrame(tecnicos), "id", False),
        "Stock_Repuestos": (pd.DataFrame(repuestos), "id", False),
        "Terceros_Proveedores": (pd.DataFrame(terceros), "id", False),
        "Planes_Preventivos": (pd.DataFrame(planes), "id", False),
        "Planes_Actividades": (pd.DataFrame(actividades), "id", False),
        "Presupuesto_Mensual": (pd.DataFrame(presupuestos), "id", False),
        # Tablas históricas acumulativas (True = conserva lo que ya estaba en el disco E:)
        "OTs_Historico_Completo": (pd.DataFrame(ots), "id", True),
        "Consumo_Repuestos_OT": (pd.DataFrame(ot_repuestos), "id", True),
        "Solicitudes_Compra": (pd.DataFrame(solicitudes_compra), "id", True),
        "Fallas_RCA": (pd.DataFrame(fallas), "id", True),
        "Checklists_Turnos": (pd.DataFrame(checklists), "id", True),
        "Planes_Historial_Ejecuciones": (pd.DataFrame(ejecuciones), "id", True),
    }

    resumen_guardado = {}
    conn = sqlite3.connect(ruta_sqlite)

    for nombre_archivo, (df_nuevo, col_id, es_acumulativo) in tablas.items():
        ruta_xlsx = os.path.join(carpeta_excel, f"{nombre_archivo}.xlsx")
        df_nuevo_limpio = _serializar_columnas_complejas(df_nuevo) if not df_nuevo.empty else pd.DataFrame()

        if es_acumulativo and os.path.exists(ruta_xlsx):
            try:
                df_viejo = pd.read_excel(ruta_xlsx, engine="openpyxl")
                df_final = _combinar_historico(df_viejo, df_nuevo_limpio, col_id=col_id)
            except Exception:
                df_final = df_nuevo_limpio
        else:
            df_final = df_nuevo_limpio

        df_final.to_excel(ruta_xlsx, index=False, engine="openpyxl")
        if not df_final.empty:
            df_final.to_sql(nombre_archivo, conn, if_exists="replace", index=False)
        resumen_guardado[nombre_archivo] = len(df_final)

    conn.close()
    return resumen_guardado, carpeta_excel, ruta_sqlite


def purgar_datos_antiguos_supabase(dias_antiguedad: int = 30):
    """
    Borra de Supabase ÚNICAMENTE los registros cerrados/finalizados que tengan más de X días,
    para que Supabase nunca se llene pero los técnicos sigan viendo los últimos 30 días en el celular.
    """
    fecha_corte = datetime.now().date() - timedelta(days=dias_antiguedad)

    ots_borradas = 0
    for o in get_ots():
        if o.get("estado") == "Completada":
            f_fin = _parse_fecha(o.get("fecha_fin")) or _parse_fecha(o.get("fecha_inicio"))
            if f_fin and f_fin < fecha_corte:
                delete_ot_repuestos_por_ot(o.get("id"))
                delete_ot(o.get("id"))
                ots_borradas += 1

    compras_borradas = 0
    for sc in get_solicitudes_compra():
        if sc.get("estado") in ("Comprado", "Rechazado"):
            f_sol = _parse_fecha(sc.get("fecha_solicitud"))
            if f_sol and f_sol < fecha_corte:
                borrar_fotos_storage_solicitud(sc.get("id"))
                delete_solicitud_compra(sc.get("id"))
                compras_borradas += 1

    fallas_borradas = 0
    for f in get_fallas():
        if f.get("estado") == "Cerrada":
            f_det = _parse_fecha(f.get("fecha_deteccion"))
            if f_det and f_det < fecha_corte:
                delete_falla(f.get("id"))
                fallas_borradas += 1

    checklists_borrados = 0
    for c in get_checklists():
        f_chk = _parse_fecha(c.get("fecha"))
        if f_chk and f_chk < fecha_corte:
            delete_checklist(c.get("id"))
            checklists_borrados += 1

    # Refrescar memoria de la sesión
    get_ots_cached.clear()
    st.session_state.ots = get_ots()
    st.session_state.ot_repuestos = get_ot_repuestos()
    st.session_state.fallas = get_fallas()
    st.session_state.checklists = get_checklists()

    return {
        "ots": ots_borradas,
        "compras": compras_borradas,
        "fallas": fallas_borradas,
        "checklists": checklists_borrados
    }


def render_disco_externo():
    st.title("💾 Disco Externo (E:) & Power BI")
    st.write(
        "Sincronizá toda tu información directamente a tu disco externo en archivos de Excel limpios "
        "(listos para conectar a Power BI) y liberá espacio en Supabase borrando lo cerrado de hace más de 30 días."
    )

    ruta_disco = st.text_input(
        "📂 Ruta de tu Disco Externo para Power BI",
        value=st.session_state.get("ruta_disco_externo", RUTA_DISCO_DEFAULT),
        help="Por defecto apunta a tu disco E:\\CMMS_Datos"
    )
    st.session_state["ruta_disco_externo"] = ruta_disco

    unidad = os.path.splitdrive(ruta_disco)[0]  # Ej: "E:"
    disco_conectado = os.path.exists(unidad + "\\") if unidad else False

    if disco_conectado:
        st.success(f"🟢 Disco externo detectado correctamente en **{unidad}\\** — Listo para guardar directo en `{ruta_disco}`.")
    else:
        st.warning(
            f"🟠 En este momento no se detecta la unidad **{unidad}\\** directamente (puede ser que no esté enchufado "
            f"o que estés abriendo la app desde el servidor en la nube en vez de tu PC). "
            f"Si estás desde el navegador en la nube, podés usar el botón de descarga directa abajo."
        )

    st.markdown("---")
    st.subheader("Paso 1: Actualizar Disco Externo (Excel + Base de Datos)")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("💾 Guardar / Actualizar directo en Disco E:", disabled=not disco_conectado, use_container_width=True):
            with st.spinner("Sincronizando tablas, acumulando historial y descargando fotos al disco E:..."):
                resumen, carpeta_excel, ruta_sqlite = sincronizar_en_disco_externo(ruta_disco)
                st.session_state["respaldo_exitoso"] = True
                st.success(f"✅ ¡Sincronización completa en `{carpeta_excel}`!")
                st.json(resumen)

    with col2:
        st.caption("¿Entraste desde la web en la nube? Descargá el paquete ZIP directo a tu disco `E:\\CMMS_Datos`:")
        if st.button("📦 Preparar paquete para guardar en E: (Modo Nube)", use_container_width=True):
            with st.spinner("Armando todos los Excel limpios..."):
                carpeta_temp = "temp_respaldo_cmms"
                resumen, _, _ = sincronizar_en_disco_externo(carpeta_temp)
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                    for root, _, files in os.walk(carpeta_temp):
                        for file in files:
                            full_path = os.path.join(root, file)
                            rel_path = os.path.relpath(full_path, carpeta_temp)
                            zf.write(full_path, rel_path)
                zip_buffer.seek(0)
                st.session_state["zip_respaldo_bytes"] = zip_buffer.getvalue()
                st.session_state["respaldo_exitoso"] = True

        if st.session_state.get("zip_respaldo_bytes"):
            st.download_button(
                "⬇️ Guardar ZIP en E:\\CMMS_Datos",
                data=st.session_state["zip_respaldo_bytes"],
                file_name=f"CMMS_PowerBI_{datetime.now().strftime('%Y%m%d_%H%M')}.zip",
                mime="application/zip",
                use_container_width=True
            )

    # --- PASO 2: LIMPIEZA DE SUPABASE (SOLO SE ACTIVA DESPUÉS DE RESPALDAR) ---
    st.markdown("---")
    st.subheader("Paso 2: Liberar espacio en Supabase (Antigüedad > 30 días)")
    st.caption(
        "🔒 Por seguridad, este botón solo se habilita después de haber ejecutado el Paso 1 en esta sesión. "
        "Borra de Supabase únicamente las OTs Completadas, Solicitudes de Compra terminadas (y sus fotos), "
        "Fallas Cerradas y Checklists que tengan más de 30 días de antigüedad. "
        "**Nunca borra máquinas, ni stock actual, ni planes preventivos, ni OTs abiertas.**"
    )

    dias_corte = st.number_input("Borrar cerrados con más de cuántos días de antigüedad:", min_value=7, max_value=365, value=30, step=1)
    confirmar_purga = st.checkbox("Confirmo que ya están actualizados mis archivos en el Disco Externo E:")

    puede_purgar = st.session_state.get("respaldo_exitoso", False) and confirmar_purga
    if st.button("🧹 Limpiar datos antiguos de Supabase ahora", disabled=not puede_purgar):
        with st.spinner("Liberando espacio en Supabase y borrando fotos antiguas del Storage..."):
            resultado_purga = purgar_datos_antiguos_supabase(int(dias_corte))
        st.success(
            f"✅ ¡Espacio liberado en Supabase! Se archivaron y limpiaron: "
            f"{resultado_purga['ots']} OT(s) completadas, "
            f"{resultado_purga['compras']} solicitud(es) de compra (con sus fotos), "
            f"{resultado_purga['fallas']} falla(s) cerradas y "
            f"{resultado_purga['checklists']} checklist(s)."
        )

    st.markdown("---")
    with st.expander("📊 ¿Cómo conecto Power BI a mi Disco E:?"):
        st.markdown("""
        1. Abrí **Power BI Desktop** en tu computadora (con el disco `E:` enchufado).
        2. Hacé clic en **Obtener datos** ➔ **Excel**.
        3. Entrá a la carpeta **`E:\\CMMS_Datos\\PowerBI_Excel\\`** y elegí las tablas que quieras cruzar:
           - `OTs_Historico_Completo.xlsx` (tiene todas las OTs históricas, costos, horas de paro y códigos de OpenOrange).
           - `Consumo_Repuestos_OT.xlsx` (qué repuesto se usó en cada OT y cuánto costó).
           - `Stock_Repuestos.xlsx` (tu inventario actual y punto de pedido).
           - `Solicitudes_Compra.xlsx` (todas las compras locales e importaciones vinculadas a OpenOrange).
           - `Planes_Preventivos.xlsx` y `Presupuesto_Mensual.xlsx`.
        4. Cada vez que actualices el disco desde este botón, en Power BI solo tenés que tocar **"Actualizar"** (*Refresh*) arriba y todos tus gráficos se ponen al día solos.
        """)
