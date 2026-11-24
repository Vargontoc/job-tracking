"""Adaptador de recuento de ofertas del PDF sobre el parser en proceso.

Envuelve `source/api/parser.py` para que la comprobación de integridad reciba
el recuento de ofertas del PDF de difusión o un error propio y controlado
(`ErrorParseoIntegridad`). Se compone **en proceso** con las dos funciones
públicas del parser —`extraer_texto_pdf` y `extraer_ofertas`—, sin reescribir
la lógica de parseo y sin emitir ninguna petición HTTP al endpoint `GET /parse`
ni a ningún otro endpoint de la API (SUP-005).

La composición distingue el PDF ilegible del PDF válido sin ofertas (ALT-004):
`extraer_texto_pdf` lanza `ErrorParseoPDF` cuando el documento no se puede
leer, mientras que un PDF legible sin ninguna oferta devuelve un recuento cero
sin error. Un PDF con parseo fallido se conserva y se marca con veredicto
`fallido` (DEC-002); el recuento cero lo resolverá el comparador aplicando el
umbral de cordura.
"""

from collections.abc import Callable
from dataclasses import dataclass

from source.api.models import Oferta
from source.api.parser import ErrorParseoPDF, extraer_ofertas, extraer_texto_pdf


ExtractorTexto = Callable[[bytes], str]
ExtractorOfertas = Callable[..., list[Oferta]]


@dataclass(frozen=True)
class ErrorParseoIntegridad:
    """Fallo controlado al parsear el PDF de difusión (ALT-004).

    Es propio de la integridad y distinto del `ErrorDescargaIntegridad`, de
    modo que quien orquesta la comprobación puede separar un fallo de descarga
    de uno de parseo por el tipo del resultado, sin propagar excepciones. El
    motivo es el mensaje de `ErrorParseoPDF`.
    """

    motivo: str

    @property
    def mensaje(self) -> str:
        """Alias de `motivo`, simétrico al error de descarga."""
        return self.motivo


@dataclass(frozen=True)
class RecuentoPDF:
    """Recuento de ofertas extraídas del PDF y comunidad de origen (REQ-003)."""

    recuento: int
    comunidad: str


class AdaptadorParseo:
    """Extrae el recuento de ofertas del PDF con el parser en proceso (REQ-003).

    Args:
        extractor_texto: función que extrae el texto del PDF y lanza
            `ErrorParseoPDF` si el documento no es legible. Por defecto,
            `source.api.parser.extraer_texto_pdf`. Es inyectable para las
            pruebas.
        extractor_ofertas: función que extrae las ofertas de un texto limpio.
            Por defecto, `source.api.parser.extraer_ofertas`. Es inyectable
            para las pruebas.
    """

    def __init__(
        self,
        extractor_texto: ExtractorTexto = extraer_texto_pdf,
        extractor_ofertas: ExtractorOfertas = extraer_ofertas,
    ) -> None:
        self._extractor_texto = extractor_texto
        self._extractor_ofertas = extractor_ofertas

    def parsear(
        self,
        contenido: bytes,
        comunidad: str,
    ) -> RecuentoPDF | ErrorParseoIntegridad:
        """Devuelve el recuento y la comunidad, o un error controlado."""
        try:
            texto = self._extractor_texto(contenido)
        except ErrorParseoPDF as error:
            return ErrorParseoIntegridad(motivo=str(error))
        ofertas = self._extractor_ofertas(texto, comunidad)
        return RecuentoPDF(recuento=len(ofertas), comunidad=comunidad)
