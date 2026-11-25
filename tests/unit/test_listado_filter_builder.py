"""Pruebas unitarias del constructor de filtros del listado (TASK-006).

Comprueban que la cláusula ``WHERE`` se compone con conjunción ``AND``, que
todos los valores viajan como parámetros posicionales (también un valor con
comillas o texto de SQL), que la visibilidad por estado se aplica por defecto y
que el texto libre y el municipio quedan fuera de SQL para filtrarse en memoria.
"""

from __future__ import annotations

import pytest

from source.api.listado.date_parser import ErrorFecha, expresion_fecha_iso
from source.api.listado.filter_builder import ClausulaFiltros, construir


# ---------------------------------------------------------------------------
# Pruebas: sin filtros y valores vacíos (REQ-001)
# ---------------------------------------------------------------------------

class TestSinFiltros:
    """Sin filtros del cliente solo se aplica la visibilidad por defecto."""

    def test_sin_filtros_solo_aplica_el_estado_por_defecto(self) -> None:
        clausula = construir({})

        # La única condición es la visibilidad por defecto de REQ-006.
        assert clausula.where == "estado = ?"
        assert clausula.parametros == ["vigente"]
        assert clausula.texto is None
        assert clausula.municipio is None
        assert clausula.filtrado_en_memoria is False

    def test_valores_vacios_no_generan_condiciones(self) -> None:
        filtros = {
            "texto": "",
            "sector": "   ",
            "municipio": "",
            "fecha_desde": "",
            "fecha_hasta": "",
            "incluir_cerradas": False,
        }

        clausula = construir(filtros)

        assert clausula.where == "estado = ?"
        assert clausula.parametros == ["vigente"]
        assert clausula.filtrado_en_memoria is False

    def test_claves_ausentes_equivalen_a_sin_filtro(self) -> None:
        clausula = construir({"incluir_cerradas": None})

        assert clausula.where == "estado = ?"
        assert clausula.parametros == ["vigente"]


# ---------------------------------------------------------------------------
# Pruebas: conjunción de filtros (REQ-001, REQ-005)
# ---------------------------------------------------------------------------

class TestConjuncion:
    """Cada filtro activo añade una condición unida por ``AND``."""

    def test_municipio_y_fecha_combinan_con_and(self) -> None:
        clausula = construir(
            {"municipio": "Santander", "fecha_desde": "10/11/2026"}
        )

        # Dos condiciones: la de estado y la del rango de fechas. El municipio
        # no está en SQL (se aplica en memoria).
        assert clausula.where.count(" AND ") == 1
        assert clausula.where.startswith("estado = ? AND ")
        assert expresion_fecha_iso() in clausula.where
        assert clausula.parametros == ["vigente", "2026-11-10"]
        assert clausula.municipio == "Santander"

    def test_rango_completo_lleva_sus_dos_cotas_en_iso(self) -> None:
        clausula = construir(
            {"fecha_desde": "10/11/2026", "fecha_hasta": "20/11/2026"}
        )

        assert clausula.where.count(" AND ") == 2
        assert ">= ?" in clausula.where
        assert "<= ?" in clausula.where
        assert clausula.parametros == ["vigente", "2026-11-10", "2026-11-20"]

    def test_solo_fecha_hasta(self) -> None:
        clausula = construir({"fecha_hasta": "20/11/2026"})

        assert ">= ?" not in clausula.where
        assert "<= ?" in clausula.where
        assert clausula.parametros == ["vigente", "2026-11-20"]

    def test_fecha_invalida_es_un_error_de_formato(self) -> None:
        with pytest.raises(ErrorFecha):
            construir({"fecha_desde": "32/13/2026"})


# ---------------------------------------------------------------------------
# Pruebas: filtros textuales en memoria (DEC-002, REQ-002, REQ-004)
# ---------------------------------------------------------------------------

class TestFiltrosTextuales:
    """El texto libre y el municipio se informan, pero no entran en el SQL."""

    def test_texto_libre_no_aparece_en_sql(self) -> None:
        clausula = construir({"texto": "tecnico"})

        # Se conserva solo la condición de estado.
        assert clausula.where == "estado = ?"
        assert clausula.parametros == ["vigente"]
        # El filtro textual se informa para aplicarlo después en memoria.
        assert clausula.texto == "tecnico"
        assert clausula.filtrado_en_memoria is True
        assert "texto_libre" not in clausula.where

    def test_municipio_no_aparece_en_sql(self) -> None:
        clausula = construir({"municipio": "santander"})

        assert "municipio" not in clausula.where
        assert clausula.parametros == ["vigente"]
        assert clausula.municipio == "santander"
        assert clausula.filtrado_en_memoria is True

    def test_texto_y_municipio_a_la_vez(self) -> None:
        clausula = construir({"texto": " python ", "municipio": " Santander "})

        # Los espacios sobrantes no forman parte del filtro.
        assert clausula.texto == "python"
        assert clausula.municipio == "Santander"
        assert clausula.where == "estado = ?"


# ---------------------------------------------------------------------------
# Pruebas: valores como parámetros posicionales (REQ-010)
# ---------------------------------------------------------------------------

class TestParametros:
    """Ningún valor se concatena dentro del texto de la consulta."""

    def test_valor_con_comillas_y_sql_viaja_como_parametro(self) -> None:
        valor = "'; DROP TABLE ofertas; --"

        clausula = construir({"sector": valor})

        assert clausula.where == "estado = ? AND sector = ?"
        assert clausula.parametros == ["vigente", valor]
        assert "DROP" not in clausula.where
        assert valor not in clausula.where

    def test_texto_con_sql_no_llega_a_la_consulta(self) -> None:
        valor = "x' OR '1'='1"

        clausula = construir({"texto": valor})

        assert valor not in clausula.where
        assert clausula.texto == valor


# ---------------------------------------------------------------------------
# Pruebas: visibilidad por estado (REQ-006, SUP-003)
# ---------------------------------------------------------------------------

class TestEstado:
    """``vigente`` por defecto, ``cerrada`` solo si se pide, ``sin_ficha`` nunca."""

    def test_por_defecto_solo_vigente(self) -> None:
        clausula = construir({})

        assert clausula.where == "estado = ?"
        assert clausula.parametros == ["vigente"]

    def test_incluir_cerradas_anade_cerrada(self) -> None:
        clausula = construir({"incluir_cerradas": True})

        assert clausula.where == "estado IN (?, ?)"
        assert clausula.parametros == ["vigente", "cerrada"]

    def test_sin_ficha_nunca_se_incluye(self) -> None:
        sin_incluir = construir({"incluir_cerradas": False})
        incluyendo = construir({"incluir_cerradas": True})

        assert "sin_ficha" not in sin_incluir.where
        assert "sin_ficha" not in sin_incluir.parametros
        assert "sin_ficha" not in incluyendo.where
        assert "sin_ficha" not in incluyendo.parametros


# ---------------------------------------------------------------------------
# Pruebas: sector (REQ-003, ALT-007)
# ---------------------------------------------------------------------------

class TestSector:
    """El sector se filtra aunque hoy no haya datos que lo satisfagan."""

    def test_sector_genera_condicion_por_parametro(self) -> None:
        clausula = construir({"sector": "informatica"})

        assert clausula.where == "estado = ? AND sector = ?"
        assert clausula.parametros == ["vigente", "informatica"]

    def test_sector_vacio_no_genera_condicion(self) -> None:
        clausula = construir({"sector": ""})

        assert "sector" not in clausula.where


# ---------------------------------------------------------------------------
# Pruebas: ausencia de condiciones ajenas (SUP-002)
# ---------------------------------------------------------------------------

class TestSinOficina:
    """El constructor no genera ninguna condición sobre ``oficina``."""

    def test_no_hay_condicion_sobre_oficina(self) -> None:
        clausula = construir({"oficina": "Torrelavega"})

        assert "oficina" not in clausula.where
        assert clausula.where == "estado = ?"
        assert "Torrelavega" not in clausula.parametros


# ---------------------------------------------------------------------------
# Pruebas: forma del resultado
# ---------------------------------------------------------------------------

def test_el_resultado_es_una_tupla_con_nombre() -> None:
    """El resultado expone ``where``, ``parametros`` y los filtros textuales."""
    clausula = construir({"texto": "tecnico"})

    assert isinstance(clausula, ClausulaFiltros)
    where, parametros, texto, municipio = clausula
    assert where == clausula.where == "estado = ?"
    assert parametros == clausula.parametros == ["vigente"]
    assert texto == clausula.texto == "tecnico"
    assert municipio == clausula.municipio is None
