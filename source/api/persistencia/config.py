"""Carga de la configuración de la capa de persistencia SQLite."""

from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_CONFIG_PATH = Path("config/persistencia.yaml")


@dataclass
class ConfigPersistencia:
    """Configuración de la capa de persistencia.

    Atributos:
        ruta_bd: Ruta al fichero SQLite único, relativa a la raíz del proyecto.
        url_base_buscador: URL base para consultar GET /buscador/status.
        cadencia_segundos: Intervalo entre consultas al buscador.
        dias_retencion: Días que se conservan texto y contacto tras el cierre.
        frecuencia_segundos: Intervalo entre ejecuciones de la purga.
    """

    ruta_bd: str = "data/job_emcan.db"
    url_base_buscador: str = "http://localhost:8000"
    cadencia_segundos: int = 300
    dias_retencion: int = 7
    frecuencia_segundos: int = 86400


class ErrorConfiguracion(Exception):
    """Indica que la configuración de la persistencia no es válida."""


def cargar_configuracion(
    ruta: str | Path | None = None,
) -> ConfigPersistencia:
    """Lee el fichero YAML de configuración de la persistencia.

    Si el fichero no existe, devuelve una ConfigPersistencia con valores por
    defecto. Si el fichero existe pero el YAML es malformado o está vacío,
    lanza ErrorConfiguracion. Los campos opcionales ausentes toman sus
    valores por defecto. Los submapas ausentes usan sus valores por defecto.
    """
    if ruta is None:
        ruta = DEFAULT_CONFIG_PATH
    try:
        with Path(ruta).open(encoding="utf-8") as fichero:
            contenido = yaml.safe_load(fichero)
    except FileNotFoundError:
        return ConfigPersistencia()
    except yaml.YAMLError as error:
        raise ErrorConfiguracion(
            f"Error de configuración de persistencia: YAML malformado en {ruta}."
        ) from error
    except OSError as error:
        raise ErrorConfiguracion(
            f"Error de configuración de persistencia: no se puede leer {ruta}."
        ) from error

    if contenido is None:
        raise ErrorConfiguracion(
            f"Error de configuración de persistencia: el fichero {ruta} está vacío."
        )
    if not isinstance(contenido, dict):
        raise ErrorConfiguracion(
            f"Error de configuración de persistencia: se esperaba un mapa YAML en {ruta}."
        )

    base_de_datos = _obtener_submapa(contenido, "base_de_datos")
    buscador = _obtener_submapa(contenido, "buscador")
    ingesta = _obtener_submapa(contenido, "ingesta")
    purga = _obtener_submapa(contenido, "purga")

    ruta_bd = _obtener_texto(base_de_datos, "ruta", "data/job_emcan.db", ruta)
    url_base = _obtener_texto(buscador, "url_base", "http://localhost:8000", ruta)
    cadencia = _obtener_entero(
        ingesta, "cadencia_segundos", 300, ruta, minimo=1
    )
    dias = _obtener_entero(purga, "dias_retencion", 7, ruta, minimo=0)
    frecuencia = _obtener_entero(
        purga, "frecuencia_segundos", 86400, ruta, minimo=1
    )

    return ConfigPersistencia(
        ruta_bd=ruta_bd,
        url_base_buscador=url_base,
        cadencia_segundos=cadencia,
        dias_retencion=dias,
        frecuencia_segundos=frecuencia,
    )


def _obtener_submapa(
    contenido: dict, clave: str
) -> dict:
    """Obtiene un submapa del contenido, lanzando ErrorConfiguracion si no es un mapa."""
    if clave not in contenido:
        return {}
    valor = contenido[clave]
    if valor is None:
        return {}
    if not isinstance(valor, dict):
        raise ErrorConfiguracion(
            f"Error de configuración de persistencia: '{clave}' debe ser un mapa."
        )
    return valor


def _obtener_texto(
    submapa: dict, clave: str, por_defecto: str, ruta_config: str | Path
) -> str:
    """Obtiene un valor de texto, lanzando ErrorConfiguracion si el tipo es incorrecto."""
    if clave not in submapa:
        return por_defecto
    valor = submapa[clave]
    if not isinstance(valor, str):
        raise ErrorConfiguracion(
            f"Error de configuración de persistencia: "
            f"'{clave}' debe ser una cadena de texto, recibido {valor!r} en {ruta_config}."
        )
    return valor


def _obtener_entero(
    submapa: dict,
    clave: str,
    por_defecto: int,
    ruta_config: str | Path,
    *,
    minimo: int,
) -> int:
    """Obtiene un valor entero, lanzando ErrorConfiguracion si el tipo es incorrecto."""
    if clave not in submapa:
        return por_defecto
    valor = submapa[clave]
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise ErrorConfiguracion(
            f"Error de configuración de persistencia: "
            f"'{clave}' debe ser un entero, recibido {valor!r} en {ruta_config}."
        )
    if valor < minimo:
        raise ErrorConfiguracion(
            f"Error de configuración de persistencia: "
            f"'{clave}' debe ser >= {minimo}, recibido {valor} en {ruta_config}."
        )
    return valor
