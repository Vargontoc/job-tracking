"""Endpoints de consulta del histórico.

Expone cuatro rutas de consulta sobre el SQLite de ``api-persistencia`` en
modo solo lectura a través del ``AdaptadorLecturaHistorica``:

- ``GET /historico/altas`` – ofertas dadas de alta por rango de ``fecha_alta``.
- ``GET /historico/cierres`` – ofertas cerradas por rango de ``fecha_cierre``.
- ``GET /historico/cierres-por-fin-difusion`` – ofertas cerradas por rango de
  ``fecha_fin_difusion``.
- ``GET /historico/resumen`` – resumen diario de altas y cierres.

Los parámetros ``desde`` y ``hasta`` son fechas ISO (``YYYY-MM-DD``).  No
exigen autenticación, como el resto de la API.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException

from source.api.historico.read_adapter import AdaptadorLecturaHistorica

router = APIRouter(prefix="/historico", tags=["historico"])


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _parsear_fecha(valor: str, campo: str) -> date:
    """Parsea una cadena ``YYYY-MM-DD`` y devuelve un ``date``.

    Lanza ``HTTPException(400)`` si el formato es inválido.
    """
    try:
        return datetime.strptime(valor, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=400,
            detail=(
                f"El parámetro '{campo}' debe tener formato YYYY-MM-DD; "
                f"recibido: {valor!r}"
            ),
        ) from None


def _obtener_adaptador() -> AdaptadorLecturaHistorica:
    """Recupera el adaptador de lectura desde ``app_state``.

    Lanza ``HTTPException(503)`` si el histórico no se inicializó.
    """
    from source.api.main import app_state

    adaptador = app_state.get("adaptador_lectura_historica")
    if adaptador is None:
        raise HTTPException(
            status_code=503,
            detail="El histórico no está disponible. Comprueba la configuración.",
        )
    return adaptador


def _validar_rango(desde_iso: str, hasta_iso: str) -> tuple[date, date]:
    """Valida y parsea un rango de fechas.

    Devuelve ``(desde, hasta)`` como ``date``.  Lanza ``HTTPException(400)``
    si las fechas son inválidas o si ``desde > hasta``.
    """
    desde = _parsear_fecha(desde_iso, "desde")
    hasta = _parsear_fecha(hasta_iso, "hasta")
    if desde > hasta:
        raise HTTPException(
            status_code=400,
            detail=(
                f"El parámetro 'desde' ({desde_iso}) no puede ser posterior "
                f"a 'hasta' ({hasta_iso})"
            ),
        )
    return desde, hasta


def _oferta_a_dict(oferta) -> dict:
    """Convierte una ``OfertaResumen`` a un diccionario serializable."""
    return asdict(oferta)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/altas")
def consultar_altas(desde: str, hasta: str) -> list[dict]:
    """Devuelve las ofertas cuya ``fecha_alta`` está en ``[desde, hasta]``."""
    _validar_rango(desde, hasta)
    adaptador = _obtener_adaptador()
    ofertas = adaptador.altas_por_fecha(desde, hasta)
    return [_oferta_a_dict(o) for o in ofertas]


@router.get("/cierres")
def consultar_cierres(desde: str, hasta: str) -> list[dict]:
    """Devuelve las ofertas cuya ``fecha_cierre`` está en ``[desde, hasta]``."""
    _validar_rango(desde, hasta)
    adaptador = _obtener_adaptador()
    ofertas = adaptador.cierres_por_fecha(desde, hasta)
    return [_oferta_a_dict(o) for o in ofertas]


@router.get("/cierres-por-fin-difusion")
def consultar_cierres_fin_difusion(
    desde: str, hasta: str
) -> list[dict]:
    """Devuelve ofertas cuya ``fecha_fin_difusion`` está en ``[desde, hasta]``."""
    _validar_rango(desde, hasta)
    adaptador = _obtener_adaptador()
    ofertas = adaptador.cierres_por_fecha_fin_difusion(desde, hasta)
    return [_oferta_a_dict(o) for o in ofertas]


@router.get("/resumen")
def consultar_resumen(desde: str, hasta: str) -> list[dict]:
    """Devuelve el resumen diario de altas y cierres para el rango dado.

    Cada elemento contiene ``fecha``, ``altas`` y ``cierres``.
    """
    desde_dt, hasta_dt = _validar_rango(desde, hasta)
    adaptador = _obtener_adaptador()

    resultados: list[dict] = []
    fecha_actual = desde_dt
    delta = timedelta(days=1)
    while fecha_actual <= hasta_dt:
        iso = fecha_actual.isoformat()
        resumen = adaptador.resumen_diario(iso)
        resultados.append(asdict(resumen))
        fecha_actual += delta
    return resultados
