"""Pruebas unitarias del parser de fechas del listado (TASK-004).

Comprueban la validación estricta ``dd/mm/aaaa``, el rechazo de rangos
invertidos y las expresiones SQL ``GLOB`` de conversión a ISO y de orden que
dejan las ofertas sin fecha válida al final del listado.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest

from source.api.listado.date_parser import (
    ErrorFecha,
    expresion_fecha_iso,
    expresion_orden,
    validar_fecha,
    validar_rango,
)

# Ofertas de prueba para las expresiones SQL: fechas válidas, una fecha
# imposible que pasa el patrón, una cadena vacía y una fecha incompleta.
_OFERTAS = [
    ("000000000001", "15/11/2026"),
    ("000000000002", "30/11/2026"),
    ("000000000003", "20/11/2026"),
    ("000000000020", "20/11/2026"),
    ("000000000005", "31/02/2026"),
    ("000000000010", ""),
    ("000000000011", "20/11"),
]


@pytest.fixture()
def conexion() -> Iterator[sqlite3.Connection]:
    """SQLite en memoria con la columna ``fecha_inicio_difusion`` del esquema."""
    conexion = sqlite3.connect(":memory:")
    try:
        conexion.execute(
            "CREATE TABLE ofertas (codigo TEXT NOT NULL, fecha_inicio_difusion TEXT)"
        )
        conexion.executemany(
            "INSERT INTO ofertas (codigo, fecha_inicio_difusion) VALUES (?, ?)",
            _OFERTAS,
        )
        yield conexion
    finally:
        conexion.close()


# ---------------------------------------------------------------------------
# Pruebas: validación de una fecha
# ---------------------------------------------------------------------------

class TestValidarFecha:
    """La entrada debe cumplir estrictamente dd/mm/aaaa."""

    def test_fecha_valida_se_convierte_a_iso(self) -> None:
        assert validar_fecha("15/11/2026") == "2026-11-15"

    @pytest.mark.parametrize(
        "texto",
        [
            "32/13/2026",  # día y mes fuera de rango
            "2026-11-15",  # orden ISO
            "1/1/26",  # sin ceros a la izquierda y año corto
            "15-11-2026",  # separador distinto
            "31/02/2026",  # patrón válido pero fecha imposible
            "",  # sin valor
        ],
    )
    def test_fecha_invalida_indica_el_formato(self, texto: str) -> None:
        with pytest.raises(ErrorFecha, match="dd/mm/aaaa"):
            validar_fecha(texto)


# ---------------------------------------------------------------------------
# Pruebas: validación de un rango
# ---------------------------------------------------------------------------

class TestValidarRango:
    """El rango debe ser válido y sus dos cotas son opcionales."""

    def test_rango_valido_se_convierte_a_iso(self) -> None:
        assert validar_rango("10/11/2026", "20/11/2026") == (
            "2026-11-10",
            "2026-11-20",
        )

    def test_rango_de_un_solo_dia_es_valido(self) -> None:
        assert validar_rango("15/11/2026", "15/11/2026") == (
            "2026-11-15",
            "2026-11-15",
        )

    def test_rango_invertido_se_rechaza(self) -> None:
        with pytest.raises(ErrorFecha, match="posterior"):
            validar_rango("20/11/2026", "10/11/2026")

    def test_solo_cota_inferior(self) -> None:
        assert validar_rango("10/11/2026", None) == ("2026-11-10", None)

    def test_solo_cota_superior(self) -> None:
        assert validar_rango(None, "20/11/2026") == (None, "2026-11-20")

    def test_sin_cotas_el_rango_no_se_aplica(self) -> None:
        assert validar_rango(None, None) == (None, None)
        assert validar_rango("", "") == (None, None)

    def test_cota_invalida_se_rechaza(self) -> None:
        with pytest.raises(ErrorFecha, match="dd/mm/aaaa"):
            validar_rango("32/13/2026", "20/11/2026")


# ---------------------------------------------------------------------------
# Pruebas: expresiones SQL (DEC-003)
# ---------------------------------------------------------------------------

class TestExpresionesSql:
    """Las expresiones SQL del listado llevan guarda GLOB y ordenan por fecha."""

    def test_expresion_fecha_iso_contiene_la_guarda_glob(self) -> None:
        expresion = expresion_fecha_iso()

        assert expresion.startswith("CASE WHEN")
        assert (
            "fecha_inicio_difusion GLOB "
            "'[0-9][0-9]/[0-9][0-9]/[0-9][0-9][0-9][0-9]'"
        ) in expresion
        assert "ELSE NULL" in expresion

    def test_expresion_orden_nulos_al_final_y_desempate_por_codigo(self) -> None:
        orden = expresion_orden()

        assert orden.startswith("ORDER BY")
        assert "IS NULL" in orden
        assert "DESC" in orden
        assert "codigo ASC" in orden
        assert expresion_fecha_iso() in orden

    def test_expresion_aplicada_a_las_filas(
        self, conexion: sqlite3.Connection
    ) -> None:
        filas = conexion.execute(
            f"SELECT codigo, {expresion_fecha_iso()} AS fecha_iso "
            "FROM ofertas ORDER BY codigo"
        ).fetchall()
        resultado = dict(filas)

        assert resultado["000000000001"] == "2026-11-15"
        # La cadena vacía y una fecha incompleta no cumplen el patrón.
        assert resultado["000000000010"] is None
        assert resultado["000000000011"] is None
        # 31/02/2026 pasa la guarda y ordena por su texto ISO.
        assert resultado["000000000005"] == "2026-02-31"

    def test_expresion_orden_sobre_las_filas(
        self, conexion: sqlite3.Connection
    ) -> None:
        filas = conexion.execute(
            f"SELECT codigo FROM ofertas {expresion_orden()}"
        ).fetchall()

        assert [fila[0] for fila in filas] == [
            "000000000002",  # 30/11/2026
            "000000000003",  # 20/11/2026: mismo día, código menor primero
            "000000000020",  # 20/11/2026: desempate por código ascendente
            "000000000001",  # 15/11/2026
            "000000000005",  # 31/02/2026: pasa el GLOB, ordena por texto ISO
            "000000000010",  # sin fecha válida, al final
            "000000000011",  # sin fecha válida, al final
        ]
