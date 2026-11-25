"""Endpoints de consulta del listado de ofertas.

Expone ``GET /listado`` (consulta filtrada y paginada de ofertas) y
``GET /listado/filtros`` (filtros soportados con su tipo, formato y ejemplo).
En ``GET /listado`` los parámetros se validan antes de tocar la base de datos:
una fecha mal formada, un rango invertido, un desplazamiento negativo o un
tamaño de página no positivo se rechazan con ``400`` y, en las fechas, con el
formato esperado. Un fallo de acceso a los datos se traduce en un ``503`` sin
exponer detalles internos. ``GET /listado/filtros`` es una respuesta estática:
no consulta la base de datos. Ninguno de los dos exige autenticación, como el
resto de la API.
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from source.api.listado.config import ConfigListado
from source.api.listado.date_parser import ErrorFecha, validar_fecha, validar_rango
from source.api.listado.read_adapter import ErrorAccesoDatos
from source.api.listado.repository import RepositorioListado

router = APIRouter(prefix="/listado", tags=["listado"])


# ---------------------------------------------------------------------------
# Modelos Pydantic
# ---------------------------------------------------------------------------

class SolicitudListado(BaseModel):
    """Parámetros de ``GET /listado`` una vez validados.

    Es el modelo de entrada del endpoint: se construye solo cuando las fechas,
    el desplazamiento y el tamaño de página ya han pasado la validación, de modo
    que el repositorio recibe valores válidos.
    """

    texto: str | None = Field(
        default=None,
        description="Término de búsqueda libre sobre ocupación, municipio y texto.",
    )
    sector: str | None = Field(
        default=None,
        description="Sector de la oferta. Existe aunque hoy el campo esté vacío.",
    )
    municipio: str | None = Field(
        default=None,
        description="Municipio, por igualdad e insensible a mayúsculas y tildes.",
    )
    fecha_desde: str | None = Field(
        default=None,
        description="Fecha de inicio de difusión mínima, en formato dd/mm/aaaa.",
    )
    fecha_hasta: str | None = Field(
        default=None,
        description="Fecha de inicio de difusión máxima, en formato dd/mm/aaaa.",
    )
    incluir_cerradas: bool = Field(
        default=False,
        description="Incluye las ofertas cerradas además de las vigentes.",
    )
    offset: int = Field(default=0, description="Ofertas omitidas desde el inicio.")
    tamano_pagina: int = Field(
        default=20, description="Ofertas por página, recortado al máximo configurado."
    )

    def filtros(self) -> dict[str, object]:
        """Devuelve los filtros en el formato que consume el repositorio."""
        return {
            "texto": self.texto,
            "sector": self.sector,
            "municipio": self.municipio,
            "fecha_desde": self.fecha_desde,
            "fecha_hasta": self.fecha_hasta,
            "incluir_cerradas": self.incluir_cerradas,
        }


class OfertaListadoRespuesta(BaseModel):
    """Una oferta del listado con los once campos de REQ-008."""

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


class RespuestaListado(BaseModel):
    """Página del listado con sus metadatos de paginación y filtros."""

    items: list[OfertaListadoRespuesta]
    total: int = Field(description="Ofertas que cumplen los filtros.")
    pagina: int = Field(description="Página actual, empezando en 1.")
    tamano_pagina: int = Field(description="Tamaño de página aplicado.")
    filtros_aplicados: dict[str, str | bool] = Field(
        description="Filtros recibidos que han restringido la consulta."
    )


class FiltroDisponible(BaseModel):
    """Un filtro que admite ``GET /listado``, con sus metadatos de uso."""

    nombre: str = Field(description="Nombre del parámetro de consulta.")
    tipo: str = Field(description="Tipo de valor que admite el filtro.")
    formato: str = Field(description="Formato esperado del valor.")
    ejemplo: str = Field(description="Valor de ejemplo del filtro.")


class RespuestaFiltrosDisponibles(BaseModel):
    """Filtros soportados por ``GET /listado``."""

    filtros: list[FiltroDisponible]


# ---------------------------------------------------------------------------
# Filtros anunciados por ``GET /listado/filtros``
# ---------------------------------------------------------------------------

#: Respuesta estática de ``GET /listado/filtros`` (DEC-005).
#:
#: El filtro por ``sector`` se anuncia aunque hoy el campo se almacene siempre
#: vacío (REQ-003, ALT-007); el filtro por ``oficina`` no se anuncia porque el
#: campo no existe en el esquema de api-persistencia (SUP-002).
_FILTROS_DISPONIBLES: tuple[FiltroDisponible, ...] = (
    FiltroDisponible(
        nombre="texto",
        tipo="texto",
        formato="texto libre",
        ejemplo="tecnico",
    ),
    FiltroDisponible(
        nombre="sector",
        tipo="texto",
        formato="texto (igualdad exacta)",
        ejemplo="Informática",
    ),
    FiltroDisponible(
        nombre="municipio",
        tipo="texto",
        formato="texto (igualdad, sin distinguir mayúsculas ni tildes)",
        ejemplo="Santander",
    ),
    FiltroDisponible(
        nombre="fecha_desde",
        tipo="fecha",
        formato="dd/mm/aaaa",
        ejemplo="10/11/2026",
    ),
    FiltroDisponible(
        nombre="fecha_hasta",
        tipo="fecha",
        formato="dd/mm/aaaa",
        ejemplo="20/11/2026",
    ),
    FiltroDisponible(
        nombre="incluir_cerradas",
        tipo="booleano",
        formato="true | false",
        ejemplo="true",
    ),
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=RespuestaListado)
def consultar_listado(
    texto: str | None = Query(
        default=None,
        description="Término de búsqueda libre sobre ocupación, municipio y texto.",
    ),
    sector: str | None = Query(
        default=None, description="Sector de la oferta."
    ),
    municipio: str | None = Query(
        default=None, description="Municipio de la oferta."
    ),
    fecha_desde: str | None = Query(
        default=None, description="Fecha mínima de inicio de difusión (dd/mm/aaaa)."
    ),
    fecha_hasta: str | None = Query(
        default=None, description="Fecha máxima de inicio de difusión (dd/mm/aaaa)."
    ),
    incluir_cerradas: bool = Query(
        default=False, description="Incluye también las ofertas cerradas."
    ),
    offset: int = Query(
        default=0, description="Número de ofertas omitidas desde el principio."
    ),
    tamano_pagina: int | None = Query(
        default=None,
        description="Ofertas por página; si supera el máximo configurado, se recorta.",
    ),
) -> RespuestaListado:
    """Devuelve una página del listado que cumple todos los filtros.

    Valida los parámetros antes de tocar la base de datos, aplica el recorte del
    tamaño de página al máximo configurado y orquesta el repositorio de consulta.

    Raises:
        HTTPException: ``400`` si un parámetro no es válido, identificando cuál y,
            en las fechas, el formato ``dd/mm/aaaa``; ``503`` si la feature no
            está disponible o no se puede acceder a los datos.
    """
    config = _obtener_configuracion()
    solicitud = _construir_solicitud(
        config,
        texto=texto,
        sector=sector,
        municipio=municipio,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        incluir_cerradas=incluir_cerradas,
        offset=offset,
        tamano_pagina=tamano_pagina,
    )
    repositorio = _obtener_repositorio()

    try:
        resultado = repositorio.consultar(
            solicitud.filtros(),
            offset=solicitud.offset,
            tamano_pagina=solicitud.tamano_pagina,
        )
    except ErrorAccesoDatos as error:
        raise HTTPException(
            status_code=503,
            detail="No se puede acceder a los datos del listado.",
        ) from error

    return RespuestaListado(
        items=[
            OfertaListadoRespuesta(**asdict(oferta)) for oferta in resultado.items
        ],
        total=resultado.total,
        pagina=resultado.pagina,
        tamano_pagina=resultado.tamano_pagina,
        filtros_aplicados=resultado.filtros_aplicados,
    )


@router.get("/filtros", response_model=RespuestaFiltrosDisponibles)
def consultar_filtros_disponibles() -> RespuestaFiltrosDisponibles:
    """Devuelve los filtros que admite ``GET /listado`` con sus metadatos.

    La respuesta es estática: no consulta la base de datos ni depende de la
    configuración de la feature, por lo que ``sector`` figura como soportado
    aunque hoy no haya ofertas con ese valor (REQ-003, ALT-007) y ``oficina``
    no se anuncia (SUP-002). No exige autenticación.
    """
    return RespuestaFiltrosDisponibles(
        filtros=list(_FILTROS_DISPONIBLES),
    )


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _obtener_configuracion() -> ConfigListado:
    """Recupera la configuración del listado desde ``app_state``.

    Raises:
        HTTPException: ``503`` si el listado no se inicializó.
    """
    from source.api.main import app_state

    config = app_state.get("config_listado")
    if config is None:
        raise HTTPException(
            status_code=503,
            detail="El listado no está disponible. Comprueba la configuración.",
        )
    return config


def _obtener_repositorio() -> RepositorioListado:
    """Recupera el repositorio del listado desde ``app_state``.

    Raises:
        HTTPException: ``503`` si el listado no se inicializó.
    """
    from source.api.main import app_state

    repositorio = app_state.get("repositorio_listado")
    if repositorio is None:
        raise HTTPException(
            status_code=503,
            detail="El listado no está disponible. Comprueba la configuración.",
        )
    return repositorio


def _construir_solicitud(
    config: ConfigListado,
    *,
    texto: str | None,
    sector: str | None,
    municipio: str | None,
    fecha_desde: str | None,
    fecha_hasta: str | None,
    incluir_cerradas: bool,
    offset: int,
    tamano_pagina: int | None,
) -> SolicitudListado:
    """Valida los parámetros y devuelve la solicitud lista para el repositorio.

    El tamaño de página ausente toma el valor por defecto de la configuración y
    se recorta al máximo configurado cuando lo supera (NFR-001, DEC-004).

    Raises:
        HTTPException: ``400`` si una fecha no cumple ``dd/mm/aaaa``, el rango
            está invertido, el desplazamiento es negativo o el tamaño de página
            no es positivo.
    """
    _validar_fechas(fecha_desde, fecha_hasta)

    if offset < 0:
        raise HTTPException(
            status_code=400,
            detail="El parámetro 'offset' no puede ser negativo.",
        )

    tamano = (
        config.tamano_pagina_por_defecto
        if tamano_pagina is None
        else tamano_pagina
    )
    if tamano <= 0:
        raise HTTPException(
            status_code=400,
            detail="El parámetro 'tamano_pagina' debe ser mayor que cero.",
        )
    tamano = min(tamano, config.tamano_pagina_maximo)

    return SolicitudListado(
        texto=texto,
        sector=sector,
        municipio=municipio,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        incluir_cerradas=incluir_cerradas,
        offset=offset,
        tamano_pagina=tamano,
    )


def _validar_fechas(fecha_desde: str | None, fecha_hasta: str | None) -> None:
    """Valida el formato de cada cota y que el rango no esté invertido.

    Raises:
        HTTPException: ``400`` identificando el parámetro y, en el formato, el
            esperado ``dd/mm/aaaa`` (REQ-009, ALT-002).
    """
    for nombre, valor in (
        ("fecha_desde", fecha_desde),
        ("fecha_hasta", fecha_hasta),
    ):
        if not valor:
            continue
        try:
            validar_fecha(valor)
        except ErrorFecha:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"El parámetro '{nombre}' debe ser una fecha con formato "
                    f"dd/mm/aaaa; recibido: {valor!r}"
                ),
            ) from None

    try:
        validar_rango(fecha_desde, fecha_hasta)
    except ErrorFecha as error:
        raise HTTPException(status_code=400, detail=str(error)) from None
