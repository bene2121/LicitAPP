"""Lógica del asistente "Ofertar paso a paso".

Para cualquier proponente, sin datos previos: busca el proceso en SECOP II,
trae las ofertas reales si ya son públicas, arma una carpeta de expediente
propia con la carta de presentación (y el documento de consorcio si aplica)
y guarda los documentos que el usuario sube. No inventa datos ni radica.
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import date
from pathlib import Path

from m1_ingestor.campos import fila_proceso_s2, soql_literal, soql_like
from m6_propuesta.expediente import RAIZ_EXPEDIENTES, fold
from seguridad import nombre_archivo_seguro, ruta_dentro_de

API_PROCESOS = "https://www.datos.gov.co/resource/p6dx-8zbt.json"
API_OFERTAS = "https://www.datos.gov.co/resource/wi7w-2nvm.json"
MAX_SUBIDA = 50 * 1024 * 1024
EXTENSIONES = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".jpg", ".jpeg", ".png", ".zip", ".rar"}
ARCHIVO_CHECKLIST = ".licitapp_checklist.json"

# Orden estándar de una propuesta pública (pliegos tipo de Colombia Compra Eficiente).
SECCIONES = [
    ("carta", "1. Carta de Presentación de la Oferta", "Carta de presentación firmada y cédula del representante legal"),
    ("consorcio", "2. Documento de Conformación del Consorcio", "Documento de consorcio o unión temporal firmado (solo proponente plural)"),
    ("existencia", "3. Certificado de Existencia y Representación Legal", "Cámara de comercio de cada integrante (máximo 30 días)"),
    ("rut", "4. RUT", "RUT de cada integrante"),
    ("rup", "5. RUP", "Registro Único de Proponentes vigente y en firme"),
    ("seguridad_social", "6. Certificación de Pagos de Seguridad Social", "Certificado de aportes firmado por revisor fiscal o representante"),
    ("experiencia", "7. Experiencia", "Formato de experiencia y certificados de contratos"),
    ("financiero", "8. Capacidad Financiera", "Estados financieros o indicadores del RUP"),
    ("economica", "9. Propuesta Económica", "Formulario de precios del pliego, firmado"),
    ("garantia", "10. Garantía de Seriedad de la Oferta", "Póliza de seriedad (normalmente 10 % del presupuesto)"),
    ("otros", "11. Otros Documentos del Pliego", "Formatos adicionales que pida el pliego"),
]


def buscar_procesos(texto: str, cliente) -> list[dict]:
    """Proceso por ID de SECOP (CO1.…), referencia de la entidad o palabras del objeto."""
    consulta = " ".join(str(texto or "").split())[:120]
    if len(consulta) < 3:
        raise ValueError("Escribe el ID de SECOP, la referencia del proceso o palabras del objeto.")
    literal = soql_literal(consulta)
    if re.match(r"^CO1\.[A-Z]+\.\d+$", consulta, re.I):
        where = f"id_del_portafolio='{literal.upper()}' OR id_del_proceso='{literal.upper()}'"
    elif re.search(r"\d", consulta) and " " not in consulta:
        where = f"referencia_del_proceso='{literal}' OR referencia_del_proceso like '{soql_like(consulta)}%'"
    else:
        where = f"upper(nombre_del_procedimiento) like '%{soql_like(consulta.upper())}%'"
    filas = cliente(API_PROCESOS, {"$where": where, "$order": "fecha_de_publicacion_del DESC", "$limit": "20"})
    hoy = date.today().isoformat()
    vistos, procesos = set(), []
    for fila in filas or []:
        proceso = fila_proceso_s2(fila, hoy)
        if not proceso or proceso["id_del_proceso"] in vistos:
            continue
        vistos.add(proceso["id_del_proceso"])
        proceso["id"] = str(fila.get("id_del_proceso") or proceso["id_del_proceso"])
        proceso["objeto"] = proceso.get("titulo", "")
        proceso["nit_entidad"] = str(fila.get("nit_entidad") or "")
        procesos.append(proceso)
    return procesos


def ofertas_del_proceso(proceso: dict, cliente) -> list[dict]:
    """Ofertas ya publicadas en SECOP para el proceso (una por oferta, sin duplicados)."""
    portafolio = str(proceso.get("id_del_proceso") or "")
    if not portafolio:
        return []
    filas = cliente(API_OFERTAS, {
        "$select": "identificador_de_la_oferta,nombre_proveedor,valor_de_la_oferta",
        "$where": f"id_del_proceso_de_compra='{soql_literal(portafolio)}'",
        "$limit": "500",
    })
    unicas = {}
    for fila in filas or []:
        try:
            valor = float(fila.get("valor_de_la_oferta") or 0)
        except (TypeError, ValueError):
            continue
        if valor > 0:
            unicas.setdefault(fila.get("identificador_de_la_oferta") or len(unicas), {
                "proveedor": str(fila.get("nombre_proveedor") or ""), "valor": valor})
    return list(unicas.values())


def carpeta_proponente(perfil: dict, base: Path | str | None = None) -> Path:
    nombre = perfil.get("proponente_nombre") or perfil.get("empresa") or "mi-empresa"
    return Path(base or RAIZ_EXPEDIENTES) / nombre_archivo_seguro(fold(nombre).lower().replace(" ", "-"), largo=60)


def crear_expediente(perfil: dict, proceso: dict, oferta: dict, base: Path | str | None = None) -> Path:
    """Carpetas numeradas + carta de presentación + documento de consorcio (si aplica)."""
    carpeta = carpeta_proponente(perfil, base)
    plural = bool(perfil.get("proponente_plural"))
    for clave, nombre, _ in SECCIONES:
        if clave == "consorcio" and not plural:
            continue
        (carpeta / nombre).mkdir(parents=True, exist_ok=True)
    _carta_docx(carpeta / SECCIONES[0][1] / "Carta de Presentacion de la Oferta.docx", perfil, proceso, oferta)
    if plural:
        _consorcio_docx(carpeta / SECCIONES[1][1] / "Documento de Conformacion.docx", perfil, proceso)
    return carpeta


def guardar_subida(carpeta: Path, seccion: str, nombre: str, datos: bytes) -> Path:
    destino_dir = carpeta / seccion
    ext = Path(nombre).suffix.lower()
    if ext not in EXTENSIONES:
        raise ValueError(f"Tipo de archivo no permitido: {ext or 'sin extensión'}.")
    if len(datos) > MAX_SUBIDA:
        raise ValueError("El archivo pasa de 50 MB.")
    destino = destino_dir / (nombre_archivo_seguro(Path(nombre).stem, largo=80) + ext)
    if not ruta_dentro_de(carpeta, destino):
        raise ValueError("Nombre de archivo no válido.")
    destino_dir.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(datos)
    return destino


def faltantes(carpeta: Path, plural: bool) -> list[str]:
    """Secciones sin ningún documento cargado (la carta generada no cuenta como firmada)."""
    pendientes = []
    for clave, nombre, ayuda in SECCIONES:
        if clave == "consorcio" and not plural or clave == "otros":
            continue
        archivos = [p for p in (carpeta / nombre).glob("*") if p.is_file()]
        if clave in {"carta", "consorcio"}:
            archivos = [p for p in archivos if p.suffix.lower() == ".pdf"]
        if not archivos:
            pendientes.append(f"{nombre}: {ayuda}")
    return pendientes


def cargar_checklist(carpeta: Path) -> dict:
    """Carga las confirmaciones del usuario para una oferta concreta."""
    ruta = carpeta / ARCHIVO_CHECKLIST
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        return datos if isinstance(datos, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def guardar_checklist(carpeta: Path, datos: dict) -> None:
    """Persiste el avance sin confundirlo con un documento de la propuesta."""
    ruta = carpeta / ARCHIVO_CHECKLIST
    temporal = ruta.with_suffix(".tmp")
    temporal.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    temporal.replace(ruta)


def sincronizar_documentos_reutilizables(carpeta: Path, perfil: dict, hoy: date | None = None) -> dict:
    """Copia al expediente únicamente soportes reutilizables y vigentes."""
    hoy = hoy or date.today()
    destinos = {clave: nombre for clave, nombre, _ in SECCIONES}
    permitidos = {"existencia", "rut", "rup", "seguridad_social", "experiencia", "financiero", "otros"}
    copiados, vencidos, no_encontrados = [], [], []
    for item in perfil.get("biblioteca_documentos") or []:
        clave = str(item.get("categoria") or "")
        if clave not in permitidos or clave not in destinos:
            continue
        ruta = Path(str(item.get("ruta") or ""))
        vence = str(item.get("vence") or "").strip()
        if vence:
            try:
                if date.fromisoformat(vence[:10]) < hoy:
                    vencidos.append(item.get("nombre") or ruta.name)
                    continue
            except ValueError:
                vencidos.append(item.get("nombre") or ruta.name)
                continue
        if not ruta.is_file():
            no_encontrados.append(item.get("nombre") or ruta.name)
            continue
        destino = carpeta / destinos[clave] / nombre_archivo_seguro(ruta.stem, largo=80)
        destino = destino.with_suffix(ruta.suffix.lower())
        if not destino.exists():
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ruta, destino)
        copiados.append(destino.name)
    return {"copiados": copiados, "vencidos": vencidos, "no_encontrados": no_encontrados}


def estado_checklist(carpeta: Path, plural: bool, confirmaciones: dict | None = None) -> dict:
    """Estado verificable: evidencia cargada + revisión expresa contra el pliego."""
    confirmaciones = confirmaciones or {}
    items = []
    for clave, nombre, ayuda in SECCIONES:
        if clave == "otros" or (clave == "consorcio" and not plural):
            continue
        archivos = [p for p in (carpeta / nombre).glob("*") if p.is_file()]
        if clave in {"carta", "consorcio"}:
            archivos = [p for p in archivos if p.suffix.lower() == ".pdf"]
        evidencia = bool(archivos)
        revisado = bool(confirmaciones.get(f"seccion_{clave}"))
        items.append({"clave": clave, "nombre": nombre, "ayuda": ayuda,
                      "evidencia": evidencia, "revisado": revisado,
                      "completo": evidencia and revisado})
    globales = [
        ("pliego", "Descargué y revisé el pliego, anexos y formatos oficiales"),
        ("adendas", "Revisé todas las adendas publicadas"),
        ("requisitos", "Verifiqué requisitos habilitantes y factores de evaluación"),
        ("cierre", "Confirmé fecha y hora exactas de cierre"),
        ("canal", "Confirmé el canal de presentación y el acceso a la plataforma"),
    ]
    controles = [{"clave": clave, "nombre": texto,
                  "completo": bool(confirmaciones.get(f"global_{clave}"))}
                 for clave, texto in globales]
    total = len(items) + len(controles)
    completos = sum(i["completo"] for i in items) + sum(i["completo"] for i in controles)
    return {"secciones": items, "controles": controles, "completos": completos, "total": total,
            "porcentaje": round(completos / total * 100) if total else 100,
            "listo": completos == total}


def _cop(valor) -> str:
    return f"$ {float(valor or 0):,.0f}".replace(",", ".")


def _carta_docx(ruta: Path, perfil: dict, proceso: dict, oferta: dict) -> None:
    import docx

    doc = docx.Document()
    ref = proceso.get("referencia") or proceso.get("id") or ""
    doc.add_paragraph(f"{perfil.get('ciudad') or ''}, {date.today().strftime('%d/%m/%Y')}")
    doc.add_paragraph("Señores")
    doc.add_paragraph(str(proceso.get("entidad") or ""))
    doc.add_paragraph(f"REFERENCIA: Proceso de Contratación {ref}.")
    doc.add_paragraph(f"Objeto: {proceso.get('objeto') or proceso.get('titulo') or ''}.")
    doc.add_heading("CARTA DE PRESENTACIÓN DE LA OFERTA", level=2)
    doc.add_paragraph(
        f"{perfil.get('representante') or '[Representante legal]'}, identificado con cédula "
        f"{perfil.get('cedula_representante') or '[cédula]'}, en calidad de representante legal de "
        f"{perfil.get('proponente_nombre') or perfil.get('empresa') or '[proponente]'}"
        f" (NIT {perfil.get('nit') or '[NIT]'}), presento oferta para el proceso de la referencia "
        "y manifiesto bajo la gravedad del juramento que conozco y acepto los documentos del proceso, "
        "que no estoy incurso en inhabilidades ni incompatibilidades y que la información es veraz."
    )
    doc.add_paragraph(f"Valor total de la oferta: {_cop(oferta.get('precio'))}, incluido IVA y demás costos.")
    doc.add_paragraph(
        "Notificaciones: " + ", ".join(x for x in (perfil.get("direccion"), perfil.get("ciudad"),
                                                   perfil.get("email"), perfil.get("telefono")) if x))
    doc.add_paragraph("\n\n______________________________")
    doc.add_paragraph(f"{perfil.get('representante') or ''}\nRepresentante legal")
    doc.add_paragraph(
        "Nota de LicitApp: si el pliego trae su propio Formato 1, úsalo en lugar de esta carta. "
        "Firma, convierte a PDF y guárdalo en esta carpeta.")
    doc.save(str(ruta))


def _consorcio_docx(ruta: Path, perfil: dict, proceso: dict) -> None:
    import docx

    doc = docx.Document()
    tipo = perfil.get("tipo_plural") or "Consorcio"
    doc.add_paragraph("Señores")
    doc.add_paragraph(str(proceso.get("entidad") or ""))
    doc.add_paragraph(f"REFERENCIA: Proceso de Contratación {proceso.get('referencia') or proceso.get('id') or ''}.")
    doc.add_heading(f"DOCUMENTO DE CONFORMACIÓN DE {tipo.upper()}", level=2)
    doc.add_paragraph(f"Los suscritos convenimos asociarnos en {tipo} para participar en el proceso de la referencia.")
    tabla = doc.add_table(rows=1, cols=3)
    tabla.style = "Table Grid"
    for celda, texto in zip(tabla.rows[0].cells, ("Integrante", "NIT", "Participación (%)")):
        celda.text = texto
    for socio in perfil.get("integrantes") or []:
        fila = tabla.add_row().cells
        fila[0].text = str(socio.get("nombre") or "")
        fila[1].text = str(socio.get("nit") or "")
        fila[2].text = f"{float(socio.get('participacion') or 0):g} %"
    doc.add_paragraph(f"El {tipo} se denomina {perfil.get('proponente_nombre') or ''}.")
    doc.add_paragraph(f"Representante: {perfil.get('representante') or ''}, cédula {perfil.get('cedula_representante') or ''}.")
    doc.add_paragraph("Duración: el término del contrato y un año más.")
    doc.add_paragraph("\n\nFirmas de los integrantes:")
    doc.save(str(ruta))
