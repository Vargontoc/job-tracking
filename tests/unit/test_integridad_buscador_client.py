"""Pruebas del adaptador del estado del buscador (TASK-008).

Cubren `source/api/integridad/buscador_client.py`: `ClienteEstadoBuscador`
consulta **solo** `GET /buscador/status` (la URL base configurada más
`/buscador/status`), normaliza el cuerpo real publicado por `api-buscador`
(`in_progress`, `progreso` y `ultima_pasada` con `timestamp`, `comunidad`,
`total_listado`, `error_global` y `errores_por_oferta`, SUP-006) y distingue
sin lanzar excepción los estados no utilizables: error HTTP o de red
(ALT-005), `ultima_pasada` nula o sin `total_listado` (ALT-005) y
`error_global` no vacío (ALT-006). El cliente es de solo lectura: no lanza
pasadas, no descarga fichas y no modifica `source/api/buscador/` (SUP-004).
"""

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from source.api.integridad.buscador_client import (
    ClienteEstadoBuscador,
    EstadoBuscador,
    EstadoBuscadorNoUtilizable,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
URL_BASE = "http://localhost:8000"
URL_ESTADO = f"{URL_BASE}/buscador/status"

# Cuerpo real de `GET /buscador/status` (source/api/buscador/routes.py).
ULTIMA_PASADA = {
    "timestamp": "2026-11-23T01:00:04",
    "comunidad": "Cantabria",
    "total_listado": 93,
    "error_global": "",
    "errores_por_oferta": [
        {"codigo": "000000000037", "mensaje": "ficha no accesible"}
    ],
    "ofertas_nuevas": [],
}

CUERPO_REAL = {
    "in_progress": False,
    "progreso": None,
    "ultima_pasada": ULTIMA_PASADA,
}

Respondedor = Callable[[httpx.Request], httpx.Response]


def _responder(cuerpo: object) -> Respondedor:
    """Respondedor de `MockTransport` con el cuerpo JSON indicado."""

    def responder(solicitud: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=cuerpo, request=solicitud)

    return responder


def _consultar_con(
    responder: Respondedor,
    url_base: str = URL_BASE,
) -> EstadoBuscador | EstadoBuscadorNoUtilizable:
    """Consulta el estado a través del cliente con un transporte simulado."""
    transporte = httpx.MockTransport(responder)
    with httpx.Client(transport=transporte) as cliente:
        return ClienteEstadoBuscador(url_base, cliente=cliente).consultar_estado()


def _consultar_cuerpo(cuerpo: object) -> EstadoBuscador | EstadoBuscadorNoUtilizable:
    """Consulta el estado con el cuerpo JSON indicado."""
    return _consultar_con(_responder(cuerpo))


# --- Estado utilizable (SUP-006) --------------------------------------------


def test_cuerpo_real_devuelve_el_estado_publicado() -> None:
    """El cuerpo real se normaliza con sus campos y expone `total_listado`."""
    estado = _consultar_con(_responder(CUERPO_REAL))

    assert isinstance(estado, EstadoBuscador)
    assert estado.in_progress is False
    assert estado.progreso is None
    assert estado.ultima_pasada.timestamp == "2026-11-23T01:00:04"
    assert estado.ultima_pasada.comunidad == "Cantabria"
    assert estado.ultima_pasada.total_listado == 93
    assert estado.ultima_pasada.error_global == ""
    assert estado.ultima_pasada.errores_por_oferta == [
        {"codigo": "000000000037", "mensaje": "ficha no accesible"}
    ]
    assert estado.total_listado == 93


def test_una_pasada_en_curso_conserva_el_progreso() -> None:
    """Si hay pasada en curso, `in_progress` y `progreso` llegan tal cual."""
    progreso = {
        "hora_inicio": "2026-11-23T01:00:04",
        "codigos_procesados": 10,
        "total_codigos": 75,
    }
    cuerpo = {
        "in_progress": True,
        "progreso": progreso,
        "ultima_pasada": ULTIMA_PASADA,
    }

    estado = _consultar_con(_responder(cuerpo))

    assert isinstance(estado, EstadoBuscador)
    assert estado.in_progress is True
    assert estado.progreso == progreso
    assert estado.total_listado == 93


# --- URL solicitada ---------------------------------------------------------


def test_se_solicita_exactamente_la_url_base_mas_buscador_status() -> None:
    """La única petición va a `<url_base>/buscador/status` con GET."""
    solicitudes: list[httpx.Request] = []

    def responder(solicitud: httpx.Request) -> httpx.Response:
        solicitudes.append(solicitud)
        return httpx.Response(200, json=CUERPO_REAL, request=solicitud)

    _consultar_con(responder)

    assert len(solicitudes) == 1
    assert solicitudes[0].method == "GET"
    assert str(solicitudes[0].url) == URL_ESTADO


def test_la_url_base_con_barra_final_no_duplica_la_barra() -> None:
    """Una `url_base` terminada en `/` no produce `//buscador/status`."""
    solicitudes: list[str] = []

    def responder(solicitud: httpx.Request) -> httpx.Response:
        solicitudes.append(str(solicitud.url))
        return httpx.Response(200, json=CUERPO_REAL, request=solicitud)

    _consultar_con(responder, url_base=f"{URL_BASE}/")

    assert solicitudes == [URL_ESTADO]


# --- Estados no utilizables (ALT-005, ALT-006) ------------------------------


def test_ultima_pasada_nula_no_es_utilizable() -> None:
    """Sin `ultima_pasada` no hay recuento con el que comparar (ALT-005)."""
    estado = _consultar_cuerpo(
        {"in_progress": False, "progreso": None, "ultima_pasada": None}
    )

    assert isinstance(estado, EstadoBuscadorNoUtilizable)
    assert not isinstance(estado, EstadoBuscador)
    assert "ultima_pasada" in estado.motivo


def test_ultima_pasada_sin_total_listado_no_es_utilizable() -> None:
    """Una `ultima_pasada` sin `total_listado` no es utilizable (ALT-005)."""
    pasada_sin_total = {
        "timestamp": "2026-11-23T01:00:04",
        "comunidad": "Cantabria",
        "error_global": "",
        "errores_por_oferta": [],
    }

    estado = _consultar_cuerpo(
        {"in_progress": False, "progreso": None, "ultima_pasada": pasada_sin_total}
    )

    assert isinstance(estado, EstadoBuscadorNoUtilizable)
    assert "total_listado" in estado.motivo


def test_error_global_no_vacio_no_es_utilizable_sin_excepcion() -> None:
    """Un `error_global` no vacío se comunica como estado no utilizable."""
    pasada_con_error = dict(ULTIMA_PASADA, error_global="el portal no respondió")

    estado = _consultar_cuerpo(
        {"in_progress": False, "progreso": None, "ultima_pasada": pasada_con_error}
    )

    assert isinstance(estado, EstadoBuscadorNoUtilizable)
    assert "error_global" in estado.motivo
    assert "el portal no respondió" in estado.motivo


def test_un_error_http_devuelve_un_estado_no_utilizable() -> None:
    """Un 503 del endpoint se comunica sin lanzar excepción (ALT-005)."""

    def responder(solicitud: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=solicitud)

    estado = _consultar_con(responder)

    assert isinstance(estado, EstadoBuscadorNoUtilizable)
    assert "503" in estado.motivo


def test_un_fallo_de_conexion_devuelve_un_estado_no_utilizable() -> None:
    """Un fallo de red se comunica sin lanzar excepción (ALT-005)."""

    def fallar_conexion(solicitud: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin conexion", request=solicitud)

    estado = _consultar_con(fallar_conexion)

    assert isinstance(estado, EstadoBuscadorNoUtilizable)
    assert "red" in estado.motivo


def test_un_tiempo_de_espera_agotado_devuelve_un_estado_no_utilizable() -> None:
    """Un timeout se comunica sin lanzar excepción (ALT-005)."""

    def agotar_timeout(solicitud: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("agotado", request=solicitud)

    estado = _consultar_con(agotar_timeout)

    assert isinstance(estado, EstadoBuscadorNoUtilizable)
    assert "red" in estado.motivo


def test_una_respuesta_sin_json_valido_no_lanza_excepcion() -> None:
    """Una respuesta que no es JSON se comunica como no utilizable."""

    def responder(solicitud: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>no es JSON</html>", request=solicitud)

    estado = _consultar_con(responder)

    assert isinstance(estado, EstadoBuscadorNoUtilizable)
    assert "JSON" in estado.motivo


def test_los_estados_no_utilizables_identifican_su_causa() -> None:
    """Cada causa produce un motivo distinto, sin lanzar excepción."""

    def fallar_conexion(solicitud: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin conexion", request=solicitud)

    def responder_503(solicitud: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=solicitud)

    pasada_sin_total = {
        "timestamp": "2026-11-23T01:00:04",
        "comunidad": "Cantabria",
        "error_global": "",
        "errores_por_oferta": [],
    }
    pasada_con_error = dict(ULTIMA_PASADA, error_global="el portal no respondió")

    resultados = [
        _consultar_cuerpo(
            {"in_progress": False, "progreso": None, "ultima_pasada": None}
        ),
        _consultar_cuerpo(
            {
                "in_progress": False,
                "progreso": None,
                "ultima_pasada": pasada_sin_total,
            }
        ),
        _consultar_cuerpo(
            {
                "in_progress": False,
                "progreso": None,
                "ultima_pasada": pasada_con_error,
            }
        ),
        _consultar_con(responder_503),
        _consultar_con(fallar_conexion),
    ]

    assert all(
        isinstance(resultado, EstadoBuscadorNoUtilizable)
        for resultado in resultados
    )
    motivos = [resultado.motivo for resultado in resultados]
    assert len(set(motivos)) == len(motivos)


# --- Solo el endpoint de estado (SUP-004) -----------------------------------


def test_solo_emite_peticiones_al_endpoint_de_estado() -> None:
    """No solicita otro endpoint del buscador ni lanza una pasada (SUP-004)."""
    solicitudes: list[str] = []

    def responder(solicitud: httpx.Request) -> httpx.Response:
        solicitudes.append(str(solicitud.url))
        return httpx.Response(200, json=CUERPO_REAL, request=solicitud)

    _consultar_con(responder)

    assert solicitudes == [URL_ESTADO]
    assert not any("/buscador/run" in url for url in solicitudes)
    assert not any("/parse" in url or "/oferta" in url for url in solicitudes)


def test_no_modifica_el_modulo_del_buscador() -> None:
    """Consultar el estado solo lee: no toca `source/api/buscador/` (SUP-004)."""
    protegidos = [
        REPO_ROOT / "source" / "api" / "buscador" / "routes.py",
        REPO_ROOT / "source" / "api" / "buscador" / "models.py",
    ]
    antes = [ruta.stat().st_mtime_ns for ruta in protegidos]

    assert isinstance(_consultar_con(_responder(CUERPO_REAL)), EstadoBuscador)

    assert [ruta.stat().st_mtime_ns for ruta in protegidos] == antes


# --- Ciclo de vida del cliente ----------------------------------------------


class ClienteFalso:
    """Doble mínimo de `httpx.Client` que anota peticiones y cierre."""

    def __init__(self, respuesta: httpx.Response) -> None:
        self._respuesta = respuesta
        self.peticiones: list[str] = []
        self.cerrado = False

    def get(self, url: str) -> httpx.Response:
        """Devuelve la respuesta preparada y anota la URL solicitada."""
        self.peticiones.append(url)
        return self._respuesta

    def close(self) -> None:
        """Anota que el cliente se ha cerrado."""
        self.cerrado = True


def test_sin_cliente_inyectado_crea_uno_y_lo_cierra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si el cliente se crea dentro, se cierra al terminar la consulta."""
    respuesta = httpx.Response(
        200,
        json=CUERPO_REAL,
        request=httpx.Request("GET", URL_ESTADO),
    )
    falso = ClienteFalso(respuesta)
    monkeypatch.setattr(httpx, "Client", lambda: falso)

    estado = ClienteEstadoBuscador(URL_BASE).consultar_estado()

    assert isinstance(estado, EstadoBuscador)
    assert falso.peticiones == [URL_ESTADO]
    assert falso.cerrado is True


def test_un_cliente_inyectado_no_se_cierra() -> None:
    """El cliente de las pruebas sigue abierto tras consultar el estado."""
    with httpx.Client(transport=httpx.MockTransport(_responder(CUERPO_REAL))) as cliente:
        ClienteEstadoBuscador(URL_BASE, cliente=cliente).consultar_estado()

        # Si el adaptador lo hubiese cerrado, esta petición fallaría.
        assert cliente.get(URL_ESTADO).status_code == 200
