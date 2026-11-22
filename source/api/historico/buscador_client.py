"""Adaptador del estado del buscador.

Consulta ``GET /buscador/status`` en la URL base configurada y normaliza la
respuesta para los evaluadores del histórico. Ante un error HTTP, de red,
``ultima_pasada`` nula o ``error_global`` no vacío, devuelve un
``ErrorEstadoBuscador`` sin lanzar excepción.
"""

from dataclasses import dataclass, field

import httpx


@dataclass
class EstadoBuscador:
    """Estado publicado por el buscador en ``GET /buscador/status``.

    Atributos:
        total_ofertas: Total de ofertas del listado (``total_listado``).
        timestamp: Marca de tiempo de la última pasada.
        comunidad: Comunidad autónoma consultada.
        errores: Códigos de oferta con error en ``errores_por_oferta``.
    """

    total_ofertas: int
    timestamp: str
    comunidad: str
    errores: list[str] = field(default_factory=list)


@dataclass
class ErrorEstadoBuscador:
    """Error al consultar el estado del buscador.

    Se devuelve cuando la petición falla (HTTP o red), ``ultima_pasada`` es
    nula o ``error_global`` no está vacío.

    Atributos:
        motivo: Descripción del motivo del error.
    """

    motivo: str


class ClienteEstadoBuscador:
    """Cliente HTTP que consulta el estado del buscador.

    Args:
        url_base: URL base del buscador (por ejemplo ``http://localhost:8000``).
        cliente_http: Instancia de ``httpx.Client`` opcional. Si no se
            proporciona, se crea una nueva.
    """

    def __init__(self, url_base: str, cliente_http: httpx.Client | None = None) -> None:
        self._url_base = url_base.rstrip("/")
        self._cliente = cliente_http if cliente_http is not None else httpx.Client()
        self._owns_client = cliente_http is None

    def consultar_estado(self) -> EstadoBuscador | ErrorEstadoBuscador:
        """Consulta ``GET {url_base}/buscador/status`` y normaliza la respuesta.

        Returns:
            ``EstadoBuscador`` si la respuesta es válida y utilizable,
            ``ErrorEstadoBuscador`` si hay un error HTTP, de red, si
            ``ultima_pasada`` es nula o si ``error_global`` no está vacío.
        """
        try:
            respuesta = self._cliente.get(f"{self._url_base}/buscador/status")
            respuesta.raise_for_status()
            datos = respuesta.json()
        except httpx.HTTPStatusError as exc:
            return ErrorEstadoBuscador(
                motivo=f"HTTP {exc.response.status_code}"
            )
        except (httpx.RequestError, ValueError) as exc:
            return ErrorEstadoBuscador(motivo=str(exc))

        ultima_pasada = datos.get("ultima_pasada")
        if ultima_pasada is None:
            return ErrorEstadoBuscador(motivo="ultima_pasada es nula")

        error_global = ultima_pasada.get("error_global", "")
        if error_global:
            return ErrorEstadoBuscador(motivo=error_global)

        errores_por_oferta = ultima_pasada.get("errores_por_oferta", [])
        errores: list[str] = []
        for entrada in errores_por_oferta:
            if isinstance(entrada, dict):
                codigo = entrada.get("codigo", "")
                if codigo:
                    errores.append(codigo)
            elif isinstance(entrada, str):
                errores.append(entrada)

        return EstadoBuscador(
            total_ofertas=ultima_pasada.get("total_listado", 0),
            timestamp=ultima_pasada.get("timestamp", ""),
            comunidad=ultima_pasada.get("comunidad", ""),
            errores=errores,
        )
