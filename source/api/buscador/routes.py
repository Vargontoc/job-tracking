"""Rutas HTTP para el rastreador del buscador HTML."""

import logging
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from source.api.buscador.coordinator import CoordinadorPasada
from source.api.buscador.models import ResultadoPasada

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/buscador", tags=["buscador"])


class SolicitudPasada(BaseModel):
    """Cuerpo opcional para solicitar una pasada manual."""

    historical_codes: Optional[list[str]] = None


class CoordinadorNoDisponible(Exception):
    """El coordinador no está disponible."""


def _resultado_a_dict(resultado: ResultadoPasada) -> dict:
    """Convierte un ResultadoPasada a diccionario serializable."""
    return asdict(resultado)


def ejecutar_pasada_manual(
    coordinador: CoordinadorPasada,
    historical_codes: Optional[list[str]] = None,
) -> dict:
    """Ejecuta una pasada manual del rastreador.

    Args:
        coordinador: Coordinador de pasadas del rastreador.
        historical_codes: Lista opcional de códigos históricos. Si es None,
            se usa el fichero seen_codes.json. Si se proporciona, se usa esa
            lista para filtrar y NO se modifica el fichero.

    Returns:
        Diccionario con el resultado de la pasada en formato JSON.

    Raises:
        CoordinadorNoDisponible: Si el coordinador no está configurado.
    """
    if coordinador is None:
        raise CoordinadorNoDisponible("El coordinador no está disponible")

    # Ejecutar la pasada con historical_codes
    logger.debug("Ejecutando pasada manual")
    resultado = coordinador.ejecutar_pasada(historical_codes=historical_codes)
    logger.debug("Pasada manual completada")

    # Convertir a diccionario para JSON
    return _resultado_a_dict(resultado)


@router.post("/run")
def pasada_manual(solicitud: Optional[SolicitudPasada] = None) -> dict:
    """Endpoint para ejecutar una pasada manual del rastreador.

    Args:
        solicitud: Cuerpo opcional con historical_codes. Si es None o no
            contiene historical_codes, se usa el fichero seen_codes.json.

    Returns:
        Resultado de la pasada en formato JSON con la estructura de REQ-013.

    Raises:
        HTTPException: Si el coordinador no está disponible.
    """
    logger.info("POST /buscador/run - Iniciando ejecución manual")
    
    # Obtener el coordinador del estado de la aplicación
    # Esto se configurará en main.py mediante lifespan
    from source.api.main import app_state

    coordinador = app_state.get("coordinador")
    logger.debug(f"Coordinador obtenido: {'disponible' if coordinador else 'no disponible'}")

    if coordinador is None:
        logger.error("Coordinador no disponible")
        raise HTTPException(
            status_code=503,
            detail="El coordinador del buscador no está disponible",
        )

    # Extraer historical_codes si está presente
    historical_codes = None
    if solicitud is not None and solicitud.historical_codes is not None:
        historical_codes = solicitud.historical_codes
        logger.info(f"Usando historical_codes proporcionados: {len(historical_codes)} códigos")

    # Ejecutar la pasada
    logger.info("Ejecutando pasada manual...")
    resultado_dict = ejecutar_pasada_manual(coordinador, historical_codes)
    logger.info("Pasada manual completada exitosamente")

    return resultado_dict


@router.get("/status")
def estado_buscador() -> dict:
    """Endpoint para consultar el estado del rastreador.

    Devuelve información sobre si hay una pasada en curso, el progreso
    actual si la hay, y el resumen de la última pasada finalizada.

    Returns:
        Diccionario JSON con la estructura:
        {
            "in_progress": bool,
            "progreso": {
                "hora_inicio": str,
                "codigos_procesados": int,
                "total_codigos": int
            } | None,
            "ultima_pasada": {
                "timestamp": str,
                "comunidad": str,
                "total_listado": int,
                "error_global": str,
                "errores_por_oferta": [...],
                "ofertas_nuevas": [...]
            } | None
        }

    Raises:
        HTTPException: Si el coordinador no está disponible.
    """
    from source.api.main import app_state

    coordinador = app_state.get("coordinador")

    if coordinador is None:
        raise HTTPException(
            status_code=503,
            detail="El coordinador del buscador no está disponible",
        )

    # Obtener estado del coordinador
    en_curso = coordinador.pasada_en_curso
    ultimo = coordinador.ultimo_resultado
    progreso = coordinador.progreso

    # Construir respuesta
    respuesta = {
        "in_progress": en_curso,
        "progreso": None,
        "ultima_pasada": None,
    }

    # Si hay pasada en curso, incluir progreso
    if en_curso:
        respuesta["progreso"] = {
            "hora_inicio": progreso.hora_inicio,
            "codigos_procesados": progreso.codigos_procesados,
            "total_codigos": progreso.total_codigos,
        }

    # Si hay última pasada, incluir resumen
    if ultimo is not None:
        respuesta["ultima_pasada"] = _resultado_a_dict(ultimo)

    return respuesta
