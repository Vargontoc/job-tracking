"""Pruebas de migraciones secuenciales del esquema propio del histórico (TASK-004)."""

import sqlite3

import pytest

from source.api.historico.connection import abrir_conexion
from source.api.historico.migrations import (
    MIGRACIONES,
    ErrorMigracion,
    migrar,
    obtener_version_actual,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ruta_db(tmp_path):
    """Devuelve la ruta de una BD temporal vacía."""
    return tmp_path / "test_historico_migrations.db"


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
    """Tras migrar existen schema_version y las 4 tablas propias del histórico."""

    def test_tablas_existen(self, conexion):
        migrar(conexion)
        tablas = {
            fila[0]
            for fila in conexion.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "schema_version" in tablas
        assert "presencia_en_listado" in tablas
        assert "serie_recuentos" in tablas
        assert "abstenciones_cierre" in tablas
        assert "ejecucion_diaria" in tablas

    def test_no_duplica_tablas_de_ofertas(self, conexion):
        """Ninguna tabla propia del histórico es 'ofertas' (SUP-003)."""
        migrar(conexion)
        tablas = {
            fila[0]
            for fila in conexion.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "ofertas" not in tablas


# ---------------------------------------------------------------------------
# Pruebas: columnas de presencia_en_listado
# ---------------------------------------------------------------------------

class TestColumnasPresencia:
    """La tabla presencia_en_listado tiene las columnas esperadas."""

    COLUMNAS_ESPERADAS = ["comunidad", "codigo", "fecha_listado", "presente"]

    def test_todas_las_columnas_presentes(self, conexion):
        migrar(conexion)
        columnas = {
            fila[1]
            for fila in conexion.execute(
                "PRAGMA table_info(presencia_en_listado)"
            ).fetchall()
        }
        for col in self.COLUMNAS_ESPERADAS:
            assert col in columnas, f"Falta la columna '{col}' en presencia_en_listado"

    def test_numero_columnas(self, conexion):
        migrar(conexion)
        filas = conexion.execute(
            "PRAGMA table_info(presencia_en_listado)"
        ).fetchall()
        assert len(filas) == 4

    def test_presente_es_integer(self, conexion):
        """presente es INTEGER (marca booleana 0/1)."""
        migrar(conexion)
        filas = conexion.execute(
            "PRAGMA table_info(presencia_en_listado)"
        ).fetchall()
        tipos = {fila[1]: fila[2].upper() for fila in filas}
        assert tipos["presente"] == "INTEGER"

    def test_primary_key_compuesta(self, conexion):
        """La PRIMARY KEY es (comunidad, codigo, fecha_listado)."""
        migrar(conexion)
        filas = conexion.execute(
            "PRAGMA table_info(presencia_en_listado)"
        ).fetchall()
        pk_cols = [fila[1] for fila in filas if fila[5] > 0]
        assert set(pk_cols) == {"comunidad", "codigo", "fecha_listado"}


# ---------------------------------------------------------------------------
# Pruebas: columnas de serie_recuentos
# ---------------------------------------------------------------------------

class TestColumnasSerieRecuentos:
    """La tabla serie_recuentos tiene las columnas esperadas."""

    COLUMNAS_ESPERADAS = ["id", "recuento_total", "timestamp"]

    def test_todas_las_columnas_presentes(self, conexion):
        migrar(conexion)
        columnas = {
            fila[1]
            for fila in conexion.execute(
                "PRAGMA table_info(serie_recuentos)"
            ).fetchall()
        }
        for col in self.COLUMNAS_ESPERADAS:
            assert col in columnas, f"Falta la columna '{col}' en serie_recuentos"

    def test_numero_columnas(self, conexion):
        migrar(conexion)
        filas = conexion.execute(
            "PRAGMA table_info(serie_recuentos)"
        ).fetchall()
        assert len(filas) == 3

    def test_recuento_total_es_integer_not_null(self, conexion):
        """recuento_total es INTEGER NOT NULL."""
        migrar(conexion)
        filas = conexion.execute(
            "PRAGMA table_info(serie_recuentos)"
        ).fetchall()
        tipos = {fila[1]: (fila[2].upper(), fila[3]) for fila in filas}
        assert tipos["recuento_total"][0] == "INTEGER"
        assert tipos["recuento_total"][1] == 1  # notnull


# ---------------------------------------------------------------------------
# Pruebas: columnas de abstenciones_cierre
# ---------------------------------------------------------------------------

class TestColumnasAbstenciones:
    """La tabla abstenciones_cierre tiene las columnas esperadas."""

    COLUMNAS_ESPERADAS = [
        "id", "motivo", "timestamp", "recuento_anterior",
        "recuento_actual", "umbral_aplicado", "codigos_afectados",
    ]

    def test_todas_las_columnas_presentes(self, conexion):
        migrar(conexion)
        columnas = {
            fila[1]
            for fila in conexion.execute(
                "PRAGMA table_info(abstenciones_cierre)"
            ).fetchall()
        }
        for col in self.COLUMNAS_ESPERADAS:
            assert col in columnas, f"Falta la columna '{col}' en abstenciones_cierre"

    def test_numero_columnas(self, conexion):
        migrar(conexion)
        filas = conexion.execute(
            "PRAGMA table_info(abstenciones_cierre)"
        ).fetchall()
        assert len(filas) == 7

    def test_motivo_es_text_not_null(self, conexion):
        """motivo es TEXT NOT NULL."""
        migrar(conexion)
        filas = conexion.execute(
            "PRAGMA table_info(abstenciones_cierre)"
        ).fetchall()
        tipos = {fila[1]: (fila[2].upper(), fila[3]) for fila in filas}
        assert tipos["motivo"][0] == "TEXT"
        assert tipos["motivo"][1] == 1  # notnull


# ---------------------------------------------------------------------------
# Pruebas: columnas de ejecucion_diaria
# ---------------------------------------------------------------------------

class TestColumnasEjecucionDiaria:
    """La tabla ejecucion_diaria tiene la columna fecha como PRIMARY KEY."""

    def test_columna_fecha_presente(self, conexion):
        migrar(conexion)
        columnas = {
            fila[1]
            for fila in conexion.execute(
                "PRAGMA table_info(ejecucion_diaria)"
            ).fetchall()
        }
        assert "fecha" in columnas

    def test_numero_columnas(self, conexion):
        migrar(conexion)
        filas = conexion.execute(
            "PRAGMA table_info(ejecucion_diaria)"
        ).fetchall()
        assert len(filas) == 1

    def test_fecha_es_primary_key(self, conexion):
        """fecha es PRIMARY KEY."""
        migrar(conexion)
        filas = conexion.execute(
            "PRAGMA table_info(ejecucion_diaria)"
        ).fetchall()
        pk_cols = [fila[1] for fila in filas if fila[5] > 0]
        assert pk_cols == ["fecha"]


# ---------------------------------------------------------------------------
# Pruebas: sin columnas de oferta en ninguna tabla propia (SUP-003)
# ---------------------------------------------------------------------------

class TestSinColumnasDeOferta:
    """Ninguna tabla propia del histórico contiene columnas de oferta."""

    COLUMNAS_PROHIBIDAS = [
        "estado", "texto_libre", "contacto", "embedding",
        "embedding_model_name", "embedding_model_version", "embedding_dim",
        "interesada", "fecha_alta", "fecha_ultima_actualizacion",
    ]

    def test_sin_columnas_de_oferta_en_presencia(self, conexion):
        migrar(conexion)
        columnas = {
            fila[1]
            for fila in conexion.execute(
                "PRAGMA table_info(presencia_en_listado)"
            ).fetchall()
        }
        for col in self.COLUMNAS_PROHIBIDAS:
            assert col not in columnas

    def test_sin_columnas_de_oferta_en_serie(self, conexion):
        migrar(conexion)
        columnas = {
            fila[1]
            for fila in conexion.execute(
                "PRAGMA table_info(serie_recuentos)"
            ).fetchall()
        }
        for col in self.COLUMNAS_PROHIBIDAS:
            assert col not in columnas

    def test_sin_columnas_de_oferta_en_abstenciones(self, conexion):
        migrar(conexion)
        columnas = {
            fila[1]
            for fila in conexion.execute(
                "PRAGMA table_info(abstenciones_cierre)"
            ).fetchall()
        }
        for col in self.COLUMNAS_PROHIBIDAS:
            assert col not in columnas


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

    def test_obtener_version_actual_publica(self, conexion):
        """obtener_version_actual() devuelve la versión sin aplicar migraciones."""
        # Antes de migrar, la versión es 0
        assert obtener_version_actual(conexion) == 0
        migrar(conexion)
        assert obtener_version_actual(conexion) == len(MIGRACIONES)


# ---------------------------------------------------------------------------
# Pruebas: BD ya migrada no reejecuta (idempotente)
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

    def test_migrar_dos_veces_no_falla(self, conexion):
        """Ejecutar migrar() dos veces no lanza excepción."""
        migrar(conexion)
        migrar(conexion)  # No debe fallar


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
            from source.api.historico import migrations as mod

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
