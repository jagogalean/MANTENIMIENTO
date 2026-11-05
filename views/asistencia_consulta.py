"""
Asistencia (consulta): vista de SOLO LECTURA para quien necesita ver la asistencia y las horas del personal
pero no sus salarios.

- No muestra salarios, valor hora ni ningún monto en guaraníes.
- No tiene ningún botón ni tabla editable: no guarda, no modifica y no borra nada.
- Los salarios se descartan apenas se leen los empleados, así que ni siquiera pasan por la pantalla.
"""
import io
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from database import asistencia_db as db
from database import asistencia_logica as A

ROLES_CONSULTA = ("admin", "consulta_asistencia")
CAMPOS_SALARIO = ("salario_base", "adicional_fijo")
DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
TIPO_DIA_TXT = {"HABIL": "hábil", "DOMINGO": "domingo", "FERIADO": "feriado"}
LIMITE = 1000


def sin_salarios(empleados):
    """Quita los salarios de los empleados (queda 0 para que los cálculos de horas funcionen igual)."""
    return [{**{k: v for k, v in e.items() if k not in CAMPOS_SALARIO}, "salario_base": 0.0, "adicional_fijo": 0.0} for e in empleados]


def _hoy():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Asuncion")).date()
    except Exception:
        return (datetime.utcnow() - timedelta(hours=3)).date()


def _fmt_h(v):
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def filas_registro(registros, empleados_por_id, mods, params, feriados, area, empleado, solo_avisos):
    """Una fila por día registrado, con horas (nunca montos)."""
    filas = []
    for r in registros:
        e = empleados_por_id.get(r["empleado_id"])
        if not e or (area != "Todas" and (e.get("area") or "Sin área") != area) or (empleado != "Todos" and e["nombre"] != empleado):
            continue
        c = A.calcular_registro(r, mods, params, feriados)
        if solo_avisos and not c["avisos"]:
            continue
        d = A.a_fecha(r["fecha"])
        dia = TIPO_DIA_TXT[c["tipo_dia"]].capitalize() + (" → " + TIPO_DIA_TXT[c["segmentos"][-1]["tipo_dia"]]
                                                          if c["cruza"] and c["segmentos"][-1]["tipo_dia"] != c["tipo_dia"] else "")
        filas.append({"Fecha": f"{d:%d/%m/%Y} {DIAS[d.weekday()]}", "Empleado": e["nombre"], "Área": e.get("area") or "", "Modalidad": r.get("modalidad") or "",
                      "Ingreso": A.hora_texto(r.get("ingreso")), "Salida": A.hora_texto(r.get("salida")), "Descanso (h)": float(r.get("descanso") or 0),
                      "Día": dia, "Horas netas": c["netas"], "Ordinarias": c["ordinarias"], "HE diurnas": c["horas"]["he_diurna"],
                      "HE nocturnas": c["horas"]["he_nocturna"], "Domingo (h)": round(c["horas"]["domingo_diurno"] + c["horas"]["domingo_nocturno"], 2),
                      "Feriado (h)": round(c["horas"]["feriado_diurno"] + c["horas"]["feriado_nocturno"], 2),
                      "Observaciones": r.get("observaciones") or "", "Avisos": " ".join(c["avisos"])})
    return filas


def filas_resumen(liq):
    """Resumen por empleado con días y horas. Se toman SOLO las columnas de horas y de días de la liquidación."""
    filas = []
    for f in liq["filas"]:
        ordinarias = round(sum(d["calculo"]["ordinarias"] for d in liq["detalle"].get(f["empleado_id"], [])), 2)
        extras = round(f["he_diurna_horas"] + f["he_nocturna_horas"], 2)
        recargo = round(f["domingo_diurno_horas"] + f["domingo_nocturno_horas"] + f["feriado_diurno_horas"] + f["feriado_nocturno_horas"], 2)
        filas.append({"Empleado": f["empleado"], "Área": f["area"], "Días trabajados": f["dias_trabajados"], "Ausencias": f["ausencias"], "Libres": f["libres"],
                      "Vacaciones/Reposo": f["vacaciones"], "Días sin registro": f["dias_sin_registro"], "Horas ordinarias": ordinarias,
                      "HE diurnas (h)": f["he_diurna_horas"], "HE nocturnas (h)": f["he_nocturna_horas"],
                      "Domingo (h)": round(f["domingo_diurno_horas"] + f["domingo_nocturno_horas"], 2),
                      "Feriado (h)": round(f["feriado_diurno_horas"] + f["feriado_nocturno_horas"], 2), "Total horas extra y recargos": round(extras + recargo, 2)})
    return filas


def _excel(registro, resumen):
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as w:
        pd.DataFrame(resumen).to_excel(w, index=False, sheet_name="Resumen")
        pd.DataFrame(registro).to_excel(w, index=False, sheet_name="Registro diario")
    return buffer.getvalue()


def render_asistencia_consulta(usuario):
    st.title("🕒 Asistencia (consulta)")
    if (usuario or {}).get("rol") not in ROLES_CONSULTA:
        st.warning("No tenés acceso a esta pantalla.")
        return
    st.caption("Vista de solo lectura: asistencia y horas del personal. No muestra salarios ni montos y no permite cambiar nada.")
    try:
        empleados = sin_salarios(db.listar_empleados())
        modalidades, feriados_lista, params = db.listar_modalidades(), db.listar_feriados(), db.leer_parametros()
    except Exception as e:
        st.warning("No se pudieron leer las tablas de asistencia. Avisale al administrador y mostrale el detalle de abajo.")
        st.code(f"{type(e).__name__}: {e}", language=None)
        if isinstance(e, AttributeError) and "has no attribute" in str(e):
            st.error("Esto significa que un archivo de tu repositorio está incompleto o es de otra versión (el nombre aparece en el detalle de arriba). "
                     "Volvé a subirlo, arrastrándolo desde el paquete que te pasé: LISTA_DE_ARCHIVOS.txt dice cuántas líneas tiene que mostrar GitHub.")
        return
    feriados = {A.a_fecha(f["fecha"]) for f in feriados_lista if A.a_fecha(f["fecha"])}
    mods = A.modalidad_por_nombre(modalidades)
    por_id = {e["id"]: e for e in empleados}

    hoy = _hoy()
    c1, c2, c3, c4 = st.columns(4)
    desde = c1.date_input("Desde", value=hoy.replace(day=1), format="DD/MM/YYYY", key="ac_desde")
    hasta = c2.date_input("Hasta", value=hoy, format="DD/MM/YYYY", key="ac_hasta")
    areas = sorted({e.get("area") or "Sin área" for e in empleados}, key=str.casefold)
    area = c3.selectbox("Área", ["Todas"] + areas, key="ac_area")
    empleado = c4.selectbox("Empleado", ["Todos"] + sorted([e["nombre"] for e in empleados], key=str.casefold), key="ac_emp")
    if hasta < desde:
        st.error("La fecha «Hasta» no puede ser anterior a «Desde».")
        return
    try:
        registros = db.listar_registros(desde, hasta)
    except Exception as e:
        st.error(f"No se pudieron leer los registros: {e}")
        return

    tab_resumen, tab_registro = st.tabs(["📊 Resumen por empleado", "📋 Registro diario"])
    visibles = [e for e in empleados if (area == "Todas" or (e.get("area") or "Sin área") == area) and (empleado == "Todos" or e["nombre"] == empleado)]
    liq = A.liquidar(visibles, registros, modalidades, params, feriados, desde, hasta)
    resumen = filas_resumen(liq)
    registro = filas_registro(registros, por_id, mods, params, feriados, area, empleado, False)

    with tab_resumen:
        if not resumen:
            st.info("No hay empleados con esos filtros.")
        else:
            df = pd.DataFrame(resumen)
            total = {"Empleado": "TOTAL DEL PERÍODO", "Área": ""}
            for col in df.columns[2:]:
                total[col] = round(df[col].sum(), 2)
            st.dataframe(pd.concat([df, pd.DataFrame([total])], ignore_index=True), hide_index=True, width="stretch")
            avisos = [a for a in liq["avisos"] if "salario" not in a["texto"].lower()]
            if avisos:
                with st.expander(f"⚠️ {len(avisos)} aviso(s) del período"):
                    for a in avisos[:60]:
                        st.markdown(f"{'🟠' if a['nivel'] == 'media' else 'ℹ️'} {a['texto']}")
    with tab_registro:
        solo_avisos = st.checkbox("Mostrar solo los días con avisos (por ejemplo, más horas extra que el tope)", key="ac_avisos")
        filas = filas_registro(registros, por_id, mods, params, feriados, area, empleado, solo_avisos)
        if not filas:
            st.info("No hay registros con esos filtros en el período.")
        else:
            if len(filas) > LIMITE:
                st.warning(f"Hay {len(filas)} registros: se muestran los primeros {LIMITE}. Acotá el período o filtrá por empleado.")
            st.caption(f"{min(len(filas), LIMITE)} registro(s).")
            st.dataframe(pd.DataFrame(filas[:LIMITE]), hide_index=True, width="stretch", height=min(70 + 36 * min(len(filas), LIMITE), 560))
    if resumen or registro:
        st.download_button("⬇️ Descargar a Excel (resumen y registro diario, solo horas)", data=_excel(registro, resumen), key="ac_excel",
                           file_name=f"asistencia_{desde:%Y%m%d}_{hasta:%Y%m%d}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
