"""Purga de HTML fallidos caducados.

Este módulo implementa la eliminación de ficheros HTML de fichas fallidas
con más de `dias_purga` días de antigüedad. La antigüedad se calcula a partir
de la fecha `yyyy-mm-dd` embebida en el nombre del fichero, no a partir del
mtime del sistema de archivos (DEC-005).
"""

import logging
import re
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# Patrón para extraer la fecha del nombre del fichero:
# <codigo>_<yyyy-mm-dd>.html
_FECHA_EN_NOMBRE = re.compile(r"_(\d{4}-\d{2}-\d{2})\.html$")


def purgar_html_caducados(
    directorio: Path,
    dias_purga: int = 7,
) -> list[Path]:
    """Elimina los ficheros HTML con más de `dias_purga` días de antigüedad.

    La antigüedad se calcula a partir de la fecha embebida en el nombre del
    fichero (`<codigo>_<yyyy-mm-dd>.html`), no del mtime. Los ficheros sin
    fecha reconocible o con fecha inválida se ignoran. Los ficheros con
    antigüedad igual o menor a `dias_purga` se conservan.

    Args:
        directorio: Ruta al directorio `data/failed_htmls/`.
        dias_purga: Umbral en días. Ficheros con antigüedad estrictamente
            mayor que este valor se eliminan. Por defecto 7.

    Returns:
        Lista de rutas de los ficheros eliminados. Si el directorio no existe
        o está vacío, devuelve una lista vacía sin lanzar excepción.
    """
    logger.debug(f"INICIO purgar_html_caducados en {directorio} con umbral {dias_purga} días")
    if not directorio.exists() or not directorio.is_dir():
        logger.debug(f"Directorio no existe o no es directorio: {directorio}")
        return []

    hoy = date.today()
    umbral = hoy - timedelta(days=dias_purga)
    eliminados: list[Path] = []

    for ruta in directorio.iterdir():
        if not ruta.is_file():
            continue
        if ruta.suffix.lower() != ".html":
            continue

        match = _FECHA_EN_NOMBRE.search(ruta.name)
        if not match:
            continue

        try:
            fecha_fichero = date.fromisoformat(match.group(1))
        except ValueError:
            # Fecha inválida (ej. "2026-13-40"): ignorar sin eliminar
            continue

        if fecha_fichero < umbral:
            logger.debug(f"Eliminando fichero caducado: {ruta.name} (fecha: {fecha_fichero})")
            ruta.unlink()
            eliminados.append(ruta)

    logger.info(f"Purga completada: {len(eliminados)} ficheros eliminados de {directorio}")
    return eliminados
