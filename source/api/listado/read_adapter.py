"""Adaptador de lectura del listado en solo lectura.

Abre el SQLite de api-persistencia en modo solo lectura (``mode=ro``), configura
``busy_timeout`` y cierra la conexión al terminar cada consulta. No crea el
fichero si no existe, no escribe y no altera el esquema de api-persistencia: un
fichero inexistente, no válido o sin la tabla ``ofertas`` produce un error
controlado de acceso a los datos.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Sequence

#: Espera de SQLite ante una contención de escritura, igual que la de
#: api-persistencia (``source/api/persistencia/connection.py``).
BUSY_TIMEOUT_MS = 5000

#: Motivo: el fichero SQLite no existe (no se crea).
MOTIVO_INEXISTENTE = "inexistente"
#: Motivo: el fichero existe pero no es un SQLite válido.
MOTIVO_NO_VALIDO = "no_valido"
#: Motivo: el SQLite es válido pero no contiene la tabla ``ofertas``.
MOTIVO_SIN_TABLA_OFERTAS = "sin_tabla_ofertas"
#: Motivo: SQLite ha rechazado la consulta (por ejemplo, una escritura).
MOTIVO_CONSULTA = "consulta"

_TABLA_OFERTAS = "ofertas"


class ErrorAccesoDatos(Exception):
    """Indica que no se puede acceder a los datos del listado.

    Atributos:
        motivo: Uno de los valores ``MOTIVO_*`` del módulo, que distingue un
            fichero inexistente de uno que no es SQLite válido, de uno sin la
            tabla ``ofertas`` y de una consulta rechazada por SQLite.
        detalle: Texto descriptivo del fallo.
    """

    def __init__(self, motivo: str, detalle: str) -> None:
        self.motivo = motivo
        self.detalle = detalle
        super().__init__(f"No se puede acceder a los datos: {detalle}")


class AdaptadorLecturaListado:
    """Consulta el SQLite de api-persistencia en modo solo lectura.

    Cada llamada a :meth:`consultar` abre una conexión ``mode=ro``, comprueba
    que la tabla ``ofertas`` existe, ejecuta la consulta parametrizada y cierra
    la conexión antes de devolver las filas.
    """

    def __init__(self, ruta_bd: str) -> None:
        """Inicializa el adaptador.

        Args:
            ruta_bd: Ruta absoluta o relativa al fichero SQLite de
                api-persistencia (``data/job_emcan.db``).
        """
        self._ruta_bd = str(ruta_bd)

    def consultar(
        self, consulta: str, parametros: Sequence[object] = ()
    ) -> list[sqlite3.Row]:
        """Ejecuta una consulta parametrizada y devuelve sus filas.

        Args:
            consulta: Sentencia SQL con marcadores posicionales (``?``).
            parametros: Valores de los marcadores, en orden.

        Returns:
            Lista de filas con acceso por nombre de columna (``sqlite3.Row``).

        Raises:
            ErrorAccesoDatos: Si el fichero no existe, no es un SQLite válido,
                no contiene la tabla ``ofertas`` o SQLite rechaza la consulta.
        """
        conexion = self._abrir()
        try:
            try:
                return conexion.execute(consulta, tuple(parametros)).fetchall()
            except sqlite3.Error as error:
                raise ErrorAccesoDatos(
                    MOTIVO_CONSULTA,
                    f"SQLite ha rechazado la consulta sobre '{self._ruta_bd}' "
                    f"({error}).",
                ) from error
        finally:
            conexion.close()

    # -- gestión de conexión --------------------------------------------------

    def _abrir(self) -> sqlite3.Connection:
        """Abre la conexión en modo solo lectura con la tabla ``ofertas``.

        Raises:
            ErrorAccesoDatos: Si el fichero no existe, no es un SQLite válido
                o no contiene la tabla ``ofertas``.
        """
        if not os.path.isfile(self._ruta_bd):
            raise ErrorAccesoDatos(
                MOTIVO_INEXISTENTE, f"el fichero '{self._ruta_bd}' no existe."
            )

        # La URI de SQLite exige separadores de directorio tipo Unix.
        ruta_normalizada = self._ruta_bd.replace("\\", "/")
        uri = f"file:{ruta_normalizada}?mode=ro"
        try:
            conexion = sqlite3.connect(uri, uri=True)
        except sqlite3.Error as error:
            raise ErrorAccesoDatos(
                MOTIVO_NO_VALIDO,
                f"'{self._ruta_bd}' no es un SQLite válido ({error}).",
            ) from error

        try:
            conexion.row_factory = sqlite3.Row
            conexion.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS};")
            if not self._tiene_tabla_ofertas(conexion):
                raise ErrorAccesoDatos(
                    MOTIVO_SIN_TABLA_OFERTAS,
                    f"'{self._ruta_bd}' no contiene la tabla '{_TABLA_OFERTAS}'.",
                )
        except sqlite3.DatabaseError as error:
            conexion.close()
            raise ErrorAccesoDatos(
                MOTIVO_NO_VALIDO,
                f"'{self._ruta_bd}' no es un SQLite válido ({error}).",
            ) from error
        except Exception:
            conexion.close()
            raise

        return conexion

    @staticmethod
    def _tiene_tabla_ofertas(conexion: sqlite3.Connection) -> bool:
        """Comprueba en ``sqlite_master`` que la tabla ``ofertas`` existe."""
        fila = conexion.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            (_TABLA_OFERTAS,),
        ).fetchone()
        return fila is not None
