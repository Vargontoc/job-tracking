"""Carga de la configuración del listado de ofertas.

Lee ``config/listado.yaml`` y expone la ruta del SQLite de api-persistencia, el
tamaño de página por defecto y el tamaño máximo de página. Un fichero ausente
usa los valores por defecto; un YAML malformado, una raíz que no es un mapa o
un campo con tipo incorrecto produce un error controlado que identifica el
campo.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_CONFIG_PATH = Path("config/listado.yaml")


@dataclass
class ConfigListado:
    """Configuración del listado filtrable de ofertas.

    Atributos:
        ruta_bd: Ruta al fichero SQLite de api-persistencia, relativa a la raíz
            del proyecto. El listado lo abre en modo solo lectura (``mode=ro``).
        tamano_pagina_por_defecto: Tamaño de página cuando el cliente no lo
            indica (entero positivo).
        tamano_pagina_maximo: Tamaño máximo de página aplicado como recorte
            (entero positivo).
    """

    ruta_bd: str = "data/job_emcan.db"
    tamano_pagina_por_defecto: int = 20
    tamano_pagina_maximo: int = 100


class ErrorConfiguracion(Exception):
    """Indica que la configuración del listado no es válida."""


def cargar_configuracion(
    ruta: str | Path | None = None,
) -> ConfigListado:
    """Lee el fichero YAML de configuración del listado.

    Si el fichero no existe, devuelve una ConfigListado con valores por
    defecto. Si el fichero existe pero el YAML es malformado o está vacío,
    lanza ErrorConfiguracion. Los campos ausentes toman su valor por defecto.
    """
    if ruta is None:
        ruta = DEFAULT_CONFIG_PATH
    try:
        with Path(ruta).open(encoding="utf-8") as fichero:
            contenido = yaml.safe_load(fichero)
    except FileNotFoundError:
        return ConfigListado()
    except yaml.YAMLError as error:
        raise ErrorConfiguracion(
            f"Error de configuración del listado: YAML malformado en {ruta}."
        ) from error
    except OSError as error:
        raise ErrorConfiguracion(
            f"Error de configuración del listado: no se puede leer {ruta}."
        ) from error

    if contenido is None:
        raise ErrorConfiguracion(
            f"Error de configuración del listado: el fichero {ruta} está vacío."
        )
    if not isinstance(contenido, dict):
        raise ErrorConfiguracion(
            f"Error de configuración del listado: se esperaba un mapa YAML en {ruta}."
        )

    ruta_bd = _obtener_texto(contenido, "ruta_bd", "data/job_emcan.db", ruta)
    tamano_pagina_por_defecto = _obtener_entero(
        contenido, "tamano_pagina_por_defecto", 20, ruta
    )
    tamano_pagina_maximo = _obtener_entero(
        contenido, "tamano_pagina_maximo", 100, ruta
    )

    return ConfigListado(
        ruta_bd=ruta_bd,
        tamano_pagina_por_defecto=tamano_pagina_por_defecto,
        tamano_pagina_maximo=tamano_pagina_maximo,
    )


def _obtener_texto(
    contenido: dict, clave: str, por_defecto: str, ruta_config: str | Path
) -> str:
    """Obtiene un valor de texto, lanzando ErrorConfiguracion si el tipo es incorrecto."""
    if clave not in contenido:
        return por_defecto
    valor = contenido[clave]
    if not isinstance(valor, str):
        raise ErrorConfiguracion(
            f"Error de configuración del listado: "
            f"'{clave}' debe ser una cadena de texto, recibido {valor!r} en {ruta_config}."
        )
    return valor


def _obtener_entero(
    contenido: dict, clave: str, por_defecto: int, ruta_config: str | Path
) -> int:
    """Obtiene un entero positivo, lanzando ErrorConfiguracion si no lo es."""
    if clave not in contenido:
        return por_defecto
    valor = contenido[clave]
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise ErrorConfiguracion(
            f"Error de configuración del listado: "
            f"'{clave}' debe ser un entero, recibido {valor!r} en {ruta_config}."
        )
    if valor <= 0:
        raise ErrorConfiguracion(
            f"Error de configuración del listado: "
            f"'{clave}' debe ser un entero positivo, recibido {valor} en {ruta_config}."
        )
    return valor
