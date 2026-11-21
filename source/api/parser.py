"""Extracción y segmentación de los PDFs de difusión."""

from dataclasses import dataclass
from io import BytesIO
import re

import pdfplumber

from source.api.models import Oferta, SectorProfesional


PIE_DE_PAGINA = re.compile(
    r"^Ofertas\s+en\s+difusión\s+a\s+fecha\b.*?\bPágina\s+\d+\s+de\s+\d+\s*$",
    re.IGNORECASE,
)
ENCABEZADO_SECTOR = re.compile(r"^Sector Profesional:\s*(.+?)\s*$")
INICIO_OFERTA = re.compile(r"^Oferta:\s*\S+")
CODIGO_OFERTA = re.compile(r"^Oferta:\s*(\S+)")
FECHA = re.compile(r"^\d{2}/\d{2}/\d{4}$")
MUNICIPIO = re.compile(r"^(.+?)\s*\(\s*[^)]+\s*\)\s*$")


class ErrorParseoPDF(Exception):
    """Indica que no se pudo extraer el texto de un PDF."""


@dataclass(frozen=True)
class OfertaSegmentada:
    """Bloque de una oferta y el sector profesional al que pertenece."""

    sector_profesional: str
    texto: str
    prefijo: tuple[str, ...] = ()

    @property
    def lineas(self) -> list[str]:
        """Devuelve las líneas del bloque conservando su orden."""
        return self.texto.splitlines()


def extraer_texto_pdf(contenido: bytes) -> str:
    """Extrae y limpia el texto de todas las páginas de un PDF."""
    try:
        with pdfplumber.open(BytesIO(contenido)) as pdf:
            lineas = [
                linea
                for pagina in pdf.pages
                for linea in (pagina.extract_text() or "").splitlines()
                if not PIE_DE_PAGINA.match(linea.strip())
            ]
    except Exception as error:
        raise ErrorParseoPDF("Error de parseo: PDF no válido o ilegible.") from error

    return "\n".join(lineas)


def segmentar_ofertas(texto: str) -> list[OfertaSegmentada]:
    """Separa las ofertas y les asigna el sector profesional precedente."""
    sector_actual = ""
    lineas_oferta: list[str] | None = None
    prefijo_oferta: list[str] = []
    lineas_anteriores: list[str] = []
    ofertas = []

    for linea in texto.splitlines():
        linea_limpia = linea.strip()
        encabezado_sector = ENCABEZADO_SECTOR.match(linea_limpia)

        if PIE_DE_PAGINA.match(linea_limpia) or encabezado_sector:
            if lineas_oferta is not None:
                ofertas.append(
                    OfertaSegmentada(
                        sector_actual,
                        "\n".join(lineas_oferta),
                        tuple(prefijo_oferta),
                    )
                )
                lineas_oferta = None
            lineas_anteriores = []
            if encabezado_sector:
                sector_actual = encabezado_sector.group(1)
            continue

        if INICIO_OFERTA.match(linea_limpia):
            if lineas_oferta is not None:
                ofertas.append(
                    OfertaSegmentada(
                        sector_actual,
                        "\n".join(lineas_oferta),
                        tuple(prefijo_oferta),
                    )
                )
                prefijo_oferta = _municipio_previo(lineas_oferta)
            else:
                prefijo_oferta = lineas_anteriores
            lineas_oferta = [linea]
        elif lineas_oferta is not None:
            lineas_oferta.append(linea)
        else:
            lineas_anteriores.append(linea)

    if lineas_oferta is not None:
        ofertas.append(
            OfertaSegmentada(
                sector_actual,
                "\n".join(lineas_oferta),
                tuple(prefijo_oferta),
            )
        )

    return ofertas


def extraer_ofertas(texto: str, comunidad: str = "") -> list[Oferta]:
    """Extrae los campos de todas las ofertas presentes en texto limpio."""
    return [
        extraer_campos_oferta(segmento, comunidad)
        for segmento in segmentar_ofertas(texto)
    ]


def extraer_ofertas_desde_pdf(
    contenido: bytes,
    comunidad: str = "",
) -> list[Oferta]:
    """Extrae ofertas de un PDF, o una lista vacía si no contiene texto útil."""
    try:
        texto = extraer_texto_pdf(contenido)
    except ErrorParseoPDF:
        return []
    return extraer_ofertas(texto, comunidad)


def extraer_campos_oferta(
    segmento: OfertaSegmentada,
    comunidad: str = "",
) -> Oferta:
    """Construye una oferta con los campos presentes en un segmento."""
    municipio = ""
    indice_municipio = len(segmento.prefijo)
    for indice, linea in enumerate(segmento.prefijo):
        coincidencia = MUNICIPIO.match(linea.strip())
        if coincidencia:
            municipio = coincidencia.group(1).strip()
            indice_municipio = indice

    denominacion = " ".join(
        linea.strip() for linea in segmento.prefijo[:indice_municipio] if linea.strip()
    )
    lineas = segmento.lineas
    codigo = _codigo_de_oferta(lineas)
    indice_fecha = _indice_fecha(lineas)
    indice_oficina, oficina = _oficina(lineas)
    inicio_descripcion = (
        indice_oficina + 1
        if indice_oficina is not None
        else (indice_fecha + 1 if indice_fecha is not None else 1)
    )
    descripcion = " ".join(
        linea.strip() for linea in lineas[inicio_descripcion:] if linea.strip()
    )

    return Oferta(
        denominacion=denominacion,
        municipio=municipio,
        codigo_oferta=codigo,
        fecha_publicacion=(
            lineas[indice_fecha].strip() if indice_fecha is not None else ""
        ),
        oficina=oficina,
        descripcion=descripcion,
        sector_profesional=SectorProfesional(segmento.sector_profesional),
        comunidad=comunidad,
    )


def _municipio_previo(lineas: list[str]) -> list[str]:
    for linea in reversed(lineas):
        if MUNICIPIO.match(linea.strip()):
            return [linea]
    return []


def _codigo_de_oferta(lineas: list[str]) -> str:
    for linea in lineas:
        coincidencia = CODIGO_OFERTA.match(linea.strip())
        if coincidencia:
            return coincidencia.group(1)
    return ""


def _indice_fecha(lineas: list[str]) -> int | None:
    for indice, linea in enumerate(lineas):
        if FECHA.match(linea.strip()):
            return indice
    return None


def _oficina(lineas: list[str]) -> tuple[int | None, str]:
    for indice, linea in enumerate(lineas):
        if linea.strip().startswith("Oficina:"):
            return indice, linea.split(":", maxsplit=1)[1].strip()
    return None, ""
