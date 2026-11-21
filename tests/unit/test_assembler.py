"""Pruebas unitarias del ensamblado de la respuesta."""

from datetime import datetime

from source.api.assembler import ensamblar_respuesta
from source.api.models import Oferta, ResultadoPorComunidad, SectorProfesional


def _oferta(denominacion: str) -> Oferta:
    return Oferta(
        denominacion=denominacion,
        sector_profesional=SectorProfesional(nombre="Servicios"),
    )


def test_ensambla_ofertas_de_dos_comunidades_con_su_origen() -> None:
    respuesta = ensamblar_respuesta(
        [
            ResultadoPorComunidad(
                comunidad="cantabria",
                estado="ok",
                ofertas=[_oferta("Cocinero/a")],
            ),
            ResultadoPorComunidad(
                comunidad="asturias",
                estado="ok",
                ofertas=[_oferta("Camarero/a")],
            ),
        ]
    )

    resultados = respuesta["resultados"]

    assert resultados[0]["ofertas"][0]["comunidad"] == "cantabria"
    assert resultados[1]["ofertas"][0]["comunidad"] == "asturias"


def test_ensambla_error_por_comunidad_sin_lista_de_ofertas() -> None:
    respuesta = ensamblar_respuesta(
        [
            ResultadoPorComunidad(
                comunidad="cantabria",
                estado="error",
                mensaje_error="Error de descarga: HTTP 404.",
            )
        ]
    )

    resultado = respuesta["resultados"][0]

    assert resultado["estado"] == "error"
    assert resultado["error"]
    assert "ofertas" not in resultado


def test_conserva_comunidad_correcta_sin_ofertas() -> None:
    respuesta = ensamblar_respuesta(
        [ResultadoPorComunidad(comunidad="cantabria", estado="ok")]
    )

    resultado = respuesta["resultados"][0]

    assert resultado["estado"] == "ok"
    assert resultado["ofertas"] == []


def test_incluye_metadatos_y_total_consistente() -> None:
    respuesta = ensamblar_respuesta(
        [
            ResultadoPorComunidad(
                comunidad="cantabria",
                estado="ok",
                ofertas=[_oferta("Cocinero/a"), _oferta("Camarero/a")],
            ),
            ResultadoPorComunidad(comunidad="asturias", estado="ok"),
            ResultadoPorComunidad(
                comunidad="galicia",
                estado="error",
                mensaje_error="Error de conexión.",
            ),
        ]
    )

    metadatos = respuesta["metadatos"]
    ofertas = [
        oferta
        for resultado in respuesta["resultados"]
        for oferta in resultado.get("ofertas", [])
    ]

    assert metadatos["comunidades_procesadas"] == 3
    assert metadatos["total_ofertas"] == len(ofertas)
    assert datetime.fromisoformat(metadatos["timestamp"])
