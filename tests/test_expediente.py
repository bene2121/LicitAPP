from datetime import date
from pathlib import Path

import docx
import pytest

from m6_propuesta.expediente import (
    fecha_en_nombre,
    generar_paquete,
    leer_expediente,
    nombres_de_consorcio,
    texto_xml_docx,
)

OBJETO = "INTERVENTORÍA AL MEJORAMIENTO DE LA VÍA A"


def _formato(ruta: Path, lineas: list[str], tabla: list[list[str]] | None = None) -> None:
    documento = docx.Document()
    for linea in lineas:
        documento.add_paragraph(linea)
    if tabla:
        t = documento.add_table(rows=0, cols=len(tabla[0]))
        for fila in tabla:
            celdas = t.add_row().cells
            for i, valor in enumerate(fila):
                celdas[i].text = valor
    ruta.parent.mkdir(parents=True, exist_ok=True)
    documento.save(ruta)


@pytest.fixture
def expediente(tmp_path):
    base = tmp_path / "consorcio-demo" / "CONSORCIO DEMO"
    encabezado = [
        "PROC-001-26",
        "Señores",
        "GOBERNACIÓN DEL HUILA",
        "Carrera 4 Calle 8.",
        "REFERENCIA: Proceso de Contratación PROC-001-26.",
        f"Objeto: {OBJETO}.",
    ]
    _formato(base / "1. Carta de Presentación" / "Formato 1 - Carta.docx",
             encabezado + ["Nombre del proponente: CONSORCIO VÍAS DEMO 2026"])
    (base / "1. Carta de Presentación" / "Formato 1 - Carta.pdf").write_bytes(b"%PDF-1.4 viejo")
    (base / "1. Carta de Presentación" / "C.C. Representante.pdf").write_bytes(b"%PDF-1.4 cc")
    _formato(base / "2. Conformacion del Consorcio" / "Formato 2 - Conformacion.docx",
             encabezado + ["El Consorcio se denomina CONSORCIO VÍAS DEMO 2026.",
                           "El representante del Consorcio es ANA PÉREZ, identificada con cédula",
                           "Representante Legal - CONSORCIO VIAS DEL NORTE 2026"],
             [["Nombre del integrante", "Compromiso (%)"],
              ["ALFA S.A.S. NIT. 900.111.222-3", "60%"],
              ["BETA S.A.S NIT. 900.333.444-5", "40%"]])
    (base / "3. Certificado de Existencia").mkdir(parents=True)
    (base / "3. Certificado de Existencia" / "Cert. Existencia ALFA - 01-05-26.pdf").write_bytes(b"%PDF")
    (base / "4. Propuesta Economica").mkdir(parents=True)
    (base / "4. Propuesta Economica" / "PROPUESTA ECONOMICA.pdf").write_bytes(b"%PDF")
    (base / "5. Garantia de Seriedad").mkdir(parents=True)
    (base / "5. Garantia de Seriedad" / "Poliza.pdf").write_bytes(b"%PDF")
    (base / "6. RUT").mkdir(parents=True)
    (base / "6. RUT" / "RUT ALFA.pdf").write_bytes(b"%PDF")
    (base / "Pliego Definitivo.pdf").write_bytes(b"%PDF")
    return leer_expediente(tmp_path / "consorcio-demo")


def test_lee_orden_y_datos_reales(expediente):
    assert [s["numero"] for s in expediente["secciones"]] == [1, 2, 3, 4, 5, 6]
    datos = expediente["datos"]
    assert datos["proceso_id"] == "PROC-001-26"
    assert datos["entidad"] == "GOBERNACIÓN DEL HUILA"
    assert datos["objeto"] == OBJETO
    assert datos["proponente"] == "CONSORCIO VÍAS DEMO 2026"
    assert datos["representante"] == "ANA PÉREZ"
    assert [i["participacion"] for i in datos["integrantes"]] == [60.0, 40.0]
    assert [r["nombre"] for r in expediente["referencia"]] == ["Pliego Definitivo.pdf"]


def test_avisa_firma_con_otro_consorcio(expediente):
    assert any("VIAS DEL NORTE 2026" in aviso for aviso in expediente["avisos"])


def test_mismo_proceso_copia_todo(expediente, tmp_path):
    proceso = {"id": "PROC-001-26", "entidad": "GOBERNACIÓN DEL HUILA", "objeto": OBJETO,
               "presupuesto_oficial": 100_000_000}
    paquete = generar_paquete(expediente, proceso, {"precio": 100_000_000}, destino=tmp_path / "out",
                              fecha_cierre=date(2026, 5, 20))
    carpeta = Path(paquete["carpeta"])
    assert paquete["mismo_proceso"] is True
    assert (carpeta / "1. Carta de Presentación" / "Formato 1 - Carta.pdf").exists()
    assert (carpeta / "5. Garantia de Seriedad" / "Poliza.pdf").exists()
    assert (carpeta / "00 INDICE DE LA PROPUESTA.xlsx").exists()
    assert (carpeta / "4. Propuesta Economica" / "Resumen oferta economica - LicitApp.xlsx").exists()
    assert paquete["canal"]["tipo"] == "secop"


def test_proceso_nuevo_actualiza_formatos_y_aparta_lo_viejo(expediente, tmp_path):
    proceso = {"id": "CO1.REQ.999", "entidad": "FINDETER", "objeto": "Interventoría puente B",
               "presupuesto_oficial": 500_000_000}
    paquete = generar_paquete(
        expediente, proceso, {"precio": 450_000_000, "formula": "MG"},
        consorcio={"nombre": "CONSORCIO NUEVO 2026", "corregir_nombres": True},
        destino=tmp_path / "out", fecha_cierre=date(2026, 7, 1),
    )
    carpeta = Path(paquete["carpeta"])
    carta = texto_xml_docx(str(carpeta / "1. Carta de Presentación" / "Formato 1 - Carta.docx"))
    assert "CO1.REQ.999" in carta and "PROC-001-26" not in carta
    assert "FINDETER" in carta and "CONSORCIO NUEVO 2026" in carta
    conformacion = texto_xml_docx(str(carpeta / "2. Conformacion del Consorcio" / "Formato 2 - Conformacion.docx"))
    assert "NORTE" not in conformacion
    assert not (carpeta / "1. Carta de Presentación" / "Formato 1 - Carta.pdf").exists()
    assert not (carpeta / "5. Garantia de Seriedad" / "Poliza.pdf").exists()
    assert (carpeta / "5. Garantia de Seriedad" / "PENDIENTE - solicitar poliza de seriedad.txt").exists()
    assert (carpeta / "6. RUT" / "RUT ALFA.pdf").exists()
    assert paquete["canal"]["tipo"] == "findeter"
    assert list(carpeta.glob("Correo a Findeter*.eml"))
    vencido = [f for f in paquete["indice"] if "Existencia" in f["archivo"]][0]
    assert vencido["estado"] == "revisar"


def test_ecopetrol_va_por_ariba(expediente, tmp_path):
    proceso = {"id": "ECP-1", "entidad": "ECOPETROL S.A.", "nit_entidad": "899999068", "objeto": "Obra"}
    paquete = generar_paquete(expediente, proceso, {"precio": 10}, destino=tmp_path / "out")
    assert paquete["canal"]["tipo"] == "ariba"
    texto = (Path(paquete["carpeta"]) / "00 PRESENTACION Y CANAL.txt").read_text(encoding="utf-8")
    assert "proveedores.ecopetrol.com.co" in texto


def test_sin_precio_no_genera(expediente):
    with pytest.raises(ValueError):
        generar_paquete(expediente, {"id": "X"}, {"precio": 0})


def test_utilidades():
    assert fecha_en_nombre("Cert. Existencia A2M - 12-05-26") == date(2026, 5, 12)
    assert fecha_en_nombre("REDAM AMM a 07062026") == date(2026, 6, 7)
    assert nombres_de_consorcio("firma: El Consorcio se denomina CONSORCIO VÍAS DEL HUILA 2026.") == {
        "CONSORCIO VÍAS DEL HUILA 2026"
    }


def test_mismo_proceso_por_referencia_secop(expediente, tmp_path):
    # SECOP trae el id interno y la referencia con la fase; la entidad con asterisco.
    proceso = {"id": "CO1.REQ.9426412", "referencia": "PROC-001-26 (Presentación de oferta)",
               "entidad": "GOBERNACION DEL HUILA*", "objeto": OBJETO, "presupuesto_oficial": 100}
    paquete = generar_paquete(expediente, proceso, {"precio": 100}, destino=tmp_path / "out")
    assert paquete["mismo_proceso"] is True
    assert paquete["proceso_id"] == "PROC-001-26"
    carta = texto_xml_docx(str(Path(paquete["carpeta"]) / "1. Carta de Presentación" / "Formato 1 - Carta.docx"))
    assert "GOBERNACIÓN DEL HUILA" in carta and "CO1.REQ" not in carta
