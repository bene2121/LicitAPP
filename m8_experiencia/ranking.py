"""Afinidad de una licitación nueva con el historial de la empresa."""
from __future__ import annotations

from m8_experiencia.historial import listar_participaciones


def rankear(procesos: list[dict], perfil: dict) -> list[dict]:
    historial = listar_participaciones(perfil)
    if not historial:
        return []
    sectores = {_prefijo(item.get("unspsc")) for item in historial if _prefijo(item.get("unspsc"))}
    regiones = {str(item.get("departamento") or "").upper() for item in historial if item.get("departamento")}
    montos = [float(item.get("presupuesto") or 0) for item in historial if float(item.get("presupuesto") or 0) > 0]
    referencia = sorted(montos)[len(montos) // 2] if montos else 0
    orden = []
    for proceso in procesos:
        puntos, razones = _afinidad(proceso, sectores, regiones, referencia)
        orden.append({
            "id": proceso.get("id") or proceso.get("id_del_proceso") or "",
            "entidad": proceso.get("entidad") or "",
            "objeto": proceso.get("objeto") or proceso.get("titulo") or "",
            "afinidad": puntos,
            "razones": razones,
        })
    orden.sort(key=lambda fila: fila["afinidad"], reverse=True)
    return orden


def _afinidad(proceso: dict, sectores: set[str], regiones: set[str], referencia: float) -> tuple[int, list[str]]:
    puntos = 0
    razones = []
    codigo = _prefijo(proceso.get("unspsc"))
    if codigo and codigo in sectores:
        puntos += 40
        razones.append("mismo sector")
    depto = str(proceso.get("departamento") or proceso.get("departamento_entidad") or "").upper()
    if depto and depto in regiones:
        puntos += 35
        razones.append("misma región")
    monto = float(proceso.get("presupuesto_oficial") or proceso.get("presupuesto") or 0)
    if referencia > 0 and monto > 0 and referencia * 0.5 <= monto <= referencia * 2:
        puntos += 25
        razones.append("cuantía parecida")
    return puntos, razones


def _prefijo(codigo) -> str:
    digitos = "".join(c for c in str(codigo or "") if c.isdigit())
    return digitos[:4]
