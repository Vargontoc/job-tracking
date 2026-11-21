"""Pruebas unitarias de la segmentación de ofertas."""

from pathlib import Path

from source.api.parser import segmentar_ofertas


MUESTRA = (
    Path(__file__).parents[2]
    / "docs"
    / "contracts"
    / "pdf"
    / "ofertas_cantabria.txt"
)


def test_segmenta_todas_las_ofertas_de_la_muestra() -> None:
    texto = MUESTRA.read_text(encoding="utf-8")

    ofertas = segmentar_ofertas(texto)
    esperadas = [
        linea for linea in texto.splitlines() if linea.strip().startswith("Oferta:")
    ]

    assert len(ofertas) == len(esperadas)
    assert [oferta.lineas[0] for oferta in ofertas] == esperadas


def test_asigna_el_sector_precedente_a_cada_oferta() -> None:
    texto = MUESTRA.read_text(encoding="utf-8")
    sector_actual = ""
    sectores_por_codigo = {}
    for linea in texto.splitlines():
        if linea.startswith("Sector Profesional:"):
            sector_actual = linea.split(":", maxsplit=1)[1].strip()
        elif linea.startswith("Oferta:"):
            sectores_por_codigo[linea] = sector_actual

    ofertas = segmentar_ofertas(texto)

    assert all(oferta.sector_profesional for oferta in ofertas)
    assert all(
        oferta.sector_profesional == sectores_por_codigo[oferta.lineas[0]]
        for oferta in ofertas
    )


def test_no_hereda_sector_si_la_oferta_lo_precede() -> None:
    ofertas = segmentar_ofertas(
        "Título sin sector\nOferta: 0001\nDescripción"
    )

    assert ofertas[0].sector_profesional == ""


def test_incorpora_el_texto_final_a_la_ultima_oferta() -> None:
    texto = MUESTRA.read_text(encoding="utf-8")
    lineas = texto.splitlines()
    ultima_linea_de_oferta = next(
        linea
        for linea in reversed(lineas)
        if not linea.startswith("Ofertas en difusión a fecha")
    )
    ofertas = segmentar_ofertas(texto)

    assert ofertas[-1].lineas[-1] == ultima_linea_de_oferta
