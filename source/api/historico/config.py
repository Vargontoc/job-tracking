"""Carga de la configuración del histórico de altas y cierres de ofertas."""

import logging
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path("config/historico.yaml")


@dataclass
class ConfigHistorico:
    """Configuración del histórico de altas y cierres.

    Atributos:
        zona_horaria: Zona horaria IANA para todas las operaciones (NFR-001).
        hora_ejecucion: Hora del día (0-23) del cierre diario.
        ausencias_consecutivas: Listados sin un código para considerarlo
            desaparecido (NFR-003).
        umbral_caida_pct: Porcentaje de caída del recuento que aborta el
            cierre por desaparición (REQ-008).
        recuento_minimo: Recuento mínimo del listado para permitir cierres
            por desaparición (REQ-008).
        ruta_sqlite_historico: Ruta al SQLite propio del histórico.
        ruta_sqlite_persistencia: Ruta al SQLite de api-persistencia (solo
            lectura, DEC-006).
        url_base_buscador: URL base para consultar GET /buscador/status.
        url_base_persistencia: URL base para consultar persistencia-api.
        pdf_comunidad: Nombre de la comunidad del PDF de difusión.
        pdf_identificador: Identificador de la comunidad en el PDF.
    """

    zona_horaria: str = "Europe/Madrid"
    hora_ejecucion: int = 2
    ausencias_consecutivas: int = 2
    umbral_caida_pct: int = 30
    recuento_minimo: int = 70
    ruta_sqlite_historico: str = "data/job_emcan_historico.db"
    ruta_sqlite_persistencia: str = "data/job_emcan.db"
    url_base_buscador: str = "http://localhost:8000"
    url_base_persistencia: str = "http://localhost:8000"
    pdf_comunidad: str = "Cantabria"
    pdf_identificador: str = "cantabria"


class ErrorConfiguracion(Exception):
    """Indica que la configuración del histórico no es válida."""


def cargar_configuracion(
    ruta: str | Path | None = None,
) -> ConfigHistorico:
    """Lee el fichero YAML de configuración del histórico.

    Si el fichero no existe, devuelve una ConfigHistorico con valores por
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
        return ConfigHistorico()
    except yaml.YAMLError as error:
        raise ErrorConfiguracion(
            f"Error de configuración del histórico: YAML malformado en {ruta}."
        ) from error
    except OSError as error:
        raise ErrorConfiguracion(
            f"Error de configuración del histórico: no se puede leer {ruta}."
        ) from error

    if contenido is None:
        raise ErrorConfiguracion(
            f"Error de configuración del histórico: el fichero {ruta} está vacío."
        )
    if not isinstance(contenido, dict):
        raise ErrorConfiguracion(
            f"Error de configuración del histórico: se esperaba un mapa YAML en {ruta}."
        )

    submapa_rutas = _obtener_submapa(contenido, "rutas")
    submapa_buscador = _obtener_submapa(contenido, "buscador")
    submapa_persistencia = _obtener_submapa(contenido, "persistencia")
    submapa_pdf = _obtener_submapa(contenido, "pdf")

    zona_horaria = _obtener_texto(
        contenido, "zona_horaria", "Europe/Madrid", ruta
    )
    hora_ejecucion = _obtener_entero(
        contenido, "hora_ejecucion", 2, ruta, minimo=0
    )
    if hora_ejecucion > 23:
        raise ErrorConfiguracion(
            f"Error de configuración del histórico: "
            f"'hora_ejecucion' debe ser <= 23, recibido {hora_ejecucion} en {ruta}."
        )
    ausencias = _obtener_entero(
        contenido, "ausencias_consecutivas", 2, ruta, minimo=1
    )
    umbral = _obtener_entero(
        contenido, "umbral_caida_pct", 30, ruta, minimo=0
    )
    recuento_minimo = _obtener_entero(
        contenido, "recuento_minimo", 70, ruta, minimo=0
    )

    ruta_sqlite_historico = _obtener_texto(
        submapa_rutas, "sqlite_historico", "data/job_emcan_historico.db", ruta
    )
    ruta_sqlite_persistencia = _obtener_texto(
        submapa_rutas, "sqlite_persistencia", "data/job_emcan.db", ruta
    )
    url_base_buscador = _obtener_texto(
        submapa_buscador, "url_base", "http://localhost:8000", ruta
    )
    url_base_persistencia = _obtener_texto(
        submapa_persistencia, "url_base", "http://localhost:8000", ruta
    )
    pdf_comunidad = _obtener_texto(
        submapa_pdf, "comunidad", "Cantabria", ruta
    )
    pdf_identificador = _obtener_texto(
        submapa_pdf, "identificador", "cantabria", ruta
    )

    _validar_zona_horaria(zona_horaria, ruta)

    return ConfigHistorico(
        zona_horaria=zona_horaria,
        hora_ejecucion=hora_ejecucion,
        ausencias_consecutivas=ausencias,
        umbral_caida_pct=umbral,
        recuento_minimo=recuento_minimo,
        ruta_sqlite_historico=ruta_sqlite_historico,
        ruta_sqlite_persistencia=ruta_sqlite_persistencia,
        url_base_buscador=url_base_buscador,
        url_base_persistencia=url_base_persistencia,
        pdf_comunidad=pdf_comunidad,
        pdf_identificador=pdf_identificador,
    )


def _validar_zona_horaria(zona: str, ruta_config: str | Path) -> None:
    """Valida que la zona horaria sea una zona IANA reconocida.

    Si el paquete ``tzdata`` no está disponible en el entorno, la validación
    se omite con un warning en lugar de rechazar la configuración, ya que
    todas las zonas (válidas e inválidas) fallarían por igual.
    """
    try:
        ZoneInfo(zona)
    except KeyError:
        try:
            ZoneInfo("UTC")
        except Exception:
            logger.warning(
                "No se puede validar la zona horaria '%s': tzdata no "
                "disponible en el entorno. Se continúa con la zona tal cual.",
                zona,
            )
            return
        raise ErrorConfiguracion(
            f"Error de configuración del histórico: "
            f"zona horaria inválida '{zona}' en {ruta_config}."
        )
    except Exception as error:
        logger.warning(
            "No se puede validar la zona horaria '%s' (%s). Se continúa "
            "con la zona tal cual.",
            zona,
            error,
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
            f"Error de configuración del histórico: '{clave}' debe ser un mapa."
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
            f"Error de configuración del histórico: "
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
            f"Error de configuración del histórico: "
            f"'{clave}' debe ser un entero, recibido {valor!r} en {ruta_config}."
        )
    if valor < minimo:
        raise ErrorConfiguracion(
            f"Error de configuración del histórico: "
            f"'{clave}' debe ser >= {minimo}, recibido {valor} en {ruta_config}."
        )
    return valor
