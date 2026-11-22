"""Conexión única a SQLite del histórico con WAL y contexto de transacción."""

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

# Lock interno del módulo para serializar escrituras entre hilos.
_lock = threading.Lock()

# Tiempo de espera por ocupación de la base de datos (ms). 30 segundos.
BUSY_TIMEOUT_MS = 30000


def abrir_conexion(ruta: str | Path) -> sqlite3.Connection:
    """Abre o crea el fichero SQLite del histórico en la ruta dada.

    - Crea el directorio padre si no existe.
    - Ejecuta PRAGMA journal_mode = WAL.
    - Configura busy_timeout > 0.
    - Configura row_factory = sqlite3.Row para acceso por nombre de columna.
    - check_same_thread=False para compartir entre hilos.

    No abre ninguna conexión de escritura sobre la ruta del SQLite de
    persistencia (SUP-003) ni abre conexión de red.

    Args:
        ruta: Ruta al fichero SQLite (relativa a la raíz del proyecto).

    Returns:
        Una conexión sqlite3 ya configurada.
    """
    ruta_path = Path(ruta)
    ruta_path.parent.mkdir(parents=True, exist_ok=True)

    conexion = sqlite3.connect(
        str(ruta_path),
        check_same_thread=False,
    )
    # Control manual de transacciones: ni BEGIN implícito ni autocommit.
    conexion.isolation_level = None
    conexion.execute("PRAGMA journal_mode = WAL;")
    conexion.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS};")
    conexion.row_factory = sqlite3.Row
    return conexion


@contextmanager
def transaccion(conexion: sqlite3.Connection):
    """Contexto de transacción sobre la conexión.

    - BEGIN al entrar.
    - COMMIT si no hay excepción.
    - ROLLBACK si hay excepción.

    Usa el lock del módulo para serializar escrituras entre hilos.
    """
    with _lock:
        conexion.execute("BEGIN;")
        try:
            yield conexion
            conexion.execute("COMMIT;")
        except BaseException:
            conexion.execute("ROLLBACK;")
            raise


def lock_modulo() -> threading.Lock:
    """Devuelve el lock interno del módulo para uso externo si es necesario."""
    return _lock
