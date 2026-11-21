"""Pruebas unitarias de la carga y validación de la configuración de persistencia."""

import pytest

from source.api.persistencia.config import (
    DEFAULT_CONFIG_PATH,
    ConfigPersistencia,
    ErrorConfiguracion,
    cargar_configuracion,
)


def test_carga_completa_del_fichero_de_configuracion() -> None:
    """La carga del fichero real devuelve ruta de BD, URL base, cadencia, retención y frecuencia."""
    config = cargar_configuracion()

    assert config.ruta_bd == "data/job_emcan.db"
    assert config.url_base_buscador == "http://localhost:8000"
    assert config.cadencia_segundos == 300
    assert config.dias_retencion == 7
    assert config.frecuencia_segundos == 86400


def test_fichero_real_con_todos_los_campos() -> None:
    """La carga de DEFAULT_CONFIG_PATH coincide con cargar_configuracion()."""
    config = cargar_configuracion(DEFAULT_CONFIG_PATH)

    assert config.ruta_bd == "data/job_emcan.db"
    assert config.url_base_buscador == "http://localhost:8000"
    assert config.cadencia_segundos == 300
    assert config.dias_retencion == 7
    assert config.frecuencia_segundos == 86400


def test_sin_fichero_de_configuracion_usa_valores_por_defecto(tmp_path) -> None:
    """Sin fichero de configuración, la ruta es data/job_emcan.db, la URL base
    es http://localhost:8000, la cadencia son 300 s, la retención son 7 días
    y la frecuencia son 86400 s."""
    ruta_inexistente = tmp_path / "no_existe.yaml"

    config = cargar_configuracion(ruta_inexistente)

    assert config.ruta_bd == "data/job_emcan.db"
    assert config.url_base_buscador == "http://localhost:8000"
    assert config.cadencia_segundos == 300
    assert config.dias_retencion == 7
    assert config.frecuencia_segundos == 86400


def test_fichero_vacio_produce_error_controlado(tmp_path) -> None:
    """Un fichero vacío produce un error controlado."""
    configuracion = tmp_path / "vacio.yaml"
    configuracion.write_text("", encoding="utf-8")

    with pytest.raises(ErrorConfiguracion, match="persistencia"):
        cargar_configuracion(configuracion)


def test_fichero_con_raiz_no_mapa_produce_error_controlado(tmp_path) -> None:
    """Un YAML con raíz que no es un mapa produce un error controlado."""
    configuracion = tmp_path / "lista.yaml"
    configuracion.write_text("- base_de_datos:\n    ruta: data/test.db\n", encoding="utf-8")

    with pytest.raises(ErrorConfiguracion, match="persistencia"):
        cargar_configuracion(configuracion)


def test_fichero_malformado_produce_error_controlado(tmp_path) -> None:
    """Un fichero con YAML malformado produce un error controlado."""
    configuracion = tmp_path / "mal.yaml"
    configuracion.write_text("base_de_datos: [", encoding="utf-8")

    with pytest.raises(ErrorConfiguracion, match="persistencia"):
        cargar_configuracion(configuracion)


def test_campo_tipo_incorrecto_ruta_bd(tmp_path) -> None:
    """Un campo ruta que no es cadena produce un error controlado que identifica el campo."""
    configuracion = tmp_path / "mal_tipo.yaml"
    configuracion.write_text("base_de_datos:\n  ruta: 123\n", encoding="utf-8")

    with pytest.raises(ErrorConfiguracion, match="ruta"):
        cargar_configuracion(configuracion)


def test_campo_tipo_incorrecto_cadencia(tmp_path) -> None:
    """Un campo cadencia_segundos que no es entero produce un error controlado."""
    configuracion = tmp_path / "mal_cadencia.yaml"
    configuracion.write_text("ingesta:\n  cadencia_segundos: 'trescientos'\n", encoding="utf-8")

    with pytest.raises(ErrorConfiguracion, match="cadencia_segundos"):
        cargar_configuracion(configuracion)


def test_campo_tipo_incorrecto_booleano(tmp_path) -> None:
    """Un booleano no se acepta como entero en cadencia_segundos."""
    configuracion = tmp_path / "bool.yaml"
    configuracion.write_text("ingesta:\n  cadencia_segundos: true\n", encoding="utf-8")

    with pytest.raises(ErrorConfiguracion, match="cadencia_segundos"):
        cargar_configuracion(configuracion)


def test_campo_tipo_incorrecto_submapa(tmp_path) -> None:
    """Un submapa que no es un mapa produce un error controlado."""
    configuracion = tmp_path / "submapa.yaml"
    configuracion.write_text("base_de_datos: 'no_es_un_mapa'\n", encoding="utf-8")

    with pytest.raises(ErrorConfiguracion, match="base_de_datos"):
        cargar_configuracion(configuracion)


def test_subcampos_parciales_usan_por_defecto(tmp_path) -> None:
    """Campos ausentes dentro de un submapa toman su valor por defecto."""
    configuracion = tmp_path / "parcial.yaml"
    configuracion.write_text(
        "base_de_datos:\n  ruta: data/custom.db\n",
        encoding="utf-8",
    )

    config = cargar_configuracion(configuracion)

    assert config.ruta_bd == "data/custom.db"
    assert config.url_base_buscador == "http://localhost:8000"
    assert config.cadencia_segundos == 300
    assert config.dias_retencion == 7
    assert config.frecuencia_segundos == 86400


def test_configuracion_no_contiene_credenciales_ni_servidor(tmp_path) -> None:
    """La configuración no contiene rutas de servidor de BD ni credenciales (NFR-001)."""
    config = cargar_configuracion()
    campos = vars(config)
    claves_prohibidas = {"host", "puerto", "usuario", "password", "contrasena", "dsn", "socket"}

    for clave in campos:
        assert clave not in claves_prohibidas

    for valor in campos.values():
        if isinstance(valor, str):
            assert "postgresql" not in valor.lower()
            assert "mysql" not in valor.lower()
            assert "sqlite:///" not in valor.lower()


def test_fichero_ausente_no_lanza_excepcion_no_controlada(tmp_path) -> None:
    """Un fichero ausente produce un retorno controlado con valores por defecto,
    no una excepción no controlada."""
    ruta_inexistente = tmp_path / "ausente.yaml"

    # No debe lanzar ninguna excepción
    config = cargar_configuracion(ruta_inexistente)

    assert isinstance(config, ConfigPersistencia)
    assert config.ruta_bd == "data/job_emcan.db"


def test_cadencia_negativa_se_rechaza(tmp_path) -> None:
    """Una cadencia negativa produce un error controlado."""
    configuracion = tmp_path / "negativa.yaml"
    configuracion.write_text("ingesta:\n  cadencia_segundos: -1\n", encoding="utf-8")

    with pytest.raises(ErrorConfiguracion, match="cadencia_segundos"):
        cargar_configuracion(configuracion)


def test_cambio_de_valores_se_refleja(tmp_path) -> None:
    """Cambiar cadencia y retención y recargar: los nuevos valores se aplican."""
    configuracion = tmp_path / "custom.yaml"
    configuracion.write_text(
        "ingesta:\n  cadencia_segundos: 600\n"
        "purga:\n  dias_retencion: 14\n",
        encoding="utf-8",
    )

    config = cargar_configuracion(configuracion)

    assert config.cadencia_segundos == 600
    assert config.dias_retencion == 14
    assert config.ruta_bd == "data/job_emcan.db"
