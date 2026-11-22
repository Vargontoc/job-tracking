"""Repositorio de presencia en listado y serie de recuentos."""

from __future__ import annotations

import sqlite3
from typing import Optional

from source.api.historico.connection import transaccion


class RepositorioPresencia:
    """Persiste la presencia/ausencia de cada código en cada listado oficial
    y la serie histórica de recuentos del listado.

    Opera sobre las tablas ``presencia_en_listado`` y ``serie_recuentos``
    del SQLite propio del histórico. No escribe en la base de datos de ofertas
    (SUP-003).
    """

    def __init__(self, conexion: sqlite3.Connection) -> None:
        """Inicializa el repositorio con una conexión SQLite.

        Args:
            conexion: Conexión SQLite abierta (no se abre internamente).
        """
        self._conexion = conexion

    # ------------------------------------------------------------------
    # Presencia / ausencia en listado
    # ------------------------------------------------------------------

    def registrar_presencia(
        self, comunidad: str, codigo: str, fecha_listado: str
    ) -> None:
        """Inserta o actualiza la marca de presencia de un código en un listado.

        Si ya existe un registro para la clave ``(comunidad, codigo,
        fecha_listado)``, lo actualiza con ``presente = 1`` (la última marca
        prevalece, sin duplicar fila).

        Args:
            comunidad: Identificador de la comunidad autónoma.
            codigo: Código de la oferta (texto de 12 dígitos).
            fecha_listado: Fecha del listado oficial (ISO ``YYYY-MM-DD``).
        """
        with transaccion(self._conexion):
            self._conexion.execute(
                """INSERT INTO presencia_en_listado
                   (comunidad, codigo, fecha_listado, presente)
                   VALUES (?, ?, ?, 1)
                   ON CONFLICT(comunidad, codigo, fecha_listado)
                   DO UPDATE SET presente = 1""",
                (comunidad, codigo, fecha_listado),
            )

    def registrar_ausencia(
        self, comunidad: str, codigo: str, fecha_listado: str
    ) -> None:
        """Inserta o actualiza la marca de ausencia de un código en un listado.

        Si ya existe un registro para la clave ``(comunidad, codigo,
        fecha_listado)``, lo actualiza con ``presente = 0``.

        Args:
            comunidad: Identificador de la comunidad autónoma.
            codigo: Código de la oferta (texto de 12 dígitos).
            fecha_listado: Fecha del listado oficial (ISO ``YYYY-MM-DD``).
        """
        with transaccion(self._conexion):
            self._conexion.execute(
                """INSERT INTO presencia_en_listado
                   (comunidad, codigo, fecha_listado, presente)
                   VALUES (?, ?, ?, 0)
                   ON CONFLICT(comunidad, codigo, fecha_listado)
                   DO UPDATE SET presente = 0""",
                (comunidad, codigo, fecha_listado),
            )

    def consultar_historial(
        self,
        codigo: str,
        comunidad: Optional[str] = None,
        limite: int = 10,
    ) -> list[tuple[str, bool]]:
        """Devuelve las últimas marcas de presencia de un código, ordenadas
        de más reciente a más antigua.

        Args:
            codigo: Código de la oferta.
            comunidad: Si se indica, filtra por comunidad; si no, consulta
                todas las comunidades para ese código.
            limite: Máximo de registros a devolver (por defecto 10).

        Returns:
            Lista de tuplas ``(fecha_listado, presente)`` ordenadas por
            ``fecha_listado`` descendente.
        """
        if comunidad is not None:
            filas = self._conexion.execute(
                """SELECT fecha_listado, presente
                   FROM presencia_en_listado
                   WHERE codigo = ? AND comunidad = ?
                   ORDER BY fecha_listado DESC
                   LIMIT ?""",
                (codigo, comunidad, limite),
            ).fetchall()
        else:
            filas = self._conexion.execute(
                """SELECT fecha_listado, presente
                   FROM presencia_en_listado
                   WHERE codigo = ?
                   ORDER BY fecha_listado DESC
                   LIMIT ?""",
                (codigo, limite),
            ).fetchall()
        return [(fila[0], bool(fila[1])) for fila in filas]

    def ausencias_consecutivas(
        self, codigo: str, comunidad: str, n: int
    ) -> bool:
        """Verifica si un código tiene ``n`` ausencias consecutivas.

        Consulta las últimas ``n`` entradas de la serie ordenadas por fecha
        descendente y comprueba que todas son de ausencia (``presente = 0``).
        Si hay menos de ``n`` registros, devuelve ``False``.

        Args:
            codigo: Código de la oferta.
            comunidad: Comunidad de la oferta.
            n: Número de ausencias consecutivas requeridas.

        Returns:
            ``True`` si existen al menos ``n`` registros consecutivos y todos
            son ausencias; ``False`` en otro caso.
        """
        if n <= 0:
            return False
        filas = self._conexion.execute(
            """SELECT presente
               FROM presencia_en_listado
               WHERE codigo = ? AND comunidad = ?
               ORDER BY fecha_listado DESC
               LIMIT ?""",
            (codigo, comunidad, n),
        ).fetchall()

        if len(filas) < n:
            return False
        return all(fila[0] == 0 for fila in filas)

    # ------------------------------------------------------------------
    # Serie de recuentos
    # ------------------------------------------------------------------

    def registrar_recuento(self, total: int, timestamp: str) -> None:
        """Registra un recuento del listado en la serie histórica.

        Args:
            total: Número total de ofertas del listado.
            timestamp: Marca de tiempo (ISO 8601) de la pasada.
        """
        with transaccion(self._conexion):
            self._conexion.execute(
                """INSERT INTO serie_recuentos (recuento_total, timestamp)
                   VALUES (?, ?)""",
                (total, timestamp),
            )

    def obtener_ultimo_recuento(self) -> Optional[tuple[int, str]]:
        """Devuelve el recuento más reciente de la serie.

        Returns:
            Tupla ``(total, timestamp)`` del último recuento, o ``None`` si
            la serie está vacía (ALT-010).
        """
        fila = self._conexion.execute(
            """SELECT recuento_total, timestamp
               FROM serie_recuentos
               ORDER BY id DESC
               LIMIT 1"""
        ).fetchone()
        if fila is None:
            return None
        return (fila[0], fila[1])
