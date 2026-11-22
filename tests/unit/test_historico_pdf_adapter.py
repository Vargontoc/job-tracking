"""Pruebas unitarias del adaptador del listado oficial de códigos del PDF."""

from unittest.mock import patch

from source.api.downloader import ErrorDescarga
from source.api.models import Oferta, SectorProfesional
from source.api.historico.pdf_adapter import (
    AdaptadorListadoPDF,
    ErrorListadoPDF,
    ListadoPDF,
)


URL_PDF = "https://example.com/difusion.pdf"
COMUNIDAD = "cantabria"


def _oferta(codigo: str, fecha: str = "22/11/2026") -> Oferta:
    return Oferta(
        codigo_oferta=codigo,
        fecha_publicacion=fecha,
        sector_profesional=SectorProfesional("Informática"),
        comunidad=COMUNIDAD,
    )


class TestAdaptadorListadoPDFCasoExitoso:
    """El adaptador devuelve el listado de códigos cuando todo funciona."""

    @patch("source.api.historico.pdf_adapter.extraer_ofertas_desde_pdf")
    @patch("source.api.historico.pdf_adapter.descargar_pdf")
    def test_devuelve_codigos_y_fecha(self, mock_descargar, mock_parser):
        mock_descargar.return_value = b"%PDF-1.4 contenido"
        mock_parser.return_value = [
            _oferta("001234567890"),
            _oferta("009876543210"),
            _oferta("001234567890"),  # duplicado
        ]

        adaptador = AdaptadorListadoPDF(url_pdf=URL_PDF, comunidad=COMUNIDAD)
        resultado = adaptador.obtener_listado()

        assert isinstance(resultado, ListadoPDF)
        assert resultado.codigos == {"001234567890", "009876543210"}
        assert resultado.fecha_listado == "22/11/2026"

    @patch("source.api.historico.pdf_adapter.extraer_ofertas_desde_pdf")
    @patch("source.api.historico.pdf_adapter.descargar_pdf")
    def test_codigos_conservan_ceros_iniciales(self, mock_descargar, mock_parser):
        mock_descargar.return_value = b"%PDF-1.4"
        mock_parser.return_value = [
            _oferta("000000000001"),
            _oferta("000000000002"),
        ]

        adaptador = AdaptadorListadoPDF(url_pdf=URL_PDF, comunidad=COMUNIDAD)
        resultado = adaptador.obtener_listado()

        assert isinstance(resultado, ListadoPDF)
        assert "000000000001" in resultado.codigos
        assert "000000000002" in resultado.codigos
        for codigo in resultado.codigos:
            assert len(codigo) == 12

    @patch("source.api.historico.pdf_adapter.extraer_ofertas_desde_pdf")
    @patch("source.api.historico.pdf_adapter.descargar_pdf")
    def test_fecha_listado_es_la_mas_frecuente(
        self, mock_descargar, mock_parser
    ):
        mock_descargar.return_value = b"%PDF-1.4"
        mock_parser.return_value = [
            _oferta("000000000001", fecha="22/11/2026"),
            _oferta("000000000002", fecha="22/11/2026"),
            _oferta("000000000003", fecha="21/11/2026"),
        ]

        adaptador = AdaptadorListadoPDF(url_pdf=URL_PDF, comunidad=COMUNIDAD)
        resultado = adaptador.obtener_listado()

        assert isinstance(resultado, ListadoPDF)
        assert resultado.fecha_listado == "22/11/2026"

    @patch("source.api.historico.pdf_adapter.extraer_ofertas_desde_pdf")
    @patch("source.api.historico.pdf_adapter.descargar_pdf")
    def test_invoca_descargar_y_parser_en_proceso(
        self, mock_descargar, mock_parser
    ):
        mock_descargar.return_value = b"%PDF-1.4"
        mock_parser.return_value = [_oferta("000000000001")]

        adaptador = AdaptadorListadoPDF(url_pdf=URL_PDF, comunidad=COMUNIDAD)
        adaptador.obtener_listado()

        mock_descargar.assert_called_once_with(URL_PDF)
        mock_parser.assert_called_once_with(b"%PDF-1.4", COMUNIDAD)

    @patch("source.api.historico.pdf_adapter.extraer_ofertas_desde_pdf")
    @patch("source.api.historico.pdf_adapter.descargar_pdf")
    def test_ignora_ofertas_sin_codigo(self, mock_descargar, mock_parser):
        mock_descargar.return_value = b"%PDF-1.4"
        mock_parser.return_value = [
            _oferta("000000000001"),
            _oferta(""),  # sin código
            _oferta("000000000002"),
        ]

        adaptador = AdaptadorListadoPDF(url_pdf=URL_PDF, comunidad=COMUNIDAD)
        resultado = adaptador.obtener_listado()

        assert isinstance(resultado, ListadoPDF)
        assert resultado.codigos == {"000000000001", "000000000002"}


class TestAdaptadorListadoPDFFallos:
    """El adaptador informa de errores controlados en cada escenario de fallo."""

    @patch("source.api.historico.pdf_adapter.descargar_pdf")
    def test_error_de_descarga(self, mock_descargar):
        mock_descargar.return_value = ErrorDescarga(
            "Error de descarga: HTTP 404."
        )

        adaptador = AdaptadorListadoPDF(url_pdf=URL_PDF, comunidad=COMUNIDAD)
        resultado = adaptador.obtener_listado()

        assert isinstance(resultado, ErrorListadoPDF)
        assert "descarga" in resultado.motivo.lower() or "Error" in resultado.motivo

    @patch("source.api.historico.pdf_adapter.extraer_ofertas_desde_pdf")
    @patch("source.api.historico.pdf_adapter.descargar_pdf")
    def test_parser_sin_ofertas(self, mock_descargar, mock_parser):
        mock_descargar.return_value = b"%PDF-1.4"
        mock_parser.return_value = []

        adaptador = AdaptadorListadoPDF(url_pdf=URL_PDF, comunidad=COMUNIDAD)
        resultado = adaptador.obtener_listado()

        assert isinstance(resultado, ErrorListadoPDF)
        assert "oferta" in resultado.motivo.lower() or "parseo" in resultado.motivo.lower()

    @patch("source.api.historico.pdf_adapter.extraer_ofertas_desde_pdf")
    @patch("source.api.historico.pdf_adapter.descargar_pdf")
    def test_parser_sin_codigos(self, mock_descargar, mock_parser):
        mock_descargar.return_value = b"%PDF-1.4"
        mock_parser.return_value = [
            _oferta(""),
            _oferta(""),
        ]

        adaptador = AdaptadorListadoPDF(url_pdf=URL_PDF, comunidad=COMUNIDAD)
        resultado = adaptador.obtener_listado()

        assert isinstance(resultado, ErrorListadoPDF)
        assert "código" in resultado.motivo.lower() or "codigo" in resultado.motivo.lower()

    @patch("source.api.historico.pdf_adapter.extraer_ofertas_desde_pdf")
    @patch("source.api.historico.pdf_adapter.descargar_pdf")
    def test_no_realiza_llamadas_http(self, mock_descargar, mock_parser):
        """El adaptador invoca en proceso; no llama a GET /parse."""
        mock_descargar.return_value = b"%PDF-1.4"
        mock_parser.return_value = [_oferta("000000000001")]

        with patch("httpx.Client") as mock_httpx:
            adaptador = AdaptadorListadoPDF(url_pdf=URL_PDF, comunidad=COMUNIDAD)
            adaptador.obtener_listado()
            # httpx.Client no debe instanciarse para /parse
            # (solo se usa internamente en descargar_pdf, ya mockeada)
            mock_httpx.assert_not_called()
