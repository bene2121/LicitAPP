"""Lee un expediente real de propuesta y genera el mismo paquete para otro proceso.

Un expediente es la carpeta de una propuesta ya presentada (por ejemplo
CONSORCIO VIAS DEL HUILA 2026): carpetas numeradas en el orden del pliego,
formatos en Word, soportes en PDF y comprimidos. LicitApp no inventa
documentos: copia lo que hay, actualiza en los formatos Word los datos del
proceso nuevo y marca lo que el proponente debe rehacer o firmar.
"""
from __future__ import annotations

import csv
import re
import shutil
import sys
import unicodedata
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from seguridad import (  # noqa: E402
    ArchivoNoSeguro, MAX_PDF_BYTES, abrir_docx_zip, nombre_archivo_seguro,
    revisar_tamano, ruta_dentro_de, sin_control,
)


def _documentos() -> Path:
    """Carpeta Documentos real del usuario (respeta OneDrive/redirecciones en Windows)."""
    import sys

    if sys.platform == "win32":
        try:
            import ctypes

            buf = ctypes.create_unicode_buffer(260)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:  # CSIDL_PERSONAL
                return Path(buf.value)
        except Exception:
            pass
    return Path.home() / "Documents"


def _raiz_expedientes() -> Path:
    """Carpeta de expedientes. Congelado (.exe) va a Documentos\\LicitApp\\expedientes, que el usuario puede escribir."""
    import os
    import sys

    if os.environ.get("LICITAPP_EXPEDIENTES"):
        return Path(os.environ["LICITAPP_EXPEDIENTES"])
    if getattr(sys, "frozen", False):
        return _documentos() / "LicitApp" / "expedientes"
    return Path(__file__).resolve().parent.parent / "expedientes"


RAIZ_EXPEDIENTES = _raiz_expedientes()
CARPETA_SALIDA = "propuestas"
VIGENCIA_DIAS = 30
_NUMERADA = re.compile(r"^\s*(\d{1,3})\s*[.\-_)]\s*(.+?)\s*$")
_COMPRIMIDOS = {".rar", ".zip", ".7z"}
_REFERENCIA = ("PLIEGO", "CRONOGRAMA", "ADENDA", "ANEXO TECNICO", "NO APLICA", "ESTUDIOS PREVIOS")
_CON_VIGENCIA = ("EXISTENCIA", "REDAM", "ANTECEDENTE", "SEGURIDAD SOCIAL", "PARAFISCAL")
_MESES = {
    "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6, "JULIO": 7,
    "AGOSTO": 8, "SEPTIEMBRE": 9, "SETIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12,
}


# ── Lectura ──────────────────────────────────────────────────────────────────

def listar_expedientes(raiz: Path | str | None = None) -> list[dict]:
    """Expedientes cargados en la carpeta `expedientes/` del proyecto."""
    base = Path(raiz or RAIZ_EXPEDIENTES)
    if not base.is_dir():
        return []
    salida = []
    for carpeta in sorted(p for p in base.iterdir() if p.is_dir()):
        contenido = raiz_documental(carpeta)
        secciones = _carpetas_numeradas(contenido)
        salida.append({
            "nombre": carpeta.name,
            "ruta": str(carpeta),
            "secciones": len(secciones),
            "cargado": bool(secciones),
        })
    return salida


def raiz_documental(carpeta: Path | str) -> Path:
    """Baja por carpetas envoltorio (p. ej. `X/X/`) hasta las carpetas numeradas."""
    actual = Path(carpeta)
    for _ in range(4):
        if _carpetas_numeradas(actual):
            return actual
        hijos = [p for p in actual.iterdir() if p.is_dir() and p.name != CARPETA_SALIDA]
        if len(hijos) != 1:
            return actual
        actual = hijos[0]
    return actual


def leer_expediente(carpeta: Path | str) -> dict:
    """Estructura, orden y datos reales del expediente."""
    base = Path(carpeta)
    if not base.is_dir():
        raise ValueError(f"No existe la carpeta del expediente: {base}")
    raiz = raiz_documental(base)
    numeradas = _carpetas_numeradas(raiz)
    if not numeradas:
        raise ValueError(
            "La carpeta del expediente no tiene carpetas numeradas (1. Carta…, 2. …). "
            "Copia ahí el contenido de la propuesta."
        )
    secciones = []
    for numero, nombre, ruta in numeradas:
        # Se ignoran enlaces simbólicos y cualquier archivo que resuelva fuera de la carpeta
        # del expediente: un expediente descargado no puede arrastrar archivos ajenos al paquete.
        archivos = sorted(
            (p for p in ruta.rglob("*") if p.is_file() and not p.is_symlink() and ruta_dentro_de(ruta, p)),
            key=lambda p: str(p).lower(),
        )
        stems_docx = {fold(p.stem) for p in archivos if p.suffix.lower() == ".docx"}
        secciones.append({
            "numero": numero,
            "carpeta": ruta.name,
            "nombre": nombre,
            "tipo": _tipo_seccion(nombre),
            "archivos": [_ficha_archivo(p, ruta, stems_docx) for p in archivos],
        })
    referencia = [
        {"nombre": p.name, "ruta": str(p)}
        for p in sorted(raiz.iterdir())
        if p.is_file() and not p.is_symlink() and p.name.upper() != "LEEME.TXT"
    ]
    datos = _datos_de_formatos(secciones, raiz)
    return {
        "carpeta": str(base),
        "raiz": str(raiz),
        "nombre": base.name,
        "secciones": secciones,
        "referencia": referencia,
        "datos": datos,
        "avisos": _avisos(datos),
    }


def _carpetas_numeradas(carpeta: Path) -> list[tuple[int, str, Path]]:
    if not carpeta.is_dir():
        return []
    filas = []
    for hijo in carpeta.iterdir():
        if not hijo.is_dir():
            continue
        m = _NUMERADA.match(hijo.name)
        if m:
            filas.append((int(m.group(1)), m.group(2), hijo))
    return sorted(filas, key=lambda f: f[0])


def _tipo_seccion(nombre: str) -> str:
    n = fold(nombre)
    if "CARTA DE PRESENTACION" in n:
        return "carta"
    if "CONFORMACION" in n or "CONSORCIO" in n or "UNION TEMPORAL" in n:
        return "consorcio"
    if "ECONOMIC" in n:
        return "economica"
    if "GARANTIA" in n or "POLIZA" in n:
        return "garantia"
    if "EXPERIENCIA" in n and "PERSONAL" not in n:
        return "experiencia"
    return "habilitante"


def _ficha_archivo(ruta: Path, seccion: Path, stems_docx: set[str]) -> dict:
    ext = ruta.suffix.lower()
    if ext == ".docx":
        clase = "formato"
    elif ext == ".pdf" and fold(ruta.stem) in stems_docx:
        clase = "pdf_de_formato"
    elif ext in _COMPRIMIDOS:
        clase = "comprimido"
    else:
        clase = "soporte"
    fecha = fecha_en_nombre(ruta.stem)
    return {
        "nombre": ruta.name,
        "relativa": str(ruta.relative_to(seccion)),
        "ruta": str(ruta),
        "clase": clase,
        "fecha_documento": fecha.isoformat() if fecha else "",
        "con_vigencia": any(k in fold(ruta.stem) for k in _CON_VIGENCIA),
        "bytes": ruta.stat().st_size,
    }


def fecha_en_nombre(texto: str) -> date | None:
    """Fecha escrita en el nombre del archivo: 12-05-26, 09-06-2026, 07062026."""
    m = re.search(r"(\d{1,2})[-_.\s/](\d{1,2})[-_.\s/](\d{2,4})(?!\d)", texto)
    if not m:
        m = re.search(r"(?<!\d)(\d{2})(\d{2})(\d{4})(?!\d)", texto)
    if not m:
        return None
    dia, mes, anio = (int(x) for x in m.groups())
    if anio < 100:
        anio += 2000
    try:
        return date(anio, mes, dia)
    except ValueError:
        return None


# ── Datos de los formatos Word ───────────────────────────────────────────────

def _datos_de_formatos(secciones: list[dict], raiz: Path) -> dict:
    datos = {
        "proceso_id": "",
        "entidad": "",
        "direccion_entidad": [],
        "objeto": "",
        "proponente": "",
        "representante": "",
        "suplente": "",
        "integrantes": [],
        "fecha_firma": "",
        "nombres_consorcio_en_documentos": [],
        "valor_oferta": 0.0,
        "garantia_valor": 0.0,
        "garantia_proceso": "",
        "omitidos": [],
    }
    formatos = [a for s in secciones for a in s["archivos"] if a["clase"] == "formato"]
    # La carta y la conformación primero: son las que traen los datos del proceso.
    formatos.sort(key=lambda a: (0 if "CARTA" in fold(a["nombre"]) else 1 if "CONFORMACION" in fold(a["nombre"]) else 2))
    nombres = set()
    for archivo in formatos:
        try:
            parrafos, tablas = _texto_docx(archivo["ruta"])
        except ArchivoNoSeguro:
            datos["omitidos"].append(archivo["nombre"])
            continue
        except Exception:
            continue
        texto = "\n".join(parrafos)
        if not datos["proceso_id"]:
            m = re.search(r"Proceso de Contrataci[oó]n\s*(?:No\.?\s*)?([A-Z0-9][A-Z0-9\-_/.]*[A-Z0-9])", texto, re.I)
            if m:
                datos["proceso_id"] = m.group(1).strip()
        for i, p in enumerate(parrafos):
            limpio = p.strip()
            if not datos["entidad"] and fold(limpio).startswith("SENORES") and i + 1 < len(parrafos):
                datos["entidad"] = parrafos[i + 1].strip()
                datos["direccion_entidad"] = [x.strip() for x in parrafos[i + 2:i + 4] if x.strip() and not fold(x).startswith("REFERENCIA")]
            if not datos["objeto"] and fold(limpio).startswith("OBJETO:"):
                datos["objeto"] = limpio.split(":", 1)[1].strip().rstrip(".")
            if not datos["proponente"]:
                m = re.match(r"Nombre del proponente:\s*(.+)", limpio, re.I)
                if m:
                    datos["proponente"] = m.group(1).strip().rstrip(".")
        m = re.search(r"se denomina\s+(.+?)\.\s*$", texto, re.I | re.M)
        if m:
            datos["proponente"] = datos["proponente"] or m.group(1).strip()
        m = re.search(r"representante del (?:Consorcio|Uni[oó]n Temporal) es\s+([^,]+)", texto, re.I)
        if m:
            datos["representante"] = m.group(1).strip()
        m = re.search(r"representante suplente del (?:Consorcio|Uni[oó]n Temporal) es:?\s+([^,]+)", texto, re.I)
        if m:
            datos["suplente"] = m.group(1).strip()
        m = re.search(r"a los\s+(\d{1,2})\s+d[ií]as del mes de\s+([a-záéíóú]+)\s+de\s+(\d{4})", texto, re.I)
        if m and not datos["fecha_firma"]:
            mes = _MESES.get(fold(m.group(2)))
            if mes:
                datos["fecha_firma"] = date(int(m.group(3)), mes, int(m.group(1))).isoformat()
        if not datos["integrantes"]:
            datos["integrantes"] = _integrantes(tablas)
        try:
            nombres.update(nombres_de_consorcio(texto_xml_docx(archivo["ruta"])))
        except ArchivoNoSeguro:
            continue
    datos["nombres_consorcio_en_documentos"] = sorted(nombres)

    for seccion in secciones:
        for archivo in seccion["archivos"]:
            if archivo["nombre"].lower().endswith(".pdf"):
                if seccion["tipo"] == "economica" and not datos["valor_oferta"]:
                    datos["valor_oferta"] = _valor_en_pdf(archivo["ruta"], ("COSTO TOTAL", "VALOR TOTAL DE LA OFERTA", "VALOR TOTAL"))
                if seccion["tipo"] == "garantia" and not datos["garantia_valor"]:
                    texto_pdf = texto_pdf_seguro(archivo["ruta"])
                    datos["garantia_valor"] = _primer_valor(texto_pdf, ("SERIEDAD DE LA OFERTA",))
                    m = re.search(r"PROCESO DE CONTRATACI[OÓ]N\s+([A-Z0-9][A-Z0-9\-_/.]*[A-Z0-9])", texto_pdf.upper())
                    datos["garantia_proceso"] = m.group(1) if m else ""
    return datos


_PALABRAS_NO_NOMBRE = {"SE", "DENOMINA", "ES", "EL", "DEL", "LA", "DE", "CONSORCIO", "INTEGRADO", "OBJETO"}


def nombres_de_consorcio(texto: str) -> set[str]:
    """Nombres tipo `CONSORCIO VIAS DEL HUILA 2026` que aparecen en un texto."""
    hallados = set()
    for m in re.finditer(r"(CONSORCIO|UNI[OÓ]N TEMPORAL)((?:\s+[A-ZÁÉÍÓÚÑ0-9&\-]+){1,7}?)\s+(\d{4})\b", texto.upper()):
        palabras = m.group(2).split()
        while palabras and palabras[0] in _PALABRAS_NO_NOMBRE:
            palabras.pop(0)
        if palabras and not any(p in {"CONSORCIO", "DENOMINA"} for p in palabras):
            hallados.add(" ".join([m.group(1)] + palabras + [m.group(3)]))
    return hallados


def texto_xml_docx(ruta: str) -> str:
    """Todo el texto del .docx, incluidos cuadros de texto, encabezados y pies."""
    with abrir_docx_zip(ruta) as z:  # valida tamaño, zip bombs y rutas peligrosas
        partes = [n for n in z.namelist() if re.match(r"word/(document|header\d*|footer\d*)\.xml$", n)]
        xml = " ".join(z.read(n).decode("utf-8", "ignore") for n in partes)
    xml = re.sub(r"</w:p>", "\n", xml)
    return re.sub(r"<[^>]+>", "", xml)


def _integrantes(tablas: list[list[list[str]]]) -> list[dict]:
    filas = []
    for tabla in tablas:
        for fila in tabla:
            celdas = [" ".join(c.split()) for c in fila]
            pct = next((c for c in celdas if re.fullmatch(r"\d{1,3}(?:[.,]\d+)?\s*%", c)), "")
            nit = re.search(r"NIT\.?\s*([\d.\s]+-?\s*\d?)", " ".join(celdas), re.I)
            if not pct or not nit:
                continue
            nombre = re.split(r"\s*NIT", celdas[0], flags=re.I)[0].strip().rstrip(".")
            filas.append({
                "nombre": nombre,
                "nit": re.sub(r"[^\d-]", "", nit.group(1)),
                "participacion": float(pct.replace("%", "").replace(",", ".").strip()),
            })
    return filas


def _avisos(datos: dict) -> list[str]:
    avisos = []
    if datos.get("omitidos"):
        avisos.append(
            "No se leyeron por tamaño o estructura no segura: " + ", ".join(datos["omitidos"]) + "."
        )
    propio = fold(datos.get("proponente"))
    otros = [n for n in datos.get("nombres_consorcio_en_documentos", []) if fold(n) != propio]
    if propio and otros:
        avisos.append(
            "Los formatos nombran otro consorcio además de "
            f"{datos['proponente']}: {', '.join(otros)}. Corrige esas firmas antes de presentar."
        )
    total = sum(i["participacion"] for i in datos.get("integrantes", []))
    if datos.get("integrantes") and abs(total - 100) > 0.01:
        avisos.append(f"Las participaciones del consorcio suman {total:g} %, no 100 %.")
    if datos.get("garantia_proceso") and datos.get("proceso_id") and fold(datos["garantia_proceso"]) != fold(datos["proceso_id"]):
        avisos.append(
            f"La póliza de seriedad dice proceso {datos['garantia_proceso']} y los formatos {datos['proceso_id']}."
        )
    return avisos


def _texto_docx(ruta: str) -> tuple[list[str], list[list[list[str]]]]:
    import docx  # python-docx (su parser no resuelve entidades externas: sin XXE)

    with abrir_docx_zip(ruta):  # rechaza archivos enormes o zip bombs antes de parsear
        pass
    documento = docx.Document(ruta)
    parrafos = [p.text for p in documento.paragraphs if p.text.strip()]
    tablas = [[[c.text for c in fila.cells] for fila in t.rows] for t in documento.tables]
    for seccion in documento.sections:
        for parte in (seccion.header, seccion.footer):
            parrafos[:0] = [p.text for p in parte.paragraphs if p.text.strip()]
    return parrafos, tablas


def texto_pdf_seguro(ruta: str) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        revisar_tamano(ruta, MAX_PDF_BYTES)
        lector = PdfReader(ruta)
        return "\n".join((pagina.extract_text() or "") for pagina in lector.pages[:6])
    except Exception:
        return ""


def _valor_en_pdf(ruta: str, rotulos: tuple[str, ...]) -> float:
    """Valor total del formulario económico.

    Si el PDF separa rótulos y cifras en columnas, el total es la cifra mayor
    del formulario (el costo total con IVA).
    """
    texto = texto_pdf_seguro(ruta)
    valor = _primer_valor(texto, rotulos)
    if valor:
        return valor
    if any(r in fold(texto) for r in rotulos):
        return max((_monto("$" + m) for m in re.findall(r"\$\s*([\d.,]{5,})", texto)), default=0.0)
    return 0.0


def _primer_valor(texto: str, rotulos: tuple[str, ...]) -> float:
    lineas = texto.upper().splitlines()
    for rotulo in rotulos:
        for i, linea in enumerate(lineas):
            if rotulo in fold(linea):
                for candidata in [linea] + lineas[i + 1:i + 3]:
                    valor = _monto(candidata)
                    if valor:
                        return valor
    return 0.0


def _monto(texto: str) -> float:
    encontrados = re.findall(r"\$\s*([\d.,]{5,})", texto)
    if not encontrados:
        return 0.0
    crudo = encontrados[-1]
    if re.search(r",\d{2}$", crudo):  # 1.288.612.325,00
        crudo = crudo[:-3].replace(".", "").replace(",", "")
    elif re.search(r"\.\d{2}$", crudo):  # 128,861,232.50
        crudo = crudo[:-3].replace(",", "").replace(".", "")
    else:
        crudo = crudo.replace(".", "").replace(",", "")
    try:
        return float(crudo)
    except ValueError:
        return 0.0


# ── Generación del paquete ───────────────────────────────────────────────────

def generar_paquete(
    expediente: dict,
    proceso: dict,
    oferta: dict,
    consorcio: dict | None = None,
    perfil: dict | None = None,
    fecha_cierre: date | None = None,
    pct_garantia: float = 10.0,
    destino: Path | str | None = None,
) -> dict:
    """Escribe la propuesta en `<expediente>/propuestas/<proceso>_<fecha>/`.

    `proceso` es el proceso real elegido en el Explorador; `oferta` el precio que
    se guardó en la Calculadora; `consorcio` permite cambiar nombre y socios.
    """
    from m6_propuesta.armar import _canal  # mismo criterio de canal en toda la app

    if not proceso:
        raise ValueError("Selecciona un proceso real antes de generar la propuesta.")
    precio = _num((oferta or {}).get("precio"))
    if precio <= 0:
        raise ValueError("Calcula y guarda el precio en la Calculadora antes de generar la propuesta.")
    id_secop = str(proceso.get("id") or proceso.get("id_del_proceso") or "").strip()
    # En los formatos va la referencia que usa la entidad (p. ej. SVCMIN0010-25),
    # no el identificador interno de SECOP (CO1.REQ…).
    referencia = _referencia(proceso.get("referencia") or proceso.get("referencia_del_proceso"))
    nuevo_id = referencia or id_secop
    if not nuevo_id:
        raise ValueError("El proceso no tiene identificador.")

    datos = expediente["datos"]
    consorcio = consorcio or {}
    nuevo_nombre = (consorcio.get("nombre") or datos.get("proponente") or "").strip()
    mismo_proceso = fold(datos.get("proceso_id")) in {fold(nuevo_id), fold(id_secop)} and bool(datos.get("proceso_id"))
    nuevo_objeto = str(proceso.get("objeto") or proceso.get("titulo") or "").strip()
    nueva_entidad = _entidad_limpia(proceso.get("entidad") or proceso.get("nombre_entidad"))
    presupuesto = _num(proceso.get("presupuesto_oficial") or (oferta or {}).get("presupuesto_oficial"))
    canal = _canal(proceso)
    cierre = fecha_cierre or _fecha(proceso.get("fecha_cierre")) or date.today()

    reemplazos = []
    if datos.get("proceso_id") and not mismo_proceso:
        reemplazos.append((datos["proceso_id"], nuevo_id))
    if datos.get("objeto") and nuevo_objeto and _clave(datos["objeto"]) != _clave(nuevo_objeto):
        reemplazos.append((datos["objeto"], nuevo_objeto.upper()))
    if datos.get("entidad") and nueva_entidad and _clave(datos["entidad"]) != _clave(nueva_entidad):
        reemplazos.append((datos["entidad"], nueva_entidad.upper()))
    variantes = {datos.get("proponente", "")} | {
        n for n in datos.get("nombres_consorcio_en_documentos", [])
        if fold(n) == fold(datos.get("proponente"))
    }
    if consorcio.get("corregir_nombres"):
        # Firmas con el nombre de otro consorcio (p. ej. un expediente anterior).
        variantes |= set(datos.get("nombres_consorcio_en_documentos", []))
    for variante in sorted(v for v in variantes if v):
        if nuevo_nombre and variante != nuevo_nombre.upper() and variante != nuevo_nombre:
            reemplazos.append((variante, nuevo_nombre.upper()))

    marca = datetime.now().strftime("%Y%m%d_%H%M")
    base = Path(destino) if destino else Path(expediente["carpeta"]) / CARPETA_SALIDA
    salida = base / f"{_seguro(nuevo_id)}_{marca}"
    if not ruta_dentro_de(base, salida):
        raise ValueError("La carpeta de salida queda fuera de la carpeta de destino.")
    salida.mkdir(parents=True, exist_ok=False)

    indice = []
    for seccion in expediente["secciones"]:
        carpeta = salida / seccion["carpeta"]
        carpeta.mkdir(parents=True, exist_ok=True)
        hay_formato = any(a["clase"] == "formato" for a in seccion["archivos"])
        for archivo in seccion["archivos"]:
            fila = _procesar_archivo(
                seccion, archivo, carpeta, reemplazos, mismo_proceso, hay_formato, cierre
            )
            indice.append(fila)
        if seccion["tipo"] == "economica":
            indice.append(_resumen_economico(carpeta, seccion, nuevo_id, nuevo_objeto, nueva_entidad,
                                             nuevo_nombre, precio, presupuesto, oferta or {}))
        if seccion["tipo"] == "garantia" and not mismo_proceso:
            indice.append(_pendiente_garantia(carpeta, seccion, nuevo_id, nueva_entidad, nuevo_nombre,
                                              presupuesto, pct_garantia))

    integrantes = consorcio.get("integrantes") or datos.get("integrantes") or []
    _escribir_indice(salida, indice)
    presentacion = _presentacion(salida, nuevo_id, nueva_entidad or datos.get("entidad", ""),
                                 nuevo_objeto or datos.get("objeto", ""), nuevo_nombre,
                                 integrantes, precio, presupuesto, oferta or {}, canal, indice,
                                 expediente.get("avisos", []))
    archivos = sorted(str(p.relative_to(salida)) for p in salida.rglob("*") if p.is_file())
    pendientes = [f for f in indice if f["estado"] in {"pendiente", "rehacer", "revisar"}]
    return {
        "carpeta": str(salida),
        "proceso_id": nuevo_id,
        "id_secop": id_secop,
        "mismo_proceso": mismo_proceso,
        "proponente": nuevo_nombre,
        "integrantes": integrantes,
        "precio": precio,
        "canal": canal,
        "indice": indice,
        "pendientes": pendientes,
        "archivos": archivos,
        "presentacion": presentacion,
        "avisos": list(expediente.get("avisos", [])),
    }


def _procesar_archivo(seccion, archivo, carpeta, reemplazos, mismo_proceso, hay_formato, cierre) -> dict:
    origen = Path(archivo["ruta"])
    destino = carpeta / archivo["relativa"]
    if not ruta_dentro_de(carpeta, destino) or origen.is_symlink():
        raise ValueError(f"Ruta no permitida en el expediente: {archivo['relativa']}")
    destino.parent.mkdir(parents=True, exist_ok=True)
    fila = {
        "orden": seccion["numero"],
        "seccion": seccion["carpeta"],
        "archivo": archivo["relativa"],
        "estado": "listo",
        "accion": "Copiado del expediente",
        "observacion": "",
    }
    clase = archivo["clase"]
    especifico = seccion["tipo"] in {"economica", "garantia"}

    if clase == "formato":
        shutil.copy2(origen, destino)
        try:
            cambios = reemplazar_en_docx(destino, reemplazos) if reemplazos else 0
        except ArchivoNoSeguro as exc:
            fila.update(estado="revisar", accion="Formato copiado sin actualizar",
                        observacion=f"No se editó automáticamente ({exc}). Actualízalo a mano.")
            return fila
        fila["accion"] = f"Formato actualizado ({cambios} cambios)" if reemplazos else "Formato copiado"
        fila["estado"] = "revisar" if reemplazos else "listo"
        fila["observacion"] = "Revisa, firma y expórtalo a PDF." if reemplazos else "Mismo proceso del expediente."
        return fila
    if not mismo_proceso and (clase == "pdf_de_formato" or (clase == "comprimido" and hay_formato) or (especifico and clase != "formato")):
        if seccion["tipo"] == "economica" and origen.suffix.lower() in {".xlsx", ".xlsm", ".xls"}:
            shutil.copy2(origen, destino.with_name("PLANTILLA - " + destino.name))
            fila.update(estado="rehacer", accion="Copiado como plantilla",
                        observacion="Es el presupuesto del otro proceso: llénalo con el Formulario 1 del proceso nuevo.")
            fila["archivo"] = "PLANTILLA - " + archivo["relativa"]
            return fila
        fila.update(estado="rehacer", accion="No copiado",
                    observacion="Pertenece al proceso del expediente; se genera de nuevo para este proceso.")
        return fila

    shutil.copy2(origen, destino)
    if seccion["tipo"] == "experiencia" and not mismo_proceso:
        fila.update(estado="revisar", observacion="Actualiza el encabezado del proceso en el formato de experiencia.")
    if archivo["con_vigencia"] and archivo["fecha_documento"]:
        edad = (cierre - date.fromisoformat(archivo["fecha_documento"])).days
        if edad > VIGENCIA_DIAS:
            fila.update(estado="revisar",
                        observacion=f"Expedido {archivo['fecha_documento']}: {edad} días al cierre ({cierre.isoformat()}). Pide uno nuevo.")
        else:
            fila["observacion"] = f"Expedido {archivo['fecha_documento']} ({edad} días al cierre)."
    return fila


def reemplazar_en_docx(ruta: Path | str, reemplazos: list[tuple[str, str]]) -> int:
    """Reemplaza textos completos en párrafos, tablas, encabezados y pies del .docx."""
    import docx

    with abrir_docx_zip(ruta):
        pass
    documento = docx.Document(str(ruta))
    total = 0
    for parrafo in _todos_los_parrafos(documento):
        for viejo, nuevo in reemplazos:
            total += _reemplazar_parrafo(parrafo, viejo, nuevo)
    documento.save(str(ruta))
    return total + _reemplazar_en_xml(Path(ruta), reemplazos)


def _reemplazar_en_xml(ruta: Path, reemplazos: list[tuple[str, str]]) -> int:
    """Segunda pasada para cuadros de texto (firmas), que python-docx no recorre."""
    import zipfile
    from xml.sax.saxutils import escape  # nosec B406 - solo escapa texto saliente; no parsea XML

    temporal = ruta.with_suffix(".tmp.docx")
    total = 0
    with zipfile.ZipFile(ruta) as origen, zipfile.ZipFile(temporal, "w", zipfile.ZIP_DEFLATED) as destino:
        for item in origen.infolist():
            datos = origen.read(item.filename)
            if re.match(r"word/(document|header\d*|footer\d*)\.xml$", item.filename):
                xml = datos.decode("utf-8")
                for viejo, nuevo in reemplazos:
                    v, n = escape(viejo), escape(nuevo)
                    total += xml.count(v)
                    xml = xml.replace(v, n)
                datos = xml.encode("utf-8")
            destino.writestr(item, datos)
    temporal.replace(ruta)
    return total


def _todos_los_parrafos(documento):
    def de_contenedor(contenedor):
        for p in contenedor.paragraphs:
            yield p
        for tabla in contenedor.tables:
            for fila in tabla.rows:
                for celda in fila.cells:
                    yield from de_contenedor(celda)

    yield from de_contenedor(documento)
    for seccion in documento.sections:
        for parte in (seccion.header, seccion.footer, seccion.first_page_header,
                      seccion.first_page_footer, seccion.even_page_header, seccion.even_page_footer):
            if not parte.is_linked_to_previous:
                yield from de_contenedor(parte)


def _reemplazar_parrafo(parrafo, viejo: str, nuevo: str) -> int:
    texto = parrafo.text
    if not viejo or viejo not in texto:
        return 0
    cambios = texto.count(viejo)
    runs = parrafo.runs
    if not runs:
        return 0
    # Se conserva el formato del primer run que toca cada coincidencia.
    while True:
        texto = "".join(r.text for r in runs)
        inicio = texto.find(viejo)
        if inicio < 0:
            break
        fin = inicio + len(viejo)
        pos = 0
        primero = True
        for run in runs:
            largo = len(run.text)
            r_ini, r_fin = pos, pos + largo
            pos = r_fin
            if r_fin <= inicio or r_ini >= fin:
                continue
            antes = run.text[: max(0, inicio - r_ini)]
            despues = run.text[max(0, fin - r_ini):] if r_fin > fin else ""
            if primero:
                run.text = antes + nuevo + despues
                primero = False
            else:
                run.text = despues
    return cambios


def _resumen_economico(carpeta, seccion, proceso_id, objeto, entidad, proponente, precio, presupuesto, oferta) -> dict:
    from openpyxl import Workbook

    libro = Workbook()
    hoja = libro.active
    hoja.title = "Oferta economica"
    filas = [
        ("Proceso", proceso_id),
        ("Entidad", entidad),
        ("Objeto", objeto),
        ("Proponente", proponente),
        ("Presupuesto oficial (COP)", presupuesto or "Sin dato en SECOP"),
        ("Valor ofertado (COP)", precio),
        ("Fórmula usada", f"{oferta.get('formula', '')} {oferta.get('nombre_formula', '')}".strip()),
        ("% bajo el presupuesto", round((presupuesto - precio) / presupuesto * 100, 2) if presupuesto else ""),
        ("Generado por LicitApp", datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("Nota", "Este valor debe coincidir con el Formulario 1 – Propuesta económica que firmas."),
    ]
    for fila in filas:
        hoja.append(list(fila))
    hoja.column_dimensions["A"].width = 28
    hoja.column_dimensions["B"].width = 90
    for celda in ("B5", "B6"):
        hoja[celda].number_format = '"$" #,##0'
    nombre = "Resumen oferta economica - LicitApp.xlsx"
    libro.save(carpeta / nombre)
    return {"orden": seccion["numero"], "seccion": seccion["carpeta"], "archivo": nombre,
            "estado": "revisar", "accion": "Generado por LicitApp",
            "observacion": f"Valor ofertado {_cop(precio)}. Pásalo al Formulario 1 y fírmalo."}


def _pendiente_garantia(carpeta, seccion, proceso_id, entidad, proponente, presupuesto, pct) -> dict:
    valor = presupuesto * pct / 100 if presupuesto else 0
    texto = (
        "GARANTÍA DE SERIEDAD DE LA OFERTA — PENDIENTE\n\n"
        f"Tomador: {proponente}\nAsegurado / beneficiario: {entidad}\nProceso: {proceso_id}\n"
        f"Valor asegurado: {pct:g} % del presupuesto oficial = {_cop(valor) if valor else 'confirmar presupuesto oficial'}\n\n"
        "Pide la póliza a la aseguradora con estos datos y verifica en el pliego el porcentaje "
        "y la vigencia exigidos. Guarda aquí el PDF firmado.\n"
    )
    (carpeta / "PENDIENTE - solicitar poliza de seriedad.txt").write_text(texto, encoding="utf-8")
    return {"orden": seccion["numero"], "seccion": seccion["carpeta"],
            "archivo": "PENDIENTE - solicitar poliza de seriedad.txt", "estado": "pendiente",
            "accion": "Generado por LicitApp",
            "observacion": f"Póliza nueva por {_cop(valor) if valor else 'el % del pliego'}."}


def _escribir_indice(salida: Path, indice: list[dict]) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    libro = Workbook()
    hoja = libro.active
    hoja.title = "Orden de la propuesta"
    columnas = ["orden", "seccion", "archivo", "estado", "accion", "observacion"]
    hoja.append([c.capitalize() for c in columnas])
    for celda in hoja[1]:
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = PatternFill("solid", fgColor="1F4E79")
    colores = {"listo": "E2EFDA", "revisar": "FFF2CC", "rehacer": "FCE4D6", "pendiente": "F8CBAD"}
    for fila in sorted(indice, key=lambda f: (f["orden"], f["archivo"])):
        hoja.append([fila[c] for c in columnas])
        hoja.cell(hoja.max_row, 4).fill = PatternFill("solid", fgColor=colores.get(fila["estado"], "FFFFFF"))
    for letra, ancho in zip("ABCDEF", (7, 55, 60, 11, 30, 80)):
        hoja.column_dimensions[letra].width = ancho
    libro.save(salida / "00 INDICE DE LA PROPUESTA.xlsx")
    with open(salida / "00 INDICE DE LA PROPUESTA.csv", "w", newline="", encoding="utf-8-sig") as f:
        escritor = csv.DictWriter(f, fieldnames=columnas, delimiter=";")
        escritor.writeheader()
        escritor.writerows(sorted(indice, key=lambda f: (f["orden"], f["archivo"])))


def _presentacion(salida, proceso_id, entidad, objeto, proponente, integrantes, precio, presupuesto,
                  oferta, canal, indice, avisos) -> str:
    socios = "\n".join(
        f"  - {i.get('nombre', '')} (NIT {i.get('nit', '')}): {float(i.get('participacion') or 0):g} %"
        for i in integrantes
    ) or "  - Proponente singular"
    por_estado = {}
    for fila in indice:
        por_estado[fila["estado"]] = por_estado.get(fila["estado"], 0) + 1
    pendientes = [f"  - [{f['estado'].upper()}] {f['seccion']} / {f['archivo']}: {f['observacion']}"
                  for f in sorted(indice, key=lambda f: f["orden"]) if f["estado"] != "listo"]
    mejora = f" ({(presupuesto - precio) / presupuesto * 100:.2f} % bajo el presupuesto de {_cop(presupuesto)})" if presupuesto else ""
    texto = (
        f"PRESENTACIÓN DE LA PROPUESTA — {proceso_id}\n"
        f"Generada por LicitApp el {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        f"Entidad: {entidad}\nObjeto: {objeto}\n\n"
        f"Proponente: {proponente}\n{socios}\n\n"
        f"Oferta económica: {_cop(precio)}{mejora}\n"
        f"Fórmula elegida en la calculadora: {oferta.get('formula', '')} {oferta.get('nombre_formula', '')}\n\n"
        f"CANAL DE PRESENTACIÓN ({canal['tipo'].upper()})\n{canal['instruccion']}\nDestino: {canal['destino']}\n"
        "LicitApp arma el paquete; la radicación la haces tú en ese canal.\n\n"
        f"Estado del paquete: " + ", ".join(f"{k}: {v}" for k, v in sorted(por_estado.items())) + "\n"
        + ("\nPENDIENTES ANTES DE PRESENTAR\n" + "\n".join(pendientes) + "\n" if pendientes else "\nTodo el paquete está listo.\n")
        + ("\nAVISOS DEL EXPEDIENTE\n" + "\n".join(f"  - {a}" for a in avisos) + "\n" if avisos else "")
    )
    (salida / "00 PRESENTACION Y CANAL.txt").write_text(texto, encoding="utf-8")
    if canal["tipo"] == "findeter":
        correo = (
            f"To: {canal['destino']}\nSubject: Oferta proceso {sin_control(proceso_id)} - {sin_control(proponente)}\n"
            "MIME-Version: 1.0\nContent-Type: text/plain; charset=utf-8\nX-Unsent: 1\n\n"
            f"Señores FINDETER:\n\nRemitimos la oferta de {proponente} para el proceso {proceso_id}.\n"
            f"Valor ofertado: {_cop(precio)}.\n\nAdjuntamos los documentos en el orden del índice.\n\n"
            "Atentamente,\n"
        )
        (salida / f"Correo a Findeter - {_seguro(proceso_id)}.eml").write_text(correo, encoding="utf-8")
    return texto


# ── Utilidades ───────────────────────────────────────────────────────────────

def fold(texto) -> str:
    texto = unicodedata.normalize("NFKD", str(texto or ""))
    return " ".join("".join(c for c in texto if not unicodedata.combining(c)).upper().split())


def _referencia(valor) -> str:
    """`SVCMIN0010-25 (Presentación de oferta)` → `SVCMIN0010-25`."""
    return re.sub(r"\s*\(.*?\)\s*$", "", str(valor or "")).strip()


def _entidad_limpia(valor) -> str:
    return str(valor or "").strip().rstrip("*").strip()


def _clave(texto) -> str:
    """Comparación sin tildes, signos ni espacios dobles."""
    return re.sub(r"[^A-Z0-9]+", " ", fold(texto)).strip()


def _num(valor) -> float:
    try:
        return float(valor or 0)
    except (TypeError, ValueError):
        return 0.0


def _fecha(valor) -> date | None:
    try:
        return datetime.fromisoformat(str(valor)[:10]).date() if valor else None
    except ValueError:
        return None


def _seguro(texto: str) -> str:
    """Nombre de carpeta/archivo derivado de un id: sin separadores ni puntos iniciales (`..`)."""
    return nombre_archivo_seguro(texto, 60, "proceso")


def _cop(valor: float) -> str:
    return f"$ {valor:,.0f}".replace(",", ".")
