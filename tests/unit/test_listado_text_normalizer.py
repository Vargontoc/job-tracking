"""Pruebas unitarias del normalizador de texto del listado (TASK-005).

Comprueban que la normalización es insensible a mayúsculas y a tildes (incluida
la eñe), que la cadena vacía se normaliza sin error y que un campo vacío no
aporta coincidencias.
"""

from __future__ import annotations

from source.api.listado.text_normalizer import coincide, contiene, normalizar


# ---------------------------------------------------------------------------
# Pruebas: normalización (NFR-003, REQ-004, DEC-002)
# ---------------------------------------------------------------------------

class TestNormalizar:
    """La normalización deja el texto en minúsculas y sin diacríticos."""

    def test_tecnico_con_y_sin_tilde(self) -> None:
        assert normalizar("Técnico") == normalizar("tecnico") == "tecnico"

    def test_tecnico_en_mayusculas_y_con_tilde(self) -> None:
        assert normalizar("TÉCNICO") == "tecnico"

    def test_santander_con_y_sin_mayuscula(self) -> None:
        assert normalizar("Santander") == normalizar("santander") == "santander"

    def test_ene_se_normaliza(self) -> None:
        assert normalizar("Año") == normalizar("ano") == "ano"

    def test_cadena_vacia(self) -> None:
        assert normalizar("") == ""

    def test_valor_ausente(self) -> None:
        assert normalizar(None) == ""


# ---------------------------------------------------------------------------
# Pruebas: coincidencia parcial (REQ-002, NFR-003)
# ---------------------------------------------------------------------------

class TestContiene:
    """La comparación parcial no distingue mayúsculas ni tildes."""

    def test_termino_sin_tilde_encuentra_la_ocupacion_con_tilde(self) -> None:
        assert contiene("Técnico", "tecnico") is True

    def test_termino_sin_tilde_encuentra_la_ocupacion_en_mayusculas(self) -> None:
        assert contiene("TÉCNICO", "tecnico") is True

    def test_termino_parcial_coincide(self) -> None:
        assert contiene("Programador de sistemas", "sistemas") is True
        assert contiene("Programador de sistemas", "PROGRAMADOR") is True

    def test_termino_que_no_aparece(self) -> None:
        assert contiene("Técnico", "fontanero") is False

    def test_campo_vacio_no_aporta_coincidencias(self) -> None:
        # Una oferta con el texto purgado (campo vacío) no coincide con nada.
        assert contiene("", "tecnico") is False
        assert contiene(None, "tecnico") is False

    def test_termino_vacio_no_filtra(self) -> None:
        assert contiene("Técnico", "") is False
        assert contiene("Técnico", None) is False


# ---------------------------------------------------------------------------
# Pruebas: igualdad para el filtro de municipio (REQ-004)
# ---------------------------------------------------------------------------

class TestCoincide:
    """El filtro de municipio compara cadenas normalizadas por igualdad."""

    def test_municipio_en_minusculas_encuentra_el_almacenado_en_mayusculas(self) -> None:
        assert coincide("SANTANDER", "santander") is True

    def test_municipio_con_tilde(self) -> None:
        assert coincide("Torrelavega", "TORRELAVEGA") is True
        assert coincide("Camargo", "camargó") is True

    def test_no_es_coincidencia_parcial(self) -> None:
        assert coincide("Santander", "Sant") is False

    def test_campo_vacio_no_coincide(self) -> None:
        assert coincide("", "santander") is False
        assert coincide("", "") is False
