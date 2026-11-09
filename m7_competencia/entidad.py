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
    if filtrar_contexto:
        filtro_proceso = (f"nit_entidad='{soql_literal(nit)}'" if nit else
                          f"upper(entidad) like '%{soql_literal(fold(nombre).upper())}%'")
        modalidad = fold(proceso.get("modalidad") or "").upper()
        unspsc = "".join(c for c in str(proceso.get("unspsc") or "") if c.isdigit())[:2]
        partes = [filtro_proceso, f"fecha_de_publicacion_del >= '{desde}T00:00:00'"]
        if modalidad:
            partes.append(f"upper(modalidad_de_contratacion) like '%{soql_literal(modalidad)}%'")
        if unspsc:
            partes.append(f"codigo_principal_de_categoria like 'V1.{soql_literal(unspsc)}%'")
        procesos_contexto = cliente(API_PROCESOS, {
            "$select": "id_del_portafolio,referencia_del_proceso,precio_base,nombre_del_procedimiento",
            "$where": " AND ".join(partes), "$order": "fecha_de_publicacion_del DESC", "$limit": "500",
        }) or []
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
        "nota": "Conteos construidos con ofertas y contratos publicados en Datos Abiertos SECOP II.",
    }


SECCIONES_PLIEGO = {
    "Experiencia": ("experiencia general", "experiencia especifica", "experiencia específica", "contratos acreditados"),
    "Requisitos habilitantes": ("requisitos habilitantes", "capacidad juridica", "capacidad jurídica"),
    "Capacidad financiera": ("indice de liquidez", "índice de liquidez", "endeudamiento", "cobertura de intereses"),
    "Capacidad organizacional": ("rentabilidad del patrimonio", "rentabilidad del activo", "capacidad organizacional"),
    "Causales de rechazo": ("causales de rechazo", "rechazo de la oferta", "será rechazada"),
    "Personal y equipo": ("personal minimo", "personal mínimo", "equipo minimo", "equipo mínimo"),
}


def extraer_requisitos_pdf(datos: bytes, max_paginas: int = 250) -> dict:
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
        return {"paginas": len(lector.pages), "legibles": 0, "secciones": {},
                "aviso": "El PDF parece escaneado y no contiene texto seleccionable. Requiere OCR o revisión manual."}
    hallazgos = {}
    for titulo, terminos in SECCIONES_PLIEGO.items():
        encontrados = []
        for pagina, texto in textos:
            plano = fold(texto).lower()
            posiciones = [plano.find(fold(t).lower()) for t in terminos]
            posiciones = [p for p in posiciones if p >= 0]
            if posiciones:
                pos = min(posiciones)
                inicio, fin = max(0, pos - 180), min(len(texto), pos + 650)
                encontrados.append({"pagina": pagina, "texto": texto[inicio:fin]})
            if len(encontrados) >= 4:
                break
        if encontrados:
            hallazgos[titulo] = encontrados
    return {"paginas": len(lector.pages), "legibles": len(textos), "secciones": hallazgos,
            "aviso": "Fragmentos encontrados automáticamente. Confirma siempre el texto completo, tablas y adendas."}


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
