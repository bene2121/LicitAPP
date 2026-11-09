"""Arma la propuesta que el proponente va a presentar.

No envía la oferta. Junta el proceso, el precio calculado, los habilitantes
del perfil y el canal real de presentación.
"""
from __future__ import annotations

from datetime import datetime

from m1_ingestor.entidades import ENTIDADES, es_entidad

HABILITANTES = (
    ("rup_estado", "RUP"),
    ("cc_estado", "Cámara de comercio"),
    ("cedula_estado", "Cédula del representante legal"),
    ("rut_estado", "RUT"),
    ("ef_estado", "Estados financieros"),
)


def armar_propuesta(proceso: dict, perfil: dict, oferta: dict) -> dict:
    """Devuelve el paquete de presentación. `lista_para_presentar` exige datos reales."""
    if not proceso:
        raise ValueError("Selecciona un proceso antes de armar la propuesta.")
    precio = _precio(oferta)
    if precio <= 0:
        raise ValueError("Calcula el precio en la calculadora antes de armar la propuesta.")

    proceso_id = str(proceso.get("id") or proceso.get("id_del_proceso") or "").strip()
    if not proceso_id:
        raise ValueError("El proceso no tiene identificador.")

    objeto = str(proceso.get("objeto") or proceso.get("titulo") or "").strip()
    entidad = str(proceso.get("entidad") or "").strip()
    presupuesto = _numero(proceso.get("presupuesto_oficial") or oferta.get("presupuesto_oficial"))
    canal = _canal(proceso)
    habilitantes = _habilitantes(perfil.get("documentos") or {})
    empresa = str(perfil.get("empresa") or "").strip()
    nit = str(perfil.get("nit") or "").strip()

    faltantes = [item["nombre"] for item in habilitantes if not item["listo"]]
    if not empresa:
        faltantes.insert(0, "Razón social")
    if not nit:
        faltantes.insert(0, "NIT del proponente")

    carta = _carta(
        proceso_id=proceso_id,
        objeto=objeto,
        entidad=entidad,
        empresa=empresa or "(sin razón social)",
        nit=nit or "(sin NIT)",
        precio=precio,
        presupuesto=presupuesto,
        formula=str(oferta.get("nombre_formula") or oferta.get("formula") or ""),
        canal=canal,
    )
    correo = None
    if canal["tipo"] == "findeter":
        correo = {
            "para": canal["destino"],
            "asunto": f"Oferta {proceso_id} — {empresa or 'proponente'}",
            "cuerpo": carta,
        }

    return {
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "proceso": {
            "id": proceso_id,
            "entidad": entidad,
            "objeto": objeto,
            "estado": str(proceso.get("estado") or ""),
            "presupuesto_oficial": presupuesto,
            "url": str(proceso.get("url_proceso") or ""),
        },
        "proponente": {
            "empresa": empresa,
            "nit": nit,
            "email": str(perfil.get("email") or ""),
        },
        "economica": {
            "precio": precio,
            "formula": str(oferta.get("formula") or ""),
            "nombre_formula": str(oferta.get("nombre_formula") or ""),
            "pct_mejora": _numero(oferta.get("pct_mejora")),
            "presupuesto_oficial": presupuesto,
        },
        "canal": canal,
        "habilitantes": habilitantes,
        "faltantes": faltantes,
        "lista_para_presentar": not faltantes,
        "carta": carta,
        "correo": correo,
    }


def _canal(proceso: dict) -> dict:
    texto = str(proceso.get("canal_oferta") or "")
    if es_entidad(proceso, "ECOPETROL") or "Ariba" in texto:
        ficha = ENTIDADES["ECOPETROL"]
        return {
            "tipo": "ariba",
            "destino": "https://proveedores.ecopetrol.com.co",
            "instruccion": ficha["canal_oferta"],
        }
    if es_entidad(proceso, "FINDETER") or "findeter.gov.co" in texto.lower():
        ficha = ENTIDADES["FINDETER"]
        return {
            "tipo": "findeter",
            "destino": "invitacionesaofertar@findeter.gov.co",
            "instruccion": ficha["canal_oferta"],
        }
    url = str(proceso.get("url_proceso") or "").strip()
    return {
        "tipo": "secop",
        "destino": url or "SECOP II",
        "instruccion": "Radique la oferta en el expediente del proceso en SECOP II.",
    }


def _habilitantes(documentos: dict) -> list[dict]:
    filas = []
    for clave, nombre in HABILITANTES:
        estado = str(documentos.get(clave) or "Pendiente")
        filas.append({
            "nombre": nombre,
            "estado": estado,
            "listo": "Vigente" in estado or estado.startswith("✅"),
        })
    return filas


def _carta(
    proceso_id: str,
    objeto: str,
    entidad: str,
    empresa: str,
    nit: str,
    precio: float,
    presupuesto: float,
    formula: str,
    canal: dict,
) -> str:
    mejora = ""
    if presupuesto > 0:
        mejora = f" ({(presupuesto - precio) / presupuesto * 100:.1f} % bajo el presupuesto oficial de {_cop(presupuesto)})"
    formula_txt = f"\nFórmula usada: {formula}." if formula else ""
    return (
        f"PROPUESTA DE OFERTA\n"
        f"Proceso: {proceso_id}\n"
        f"Entidad: {entidad or '—'}\n"
        f"Objeto: {objeto or '—'}\n\n"
        f"Proponente: {empresa}\n"
        f"NIT: {nit}\n\n"
        f"Oferta económica: {_cop(precio)}{mejora}.{formula_txt}\n\n"
        f"Cómo se presenta:\n{canal['instruccion']}\n"
        f"Destino: {canal['destino']}\n\n"
        f"Esta carta reúne los datos cargados en LicitApp. "
        f"Revísela contra el pliego antes de enviarla. LicitApp no radica la oferta.\n"
    )


def _precio(oferta: dict) -> float:
    return _numero(oferta.get("precio") if oferta else 0)


def _numero(valor) -> float:
    try:
        return float(valor or 0)
    except (TypeError, ValueError):
        return 0.0


def _cop(valor: float) -> str:
    return f"$ {valor:,.0f}".replace(",", ".")
