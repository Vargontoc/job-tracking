"""Repositorio de consulta del listado de ofertas.

Ejecuta la consulta sobre la conexión de solo lectura: con ``COUNT`` y
``LIMIT/OFFSET`` cuando no hay filtros textuales, y con filtrado en memoria de
las filas candidatas ya ordenadas antes de calcular el total y recortar la
página cuando los hay.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from source.api.listado.date_parser import expresion_orden
from source.api.listado.filter_builder import construir
from source.api.listado.read_adapter import AdaptadorLecturaListado
from source.api.listado.text_normalizer import coincide, contiene

#: Tamaño de página que se aplica cuando no se indica otro. Coincide con el
#: valor por defecto de la configuración del listado (DEC-006).
TAMANO_PAGINA_POR_DEFECTO = 20

#: Columnas que forman la oferta devuelta al cliente (REQ-008).
_COLUMNAS = (
    "comunidad, codigo, ocupacion, municipio, provincia, sector, "
    "fecha_inicio_difusion, fecha_fin_difusion, estado, contacto, texto_libre"
)

#: Claves de filtro que se anuncian como aplicadas en los metadatos (REQ-008).
_CLAVES_FILTRO = ("texto", "sector", "municipio", "fecha_desde", "fecha_hasta")


# ---------------------------------------------------------------------------
# Dataclasses de resultado
# ---------------------------------------------------------------------------

@dataclass
class OfertaListado:
    """Una oferta tal como la devuelve el listado (REQ-008)."""

    comunidad: str
    codigo: str
    ocupacion: str
    municipio: str
    provincia: str
    sector: str
    fecha_inicio_difusion: str
    fecha_fin_difusion: str
    estado: str
    contacto: str
    texto_libre: str


@dataclass
class ResultadoListado:
    """Página del listado con sus metadatos (REQ-007, REQ-008).

    Attributes:
        items: Ofertas de la página solicitada, ya ordenadas.
        total: Número de ofertas que cumplen los filtros. Con filtros
            textuales es el número de filas después del filtrado en memoria.
        pagina: Página actual, empezando en 1.
        tamano_pagina: Tamaño de página aplicado.
        filtros_aplicados: Filtros recibidos que han restringido la consulta.
    """

    items: list[OfertaListado] = field(default_factory=list)
    total: int = 0
    pagina: int = 1
    tamano_pagina: int = TAMANO_PAGINA_POR_DEFECTO
    filtros_aplicados: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Repositorio
# ---------------------------------------------------------------------------

class RepositorioListado:
    """Consulta el listado de ofertas sobre el adaptador de solo lectura."""

    def __init__(self, adaptador: AdaptadorLecturaListado) -> None:
        """Inicializa el repositorio.

        Args:
            adaptador: Adaptador de lectura ``mode=ro`` sobre el SQLite de
                api-persistencia.
        """
        self._adaptador = adaptador

    def consultar(
        self,
        filtros: Mapping[str, Any] | None = None,
        offset: int = 0,
        tamano_pagina: int = TAMANO_PAGINA_POR_DEFECTO,
    ) -> ResultadoListado:
        """Devuelve una página del listado que cumple todos los filtros.

        Si no hay filtros textuales, el total se calcula con ``COUNT`` en SQL y
        la página se obtiene con ``LIMIT/OFFSET``. Si hay filtro de texto libre
        o de municipio, SQL solo aplica los filtros no textuales y devuelve
        todas las filas candidatas ya ordenadas; el filtrado se hace en
        memoria, el total es el del conjunto filtrado y la página se recorta
        después (DEC-002).

        Args:
            filtros: Filtros validados por ``listado-api``: ``texto``,
                ``sector``, ``municipio``, ``fecha_desde``, ``fecha_hasta`` e
                ``incluir_cerradas``. Un valor ausente o vacío no filtra.
            offset: Número de ofertas que se omiten desde el principio.
            tamano_pagina: Número máximo de ofertas que devuelve la página.

        Returns:
            La página solicitada con el total real y los filtros aplicados.

        Raises:
            ErrorFecha: Si una fecha de filtro no cumple ``dd/mm/aaaa`` o el
                rango está invertido.
            ErrorAccesoDatos: Si no se puede acceder al SQLite de
                api-persistencia.
            ValueError: Si ``offset`` es negativo o ``tamano_pagina`` no es
                positivo.
        """
        if offset < 0:
            raise ValueError("El desplazamiento no puede ser negativo.")
        if tamano_pagina <= 0:
            raise ValueError("El tamaño de página debe ser mayor que cero.")

        filtros = dict(filtros or {})
        clausula = construir(filtros)
        where = f"WHERE {clausula.where}" if clausula.where else ""
        orden = expresion_orden()
        filtros_aplicados = _filtros_aplicados(filtros)

        if not clausula.filtrado_en_memoria:
            total = self._contar(where, clausula.parametros)
            items = [
                _convertir(fila)
                for fila in self._pagina(
                    where, orden, clausula.parametros, offset, tamano_pagina
                )
            ]
        else:
            candidatas = self._adaptador.consultar(
                f"SELECT {_COLUMNAS} FROM ofertas {where} {orden}",
                clausula.parametros,
            )
            filtradas = [
                fila
                for fila in candidatas
                if _pasa_filtros_textuales(fila, clausula.texto, clausula.municipio)
            ]
            total = len(filtradas)
            items = [
                _convertir(fila)
                for fila in filtradas[offset : offset + tamano_pagina]
            ]

        return ResultadoListado(
            items=items,
            total=total,
            pagina=offset // tamano_pagina + 1,
            tamano_pagina=tamano_pagina,
            filtros_aplicados=filtros_aplicados,
        )

    # -- consultas SQL --------------------------------------------------------

    def _contar(self, where: str, parametros: list[Any]) -> int:
        """Cuenta las filas que cumplen el ``WHERE`` en SQL."""
        filas = self._adaptador.consultar(
            f"SELECT COUNT(*) AS total FROM ofertas {where}", parametros
        )
        return int(filas[0]["total"])

    def _pagina(
        self,
        where: str,
        orden: str,
        parametros: list[Any],
        offset: int,
        tamano_pagina: int,
    ) -> list[Any]:
        """Recupera la página con ``LIMIT/OFFSET`` cuando no hay texto."""
        return self._adaptador.consultar(
            f"SELECT {_COLUMNAS} FROM ofertas {where} {orden} LIMIT ? OFFSET ?",
            [*parametros, tamano_pagina, offset],
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pasa_filtros_textuales(
    fila: Any, texto: str | None, municipio: str | None
) -> bool:
    """Aplica en memoria el texto libre y el municipio a una fila candidata.

    El texto libre coincide por contención sobre ``ocupacion``, ``municipio`` y
    ``texto_libre``, sin distinguir mayúsculas ni tildes (REQ-002, NFR-003). El
    municipio coincide por igualdad de cadenas normalizadas (REQ-004, DEC-002).
    """
    if texto is not None:
        if not (
            contiene(fila["ocupacion"], texto)
            or contiene(fila["municipio"], texto)
            or contiene(fila["texto_libre"], texto)
        ):
            return False
    if municipio is not None and not coincide(fila["municipio"], municipio):
        return False
    return True


def _convertir(fila: Any) -> OfertaListado:
    """Convierte una fila de SQLite en una oferta del listado.

    Los campos ``NULL`` o purgados se devuelven como cadena vacía (ALT-006).
    """
    return OfertaListado(
        comunidad=_texto(fila["comunidad"]),
        codigo=_texto(fila["codigo"]),
        ocupacion=_texto(fila["ocupacion"]),
        municipio=_texto(fila["municipio"]),
        provincia=_texto(fila["provincia"]),
        sector=_texto(fila["sector"]),
        fecha_inicio_difusion=_texto(fila["fecha_inicio_difusion"]),
        fecha_fin_difusion=_texto(fila["fecha_fin_difusion"]),
        estado=_texto(fila["estado"]),
        contacto=_texto(fila["contacto"]),
        texto_libre=_texto(fila["texto_libre"]),
    )


def _texto(valor: Any) -> str:
    """Devuelve un valor de texto, con la cadena vacía para ``NULL``."""
    return "" if valor is None else str(valor)


def _filtros_aplicados(filtros: Mapping[str, Any]) -> dict[str, Any]:
    """Resume los filtros recibidos que restringen la consulta (REQ-008)."""
    aplicados: dict[str, Any] = {}
    for clave in _CLAVES_FILTRO:
        valor = filtros.get(clave)
        if valor is None:
            continue
        texto = str(valor).strip()
        if texto:
            aplicados[clave] = texto
    if filtros.get("incluir_cerradas"):
        aplicados["incluir_cerradas"] = True
    return aplicados
