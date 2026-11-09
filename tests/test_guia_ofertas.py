from m2_formulas.comparar import diferencias_formulas
from m2_formulas.optimizador import optimizar_todas
from m7_competencia.historial_ofertas import estimar_ofertas


def test_cinco_formulas_separadas_con_diferencias():
    resultados = optimizar_todas(1_000_000, 100, [900_000, 850_000, 800_000])
    filas = diferencias_formulas(resultados)
    assert [f["formula"] for f in filas] == ["M", "MG", "MAB", "MAA", "MV"]
    assert min(f["dif_vs_mas_baja"] for f in filas) == 0
    mv = next(f for f in filas if f["formula"] == "MV")
    assert mv["dif_vs_mv"] == 0
    assert all("dif_vs_promedio" in f for f in filas)


def cliente(url, params):
    where = params.get("$where", "")
    if "wi7w-2nvm" in url and "900111" in where:
        return [
            {"id_del_proceso_de_compra": "CO1.BDOS.1", "valor_de_la_oferta": "800", "nombre_proveedor": "OBRAS SAS", "nit_del_proveedor": "900111"},
            {"id_del_proceso_de_compra": "CO1.BDOS.2", "valor_de_la_oferta": "700", "nombre_proveedor": "OBRAS SAS", "nit_del_proveedor": "900111"},
        ]
    if "p6dx-8zbt" in url:
        return [
            {"id_del_portafolio": "CO1.BDOS.1", "precio_base": "1000"},
            {"id_del_portafolio": "CO1.BDOS.2", "precio_base": "1000"},
        ]
    return []


def test_guia_sale_del_descuento_historico():
    # Ofertó 20 % y 30 % bajo el presupuesto. La mediana es 25 %.
    guia = estimar_ofertas(["900111"], 1_000_000, cliente=cliente)
    ficha = guia["competidores"][0]
    assert ficha["con_presupuesto"] == 2
    assert ficha["descuento_mediano"] == 0.25
    assert ficha["precio_guia"] == 750_000
    assert guia["precios_guia"] == [750_000]


def test_sin_presupuesto_no_inventa_guia():
    def vacio(url, params):
        if "wi7w-2nvm" in url:
            return [{"id_del_proceso_de_compra": "CO1.BDOS.9", "valor_de_la_oferta": "500", "nombre_proveedor": "X"}]
        return []
    guia = estimar_ofertas(["EMPRESA X"], 2_000_000, cliente=vacio)
    assert guia["precios_guia"] == []
    assert guia["competidores"][0]["precio_guia"] == 0


def test_datos_reales_svcmin0010_dedup_y_socio_por_consorcio():
    # SECOP II, proceso CO1.BDOS.9257883 (SVCMIN0010-25, Gobernación del Huila), consultado 2026-11-09.
    oferta = {"identificador_de_la_oferta": "CO1.RPL.5712866", "id_del_proceso_de_compra": "CO1.BDOS.9257883",
              "valor_de_la_oferta": "1288612325.00", "nombre_proveedor": "CONSORCIO VIAS DEL HUILA 2026",
              "nit_del_proveedor": "No Definido"}

    def cli(url, params):
        where = params.get("$where", "")
        if "wi7w-2nvm" in url:
            if "nit_del_proveedor" in where:
                return []
            return [oferta, dict(oferta), dict(oferta)] if "VIAS DEL HUILA" in where else []
        if "ceth-n4bn" in url:
            return [{"nombre_grupo": "CONSORCIO VIAS DEL HUILA 2026"}]
        if "p6dx-8zbt" in url:
            return [{"id_del_portafolio": "CO1.BDOS.9257883", "precio_base": "1288612325"}]
        return []

    from m7_competencia.historial_ofertas import estimar_ofertas
    r = estimar_ofertas(["901267026"], 1_288_612_325, cliente=cli)
    ficha = r["competidores"][0]
    assert ficha["via"] == "consorcios"
    assert ficha["ofertas"] == 1 and ficha["con_presupuesto"] == 1
    assert ficha["precio_guia"] == 1_288_612_325
    assert "100 %" in ficha["nota"]
