"""Pruebas unitarias de la carga del mapa de comunidades."""

import pytest

from source.api.config import (
    DEFAULT_CONFIG_PATH,
    ErrorConfiguracion,
    cargar_comunidades,
)


def test_carga_la_comunidad_de_configuracion_predeterminada() -> None:
    comunidades = cargar_comunidades()

    assert comunidades
    assert comunidades[0].identificador == "cantabria"
    assert comunidades[0].url_pdf


def test_carga_comunidades_adicionales_sin_cambios_de_codigo(tmp_path) -> None:
    configuracion = tmp_path / "comunidades.yaml"
    configuracion.write_text(
        """
comunidades:
  - identificador: cantabria
    url_pdf: https://ejemplo.test/cantabria.pdf
  - identificador: asturias
    url_pdf: https://ejemplo.test/asturias.pdf
""".strip(),
        encoding="utf-8",
    )

    comunidades = cargar_comunidades(configuracion)

    assert [comunidad.identificador for comunidad in comunidades] == [
        "cantabria",
        "asturias",
    ]


@pytest.mark.parametrize(
    ("nombre", "contenido"),
    [
        ("malformado.yaml", "comunidades: ["),
        (
            "sin_url.yaml",
            "comunidades:\n  - identificador: cantabria",
        ),
    ],
)
def test_informa_errores_de_configuracion(
    tmp_path,
    nombre: str,
    contenido: str,
) -> None:
    configuracion = tmp_path / nombre
    configuracion.write_text(contenido, encoding="utf-8")

    with pytest.raises(ErrorConfiguracion, match="configuración"):
        cargar_comunidades(configuracion)


def test_informa_si_el_fichero_no_existe(tmp_path) -> None:
    with pytest.raises(ErrorConfiguracion, match="configuración"):
        cargar_comunidades(tmp_path / "inexistente.yaml")
