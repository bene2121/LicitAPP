"""Utilidades de seguridad del servidor central (limitador y escape de LIKE)."""
import time
from collections import defaultdict, deque


class Limitador:
    """Ventana deslizante en memoria, por clave (normalmente la IP)."""

    def __init__(self, maximo: int, ventana: float):
        self.maximo, self.ventana = maximo, ventana
        self._hits = defaultdict(deque)

    def _limpiar(self, clave: str):
        ahora = time.monotonic()
        cola = self._hits[clave]
        while cola and ahora - cola[0] > self.ventana:
            cola.popleft()
        return cola

    def excedido(self, clave: str) -> bool:
        """True si la clave ya agoto su cupo (no registra nada)."""
        return len(self._limpiar(clave)) >= self.maximo

    def registrar(self, clave: str) -> None:
        self._limpiar(clave).append(time.monotonic())
        if len(self._hits) > 10_000:  # evita crecer sin limite
            self._hits.clear()

    def permitir(self, clave: str) -> bool:
        """Registra el intento y dice si todavia esta dentro del cupo."""
        if self.excedido(clave):
            return False
        self.registrar(clave)
        return True


def ip_cliente(request) -> str:
    """IP real: detras de nginx (127.0.0.1) se usa X-Real-IP; si no, la del socket."""
    ip = request.client.host if request.client else "?"
    if ip in ("127.0.0.1", "::1"):
        return request.headers.get("x-real-ip", ip)[:64]
    return ip


def like_escape(texto: str) -> str:
    """Escapa % _ \\ para usarlos como texto literal en ILIKE ... ESCAPE '\\'."""
    return str(texto).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
