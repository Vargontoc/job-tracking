"""Pruebas de migraciones secuenciales y esquema SQLite (TASK-004)."""

import sqlite3

import pytest

from source.api.persistencia.connection import abrir_conexion
from source.api.persistencia.migrations import (
    MIGRACIONES,
    ErrorMigracion,
    migrar,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ruta_db(tmp_path):
    """Devuelve la ruta de una BD temporal vacía."""
    return tmp_path / "test_migrations.db"


@pytest.fixture
def conexion(ruta_db):
    """Abre una conexión a una BD temporal y la cierra al terminar."""
    conn = abrir_conexion(ruta_db)
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Pruebas: tablas existen tras migrar
# ---------------------------------------------------------------------------

class TestTablasExistentes:
    """Tras migrar existen schema_version, ofertas e ingesta_log."""

    def test_tablas_existen(self, conexion):
        migrar(conexion)
        tablas = {
            fila[0]
            for fila in conexion.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "schema_version" in tablas
        assert "ofertas" in tablas
        assert "ingesta_log" in tablas


# ---------------------------------------------------------------------------
# Pruebas: columnas de ofertas
# ---------------------------------------------------------------------------

COLUMNAS_ESPERADAS = [
    "comunidad", "provincia", "codigo", "ocupacion", "municipio",
    "sector", "nivel", "contrato", "fecha_inicio_difusion",
    "fecha_fin_difusion", "estado", "texto_libre", "contacto",
    "embedding", "embedding_model_name", "embedding_model_version",
    "embedding_dim", "interesada", "fecha_alta", "fecha_cierre",
    "fecha_ultima_actualizacion",
]


class TestColumnasOfertas:
    """La tabla ofertas tiene las 21 columnas esperadas."""

    def test_todas_las_columnas_presentes(self, conexion):
        migrar(conexion)
        columnas = {
            fila[1]
            for fila in conexion.execute("PRAGMA table_info(ofertas)").fetchall()
        }
        for col in COLUMNAS_ESPERADAS:
            assert col in columnas, f"Falta la columna '{col}' en ofertas"

    def test_numero_columnas(self, conexion):
        migrar(conexion)
        filas = conexion.execute("PRAGMA table_info(ofertas)").fetchall()
        assert len(filas) == 21

    def test_embedding_es_blob(self, conexion):
        """embedding es de tipo BLOB (DEC-002)."""
        migrar(conexion)
        filas = conexion.execute("PRAGMA table_info(ofertas)").fetchall()
        tipos = {fila[1]: fila[2].upper() for fila in filas}
        assert tipos["embedding"] == "BLOB"

    def test_embedding_dim_es_entero(self, conexion):
        """embedding_dim es de tipo INTEGER (DEC-002)."""
        migrar(conexion)
        filas = conexion.execute("PRAGMA table_info(ofertas)").fetchall()
        tipos = {fila[1]: fila[2].upper() for fila in filas}
        assert tipos["embedding_dim"] == "INTEGER"

    def test_interesada_defecto_cero(self, conexion):
        """interesada es INTEGER con valor por defecto 0 (DEC-007)."""
        migrar(conexion)
        # Insertar una oferta sin especificar interesada
        conexion.execute(
            """INSERT INTO ofertas
               (comunidad, codigo, estado, fecha_alta, fecha_ultima_actualizacion)
               VALUES ('Cantabria', '000000000001', 'vigente', '2026-01-01', '2026-01-01')"""
        )
        fila = conexion.execute(
            "SELECT interesada FROM ofertas WHERE codigo = '000000000001'"
        ).fetchone()
        assert fila[0] == 0


# ---------------------------------------------------------------------------
# Pruebas: sin tabla ni extensión vectorial (NFR-005)
# ---------------------------------------------------------------------------

class TestSinExtensionVectorial:
    """No existe ninguna tabla de vectores ni extensión vectorial cargada."""

    def test_sin_tablas_vectoriales(self, conexion):
        migrar(conexion)
        tablas = {
            fila[0]
            for fila in conexion.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        # No debe existir ninguna tabla con nombre sugerente de vectores
        for tabla in tablas:
            assert "vector" not in tabla.lower()

    def test_sin_extensiones_cargadas(self, conexion):
        """No hay extensiones cargadas (no hay pragma module_list relevante)."""
        migrar(conexion)
        # sqlite3 no expone extensiones de forma estándar; simplemente
        # comprobamos que no existe tabla sqlite_* con contenido vectorial.
        tablas = {
            fila[0]
            for fila in conexion.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert not any("vec" in t.lower() for t in tablas)


# ---------------------------------------------------------------------------
# Pruebas: restricción UNIQUE (comunidad, codigo) (REQ-007)
# ---------------------------------------------------------------------------

class TestRestriccionUnique:
    """Insertar dos ofertas con misma comunidad y código viola UNIQUE."""

    def test_unique_violation(self, conexion):
        migrar(conexion)
        conexion.execute(
            """INSERT INTO ofertas
               (comunidad, codigo, estado, fecha_alta, fecha_ultima_actualizacion)
               VALUES ('Cantabria', '000000000001', 'vigente', '2026-01-01', '2026-01-01')"""
        )
        with pytest.raises(sqlite3.IntegrityError):
            conexion.execute(
                """INSERT INTO ofertas
                   (comunidad, codigo, estado, fecha_alta, fecha_ultima_actualizacion)
                   VALUES ('Cantabria', '000000000001', 'vigente', '2026-01-02', '2026-01-02')"""
            )


# ---------------------------------------------------------------------------
# Pruebas: índices
# ---------------------------------------------------------------------------

class TestIndices:
    """Los índices (estado, fecha_fin_difusion) y (embedding_model_name,
    embedding_model_version) existen."""

    def test_indice_estado_fecha_fin(self, conexion):
        migrar(conexion)
        indices = {
            fila[0]
            for fila in conexion.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        assert "idx_ofertas_estado_fecha_fin" in indices

    def test_indice_embedding_model(self, conexion):
        migrar(conexion)
        indices = {
            fila[0]
            for fila in conexion.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        assert "idx_ofertas_embedding_model" in indices


# ---------------------------------------------------------------------------
# Pruebas: schema_version
# ---------------------------------------------------------------------------

class TestSchemaVersion:
    """La tabla schema_version refleja la versión aplicada."""

    def test_version_registrada(self, conexion):
        version = migrar(conexion)
        assert version == len(MIGRACIONES)
        fila = conexion.execute(
            "SELECT version, applied_at FROM schema_version WHERE version = ?",
            (len(MIGRACIONES),),
        ).fetchone()
        assert fila is not None
        assert fila[0] == len(MIGRACIONES)
        assert fila[1]  # applied_at no vacío


# ---------------------------------------------------------------------------
# Pruebas: BD ya migrada no reejecuta
# ---------------------------------------------------------------------------

class TestIdempotencia:
    """Al migrar una BD ya en la versión esperada, no se ejecuta nada nuevo."""

    def test_no_reejecuta(self, conexion):
        version_1 = migrar(conexion)
        # Modificar applied_at para detectar si se reinserta
        conexion.execute(
            "UPDATE schema_version SET applied_at = 'ya-estaba' WHERE version = ?",
            (version_1,),
        )
        version_2 = migrar(conexion)
        assert version_2 == version_1
        # applied_at sigue siendo el modificado (no se ha reinsertado)
        fila = conexion.execute(
            "SELECT applied_at FROM schema_version WHERE version = ?",
            (version_1,),
        ).fetchone()
        assert fila[0] == "ya-estaba"


# ---------------------------------------------------------------------------
# Pruebas: versión futura aborta (ALT-004)
# ---------------------------------------------------------------------------

class TestVersionFutura:
    """Una BD con versión superior a la esperada aborta con error explícito."""

    def test_aborta_sin_modificar(self, ruta_db):
        # Migrar primero con una conexión dedicada
        conn_ini = abrir_conexion(ruta_db)
        try:
            migrar(conn_ini)
            # Insertar una versión futura
            conn_ini.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (999, 'futuro')"
            )
            # Con isolation_level=None, la sentencia ya está confirmada.
        finally:
            conn_ini.close()

        # Reabrir para verificar que migrar aborta sin modificar la versión
        conn2 = abrir_conexion(ruta_db)
        try:
            with pytest.raises(ErrorMigracion, match="versión futura"):
                migrar(conn2)
        finally:
            conn2.close()

        # La versión sigue siendo 999 (no se ha modificado)
        conn3 = abrir_conexion(ruta_db)
        try:
            fila = conn3.execute(
                "SELECT MAX(version) FROM schema_version"
            ).fetchone()
            assert fila[0] == 999
        finally:
            conn3.close()


# ---------------------------------------------------------------------------
# Pruebas: migración fallida deshace la transacción
# ---------------------------------------------------------------------------

class TestMigracionFallida:
    """Una migración que falla deja el esquema en el estado anterior."""

    def test_rollback_en_fallo(self, tmp_path):
        ruta = tmp_path / "fallo.db"
        conn = abrir_conexion(ruta)
        try:
            # Crear la tabla schema_version y registrar versión 1 como si
            # la migración 001 ya se hubiera aplicado.
            conn.execute(
                "CREATE TABLE schema_version ("
                "  version INTEGER PRIMARY KEY,"
                "  applied_at TEXT NOT NULL"
                ")"
            )
            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (1, 'ok')"
            )
            conn.commit()

            # Añadir una migración 002 que falla a la lista
            from source.api.persistencia import migrations as mod

            def _migracion_fallida(c):
                # Primero crear algo...
                c.execute("CREATE TABLE tabla_efimera (id INTEGER)")
                # ...y luego fallar
                raise RuntimeError("fallo intencionado")

            originales = mod.MIGRACIONES
            mod.MIGRACIONES = list(originales) + [_migracion_fallida]
            try:
                with pytest.raises(ErrorMigracion, match="fallo intencionado"):
                    migrar(conn)
            finally:
                mod.MIGRACIONES = originales

            # La tabla efímera no debe existir (rollback)
            tablas = {
                fila[0]
                for fila in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert "tabla_efimera" not in tablas

            # La versión sigue siendo 1
            version = conn.execute(
                "SELECT MAX(version) FROM schema_version"
            ).fetchone()
            assert version[0] == 1
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Pruebas: tabla ingesta_log con registro inicial
# ---------------------------------------------------------------------------

class TestIngestaLog:
    """La tabla ingesta_log tiene un único registro id=1 tras migrar."""

    def test_registro_inicial(self, conexion):
        migrar(conexion)
        filas = conexion.execute("SELECT id, ultimo_timestamp FROM ingesta_log").fetchall()
        assert len(filas) == 1
        assert filas[0][0] == 1
        assert filas[0][1] is None  # ultimo_timestamp inicial es NULL
