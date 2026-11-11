from m5_dashboard.exportar import a_excel, a_pdf, filas_exportables

PROCESO = {
    "id_del_proceso": "CO1.BDOS.1",
    "entidad": "ALCALDÍA DE BARRANQUILLA",
    "titulo": "Pavimentación de la carrera 50",
    "modalidad": "Mínima cuantía",
    "presupuesto_oficial": 80_000_000,
    "estado": "Presentación de oferta",
    "departamento_entidad": "ATLANTICO",
    "unspsc": "72101500",
    "fecha_cierre": "",
    "score": 74,
}


def test_excel_contiene_el_proceso():
    contenido = a_excel([PROCESO])
    assert contenido[:2] == b"PK"
    filas = filas_exportables([PROCESO])
    assert filas[0]["ID"] == "CO1.BDOS.1"
    assert filas[0]["Entidad"].startswith("ALCALD")


def test_pdf_no_esta_vacio():
    contenido = a_pdf([PROCESO])
    assert contenido.startswith(b"%PDF")
    assert len(contenido) > 500
