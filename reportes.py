import streamlit as st
import pandas as pd
from io import BytesIO
from datetime import datetime
from views.dashboard import calcular_kpis_industriales


def _construir_costos_por_maquina(ots, maquinas, ot_repuestos, repuestos):
    """Costo total (mano de obra + repuestos consumidos) agrupado por máquina."""
    map_maquina = {m["id"]: m["nombre"] for m in maquinas}
    map_repuesto_costo = {r["id"]: r.get("costo_unitario", 0) for r in repuestos}

    costo_repuestos_por_ot = {}
    for orr in ot_repuestos:
        ot_id = orr.get("ot_id")
        costo = orr.get("cantidad_usada", 0) * map_repuesto_costo.get(orr.get("repuesto_id"), 0)
        costo_repuestos_por_ot[ot_id] = costo_repuestos_por_ot.get(ot_id, 0) + costo

    filas = {}
    for o in ots:
        m_nombre = map_maquina.get(o.get("maquina_id"), "Desconocida")
        costo_mo = o.get("costo_mano_obra", 0) or 0
        costo_rep = costo_repuestos_por_ot.get(o.get("id"), 0)
        horas_paro = o.get("horas_paro", 0) or 0

        if m_nombre not in filas:
            filas[m_nombre] = {"Máquina": m_nombre, "OTs": 0, "Costo Mano de Obra": 0, "Costo Repuestos": 0, "Costo Total": 0, "Horas de Paro": 0}

        filas[m_nombre]["OTs"] += 1
        filas[m_nombre]["Costo Mano de Obra"] += costo_mo
        filas[m_nombre]["Costo Repuestos"] += costo_rep
        filas[m_nombre]["Costo Total"] += costo_mo + costo_rep
        filas[m_nombre]["Horas de Paro"] += horas_paro

    return sorted(filas.values(), key=lambda x: x["Costo Total"], reverse=True)


def render_reportes():
    st.title("📑 Reportes para Gerencia")
    st.write("Generá un reporte descargable en Excel con el estado actual del área de mantenimiento.")

    maquinas = st.session_state.get("maquinas", [])
    fallas = st.session_state.get("fallas", [])
    ots = st.session_state.get("ots", [])
    repuestos = st.session_state.get("repuestos", [])
    terceros = st.session_state.get("terceros", [])
    planes = st.session_state.get("planes", [])

    kpis = calcular_kpis_industriales(maquinas, fallas, ots)

    st.markdown("##### Vista previa del resumen ejecutivo")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Disponibilidad", f"{kpis['disponibilidad']}%")
    c2.metric("MTTR", f"{kpis['mttr']} hrs")
    c3.metric("MTBF", f"{kpis['mtbf']} hrs")
    c4.metric("Horas de Paro Totales", f"{kpis['horas_paro']} hrs")

    if st.button("📥 Generar Reporte Excel"):
        buffer = BytesIO()

        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            # Hoja 1: Resumen ejecutivo
            resumen = pd.DataFrame([{
                "Fecha del Reporte": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "Máquinas Registradas": len(maquinas),
                "Disponibilidad (%)": kpis["disponibilidad"],
                "MTTR (hrs)": kpis["mttr"],
                "MTBF (hrs)": kpis["mtbf"],
                "Horas de Paro Totales": kpis["horas_paro"],
                "Fallas Abiertas": len([f for f in fallas if f.get("estado") != "Cerrada"]),
                "Repuestos Críticos": len([r for r in repuestos if r.get("stock_actual", 0) <= r.get("stock_minimo", 0)])
            }])
            resumen.to_excel(writer, sheet_name="Resumen Ejecutivo", index=False)

            # Hoja 2: Backlog de OTs pendientes
            map_maquina = {m["id"]: m["nombre"] for m in maquinas}
            backlog = [{
                "Código": o.get("codigo"),
                "Máquina": map_maquina.get(o.get("maquina_id"), "Desconocida"),
                "Tipo": o.get("tipo_mantenimiento"),
                "Estado": o.get("estado"),
                "Descripción": o.get("descripcion"),
                "Horas de Paro": o.get("horas_paro")
            } for o in ots if o.get("estado") != "Completada"]
            pd.DataFrame(backlog if backlog else [{"Info": "Sin pendientes"}]).to_excel(writer, sheet_name="Backlog OTs", index=False)

            # Hoja 3: Costos por máquina
            costos = _construir_costos_por_maquina(ots, maquinas, st.session_state.get("ot_repuestos", []), repuestos)
            pd.DataFrame(costos if costos else [{"Info": "Sin datos de costos aún"}]).to_excel(writer, sheet_name="Costos por Máquina", index=False)

            # Hoja 4: Repuestos críticos
            criticos = [{
                "Repuesto": r.get("nombre"),
                "Código Interno": r.get("codigo_interno"),
                "Stock Actual": r.get("stock_actual"),
                "Stock Mínimo": r.get("stock_minimo")
            } for r in repuestos if r.get("stock_actual", 0) <= r.get("stock_minimo", 0)]
            pd.DataFrame(criticos if criticos else [{"Info": "Sin repuestos críticos"}]).to_excel(writer, sheet_name="Repuestos Críticos", index=False)

            # Hoja 5: Plan preventivo vencido o próximo
            hoy = datetime.now().date()
            plan_rows = []
            for p in planes:
                try:
                    fecha_prox = datetime.strptime(p.get("proxima_ejecucion"), "%Y-%m-%d").date()
                    dias = (fecha_prox - hoy).days
                except (TypeError, ValueError):
                    dias = None
                plan_rows.append({
                    "Máquina": map_maquina.get(p.get("maquina_id"), "Desconocida"),
                    "Tarea": p.get("tarea"),
                    "Próxima Ejecución": p.get("proxima_ejecucion"),
                    "Días Restantes": dias
                })
            pd.DataFrame(plan_rows if plan_rows else [{"Info": "Sin plan preventivo cargado"}]).to_excel(writer, sheet_name="Plan Preventivo", index=False)

            # Hoja 6: Vencimientos de terceros
            venc_rows = [{
                "Equipo": t.get("equipo") or t.get("nombre"),
                "Proveedor": t.get("proveedor") or t.get("contacto"),
                "Próximo Vencimiento": t.get("proximoVencimiento")
            } for t in terceros]
            pd.DataFrame(venc_rows if venc_rows else [{"Info": "Sin terceros cargados"}]).to_excel(writer, sheet_name="Terceros", index=False)

        buffer.seek(0)
        st.download_button(
            label="⬇️ Descargar Reporte_Mantenimiento.xlsx",
            data=buffer,
            file_name=f"Reporte_Mantenimiento_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        st.success("✅ Reporte generado. Hacé clic en el botón de descarga.")