"""Carga del mapa de comunidades configuradas."""

from pathlib import Path

import yaml

from source.api.models import ComunidadConfigurada


DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "comunidades.yaml"
)


class ErrorConfiguracion(Exception):
    """Indica que el mapa de comunidades no es válido o no está disponible."""


def cargar_comunidades(
    ruta: str | Path = DEFAULT_CONFIG_PATH,
) -> list[ComunidadConfigurada]:
    """Lee el mapa YAML y devuelve las comunidades configuradas."""
    try:
        with Path(ruta).open(encoding="utf-8") as config_file:
            contenido = yaml.safe_load(config_file)
    except FileNotFoundError as error:
        raise ErrorConfiguracion(
            f"Error de configuración: no existe el fichero {ruta}."
        ) from error
    except OSError as error:
        raise ErrorConfiguracion(
            f"Error de configuración: no se puede leer el fichero {ruta}."
        ) from error
    except yaml.YAMLError as error:
        raise ErrorConfiguracion(
            "Error de configuración: YAML malformado."
        ) from error

    if not isinstance(contenido, dict):
        raise ErrorConfiguracion(
            "Error de configuración: se esperaba un mapa YAML."
        )

    comunidades = contenido.get("comunidades")
    if not isinstance(comunidades, list):
        raise ErrorConfiguracion(
            "Error de configuración: el campo 'comunidades' debe ser una lista."
        )

    resultado = []
    for indice, entrada in enumerate(comunidades, start=1):
        if not isinstance(entrada, dict):
            raise ErrorConfiguracion(
                f"Error de configuración: comunidad {indice} no es un mapa."
            )

        identificador = entrada.get("identificador")
        url_pdf = entrada.get("url_pdf")
        if not isinstance(identificador, str) or not identificador:
            raise ErrorConfiguracion(
                "Error de configuración: comunidad "
                f"{indice} sin 'identificador'."
            )
        if not isinstance(url_pdf, str) or not url_pdf:
            raise ErrorConfiguracion(
                f"Error de configuración: comunidad {indice} sin 'url_pdf'."
            )

        resultado.append(
            ComunidadConfigurada(
                identificador=identificador,
                url_pdf=url_pdf,
            )
        )

    return resultado
