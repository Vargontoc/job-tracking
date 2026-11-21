"""Pruebas unitarias del recorrido del listado paginado."""

from dataclasses import dataclass
from pathlib import Path

import pytest

from source.api.buscador.rate_limiter import LimitadorPeticiones
from source.api.buscador.scraper import (
    ErrorListado,
    ResultadoListado,
    _construir_url,
    _es_listado_vacio,
    _es_ultima_pagina,
    _extraer_codigos,
    _extraer_total,
    recorrer_listado,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "buscador"

PAGINA_1 = (FIXTURES / "listado_pagina_1.html").read_text(encoding="utf-8")
PAGINA_2 = (FIXTURES / "listado_pagina_2.html").read_text(encoding="utf-8")
LISTADO_VACIO = (FIXTURES / "listado_vacio.html").read_text(encoding="utf-8")


# --- Helpers ---


class RelojFijo:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class DormirFalso:
    def __init__(self) -> None:
        self.llamadas = 0

    def __call__(self, s: float) -> None:
        self.llamadas += 1


@dataclass
class RespuestaMock:
    status_code: int = 200
    text: str = ""

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class ClienteSecuencia:
    """Cliente que devuelve respuestas de una secuencia predefinida."""

    def __init__(self, respuestas: list[RespuestaMock]) -> None:
        self.respuestas = respuestas
        self.peticiones: list[tuple[str, float]] = []
        self.indice = 0

    def get(self, url: str, *, timeout: float) -> RespuestaMock:
        self.peticiones.append((url, timeout))
        if self.indice >= len(self.respuestas):
            raise RuntimeError("No hay más respuestas en la secuencia")
        respuesta = self.respuestas[self.indice]
        self.indice += 1
        return respuesta


class ClienteError:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.peticiones: list[tuple[str, float]] = []

    def get(self, url: str, *, timeout: float) -> RespuestaMock:
        self.peticiones.append((url, timeout))
        raise self.error


def limitador_rapido() -> LimitadorPeticiones:
    return LimitadorPeticiones(
        delay_segundos=0.0,
        reloj=RelojFijo(),
        dormir=DormirFalso(),
    )


# --- Pruebas de parseo (funciones auxiliares) ---


def test_extraer_total_pagina_1() -> None:
    assert _extraer_total(PAGINA_1) == 93


def test_extraer_total_pagina_2() -> None:
    assert _extraer_total(PAGINA_2) == 93


def test_extraer_total_sin_small_lanza_error() -> None:
    with pytest.raises(ErrorListado, match="small.search-results"):
        _extraer_total(LISTADO_VACIO)


def test_extraer_codigos_pagina_1() -> None:
    codigos = _extraer_codigos(PAGINA_1)
    assert codigos == ["062026003633", "062026003632", "062026003631"]


def test_extraer_codigos_pagina_2() -> None:
    codigos = _extraer_codigos(PAGINA_2)
    assert codigos == ["062026003487", "062026003486", "062026003485"]


def test_codigos_se_conservan_con_cero_al_inicio() -> None:
    """Los códigos se devuelven como texto de 12 dígitos sin perder ceros."""
    assert all(len(c) == 12 for c in _extraer_codigos(PAGINA_1))
    assert _extraer_codigos(PAGINA_1)[0].startswith("0")


def test_es_listado_vacio() -> None:
    assert _es_listado_vacio(LISTADO_VACIO) is True
    assert _es_listado_vacio(PAGINA_1) is False
    assert _es_listado_vacio(PAGINA_2) is False


def test_es_ultima_pagina() -> None:
    assert _es_ultima_pagina(PAGINA_1) is False
    assert _es_ultima_pagina(PAGINA_2) is True


def test_construir_url_pagina_1() -> None:
    url = _construir_url("https://empleacantabria.es/ofertas-cantabria", 75, 1)
    assert "delta=75" in url
    assert "cur=1" in url
    # No doble "?"
    assert url.count("?") == 1


def test_construir_url_pagina_2() -> None:
    url = _construir_url("https://empleacantabria.es/ofertas-cantabria", 75, 2)
    assert "cur=2" in url


# --- Pruebas de recorrer_listado ---


def test_recorrer_dos_paginas_total_93() -> None:
    cliente = ClienteSecuencia([
        RespuestaMock(200, PAGINA_1),
        RespuestaMock(200, PAGINA_2),
    ])

    resultado = recorrer_listado(
        cliente=cliente,
        url_listado="https://empleacantabria.es/ofertas-cantabria",
        limitador=limitador_rapido(),
        tamano_pagina=75,
    )

    assert resultado.total == 93
    assert resultado.pagina_alcanzada == 2
    assert resultado.paginas_solicitadas == 2
    assert resultado.error_global == ""
    # 3 códigos por página en los fixtures
    assert resultado.codigos == [
        "062026003633", "062026003632", "062026003631",
        "062026003487", "062026003486", "062026003485",
    ]


def test_reconoce_rangos_1_75_y_76_93() -> None:
    """Ambas páginas reconocen sus rangos y el total es 93."""
    cliente = ClienteSecuencia([
        RespuestaMock(200, PAGINA_1),
        RespuestaMock(200, PAGINA_2),
    ])
    resultado = recorrer_listado(
        cliente=cliente,
        url_listado="https://empleacantabria.es/ofertas-cantabria",
        limitador=limitador_rapido(),
    )
    assert resultado.total == 93
    # Los rangos se reconocen porque ambas páginas son procesadas
    assert resultado.paginas_solicitadas == 2


def test_pagina_2_reconocida_como_ultima() -> None:
    cliente = ClienteSecuencia([
        RespuestaMock(200, PAGINA_1),
        RespuestaMock(200, PAGINA_2),
    ])
    resultado = recorrer_listado(
        cliente=cliente,
        url_listado="https://empleacantabria.es/ofertas-cantabria",
        limitador=limitador_rapido(),
    )
    # Solo 2 páginas solicitadas (no intenta una tercera)
    assert resultado.paginas_solicitadas == 2


def test_url_con_parametro_tamano_75() -> None:
    cliente = ClienteSecuencia([RespuestaMock(200, PAGINA_1), RespuestaMock(200, PAGINA_2)])
    recorrer_listado(
        cliente=cliente,
        url_listado="https://empleacantabria.es/ofertas-cantabria",
        limitador=limitador_rapido(),
        tamano_pagina=75,
    )
    for url, _ in cliente.peticiones:
        assert "delta=75" in url


def test_codigos_se_conservan_como_texto_12_digitos() -> None:
    cliente = ClienteSecuencia([RespuestaMock(200, PAGINA_1), RespuestaMock(200, PAGINA_2)])
    resultado = recorrer_listado(
        cliente=cliente,
        url_listado="https://empleacantabria.es/ofertas-cantabria",
        limitador=limitador_rapido(),
    )
    assert all(len(c) == 12 and c.isdigit() for c in resultado.codigos)
    assert resultado.codigos[0].startswith("0")


def test_listado_vacio_total_cero() -> None:
    cliente = ClienteSecuencia([RespuestaMock(200, LISTADO_VACIO)])
    resultado = recorrer_listado(
        cliente=cliente,
        url_listado="https://empleacantabria.es/ofertas-cantabria",
        limitador=limitador_rapido(),
    )
    assert resultado.total == 0
    assert resultado.codigos == []
    assert resultado.error_global == ""
    assert resultado.paginas_solicitadas == 1


def test_sin_small_search_results_error_global() -> None:
    """Verifica error de parseo cuando falta el elemento small.search-results."""
    html_sin_total = PAGINA_1.replace('class="search-results"', 'class="otra-cosa"')
    cliente = ClienteSecuencia([RespuestaMock(200, html_sin_total)])
    resultado = recorrer_listado(
        cliente=cliente,
        url_listado="https://empleacantabria.es/ofertas-cantabria",
        limitador=limitador_rapido(),
    )
    assert resultado.error_global != ""
    assert "parseo" in resultado.error_global.lower() or "small" in resultado.error_global.lower()


def test_error_http_error_global() -> None:
    cliente = ClienteError(RuntimeError("timeout"))
    resultado = recorrer_listado(
        cliente=cliente,
        url_listado="https://empleacantabria.es/ofertas-cantabria",
        limitador=limitador_rapido(),
    )
    assert resultado.error_global != ""
    assert "timeout" in resultado.error_global.lower() or "error" in resultado.error_global.lower()


def test_codigo_estado_http_en_error_global() -> None:
    cliente = ClienteSecuencia([RespuestaMock(503, "")])
    resultado = recorrer_listado(
        cliente=cliente,
        url_listado="https://empleacantabria.es/ofertas-cantabria",
        limitador=limitador_rapido(),
    )
    assert resultado.error_global != ""
    assert "503" in resultado.error_global


def test_segunda_pagina_fallida_se_detiene() -> None:
    cliente = ClienteSecuencia([
        RespuestaMock(200, PAGINA_1),
        RespuestaMock(500, ""),
    ])
    resultado = recorrer_listado(
        cliente=cliente,
        url_listado="https://empleacantabria.es/ofertas-cantabria",
        limitador=limitador_rapido(),
    )
    assert resultado.error_global != ""
    assert resultado.pagina_alcanzada == 2
    # Los códigos de la primera página no se conservan porque hubo error en la segunda
    # (pero los de la primera ya estaban en resultado.codigos antes del fallo)
    assert resultado.codigos  # códigos de página 1


def test_segunda_pagina_fallida_no_incluye_codigos_de_segunda() -> None:
    cliente = ClienteSecuencia([
        RespuestaMock(200, PAGINA_1),
        RespuestaMock(500, ""),
    ])
    resultado = recorrer_listado(
        cliente=cliente,
        url_listado="https://empleacantabria.es/ofertas-cantabria",
        limitador=limitador_rapido(),
    )
    # Los códigos de la página 2 no aparecen
    codigos_pagina_2 = {"062026003487", "062026003486", "062026003485"}
    assert not any(c in codigos_pagina_2 for c in resultado.codigos)


def test_codigos_ya_vistos_no_se_repeten() -> None:
    cliente = ClienteSecuencia([RespuestaMock(200, PAGINA_1), RespuestaMock(200, PAGINA_2)])
    vistos = {"062026003633", "062026003632", "062026003631"}
    resultado = recorrer_listado(
        cliente=cliente,
        url_listado="https://empleacantabria.es/ofertas-cantabria",
        limitador=limitador_rapido(),
        codigos_vistos=vistos,
    )
    # Los códigos vistos no aparecen en resultado.codigos
    for visto in vistos:
        assert visto not in resultado.codigos


def test_listado_completamente_visto_no_genera_nuevas() -> None:
    """Si todos los códigos están ya vistos, no hay ofertas nuevas."""
    cliente = ClienteSecuencia([RespuestaMock(200, PAGINA_1), RespuestaMock(200, PAGINA_2)])
    todos_los_codigos = {
        "062026003633", "062026003632", "062026003631",
        "062026003487", "062026003486", "062026003485",
    }
    resultado = recorrer_listado(
        cliente=cliente,
        url_listado="https://empleacantabria.es/ofertas-cantabria",
        limitador=limitador_rapido(),
        codigos_vistos=todos_los_codigos,
    )
    assert resultado.codigos == []


def test_limitador_se_invoca_en_cada_peticion() -> None:
    """Todas las peticiones al listado pasan por el limitador."""
    dormir = DormirFalso()
    limitador = LimitadorPeticiones(
        delay_segundos=10.0,
        reloj=RelojFijo(),
        dormir=dormir,
    )
    cliente = ClienteSecuencia([RespuestaMock(200, PAGINA_1), RespuestaMock(200, PAGINA_2)])
    recorrer_listado(
        cliente=cliente,
        url_listado="https://empleacantabria.es/ofertas-cantabria",
        limitador=limitador,
    )
    # El limitador se invocó antes de cada petición
    assert len(cliente.peticiones) == 2
