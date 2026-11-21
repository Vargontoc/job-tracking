"""Entidades de dominio del rastreador del buscador HTML de Emplea Cantabria."""

from dataclasses import dataclass, field


@dataclass
class ConfigBuscador:
    """Configuración del rastreador del buscador HTML.

    Atributos:
        hora_pasada: Hora del día para la pasada automática (0-23).
        url_listado: URL del listado paginado del buscador.
        url_ficha: URL base para las fichas de oferta.
        user_agent: User-Agent identificable del proyecto.
        delay_peticiones: Segundos mínimos entre peticiones al portal.
        tamano_pagina: Número de ofertas por página del listado.
        ruta_seen_codes: Ruta al fichero JSON de códigos vistos.
        ruta_failed_htmls: Ruta al directorio de HTML fallidos.
        dias_purga: Número de días para purgar HTML fallidos.
    """

    hora_pasada: int = 1
    url_listado: str = ""
    url_ficha: str = ""
    user_agent: str = ""
    delay_peticiones: int = 10
    tamano_pagina: int = 75
    ruta_seen_codes: str = ""
    ruta_failed_htmls: str = ""
    dias_purga: int = 7


@dataclass
class OfertaBuscador:
    """Oferta extraída de una ficha del buscador HTML.

    Los campos publicados por la ficha del portal son los ocho primeros.
    Los campos sector, nivel y contrato se mantienen en el modelo pero siempre
    se devuelven vacíos (DEC-009) porque la ficha no los publica.

    Atributos:
        numero_oferta: Código de oferta de 12 dígitos.
        ocupacion: Título o denominación del puesto.
        municipio: Localidad de la oferta.
        provincia: Provincia de la oferta.
        fecha_inicio_difusion: Fecha de inicio de difusión (dd/mm/aaaa).
        fecha_fin_difusion: Fecha de fin de difusión (dd/mm/aaaa).
        texto_libre: Descripción detallada de la oferta.
        contacto: Información de contacto.
        comunidad: Comunidad autónoma (por defecto "Cantabria").
        sector: Sector profesional (siempre vacío, DEC-009).
        nivel: Nivel de estudios requerido (siempre vacío, DEC-009).
        contrato: Tipo de contrato (siempre vacío, DEC-009).
    """

    numero_oferta: str = ""
    ocupacion: str = ""
    municipio: str = ""
    provincia: str = ""
    fecha_inicio_difusion: str = ""
    fecha_fin_difusion: str = ""
    texto_libre: str = ""
    contacto: str = ""
    comunidad: str = "Cantabria"
    sector: str = ""
    nivel: str = ""
    contrato: str = ""


@dataclass
class CodigoVisto:
    """Código de oferta cuya ficha se parseó correctamente.

    Se almacena en state-store para filtrar novedades en pasadas posteriores.

    Atributos:
        codigo: Código de oferta de 12 dígitos.
    """

    codigo: str = ""


@dataclass
class HtmlFallido:
    """HTML original de una ficha cuyo parseo falló.

    El nombre del fichero sigue el formato <codigo>_<yyyy-mm-dd>.html.

    Atributos:
        codigo: Código de oferta de 12 dígitos.
        fecha: Fecha del fallo en formato ISO (yyyy-mm-dd).
        html: Contenido HTML completo recibido del portal.
    """

    codigo: str = ""
    fecha: str = ""
    html: str = ""


@dataclass
class ErrorOferta:
    """Error ocurrido al procesar una oferta específica.

    Atributos:
        codigo: Código de oferta que provocó el error.
        mensaje: Descripción del error.
    """

    codigo: str = ""
    mensaje: str = ""


@dataclass
class ResultadoPasada:
    """Resultado estructurado de una pasada del rastreador.

    Atributos:
        timestamp: Marca de tiempo ISO del inicio de la pasada.
        comunidad: Comunidad rastreada.
        total_listado: Total de ofertas encontradas en el listado.
        error_global: Error que impidió completar la pasada (vacío si no hay).
        errores_por_oferta: Lista de errores por oferta individual.
        ofertas_nuevas: Lista de ofertas nuevas parseadas correctamente.
    """

    timestamp: str = ""
    comunidad: str = "Cantabria"
    total_listado: int = 0
    error_global: str = ""
    errores_por_oferta: list[ErrorOferta] = field(default_factory=list)
    ofertas_nuevas: list[OfertaBuscador] = field(default_factory=list)
