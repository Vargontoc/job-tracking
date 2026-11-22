"""Adaptador del listado oficial de códigos del PDF."""

from collections import Counter
from dataclasses import dataclass, field

from source.api.downloader import ErrorDescarga, descargar_pdf
from source.api.parser import extraer_ofertas_desde_pdf


@dataclass(frozen=True)
class ListadoPDF:
    """Listado oficial de códigos de oferta extraído del PDF de difusión.

    Atributos:
        codigos: Conjunto de códigos de oferta publicados.
        fecha_listado: Fecha del listado (formato dd/mm/aaaa).
    """

    codigos: set[str] = field(default_factory=set)
    fecha_listado: str = ""


@dataclass(frozen=True)
class ErrorListadoPDF:
    """Fallo controlado al obtener el listado oficial del PDF.

    Atributos:
        motivo: Descripción del fallo.
    """

    motivo: str = ""


class AdaptadorListadoPDF:
    """Adaptador que obtiene el listado oficial de códigos del PDF de difusión.

    Invoca en proceso el downloader y el parser, sin llamadas HTTP externas.
    """

    def __init__(self, url_pdf: str, comunidad: str) -> None:
        self._url_pdf = url_pdf
        self._comunidad = comunidad

    def obtener_listado(self) -> ListadoPDF | ErrorListadoPDF:
        """Descarga el PDF, extrae las ofertas y devuelve el listado de códigos.

        Devuelve ErrorListadoPDF si la descarga falla, el parseo no produce
        ofertas o no se encuentra ningún código de oferta.
        """
        contenido_pdf = descargar_pdf(self._url_pdf)
        if isinstance(contenido_pdf, ErrorDescarga):
            return ErrorListadoPDF(
                motivo=f"Error de descarga del PDF: {contenido_pdf.mensaje}"
            )

        ofertas = extraer_ofertas_desde_pdf(contenido_pdf, self._comunidad)
        if not ofertas:
            return ErrorListadoPDF(
                motivo="El parseo del PDF no produjo ninguna oferta."
            )

        codigos = {
            oferta.codigo_oferta
            for oferta in ofertas
            if oferta.codigo_oferta
        }
        if not codigos:
            return ErrorListadoPDF(
                motivo="El parseo del PDF no produjo ningún código de oferta."
            )

        fecha_listado = _fecha_mas_frecuente(ofertas)

        return ListadoPDF(codigos=codigos, fecha_listado=fecha_listado)


def _fecha_mas_frecuente(ofertas) -> str:
    """Devuelve la fecha de publicación más frecuente entre las ofertas."""
    fechas = [oferta.fecha_publicacion for oferta in ofertas if oferta.fecha_publicacion]
    if not fechas:
        return ""
    return Counter(fechas).most_common(1)[0][0]
