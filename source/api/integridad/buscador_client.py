"""Cliente HTTP del estado del buscador (GET /buscador/status).

Consulta el estado que publica `api-buscador` en su endpoint de solo lectura
`GET /buscador/status` y lo normaliza para la comprobación de integridad:
`in_progress`, `progreso` y `ultima_pasada` con `timestamp`, `comunidad`,
`total_listado`, `error_global` y `errores_por_oferta` (SUP-006).

`consultar_estado()` devuelve un `EstadoBuscador` cuando el estado es
utilizable por el comparador y un `EstadoBuscadorNoUtilizable` —sin lanzar
excepción— en los tres casos en los que no se puede emitir un veredicto
`concordante` (ALT-005, ALT-006):

- error HTTP o de red al consultar el endpoint;
- `ultima_pasada` nula o sin `total_listado`;
- `ultima_pasada.error_global` no vacío.

El cliente solo emite peticiones a `/buscador/status`: no lanza pasadas del
buscador, no descarga fichas y no escribe nada (SUP-004). Es propio de la
integridad y no reutiliza el cliente de `api-persistencia` ni el de
`api-historico`.
"""

from dataclasses import dataclass, field

import httpx

RUTA_ESTADO = "/buscador/status"


@dataclass(frozen=True)
class UltimaPasada:
    """Resumen de la última pasada finalizada publicado por el buscador.

    Atributos:
        timestamp: Marca de tiempo ISO del inicio de la pasada.
        comunidad: Comunidad rastreada.
        total_listado: Total de ofertas del listado (SUP-006).
        error_global: Error que impidió completar la pasada, vacío si no hay
            (ALT-006).
        errores_por_oferta: Errores por oferta individual.
    """

    timestamp: str
    comunidad: str
    total_listado: int
    error_global: str
    errores_por_oferta: list = field(default_factory=list)


@dataclass(frozen=True)
class EstadoBuscador:
    """Estado utilizable publicado por el buscador (REQ-003).

    Es el resultado de `consultar_estado()` cuando la consulta funciona, hay
    `ultima_pasada` con `total_listado` y esa pasada no tiene `error_global`.

    Atributos:
        in_progress: Si hay una pasada en curso.
        progreso: Progreso de la pasada en curso, o `None` si no hay.
        ultima_pasada: Resumen de la última pasada finalizada.
    """

    in_progress: bool
    progreso: dict | None
    ultima_pasada: UltimaPasada

    @property
    def total_listado(self) -> int:
        """Total del listado de la última pasada, cómodo para el comparador."""
        return self.ultima_pasada.total_listado


@dataclass(frozen=True)
class EstadoBuscadorNoUtilizable:
    """Estado del buscador que impide un veredicto `concordante`.

    Lo devuelve `consultar_estado()` sin lanzar excepción cuando la causa es un
    error HTTP o de red (ALT-005), una `ultima_pasada` nula o sin
    `total_listado` (ALT-005) o un `error_global` no vacío (ALT-006).

    Atributos:
        motivo: Descripción legible de la causa; es la que se registra en el
            `.meta.json` del día y en los avisos.
    """

    motivo: str


class ClienteEstadoBuscador:
    """Cliente HTTP que consulta `GET /buscador/status` (REQ-003).

    Args:
        url_base: URL base del buscador (por ejemplo,
            `http://localhost:8000`).
        cliente: cliente `httpx` inyectable; en las pruebas, un
            `httpx.Client` con `MockTransport`. Si no se indica, se crea uno
            por consulta y se cierra al terminar.
    """

    def __init__(
        self,
        url_base: str,
        cliente: httpx.Client | None = None,
    ) -> None:
        self._url_base = url_base.rstrip("/")
        self._cliente = cliente

    def consultar_estado(self) -> EstadoBuscador | EstadoBuscadorNoUtilizable:
        """Consulta `<url_base>/buscador/status` sin lanzar excepciones.

        Devuelve el estado normalizado si es utilizable o un
        `EstadoBuscadorNoUtilizable` con el motivo de la causa.
        """
        url = f"{self._url_base}{RUTA_ESTADO}"
        cliente_propio = self._cliente is None
        cliente = self._cliente
        if cliente is None:
            cliente = httpx.Client()
        try:
            try:
                respuesta = cliente.get(url)
                respuesta.raise_for_status()
            except httpx.HTTPStatusError as error:
                return EstadoBuscadorNoUtilizable(
                    motivo=(
                        "Error HTTP "
                        f"{error.response.status_code} al consultar el "
                        f"estado del buscador en {url}."
                    )
                )
            except httpx.RequestError as error:
                return EstadoBuscadorNoUtilizable(
                    motivo=(
                        "Error de red al consultar el estado del buscador en "
                        f"{url}: {error}."
                    )
                )

            try:
                datos = respuesta.json()
            except ValueError as error:
                return EstadoBuscadorNoUtilizable(
                    motivo=f"La respuesta de {url} no es JSON válido: {error}."
                )

            return _normalizar_estado(datos, url)
        finally:
            if cliente_propio:
                cliente.close()


def _normalizar_estado(
    datos: object,
    url: str,
) -> EstadoBuscador | EstadoBuscadorNoUtilizable:
    """Convierte el JSON de `/buscador/status` en estado utilizable o no."""
    if not isinstance(datos, dict):
        return EstadoBuscadorNoUtilizable(
            motivo=f"La respuesta de {url} no es un objeto JSON."
        )

    pasada_datos = datos.get("ultima_pasada")
    if pasada_datos is None:
        return EstadoBuscadorNoUtilizable(
            motivo=(
                "El buscador no publica 'ultima_pasada': no hay recuento del "
                "listado con el que comparar."
            )
        )
    if not isinstance(pasada_datos, dict):
        return EstadoBuscadorNoUtilizable(
            motivo=(
                "El buscador publica 'ultima_pasada' con un formato "
                f"inesperado en {url}."
            )
        )

    total_listado = pasada_datos.get("total_listado")
    if isinstance(total_listado, bool) or not isinstance(total_listado, int):
        return EstadoBuscadorNoUtilizable(
            motivo=(
                "El buscador no publica 'ultima_pasada.total_listado' como "
                "entero: no hay recuento del listado con el que comparar."
            )
        )

    error_global = pasada_datos.get("error_global") or ""
    if not isinstance(error_global, str):
        error_global = str(error_global)
    if error_global.strip():
        return EstadoBuscadorNoUtilizable(
            motivo=(
                "La última pasada del buscador terminó con error_global: "
                f"{error_global.strip()}"
            )
        )

    progreso = datos.get("progreso")
    if not isinstance(progreso, dict):
        progreso = None

    return EstadoBuscador(
        in_progress=bool(datos.get("in_progress", False)),
        progreso=progreso,
        ultima_pasada=UltimaPasada(
            timestamp=str(pasada_datos.get("timestamp") or ""),
            comunidad=str(pasada_datos.get("comunidad") or ""),
            total_listado=total_listado,
            error_global=error_global,
            errores_por_oferta=list(pasada_datos.get("errores_por_oferta") or []),
        ),
    )
