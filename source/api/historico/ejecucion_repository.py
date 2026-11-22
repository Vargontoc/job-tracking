"""Repositorio de ejecución diaria.

Registra la fecha (YYYY-MM-DD) de cada ejecución del cierre diario y
permite consultar si ya se ejecutó en un día dado, evitando ejecuciones
múltiples el mismo día (REQ-011, ALT-006).

La tabla ``ejecucion_diaria`` tiene ``fecha`` como PRIMARY KEY, por lo
que la inserción es idempotente: registrar la misma fecha dos veces no
genera duplicados.

El repositorio no aplica la zona horaria (NFR-001): el formato
YYYY-MM-DD lo calcula el llamador en la zona horaria configurada y se
recibe ya como texto. El repositorio no escribe en la base de datos de
ofertas (SUP-003).
"""

from __future__ import annotations

import sqlite3
from typing import Optional

from source.api.historico.connection import transaccion


class RepositorioEjecucion:
    """Abstracción de lectura y escritura sobre ``ejecucion_diaria``."""

    def __init__(self, conexion: sqlite3.Connection) -> None:
        """Inicializa el repositorio con una conexión SQLite.

        Args:
            conexion: Conexión SQLite abierta (no se abre internamente).
        """
        self._conexion = conexion

    def registrar_ejecucion(self, fecha: str) -> None:
        """Registra la ejecución de un día.

        Si la fecha ya existe, la operación es idempotente: no se crea
        un segundo registro (ALT-006).

        Args:
            fecha: Fecha de ejecución en formato ``YYYY-MM-DD``. Se
                espera que el llamador la calcule en la zona horaria
                configurada (NFR-001).
        """
        with transaccion(self._conexion):
            self._conexion.execute(
                "INSERT OR IGNORE INTO ejecucion_diaria (fecha) VALUES (?)",
                (fecha,),
            )

    def se_ejecuto_hoy(self, fecha: str) -> bool:
        """Comprueba si ya se registró una ejecución para la fecha dada.

        Args:
            fecha: Fecha a consultar en formato ``YYYY-MM-DD``.

        Returns:
            ``True`` si existe un registro para esa fecha, ``False`` en
            caso contrario.
        """
        fila = self._conexion.execute(
            "SELECT 1 FROM ejecucion_diaria WHERE fecha = ?",
            (fecha,),
        ).fetchone()
        return fila is not None

    def obtener_ultima_ejecucion(self) -> Optional[str]:
        """Devuelve la fecha de la última ejecución registrada.

        Returns:
            La fecha (``YYYY-MM-DD``) de la última ejecución, o ``None``
            si no hay ninguna ejecución registrada.
        """
        fila = self._conexion.execute(
            "SELECT MAX(fecha) FROM ejecucion_diaria",
        ).fetchone()
        if fila is None or fila[0] is None:
            return None
        return fila[0]
