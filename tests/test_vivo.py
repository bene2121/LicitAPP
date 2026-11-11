from m1_ingestor.vivo import comodin_vocales, where_vivo


def test_atlantico_ignora_tilde():
    assert comodin_vocales("Atlántico") == "_TL_NT_C_"


def test_where_lleva_departamento_y_sector():
    where = where_vivo(["Atlántico"], ["72"], ["Mínima cuantía"])
    assert "departamento_entidad" in where
    assert "_TL_NT_C_" in where
    assert "codigo_principal_de_categoria like '%72%'" in where
    assert "modalidad_de_contratacion" in where
    assert "estado_de_apertura_del_proceso='Abierto'" in where
