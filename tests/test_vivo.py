import os
import tempfile

from m1_ingestor.vivo import comodin_vocales, consultar_vivo, where_vivo


def test_atlantico_ignora_tilde():
    assert comodin_vocales("Atlántico") == "_TL_NT_C_"


def test_where_lleva_departamento_y_sector():
    where = where_vivo(["Atlántico"], ["72"], ["Mínima cuantía"])
    assert "departamento_entidad" in where
    assert "_TL_NT_C_" in where
    assert "codigo_principal_de_categoria like '%72%'" in where
    assert "modalidad_de_contratacion" in where
    assert "estado_de_apertura_del_proceso='Abierto'" in where


class _Cliente:
    def __init__(self):
        self.llamadas = 0

    def get_procesos_s2(self, filters=None, max_records=5000):
        self.llamadas += 1
        return [{
            "id_del_portafolio": "CO1.BDOS.1",
            "entidad": "ALCALDIA",
            "nombre_del_procedimiento": "Via",
            "fase": "Presentación de oferta",
            "precio_base": "10000000",
            "departamento_entidad": "Atlantico",
            "codigo_principal_de_categoria": "V1.72101500",
        }]


def test_mismos_filtros_no_vuelven_a_la_api():
    cliente = _Cliente()
    with tempfile.TemporaryDirectory() as carpeta:
        primera = consultar_vivo(["Atlántico"], ["72"], cliente=cliente, cache_dir=carpeta)
        segunda = consultar_vivo(["Atlántico"], ["72"], cliente=cliente, cache_dir=carpeta)
        assert cliente.llamadas == 1
        assert primera[0]["id_del_proceso"] == segunda[0]["id_del_proceso"]
        assert os.listdir(carpeta)
