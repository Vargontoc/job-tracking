"""Constructor del ``WHERE`` parametrizado del listado.

Traduce los filtros validados a una cláusula ``WHERE`` con parámetros
posicionales: estado, sector y rango de fechas se aplican en SQL, mientras que
los filtros textuales (texto libre y municipio) se omiten de la cláusula y se
señalan para su aplicación posterior en memoria.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, NamedTuple

from source.api.listado.date_parser import expresion_fecha_iso, validar_fecha

#: Estados visibles del listado: por defecto solo ``vigente`` y, con
#: ``incluir_cerradas``, también ``cerrada``. ``sin_ficha`` nunca se incluye
#: (REQ-006, SUP-003).
ESTADO_VIGENTE = "vigente"
ESTADO_CERRADA = "cerrada"


class ClausulaFiltros(NamedTuple):
    """Resultado de construir la cláusula del listado.

    Attributes:
        where: Condiciones unidas por ``AND``, sin la palabra clave ``WHERE``
            (la añade quien compone la consulta). Puede quedar vacía si no hay
            ninguna condición que aplicar.
        parametros: Valores posicionales de las condiciones del ``WHERE``, en el
            mismo orden en que aparecen sus marcadores ``?``.
        texto: Término de búsqueda libre que se aplica en memoria sobre
            ``ocupacion``, ``municipio`` y ``texto_libre``, o ``None`` si no se
            filtra por texto (DEC-002).
        municipio: Municipio que se aplica en memoria por igualdad de cadenas
            normalizadas, o ``None`` si no se filtra por municipio (DEC-002,
            REQ-004).
    """

    where: str
    parametros: list[Any]
    texto: str | None
    municipio: str | None

    @property
    def filtrado_en_memoria(self) -> bool:
        """Indica si quedan filtros textuales por aplicar fuera de SQL."""
        return self.texto is not None or self.municipio is not None


def _valor_texto(valor: Any) -> str | None:
    """Devuelve el valor como texto sin espacios, o ``None`` si está vacío.

    Un filtro vacío o ausente se interpreta como "sin filtro" (REQ-001).
    """
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto or None


def construir(filtros: Mapping[str, Any]) -> ClausulaFiltros:
    """Construye la cláusula ``WHERE`` y los parámetros del listado.

    Los filtros son los validados por ``listado-api``: ``texto``, ``sector``,
    ``municipio``, ``fecha_desde``, ``fecha_hasta`` e ``incluir_cerradas``. Las
    fechas llegan en ``dd/mm/aaaa`` y aquí se convierten a texto ISO
    ``aaaa-mm-dd`` para compararlas con la expresión de ``listado-date-parser``
    (DEC-003). Todo valor viaja como parámetro posicional, nunca concatenado en
    el texto de la consulta (REQ-010).

    Args:
        filtros: Mapa con los filtros recibidos. Una clave ausente o con valor
            vacío no genera condición.

    Returns:
        La cláusula con sus parámetros y los filtros textuales que se aplican
        en memoria.

    Raises:
        ErrorFecha: Si un valor de ``fecha_desde`` o ``fecha_hasta`` no cumple
            ``dd/mm/aaaa``.
    """
    condiciones: list[str] = []
    parametros: list[Any] = []

    # Visibilidad por estado: la regla por defecto es siempre la primera
    # condición, de modo que ``sin_ficha`` no aparece nunca (REQ-006, SUP-003).
    if filtros.get("incluir_cerradas"):
        condiciones.append("estado IN (?, ?)")
        parametros.extend([ESTADO_VIGENTE, ESTADO_CERRADA])
    else:
        condiciones.append("estado = ?")
        parametros.append(ESTADO_VIGENTE)

    # El sector se filtra aunque hoy el campo se almacene siempre vacío
    # (REQ-003, ALT-007).
    sector = _valor_texto(filtros.get("sector"))
    if sector is not None:
        condiciones.append("sector = ?")
        parametros.append(sector)

    # Rango de fechas sobre la fecha de inicio de difusión, convertida a texto
    # ISO con guarda de patrón (DEC-003, SUP-004).
    desde = _valor_texto(filtros.get("fecha_desde"))
    hasta = _valor_texto(filtros.get("fecha_hasta"))
    if desde is not None or hasta is not None:
        expresion = expresion_fecha_iso()
        if desde is not None:
            condiciones.append(f"{expresion} >= ?")
            parametros.append(validar_fecha(desde))
        if hasta is not None:
            condiciones.append(f"{expresion} <= ?")
            parametros.append(validar_fecha(hasta))

    # El texto libre y el municipio exigen tolerancia a tildes, que el
    # ``lower()`` de SQLite no cubre: se aplican en memoria (DEC-002).
    return ClausulaFiltros(
        where=" AND ".join(condiciones),
        parametros=parametros,
        texto=_valor_texto(filtros.get("texto")),
        municipio=_valor_texto(filtros.get("municipio")),
    )
