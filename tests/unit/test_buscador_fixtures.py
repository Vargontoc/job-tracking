"""Pruebas de verificación de las muestras HTML del contrato como fixtures."""

import re
from pathlib import Path

import pytest
from selectolax.lexbor import LexborHTMLParser

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "buscador"

# Ficheros esperados
LISTADO_PAGINA_1 = FIXTURES_DIR / "listado_pagina_1.html"
LISTADO_PAGINA_2 = FIXTURES_DIR / "listado_pagina_2.html"
LISTADO_VACIO = FIXTURES_DIR / "listado_vacio.html"
LISTADO_SIN_TOTAL = FIXTURES_DIR / "listado_sin_total.html"
FICHA_062026003633 = FIXTURES_DIR / "ficha_062026003633.html"
FICHA_SIN_CONTACTO = FIXTURES_DIR / "ficha_sin_contacto.html"
FICHA_INPUTS_VACIOS = FIXTURES_DIR / "ficha_inputs_vacios.html"


@pytest.fixture
def pagina1():
    return LexborHTMLParser(LISTADO_PAGINA_1.read_text(encoding="utf-8"))


@pytest.fixture
def pagina2():
    return LexborHTMLParser(LISTADO_PAGINA_2.read_text(encoding="utf-8"))


@pytest.fixture
def listado_vacio():
    return LexborHTMLParser(LISTADO_VACIO.read_text(encoding="utf-8"))


@pytest.fixture
def ficha():
    return LexborHTMLParser(FICHA_062026003633.read_text(encoding="utf-8"))


@pytest.fixture
def ficha_sin_contacto():
    return LexborHTMLParser(FICHA_SIN_CONTACTO.read_text(encoding="utf-8"))


@pytest.fixture
def listado_sin_total():
    return LexborHTMLParser(LISTADO_SIN_TOTAL.read_text(encoding="utf-8"))


@pytest.fixture
def ficha_inputs_vacios():
    return LexborHTMLParser(FICHA_INPUTS_VACIOS.read_text(encoding="utf-8"))


def _codigo_desde_enlace(a):
    """Extrae el código de oferta del href de un enlace."""
    href = a.attributes.get("href", "")
    match = re.search(r"/oferta/(\d{12})$", href)
    return match.group(1) if match else None


def _input_por_sufijo(arbol, sufijo):
    """Busca un input readonly cuyo id termine con el sufijo dado."""
    for node in arbol.css("input[readonly]"):
        node_id = node.attributes.get("id", "")
        if node_id.endswith(f"_{sufijo}"):
            return node
    return None


# --- Existencia y legibilidad ---


@pytest.mark.parametrize(
    "ruta",
    [
        LISTADO_PAGINA_1, LISTADO_PAGINA_2, LISTADO_VACIO, LISTADO_SIN_TOTAL,
        FICHA_062026003633, FICHA_SIN_CONTACTO, FICHA_INPUTS_VACIOS,
    ],
)
def test_fixture_existe_y_es_legible(ruta):
    assert ruta.exists(), f"Fichero fixture ausente: {ruta}"
    contenido = ruta.read_text(encoding="utf-8")
    assert len(contenido) > 0, f"Fichero fixture vacío: {ruta}"


# --- Listado: página 1 ---


def test_pagina_1_declara_rango_1_a_75_de_93(pagina1):
    small = pagina1.css_first("small.search-results")
    assert small is not None, "Falta small.search-results en la página 1"
    texto = small.text(strip=True)
    assert "1 - 75" in texto, f"Rango inesperado: {texto!r}"
    assert "93" in texto, f"Total inesperado: {texto!r}"


def test_pagina_1_conserva_3_filas_con_codigos_de_12_digitos(pagina1):
    enlaces = pagina1.css("a[href*='/ofertas-cantabria/-/oferta/']")
    assert len(enlaces) == 3, f"Se esperaban 3 filas de ejemplo, hay {len(enlaces)}"
    codigos = [_codigo_desde_enlace(a) for a in enlaces]
    assert all(c is not None and len(c) == 12 for c in codigos)
    # Los códigos concretos de la muestra
    assert "062026003633" in codigos
    assert "062026003632" in codigos
    assert "062026003631" in codigos


def test_pagina_1_tiene_enlace_a_pagina_2_con_delta_75(pagina1):
    enlaces = pagina1.css("ul.lfr-pagination-buttons a")
    urls_con_delta_75_y_cur_2 = [
        a.attributes.get("href", "")
        for a in enlaces
        if "delta=75" in a.attributes.get("href", "")
        and "cur=2" in a.attributes.get("href", "")
    ]
    assert urls_con_delta_75_y_cur_2, (
        "No se encontró enlace de página 2 con delta=75 en la página 1"
    )


def test_pagina_1_tiene_tabla_con_tbody_table_data(pagina1):
    tbody = pagina1.css_first("table.table tbody.table-data")
    assert tbody is not None, "Falta tbody.table-data en la página 1"


# --- Listado: página 2 ---


def test_pagina_2_declara_rango_76_a_93_de_93(pagina2):
    small = pagina2.css_first("small.search-results")
    assert small is not None, "Falta small.search-results en la página 2"
    texto = small.text(strip=True)
    assert "76 - 93" in texto, f"Rango inesperado: {texto!r}"
    assert "93" in texto, f"Total inesperado: {texto!r}"


def test_pagina_2_conserva_3_filas_con_codigos(pagina2):
    enlaces = pagina2.css("a[href*='/ofertas-cantabria/-/oferta/']")
    assert len(enlaces) == 3, f"Se esperaban 3 filas de ejemplo, hay {len(enlaces)}"
    codigos = [_codigo_desde_enlace(a) for a in enlaces]
    assert all(c is not None and len(c) == 12 for c in codigos)
    # Los códigos concretos de la muestra
    assert "062026003487" in codigos
    assert "062026003486" in codigos
    assert "062026003485" in codigos


def test_pagina_2_no_ofrece_pagina_siguiente(pagina2):
    """La página 2 es la última: 'Siguiente' está deshabilitada."""
    lis = pagina2.css("ul.lfr-pagination-buttons li")
    siguiente_li = None
    for li in lis:
        if "Siguiente" in li.text():
            siguiente_li = li
            break
    assert siguiente_li is not None, "No se encontró 'Siguiente' en la paginación"
    clases = siguiente_li.attributes.get("class", "")
    assert "disabled" in clases, (
        "'Siguiente' debería estar deshabilitado en la última página"
    )


def test_pagina_2_delta_75(pagina2):
    """La paginación de la página 2 usa delta=75."""
    enlaces = pagina2.css("ul.lfr-pagination-buttons a")
    urls_con_delta_75 = [
        a.attributes.get("href", "")
        for a in enlaces
        if "delta=75" in a.attributes.get("href", "")
    ]
    assert urls_con_delta_75, "La página 2 no conserva el delta=75 en la paginación"


# --- Listado vacío ---


def test_listado_vacio_no_tiene_small_search_results(listado_vacio):
    small = listado_vacio.css_first("small.search-results")
    assert small is None, (
        "El listado vacío no debería tener small.search-results"
    )


def test_listado_vacio_contiene_mensaje_no_hay_resultados(listado_vacio):
    cuerpo = listado_vacio.root.html
    assert "No hay resultados" in cuerpo


def test_listado_vacio_tiene_contenedor_oculto(listado_vacio):
    """El listado vacío tiene un div.lfr-search-container con clase 'hide'."""
    contenedor = listado_vacio.css_first("div.lfr-search-container")
    assert contenedor is not None, "Falta div.lfr-search-container"
    clases = contenedor.attributes.get("class", "")
    assert "hide" in clases, (
        f"El contenedor debería tener la clase 'hide', tiene: {clases!r}"
    )


# --- Ficha ---


def test_ficha_contiene_los_6_inputs_readonly_por_sufijo(ficha):
    sufijos = [
        "numeroOferta",
        "ocupacion",
        "municipio",
        "provincia",
        "fechaInicioDifusion",
        "fechaFinDifusion",
    ]
    for sufijo in sufijos:
        input_node = _input_por_sufijo(ficha, sufijo)
        assert input_node is not None, (
            f"Falta input[readonly] con id terminando en _{sufijo}"
        )
        valor = input_node.attributes.get("value", "")
        assert valor, (
            f"El input _{sufijo} no tiene valor en el atributo 'value'"
        )


def test_ficha_conserva_valores_esperados_de_los_inputs(ficha):
    valores_esperados = {
        "numeroOferta": "062026003633",
        "municipio": "SANTANDER",
        "provincia": "CANTABRIA",
        "fechaInicioDifusion": "18/11/2026",
        "fechaFinDifusion": "03/12/2026",
    }
    for sufijo, esperado in valores_esperados.items():
        input_node = _input_por_sufijo(ficha, sufijo)
        assert input_node is not None
        assert input_node.attributes.get("value", "") == esperado, (
            f"El valor de _{sufijo} no coincide con {esperado!r}"
        )


def test_ficha_tiene_bloque_de_texto_libre(ficha):
    """El bloque de texto libre aparece tras label.dAdicionales."""
    label = None
    for node in ficha.css("label"):
        clases = node.attributes.get("class", "")
        if "dAdicionales" in clases:
            label = node
            break
    assert label is not None, "Falta label.dAdicionales en la ficha"

    # El div siguiente al label debe contener texto libre
    div_texto_libre = None
    for node in ficha.css("div"):
        clases = node.attributes.get("class", "")
        if "dAdicionales" in clases:
            div_texto_libre = node
            break
    assert div_texto_libre is not None, "Falta div.dAdicionales en la ficha"
    texto = div_texto_libre.text()
    assert texto.strip(), "El bloque de texto libre está vacío"


def test_ficha_tiene_bloque_de_contacto(ficha):
    """El bloque de contacto aparece tras label.dContacto."""
    div_contacto = None
    for node in ficha.css("div"):
        clases = node.attributes.get("class", "")
        if "dContacto" in clases:
            div_contacto = node
            break
    assert div_contacto is not None, "Falta div.dContacto en la ficha"
    texto = div_contacto.text()
    assert texto.strip(), "El bloque de contacto está vacío"


def test_ficha_no_contiene_campos_sector_nivel_ni_contrato(ficha):
    """La ficha no publica sector, nivel ni contrato (DEC-009)."""
    cuerpo = ficha.root.html.lower()
    # Comprobar que no hay inputs con sufijos de esos campos
    for sufijo in ("sector", "nivel", "contrato"):
        input_node = _input_por_sufijo(ficha, sufijo)
        assert input_node is None, (
            f"La ficha no debería tener input con sufijo _{sufijo}"
        )
    # Y que la palabra no aparece como id de input (aceptamos que aparezca en texto libre)
    for node in ficha.css("input"):
        node_id = node.attributes.get("id", "").lower()
        for sufijo in ("sector", "nivel", "contrato"):
            assert not node_id.endswith(f"_{sufijo}"), (
                f"La ficha contiene input con sufijo prohibido: {sufijo}"
            )


# --- Variante: ficha sin contacto ---


def test_ficha_sin_contacto_no_tiene_bloque_de_contacto(ficha_sin_contacto):
    """La variante sin contacto no tiene div.dContacto con texto."""
    div_contacto = None
    for node in ficha_sin_contacto.css("div"):
        clases = node.attributes.get("class", "")
        if "dContacto" in clases:
            div_contacto = node
            break
    assert div_contacto is None, (
        "La ficha sin contacto no debería tener div.dContacto"
    )


def test_ficha_sin_contacto_conserva_los_6_inputs(ficha_sin_contacto):
    """La ficha sin contacto conserva los 6 inputs con sus valores."""
    valores_esperados = {
        "numeroOferta": "062026003633",
        "ocupacion": "ORIENTADORES PROFESIONALES PARA LA INSERCIÓN",
        "municipio": "SANTANDER",
        "provincia": "CANTABRIA",
        "fechaInicioDifusion": "18/11/2026",
        "fechaFinDifusion": "03/12/2026",
    }
    for sufijo, esperado in valores_esperados.items():
        input_node = _input_por_sufijo(ficha_sin_contacto, sufijo)
        assert input_node is not None, (
            f"Falta input _{sufijo} en la ficha sin contacto"
        )
        assert input_node.attributes.get("value", "") == esperado, (
            f"El valor de _{sufijo} no coincide con {esperado!r}"
        )


def test_ficha_sin_contacto_conserva_texto_libre(ficha_sin_contacto):
    """La ficha sin contacto conserva el bloque de texto libre."""
    div_texto_libre = None
    for node in ficha_sin_contacto.css("div"):
        clases = node.attributes.get("class", "")
        if "dAdicionales" in clases:
            div_texto_libre = node
            break
    assert div_texto_libre is not None, "Falta div.dAdicionales en la ficha sin contacto"
    texto = div_texto_libre.text()
    assert texto.strip(), "El bloque de texto libre está vacío en la ficha sin contacto"
    assert "INSTITUCIÓN SOCIAL" in texto


def test_ficha_sin_contacto_parser_contacto_vacio():
    """El parser devuelve contacto vacío para la ficha sin contacto."""
    from source.api.buscador.parser import _extraer_campos

    html = FICHA_SIN_CONTACTO.read_text(encoding="utf-8")
    oferta = _extraer_campos(html)

    assert oferta.contacto == ""
    assert oferta.numero_oferta == "062026003633"
    assert oferta.municipio == "SANTANDER"


# --- Variante: listado sin total ---


def test_listado_sin_total_no_tiene_small_search_results(listado_sin_total):
    """La variante sin total no tiene small.search-results."""
    small = listado_sin_total.css_first("small.search-results")
    assert small is None, (
        "El listado sin total no debería tener small.search-results"
    )


def test_listado_sin_total_conserva_filas_y_paginacion(listado_sin_total):
    """El listado sin total conserva las filas y la paginación."""
    enlaces = listado_sin_total.css("a[href*='/ofertas-cantabria/-/oferta/']")
    assert len(enlaces) == 3, (
        f"Se esperaban 3 filas en el listado sin total, hay {len(enlaces)}"
    )
    codigos = [_codigo_desde_enlace(a) for a in enlaces]
    assert "062026003633" in codigos


def test_listado_sin_total_error_global_estructura():
    """El scraper comunica error_global cuando falta small.search-results."""
    from source.api.buscador.scraper import _extraer_total, ErrorListado

    html = LISTADO_SIN_TOTAL.read_text(encoding="utf-8")
    with pytest.raises(ErrorListado, match="small.search-results"):
        _extraer_total(html)


# --- Variante: ficha con inputs vacíos ---


def test_ficha_inputs_vacios_todos_los_inputs_tienen_value_vacio(ficha_inputs_vacios):
    """Todos los inputs readonly de la variante tienen value=""."""
    sufijos = [
        "numeroOferta",
        "ocupacion",
        "municipio",
        "provincia",
        "fechaInicioDifusion",
        "fechaFinDifusion",
    ]
    for sufijo in sufijos:
        input_node = _input_por_sufijo(ficha_inputs_vacios, sufijo)
        assert input_node is not None, (
            f"Falta input _{sufijo} en la ficha de inputs vacíos"
        )
        valor = input_node.attributes.get("value", "")
        assert valor == "", (
            f"El input _{sufijo} debería tener value='' vacío, tiene {valor!r}"
        )


def test_ficha_inputs_vacios_conserva_estructura(ficha_inputs_vacios):
    """La ficha de inputs vacíos conserva la estructura de bloques."""
    # Tiene bloques de texto libre y contacto
    div_texto_libre = None
    div_contacto = None
    for node in ficha_inputs_vacios.css("div"):
        clases = node.attributes.get("class", "")
        if "dAdicionales" in clases:
            div_texto_libre = node
        if "dContacto" in clases:
            div_contacto = node
    assert div_texto_libre is not None, "Falta div.dAdicionales"
    assert div_contacto is not None, "Falta div.dContacto"


def test_ficha_inputs_vacios_parser_campos_vacios():
    """El parser devuelve campos vacíos para la ficha de inputs vacíos."""
    from source.api.buscador.parser import _extraer_campos

    html = FICHA_INPUTS_VACIOS.read_text(encoding="utf-8")
    # El parser lanza ValueError cuando numero_oferta está vacío
    with pytest.raises(ValueError, match="número de oferta"):
        _extraer_campos(html)
