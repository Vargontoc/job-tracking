"""Recorrido del listado paginado del buscador de Emplea Cantabria."""

import logging
import re
from dataclasses import dataclass, field
from typing import Protocol

from selectolax.lexbor import LexborHTMLParser

from source.api.buscador.rate_limiter import LimitadorPeticiones

logger = logging.getLogger(__name__)


# Regex para extraer rango y total del texto de paginación.
# "Mostrando el intervalo 1 - 75 de 93 resultados."
_RE_RANGO = re.compile(
    r"(\d+)\s*-\s*(\d+)\s+de\s+(\d+)\s+resultados"
)


class ErrorListado(Exception):
    """Error durante el recorrido del listado del buscador."""


class ClienteHTTP(Protocol):
    """Protocolo para un cliente HTTP síncrono (compatible con httpx.Client)."""

    def get(self, url: str, *, timeout: float) -> "RespuestaHTTP":
        ...


class RespuestaHTTP(Protocol):
    """Protocolo para una respuesta HTTP."""

    status_code: int
    text: str

    def raise_for_status(self) -> None:
        ...


@dataclass
class ResultadoListado:
    """Resultado del recorrido del listado paginado.

    Atributos:
        total: Total de ofertas declaradas por el portal.
        codigos: Lista ordenada de códigos de oferta extraídos.
        error_global: Error que detuvo el recorrido, vacío si no hay.
        pagina_alcanzada: Número de la última página procesada (1-based).
        paginas_solicitadas: Número de peticiones realizadas al listado.
    """

    total: int = 0
    codigos: list[str] = field(default_factory=list)
    error_global: str = ""
    pagina_alcanzada: int = 0
    paginas_solicitadas: int = 0


def recorrer_listado(
    cliente: ClienteHTTP,
    url_listado: str,
    limitador: LimitadorPeticiones,
    tamano_pagina: int = 75,
    timeout: float = 30.0,
    codigos_vistos: set[str] | None = None,
) -> ResultadoListado:
    """Recorre el listado paginado del buscador.

    Args:
        cliente: Cliente HTTP síncrono (compatible con httpx.Client).
        url_listado: URL base del listado del portal.
        limitador: Limitador de peticiones compartido (NFR-002, DEC-003).
        tamano_pagina: Número de ofertas por página (NFR-004).
        timeout: Timeout de cada petición HTTP en segundos.
        codigos_vistos: Conjunto de códigos ya vistos (para filtrar novedades).

    Returns:
        ResultadoListado con el total declarado, los códigos extraídos
        (como texto de 12 dígitos conservando ceros por delante),
        el error global si el recorrido falla y el punto alcanzado.
    """
    logger.info(f"INICIO recorrer_listado desde {url_listado}")
    vistos = codigos_vistos or set()
    resultado = ResultadoListado()
    pagina = 1

    # Log de cookies/sesión del cliente (diagnóstico)
    if hasattr(cliente, "cookies"):
        logger.info(f"Cookies del cliente HTTP: {dict(cliente.cookies)}")
    else:
        logger.info("El cliente HTTP no tiene atributo 'cookies'")

    while True:
        url = _construir_url(url_listado, tamano_pagina, pagina)

        # Log 1: URL completa de cada petición
        logger.info(f"Página {pagina}: URL completa = {url}")

        try:
            limitador.esperar()
            respuesta = cliente.get(url, timeout=timeout)
            respuesta.raise_for_status()
            logger.debug(f"Página {pagina} recibida correctamente")
        except Exception as error:
            logger.error(f"Error HTTP en página {pagina}: {error}")
            resultado.error_global = (
                f"Error HTTP al solicitar el listado (página {pagina}): {error}"
            )
            resultado.pagina_alcanzada = pagina
            return resultado

        resultado.paginas_solicitadas += 1
        resultado.pagina_alcanzada = pagina
        html = respuesta.text

        # Log 2: Comparar HTML entre páginas (primeros 500 chars de CADA página)
        logger.info(
            f"Página {pagina}: HTML primeros 500 chars = {html[:500]}"
        )

        # Log 3: Extraer href completo del enlace "Siguiente"
        _log_enlace_siguiente(html, pagina)

        # Detectar listado vacío
        if _es_listado_vacio(html):
            logger.info("Listado vacío detectado")
            resultado.total = 0
            resultado.codigos = []
            return resultado

        # Extraer total y rango
        try:
            total = _extraer_total(html)
            logger.debug(f"Total extraído: {total} resultados")
        except ErrorListado as error:
            logger.error(f"Error al extraer total: {error}")
            resultado.error_global = str(error)
            return resultado
        resultado.total = total

        # Extraer códigos de la página
        codigos_pagina = _extraer_codigos(html)
        codigos_nuevos = [
            c for c in codigos_pagina
            if c not in vistos and c not in resultado.codigos
        ]
        codigos_duplicados = [
            c for c in codigos_pagina
            if c in vistos or c in resultado.codigos
        ]
        logger.info(
            f"Página {pagina}: extraídos={len(codigos_pagina)}, "
            f"nuevos={len(codigos_nuevos)}, duplicados={len(codigos_duplicados)}, "
            f"total_únicos_acumulados={len(resultado.codigos)}, "
            f"total_declarado_portal={total}"
        )
        logger.debug(f"Códigos extraídos de página {pagina}: {len(codigos_pagina)}")
        for codigo in codigos_pagina:
            if codigo not in vistos and codigo not in resultado.codigos:
                resultado.codigos.append(codigo)

        logger.info(
            f"Antes de _es_ultima_pagina: página={pagina}, "
            f"códigos_únicos={len(resultado.codigos)}, total_portal={total}"
        )

        # Si ya hemos alcanzado el total, o es la última página, terminar
        if _es_ultima_pagina(html):
            logger.info(f"Última página detectada en página {pagina}")
            return resultado

        if len(resultado.codigos) >= total:
            logger.info(f"Total de códigos alcanzado: {len(resultado.codigos)} >= {total}")
            return resultado

        logger.debug(f"Avanzando a página {pagina + 1}")
        pagina += 1


def _construir_url(url_base: str, tamano_pagina: int, pagina: int) -> str:
    """Construye la URL completa del listado con todos los parámetros necesarios para Liferay."""
    # Prefijo común para todos los parámetros del portlet
    prefijo = "_es_gobcantabria_liferay_empleacan_buscador_ofertas_EmpleacanBuscadorOfertasPortlet_"
    
    # Separador inicial (? si no hay query string, & si ya existe)
    separador = "&" if ("?" in url_base or "&" in url_base) else "?"
    
    # Construir URL con todos los parámetros necesarios
    url = (
        f"{url_base}{separador}"
        # Parámetros base de Liferay
        f"p_p_id=es_gobcantabria_liferay_empleacan_buscador_ofertas_EmpleacanBuscadorOfertasPortlet&"
        f"p_p_lifecycle=0&"
        f"p_p_state=normal&"
        f"p_p_mode=view&"
        # Parámetros de filtro (vacíos excepto provincia)
        f"{prefijo}keyword=&"
        f"{prefijo}provincia=39&"
        f"{prefijo}municipio=&"
        f"{prefijo}fechaInicioDifusion=&"
        f"{prefijo}fechaFinDifusion=&"
        f"{prefijo}sector=&"
        f"{prefijo}nivelProfesional=&"
        f"{prefijo}tipoSalario=&"
        f"{prefijo}cuantia=&"
        f"{prefijo}tipoContrato=&"
        f"{prefijo}nivelFormativo=&"
        f"{prefijo}resetCur=false&"
        # Parámetros de paginación
        f"{prefijo}delta={tamano_pagina}&"
        f"{prefijo}cur={pagina}"
    )
    
    return url


def _es_listado_vacio(html: str) -> bool:
    """Detecta el estado de listado vacío por el contenedor oculto."""
    arbol = LexborHTMLParser(html)
    for node in arbol.css("div.lfr-search-container"):
        clases = node.attributes.get("class", "")
        if "hide" in clases:
            return True
    return False


def _extraer_total(html: str) -> int:
    """Extrae el total desde small.search-results.

    Lanza ErrorListado si no encuentra el marcador.
    """
    arbol = LexborHTMLParser(html)
    small = arbol.css_first("small.search-results")
    if small is None:
        raise ErrorListado(
            "Error de parseo del listado: no se encuentra small.search-results."
        )
    texto = small.text()
    match = _RE_RANGO.search(texto)
    if not match:
        raise ErrorListado(
            f"Error de parseo del listado: formato de rango no reconocido "
            f"en {texto!r}."
        )
    return int(match.group(3))


def _extraer_codigos(html: str) -> list[str]:
    """Extrae los códigos de oferta (12 dígitos) desde los enlaces del listado."""
    arbol = LexborHTMLParser(html)

    # Log 1: Cuántas tablas hay en el HTML
    tablas = arbol.css("table.table")
    logger.info(
        f"_extraer_codigos: encontradas {len(tablas)} tablas con clase 'table.table'"
    )

    # Log 2: Cuántas tablas con tbody.table-data
    tbodies = arbol.css("table.table tbody.table-data")
    logger.info(
        f"_extraer_codigos: encontrados {len(tbodies)} tbody con clase 'table-data'"
    )

    # Log 3: Cuántos enlaces de oferta en total (sin restricción de tabla)
    enlaces_total = arbol.css("a[href*='/ofertas-cantabria/-/oferta/']")
    logger.info(
        f"_extraer_codigos: encontrados {len(enlaces_total)} enlaces de oferta en total"
    )

    # Log 4: Cuántos enlaces dentro de table.table tbody.table-data
    enlaces_en_tabla = arbol.css(
        "table.table tbody.table-data a[href*='/ofertas-cantabria/-/oferta/']"
    )
    logger.info(
        f"_extraer_codigos: encontrados {len(enlaces_en_tabla)} enlaces "
        f"dentro de table.table tbody.table-data"
    )

    # Log 5: Extraer códigos y mostrar los primeros 5
    codigos: list[str] = []
    for enlace in enlaces_en_tabla:
        codigo = enlace.text(strip=True)
        if len(codigo) == 12 and codigo.isdigit():
            codigos.append(codigo)

    logger.info(f"_extraer_codigos: extraídos {len(codigos)} códigos válidos")
    if codigos:
        logger.info(f"_extraer_codigos: primeros 5 códigos: {codigos[:5]}")

    return codigos


def _log_enlace_siguiente(html: str, pagina: int) -> None:
    """Log del href completo del enlace 'Siguiente' (diagnóstico de paginación)."""
    arbol = LexborHTMLParser(html)
    for li in arbol.css("ul.lfr-pagination-buttons li"):
        texto_li = li.text(strip=True)
        if "Siguiente" in texto_li:
            enlace = li.css_first("a")
            if enlace:
                href_completo = enlace.attributes.get("href", "")
                logger.info(
                    f"Página {pagina}: enlace 'Siguiente' href completo = {href_completo}"
                )
            else:
                logger.info(
                    f"Página {pagina}: 'Siguiente' encontrado pero sin <a> (¿desactivado?)"
                )
            break
    else:
        logger.info(
            f"Página {pagina}: no se encontró 'Siguiente' en la paginación"
        )


def _es_ultima_pagina(html: str) -> bool:
    """Detecta si la página es la última.

    Busca el enlace 'Siguiente' en la paginación:
    - Si existe y está deshabilitado, es la última página.
    - Si existe y no está deshabilitado, hay más páginas.
    - Si no existe, busca enlaces numéricos a otras páginas (no deshabilitados);
      si los hay, aún quedan páginas por recorrer.
    """
    logger.info("_es_ultima_pagina: evaluando si es última página...")
    arbol = LexborHTMLParser(html)
    lis = arbol.css("ul.lfr-pagination-buttons li")

    logger.info(f"_es_ultima_pagina: encontrados {len(lis)} elementos <li> en ul.lfr-pagination-buttons")

    for idx, li in enumerate(lis):
        texto = li.text(strip=True)
        clases = li.attributes.get("class", "")
        enlaces = li.css("a")
        for enlace in enlaces:
            texto_enlace = enlace.text(strip=True)
            logger.info(
                f"_es_ultima_pagina:   <li> #{idx}: texto='{texto[:80]}', "
                f"clases='{clases}', "
                f"enlace_texto='{texto_enlace}', href='{enlace.attributes.get('href', '')[:100]}'"
            )
        if not enlaces:
            logger.info(
                f"_es_ultima_pagina:   <li> #{idx}: texto='{texto[:80]}', "
                f"clases='{clases}', sin_enlaces"
            )

    # Buscar "Siguiente" en el texto de cada <li>
    for li in lis:
        texto_li = li.text(strip=True)
        if "Siguiente" in texto_li:
            clases = li.attributes.get("class", "")
            resultado = "disabled" in clases
            logger.info(
                f"_es_ultima_pagina: encontrado 'Siguiente' con clases='{clases}', "
                f"resultado={resultado}"
            )
            return resultado

    logger.info("_es_ultima_pagina: no se encontró 'Siguiente', buscando enlaces numéricos no deshabilitados")

    # No hay "Siguiente": buscar enlaces numéricos no deshabilitados.
    for li in lis:
        clases = li.attributes.get("class", "")
        if "disabled" in clases:
            continue
        for enlace in li.css("a"):
            texto_enlace = enlace.text(strip=True)
            if texto_enlace.isdigit():
                logger.info(
                    f"_es_ultima_pagina: encontrado enlace numérico '{texto_enlace}' "
                    f"con clases='{clases}', resultado=False (hay más páginas)"
                )
                return False

    logger.info("_es_ultima_pagina: no hay enlaces numéricos no deshabilitados, resultado=True (última página)")
    return True
