import streamlit as st
import pandas as pd
from io import BytesIO
from datetime import datetime
from views.dashboard import calcular_kpis_industriales

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle


def generar_pdf_maquinas(maquinas, nombre_empresa="", logo_bytes=None):
    """Genera un PDF con membrete (logo + nombre de empresa) y el listado de
    máquinas ordenado por criticidad, para el informe de gerencia."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=1.5 * cm, bottomMargin=1.5 * cm)
    styles = getSampleStyleSheet()
    story = []

    if logo_bytes:
        try:
            logo_buf = BytesIO(logo_bytes)
            img = Image(logo_buf, width=3 * cm, height=3 * cm)
            img.hAlign = "LEFT"
            story.append(img)
            story.append(Spacer(1, 8))
        except Exception:
            pass

    titulo_style = ParagraphStyle("TituloEmpresa", parent=styles["Title"], fontSize=16, spaceAfter=2)
    subtitulo_style = ParagraphStyle("Subtitulo", parent=styles["Normal"], fontSize=9, textColor=colors.grey)

    if nombre_empresa:
        story.append(Paragraph(nombre_empresa, titulo_style))
    story.append(Paragraph("Listado de Máquinas y Criticidad", styles["Heading2"]))
    story.append(Paragraph(f"Generado el {datetime.now().strftime('%d/%m/%Y %H:%M')}", subtitulo_style))
    story.append(Spacer(1, 16))

    # Ordenar por criticidad: A (crítica) primero
    orden_crit = {"A": 0, "B": 1, "C": 2}
    maquinas_ordenadas = sorted(maquinas, key=lambda m: orden_crit.get(m.get("criticidad"), 3))

    crit_texto = {"A": "Crítica (A)", "B": "Importante (B)", "C": "Menor (C)"}
    data = [["Máquina", "Código", "Sección", "Criticidad"]]
    for m in maquinas_ordenadas:
        data.append([
            m.get("nombre", "—"),
            m.get("codigo", "—"),
            m.get("seccion") or "—",
            crit_texto.get(m.get("criticidad"), m.get("criticidad", "—"))
        ])

    tabla = Table(data, colWidths=[5.5 * cm, 3 * cm, 4 * cm, 3.5 * cm], repeatRows=1)
    estilo = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#12171B")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F6F8")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ])
    for i, m in enumerate(maquinas_ordenadas, start=1):
        if m.get("criticidad") == "A":
            estilo.add("TEXTCOLOR", (3, i), (3, i), colors.HexColor("#B91C1C"))
            estilo.add("FONTNAME", (3, i), (3, i), "Helvetica-Bold")
    tabla.setStyle(estilo)
    story.append(tabla)

    story.append(Spacer(1, 20))
    resumen = (
        f"Total de máquinas: {len(maquinas)}  ·  "
        f"Críticas (A): {len([m for m in maquinas if m.get('criticidad') == 'A'])}  ·  "
        f"Importantes (B): {len([m for m in maquinas if m.get('criticidad') == 'B'])}  ·  "
        f"Menores (C): {len([m for m in maquinas if m.get('criticidad') == 'C'])}"
    )
    story.append(Paragraph(resumen, styles["Normal"]))

    doc.build(story)
    buffer.seek(0)
    return buffer


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

    st.markdown("---")
    st.markdown("##### 📄 Listado de Máquinas y Criticidad (PDF con membrete)")
    st.caption("Ideal para el primer informe a gerencia — convence más que una tabla en pantalla.")

    nombre_empresa = st.text_input(
        "Nombre de la empresa (aparece en el membrete)",
        value=st.session_state.get("nombre_empresa_pdf", "")
    )
    logo_file = st.file_uploader("Logo de la empresa (opcional, PNG o JPG)", type=["png", "jpg", "jpeg"])

    if st.button("📥 Generar PDF de Máquinas"):
        st.session_state["nombre_empresa_pdf"] = nombre_empresa
        logo_bytes = logo_file.read() if logo_file else None
        pdf_buffer = generar_pdf_maquinas(maquinas, nombre_empresa, logo_bytes)
        st.download_button(
            label="⬇️ Descargar Listado_Maquinas.pdf",
            data=pdf_buffer,
            file_name=f"Listado_Maquinas_{datetime.now().strftime('%Y%m%d')}.pdf",
            mime="application/pdf"
        )
        st.success("✅ PDF generado.")
