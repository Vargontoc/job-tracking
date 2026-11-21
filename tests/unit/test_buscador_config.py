"""Pruebas unitarias de la carga y validación de la configuración del buscador."""

import pytest

from source.api.buscador.config import (
    DEFAULT_CONFIG_PATH,
    ErrorConfiguracion,
    cargar_configuracion,
)


def test_carga_completa_del_fichero_de_configuracion() -> None:
    """La carga del fichero real devuelve hora, URLs, User-Agent, delay, página y rutas."""
    config = cargar_configuracion()

    assert config.hora_pasada == 1
    assert "empleacantabria" in config.url_listado
    assert "empleacantabria" in config.url_ficha
    assert "JobEmcanTracking" in config.user_agent
    assert config.delay_peticiones == 10
    assert config.tamano_pagina == 75
    assert "seen_codes" in config.ruta_seen_codes
    assert "failed_htmls" in config.ruta_failed_htmls
    assert config.dias_purga == 7


def test_fichero_real_con_todos_los_campos() -> None:
    """La carga de DEFAULT_CONFIG_PATH coincide con cargar_configuracion()."""
    config = cargar_configuracion(DEFAULT_CONFIG_PATH)

    assert config.hora_pasada == 1
    assert config.url_listado
    assert config.url_ficha
    assert config.user_agent
    assert config.delay_peticiones == 10
    assert config.tamano_pagina == 75


def test_sin_campos_de_configuracion_usa_valores_por_defecto(tmp_path) -> None:
    """Sin campos de configuración, la hora es 1, página 75 y delay 10."""
    configuracion = tmp_path / "buscador.yaml"
    configuracion.write_text(
        "url_listado: https://ejemplo.test/listado\n"
        "url_ficha: https://ejemplo.test/ficha\n",
        encoding="utf-8",
    )

    config = cargar_configuracion(configuracion)

    assert config.hora_pasada == 1
    assert config.tamano_pagina == 75
    assert config.delay_peticiones == 10
    assert config.dias_purga == 7
    assert config.url_listado == "https://ejemplo.test/listado"


def test_fichero_inexistente_devuelve_valores_por_defecto(tmp_path) -> None:
    """Si el fichero no existe, se devuelve una configuración por defecto."""
    ruta_inexistente = tmp_path / "no_existe.yaml"

    config = cargar_configuracion(ruta_inexistente)

    assert config.hora_pasada == 1
    assert config.tamano_pagina == 75
    assert config.delay_peticiones == 10
    assert config.url_listado == ""


@pytest.mark.parametrize("hora", [0, 23])
def test_hora_en_los_extremos_se_acepta(tmp_path, hora: int) -> None:
    """Una hora con valor 0 y con valor 23 se aceptan."""
    configuracion = tmp_path / "buscador.yaml"
    configuracion.write_text(
        f"url_listado: https://ejemplo.test/listado\n"
        f"url_ficha: https://ejemplo.test/ficha\n"
        f"hora: {hora}\n",
        encoding="utf-8",
    )

    config = cargar_configuracion(configuracion)

    assert config.hora_pasada == hora


@pytest.mark.parametrize("hora", [-1, 24])
def test_hora_fuera_de_rango_se_rechaza(tmp_path, hora: int) -> None:
    """Una hora con valor negativo o mayor que 23 se rechaza."""
    configuracion = tmp_path / "buscador.yaml"
    configuracion.write_text(
        f"hora: {hora}\n",
        encoding="utf-8",
    )

    with pytest.raises(ErrorConfiguracion, match="configuración"):
        cargar_configuracion(configuracion)


@pytest.mark.parametrize(
    ("nombre", "contenido"),
    [
        ("lista.yaml", "hora: [1, 2, 3]"),
        ("minutos.yaml", "hora: '01:30'"),
        ("fraccion.yaml", "hora: 1.5"),
        ("cron.yaml", "hora: '0 1 * * *'"),
        ("texto.yaml", "hora: medianoche"),
    ],
)
def test_hora_no_entera_se_rechaza(
    tmp_path, nombre: str, contenido: str
) -> None:
    """Una hora con lista, minutos, fracción o cron se rechaza con error controlado."""
    configuracion = tmp_path / nombre
    configuracion.write_text(contenido, encoding="utf-8")

    with pytest.raises(ErrorConfiguracion, match="configuración"):
        cargar_configuracion(configuracion)


def test_hora_booleano_se_rechaza(tmp_path) -> None:
    """Un booleano no se acepta como hora."""
    configuracion = tmp_path / "bool.yaml"
    configuracion.write_text("hora: true", encoding="utf-8")

    with pytest.raises(ErrorConfiguracion, match="configuración"):
        cargar_configuracion(configuracion)


def test_hora_invalida_no_deja_estado_invaluable(tmp_path) -> None:
    """Una hora inválida no deja la configuración en estado inválido."""
    configuracion = tmp_path / "invalida.yaml"
    configuracion.write_text("hora: 25", encoding="utf-8")

    with pytest.raises(ErrorConfiguracion, match="configuración"):
        cargar_configuracion(configuracion)

    # Verificar que una segunda carga con hora válida funciona
    configuracion.write_text(
        "url_listado: https://ejemplo.test/listado\n"
        "url_ficha: https://ejemplo.test/ficha\n"
        "hora: 5\n",
        encoding="utf-8",
    )
    config = cargar_configuracion(configuracion)
    assert config.hora_pasada == 5


def test_user_agent_contiene_nombre_del_proyecto_y_contacto() -> None:
    """El User-Agent cargado contiene el nombre del proyecto y medio de contacto."""
    config = cargar_configuracion()

    assert "JobEmcanTracking" in config.user_agent
    assert "example.com" in config.user_agent


def test_user_agent_de_fichero_real_cumple_nfr_001() -> None:
    """El User-Agent del fichero real identifica proyecto y contacto (NFR-001)."""
    config = cargar_configuracion()

    ua = config.user_agent
    assert ua, "El User-Agent no debe estar vacío"
    assert "+" in ua or "mailto:" in ua, (
        "El User-Agent debe incluir una referencia de contacto"
    )


def test_fichero_malformado_produce_error_controlado(tmp_path) -> None:
    """Un fichero con YAML malformado produce un error controlado."""
    configuracion = tmp_path / "mal.yaml"
    configuracion.write_text("hora: [", encoding="utf-8")

    with pytest.raises(ErrorConfiguracion, match="configuración"):
        cargar_configuracion(configuracion)


def test_fichero_vacio_produce_error_controlado(tmp_path) -> None:
    """Un fichero vacío produce un error controlado."""
    configuracion = tmp_path / "vacio.yaml"
    configuracion.write_text("", encoding="utf-8")

    with pytest.raises(ErrorConfiguracion, match="configuración"):
        cargar_configuracion(configuracion)


def test_fichero_con_raiz_no_mapa_produce_error_controlado(tmp_path) -> None:
    """Un YAML con raíz que no es un mapa produce un error controlado."""
    configuracion = tmp_path / "lista.yaml"
    configuracion.write_text("- hora: 1\n- hora: 2\n", encoding="utf-8")

    with pytest.raises(ErrorConfiguracion, match="configuración"):
        cargar_configuracion(configuracion)


def test_rutas_invalidas_producen_error_controlado(tmp_path) -> None:
    """Un campo rutas que no es un mapa produce un error controlado."""
    configuracion = tmp_path / "rutas.yaml"
    configuracion.write_text(
        "url_listado: https://ejemplo.test/listado\n"
        "url_ficha: https://ejemplo.test/ficha\n"
        "rutas: 'no_es_un_mapa'\n",
        encoding="utf-8",
    )

    with pytest.raises(ErrorConfiguracion, match="configuración"):
        cargar_configuracion(configuracion)


def test_carga_desde_fichero_con_hora_23(tmp_path) -> None:
    """Cambiar la hora a 23 y recargar: la nueva hora es 23, la página sigue 75."""
    configuracion = tmp_path / "buscador.yaml"
    configuracion.write_text(
        "url_listado: https://ejemplo.test/listado\n"
        "url_ficha: https://ejemplo.test/ficha\n"
        "hora: 23\n"
        "tamano_pagina: 75\n",
        encoding="utf-8",
    )

    config = cargar_configuracion(configuracion)

    assert config.hora_pasada == 23
    assert config.tamano_pagina == 75
