"""Cliente HTTP para la API Socrata de datos.gov.co (SECOP I y II)."""
import os
import sys
import time
import logging
from typing import Optional

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import (
    API_SECOP1,
    API_SECOP2,
    API_OFERTAS,
    APP_TOKEN,
    PAGE_SIZE,
)

logger = logging.getLogger(__name__)

RETRY_COUNT = 3
RETRY_BACKOFF = 2.0  # segundos base para backoff exponencial


class SecopRequestError(Exception):
    """La API no respondio despues de los reintentos."""


class SecopClient:
    """Cliente para las APIs Socrata de SECOP I y SECOP II en datos.gov.co."""

    def __init__(self, app_token: Optional[str] = None):
        self.app_token = app_token or APP_TOKEN
        self.session = requests.Session()
        if self.app_token:
            self.session.headers.update({"X-App-Token": self.app_token})

    # ------------------------------------------------------------------
    # Metodos publicos
    # ------------------------------------------------------------------

    def get_procesos_s2(
        self,
        filters: Optional[dict] = None,
        max_records: int = 5000,
    ) -> list:
        """Descarga procesos de SECOP II con paginacion.

        Args:
            filters: Diccionario con parametros SoQL adicionales
                     (ej. {'$where': "estado='CONVOCADO'", '$order': 'fecha_modificacion DESC'}).
            max_records: Limite maximo de registros a descargar.

        Returns:
            Lista de dicts con los registros descargados.
        """
        params = dict(filters or {})
        return self._paginate(API_SECOP2, params, max_records)

    def get_procesos_s1(
        self,
        filters: Optional[dict] = None,
        max_records: int = 5000,
    ) -> list:
        """Descarga procesos de SECOP I con paginacion."""
        params = dict(filters or {})
        return self._paginate(API_SECOP1, params, max_records)

    def get_ofertas(self, id_proceso: Optional[str] = None) -> list:
        """Descarga ofertas, opcionalmente filtradas por id_proceso."""
        params = {}
        if id_proceso:
            from m1_ingestor.campos import where_oferta
            params["$where"] = where_oferta(id_proceso)
        return self._paginate(API_OFERTAS, params, max_records=10_000)

    # ------------------------------------------------------------------
    # Metodos internos
    # ------------------------------------------------------------------

    def _get_page(self, url: str, params: dict, offset: int, limit: int) -> list:
        """Descarga una pagina con reintentos y backoff exponencial."""
        paged_params = dict(params)
        paged_params["$limit"] = limit
        paged_params["$offset"] = offset

        for attempt in range(1, RETRY_COUNT + 1):
            try:
                resp = self.session.get(url, params=paged_params, timeout=30)
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.RequestException as exc:
                if attempt == RETRY_COUNT:
                    logger.error(
                        "[secop_client] Error en %s (offset=%d) tras %d intentos: %s",
                        url,
                        offset,
                        RETRY_COUNT,
                        exc,
                    )
                    raise SecopRequestError(str(exc)) from exc
                wait = RETRY_BACKOFF * (2 ** (attempt - 1))
                logger.warning(
                    "[secop_client] Reintento %d/%d en %.1fs — %s",
                    attempt,
                    RETRY_COUNT,
                    wait,
                    exc,
                )
                time.sleep(wait)
        return []

    def _paginate(self, url: str, params: dict, max_records: int) -> list:
        """Pagina la API hasta alcanzar max_records o agotar los resultados."""
        all_records: list = []
        offset = 0

        while len(all_records) < max_records:
            limit = min(PAGE_SIZE, max_records - len(all_records))
            page = self._get_page(url, params, offset, limit)
            if not page:
                break
            all_records.extend(page)
            if len(page) < limit:
                # Ultima pagina: no hay mas registros
                break
            offset += limit

        return all_records
