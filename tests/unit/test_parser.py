"""Pruebas unitarias de extracción y limpieza de PDFs."""

from pathlib import Path

import pytest

from source.api import parser
from source.api.parser import (
    ErrorParseoPDF,
    extraer_ofertas,
    extraer_ofertas_desde_pdf,
    extraer_texto_pdf,
)


SAMPLE_PDF = Path(__file__).parents[1] / "fixtures" / "sample.pdf"
MUESTRA = (
    Path(__file__).parents[2]
    / "docs"
    / "contracts"
    / "pdf"
    / "ofertas_cantabria.txt"
)


def test_extrae_texto_de_todas_las_paginas_en_orden() -> None:
    texto = extraer_texto_pdf(SAMPLE_PDF.read_bytes())

    assert texto
    assert texto.index("Titulo de oferta: COCINERO/A") < texto.index(
        "Descripcion: comienzo de la oferta"
    )
    assert texto.index("Descripcion: comienzo de la oferta") < texto.index(
        "resto de la descripcion"
    )
    assert texto.index("resto de la descripcion") < texto.index(
        "sin huecos ni duplicados"
    )


def test_elimina_los_pies_de_pagina() -> None:
    texto = extraer_texto_pdf(SAMPLE_PDF.read_bytes())

    assert "Ofertas en difusión a fecha" not in texto


def test_informa_error_controlado_para_bytes_que_no_son_pdf() -> None:
    with pytest.raises(ErrorParseoPDF, match="Error de parseo"):
        extraer_texto_pdf(b"esto no es un PDF")


def test_extrae_los_campos_presentes_de_una_oferta() -> None:
    oferta = extraer_ofertas(MUESTRA.read_text(encoding="utf-8"))[0]

    assert oferta.codigo_oferta == "062026003484"
    assert oferta.fecha_publicacion == "04/11/2026"
    assert oferta.oficina == "TORRELAVEGAs"
    assert oferta.municipio == "Torrelavega"
    assert oferta.denominacion == (
        "1 DIRECTOR/A DE FÁBRICA CON GESTIÓN COMERCIAL Y DESARROLLO "
        "DE NEGOCIO."
    )
    assert "EMPRESA DEDICADA A LA FABRICACIÓN" in oferta.descripcion
    assert not hasattr(oferta, "empresa")


def test_deja_vacia_la_oficina_ausente_y_admite_lineas_irregulares() -> None:
    oferta = extraer_ofertas(
        "\n".join(
            [
                "Sector Profesional: SERVICIOS",
                "TÍTULO DE PRUEBA",
                "Santander ( CANTABRIA )",
                "Oferta: 0001",
                "01/01/2026",
                "Descripción en la misma línea que el título no impide el parseo.",
            ]
        )
    )[0]

    assert oferta.oficina == ""
    assert oferta.descripcion == (
        "Descripción en la misma línea que el título no impide el parseo."
    )


def test_textos_sin_ofertas_devuelven_una_lista_vacia() -> None:
    assert extraer_ofertas("") == []
    assert extraer_ofertas("Texto sin ofertas") == []
    assert extraer_ofertas("Sector Profesional: SERVICIOS") == []


def test_pdf_sin_texto_extraible_devuelve_una_lista_vacia(monkeypatch) -> None:
    monkeypatch.setattr(parser, "extraer_texto_pdf", lambda contenido: "")

    assert extraer_ofertas_desde_pdf(b"%PDF") == []


def test_pdf_no_parseable_devuelve_una_lista_vacia(monkeypatch) -> None:
    def lanzar_error(contenido: bytes) -> str:
        raise ErrorParseoPDF("PDF no válido")

    monkeypatch.setattr(parser, "extraer_texto_pdf", lanzar_error)

    assert extraer_ofertas_desde_pdf(b"no es un PDF") == []
