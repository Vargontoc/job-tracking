"""Pruebas de la configuración de la integridad del PDF de difusión."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

from source.api.config import ErrorConfiguracion
from source.api.integridad.config import (
    ConfigIntegridad,
    ErrorConfiguracionIntegridad,
    cargar_configuracion,
)
from source.api.models import ComunidadConfigurada


def test_carga_completa_con_todos_los_campos(tmp_path: Path) -> None:
    """La carga completa devuelve todos los campos configurados."""
    config_file = tmp_path / "integridad.yaml"
    config_file.write_text(
        yaml.dump(
            {
                "zona_horaria": "America/New_York",
                "hora_ejecucion": 5,
                "margen_catchup": 30,
                "dias_retencion": 7,
                "tolerancia_absoluta": 2,
                "tolerancia_relativa_pct": 10,
                "umbral_cordura": 80,
                "rutas": {"base_pdfs": "data/otra_base"},
                "buscador": {"url_base": "http://example.com:9000"},
                "comunidades": [
                    {
                        "identificador": "cantabria",
                        "url_pdf": "https://example.com/cantabria.pdf",
                    },
                    {
                        "identificador": "madrid",
                        "url_pdf": "https://example.com/madrid.pdf",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    config = cargar_configuracion(config_file)

    assert isinstance(config, ConfigIntegridad)
    assert config.zona_horaria == "America/New_York"
    assert config.hora_ejecucion == 5
    assert config.margen_catchup == 30
    assert config.dias_retencion == 7
    assert config.tolerancia_absoluta == 2
    assert config.tolerancia_relativa_pct == 10
    assert config.umbral_cordura == 80
    assert config.ruta_base_pdfs == "data/otra_base"
    assert config.url_base_buscador == "http://example.com:9000"
    assert [c.identificador for c in config.comunidades] == ["cantabria", "madrid"]
    assert config.comunidades[0].url_pdf == "https://example.com/cantabria.pdf"


def test_valores_por_defecto_cuando_el_fichero_no_existe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sin fichero se devuelven los valores por defecto del diseño."""
    monkeypatch.setattr(
        "source.api.integridad.config.cargar_comunidades",
        lambda: [
            ComunidadConfigurada(
                identificador="cantabria",
                url_pdf="https://example.com/cantabria.pdf",
            )
        ],
    )

    config = cargar_configuracion(tmp_path / "no_existe.yaml")

    assert config.zona_horaria == "Europe/Madrid"
    assert config.hora_ejecucion == 2
    assert config.margen_catchup == 60
    assert config.dias_retencion == 30
    assert config.tolerancia_absoluta == 1
    assert config.tolerancia_relativa_pct == 5
    assert config.umbral_cordura == 70
    assert config.ruta_base_pdfs == "data/pdfs"
    assert config.url_base_buscador == "http://localhost:8000"
    assert [c.identificador for c in config.comunidades] == ["cantabria"]


def test_comunidades_se_reutilizan_si_no_se_declaran(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sin la clave `comunidades` se cargan las de config/comunidades.yaml."""
    monkeypatch.setattr(
        "source.api.integridad.config.cargar_comunidades",
        lambda: [
            ComunidadConfigurada(
                identificador="cantabria",
                url_pdf="https://example.com/cantabria.pdf",
            )
        ],
    )
    config_file = tmp_path / "integridad.yaml"
    config_file.write_text("hora_ejecucion: 5\n", encoding="utf-8")

    config = cargar_configuracion(config_file)

    assert config.hora_ejecucion == 5
    assert len(config.comunidades) == 1
    assert config.comunidades[0].identificador == "cantabria"


def test_fichero_real_del_repositorio_carga_los_valores_por_defecto() -> None:
    """El config/integridad.yaml del repositorio carga los valores por defecto."""
    config = cargar_configuracion()

    assert config.zona_horaria == "Europe/Madrid"
    assert config.hora_ejecucion == 2
    assert config.margen_catchup == 60
    assert config.dias_retencion == 30
    assert config.tolerancia_absoluta == 1
    assert config.tolerancia_relativa_pct == 5
    assert config.umbral_cordura == 70
    assert config.ruta_base_pdfs == "data/pdfs"
    assert config.url_base_buscador == "http://localhost:8000"
    assert config.comunidades


def test_yaml_malformado_lanza_error(tmp_path: Path) -> None:
    """Un YAML malformado lanza ErrorConfiguracionIntegridad."""
    config_file = tmp_path / "integridad.yaml"
    config_file.write_text(":\n  - :\n  bad: [yaml", encoding="utf-8")

    with pytest.raises(ErrorConfiguracionIntegridad, match="YAML malformado"):
        cargar_configuracion(config_file)


def test_fichero_vacio_lanza_error(tmp_path: Path) -> None:
    """Un fichero vacío lanza ErrorConfiguracionIntegridad."""
    config_file = tmp_path / "integridad.yaml"
    config_file.write_text("", encoding="utf-8")

    with pytest.raises(ErrorConfiguracionIntegridad, match="está vacío"):
        cargar_configuracion(config_file)


def test_raiz_no_es_mapa_lanza_error(tmp_path: Path) -> None:
    """Una raíz que no es un mapa lanza ErrorConfiguracionIntegridad."""
    config_file = tmp_path / "integridad.yaml"
    config_file.write_text("- solo\n- una\n- lista\n", encoding="utf-8")

    with pytest.raises(ErrorConfiguracionIntegridad, match="se esperaba un mapa"):
        cargar_configuracion(config_file)


@pytest.mark.parametrize("submapa", ["rutas", "buscador"])
def test_submapa_que_no_es_mapa_lanza_error(
    tmp_path: Path, submapa: str
) -> None:
    """Un submapa cuyo valor no es un mapa lanza un error que lo identifica."""
    config_file = tmp_path / "integridad.yaml"
    config_file.write_text(f'{submapa}: "no_es_un_mapa"\n', encoding="utf-8")

    with pytest.raises(
        ErrorConfiguracionIntegridad, match=f"{submapa}.*debe ser un mapa"
    ):
        cargar_configuracion(config_file)


def test_tipo_incorrecto_en_zona_horaria(tmp_path: Path) -> None:
    """Una zona horaria que no es texto lanza un error que identifica el campo."""
    config_file = tmp_path / "integridad.yaml"
    config_file.write_text("zona_horaria: 123\n", encoding="utf-8")

    with pytest.raises(ErrorConfiguracionIntegridad, match="zona_horaria"):
        cargar_configuracion(config_file)


def test_tipo_incorrecto_en_campo_entero(tmp_path: Path) -> None:
    """Un campo entero con texto lanza un error que identifica el campo."""
    config_file = tmp_path / "integridad.yaml"
    config_file.write_text('margen_catchup: "sesenta"\n', encoding="utf-8")

    with pytest.raises(ErrorConfiguracionIntegridad, match="margen_catchup"):
        cargar_configuracion(config_file)


def test_booleano_no_es_entero_valido(tmp_path: Path) -> None:
    """Un booleano no se acepta como entero."""
    config_file = tmp_path / "integridad.yaml"
    config_file.write_text("dias_retencion: true\n", encoding="utf-8")

    with pytest.raises(ErrorConfiguracionIntegridad, match="dias_retencion"):
        cargar_configuracion(config_file)


def test_ruta_base_pdfs_identifica_el_campo(tmp_path: Path) -> None:
    """Un tipo incorrecto en rutas.base_pdfs identifica el campo completo."""
    config_file = tmp_path / "integridad.yaml"
    config_file.write_text("rutas:\n  base_pdfs: 42\n", encoding="utf-8")

    with pytest.raises(
        ErrorConfiguracionIntegridad, match=r"rutas\.base_pdfs"
    ):
        cargar_configuracion(config_file)


def test_url_base_buscador_identifica_el_campo(tmp_path: Path) -> None:
    """Un tipo incorrecto en buscador.url_base identifica el campo completo."""
    config_file = tmp_path / "integridad.yaml"
    config_file.write_text("buscador:\n  url_base: [8000]\n", encoding="utf-8")

    with pytest.raises(
        ErrorConfiguracionIntegridad, match=r"buscador\.url_base"
    ):
        cargar_configuracion(config_file)


def test_zona_horaria_invalida_lanza_error(tmp_path: Path) -> None:
    """Una zona horaria inválida se rechaza identificándola."""
    config_file = tmp_path / "integridad.yaml"
    config_file.write_text(
        'zona_horaria: "Zona/Inexistente"\n', encoding="utf-8"
    )

    with pytest.raises(ErrorConfiguracionIntegridad, match="Zona/Inexistente"):
        cargar_configuracion(config_file)


@pytest.mark.parametrize("hora", [24, 25, -1])
def test_hora_fuera_de_rango_lanza_error(
    tmp_path: Path, hora: int
) -> None:
    """Una hora fuera del rango 0-23 se rechaza identificándola."""
    config_file = tmp_path / "integridad.yaml"
    config_file.write_text(f"hora_ejecucion: {hora}\n", encoding="utf-8")

    with pytest.raises(ErrorConfiguracionIntegridad, match="hora_ejecucion"):
        cargar_configuracion(config_file)


@pytest.mark.parametrize(
    "valor", ["2.5", '"02:30"', "[2, 30]", "true"]
)
def test_hora_con_fracciones_minutos_o_lista_lanza_error(
    tmp_path: Path, valor: str
) -> None:
    """Una hora con fracciones, minutos, lista o booleano se rechaza."""
    config_file = tmp_path / "integridad.yaml"
    config_file.write_text(f"hora_ejecucion: {valor}\n", encoding="utf-8")

    with pytest.raises(ErrorConfiguracionIntegridad, match="hora_ejecucion"):
        cargar_configuracion(config_file)


@pytest.mark.parametrize("hora", [0, 23])
def test_hora_en_los_extremos_es_valida(tmp_path: Path, hora: int) -> None:
    """Los valores 0 y 23 son horas enteras válidas."""
    config_file = tmp_path / "integridad.yaml"
    config_file.write_text(f"hora_ejecucion: {hora}\n", encoding="utf-8")

    assert cargar_configuracion(config_file).hora_ejecucion == hora


def test_margen_catchup_negativo_lanza_error(tmp_path: Path) -> None:
    """Un margen de catch-up negativo se rechaza identificándolo."""
    config_file = tmp_path / "integridad.yaml"
    config_file.write_text("margen_catchup: -5\n", encoding="utf-8")

    with pytest.raises(ErrorConfiguracionIntegridad, match="margen_catchup"):
        cargar_configuracion(config_file)


def test_margen_catchup_cero_es_valido(tmp_path: Path) -> None:
    """Un margen de catch-up de cero es válido (DEC-007)."""
    config_file = tmp_path / "integridad.yaml"
    config_file.write_text("margen_catchup: 0\n", encoding="utf-8")

    assert cargar_configuracion(config_file).margen_catchup == 0


@pytest.mark.parametrize(
    "campo",
    [
        "dias_retencion",
        "tolerancia_absoluta",
        "tolerancia_relativa_pct",
        "umbral_cordura",
    ],
)
def test_campos_negativos_lanzan_error(tmp_path: Path, campo: str) -> None:
    """Los días de retención, las tolerancias y el umbral no admiten negativos."""
    config_file = tmp_path / "integridad.yaml"
    config_file.write_text(f"{campo}: -1\n", encoding="utf-8")

    with pytest.raises(ErrorConfiguracionIntegridad, match=campo):
        cargar_configuracion(config_file)


def test_comunidades_que_no_es_lista_lanza_error(tmp_path: Path) -> None:
    """Una clave `comunidades` que no es lista se rechaza."""
    config_file = tmp_path / "integridad.yaml"
    config_file.write_text('comunidades: "cantabria"\n', encoding="utf-8")

    with pytest.raises(ErrorConfiguracionIntegridad, match="comunidades"):
        cargar_configuracion(config_file)


def test_comunidad_que_no_es_mapa_lanza_error(tmp_path: Path) -> None:
    """Una entrada de `comunidades` que no es mapa se rechaza."""
    config_file = tmp_path / "integridad.yaml"
    config_file.write_text("comunidades:\n  - cantabria\n", encoding="utf-8")

    with pytest.raises(ErrorConfiguracionIntegridad, match="comunidades"):
        cargar_configuracion(config_file)


def test_comunidad_sin_url_pdf_lanza_error(tmp_path: Path) -> None:
    """Una comunidad sin `url_pdf` se rechaza identificando el campo."""
    config_file = tmp_path / "integridad.yaml"
    config_file.write_text(
        "comunidades:\n  - identificador: cantabria\n", encoding="utf-8"
    )

    with pytest.raises(ErrorConfiguracionIntegridad, match="url_pdf"):
        cargar_configuracion(config_file)


def test_comunidad_sin_identificador_lanza_error(tmp_path: Path) -> None:
    """Una comunidad sin `identificador` se rechaza identificando el campo."""
    config_file = tmp_path / "integridad.yaml"
    config_file.write_text(
        "comunidades:\n  - url_pdf: https://example.com/cantabria.pdf\n",
        encoding="utf-8",
    )

    with pytest.raises(ErrorConfiguracionIntegridad, match="identificador"):
        cargar_configuracion(config_file)


def test_error_de_comunidades_se_propaga_como_error_de_integridad(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un ErrorConfiguracion de config/comunidades.yaml no se silencia."""

    def _falla() -> list[ComunidadConfigurada]:
        raise ErrorConfiguracion(
            "Error de configuración: no existe el fichero config/comunidades.yaml."
        )

    monkeypatch.setattr(
        "source.api.integridad.config.cargar_comunidades", _falla
    )
    config_file = tmp_path / "integridad.yaml"
    config_file.write_text("hora_ejecucion: 5\n", encoding="utf-8")

    with pytest.raises(
        ErrorConfiguracionIntegridad, match="comunidades.yaml"
    ):
        cargar_configuracion(config_file)


def test_zona_horaria_se_puede_usar_para_la_fecha_local(
    tmp_path: Path,
) -> None:
    """La zona horaria cargada permite calcular la fecha local."""
    config_file = tmp_path / "integridad.yaml"
    config_file.write_text(
        'zona_horaria: "America/New_York"\n', encoding="utf-8"
    )

    config = cargar_configuracion(config_file)
    zona = config.zona

    assert isinstance(zona, ZoneInfo)
    assert zona.key == "America/New_York"
    ahora_local = datetime(2026, 11, 23, 2, 0, tzinfo=zona)
    assert ahora_local.date().isoformat() == "2026-11-23"
    assert ahora_local.utcoffset() is not None


def test_no_contiene_rutas_de_servidor_ni_credenciales() -> None:
    """La configuración no tiene rutas de servidor de BD ni credenciales."""
    config = cargar_configuracion()
    config_text = yaml.dump(
        {
            "zona_horaria": config.zona_horaria,
            "hora_ejecucion": config.hora_ejecucion,
            "margen_catchup": config.margen_catchup,
            "dias_retencion": config.dias_retencion,
            "tolerancia_absoluta": config.tolerancia_absoluta,
            "tolerancia_relativa_pct": config.tolerancia_relativa_pct,
            "umbral_cordura": config.umbral_cordura,
            "ruta_base_pdfs": config.ruta_base_pdfs,
            "url_base_buscador": config.url_base_buscador,
            "comunidades": [
                {"identificador": c.identificador, "url_pdf": c.url_pdf}
                for c in config.comunidades
            ],
        }
    )
    texto = config_text.lower()

    assert "postgresql" not in texto
    assert "postgres" not in texto
    assert "mysql" not in texto
    assert "password" not in texto
    assert "credential" not in texto
    assert "\nhost: " not in f"\n{texto}"
    assert "port:" not in texto
    assert "sqlite" not in texto
