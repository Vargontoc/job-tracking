"""Adaptador de descarga del PDF de difusión sobre el descargador en proceso.

Envuelve `source/api/downloader.descargar_pdf` para que la comprobación de
integridad reciba siempre los bytes del PDF o un error propio y controlado
(`ErrorDescargaIntegridad`). No reimplementa la descarga ni escribe nada en
disco: la escritura del fichero es de `pdf-store`. El descargador se invoca
**en proceso**, de modo que no se emite ninguna petición HTTP al endpoint
`GET /parse` ni a ningún otro endpoint de la API (SUP-005).

Los fallos HTTP, de tiempo de espera agotado y de conexión comparten la forma
del mensaje que devuelve el descargador y se propagan sin lanzar excepción
(ALT-003).
"""

from collections.abc import Callable
from dataclasses import dataclass

import httpx

from source.api.downloader import ErrorDescarga, descargar_pdf


Descargador = Callable[..., bytes | ErrorDescarga]


@dataclass(frozen=True)
class ErrorDescargaIntegridad:
    """Fallo controlado al descargar el PDF de difusión (ALT-003).

    Es propio de la integridad y distinto del `ErrorParseoIntegridad`, de modo
    que quien orquesta la comprobación puede separar un fallo de descarga de
    uno de parseo por el tipo del resultado, sin propagar excepciones.
    """

    mensaje: str

    @property
    def motivo(self) -> str:
        """Motivo legible del fallo, para el `.meta.json` y los avisos."""
        return self.mensaje


class AdaptadorDescarga:
    """Descarga el PDF de difusión con el descargador en proceso (REQ-001).

    Args:
        descargador: función que descarga y devuelve `bytes | ErrorDescarga`.
            Por defecto, `source.api.downloader.descargar_pdf`. Es inyectable
            para las pruebas (doble del descargador).
        cliente: cliente `httpx` opcional que se pasa al descargador; en las
            pruebas, un `httpx.Client` con `MockTransport`.
    """

    def __init__(
        self,
        descargador: Descargador = descargar_pdf,
        cliente: httpx.Client | None = None,
    ) -> None:
        self._descargador = descargador
        self._cliente = cliente

    def descargar(self, url: str) -> bytes | ErrorDescargaIntegridad:
        """Devuelve los bytes del PDF o un error controlado, sin excepción."""
        resultado = self._descargador(url, cliente=self._cliente)
        if isinstance(resultado, ErrorDescarga):
            return ErrorDescargaIntegridad(mensaje=resultado.mensaje)
        return resultado
