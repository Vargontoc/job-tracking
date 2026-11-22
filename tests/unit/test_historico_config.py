"""Pruebas de la configuración del histórico de altas y cierres."""

from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

from source.api.historico.config import (
    ConfigHistorico,
    ErrorConfiguracion,
    cargar_configuracion,
)


def test_carga_completa_con_todos_los_campos(tmp_path: Path) -> None:
    """La carga completa devuelve todos los campos configurados."""
    config_file = tmp_path / "historico.yaml"
    config_file.write_text(
        yaml.dump(
            {
                "zona_horaria": "America/New_York",
                "hora_ejecucion": 3,
                "ausencias_consecutivas": 5,
                "umbral_caida_pct": 25,
                "recuento_minimo": 80,
                "rutas": {
                    "sqlite_historico": "data/otro_historico.db",
                    "sqlite_persistencia": "data/otra_persistencia.db",
                },
                "buscador": {"url_base": "http://example.com:9000"},
                "persistencia": {"url_base": "http://example.com:9001"},
                "pdf": {
                    "comunidad": "Madrid",
                    "identificador": "madrid",
                },
            }
        ),
        encoding="utf-8",
    )
    config = cargar_configuracion(config_file)
    assert config.zona_horaria == "America/New_York"
    assert config.hora_ejecucion == 3
    assert config.ausencias_consecutivas == 5
    assert config.umbral_caida_pct == 25
    assert config.recuento_minimo == 80
    assert config.ruta_sqlite_historico == "data/otro_historico.db"
    assert config.ruta_sqlite_persistencia == "data/otra_persistencia.db"
    assert config.url_base_buscador == "http://example.com:9000"
    assert config.url_base_persistencia == "http://example.com:9001"
    assert config.pdf_comunidad == "Madrid"
    assert config.pdf_identificador == "madrid"


def test_valores_por_defecto_cuando_el_fichero_no_existe(tmp_path: Path) -> None:
    """Sin fichero de configuración se devuelven los valores por defecto."""
    config = cargar_configuracion(tmp_path / "no_existe.yaml")
    assert config.zona_horaria == "Europe/Madrid"
    assert config.hora_ejecucion == 2
    assert config.ausencias_consecutivas == 2
    assert config.umbral_caida_pct == 30
    assert config.recuento_minimo == 70
    assert config.ruta_sqlite_historico == "data/job_emcan_historico.db"
    assert config.ruta_sqlite_persistencia == "data/job_emcan.db"
    assert config.url_base_buscador == "http://localhost:8000"
    assert config.url_base_persistencia == "http://localhost:8000"
    assert config.pdf_comunidad == "Cantabria"
    assert config.pdf_identificador == "cantabria"


def test_yaml_malformado_lanza_error(tmp_path: Path) -> None:
    """Un YAML malformado lanza ErrorConfiguracion."""
    config_file = tmp_path / "historico.yaml"
    config_file.write_text(":\n  - :\n  bad: [yaml", encoding="utf-8")
    with pytest.raises(ErrorConfiguracion, match="YAML malformado"):
        cargar_configuracion(config_file)


def test_raiz_no_es_mapa_lanza_error(tmp_path: Path) -> None:
    """Una raíz que no es un mapa lanza ErrorConfiguracion."""
    config_file = tmp_path / "historico.yaml"
    config_file.write_text("- solo\n- una\n- lista\n", encoding="utf-8")
    with pytest.raises(ErrorConfiguracion, match="se esperaba un mapa"):
        cargar_configuracion(config_file)


def test_submapa_no_es_mapa_lanza_error(tmp_path: Path) -> None:
    """Un submapa cuyo valor no es un mapa lanza ErrorConfiguracion."""
    config_file = tmp_path / "historico.yaml"
    config_file.write_text("rutas: \"no_es_un_mapa\"\n", encoding="utf-8")
    with pytest.raises(ErrorConfiguracion, match="rutas.*debe ser un mapa"):
        cargar_configuracion(config_file)


def test_tipo_incorrecto_identifica_el_campo(tmp_path: Path) -> None:
    """Un campo con tipo incorrecto lanza ErrorConfiguracion identificando el campo."""
    config_file = tmp_path / "historico.yaml"
    config_file.write_text("zona_horaria: 123\n", encoding="utf-8")
    with pytest.raises(ErrorConfiguracion, match="zona_horaria"):
        cargar_configuracion(config_file)


def test_tipo_incorrecto_en_campo_entero(tmp_path: Path) -> None:
    """Un campo entero con texto lanza ErrorConfiguracion identificando el campo."""
    config_file = tmp_path / "historico.yaml"
    config_file.write_text("hora_ejecucion: \"dos\"\n", encoding="utf-8")
    with pytest.raises(ErrorConfiguracion, match="hora_ejecucion"):
        cargar_configuracion(config_file)


def test_booleano_no_es_entero_valido(tmp_path: Path) -> None:
    """Un booleano no se acepta como entero (siguiendo el patrón de persistencia)."""
    config_file = tmp_path / "historico.yaml"
    config_file.write_text("ausencias_consecutivas: true\n", encoding="utf-8")
    with pytest.raises(ErrorConfiguracion, match="ausencias_consecutivas"):
        cargar_configuracion(config_file)


def test_hora_ejecucion_negativa_lanza_error(tmp_path: Path) -> None:
    """Una hora de ejecución negativa lanza ErrorConfiguracion."""
    config_file = tmp_path / "historico.yaml"
    config_file.write_text("hora_ejecucion: -1\n", encoding="utf-8")
    with pytest.raises(ErrorConfiguracion, match="hora_ejecucion"):
        cargar_configuracion(config_file)


def test_ausencias_consecutivas_cero_lanza_error(tmp_path: Path) -> None:
    """Un valor de ausencias consecutivas inferior a 1 lanza ErrorConfiguracion."""
    config_file = tmp_path / "historico.yaml"
    config_file.write_text("ausencias_consecutivas: 0\n", encoding="utf-8")
    with pytest.raises(ErrorConfiguracion, match="ausencias_consecutivas"):
        cargar_configuracion(config_file)


def test_zona_horaria_invalida_lanza_error(tmp_path: Path) -> None:
    """Una zona horaria inválida lanza ErrorConfiguracion identificándola."""
    config_file = tmp_path / "historico.yaml"
    config_file.write_text("zona_horaria: \"Zona/Inexistente\"\n", encoding="utf-8")
    with pytest.raises(ErrorConfiguracion, match="Zona/Inexistente"):
        cargar_configuracion(config_file)


def test_no_hay_rutas_de_servidor_ni_credenciales(tmp_path: Path) -> None:
    """La configuración no contiene rutas de servidor ni credenciales."""
    config = cargar_configuracion()
    config_text = yaml.dump(
        {
            "zona_horaria": config.zona_horaria,
            "ruta_sqlite_historico": config.ruta_sqlite_historico,
            "ruta_sqlite_persistencia": config.ruta_sqlite_persistencia,
            "url_base_buscador": config.url_base_buscador,
            "url_base_persistencia": config.url_base_persistencia,
        }
    )
    texto = config_text.lower()
    assert "postgresql" not in texto
    assert "postgres" not in texto
    assert "mysql" not in texto
    assert "password" not in texto
    assert "credential" not in texto
    assert "\nhost: " not in f"\n{config_text.lower()}"
    assert "port:" not in texto


def test_zona_horaria_se_puede_usar_con_zoneinfo(tmp_path: Path) -> None:
    """La zona horaria cargada es utilizable con zoneinfo.ZoneInfo."""
    config = cargar_configuracion()
    zona = ZoneInfo(config.zona_horaria)
    assert zona is not None
    assert zona.key == "Europe/Madrid"
