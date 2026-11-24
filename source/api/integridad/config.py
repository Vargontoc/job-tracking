"""Carga de la configuración de la integridad desde config/integridad.yaml."""

from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from source.api.config import ErrorConfiguracion, cargar_comunidades
from source.api.models import ComunidadConfigurada

DEFAULT_CONFIG_PATH = Path("config/integridad.yaml")


@dataclass
class ConfigIntegridad:
    """Configuración de la comprobación diaria de integridad.

    Atributos:
        zona_horaria: Zona horaria IANA para determinar el día actual
            (NFR-004).
        hora_ejecucion: Hora entera del día (0-23) de la comprobación diaria
            (NFR-001).
        margen_catchup: Minutos de margen para recuperar el día en curso al
            arrancar (DEC-007).
        dias_retencion: Días que se conservan los PDFs y sus metadatos.
        tolerancia_absoluta: Diferencia absoluta máxima de ofertas aceptada
            (SUP-001).
        tolerancia_relativa_pct: Diferencia relativa máxima en porcentaje
            aceptada (SUP-001).
        umbral_cordura: Recuento mínimo de ofertas del PDF (NFR-002).
        ruta_base_pdfs: Ruta base del árbol de PDFs, relativa a la raíz del
            proyecto (SUP-003).
        url_base_buscador: URL base para consultar GET /buscador/status.
        comunidades: Comunidades a comprobar, con su identificador y la URL
            de su PDF de difusión.
    """

    zona_horaria: str = "Europe/Madrid"
    hora_ejecucion: int = 2
    margen_catchup: int = 60
    dias_retencion: int = 30
    tolerancia_absoluta: int = 1
    tolerancia_relativa_pct: int = 5
    umbral_cordura: int = 70
    ruta_base_pdfs: str = "data/pdfs"
    url_base_buscador: str = "http://localhost:8000"
    comunidades: list[ComunidadConfigurada] = field(default_factory=list)

    @property
    def zona(self) -> ZoneInfo:
        """Zona horaria configurada, lista para calcular la fecha local."""
        return ZoneInfo(self.zona_horaria)


class ErrorConfiguracionIntegridad(Exception):
    """Indica que la configuración de la integridad no es válida."""


def cargar_configuracion(
    ruta: str | Path | None = None,
) -> ConfigIntegridad:
    """Lee el fichero YAML de configuración de la integridad.

    Si el fichero no existe, devuelve una ConfigIntegridad con valores por
    defecto y las comunidades de `config/comunidades.yaml`. Si el fichero
    existe pero el YAML es malformado, está vacío o la raíz no es un mapa,
    lanza ErrorConfiguracionIntegridad. Los campos opcionales ausentes toman
    sus valores por defecto y los submapas ausentes equivalen a submapas
    vacíos. Las rutas se conservan tal cual: son relativas a la raíz del
    proyecto.
    """
    if ruta is None:
        ruta = DEFAULT_CONFIG_PATH
    try:
        with Path(ruta).open(encoding="utf-8") as fichero:
            contenido = yaml.safe_load(fichero)
    except FileNotFoundError:
        return ConfigIntegridad(comunidades=_cargar_comunidades(ruta))
    except yaml.YAMLError as error:
        raise ErrorConfiguracionIntegridad(
            f"Error de configuración de la integridad: YAML malformado en {ruta}."
        ) from error
    except OSError as error:
        raise ErrorConfiguracionIntegridad(
            "Error de configuración de la integridad: no se puede leer "
            f"{ruta}."
        ) from error

    if contenido is None:
        raise ErrorConfiguracionIntegridad(
            f"Error de configuración de la integridad: el fichero {ruta} "
            "está vacío."
        )
    if not isinstance(contenido, dict):
        raise ErrorConfiguracionIntegridad(
            "Error de configuración de la integridad: se esperaba un mapa "
            f"YAML en {ruta}."
        )

    submapa_rutas = _obtener_submapa(contenido, "rutas", ruta)
    submapa_buscador = _obtener_submapa(contenido, "buscador", ruta)

    zona_horaria = _obtener_texto(
        contenido, "zona_horaria", "Europe/Madrid", ruta
    )
    hora_ejecucion = _obtener_entero(
        contenido, "hora_ejecucion", 2, ruta, minimo=0
    )
    if hora_ejecucion > 23:
        raise ErrorConfiguracionIntegridad(
            "Error de configuración de la integridad: 'hora_ejecucion' debe "
            f"estar en el rango 0-23, recibido {hora_ejecucion} en {ruta}."
        )
    margen_catchup = _obtener_entero(
        contenido, "margen_catchup", 60, ruta, minimo=0
    )
    dias_retencion = _obtener_entero(
        contenido, "dias_retencion", 30, ruta, minimo=0
    )
    tolerancia_absoluta = _obtener_entero(
        contenido, "tolerancia_absoluta", 1, ruta, minimo=0
    )
    tolerancia_relativa_pct = _obtener_entero(
        contenido, "tolerancia_relativa_pct", 5, ruta, minimo=0
    )
    umbral_cordura = _obtener_entero(
        contenido, "umbral_cordura", 70, ruta, minimo=0
    )

    ruta_base_pdfs = _obtener_texto(
        submapa_rutas,
        "base_pdfs",
        "data/pdfs",
        ruta,
        campo="rutas.base_pdfs",
    )
    url_base_buscador = _obtener_texto(
        submapa_buscador,
        "url_base",
        "http://localhost:8000",
        ruta,
        campo="buscador.url_base",
    )

    _validar_zona_horaria(zona_horaria, ruta)
    comunidades = _leer_comunidades(contenido, ruta)

    return ConfigIntegridad(
        zona_horaria=zona_horaria,
        hora_ejecucion=hora_ejecucion,
        margen_catchup=margen_catchup,
        dias_retencion=dias_retencion,
        tolerancia_absoluta=tolerancia_absoluta,
        tolerancia_relativa_pct=tolerancia_relativa_pct,
        umbral_cordura=umbral_cordura,
        ruta_base_pdfs=ruta_base_pdfs,
        url_base_buscador=url_base_buscador,
        comunidades=comunidades,
    )


def _validar_zona_horaria(zona: str, ruta_config: str | Path) -> None:
    """Valida que la zona horaria sea una zona IANA reconocida (NFR-004)."""
    try:
        ZoneInfo(zona)
    except Exception as error:
        raise ErrorConfiguracionIntegridad(
            "Error de configuración de la integridad: zona horaria inválida "
            f"'{zona}' en {ruta_config}."
        ) from error


def _leer_comunidades(
    contenido: dict, ruta_config: str | Path
) -> list[ComunidadConfigurada]:
    """Devuelve las comunidades del fichero o las de config/comunidades.yaml."""
    entradas = contenido.get("comunidades")
    if entradas is None:
        return _cargar_comunidades(ruta_config)
    if not isinstance(entradas, list):
        raise ErrorConfiguracionIntegridad(
            "Error de configuración de la integridad: 'comunidades' debe ser "
            f"una lista, recibido {entradas!r} en {ruta_config}."
        )

    resultado: list[ComunidadConfigurada] = []
    for indice, entrada in enumerate(entradas, start=1):
        if not isinstance(entrada, dict):
            raise ErrorConfiguracionIntegridad(
                "Error de configuración de la integridad: la comunidad "
                f"{indice} de 'comunidades' debe ser un mapa, recibido "
                f"{entrada!r} en {ruta_config}."
            )
        identificador = entrada.get("identificador")
        url_pdf = entrada.get("url_pdf")
        if not isinstance(identificador, str) or not identificador:
            raise ErrorConfiguracionIntegridad(
                "Error de configuración de la integridad: la comunidad "
                f"{indice} de 'comunidades' no tiene 'identificador' válido "
                f"en {ruta_config}."
            )
        if not isinstance(url_pdf, str) or not url_pdf:
            raise ErrorConfiguracionIntegridad(
                "Error de configuración de la integridad: la comunidad "
                f"{indice} de 'comunidades' no tiene 'url_pdf' válido en "
                f"{ruta_config}."
            )
        resultado.append(
            ComunidadConfigurada(
                identificador=identificador,
                url_pdf=url_pdf,
            )
        )
    return resultado


def _cargar_comunidades(
    ruta_config: str | Path,
) -> list[ComunidadConfigurada]:
    """Carga las comunidades de config/comunidades.yaml con error controlado."""
    try:
        return cargar_comunidades()
    except ErrorConfiguracion as error:
        raise ErrorConfiguracionIntegridad(
            "Error de configuración de la integridad: no se pueden cargar "
            "las comunidades de config/comunidades.yaml para "
            f"{ruta_config}: {error}"
        ) from error


def _obtener_submapa(
    contenido: dict, clave: str, ruta_config: str | Path
) -> dict:
    """Obtiene un submapa, lanzando el error si su valor no es un mapa."""
    if clave not in contenido:
        return {}
    valor = contenido[clave]
    if valor is None:
        return {}
    if not isinstance(valor, dict):
        raise ErrorConfiguracionIntegridad(
            "Error de configuración de la integridad: "
            f"'{clave}' debe ser un mapa, recibido {valor!r} en {ruta_config}."
        )
    return valor


def _obtener_texto(
    submapa: dict,
    clave: str,
    por_defecto: str,
    ruta_config: str | Path,
    *,
    campo: str | None = None,
) -> str:
    """Obtiene un texto, lanzando el error si el tipo es incorrecto."""
    if clave not in submapa:
        return por_defecto
    valor = submapa[clave]
    nombre = campo or clave
    if not isinstance(valor, str):
        raise ErrorConfiguracionIntegridad(
            "Error de configuración de la integridad: "
            f"'{nombre}' debe ser una cadena de texto, recibido {valor!r} en "
            f"{ruta_config}."
        )
    return valor


def _obtener_entero(
    submapa: dict,
    clave: str,
    por_defecto: int,
    ruta_config: str | Path,
    *,
    minimo: int,
    campo: str | None = None,
) -> int:
    """Obtiene un entero, lanzando el error si el tipo o el rango no valen."""
    if clave not in submapa:
        return por_defecto
    valor = submapa[clave]
    nombre = campo or clave
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise ErrorConfiguracionIntegridad(
            "Error de configuración de la integridad: "
            f"'{nombre}' debe ser un entero, recibido {valor!r} en "
            f"{ruta_config}."
        )
    if valor < minimo:
        raise ErrorConfiguracionIntegridad(
            "Error de configuración de la integridad: "
            f"'{nombre}' debe ser >= {minimo}, recibido {valor} en "
            f"{ruta_config}."
        )
    return valor
