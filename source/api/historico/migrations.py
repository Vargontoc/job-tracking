"""Migraciones secuenciales del esquema propio del histórico y función de aplicación."""

import sqlite3
from datetime import datetime, timezone

from source.api.historico.connection import transaccion


class ErrorMigracion(Exception):
    """Error durante la aplicación de migraciones."""


# ---------------------------------------------------------------------------
# Migración 001: esquema inicial del histórico
# ---------------------------------------------------------------------------

def _migracion_001(conexion: sqlite3.Connection) -> None:
    """Crea las cuatro tablas propias del histórico.

    - presencia_en_listado: marca de presencia/ausencia por (comunidad, codigo, fecha_listado).
    - serie_recuentos: serie histórica de recuentos totales del listado.
    - abstenciones_cierre: registro de abstenciones de cierre con motivo, recuentos y códigos.
    - ejecucion_diaria: fecha de cada ejecución del cierre diario.

    No contiene ninguna tabla ni columna de oferta (SUP-003/DEC-001).
    """
    sentencias = [
        """CREATE TABLE presencia_en_listado (
            comunidad TEXT NOT NULL,
            codigo TEXT NOT NULL,
            fecha_listado TEXT NOT NULL,
            presente INTEGER NOT NULL,
            PRIMARY KEY (comunidad, codigo, fecha_listado)
        )""",
        """CREATE TABLE serie_recuentos (
            id INTEGER PRIMARY KEY,
            recuento_total INTEGER NOT NULL,
            timestamp TEXT NOT NULL
        )""",
        """CREATE TABLE abstenciones_cierre (
            id INTEGER PRIMARY KEY,
            motivo TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            recuento_anterior INTEGER,
            recuento_actual INTEGER,
            umbral_aplicado TEXT,
            codigos_afectados TEXT
        )""",
        """CREATE TABLE ejecucion_diaria (
            fecha TEXT PRIMARY KEY
        )""",
    ]
    for sentencia in sentencias:
        conexion.execute(sentencia)


# ---------------------------------------------------------------------------
# Lista ordenada de migraciones (índice + 1 = número de versión)
# ---------------------------------------------------------------------------

MIGRACIONES = [_migracion_001]


# ---------------------------------------------------------------------------
# Funciones de versión
# ---------------------------------------------------------------------------

def _asegurar_tabla_version(conexion: sqlite3.Connection) -> None:
    """Crea la tabla schema_version si no existe."""
    conexion.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )


def _version_actual(conexion: sqlite3.Connection) -> int:
    """Devuelve la versión actual del esquema, o 0 si no hay ninguna."""
    fila = conexion.execute(
        "SELECT MAX(version) FROM schema_version"
    ).fetchone()
    return fila[0] if fila and fila[0] is not None else 0


def obtener_version_actual(conexion: sqlite3.Connection) -> int:
    """Devuelve la versión actual del esquema.

    Equivalente público de ``_version_actual``. Útil para inspeccionar el
    estado del esquema sin aplicar migraciones.

    Args:
        conexion: Conexión SQLite abierta.

    Returns:
        La versión del esquema (0 si no hay ninguna migración aplicada).
    """
    _asegurar_tabla_version(conexion)
    return _version_actual(conexion)


# ---------------------------------------------------------------------------
# Función pública
# ---------------------------------------------------------------------------

def migrar(conexion: sqlite3.Connection) -> int:
    """Aplica las migraciones pendientes sobre la conexión dada.

    - Crea schema_version si no existe.
    - Si la versión actual > última migración disponible, aborta con error
      (versión futura, ALT-004).
    - Aplica cada migración pendiente en su propia transacción.
    - Tras cada migración exitosa actualiza schema_version.
    - Si una migración falla, se deshace la transacción y se aborta.

    Args:
        conexion: Conexión SQLite abierta (no se abre internamente).

    Returns:
        La versión del esquema tras aplicar las migraciones.

    Raises:
        ErrorMigracion: si la versión actual es superior a la última migración
            o si una migración falla.
    """
    _asegurar_tabla_version(conexion)

    version_actual = _version_actual(conexion)
    ultima_version = len(MIGRACIONES)

    if version_actual > ultima_version:
        raise ErrorMigracion(
            f"La base de datos está en la versión {version_actual}, "
            f"pero la última migración disponible es la {ultima_version}. "
            "No se puede continuar (versión futura)."
        )

    for idx, funcion in enumerate(MIGRACIONES, start=1):
        if idx <= version_actual:
            continue
        try:
            with transaccion(conexion):
                funcion(conexion)
                aplicado_en = datetime.now(timezone.utc).isoformat()
                conexion.execute(
                    "INSERT INTO schema_version (version, applied_at) "
                    "VALUES (?, ?)",
                    (idx, aplicado_en),
                )
        except Exception as exc:
            raise ErrorMigracion(
                f"La migración {idx:03d} ha fallado: {exc}"
            ) from exc

    return _version_actual(conexion)
