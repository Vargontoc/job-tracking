"""Pruebas del comparador de recuentos y del veredicto (TASK-009).

Cubren `source/api/integridad/comparador.py`: `ComparadorRecuentos` aplica la
tolerancia más permisiva de las dos configuradas —absoluta o relativa— para
decidir entre `concordante` y `divergente` (DEC-005), anula el veredicto a
`divergente` cuando el recuento del PDF no alcanza el umbral de cordura
(ALT-004) y cuando el estado del buscador no es utilizable por error HTTP o de
red, `ultima_pasada` nula o `error_global` no vacío (ALT-005, ALT-006). El
resultado siempre lleva los recuentos conocidos, la diferencia, los umbrales
aplicados y el motivo (REQ-005), y la comparación es una función pura que no
lanza excepciones ni divide por cero con un `total_listado` de cero.
"""

import httpx

from source.api.integridad.buscador_client import (
    ClienteEstadoBuscador,
    EstadoBuscador,
    EstadoBuscadorNoUtilizable,
    UltimaPasada,
)
from source.api.integridad.comparador import (
    ComparadorRecuentos,
    ResultadoComparacion,
)

URL_BASE = "http://localhost:8000"


def _comparador(
    tolerancia_absoluta: int = 1,
    tolerancia_relativa_pct: int = 5,
    umbral_cordura: int = 70,
) -> ComparadorRecuentos:
    """Comparador con los valores por defecto de la configuración."""
    return ComparadorRecuentos(
        tolerancia_absoluta,
        tolerancia_relativa_pct,
        umbral_cordura,
    )


def _estado(total_listado: int = 93) -> EstadoBuscador:
    """Estado utilizable del buscador con el `total_listado` indicado."""
    return EstadoBuscador(
        in_progress=False,
        progreso=None,
        ultima_pasada=UltimaPasada(
            timestamp="2026-11-23T01:00:04",
            comunidad="Cantabria",
            total_listado=total_listado,
            error_global="",
        ),
    )


def _consultar(cuerpo: object) -> EstadoBuscador | EstadoBuscadorNoUtilizable:
    """Normaliza un cuerpo JSON simulado de `GET /buscador/status`."""
    transporte = httpx.MockTransport(
        lambda solicitud: httpx.Response(200, json=cuerpo, request=solicitud)
    )
    with httpx.Client(transport=transporte) as cliente:
        return ClienteEstadoBuscador(URL_BASE, cliente=cliente).consultar_estado()


def _consultar_error_http() -> EstadoBuscador | EstadoBuscadorNoUtilizable:
    """Normaliza un 503 simulado de `GET /buscador/status`."""
    transporte = httpx.MockTransport(
        lambda solicitud: httpx.Response(503, request=solicitud)
    )
    with httpx.Client(transport=transporte) as cliente:
        return ClienteEstadoBuscador(URL_BASE, cliente=cliente).consultar_estado()


# --- Tolerancias (DEC-005, SUP-001, NFR-002) --------------------------------


def test_92_y_93_son_concordantes_con_las_tolerancias_por_defecto() -> None:
    """El par observado 92/93 entra en la tolerancia absoluta (SUP-001)."""
    resultado = _comparador().comparar(92, _estado(93))

    assert isinstance(resultado, ResultadoComparacion)
    assert resultado.veredicto == "concordante"
    assert resultado.recuento_pdf == 92
    assert resultado.recuento_buscador == 93
    assert resultado.diferencia == 1
    assert resultado.motivo


def test_la_absoluta_acepta_aunque_la_relativa_no_se_cumpla() -> None:
    """Con `2` de tolerancia absoluta, una diferencia de `2` es concordante.

    La tolerancia relativa del `1 %` sobre 100 no se cumple (2 % > 1 %), pero
    se aplica la más permisiva (DEC-005).
    """
    resultado = _comparador(2, 1).comparar(98, _estado(100))

    assert resultado.veredicto == "concordante"
    assert resultado.diferencia == 2
    assert "tolerancia absoluta" in resultado.motivo


def test_la_relativa_acepta_una_diferencia_fuera_de_la_absoluta() -> None:
    """Una diferencia de `5` sobre 105 cabe en el `5 %` aunque no en `1`."""
    resultado = _comparador(1, 5).comparar(100, _estado(105))

    assert resultado.veredicto == "concordante"
    assert resultado.diferencia == 5
    assert "tolerancia relativa" in resultado.motivo


def test_una_diferencia_fuera_de_ambas_es_divergente() -> None:
    """`92` frente a `100` supera la absoluta y la relativa (REQ-004)."""
    resultado = _comparador(1, 5).comparar(92, _estado(100))

    assert resultado.veredicto == "divergente"
    assert resultado.diferencia == 8
    assert "fuera de la tolerancia absoluta" in resultado.motivo
    assert "tolerancia relativa" in resultado.motivo


def test_se_aplican_las_tolerancias_y_el_umbral_configurados() -> None:
    """Con otros valores configurados se aplican esos y no `1`, `5 %` y `70`."""
    relativa_amplia = _comparador(1, 20).comparar(70, _estado(80))
    umbral_alto = _comparador(1, 5, 80).comparar(75, _estado(75))

    # 10 de diferencia sobre 80 es un 12,5 %: cabe en el 20 %, no en el 5 %.
    assert relativa_amplia.veredicto == "concordante"
    assert relativa_amplia.tolerancia_relativa_pct == 20
    assert relativa_amplia.umbral_cordura == 70

    # 75 alcanza el umbral por defecto, pero no el umbral configurado de 80.
    assert umbral_alto.veredicto == "divergente"
    assert umbral_alto.umbral_cordura == 80
    assert "umbral de cordura" in umbral_alto.motivo


# --- Umbral de cordura (ALT-004, NFR-002) -----------------------------------


def test_por_debajo_del_umbral_es_divergente_aunque_la_diferencia_sea_cero() -> None:
    """`65` con umbral `70` diverge aunque coincida con el buscador."""
    resultado = _comparador(umbral_cordura=70).comparar(65, _estado(65))

    assert resultado.veredicto == "divergente"
    assert resultado.diferencia == 0
    assert "umbral de cordura" in resultado.motivo
    assert "65" in resultado.motivo


def test_alcanzar_el_umbral_no_produce_divergencia_por_umbral() -> None:
    """`70` con umbral `70` queda dentro del umbral (NFR-002)."""
    resultado = _comparador(umbral_cordura=70).comparar(70, _estado(70))

    assert resultado.veredicto == "concordante"
    assert resultado.diferencia == 0
    assert "umbral de cordura" not in resultado.motivo


def test_un_recuento_de_cero_es_divergente_por_el_umbral() -> None:
    """Un PDF sin ofertas se resuelve por umbral aunque el buscador sí tenga."""
    resultado = _comparador(umbral_cordura=70).comparar(0, _estado(93))

    assert resultado.veredicto == "divergente"
    assert resultado.recuento_pdf == 0
    assert resultado.recuento_buscador == 93
    assert "umbral de cordura" in resultado.motivo


# --- Estado del buscador no utilizable (ALT-005, ALT-006) -------------------


def test_un_error_http_no_emite_veredicto_concordante() -> None:
    """Un 503 del buscador deja el veredicto en `divergente` (ALT-005)."""
    estado = _consultar_error_http()

    resultado = _comparador().comparar(92, estado)

    assert isinstance(estado, EstadoBuscadorNoUtilizable)
    assert resultado.veredicto == "divergente"
    assert resultado.recuento_buscador is None
    assert resultado.diferencia is None
    assert "503" in resultado.motivo


def test_una_ultima_pasada_nula_no_emite_veredicto_concordante() -> None:
    """Sin `ultima_pasada` no hay recuento y el motivo lo identifica."""
    estado = _consultar(
        {"in_progress": False, "progreso": None, "ultima_pasada": None}
    )

    resultado = _comparador().comparar(92, estado)

    assert isinstance(estado, EstadoBuscadorNoUtilizable)
    assert resultado.veredicto == "divergente"
    assert "ultima_pasada" in resultado.motivo


def test_un_error_global_no_emite_veredicto_concordante() -> None:
    """Una pasada con `error_global` deja el veredicto en `divergente`."""
    estado = _consultar(
        {
            "in_progress": False,
            "progreso": None,
            "ultima_pasada": {
                "timestamp": "2026-11-23T01:00:04",
                "comunidad": "Cantabria",
                "total_listado": 93,
                "error_global": "el portal no respondió",
                "errores_por_oferta": [],
            },
        }
    )

    resultado = _comparador().comparar(92, estado)

    assert isinstance(estado, EstadoBuscadorNoUtilizable)
    assert resultado.veredicto == "divergente"
    assert "error_global" in resultado.motivo
    assert "el portal no respondió" in resultado.motivo


def test_estado_no_utilizable_y_umbral_bajo_mencionan_ambas_causas() -> None:
    """Si además el PDF no alcanza el umbral, el motivo recoge las dos causas."""
    resultado = _comparador().comparar(10, _consultar_error_http())

    assert resultado.veredicto == "divergente"
    assert "umbral de cordura" in resultado.motivo
    assert "503" in resultado.motivo


# --- Contenido del resultado (REQ-005) --------------------------------------


def test_el_resultado_incluye_recuentos_diferencia_y_umbrales() -> None:
    """El resultado lleva los recuentos, la diferencia y los umbrales usados."""
    resultado = _comparador(2, 4, 60).comparar(95, _estado(100))

    assert resultado.veredicto == "divergente"
    assert resultado.recuento_pdf == 95
    assert resultado.recuento_buscador == 100
    assert resultado.diferencia == 5
    assert resultado.tolerancia_absoluta == 2
    assert resultado.tolerancia_relativa_pct == 4
    assert resultado.umbral_cordura == 60
    assert resultado.motivo


# --- Límite del listado vacío ------------------------------------------------


def test_un_total_listado_de_cero_no_rompe_la_comparacion() -> None:
    """Sin `total_listado` la regla relativa se omite y no hay división por cero."""
    concordante = _comparador(1, 5, 0).comparar(0, _estado(0))
    divergente = _comparador(1, 5, 70).comparar(92, _estado(0))

    assert concordante.veredicto == "concordante"
    assert concordante.diferencia == 0
    assert divergente.veredicto == "divergente"
    assert divergente.diferencia == 92
    assert "tolerancia absoluta" in divergente.motivo
