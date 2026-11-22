"""Repositorio de abstenciones de cierre."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Optional

from source.api.historico.connection import transaccion


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class Abstencion:
    """Registro de una abstención de cierre.

    ``codigos_afectados`` se almacena como lista de textos en Python y se
    serializa a JSON en la columna homónima de la tabla.
    """

    id: int
    motivo: str
    timestamp: str
    recuento_anterior: Optional[int] = None
    recuento_actual: Optional[int] = None
    umbral_aplicado: Optional[str] = None
    codigos_afectados: Optional[list[str]] = None


# ---------------------------------------------------------------------------
# Repositorio
# ---------------------------------------------------------------------------

class RepositorioAbstenciones:
    """Abstracción de escritura y lectura de abstenciones de cierre.

    Opera sobre la tabla ``abstenciones_cierre`` del esquema propio del
    histórico. No escribe en ninguna base de datos de ofertas (SUP-003).
    """

    def __init__(self, conexion: sqlite3.Connection) -> None:
        """Inicializa el repositorio con una conexión SQLite.

        Args:
            conexion: Conexión SQLite abierta (no se abre internamente).
        """
        self._conexion = conexion

    def registrar(
        self,
        motivo: str,
        timestamp: str,
        recuento_anterior: Optional[int] = None,
        recuento_actual: Optional[int] = None,
        umbral_aplicado: Optional[str] = None,
        codigos_afectados: Optional[list[str]] = None,
    ) -> int:
        """Inserta una abstención de cierre y devuelve su id.

        Args:
            motivo: Motivo de la abstención (no vacío).
            timestamp: Marca de tiempo en formato ISO 8601.
            recuento_anterior: Recuento previo a la abstención (opcional).
            recuento_actual: Recuento en el momento de la abstención (opcional).
            umbral_aplicado: Umbral que provocó la abstención (opcional).
            codigos_afectados: Lista de códigos afectados (opcional). Se
                serializa como JSON string en la columna correspondiente.

        Returns:
            El id asignado por la base de datos al nuevo registro.
        """
        codigos_json = (
            json.dumps(codigos_afectados) if codigos_afectados is not None else None
        )
        with transaccion(self._conexion):
            cursor = self._conexion.execute(
                """INSERT INTO abstenciones_cierre
                   (motivo, timestamp, recuento_anterior, recuento_actual,
                    umbral_aplicado, codigos_afectados)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    motivo,
                    timestamp,
                    recuento_anterior,
                    recuento_actual,
                    umbral_aplicado,
                    codigos_json,
                ),
            )
            return cursor.lastrowid

    def consultar_ultimas(self, n: int = 10) -> list[Abstencion]:
        """Devuelve las últimas N abstenciones ordenadas por timestamp desc.

        Args:
            n: Número máximo de abstenciones a devolver (por defecto 10).

        Returns:
            Lista de Abstencion ordenada de más reciente a más antigua.
        """
        filas = self._conexion.execute(
            """SELECT id, motivo, timestamp, recuento_anterior,
                      recuento_actual, umbral_aplicado, codigos_afectados
               FROM abstenciones_cierre
               ORDER BY timestamp DESC
               LIMIT ?""",
            (n,),
        ).fetchall()
        return [self._fila_a_abstencion(f) for f in filas]

    def consultar_por_motivo(
        self, motivo: str, limite: int = 10
    ) -> list[Abstencion]:
        """Filtra abstenciones por motivo, ordenadas por timestamp desc.

        Args:
            motivo: Motivo por el que filtrar.
            limite: Número máximo de abstenciones a devolver (por defecto 10).

        Returns:
            Lista de Abstencion con el motivo indicado.
        """
        filas = self._conexion.execute(
            """SELECT id, motivo, timestamp, recuento_anterior,
                      recuento_actual, umbral_aplicado, codigos_afectados
               FROM abstenciones_cierre
               WHERE motivo = ?
               ORDER BY timestamp DESC
               LIMIT ?""",
            (motivo, limite),
        ).fetchall()
        return [self._fila_a_abstencion(f) for f in filas]

    def consultar_por_rango(
        self,
        fecha_inicio: str,
        fecha_fin: str,
        limite: int = 50,
    ) -> list[Abstencion]:
        """Devuelve abstenciones dentro del rango de fechas [inicio, fin].

        La comparación es lexicográfica sobre el timestamp ISO 8601.

        Args:
            fecha_inicio: Marca de tiempo inicial (inclusive).
            fecha_fin: Marca de tiempo final (inclusive).
            limite: Número máximo de abstenciones a devolver (por defecto 50).

        Returns:
            Lista de Abstencion ordenada por timestamp desc.
        """
        filas = self._conexion.execute(
            """SELECT id, motivo, timestamp, recuento_anterior,
                      recuento_actual, umbral_aplicado, codigos_afectados
               FROM abstenciones_cierre
               WHERE timestamp >= ? AND timestamp <= ?
               ORDER BY timestamp DESC
               LIMIT ?""",
            (fecha_inicio, fecha_fin, limite),
        ).fetchall()
        return [self._fila_a_abstencion(f) for f in filas]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fila_a_abstencion(fila: sqlite3.Row) -> Abstencion:
        """Convierte una fila SQLite.Row en una Abstencion."""
        codigos_json = fila["codigos_afectados"]
        codigos = json.loads(codigos_json) if codigos_json is not None else None
        return Abstencion(
            id=fila["id"],
            motivo=fila["motivo"],
            timestamp=fila["timestamp"],
            recuento_anterior=fila["recuento_anterior"],
            recuento_actual=fila["recuento_actual"],
            umbral_aplicado=fila["umbral_aplicado"],
            codigos_afectados=codigos,
        )
