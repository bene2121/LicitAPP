"""Historia de una entidad y lectura asistida de requisitos del pliego."""
from __future__ import annotations

import io
import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

from m1_ingestor.campos import fold, soql_literal
from m7_competencia.investigar import API_CONTRATOS, _cliente_publico, _numero
from m7_competencia.historial_ofertas import API_OFERTAS, API_PROCESOS
from seguridad import nombre_archivo_seguro


def _nit(valor) -> str:
    return "".join(c for c in str(valor or "") if c.isdigit())


def _fecha_anos(hoy: date, anos: int) -> str:
    try:
        return hoy.replace(year=hoy.year - anos).isoformat()
    except ValueError:
        return hoy.replace(year=hoy.year - anos, day=28).isoformat()


def analizar_entidad(proceso: dict, cliente=None, hoy: date | None = None, anos: int = 3,
                     filtrar_contexto: bool = False) -> dict:
    """Oferentes y adjudicatarios publicados por la entidad durante 3 años."""
    cliente, hoy = cliente or _cliente_publico, hoy or date.today()
    nit = _nit(proceso.get("nit_entidad"))
    nombre = str(proceso.get("entidad") or "").strip()
    if not nit and len(nombre) < 3:
        raise ValueError("El proceso no trae una entidad o NIT que permita consultar su historia.")
    anos = min(max(int(anos), 1), 10)
    desde = _fecha_anos(hoy, anos)
    filtro_ofertas = (f"nit_entidad_compradora='{soql_literal(nit)}'" if nit else
                      f"upper(entidad_compradora) like '%{soql_literal(fold(nombre).upper())}%'")
    procesos_contexto, presupuestos = [], {}
    nivel_comparacion = "historial general de la entidad"
    filtros_usados = []
    if filtrar_contexto:
        filtro_proceso = (f"nit_entidad='{soql_literal(nit)}'" if nit else
                          f"upper(entidad) like '%{soql_literal(fold(nombre).upper())}%'")
        modalidad = fold(proceso.get("modalidad") or "").upper()
        modalidad_like = re.sub(r"[AEIOU]", "_", modalidad).replace("%", "")
        unspsc = "".join(c for c in str(proceso.get("unspsc") or "") if c.isdigit())[:2]
        base = [filtro_proceso, f"fecha_de_publicacion_del >= '{desde}T00:00:00'"]
        filtro_modalidad = (f"upper(modalidad_de_contratacion) like '%{soql_literal(modalidad_like)}%'"
                            if modalidad else "")
        filtro_unspsc = f"codigo_principal_de_categoria like 'V1.{soql_literal(unspsc)}%'" if unspsc else ""
        niveles = []
        if filtro_modalidad and filtro_unspsc:
            niveles.append(("misma modalidad y familia UNSPSC", [filtro_modalidad, filtro_unspsc]))
        if filtro_unspsc:
            niveles.append(("misma familia UNSPSC", [filtro_unspsc]))
        if filtro_modalidad:
            niveles.append(("misma modalidad", [filtro_modalidad]))
        niveles.append(("historial general de la entidad", []))
        for nivel, extras in niveles:
            procesos_contexto = cliente(API_PROCESOS, {
                "$select": ("id_del_portafolio,referencia_del_proceso,precio_base,nombre_del_procedimiento,"
                            "modalidad_de_contratacion,codigo_principal_de_categoria"),
                "$where": " AND ".join(base + extras), "$order": "fecha_de_publicacion_del DESC", "$limit": "200",
            }) or []
            if procesos_contexto:
                nivel_comparacion = nivel
                filtros_usados = extras
                break
        ids = [str(f.get("id_del_portafolio") or "") for f in procesos_contexto if f.get("id_del_portafolio")]
        presupuestos = {str(f.get("id_del_portafolio")): _numero(f.get("precio_base")) for f in procesos_contexto}
        ofertas = []
        for inicio in range(0, len(ids), 40):
            lista = ",".join(f"'{soql_literal(x)}'" for x in ids[inicio:inicio + 40])
            ofertas.extend(cliente(API_OFERTAS, {
                "$select": ("identificador_de_la_oferta,id_del_proceso_de_compra,referencia_del_proceso,"
                            "nombre_proveedor,nit_del_proveedor,valor_de_la_oferta,fecha_de_registro,modalidad"),
                "$where": f"id_del_proceso_de_compra in ({lista})", "$order": "fecha_de_registro DESC", "$limit": "3000",
            }) or [])
    else:
        ofertas = cliente(API_OFERTAS, {
            "$select": ("identificador_de_la_oferta,id_del_proceso_de_compra,referencia_del_proceso,"
                        "nombre_proveedor,nit_del_proveedor,valor_de_la_oferta,fecha_de_registro,modalidad"),
            "$where": f"{filtro_ofertas} AND fecha_de_registro >= '{desde}T00:00:00'",
            "$order": "fecha_de_registro DESC", "$limit": "3000",
        }) or []
    unicas = {}
    for fila in ofertas:
        clave = fila.get("identificador_de_la_oferta") or (
            fila.get("id_del_proceso_de_compra"), fila.get("nit_del_proveedor"), fila.get("valor_de_la_oferta"))
        unicas.setdefault(str(clave), fila)
    ofertas = list(unicas.values())

    filtro_contratos = (f"nit_entidad='{soql_literal(nit)}'" if nit else
                        f"upper(nombre_entidad) like '%{soql_literal(fold(nombre).upper())}%'")
    contratos = cliente(API_CONTRATOS, {
        "$select": ("id_contrato,proceso_de_compra,proveedor_adjudicado,documento_proveedor,es_grupo,"
                    "valor_del_contrato,fecha_de_firma,modalidad_de_contratacion,objeto_del_contrato"),
        "$where": f"{filtro_contratos} AND fecha_de_firma >= '{desde}T00:00:00'",
        "$order": "fecha_de_firma DESC", "$limit": "2000",
    }) or []
    if filtrar_contexto:
        ids_contexto = {str(f.get("id_del_portafolio") or "") for f in procesos_contexto}
        contratos = [c for c in contratos if str(c.get("proceso_de_compra") or "") in ids_contexto]

    oferentes = defaultdict(lambda: {"nombre": "", "nit": "", "ofertas": 0, "procesos": set(), "valores": [], "descuentos": []})
    for fila in ofertas:
        nit_p = _nit(fila.get("nit_del_proveedor"))
        nombre_p = str(fila.get("nombre_proveedor") or "Sin nombre").strip()
        clave = nit_p or fold(nombre_p).upper()
        x = oferentes[clave]
        x["nombre"], x["nit"] = nombre_p, nit_p
        x["ofertas"] += 1
        x["procesos"].add(str(fila.get("id_del_proceso_de_compra") or ""))
        valor = _numero(fila.get("valor_de_la_oferta"))
        if valor > 0:
            x["valores"].append(valor)
            presupuesto = presupuestos.get(str(fila.get("id_del_proceso_de_compra") or ""), 0)
            if presupuesto > 0 and 0 < valor <= presupuesto * 1.5:
                x["descuentos"].append((presupuesto - valor) / presupuesto * 100)

    ganadores = defaultdict(lambda: {"nombre": "", "nit": "", "contratos": 0, "valor": 0.0, "grupos": 0})
    for fila in contratos:
        nit_p = _nit(fila.get("documento_proveedor"))
        nombre_p = str(fila.get("proveedor_adjudicado") or "Sin nombre").strip()
        clave = nit_p or fold(nombre_p).upper()
        x = ganadores[clave]
        x["nombre"], x["nit"] = nombre_p, nit_p
        x["contratos"] += 1
        x["valor"] += _numero(fila.get("valor_del_contrato"))
        x["grupos"] += str(fila.get("es_grupo") or "").lower() in {"si", "true", "verdadero"}

    tabla_oferentes = []
    for clave, x in oferentes.items():
        g = ganadores.get(clave, {})
        tabla_oferentes.append({
            "nombre": x["nombre"], "nit": x["nit"], "ofertas": x["ofertas"],
            "procesos": len(x["procesos"] - {""}), "adjudicaciones": int(g.get("contratos", 0)),
            "tasa_exito": (int(g.get("contratos", 0)) / x["ofertas"] * 100) if x["ofertas"] else 0,
            "oferta_promedio": sum(x["valores"]) / len(x["valores"]) if x["valores"] else 0,
            "descuento_promedio": (sum(x["descuentos"]) / len(x["descuentos"])) if x["descuentos"] else None,
        })
    tabla_oferentes.sort(key=lambda x: (x["ofertas"], x["adjudicaciones"]), reverse=True)
    tabla_ganadores = sorted(ganadores.values(), key=lambda x: (x["contratos"], x["valor"]), reverse=True)
    procesos = {str(f.get("id_del_proceso_de_compra") or "") for f in ofertas} - {""}
    return {
        "entidad": nombre, "nit": nit, "desde": desde, "hasta": hoy.isoformat(),
        "procesos_con_ofertas": len(procesos), "ofertas": len(ofertas), "contratos": len(contratos),
        "oferentes_unicos": len(oferentes), "oferentes": tabla_oferentes[:30],
        "adjudicatarios": tabla_ganadores[:30], "contratos_recientes": contratos[:30],
        "contexto": filtrar_contexto, "procesos_contexto": len(procesos_contexto),
        "nivel_comparacion": nivel_comparacion, "filtros_usados": filtros_usados,
        "estado_datos": ("con_datos" if ofertas or contratos else
                         "sin_ofertas_publicadas" if procesos_contexto else "sin_procesos_comparables"),
        "nota": "Conteos construidos con ofertas y contratos publicados en Datos Abiertos SECOP II.",
    }


SECCIONES_PLIEGO = {
    "Objeto y alcance": ("objeto del proceso", "objeto a contratar", "alcance del objeto", "alcance del contrato"),
    "Presupuesto y forma de pago": ("presupuesto oficial", "valor estimado", "forma de pago", "disponibilidad presupuestal"),
    "Cronograma": ("cronograma del proceso", "fecha de cierre", "plazo para presentar", "presentacion de ofertas"),
    "Experiencia": ("experiencia general", "experiencia especifica", "experiencia específica", "contratos acreditados"),
    "Requisitos habilitantes": ("requisitos habilitantes", "capacidad juridica", "capacidad jurídica"),
    "Capacidad financiera": ("indice de liquidez", "índice de liquidez", "endeudamiento", "cobertura de intereses"),
    "Capacidad organizacional": ("rentabilidad del patrimonio", "rentabilidad del activo", "capacidad organizacional"),
    "Causales de rechazo": ("causales de rechazo", "rechazo de la oferta", "será rechazada"),
    "Personal y equipo": ("personal minimo", "personal mínimo", "equipo minimo", "equipo mínimo"),
    "Garantías": ("garantia de seriedad", "garantía de seriedad", "garantia unica", "garantía única"),
    "Documentos y formatos": ("documentos de la oferta", "formatos de la oferta", "anexos de la oferta", "contenido de la oferta"),
}


def extraer_requisitos_pdf(datos: bytes, max_paginas: int = 250, documento: str = "Pliego de condiciones") -> dict:
    """Extrae fragmentos literales; no decide por sí solo si el proponente cumple."""
    if not datos or len(datos) > 50 * 1024 * 1024:
        raise ValueError("El pliego debe ser un PDF válido de máximo 50 MB.")
    from pypdf import PdfReader
    try:
        lector = PdfReader(io.BytesIO(datos), strict=False)
    except Exception as exc:
        raise ValueError("No fue posible abrir el PDF del pliego.") from exc
    textos = []
    for numero, pagina in enumerate(lector.pages[:max_paginas], start=1):
        try:
            texto = " ".join((pagina.extract_text() or "").split())
        except Exception:
            texto = ""
        if texto:
            textos.append((numero, texto))
    if not textos:
        return {"documento": documento, "paginas": len(lector.pages), "legibles": 0, "cobertura": 0,
                "estado_lectura": "escaneado_sin_ocr", "secciones": {}, "hallazgos": [],
                "aviso": "El PDF parece escaneado y no contiene texto seleccionable. Requiere OCR o revisión manual."}
    secciones, hallazgos = {}, []
    for titulo, terminos in SECCIONES_PLIEGO.items():
        encontrados = []
        for pagina, texto in textos:
            plano = fold(texto).lower()
            posiciones = [plano.find(fold(t).lower()) for t in terminos]
            posiciones = [p for p in posiciones if p >= 0]
            if posiciones:
                pos = min(posiciones)
                inicio, fin = max(0, pos - 180), min(len(texto), pos + 650)
                fragmento = texto[inicio:fin]
                doc_id = fold(documento).lower().replace(" ", "_")[:40]
                item = {"id": f"{doc_id}_{fold(titulo).lower().replace(' ', '_')}_{pagina}_{len(encontrados) + 1}",
                        "categoria": titulo, "documento": documento, "pagina": pagina,
                        "texto": fragmento, "estado": "sin_verificar"}
                encontrados.append(item)
                hallazgos.append(item)
            if len(encontrados) >= 4:
                break
        if encontrados:
            secciones[titulo] = encontrados
    cobertura = round(len(textos) / len(lector.pages) * 100) if lector.pages else 0
    estado = "texto_completo" if cobertura >= 90 else "texto_parcial"
    return {"documento": documento, "paginas": len(lector.pages), "legibles": len(textos),
            "cobertura": cobertura, "estado_lectura": estado, "secciones": secciones, "hallazgos": hallazgos,
            "aviso": "Fragmentos encontrados automáticamente. Confirma siempre el texto completo, tablas y adendas."}


def extraer_requisitos_documentos(documentos: list[tuple[str, bytes]], max_paginas: int = 250) -> dict:
    """Analiza varios PDF sin mezclar su procedencia ni afirmar cambios de una adenda."""
    if not documentos:
        raise ValueError("Carga al menos un pliego, anexo o adenda en PDF.")
    if len(documentos) > 30:
        raise ValueError("Puedes analizar máximo 30 documentos a la vez.")
    lecturas = [extraer_requisitos_pdf(datos, max_paginas=max_paginas, documento=nombre)
                for nombre, datos in documentos]
    hallazgos, secciones = [], {}
    for lectura in lecturas:
        hallazgos.extend(lectura.get("hallazgos") or [])
        for categoria, items in (lectura.get("secciones") or {}).items():
            secciones.setdefault(categoria, []).extend(items)
    paginas = sum(int(x.get("paginas") or 0) for x in lecturas)
    legibles = sum(int(x.get("legibles") or 0) for x in lecturas)
    cobertura = round(legibles / paginas * 100) if paginas else 0
    if not legibles:
        estado = "escaneado_sin_ocr"
    elif cobertura >= 90:
        estado = "texto_completo"
    else:
        estado = "texto_parcial"
    impactos = []
    for item in hallazgos:
        if "adenda" in fold(item.get("documento") or "").lower():
            impactos.append({"categoria": item.get("categoria"), "documento": item.get("documento"),
                             "pagina": item.get("pagina"), "texto": item.get("texto"),
                             "estado": "posible_impacto_sin_confirmar"})
    return {
        "documento": f"Expediente ({len(lecturas)} documentos)", "documentos": lecturas,
        "paginas": paginas, "legibles": legibles, "cobertura": cobertura,
        "estado_lectura": estado, "secciones": secciones, "hallazgos": hallazgos,
        "impactos_adendas": impactos,
        "aviso": "Hallazgos automáticos sin confirmar. Una mención en una adenda no prueba por sí sola que el requisito cambió.",
    }


def hallazgos_a_requisitos(lectura: dict, confirmados: dict | set | list) -> list[dict]:
    """Convierte únicamente hallazgos confirmados por una persona en requisitos."""
    claves = set(confirmados if not isinstance(confirmados, dict) else
                 [k for k, valor in confirmados.items() if valor])
    requisitos = []
    for item in lectura.get("hallazgos") or []:
        if item.get("id") not in claves:
            continue
        requisitos.append({
            "requisito": str(item.get("texto") or "").strip()[:500],
            "grupo": str(item.get("categoria") or "Otro"),
            "estado": "Pendiente", "critico": item.get("categoria") == "Causales de rechazo",
            "fuente": f"{item.get('documento') or lectura.get('documento') or 'Documento'}, p. {item.get('pagina')}",
            "evidencia": "", "responsable": "", "fecha_limite": "",
        })
    return requisitos


def guardar_dossier(proceso: dict, analisis: dict, raiz: Path | str) -> Path:
    """Crea un expediente local navegable sin afirmar que descargó adjuntos de SECOP."""
    ref = proceso.get("referencia") or proceso.get("id") or proceso.get("id_del_proceso") or "proceso"
    carpeta = Path(raiz) / nombre_archivo_seguro(str(ref), largo=70)
    (carpeta / "0. Documentos SECOP").mkdir(parents=True, exist_ok=True)
    (carpeta / "1. Analisis de entidad y competencia").mkdir(parents=True, exist_ok=True)
    ficha = {k: v for k, v in proceso.items() if isinstance(v, (str, int, float, bool, type(None)))}
    (carpeta / "ficha_proceso.json").write_text(json.dumps(ficha, ensure_ascii=False, indent=2), encoding="utf-8")
    (carpeta / "1. Analisis de entidad y competencia" / "historial_2_anos.json").write_text(
        json.dumps(analisis, ensure_ascii=False, indent=2), encoding="utf-8")
    url = str(proceso.get("url_proceso") or "")
    if url:
        (carpeta / "0. Documentos SECOP" / "Abrir expediente oficial SECOP II.url").write_text(
            "[InternetShortcut]\nURL=" + url + "\n", encoding="utf-8")
    (carpeta / "0. Documentos SECOP" / "IMPORTANTE - documentos.txt").write_text(
        "Abra el expediente oficial con el acceso directo y use 'Descargar documentos' en SECOP II.\n"
        "LicitAPP no marca documentos como descargados hasta que existan físicamente en esta carpeta.\n",
        encoding="utf-8")
    return carpeta
