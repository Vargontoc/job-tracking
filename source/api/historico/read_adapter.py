"""Adaptador de lectura histórica en solo lectura.

Abre el SQLite de api-persistencia en modo solo lectura (mode=ro) y consulta
la tabla ``ofertas`` para servir las consultas históricas por rango de fechas
que persistencia-api no expone: altas por fecha_alta, cierres por fecha_cierre
y resumen diario de altas y cierres.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Dataclasses de resultado
# ---------------------------------------------------------------------------

@dataclass
class OfertaResumen:
    """Resumen de una oferta para consultas históricas."""

    comunidad: str
    codigo: str
    ocupacion: str
    municipio: str
    fecha_alta: str
    fecha_cierre: str | None


@dataclass
class ResumenDiario:
    """Resumen diario de altas y cierres para una fecha concreta."""

    fecha: str
    altas: int
    cierres: int


# ---------------------------------------------------------------------------
# Consultas SQL
# ---------------------------------------------------------------------------

_SQL_ALTAS = """\
SELECT comunidad, codigo, ocupacion, municipio, fecha_alta, fecha_cierre
FROM ofertas
WHERE date(fecha_alta) >= ? AND date(fecha_alta) <= ?
ORDER BY fecha_alta
"""

_SQL_CIERRES = """\
SELECT comunidad, codigo, ocupacion, municipio, fecha_alta, fecha_cierre
FROM ofertas
WHERE fecha_cierre IS NOT NULL
  AND date(fecha_cierre) >= ? AND date(fecha_cierre) <= ?
ORDER BY fecha_cierre
"""

_SQL_CIERRES_FIN_DIFUSION = """\
SELECT comunidad, codigo, ocupacion, municipio, fecha_alta, fecha_cierre
FROM ofertas
WHERE fecha_fin_difusion IS NOT NULL
  AND date(fecha_fin_difusion) >= ? AND date(fecha_fin_difusion) <= ?
ORDER BY fecha_fin_difusion
"""

_SQL_RESUMEN_ALTAS = """\
SELECT date(fecha_alta), COUNT(*)
FROM ofertas
WHERE date(fecha_alta) = ?
GROUP BY date(fecha_alta)
"""

_SQL_RESUMEN_CIERRES = """\
SELECT date(fecha_cierre), COUNT(*)
FROM ofertas
WHERE fecha_cierre IS NOT NULL AND date(fecha_cierre) = ?
GROUP BY date(fecha_cierre)
"""


# ---------------------------------------------------------------------------
# Adaptador
# ---------------------------------------------------------------------------

class AdaptadorLecturaHistorica:
    """Lee la base de datos de persistencia en modo solo lectura.

    Abre el fichero SQLite con ``?mode=ro`` (URI) para garantizar que no se
    escribe sobre él. Si el fichero no existe, las consultas devuelven listas
    vacías sin crearlo.
    """

    def __init__(self, ruta_bd: str) -> None:
        """Inicializa el adaptador.

        Args:
            ruta_bd: Ruta absoluta o relativa al fichero SQLite de
                api-persistencia (``data/job_emcan.db``).
        """
        self._ruta_bd = ruta_bd

    # -- gestión de conexión --------------------------------------------------

    def _abrir(self) -> sqlite3.Connection | None:
        """Abre la conexión en modo solo lectura.

        Devuelve ``None`` si el fichero no existe (sin crearlo).
        """
        if not os.path.isfile(self._ruta_bd):
            return None
        # SQLite URI requiere separadores de directorio tipo Unix
        ruta_normalizada = self._ruta_bd.replace("\\", "/")
        uri = f"file:{ruta_normalizada}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def _ejecutar_conexion(self, consulta: str, params: tuple) -> list[sqlite3.Row]:
        """Ejecuta una consulta abriendo y cerrando la conexión cada vez."""
        conn = self._abrir()
        if conn is None:
            return []
        try:
            filas = conn.execute(consulta, params).fetchall()
            return filas
        finally:
            conn.close()

    # -- métodos públicos -----------------------------------------------------

    def altas_por_fecha(self, desde: str, hasta: str) -> list[OfertaResumen]:
        """Devuelve las ofertas cuya ``fecha_alta`` está en ``[desde, hasta]``.

        Args:
            desde: Fecha de inicio del rango (``YYYY-MM-DD``).
            hasta: Fecha de fin del rango (``YYYY-MM-DD``).

        Returns:
            Lista de ``OfertaResumen`` ordenada por ``fecha_alta``.
        """
        filas = self._ejecutar_conexion(_SQL_ALTAS, (desde, hasta))
        return [self._fila_a_resumen(f) for f in filas]

    def cierres_por_fecha(self, desde: str, hasta: str) -> list[OfertaResumen]:
        """Devuelve las ofertas cuya ``fecha_cierre`` está en ``[desde, hasta]``.

        Solo incluye ofertas con ``fecha_cierre`` no nula.

        Args:
            desde: Fecha de inicio del rango (``YYYY-MM-DD``).
            hasta: Fecha de fin del rango (``YYYY-MM-DD``).

        Returns:
            Lista de ``OfertaResumen`` ordenada por ``fecha_cierre``.
        """
        filas = self._ejecutar_conexion(_SQL_CIERRES, (desde, hasta))
        return [self._fila_a_resumen(f) for f in filas]

    def cierres_por_fecha_fin_difusion(
        self, desde: str, hasta: str
    ) -> list[OfertaResumen]:
        """Devuelve ofertas cuya ``fecha_fin_difusion`` está en ``[desde, hasta]``.

        Solo incluye ofertas con ``fecha_fin_difusion`` no nula.

        Args:
            desde: Fecha de inicio del rango (``YYYY-MM-DD``).
            hasta: Fecha de fin del rango (``YYYY-MM-DD``).

        Returns:
            Lista de ``OfertaResumen`` ordenada por ``fecha_fin_difusion``.
        """
        filas = self._ejecutar_conexion(_SQL_CIERRES_FIN_DIFUSION, (desde, hasta))
        return [self._fila_a_resumen(f) for f in filas]

    def resumen_diario(self, fecha: str) -> ResumenDiario:
        """Devuelve el número de altas y cierres para una fecha concreta.

        Args:
            fecha: Fecha del resumen (``YYYY-MM-DD``).

        Returns:
            ``ResumenDiario`` con los recuentos (0 si no hay datos).
        """
        altas_filas = self._ejecutar_conexion(_SQL_RESUMEN_ALTAS, (fecha,))
        altas = altas_filas[0][1] if altas_filas else 0

        cierres_filas = self._ejecutar_conexion(_SQL_RESUMEN_CIERRES, (fecha,))
        cierres = cierres_filas[0][1] if cierres_filas else 0

        return ResumenDiario(fecha=fecha, altas=altas, cierres=cierres)

    # -- helpers internos -----------------------------------------------------

    @staticmethod
    def _fila_a_resumen(fila: sqlite3.Row) -> OfertaResumen:
        return OfertaResumen(
            comunidad=fila["comunidad"],
            codigo=fila["codigo"],
            ocupacion=fila["ocupacion"] or "",
            municipio=fila["municipio"] or "",
            fecha_alta=fila["fecha_alta"],
            fecha_cierre=fila["fecha_cierre"],
        )
