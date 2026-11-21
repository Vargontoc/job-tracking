"""Pruebas del cliente HTTP de GET /buscador/status."""

from pathlib import Path

import httpx

from source.api.persistencia.client import (
    ClienteBuscador,
    EstadoBuscador,
    ResultadoConsultaEstado,
    UltimaPasada,
)


# ---------------------------------------------------------------------------
# Fijtures auxiliares
# ---------------------------------------------------------------------------

CUERPO_STATUS_COMPLETO = {
    "in_progress": False,
    "progreso": None,
    "ultima_pasada": {
        "timestamp": "2026-01-21T10:30:00",
        "comunidad": "Cantabria",
        "total_listado": 123,
        "error_global": "",
        "errores_por_oferta": [],
        "ofertas_nuevas": [
            {
                "numero_oferta": "061234567890",
                "ocupacion": "Desarrollador",
                "municipio": "Santander",
                "provincia": "Cantabria",
                "fecha_inicio_difusion": "01/01/2026",
                "fecha_fin_difusion": "31/03/2026",
                "texto_libre": "Descripción",
                "contacto": "contacto@example.com",
                "comunidad": "Cantabria",
                "sector": "",
                "nivel": "",
                "contrato": "",
            }
        ],
    },
}


def _cliente_de_prueba(
    respuesta: httpx.Response,
) -> tuple[httpx.Client, list[httpx.Request]]:
    """Devuelve un ``httpx.Client`` con MockTransport y la lista de peticiones."""
    peticiones: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        peticiones.append(request)
        return respuesta

    cliente = httpx.Client(transport=httpx.MockTransport(_handler))
    return cliente, peticiones


# ---------------------------------------------------------------------------
# Caso feliz: cuerpo real de GET /buscador/status
# ---------------------------------------------------------------------------


def test_consultar_estado_devuelve_estructura_completa() -> None:
    """Con el cuerpo real, el cliente devuelve in_progress, progreso y
    ultima_pasada con sus seis campos."""
    respuesta = httpx.Response(200, json=CUERPO_STATUS_COMPLETO)
    cliente, _ = _cliente_de_prueba(respuesta)

    buscador = ClienteBuscador("http://localhost:8000", cliente=cliente)
    resultado = buscador.consultar_estado()

    assert resultado.error == ""
    assert resultado.estado is not None

    estado = resultado.estado
    assert estado.in_progress is False
    assert estado.progreso is None

    ultima = estado.ultima_pasada
    assert ultima is not None
    assert isinstance(ultima, UltimaPasada)
    assert ultima.timestamp == "2026-01-21T10:30:00"
    assert ultima.comunidad == "Cantabria"
    assert ultima.total_listado == 123
    assert ultima.error_global == ""
    assert ultima.errores_por_oferta == []
    assert len(ultima.ofertas_nuevas) == 1
    assert ultima.ofertas_nuevas[0]["numero_oferta"] == "061234567890"


def test_consultar_estado_con_progreso_en_curso() -> None:
    """Cuando hay una pasada en curso, progreso se devuelve como dict."""
    cuerpo = {
        "in_progress": True,
        "progreso": {
            "hora_inicio": "2026-01-21T11:00:00",
            "codigos_procesados": 42,
            "total_codigos": 103,
        },
        "ultima_pasada": None,
    }
    respuesta = httpx.Response(200, json=cuerpo)
    cliente, _ = _cliente_de_prueba(respuesta)

    buscador = ClienteBuscador("http://localhost:8000", cliente=cliente)
    resultado = buscador.consultar_estado()

    assert resultado.error == ""
    assert resultado.estado is not None
    assert resultado.estado.in_progress is True
    assert resultado.estado.progreso == {
        "hora_inicio": "2026-01-21T11:00:00",
        "codigos_procesados": 42,
        "total_codigos": 103,
    }


# ---------------------------------------------------------------------------
# URL solicitada
# ---------------------------------------------------------------------------


def test_la_url_solicitada_es_url_base_mas_buscador_status() -> None:
    """La URL solicitada es la URL base configurada más /buscador/status."""
    respuesta = httpx.Response(200, json=CUERPO_STATUS_COMPLETO)
    cliente, peticiones = _cliente_de_prueba(respuesta)

    buscador = ClienteBuscador("http://localhost:8000", cliente=cliente)
    buscador.consultar_estado()

    assert len(peticiones) == 1
    assert str(peticiones[0].url) == "http://localhost:8000/buscador/status"


def test_la_url_se_construye_correctamente_con_barra_final() -> None:
    """La URL base con barra final se normaliza correctamente."""
    respuesta = httpx.Response(200, json=CUERPO_STATUS_COMPLETO)
    cliente, peticiones = _cliente_de_prueba(respuesta)

    buscador = ClienteBuscador("http://localhost:8000/", cliente=cliente)
    buscador.consultar_estado()

    assert str(peticiones[0].url) == "http://localhost:8000/buscador/status"


# ---------------------------------------------------------------------------
# ultima_pasada nula
# ---------------------------------------------------------------------------


def test_ultima_pasada_nula_se_comunica_de_forma_distinguible() -> None:
    """Con ultima_pasada nula, el cliente lo comunica de forma distinguible."""
    cuerpo = {
        "in_progress": False,
        "progreso": None,
        "ultima_pasada": None,
    }
    respuesta = httpx.Response(200, json=cuerpo)
    cliente, _ = _cliente_de_prueba(respuesta)

    buscador = ClienteBuscador("http://localhost:8000", cliente=cliente)
    resultado = buscador.consultar_estado()

    assert resultado.error == ""
    assert resultado.estado is not None
    # ultima_pasada es None (distinguible de un estado con pasada)
    assert resultado.estado.ultima_pasada is None


# ---------------------------------------------------------------------------
# error_global no vacío
# ---------------------------------------------------------------------------


def test_error_global_no_vacio_se_comunica_sin_excepcion() -> None:
    """Con error_global no vacío, el cliente lo comunica sin lanzar excepción."""
    cuerpo = {
        "in_progress": False,
        "progreso": None,
        "ultima_pasada": {
            "timestamp": "2026-01-21T10:30:00",
            "comunidad": "Cantabria",
            "total_listado": 0,
            "error_global": "El portal no responde",
            "errores_por_oferta": [],
            "ofertas_nuevas": [],
        },
    }
    respuesta = httpx.Response(200, json=cuerpo)
    cliente, _ = _cliente_de_prueba(respuesta)

    buscador = ClienteBuscador("http://localhost:8000", cliente=cliente)
    # No debe lanzar excepción
    resultado = buscador.consultar_estado()

    assert resultado.error == ""
    assert resultado.estado is not None
    ultima = resultado.estado.ultima_pasada
    assert ultima is not None
    assert ultima.error_global == "El portal no responde"
    assert ultima.total_listado == 0


# ---------------------------------------------------------------------------
# Errores HTTP y de red
# ---------------------------------------------------------------------------


def test_error_http_devuelve_error_controlado() -> None:
    """Con un error HTTP, el cliente devuelve un error controlado."""
    respuesta = httpx.Response(500, text="Internal Server Error")
    cliente, _ = _cliente_de_prueba(respuesta)

    buscador = ClienteBuscador("http://localhost:8000", cliente=cliente)
    resultado = buscador.consultar_estado()

    assert resultado.estado is None
    assert resultado.error != ""
    assert "500" in resultado.error


def test_error_http_404_devuelve_error_controlado() -> None:
    """Con un 404, el cliente devuelve un error controlado."""
    respuesta = httpx.Response(404, text="Not Found")
    cliente, _ = _cliente_de_prueba(respuesta)

    buscador = ClienteBuscador("http://localhost:8000", cliente=cliente)
    resultado = buscador.consultar_estado()

    assert resultado.estado is None
    assert resultado.error != ""
    assert "404" in resultado.error


def test_fallo_de_red_devuelve_error_controlado() -> None:
    """Con un fallo de red, el cliente devuelve un error controlado."""

    def _handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    cliente = httpx.Client(transport=httpx.MockTransport(_handler))

    buscador = ClienteBuscador("http://localhost:8000", cliente=cliente)
    resultado = buscador.consultar_estado()

    assert resultado.estado is None
    assert resultado.error != ""
    assert "Error de red" in resultado.error


# ---------------------------------------------------------------------------
# Solo se consulta /buscador/status
# ---------------------------------------------------------------------------


def test_solo_se_emite_una_peticion_a_buscador_status() -> None:
    """El cliente no solicita ningún otro endpoint: solo /buscador/status."""
    respuesta = httpx.Response(200, json=CUERPO_STATUS_COMPLETO)
    cliente, peticiones = _cliente_de_prueba(respuesta)

    buscador = ClienteBuscador("http://localhost:8000", cliente=cliente)
    buscador.consultar_estado()

    assert len(peticiones) == 1
    assert peticiones[0].url.path == "/buscador/status"
    assert peticiones[0].method == "GET"


# ---------------------------------------------------------------------------
# El cliente no escribe en BD ni en data/
# ---------------------------------------------------------------------------


def test_el_cliente_no_escribe_en_data(
    tmp_path: Path,
) -> None:
    """El cliente no escribe en la base de datos ni modifica ningún
    fichero de data/."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    fichero_control = data_dir / "control.txt"
    fichero_control.write_text("original")

    respuesta = httpx.Response(200, json=CUERPO_STATUS_COMPLETO)
    cliente, _ = _cliente_de_prueba(respuesta)

    buscador = ClienteBuscador("http://localhost:8000", cliente=cliente)
    buscador.consultar_estado()

    # El fichero de control no se ha modificado
    assert fichero_control.read_text() == "original"
    # No se han creado ficheros nuevos en data/
    assert list(data_dir.iterdir()) == [fichero_control]


# ---------------------------------------------------------------------------
# ResultadoConsultaEstado y tipos
# ---------------------------------------------------------------------------


def test_resultado_consulta_estado_por_defecto() -> None:
    """ResultadoConsultaEstado por defecto tiene estado None y error vacío."""
    resultado = ResultadoConsultaEstado()
    assert resultado.estado is None
    assert resultado.error == ""


def test_estado_buscador_por_defecto() -> None:
    """EstadoBuscador por defecto tiene valores coherentes."""
    estado = EstadoBuscador()
    assert estado.in_progress is False
    assert estado.progreso is None
    assert estado.ultima_pasada is None


def test_ultima_pasada_por_defecto() -> None:
    """UltimaPasada por defecto tiene valores coherentes."""
    ultima = UltimaPasada()
    assert ultima.timestamp == ""
    assert ultima.comunidad == ""
    assert ultima.total_listado == 0
    assert ultima.error_global == ""
    assert ultima.errores_por_oferta == []
    assert ultima.ofertas_nuevas == []
