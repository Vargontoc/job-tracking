"""Purga de PDFs y metadatos fuera de la ventana de retención.

Recorre el árbol `<base>/<comunidad>/` y elimina cada `<aaaa-mm-dd>.pdf` con
su `<aaaa-mm-dd>.meta.json` cuando la fecha **del nombre** queda fuera de la
ventana de retención configurada (REQ-002). La antigüedad se decide solo por
esa fecha y nunca por el `mtime` del fichero (DEC-004), de modo que una copia
restaurada no desplaza la ventana.

La ventana es inclusiva: se conserva un fichero con exactamente
`dias_retencion` días de antigüedad y, por supuesto, el del día en curso. Los
nombres que no siguen el patrón `<aaaa-mm-dd>.pdf` o `<aaaa-mm-dd>.meta.json`
se ignoran y no se borran, y tampoco se borra ningún directorio. Un `.pdf`
cuyo parseo falló se purga con el mismo plazo que los demás (DEC-002).

Sin SQLite: la purga solo trabaja sobre el sistema de archivos (DEC-001). La
tarea diaria calcula `hoy` con la zona horaria configurada y le pasa el
resultado; aquí no hay reloj propio ni lógica de planificación.
"""

import logging
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_SUFIJO_PDF = ".pdf"
_SUFIJO_META = ".meta.json"


def purgar(base: str | Path, dias_retencion: int, hoy: date) -> list[Path]:
    """Elimina de `base` los días fuera de la ventana de retención.

    Args:
        base: Ruta base del árbol de PDFs (`data/pdfs` por defecto). Si no
            existe, no hay nada que purgar.
        dias_retencion: Días que se conservan; por defecto `30` en la
            configuración de la integridad.
        hoy: Día en curso, en la zona horaria configurada. Nada con fecha
            igual o posterior a `hoy` se elimina.

    Returns:
        Las rutas eliminadas. Una ruta base inexistente o sin directorios de
        comunidad devuelve una lista vacía sin error.
    """
    raiz = Path(base)
    if not raiz.is_dir():
        return []

    dia = _como_fecha(hoy)
    eliminados: list[Path] = []
    for carpeta in sorted(raiz.iterdir()):
        if carpeta.is_dir():
            eliminados.extend(_purgar_comunidad(carpeta, dias_retencion, dia))
    return eliminados


def _purgar_comunidad(
    carpeta: Path, dias_retencion: int, hoy: date
) -> list[Path]:
    """Purga un directorio de comunidad y devuelve lo eliminado."""
    eliminados: list[Path] = []
    for fichero in sorted(carpeta.iterdir()):
        if not fichero.is_file():
            continue
        fecha = _fecha_del_nombre(fichero.name)
        if fecha is None:
            logger.debug("Nombre fuera del patrón, se ignora: %s", fichero)
            continue
        if not _fuera_de_ventana(fecha, dias_retencion, hoy):
            continue
        for ruta in _rutas_del_dia(carpeta, fecha):
            if ruta.is_file():
                ruta.unlink()
                eliminados.append(ruta)
                logger.info("PDF purgado por antigüedad: %s", ruta)
    return eliminados


def _rutas_del_dia(carpeta: Path, fecha: date) -> tuple[Path, Path]:
    """Devuelve el PDF del día y sus metadatos en el directorio de comunidad."""
    nombre = fecha.isoformat()
    return (
        carpeta / f"{nombre}{_SUFIJO_PDF}",
        carpeta / f"{nombre}{_SUFIJO_META}",
    )


def _fuera_de_ventana(fecha: date, dias_retencion: int, hoy: date) -> bool:
    """Indica si un día queda fuera de la ventana de retención (inclusiva).

    El día en curso y cualquier fecha futura se conservan siempre; con
    exactamente `dias_retencion` días de antigüedad también se conserva.
    """
    if fecha >= hoy:
        return False
    return (hoy - fecha).days > dias_retencion


def _fecha_del_nombre(nombre: str) -> date | None:
    """Devuelve la fecha de un nombre `<aaaa-mm-dd>.pdf` o `.meta.json`.

    Exige el patrón exacto (mismo criterio que `pdf_store`): el nombre debe
    llevar uno de los dos sufijos y su raíz debe ser la forma canónica ISO de
    una fecha, de modo que `2026-1-1.pdf`, `otro.pdf` o `2026-11-23.pdf.bak`
    devuelven `None` y no se tocan.
    """
    for sufijo in (_SUFIJO_META, _SUFIJO_PDF):
        if nombre.endswith(sufijo):
            raiz = nombre[: -len(sufijo)]
            break
    else:
        return None

    try:
        fecha = date.fromisoformat(raiz)
    except ValueError:
        return None
    return fecha if fecha.isoformat() == raiz else None


def _como_fecha(dia: date) -> date:
    """Reduce un `datetime` a su fecha para que la resta sea entre días."""
    return dia.date() if isinstance(dia, datetime) else dia
