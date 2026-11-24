"""Pruebas del adaptador de parseo del PDF de difusión (TASK-007).

Cubren `source/api/integridad/parser_adapter.py`: `AdaptadorParseo` compone
**en proceso** `extraer_texto_pdf` y `extraer_ofertas` de
`source/api/parser.py`, devuelve el recuento exacto de ofertas y la comunidad
(REQ-003), convierte un `ErrorParseoPDF` en el error propio
`ErrorParseoIntegridad` sin lanzar excepción (ALT-004) y distingue un PDF
ilegible de un PDF válido sin ofertas, que da recuento cero sin error
(ALT-004). Además se comprueba que no se emite ninguna petición HTTP ni al
endpoint `GET /parse` ni a otro endpoint (SUP-005).
"""

from pathlib import Path

import httpx
import pytest

from source.api import parser
from source.api.downloader import ErrorDescarga
from source.api.integridad.downloader_adapter import (
    AdaptadorDescarga,
    ErrorDescargaIntegridad,
)
from source.api.integridad.parser_adapter import (
    AdaptadorParseo,
    ErrorParseoIntegridad,
    RecuentoPDF,
)
from source.api.parser import ErrorParseoPDF


REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_PDF = Path(__file__).parent.parent / "fixtures" / "sample.pdf"
MUESTRA = REPO_ROOT / "docs" / "contracts" / "pdf" / "ofertas_cantabria.txt"
COMUNIDAD = "cantabria"


def _escapar(texto: str) -> str:
    """Escapa los caracteres especiales de una cadena PDF."""
    return texto.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _pdf_con_lineas(lineas: list[str]) -> bytes:
    """Genera un PDF mínimo válido de una página con las líneas indicadas.

    Replica la estructura de `tests/fixtures/sample.pdf` (catálogo, páginas,
    página, flujo de contenido y fuente Helvetica) y calcula la tabla `xref`
    con los desplazamientos reales, para que `pdfplumber` lo lea como un PDF
    de difusión con ofertas conocidas.
    """
    operaciones = ["BT", "/F1 12 Tf", "72 720 Td"]
    for indice, linea in enumerate(lineas):
        if indice:
            operaciones.append("0 -18 Td")
        operaciones.append(f"({_escapar(linea)}) Tj")
    operaciones.append("ET")
    flujo = "\n".join(operaciones).encode("latin-1")

    objetos = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length "
        + str(len(flujo)).encode("ascii")
        + b" >>\nstream\n"
        + flujo
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        b"/Encoding /WinAnsiEncoding >>",
    ]

    salida = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for numero, cuerpo in enumerate(objetos, start=1):
        offsets.append(len(salida))
        salida += f"{numero} 0 obj\n".encode("ascii")
        salida += cuerpo + b"\nendobj\n"

    inicio_xref = len(salida)
    salida += f"xref\n0 {len(objetos) + 1}\n".encode("ascii")
    salida += b"0000000000 65535 f \n"
    for offset in offsets:
        salida += f"{offset:010d} 00000 n \n".encode("ascii")
    salida += (
        f"trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\n"
        f"startxref\n{inicio_xref}\n%%EOF\n"
    ).encode("ascii")
    return bytes(salida)


PDF_CON_DOS_OFERTAS = _pdf_con_lineas(
    [
        "OFERTAS DE EMPLEO EN DIFUSION",
        "Sector Profesional: ADMINISTRACION Y OFICINAS",
        "TECNICO/A DE PRUEBA",
        "Santander - CANTABRIA",
        "Oferta: 062026009001",
        "01/12/2026",
        "Oficina: SANTANDER",
        "Descripcion de la oferta de prueba uno.",
        "Sector Profesional: SERVICIOS",
        "AUXILIAR DE PRUEBA",
        "Torrelavega - CANTABRIA",
        "Oferta: 062026009002",
        "02/12/2026",
        "Oficina: TORRELAVEGA",
        "Descripcion de la oferta de prueba dos.",
    ]
)


class DobleExtractorOfertas:
    """Doble del extractor de ofertas que guarda cómo se le invocó."""

    def __init__(self, ofertas: list[object]) -> None:
        self.ofertas = ofertas
        self.llamadas: list[tuple[str, str]] = []

    def __call__(self, texto: str, comunidad: str = "") -> list[object]:
        self.llamadas.append((texto, comunidad))
        return self.ofertas


# --- Recuento exacto y comunidad (REQ-003) ---------------------------------


def test_un_pdf_valido_con_ofertas_devuelve_el_recuento_exacto_y_la_comunidad() -> None:
    """Un PDF con dos ofertas conocidas da recuento 2 y la comunidad (REQ-003)."""
    resultado = AdaptadorParseo().parsear(PDF_CON_DOS_OFERTAS, COMUNIDAD)

    assert resultado == RecuentoPDF(recuento=2, comunidad=COMUNIDAD)
    assert isinstance(resultado, RecuentoPDF)
    assert resultado.recuento == 2
    assert resultado.comunidad == COMUNIDAD


def test_el_recuento_coincide_con_las_ofertas_de_la_muestra_del_contrato() -> None:
    """Con el texto real de la muestra (92 ofertas) el recuento es exacto."""
    texto = MUESTRA.read_text(encoding="utf-8")
    esperadas = sum(
        1 for linea in texto.splitlines() if linea.strip().startswith("Oferta:")
    )

    resultado = AdaptadorParseo(extractor_texto=lambda contenido: texto).parsear(
        b"contenido simulado", COMUNIDAD
    )

    assert isinstance(resultado, RecuentoPDF)
    assert resultado.recuento == esperadas == 92
    assert resultado.comunidad == COMUNIDAD


def test_compone_las_dos_funciones_publicas_en_proceso() -> None:
    """Extrae primero el texto y después las ofertas con la comunidad."""
    ofertas = DobleExtractorOfertas([object(), object(), object()])

    resultado = AdaptadorParseo(
        extractor_texto=lambda contenido: "texto limpio",
        extractor_ofertas=ofertas,
    ).parsear(b"contenido", COMUNIDAD)

    assert resultado == RecuentoPDF(recuento=3, comunidad=COMUNIDAD)
    assert ofertas.llamadas == [("texto limpio", COMUNIDAD)]


# --- PDF ilegible y PDF válido sin ofertas (ALT-004) ------------------------


def test_bytes_que_no_son_un_pdf_devuelven_un_error_controlado() -> None:
    """Bytes no PDF se traducen a `ErrorParseoIntegridad`, sin excepción."""
    resultado = AdaptadorParseo().parsear(b"esto no es un PDF", COMUNIDAD)

    assert isinstance(resultado, ErrorParseoIntegridad)
    assert not isinstance(resultado, RecuentoPDF)
    assert "Error de parseo" in resultado.motivo
    assert resultado.mensaje == resultado.motivo


def test_un_pdf_valido_sin_ofertas_devuelve_recuento_cero_sin_error() -> None:
    """Un PDF legible sin ofertas no es un error: recuento 0 (ALT-004)."""
    resultado = AdaptadorParseo().parsear(SAMPLE_PDF.read_bytes(), COMUNIDAD)

    assert resultado == RecuentoPDF(recuento=0, comunidad=COMUNIDAD)
    assert isinstance(resultado, RecuentoPDF)
    assert not isinstance(resultado, ErrorParseoIntegridad)


def test_el_fallo_del_extractor_de_texto_se_convierte_sin_excepcion() -> None:
    """Un `ErrorParseoPDF` del extractor se devuelve como error propio."""

    def lanzar_error(contenido: bytes) -> str:
        raise ErrorParseoPDF("Error de parseo: PDF no válido o ilegible.")

    resultado = AdaptadorParseo(extractor_texto=lanzar_error).parsear(
        b"no es un PDF", COMUNIDAD
    )

    assert isinstance(resultado, ErrorParseoIntegridad)
    assert resultado.motivo == "Error de parseo: PDF no válido o ilegible."


def test_el_error_de_parseo_es_distinguible_del_error_de_descarga() -> None:
    """ALT-004: cada adaptador devuelve su propio tipo de error controlado."""
    error_parseo = AdaptadorParseo().parsear(b"no es un PDF", COMUNIDAD)
    error_descarga = AdaptadorDescarga(
        descargador=lambda url, *, cliente=None: ErrorDescarga(
            "Error de descarga: HTTP 500."
        )
    ).descargar("https://ejemplo.test/difusion.pdf")

    assert isinstance(error_parseo, ErrorParseoIntegridad)
    assert isinstance(error_descarga, ErrorDescargaIntegridad)
    assert not isinstance(error_parseo, ErrorDescargaIntegridad)
    assert not isinstance(error_descarga, ErrorParseoIntegridad)
    assert error_parseo.motivo == "Error de parseo: PDF no válido o ilegible."
    assert error_descarga.mensaje == "Error de descarga: HTTP 500."


# --- Sin peticiones HTTP a la API (SUP-005) --------------------------------


def test_no_emite_ninguna_peticion_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """El parser se invoca en proceso: ninguna llamada a `GET /parse` (SUP-005)."""

    def prohibido(*args: object, **kwargs: object) -> None:
        raise AssertionError("no debe emitirse ninguna peticion HTTP")

    monkeypatch.setattr(httpx.Client, "send", prohibido)
    monkeypatch.setattr(httpx.Client, "request", prohibido)
    monkeypatch.setattr(httpx, "get", prohibido)
    monkeypatch.setattr(httpx, "post", prohibido)

    resultado = AdaptadorParseo().parsear(PDF_CON_DOS_OFERTAS, COMUNIDAD)

    assert isinstance(resultado, RecuentoPDF)
    assert resultado.recuento == 2


# --- Sin cambios en los módulos existentes ---------------------------------


def test_no_modifica_el_parser_ni_el_ensamblador() -> None:
    """Usar el adaptador solo lee el parser y el ensamblador existentes."""
    protegidos = [
        REPO_ROOT / "source" / "api" / "parser.py",
        REPO_ROOT / "source" / "api" / "assembler.py",
    ]
    antes = [ruta.stat().st_mtime_ns for ruta in protegidos]

    resultado = AdaptadorParseo().parsear(PDF_CON_DOS_OFERTAS, COMUNIDAD)

    assert isinstance(resultado, RecuentoPDF)
    assert [ruta.stat().st_mtime_ns for ruta in protegidos] == antes
    assert parser.extraer_texto_pdf is not None
