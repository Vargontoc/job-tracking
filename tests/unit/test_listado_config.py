"""Pruebas unitarias de la carga y validación de la configuración del listado."""

import pytest

from source.api.listado.config import (
    DEFAULT_CONFIG_PATH,
    ConfigListado,
    ErrorConfiguracion,
    cargar_configuracion,
)


def test_carga_completa_del_fichero_de_configuracion() -> None:
    """La carga del fichero real devuelve ruta, tamaño por defecto y tamaño máximo."""
    config = cargar_configuracion()

    assert config.ruta_bd == "data/job_emcan.db"
    assert config.tamano_pagina_por_defecto == 20
    assert config.tamano_pagina_maximo == 100


def test_fichero_real_con_todos_los_campos() -> None:
    """La carga de DEFAULT_CONFIG_PATH coincide con cargar_configuracion()."""
    config = cargar_configuracion(DEFAULT_CONFIG_PATH)

    assert config.ruta_bd == "data/job_emcan.db"
    assert config.tamano_pagina_por_defecto == 20
    assert config.tamano_pagina_maximo == 100


def test_sin_fichero_de_configuracion_usa_valores_por_defecto(tmp_path) -> None:
    """Sin fichero de configuración, la ruta es data/job_emcan.db, el tamaño por
    defecto es 20 y el tamaño máximo es 100."""
    ruta_inexistente = tmp_path / "no_existe.yaml"

    config = cargar_configuracion(ruta_inexistente)

    assert isinstance(config, ConfigListado)
    assert config.ruta_bd == "data/job_emcan.db"
    assert config.tamano_pagina_por_defecto == 20
    assert config.tamano_pagina_maximo == 100


def test_fichero_vacio_produce_error_controlado(tmp_path) -> None:
    """Un fichero vacío produce un error controlado."""
    configuracion = tmp_path / "vacio.yaml"
    configuracion.write_text("", encoding="utf-8")

    with pytest.raises(ErrorConfiguracion, match="listado"):
        cargar_configuracion(configuracion)


def test_fichero_malformado_produce_error_controlado(tmp_path) -> None:
    """Un fichero con YAML malformado produce un error controlado."""
    configuracion = tmp_path / "mal.yaml"
    configuracion.write_text("ruta_bd: [", encoding="utf-8")

    with pytest.raises(ErrorConfiguracion, match="listado"):
        cargar_configuracion(configuracion)


def test_fichero_con_raiz_no_mapa_produce_error_controlado(tmp_path) -> None:
    """Un YAML con raíz que no es un mapa produce un error controlado."""
    configuracion = tmp_path / "lista.yaml"
    configuracion.write_text("- 20\n- 100\n", encoding="utf-8")

    with pytest.raises(ErrorConfiguracion, match="listado"):
        cargar_configuracion(configuracion)


@pytest.mark.parametrize(
    ("contenido", "campo"),
    [
        ("ruta_bd: 123\n", "ruta_bd"),
        ("tamano_pagina_por_defecto: veinte\n", "tamano_pagina_por_defecto"),
        ("tamano_pagina_maximo: true\n", "tamano_pagina_maximo"),
        ("tamano_pagina_maximo: 100.5\n", "tamano_pagina_maximo"),
    ],
)
def test_campo_con_tipo_incorrecto_identifica_el_campo(
    tmp_path, contenido: str, campo: str
) -> None:
    """Un campo con tipo incorrecto produce un error controlado que lo identifica."""
    configuracion = tmp_path / "tipo_incorrecto.yaml"
    configuracion.write_text(contenido, encoding="utf-8")

    with pytest.raises(ErrorConfiguracion, match=campo):
        cargar_configuracion(configuracion)


@pytest.mark.parametrize(
    ("contenido", "campo"),
    [
        ("tamano_pagina_por_defecto: 0\n", "tamano_pagina_por_defecto"),
        ("tamano_pagina_por_defecto: -1\n", "tamano_pagina_por_defecto"),
        ("tamano_pagina_maximo: 0\n", "tamano_pagina_maximo"),
        ("tamano_pagina_maximo: -100\n", "tamano_pagina_maximo"),
    ],
)
def test_tamano_de_pagina_no_entero_positivo_se_rechaza(
    tmp_path, contenido: str, campo: str
) -> None:
    """Un tamaño por defecto o máximo que no es entero positivo se rechaza."""
    configuracion = tmp_path / "tamano_invalido.yaml"
    configuracion.write_text(contenido, encoding="utf-8")

    with pytest.raises(ErrorConfiguracion, match=campo):
        cargar_configuracion(configuracion)


def test_campos_ausentes_usan_valores_por_defecto(tmp_path) -> None:
    """Un fichero parcial completa los campos ausentes con sus valores por defecto."""
    configuracion = tmp_path / "parcial.yaml"
    configuracion.write_text("ruta_bd: data/otra.db\n", encoding="utf-8")

    config = cargar_configuracion(configuracion)

    assert config.ruta_bd == "data/otra.db"
    assert config.tamano_pagina_por_defecto == 20
    assert config.tamano_pagina_maximo == 100


def test_cambio_de_valores_se_refleja(tmp_path) -> None:
    """Cambiar el tamaño máximo y recargar: el nuevo valor es el que se aplica."""
    configuracion = tmp_path / "custom.yaml"
    configuracion.write_text(
        "tamano_pagina_por_defecto: 30\ntamano_pagina_maximo: 50\n",
        encoding="utf-8",
    )

    config = cargar_configuracion(configuracion)

    assert config.tamano_pagina_por_defecto == 30
    assert config.tamano_pagina_maximo == 50
    assert config.ruta_bd == "data/job_emcan.db"


def test_configuracion_no_contiene_credenciales_ni_servidor() -> None:
    """La configuración no contiene rutas de servidor de BD ni credenciales."""
    config = cargar_configuracion()
    campos = vars(config)
    claves_prohibidas = {
        "host",
        "puerto",
        "usuario",
        "password",
        "contrasena",
        "dsn",
        "socket",
    }

    for clave in campos:
        assert clave not in claves_prohibidas

    for valor in campos.values():
        if isinstance(valor, str):
            assert "postgresql" not in valor.lower()
            assert "mysql" not in valor.lower()
            assert "sqlite:///" not in valor.lower()
