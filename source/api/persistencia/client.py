"""Cliente HTTP para consultar el estado del rastreador del buscador."""

from dataclasses import dataclass, field

import httpx


@dataclass
class UltimaPasada:
    """Resultado publicado de la última pasada del buscador.

    Atributos:
        timestamp: Marca de tiempo ISO del inicio de la pasada.
        comunidad: Comunidad rastreada.
        total_listado: Total de ofertas encontradas en el listado.
        error_global: Error que impidió completar la pasada (vacío si no hay).
        errores_por_oferta: Lista de errores por oferta individual.
        ofertas_nuevas: Lista de ofertas nuevas parseadas correctamente.
    """

    timestamp: str = ""
    comunidad: str = ""
    total_listado: int = 0
    error_global: str = ""
    errores_por_oferta: list = field(default_factory=list)
    ofertas_nuevas: list = field(default_factory=list)


@dataclass
class EstadoBuscador:
    """Estado publicado por el buscador.

    Atributos:
        in_progress: Si hay una pasada en curso.
        progreso: Progreso de la pasada en curso, o None si no hay.
        ultima_pasada: Resultado de la última pasada, o None si no hay.
    """

    in_progress: bool = False
    progreso: dict | None = None
    ultima_pasada: UltimaPasada | None = None


@dataclass
class ResultadoConsultaEstado:
    """Resultado de consultar el estado del buscador.

    Si la consulta tuvo éxito, ``estado`` contiene el estado publicado
    y ``error`` está vacío. Si falló (error HTTP o de red), ``estado``
    es None y ``error`` describe el problema.

    Atributos:
        estado: Estado del buscador si la consulta fue exitosa.
        error: Mensaje de error si la consulta falló.
    """

    estado: EstadoBuscador | None = None
    error: str = ""


class ClienteBuscador:
    """Cliente HTTP que consulta GET /buscador/status.

    Nunca lanza peticiones de pasada ni descarga fichas; solo lee el
    estado publicado en memoria por el rastreador.

    Args:
        url_base: URL base del buscador (por ejemplo, ``http://localhost:8000``).
        cliente: Cliente HTTP inyectable para pruebas. Si no se proporciona,
            se crea un ``httpx.Client`` al hacer la primera consulta.
    """

    def __init__(
        self,
        url_base: str,
        cliente: httpx.Client | None = None,
    ) -> None:
        self._url_base = url_base.rstrip("/")
        self._cliente = cliente

    def consultar_estado(self) -> ResultadoConsultaEstado:
        """Consulta ``GET /buscador/status`` y devuelve el resultado.

        Devuelve un :class:`ResultadoConsultaEstado` con ``estado`` si la
        petición tuvo éxito o con ``error`` no vacío si hubo un error HTTP,
        de red o si la respuesta no es JSON válido. Nunca lanza excepciones.
        """
        url = f"{self._url_base}/buscador/status"
        try:
            respuesta = self._obtener_cliente().get(url)
            respuesta.raise_for_status()
        except httpx.HTTPStatusError as error:
            return ResultadoConsultaEstado(
                error=(
                    f"Error HTTP {error.response.status_code} "
                    f"al consultar el estado del buscador en {url}."
                )
            )
        except httpx.RequestError as error:
            return ResultadoConsultaEstado(
                error=(
                    f"Error de red al consultar el estado del buscador "
                    f"en {url}: {error}."
                )
            )

        try:
            datos = respuesta.json()
        except Exception as error:  # pragma: no cover - defensa
            return ResultadoConsultaEstado(
                error=f"La respuesta de {url} no es JSON válido: {error}."
            )

        estado = _parsear_estado(datos)
        return ResultadoConsultaEstado(estado=estado)

    def _obtener_cliente(self) -> httpx.Client:
        if self._cliente is None:
            self._cliente = httpx.Client()
        return self._cliente


def _parsear_estado(datos: dict) -> EstadoBuscador:
    """Convierte el JSON de ``/buscador/status`` en un :class:`EstadoBuscador`."""
    ultima_pasada_datos = datos.get("ultima_pasada")
    ultima_pasada = None
    if ultima_pasada_datos is not None:
        ultima_pasada = UltimaPasada(
            timestamp=ultima_pasada_datos.get("timestamp", ""),
            comunidad=ultima_pasada_datos.get("comunidad", ""),
            total_listado=ultima_pasada_datos.get("total_listado", 0),
            error_global=ultima_pasada_datos.get("error_global", ""),
            errores_por_oferta=ultima_pasada_datos.get("errores_por_oferta", []),
            ofertas_nuevas=ultima_pasada_datos.get("ofertas_nuevas", []),
        )
    return EstadoBuscador(
        in_progress=datos.get("in_progress", False),
        progreso=datos.get("progreso"),
        ultima_pasada=ultima_pasada,
    )
