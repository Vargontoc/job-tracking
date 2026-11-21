"""Parseo de fichas de oferta del buscador de Emplea Cantabria."""

import logging
import re
from dataclasses import dataclass
from typing import Protocol

from selectolax.lexbor import LexborHTMLParser

from source.api.buscador.models import OfertaBuscador
from source.api.buscador.rate_limiter import LimitadorPeticiones

logger = logging.getLogger(__name__)


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
class ResultadoFicha:
    """Resultado del parseo de una ficha.

    Atributos:
        oferta: Oferta parseada si el parseo fue exitoso, None en caso contrario.
        html: HTML original de la ficha (solo se conserva si hubo error).
        error: Mensaje de error si el parseo falló, vacío si fue exitoso.
    """

    oferta: OfertaBuscador | None = None
    html: str = ""
    error: str = ""


def parsear_ficha(
    cliente: ClienteHTTP,
    url_base: str,
    codigo: str,
    limitador: LimitadorPeticiones,
    timeout: float = 30.0,
    max_intentos: int = 2,
) -> ResultadoFicha:
    """Descarga y parsea la ficha de una oferta.

    Args:
        cliente: Cliente HTTP síncrono (compatible con httpx.Client).
        url_base: URL base de las fichas (sin el código final).
        codigo: Código de oferta de 12 dígitos.
        limitador: Limitador de peticiones compartido (DEC-003).
        timeout: Timeout de la petición HTTP en segundos.
        max_intentos: Número máximo de intentos (por defecto 2, DEC-007).

    Returns:
        ResultadoFicha con la oferta parseada si fue exitoso,
        o con el HTML y mensaje de error si falló.
    """
    logger.debug(f"INICIO parsear_ficha para código {codigo}")
    url = f"{url_base.rstrip('/')}/{codigo}"
    ultimo_html = ""
    ultimo_error = ""

    for intento in range(max_intentos):
        logger.debug(f"Intento {intento + 1}/{max_intentos} para ficha {codigo}")
        try:
            limitador.esperar()
            respuesta = cliente.get(url, timeout=timeout)
            html = respuesta.text  # Obtener texto PRIMERO
            ultimo_html = html  # Guardarlo inmediatamente
            respuesta.raise_for_status()  # Luego verificar status

            logger.debug(f"HTML recibido para ficha {codigo}, extrayendo campos...")
            oferta = _extraer_campos(html)
            logger.debug(f"Campos extraídos correctamente para ficha {codigo}")
            # Éxito: no conservar el HTML (REQ-010)
            return ResultadoFicha(oferta=oferta, html="", error="")

        except Exception as error:
            logger.warning(f"Error en intento {intento + 1} para ficha {codigo}: {error}")
            ultimo_error = str(error)
            # Si hay más intentos, continuar; si no, devolver error

    # Todos los intentos fallaron
    logger.error(f"TODOS los intentos fallaron para ficha {codigo}: {ultimo_error}")
    return ResultadoFicha(
        oferta=None,
        html=ultimo_html,
        error=f"Error al parsear ficha {codigo}: {ultimo_error}",
    )


def _extraer_campos(html: str) -> OfertaBuscador:
    """Extrae los campos de la ficha desde el HTML.

    Args:
        html: HTML de la ficha.

    Returns:
        OfertaBuscador con los campos extraídos.

    Raises:
        ValueError: Si no se encuentra el número de oferta (campo obligatorio).
    """
    arbol = LexborHTMLParser(html)

    # Extraer los 6 campos principales desde input[readonly]
    numero_oferta = _extraer_input(arbol, "_numeroOferta")
    ocupacion = _extraer_input(arbol, "_ocupacion")
    municipio = _extraer_input(arbol, "_municipio")
    provincia = _extraer_input(arbol, "_provincia")
    fecha_inicio = _extraer_input(arbol, "_fechaInicioDifusion")
    fecha_fin = _extraer_input(arbol, "_fechaFinDifusion")

    # Si no hay número de oferta, es un error crítico
    if not numero_oferta:
        raise ValueError("No se encontró el número de oferta en la ficha")

    # Extraer texto libre y contacto
    texto_libre = _extraer_bloque(arbol, "dAdicionales")
    contacto = _extraer_bloque(arbol, "dContacto")

    # Normalizar espacios y saltos de línea
    texto_libre = _normalizar_espacios(texto_libre)
    contacto = _normalizar_espacios(contacto)

    # Crear la oferta con los campos extraídos
    # sector/nivel/contrato siempre vacíos (DEC-009)
    return OfertaBuscador(
        numero_oferta=numero_oferta,
        ocupacion=ocupacion,
        municipio=municipio,
        provincia=provincia,
        fecha_inicio_difusion=fecha_inicio,
        fecha_fin_difusion=fecha_fin,
        texto_libre=texto_libre,
        contacto=contacto,
        comunidad="Cantabria",
        sector="",
        nivel="",
        contrato="",
    )


def _extraer_input(arbol: LexborHTMLParser, sufijo: str) -> str:
    """Extrae el valor de un input readonly por sufijo de id.

    Args:
        arbol: Árbol HTML parseado.
        sufijo: Sufijo del id del input (ej: "_numeroOferta").

    Returns:
        Valor del input, o cadena vacía si no se encuentra.
    """
    for node in arbol.css("input[readonly]"):
        node_id = node.attributes.get("id", "")
        if node_id.endswith(sufijo):
            return node.attributes.get("value", "")
    return ""


def _extraer_bloque(arbol: LexborHTMLParser, clase: str) -> str:
    """Extrae el texto de un bloque después de un label con clase específica.

    Args:
        arbol: Árbol HTML parseado.
        clase: Clase del label y div (ej: "dAdicionales" o "dContacto").

    Returns:
        Texto del bloque, o cadena vacía si no se encuentra.
    """
    # Buscar el div con la clase especificada
    for div in arbol.css(f"div.{clase}"):
        # Obtener todo el texto del div
        texto = div.text()
        if texto:
            return texto.strip()
    return ""


def _normalizar_espacios(texto: str) -> str:
    """Normaliza espacios y saltos de línea en un texto.

    Reemplaza múltiples espacios/saltos de línea consecutivos por un solo espacio.

    Args:
        texto: Texto a normalizar.

    Returns:
        Texto normalizado.
    """
    if not texto:
        return ""
    # Reemplazar saltos de línea y tabs por espacios
    texto = texto.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    # Colapsar múltiples espacios en uno solo
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()
