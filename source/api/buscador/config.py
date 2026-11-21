"""Carga de la configuración del rastreador del buscador HTML."""

from pathlib import Path

import yaml

from source.api.buscador.models import ConfigBuscador

DEFAULT_CONFIG_PATH = Path("config/buscador.yaml")


class ErrorConfiguracion(Exception):
    """Indica que la configuración del buscador no es válida."""


def cargar_configuracion(
    ruta: str | Path = DEFAULT_CONFIG_PATH,
) -> ConfigBuscador:
    """Lee el fichero YAML de configuración del buscador.

    Si el fichero no existe, devuelve una ConfigBuscador con valores por
    defecto. Si el fichero existe pero el YAML es malformado o está vacío,
    lanza ErrorConfiguracion. Los campos opcionales ausentes toman sus
    valores por defecto. La hora se valida como entero único entre 0 y 23.
    """
    try:
        with Path(ruta).open(encoding="utf-8") as fichero:
            contenido = yaml.safe_load(fichero)
    except FileNotFoundError:
        return ConfigBuscador()
    except yaml.YAMLError as error:
        raise ErrorConfiguracion(
            f"Error de configuración: YAML malformado en {ruta}."
        ) from error
    except OSError as error:
        raise ErrorConfiguracion(
            f"Error de configuración: no se puede leer {ruta}."
        ) from error

    if contenido is None:
        raise ErrorConfiguracion(
            f"Error de configuración: el fichero {ruta} está vacío."
        )
    if not isinstance(contenido, dict):
        raise ErrorConfiguracion(
            f"Error de configuración: se esperaba un mapa YAML en {ruta}."
        )

    hora = contenido.get("hora", 1)
    _validar_hora(hora)

    rutas = contenido.get("rutas") or {}
    if not isinstance(rutas, dict):
        raise ErrorConfiguracion(
            "Error de configuración: 'rutas' debe ser un mapa."
        )

    return ConfigBuscador(
        hora_pasada=int(hora),
        url_listado=str(contenido.get("url_listado", "")),
        url_ficha=str(contenido.get("url_ficha", "")),
        user_agent=str(contenido.get("user_agent", "")),
        delay_peticiones=int(contenido.get("delay", 10)),
        tamano_pagina=int(contenido.get("tamano_pagina", 75)),
        ruta_seen_codes=str(rutas.get("seen_codes", "")),
        ruta_failed_htmls=str(rutas.get("failed_htmls", "")),
        dias_purga=int(contenido.get("dias_purga", 7)),
    )


def _validar_hora(valor: object) -> None:
    """Valida que la hora sea un entero único entre 0 y 23."""
    if isinstance(valor, bool):
        raise ErrorConfiguracion(
            f"Error de configuración: la hora debe ser un entero entre 0 y 23, "
            f"recibido {valor!r}."
        )
    if not isinstance(valor, int):
        raise ErrorConfiguracion(
            f"Error de configuración: la hora debe ser un entero entre 0 y 23, "
            f"recibido {valor!r}."
        )
    if valor < 0 or valor > 23:
        raise ErrorConfiguracion(
            f"Error de configuración: la hora debe estar entre 0 y 23, "
            f"recibido {valor}."
        )
