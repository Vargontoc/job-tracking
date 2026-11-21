"""Archivo de HTML de fichas fallidas."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class ErrorArchivado(Exception):
    """Error al archivar HTML de ficha fallida."""
    pass


def archivar_html_fallido(
    codigo: str,
    html: str,
    fecha: str,
    directorio: Path,
) -> Path:
    """Archiva el HTML de una ficha fallida para diagnóstico posterior.

    Args:
        codigo: Código de oferta de 12 dígitos.
        html: Contenido HTML de la ficha fallida.
        fecha: Fecha en formato YYYY-MM-DD.
        directorio: Directorio donde guardar el archivo.

    Returns:
        Ruta del archivo creado.

    Raises:
        ErrorArchivado: Si no se puede crear el directorio o escribir el archivo.
    """
    logger.debug(f"Archivando HTML fallido para código {codigo} en {directorio}")
    # Crear directorio si no existe
    try:
        directorio.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.error(f"No se pudo crear directorio {directorio}: {e}")
        raise ErrorArchivado(
            f"No se pudo crear el directorio {directorio}: {e}"
        ) from e

    # Construir nombre del archivo: <codigo>_<fecha>.html
    nombre_archivo = f"{codigo}_{fecha}.html"
    ruta_archivo = directorio / nombre_archivo

    # Escribir HTML (sobrescribe si ya existe)
    try:
        ruta_archivo.write_text(html, encoding="utf-8")
        logger.info(f"HTML archivado correctamente: {ruta_archivo}")
    except OSError as e:
        logger.error(f"No se pudo escribir archivo {ruta_archivo}: {e}")
        raise ErrorArchivado(
            f"No se pudo escribir el archivo {ruta_archivo}: {e}"
        ) from e

    return ruta_archivo
