"""Pruebas unitarias de la descarga de PDFs."""

import httpx
import pytest

import source.api.downloader as downloader
from source.api.downloader import (
    TIMEOUT_SECONDS,
    ErrorDescarga,
    descargar_pdf,
)


URL = "https://ejemplo.test/ofertas.pdf"


def test_descarga_los_bytes_de_una_respuesta_correcta() -> None:
    contenido = b"%PDF-1.4"

    with httpx.Client(
        transport=httpx.MockTransport(
            lambda solicitud: httpx.Response(200, content=contenido)
        )
    ) as cliente:
        resultado = descargar_pdf(URL, cliente=cliente)

    assert resultado == contenido


def test_sigue_redireccion_hasta_la_descarga_correcta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url_final = "https://descargas.ejemplo.test/ofertas.pdf"
    solicitudes: list[str] = []

    def responder(solicitud: httpx.Request) -> httpx.Response:
        solicitudes.append(str(solicitud.url))
        if str(solicitud.url) == URL:
            return httpx.Response(
                301,
                headers={"Location": url_final},
                request=solicitud,
            )
        return httpx.Response(200, content=b"%PDF-1.4", request=solicitud)

    cliente = httpx.Client(
        follow_redirects=True,
        transport=httpx.MockTransport(responder),
    )

    def crear_cliente(*, follow_redirects: bool) -> httpx.Client:
        assert follow_redirects is True
        return cliente

    monkeypatch.setattr(downloader.httpx, "Client", crear_cliente)
    resultado = descargar_pdf(URL)

    assert resultado == b"%PDF-1.4"
    assert solicitudes == [URL, url_final]


def test_devuelve_error_con_el_codigo_http() -> None:
    def responder(solicitud: httpx.Request) -> httpx.Response:
        return httpx.Response(404, request=solicitud)

    with httpx.Client(transport=httpx.MockTransport(responder)) as cliente:
        resultado = descargar_pdf(URL, cliente=cliente)

    assert isinstance(resultado, ErrorDescarga)
    assert "404" in resultado.mensaje


def test_devuelve_error_cuando_agota_el_timeout() -> None:
    def agotar_timeout(solicitud: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("agotado", request=solicitud)

    with httpx.Client(transport=httpx.MockTransport(agotar_timeout)) as cliente:
        resultado = descargar_pdf(URL, cliente=cliente)

    assert isinstance(resultado, ErrorDescarga)
    assert "tiempo de espera agotado" in resultado.mensaje


def test_devuelve_error_ante_un_fallo_de_conexion() -> None:
    def fallar_conexion(solicitud: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin conexión", request=solicitud)

    with httpx.Client(transport=httpx.MockTransport(fallar_conexion)) as cliente:
        resultado = descargar_pdf(URL, cliente=cliente)

    assert isinstance(resultado, ErrorDescarga)
    assert "conexión" in resultado.mensaje


def test_usa_timeout_explicito_y_no_envia_autorizacion() -> None:
    class ClienteDePrueba:
        def __init__(self) -> None:
            self.timeout: float | None = None
            self.argumentos_adicionales: dict[str, object] = {}

        def get(
            self,
            url: str,
            *,
            timeout: float,
            **kwargs: object,
        ) -> httpx.Response:
            self.timeout = timeout
            self.argumentos_adicionales = kwargs
            return httpx.Response(
                200,
                content=b"%PDF",
                request=httpx.Request("GET", url),
            )

    cliente = ClienteDePrueba()

    resultado = descargar_pdf(URL, cliente=cliente)  # type: ignore[arg-type]

    assert resultado == b"%PDF"
    assert cliente.timeout == TIMEOUT_SECONDS
    assert cliente.argumentos_adicionales == {}
