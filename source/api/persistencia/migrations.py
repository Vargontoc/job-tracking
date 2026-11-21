"""Migraciones secuenciales del esquema SQLite y función de aplicación."""

import sqlite3
from datetime import datetime, timezone

from source.api.persistencia.connection import transaccion


class ErrorMigracion(Exception):
    """Error durante la aplicación de migraciones."""


# ---------------------------------------------------------------------------
# Migración 001: esquema inicial
# ---------------------------------------------------------------------------

def _migracion_001(conexion: sqlite3.Connection) -> None:
    """Crea las tablas ofertas e ingesta_log con sus índices y restricción UNIQUE."""
    sentencias = [
        """CREATE TABLE ofertas (
            comunidad TEXT NOT NULL,
            provincia TEXT,
            codigo TEXT NOT NULL,
            ocupacion TEXT,
            municipio TEXT,
            sector TEXT DEFAULT '',
            nivel TEXT DEFAULT '',
            contrato TEXT DEFAULT '',
            fecha_inicio_difusion TEXT,
            fecha_fin_difusion TEXT,
            estado TEXT NOT NULL,
            texto_libre TEXT,
            contacto TEXT,
            embedding BLOB,
            embedding_model_name TEXT,
            embedding_model_version TEXT,
            embedding_dim INTEGER,
            interesada INTEGER DEFAULT 0,
            fecha_alta TEXT NOT NULL,
            fecha_cierre TEXT,
            fecha_ultima_actualizacion TEXT NOT NULL,
            PRIMARY KEY (comunidad, codigo)
        )""",
        "CREATE INDEX idx_ofertas_estado_fecha_fin ON ofertas(estado, fecha_fin_difusion)",
        "CREATE INDEX idx_ofertas_embedding_model ON ofertas(embedding_model_name, embedding_model_version)",
        """CREATE TABLE ingesta_log (
            id INTEGER PRIMARY KEY,
            ultimo_timestamp TEXT,
            actualizado_en TEXT NOT NULL
        )""",
        "INSERT INTO ingesta_log (id, ultimo_timestamp, actualizado_en) VALUES (1, NULL, datetime('now'))",
    ]
    for sentencia in sentencias:
        conexion.execute(sentencia)


# ---------------------------------------------------------------------------
# Lista ordenada de migraciones (índice + 1 = número de versión)
# ---------------------------------------------------------------------------

MIGRACIONES = [_migracion_001]


# ---------------------------------------------------------------------------
# Función pública
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
