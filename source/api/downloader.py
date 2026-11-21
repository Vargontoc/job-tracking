"""Descarga de PDFs de difusión."""

from dataclasses import dataclass

import httpx


TIMEOUT_SECONDS = 20.0


@dataclass(frozen=True)
class ErrorDescarga:
    """Fallo controlado durante la descarga de un PDF."""

    mensaje: str


def descargar_pdf(
    url: str,
    *,
    cliente: httpx.Client | None = None,
) -> bytes | ErrorDescarga:
    """Descarga un PDF o devuelve un error controlado."""
    if cliente is not None:
        return _descargar(url, cliente)

    with httpx.Client(follow_redirects=True) as cliente_nuevo:
        return _descargar(url, cliente_nuevo)


def _descargar(url: str, cliente: httpx.Client) -> bytes | ErrorDescarga:
    try:
        respuesta = cliente.get(url, timeout=TIMEOUT_SECONDS)
        respuesta.raise_for_status()
    except httpx.HTTPStatusError as error:
        return ErrorDescarga(
            f"Error de descarga: HTTP {error.response.status_code}."
        )
    except httpx.TimeoutException:
        return ErrorDescarga("Error de descarga: tiempo de espera agotado.")
    except httpx.RequestError:
        return ErrorDescarga("Error de descarga: error de conexión.")

    return respuesta.content
