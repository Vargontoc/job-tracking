"""Pruebas unitarias del adaptador del estado del buscador."""

from unittest.mock import MagicMock

import httpx
import pytest

from source.api.historico.buscador_client import (
    ClienteEstadoBuscador,
    EstadoBuscador,
    ErrorEstadoBuscador,
)


def _respuesta_ok(datos: dict, status_code: int = 200) -> MagicMock:
    """Crea un mock de respuesta httpx con los datos indicados."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = datos
    resp.raise_for_status.return_value = None
    return resp


def _cuerpo_status(
    total_listado: int = 93,
    timestamp: str = "2026-11-22T10:00:00",
    comunidad: str = "Cantabria",
    error_global: str = "",
    errores_por_oferta: list | None = None,
) -> dict:
    """Construye el cuerpo de ``GET /buscador/status`` con la estructura real."""
    return {
        "in_progress": False,
        "progreso": None,
        "ultima_pasada": {
            "timestamp": timestamp,
            "comunidad": comunidad,
            "total_listado": total_listado,
            "error_global": error_global,
            "errores_por_oferta": errores_por_oferta or [],
            "ofertas_nuevas": [],
        },
    }


# --- Caso exitoso ---


def test_caso_exitoso_devuelve_estado_con_campos_reales() -> None:
    """Con respuesta válida se devuelven total, timestamp, comunidad y errores."""
    errores = [{"codigo": "050010000001", "mensaje": "timeout"}]
    cliente_http = MagicMock(spec=httpx.Client)
    cliente_http.get.return_value = _respuesta_ok(
        _cuerpo_status(
            total_listado=93,
            timestamp="2026-11-22T10:00:00",
            comunidad="Cantabria",
            errores_por_oferta=errores,
        )
    )

    adapter = ClienteEstadoBuscador("http://localhost:8000", cliente_http=cliente_http)
    resultado = adapter.consultar_estado()

    assert isinstance(resultado, EstadoBuscador)
    assert resultado.total_ofertas == 93
    assert resultado.timestamp == "2026-11-22T10:00:00"
    assert resultado.comunidad == "Cantabria"
    assert resultado.errores == ["050010000001"]


def test_url_solicitada_es_buscador_status() -> None:
    """La URL solicitada es la URL base configurada más ``/buscador/status``."""
    cliente_http = MagicMock(spec=httpx.Client)
    cliente_http.get.return_value = _respuesta_ok(_cuerpo_status())

    adapter = ClienteEstadoBuscador("http://localhost:8000", cliente_http=cliente_http)
    adapter.consultar_estado()

    cliente_http.get.assert_called_once_with("http://localhost:8000/buscador/status")


def test_url_base_con_barra_final_se_normaliza() -> None:
    """Una URL base con barra final no produce doble barra."""
    cliente_http = MagicMock(spec=httpx.Client)
    cliente_http.get.return_value = _respuesta_ok(_cuerpo_status())

    adapter = ClienteEstadoBuscador("http://localhost:8000/", cliente_http=cliente_http)
    adapter.consultar_estado()

    cliente_http.get.assert_called_once_with("http://localhost:8000/buscador/status")


def test_sin_errores_por_oferta_la_lista_va_vacia() -> None:
    """Cuando ``errores_por_oferta`` está vacío, ``EstadoBuscador.errores`` es ``[]``."""
    cliente_http = MagicMock(spec=httpx.Client)
    cliente_http.get.return_value = _respuesta_ok(_cuerpo_status())

    adapter = ClienteEstadoBuscador("http://localhost:8000", cliente_http=cliente_http)
    resultado = adapter.consultar_estado()

    assert isinstance(resultado, EstadoBuscador)
    assert resultado.errores == []


def test_codigos_con_error_se_pueden_consultar_por_codigo() -> None:
    """El conjunto de códigos con error se puede consultar por código."""
    errores = [
        {"codigo": "050010000001", "mensaje": "timeout"},
        {"codigo": "050010000002", "mensaje": "parse error"},
    ]
    cliente_http = MagicMock(spec=httpx.Client)
    cliente_http.get.return_value = _respuesta_ok(
        _cuerpo_status(errores_por_oferta=errores)
    )

    adapter = ClienteEstadoBuscador("http://localhost:8000", cliente_http=cliente_http)
    resultado = adapter.consultar_estado()

    assert isinstance(resultado, EstadoBuscador)
    assert "050010000001" in resultado.errores
    assert "050010000002" in resultado.errores
    assert "050010000099" not in resultado.errores


# --- Casos de error ---


def test_ultima_pasada_nula_devuelve_error_distinguible() -> None:
    """Con ``ultima_pasada`` nula se devuelve ``ErrorEstadoBuscador``."""
    cliente_http = MagicMock(spec=httpx.Client)
    cliente_http.get.return_value = _respuesta_ok(
        {"in_progress": False, "progreso": None, "ultima_pasada": None}
    )

    adapter = ClienteEstadoBuscador("http://localhost:8000", cliente_http=cliente_http)
    resultado = adapter.consultar_estado()

    assert isinstance(resultado, ErrorEstadoBuscador)
    assert "nula" in resultado.motivo.lower()


def test_error_global_no_vacio_devuelve_error_sin_excepcion() -> None:
    """Con ``error_global`` no vacío se devuelve ``ErrorEstadoBuscador`` sin excepción."""
    cliente_http = MagicMock(spec=httpx.Client)
    cliente_http.get.return_value = _respuesta_ok(
        _cuerpo_status(error_global="Ya hay una pasada en curso")
    )

    adapter = ClienteEstadoBuscador("http://localhost:8000", cliente_http=cliente_http)
    resultado = adapter.consultar_estado()

    assert isinstance(resultado, ErrorEstadoBuscador)
    assert "pasada en curso" in resultado.motivo


def test_error_http_devuelve_error_controlado() -> None:
    """Con un error HTTP se devuelve ``ErrorEstadoBuscador`` sin excepción."""
    cliente_http = MagicMock(spec=httpx.Client)
    respuesta_error = MagicMock(spec=httpx.Response)
    respuesta_error.status_code = 503
    respuesta_error.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Service Unavailable",
        request=MagicMock(),
        response=respuesta_error,
    )
    cliente_http.get.return_value = respuesta_error

    adapter = ClienteEstadoBuscador("http://localhost:8000", cliente_http=cliente_http)
    resultado = adapter.consultar_estado()

    assert isinstance(resultado, ErrorEstadoBuscador)
    assert "503" in resultado.motivo


def test_fallo_de_red_devuelve_error_controlado() -> None:
    """Con un fallo de red se devuelve ``ErrorEstadoBuscador`` sin excepción."""
    cliente_http = MagicMock(spec=httpx.Client)
    cliente_http.get.side_effect = httpx.ConnectError("Connection refused")

    adapter = ClienteEstadoBuscador("http://localhost:8000", cliente_http=cliente_http)
    resultado = adapter.consultar_estado()

    assert isinstance(resultado, ErrorEstadoBuscador)
    assert resultado.motivo  # no vacío


def test_solo_emite_peticiones_a_buscador_status() -> None:
    """El cliente solo emite peticiones a ``/buscador/status``."""
    cliente_http = MagicMock(spec=httpx.Client)
    cliente_http.get.return_value = _respuesta_ok(_cuerpo_status())

    adapter = ClienteEstadoBuscador("http://localhost:8000", cliente_http=cliente_http)
    adapter.consultar_estado()
    adapter.consultar_estado()

    assert cliente_http.get.call_count == 2
    for llamada in cliente_http.get.call_args_list:
        assert llamada.args[0].endswith("/buscador/status")
