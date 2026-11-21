"""Gestión del estado persistente de códigos vistos (DEC-002).

Módulo para leer y escribir el conjunto de códigos de oferta ya procesados.
El estado se persiste en un fichero JSON (`data/seen_codes.json`) y no utiliza
bases de datos.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_STATE_PATH = Path("data/seen_codes.json")


class ErrorEstado(Exception):
    """Error al leer o escribir el fichero de estado de códigos vistos."""


def leer_codigos_vistos(ruta: Path = DEFAULT_STATE_PATH) -> set[str]:
    """Lee el conjunto de códigos ya vistos desde el fichero JSON.

    Si el fichero no existe, lo crea vacío y devuelve un conjunto vacío.
    Si el JSON es inválido, lanza ErrorEstado.

    Args:
        ruta: Ruta al fichero JSON de códigos vistos.

    Returns:
        Conjunto de códigos (strings) ya procesados.

    Raises:
        ErrorEstado: Si el fichero existe pero contiene JSON inválido.
    """
    logger.debug(f"Leyendo códigos vistos desde {ruta}")
    if not ruta.exists():
        logger.info(f"Fichero de códigos vistos no existe, creándolo vacío: {ruta}")
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text("[]", encoding="utf-8")
        return set()

    try:
        with ruta.open("r", encoding="utf-8") as f:
            datos = json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"JSON inválido en {ruta}: {e}")
        raise ErrorEstado(
            f"El fichero {ruta} contiene JSON inválido: {e}"
        ) from e

    if not isinstance(datos, list):
        logger.error(f"El fichero {ruta} no contiene una lista de códigos")
        raise ErrorEstado(
            f"El fichero {ruta} no contiene una lista de códigos."
        )

    codigos = set(datos)
    logger.info(f"Códigos vistos leídos: {len(codigos)} códigos")
    return codigos


def guardar_codigos_vistos(
    ruta: Path, codigos_nuevos: set[str]
) -> None:
    """Guarda los códigos nuevos uniendo los ya existentes, sin duplicados.

    Lee los códigos actuales del fichero, los une con los nuevos y escribe
    el resultado de vuelta al fichero.

    Args:
        ruta: Ruta al fichero JSON de códigos vistos.
        codigos_nuevos: Conjunto de códigos a añadir.

    Raises:
        ErrorEstado: Si el fichero existe pero contiene JSON inválido.
    """
    logger.debug(f"Guardando códigos vistos en {ruta}")
    existentes = leer_codigos_vistos(ruta)
    todos = existentes | codigos_nuevos
    lista_ordenada = sorted(todos)

    logger.info(f"Escribiendo {len(lista_ordenada)} códigos totales en {ruta} ({len(codigos_nuevos)} nuevos)")
    with ruta.open("w", encoding="utf-8") as f:
        json.dump(lista_ordenada, f, indent=2, ensure_ascii=False)
    logger.debug("Códigos vistos guardados correctamente")
