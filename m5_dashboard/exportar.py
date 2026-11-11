"""Exporta la lista filtrada del Explorador a Excel y PDF."""
from __future__ import annotations

import os
from datetime import datetime
from io import BytesIO

import pandas as pd

_FUENTE = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def filas_exportables(procesos: list[dict]) -> list[dict]:
    filas = []
    for proceso in procesos:
        filas.append({
            "ID": proceso.get("id") or proceso.get("id_del_proceso") or "",
            "Entidad": proceso.get("entidad") or "",
            "Objeto": proceso.get("objeto") or proceso.get("titulo") or "",
            "Modalidad": proceso.get("modalidad") or "",
            "Presupuesto": proceso.get("presupuesto_oficial") or 0,
            "Estado": proceso.get("estado") or "",
            "Departamento": proceso.get("departamento") or proceso.get("departamento_entidad") or "",
            "UNSPSC": proceso.get("unspsc") or "",
            "Cierre": str(proceso.get("fecha_cierre") or "")[:10],
            "Score": proceso.get("score") or "",
        })
    return filas


def a_excel(procesos: list[dict]) -> bytes:
    tabla = pd.DataFrame(filas_exportables(procesos))
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as escritor:
        tabla.to_excel(escritor, index=False, sheet_name="Procesos")
    return buffer.getvalue()


def a_pdf(procesos: list[dict]) -> bytes:
    from fpdf import FPDF

    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()
    if os.path.exists(_FUENTE):
        pdf.add_font("DejaVu", "", _FUENTE)
        pdf.set_font("DejaVu", size=14)
    else:
        pdf.set_font("Helvetica", size=14)
    pdf.cell(0, 8, "LicitApp — procesos filtrados", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font_size(9)
    pdf.cell(
        0, 6,
        f"{len(procesos)} procesos · {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        new_x="LMARGIN", new_y="NEXT",
    )
    pdf.ln(2)
    pdf.set_font_size(8)
    for fila in filas_exportables(procesos):
        linea = (
            f"{fila['ID']} | {fila['Entidad']} | {fila['Estado']} | "
            f"$ {float(fila['Presupuesto'] or 0):,.0f} | {fila['Objeto']}"
        )
        pdf.multi_cell(0, 5, linea[:400])
    return bytes(pdf.output())
