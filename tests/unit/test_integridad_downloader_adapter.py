"""Pruebas del adaptador de descarga del PDF de difusión (TASK-006).

Cubren `source/api/integridad/downloader_adapter.py`: `AdaptadorDescarga`
delega **en proceso** en `source/api/downloader.descargar_pdf`, devuelve los
bytes de un PDF válido (REQ-001) y convierte un `ErrorDescarga` en el error
propio `ErrorDescargaIntegridad` conservando el mensaje, sin lanzar excepción
(ALT-003). Los fallos HTTP, de tiempo de espera y de conexión son
distinguibles entre sí y de los bytes. Además se comprueba que no se emite
ninguna petición a `GET /parse` ni a otro endpoint de la API (SUP-005), que no
se descargan fichas del buscador y que el adaptador no escribe en disco.
"""

from pathlib import Path

import httpx
import pytest

from source.api.downloader import ErrorDescarga
from source.api.integridad.downloader_adapter import (
    AdaptadorDescarga,
    ErrorDescargaIntegridad,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
URL = "https://ejemplo.test/SNE_ListadoOfertasDifusionWEB/difusion.pdf"
PDF = b"%PDF-1.4 contenido del PDF de difusion\n"


def _cliente(responder) -> httpx.Client:
    """Cliente `httpx` que responde con `MockTransport`, sin red real."""
    return httpx.Client(transport=httpx.MockTransport(responder))


def _descargar_con(responder) -> bytes | ErrorDescargaIntegridad:
    """Descarga a través del adaptador con un cliente de prueba."""
    with _cliente(responder) as cliente:
        return AdaptadorDescarga(cliente=cliente).descargar(URL)


class DobleDescargador:
    """Doble del descargador en proceso que guarda cómo se le invocó."""

    def __init__(self, resultado: bytes | ErrorDescarga) -> None:
        self.resultado = resultado
        self.llamadas: list[tuple[str, object]] = []

    def __call__(
        self,
        url: str,
        *,
        cliente: httpx.Client | None = None,
    ) -> bytes | ErrorDescarga:
        self.llamadas.append((url, cliente))
        return self.resultado


def _responder_pdf(solicitud: httpx.Request) -> httpx.Response:
    """Respuesta correcta con el contenido del PDF."""
    return httpx.Response(200, content=PDF, request=solicitud)


# --- Resultado correcto (REQ-001) -------------------------------------------


def test_con_un_pdf_valido_devuelve_los_bytes() -> None:
    """Un PDF descargado correctamente llega tal cual al llamante (REQ-001)."""
    resultado = _descargar_con(_responder_pdf)

    assert isinstance(resultado, bytes)
    assert resultado == PDF


def test_un_doble_que_devuelve_bytes_los_devuelve_tal_cual() -> None:
    """El descargador es inyectable y los bytes se devuelven sin tocar."""
    doble = DobleDescargador(PDF)

    resultado = AdaptadorDescarga(descargador=doble).descargar(URL)

    assert resultado is PDF


def test_el_doble_recibe_la_url_y_el_cliente_inyectado() -> None:
    """El adaptador delega en el descargador con la URL y el cliente."""
    doble = DobleDescargador(PDF)
    with _cliente(_responder_pdf) as cliente:
        AdaptadorDescarga(descargador=doble, cliente=cliente).descargar(URL)

    assert doble.llamadas == [(URL, cliente)]


# --- Fallos controlados (ALT-003) -------------------------------------------


def test_un_error_http_devuelve_un_error_controlado_con_el_mensaje() -> None:
    """Un 404 del PDF se propaga como error propio con su mensaje (ALT-003)."""

    def responder_404(solicitud: httpx.Request) -> httpx.Response:
        return httpx.Response(404, request=solicitud)

    resultado = _descargar_con(responder_404)

    assert isinstance(resultado, ErrorDescargaIntegridad)
    assert not isinstance(resultado, bytes)
    assert "404" in resultado.mensaje
    assert resultado.motivo == resultado.mensaje


def test_el_tiempo_de_espera_agotado_devuelve_un_error_controlado() -> None:
    """Un timeout se propaga como error propio con su mensaje (ALT-003)."""

    def agotar_timeout(solicitud: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("agotado", request=solicitud)

    resultado = _descargar_con(agotar_timeout)

    assert isinstance(resultado, ErrorDescargaIntegridad)
    assert "tiempo de espera agotado" in resultado.mensaje


def test_el_error_de_conexion_devuelve_un_error_controlado() -> None:
    """Un fallo de conexión se propaga como error propio (ALT-003)."""

    def fallar_conexion(solicitud: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin conexion", request=solicitud)

    resultado = _descargar_con(fallar_conexion)

    assert isinstance(resultado, ErrorDescargaIntegridad)
    assert "conexión" in resultado.mensaje


def test_http_timeout_y_conexion_son_errores_controlados_distinguibles() -> None:
    """Los tres fallos son del mismo tipo propio y cada uno con su mensaje."""

    def responder_503(solicitud: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=solicitud)

    def agotar_timeout(solicitud: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("agotado", request=solicitud)

    def fallar_conexion(solicitud: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin conexion", request=solicitud)

    resultados = [
        _descargar_con(responder_503),
        _descargar_con(agotar_timeout),
        _descargar_con(fallar_conexion),
    ]

    assert all(
        isinstance(resultado, ErrorDescargaIntegridad) for resultado in resultados
    )
    assert all(not isinstance(resultado, bytes) for resultado in resultados)
    mensajes = [resultado.mensaje for resultado in resultados]
    assert len(set(mensajes)) == 3


def test_un_doble_que_devuelve_error_descarga_se_convierte_sin_excepcion() -> None:
    """Un `ErrorDescarga` del doble se convierte en el error propio."""
    doble = DobleDescargador(ErrorDescarga("Error de descarga: HTTP 500."))

    resultado = AdaptadorDescarga(descargador=doble).descargar(URL)

    assert isinstance(resultado, ErrorDescargaIntegridad)
    assert resultado.mensaje == "Error de descarga: HTTP 500."


# --- Sin peticiones a la API ni fichas del buscador (SUP-005) ---------------


def test_solo_pide_el_pdf_y_nunca_el_endpoint_parse() -> None:
    """Invoca el descargador en proceso: no llama a `GET /parse` (SUP-005)."""
    solicitudes: list[httpx.Request] = []

    def responder(solicitud: httpx.Request) -> httpx.Response:
        solicitudes.append(solicitud)
        return _responder_pdf(solicitud)

    resultado = _descargar_con(responder)

    assert resultado == PDF
    assert len(solicitudes) == 1
    assert solicitudes[0].method == "GET"
    assert str(solicitudes[0].url) == URL
    assert not any("/parse" in str(solicitud.url) for solicitud in solicitudes)
    assert not any(
        "localhost" in str(solicitud.url) or "127.0.0.1" in str(solicitud.url)
        for solicitud in solicitudes
    )


def test_no_descarga_fichas_del_buscador() -> None:
    """Solo se pide la URL del PDF: ninguna ficha ni listado del buscador."""
    solicitudes: list[str] = []

    def responder(solicitud: httpx.Request) -> httpx.Response:
        solicitudes.append(str(solicitud.url))
        return _responder_pdf(solicitud)

    _descargar_con(responder)

    assert solicitudes == [URL]
    assert not any(
        "/oferta" in url or "/buscador" in url for url in solicitudes
    )


# --- Sin escritura en disco ni cambios en los módulos existentes ------------


def test_no_escribe_ningun_fichero_en_disco(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El adaptador devuelve los bytes sin guardar nada: escribe `pdf-store`."""
    monkeypatch.chdir(tmp_path)

    resultado = _descargar_con(_responder_pdf)

    assert resultado == PDF
    assert list(tmp_path.rglob("*")) == []


def test_no_modifica_los_modulos_de_descarga_ni_de_ensamblado() -> None:
    """Usar el adaptador solo lee el descargador y el ensamblador existentes."""
    protegidos = [
        REPO_ROOT / "source" / "api" / "downloader.py",
        REPO_ROOT / "source" / "api" / "assembler.py",
    ]
    antes = [ruta.stat().st_mtime_ns for ruta in protegidos]

    assert _descargar_con(_responder_pdf) == PDF

    assert [ruta.stat().st_mtime_ns for ruta in protegidos] == antes
