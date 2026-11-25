"""Validación de fechas ``dd/mm/aaaa`` y expresiones SQL del listado.

Valida las fechas de entrada, rechaza rangos invertidos y genera la expresión
SQL que convierte ``fecha_inicio_difusion`` a texto ISO ordenable con una guarda
explícita de patrón ``GLOB``, además de la expresión de orden que deja las
ofertas sin fecha válida al final del listado.
"""

from __future__ import annotations

import re
from datetime import datetime

#: Patrón de una fecha ``dd/mm/aaaa`` completa, sin espacios ni separadores
#: alternativos. Se usa tanto en la validación de entrada como en la guarda
#: ``GLOB`` de la expresión SQL (DEC-003).
_PATRON_FECHA = r"[0-9][0-9]/[0-9][0-9]/[0-9][0-9][0-9][0-9]"
_FECHA_ESTRICTA = re.compile(rf"^{_PATRON_FECHA}$")

#: Columna sobre la que se filtra y ordena (SUP-004).
_COLUMNA_FECHA = "fecha_inicio_difusion"


class ErrorFecha(Exception):
    """Indica que una fecha o un rango de fechas no es válido."""


def validar_fecha(texto: str) -> str:
    """Valida una fecha ``dd/mm/aaaa`` y la devuelve como texto ISO.

    Args:
        texto: Fecha introducida por el cliente, en formato ``dd/mm/aaaa``.

    Returns:
        La fecha en formato ISO ``aaaa-mm-dd``, comparable como texto.

    Raises:
        ErrorFecha: Si el texto no cumple ``dd/mm/aaaa`` o la fecha no existe
            (por ejemplo, ``32/13/2026`` o ``31/02/2026``).
    """
    if not isinstance(texto, str) or not _FECHA_ESTRICTA.match(texto):
        raise ErrorFecha(
            f"El formato de la fecha debe ser dd/mm/aaaa: {texto!r}."
        )
    try:
        fecha = datetime.strptime(texto, "%d/%m/%Y").date()
    except ValueError as error:
        raise ErrorFecha(
            f"La fecha {texto!r} no es válida; el formato esperado es dd/mm/aaaa."
        ) from error
    return fecha.isoformat()


def validar_rango(
    desde: str | None = None, hasta: str | None = None
) -> tuple[str | None, str | None]:
    """Valida un rango de fechas ``dd/mm/aaaa`` y lo devuelve en ISO.

    Sus dos cotas son opcionales: un valor vacío o ``None`` significa que ese
    extremo del rango no se aplica.

    Args:
        desde: Cota inferior del rango, o ``None`` si no se aplica.
        hasta: Cota superior del rango, o ``None`` si no se aplica.

    Returns:
        Tupla ``(desde_iso, hasta_iso)``, con ``None`` en los extremos no
        aplicados.

    Raises:
        ErrorFecha: Si alguna cota no es una fecha ``dd/mm/aaaa`` válida o si
            ``desde`` es posterior a ``hasta``.
    """
    desde_iso = validar_fecha(desde) if desde else None
    hasta_iso = validar_fecha(hasta) if hasta else None

    if desde_iso is not None and hasta_iso is not None and desde_iso > hasta_iso:
        raise ErrorFecha(
            f"El rango de fechas es inválido: 'desde' ({desde}) es posterior a "
            f"'hasta' ({hasta})."
        )

    return desde_iso, hasta_iso


def expresion_fecha_iso() -> str:
    """Expresión SQL que convierte ``fecha_inicio_difusion`` a texto ISO.

    La guarda ``GLOB`` deja como ``NULL`` las fechas vacías, cortas o
    corruptas, de modo que quedan fuera de los rangos y al final del orden
    (ALT-004, DEC-003).
    """
    return (
        f"CASE WHEN {_COLUMNA_FECHA} GLOB '{_PATRON_FECHA}' "
        f"THEN substr({_COLUMNA_FECHA}, 7, 4) || '-' || "
        f"substr({_COLUMNA_FECHA}, 4, 2) || '-' || "
        f"substr({_COLUMNA_FECHA}, 1, 2) "
        "ELSE NULL END"
    )


def expresion_orden() -> str:
    """Cláusula ``ORDER BY`` del listado.

    Ordena por fecha de inicio de difusión descendente, con las ofertas sin
    fecha válida siempre al final y desempate por ``codigo`` ascendente
    (REQ-007, SUP-004, DEC-003).
    """
    expresion = expresion_fecha_iso()
    return f"ORDER BY {expresion} IS NULL, {expresion} DESC, codigo ASC"
