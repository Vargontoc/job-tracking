"""Pruebas unitarias del AdaptadorLecturaListado (TASK-003).

Comprueban que la conexión se abre en modo solo lectura sobre un SQLite que
simula el esquema de api-persistencia, que el ``busy_timeout`` está activo, que
la conexión se cierra al terminar cada consulta y que un fichero inexistente,
no válido o sin la tabla ``ofertas`` produce un error controlado distinguible.
Todas las pruebas trabajan sobre ``tmp_path``.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from source.api.listado.read_adapter import (
    BUSY_TIMEOUT_MS,
    MOTIVO_CONSULTA,
    MOTIVO_INEXISTENTE,
    MOTIVO_NO_VALIDO,
    MOTIVO_SIN_TABLA_OFERTAS,
    AdaptadorLecturaListado,
    ErrorAccesoDatos,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_RUTA_PERSISTENCIA = _REPO_ROOT / "source" / "api" / "persistencia"

# Misma tabla `ofertas` que tests/unit/test_historico_read_adapter.py: replica
# el esquema real de api-persistencia.
_SCHEMA = """\
CREATE TABLE ofertas (
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
);
"""

_SQL_INSERT = """\
INSERT INTO ofertas
    (comunidad, provincia, codigo, ocupacion, municipio, sector, nivel,
     contrato, fecha_inicio_difusion, fecha_fin_difusion, estado, texto_libre,
     contacto, embedding, embedding_model_name, embedding_model_version,
     embedding_dim, interesada, fecha_alta, fecha_cierre,
     fecha_ultima_actualizacion)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insertar(
    conexion: sqlite3.Connection,
    codigo: str,
    ocupacion: str = "Programador",
    municipio: str = "Santander",
    estado: str = "vigente",
    fecha_inicio_difusion: str = "15/11/2026",
) -> None:
    """Inserta una oferta con los valores por defecto del esquema simulado."""
    conexion.execute(
        _SQL_INSERT,
        (
            "Cantabria",
            "Cantabria",
            codigo,
            ocupacion,
            municipio,
            "",
            "",
            "",
            fecha_inicio_difusion,
            "20/11/2026",
            estado,
            "Texto libre de la oferta",
            "contacto@test.com",
            None,
            None,
            None,
            None,
            0,
            "2026-11-15T10:00:00+00:00",
            None,
            "2026-11-15T10:00:00+00:00",
        ),
    )


def _crear_bd(ruta: str | Path) -> None:
    """Crea un SQLite con la tabla ``ofertas`` y dos ofertas."""
    conexion = sqlite3.connect(str(ruta))
    try:
        conexion.execute(_SCHEMA)
        _insertar(conexion, codigo="061234567890", estado="cerrada")
        _insertar(conexion, codigo="061234567891", fecha_inicio_difusion="20/11/2026")
        conexion.commit()
    finally:
        conexion.close()


def _huellas_persistencia() -> dict[str, tuple[int, int]]:
    """Marca de modificación y tamaño de los ficheros de api-persistencia."""
    return {
        str(ruta.relative_to(_RUTA_PERSISTENCIA)): (
            ruta.stat().st_mtime_ns,
            ruta.stat().st_size,
        )
        for ruta in sorted(_RUTA_PERSISTENCIA.rglob("*"))
        if ruta.is_file() and "__pycache__" not in ruta.parts
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def ruta_bd(tmp_path: Path) -> str:
    """SQLite temporal que simula el esquema de api-persistencia."""
    ruta = tmp_path / "job_emcan.db"
    _crear_bd(ruta)
    return str(ruta)


@pytest.fixture()
def adaptador(ruta_bd: str) -> AdaptadorLecturaListado:
    return AdaptadorLecturaListado(ruta_bd)


# ---------------------------------------------------------------------------
# Pruebas: consulta en solo lectura
# ---------------------------------------------------------------------------

class TestConsulta:
    """El adaptador permite consultar la tabla ofertas con parámetros."""

    def test_consulta_devuelve_filas_de_ofertas(
        self, adaptador: AdaptadorLecturaListado
    ) -> None:
        filas = adaptador.consultar(
            "SELECT codigo, ocupacion FROM ofertas ORDER BY codigo"
        )

        assert [fila["codigo"] for fila in filas] == ["061234567890", "061234567891"]
        assert filas[0]["ocupacion"] == "Programador"

    def test_consulta_parametrizada_por_llamada(
        self, adaptador: AdaptadorLecturaListado
    ) -> None:
        filas = adaptador.consultar(
            "SELECT codigo FROM ofertas WHERE estado = ?", ("cerrada",)
        )

        assert [fila["codigo"] for fila in filas] == ["061234567890"]
        # La consulta siguiente no arrastra los parámetros de la anterior.
        assert len(adaptador.consultar("SELECT codigo FROM ofertas")) == 2

    def test_consulta_sin_filas_devuelve_lista_vacia(
        self, adaptador: AdaptadorLecturaListado
    ) -> None:
        filas = adaptador.consultar(
            "SELECT codigo FROM ofertas WHERE estado = ?", ("sin_ficha",)
        )

        assert filas == []


# ---------------------------------------------------------------------------
# Pruebas: modo solo lectura (DEC-001, REQ-010)
# ---------------------------------------------------------------------------

class TestSoloLectura:
    """La conexión se abre en modo solo lectura."""

    @pytest.mark.parametrize(
        "escritura",
        [
            "INSERT INTO ofertas (comunidad, codigo, estado, fecha_alta, "
            "fecha_ultima_actualizacion) VALUES "
            "('Cantabria', '999999999999', 'vigente', '2026-11-22', '2026-11-22')",
            "UPDATE ofertas SET ocupacion = 'Otro'",
            "DELETE FROM ofertas",
        ],
    )
    def test_escritura_rechazada_por_sqlite(
        self, adaptador: AdaptadorLecturaListado, escritura: str
    ) -> None:
        with pytest.raises(ErrorAccesoDatos) as error:
            adaptador.consultar(escritura)

        assert error.value.motivo == MOTIVO_CONSULTA
        total = adaptador.consultar("SELECT COUNT(*) AS total FROM ofertas")[0]
        assert total["total"] == 2

    def test_busy_timeout_mayor_que_cero(
        self, adaptador: AdaptadorLecturaListado
    ) -> None:
        filas = adaptador.consultar("PRAGMA busy_timeout")

        assert filas[0][0] > 0
        assert filas[0][0] == BUSY_TIMEOUT_MS

    def test_no_queda_conexion_abierta_al_terminar(
        self, adaptador: AdaptadorLecturaListado, ruta_bd: str
    ) -> None:
        adaptador.consultar("SELECT codigo FROM ofertas")

        # En Windows el fichero no se puede renombrar con una conexión abierta.
        destino = ruta_bd + ".renombrado"
        os.replace(ruta_bd, destino)

        assert os.path.isfile(destino)

    def test_no_queda_conexion_abierta_tras_un_error(
        self, adaptador: AdaptadorLecturaListado, ruta_bd: str
    ) -> None:
        with pytest.raises(ErrorAccesoDatos):
            adaptador.consultar("DELETE FROM ofertas")

        destino = ruta_bd + ".renombrado"
        os.replace(ruta_bd, destino)

        assert os.path.isfile(destino)

    def test_marca_de_modificacion_no_cambia(
        self, adaptador: AdaptadorLecturaListado, ruta_bd: str
    ) -> None:
        antes = os.stat(ruta_bd).st_mtime_ns

        adaptador.consultar("SELECT codigo FROM ofertas")
        adaptador.consultar("SELECT codigo FROM ofertas WHERE estado = ?", ("vigente",))
        adaptador.consultar("PRAGMA busy_timeout")

        assert os.stat(ruta_bd).st_mtime_ns == antes

    def test_no_escribe_bajo_el_modulo_de_persistencia(
        self, adaptador: AdaptadorLecturaListado
    ) -> None:
        assert _RUTA_PERSISTENCIA.is_dir()
        antes = _huellas_persistencia()
        assert antes, "Deben existir ficheros en source/api/persistencia/"

        adaptador.consultar("SELECT codigo FROM ofertas")

        assert _huellas_persistencia() == antes


# ---------------------------------------------------------------------------
# Pruebas: errores de acceso a los datos (ALT-001)
# ---------------------------------------------------------------------------

class TestErroresAcceso:
    """Un fichero inexistente, no válido o sin ofertas da un error distinguible."""

    def test_fichero_inexistente_no_lo_crea(self, tmp_path: Path) -> None:
        ruta = tmp_path / "no_existe.db"
        adaptador = AdaptadorLecturaListado(str(ruta))

        with pytest.raises(ErrorAccesoDatos) as error:
            adaptador.consultar("SELECT codigo FROM ofertas")

        assert error.value.motivo == MOTIVO_INEXISTENTE
        assert not ruta.exists()

    def test_sqlite_sin_tabla_ofertas(self, tmp_path: Path) -> None:
        ruta = tmp_path / "sin_ofertas.db"
        conexion = sqlite3.connect(str(ruta))
        try:
            conexion.execute("CREATE TABLE migraciones (version INTEGER NOT NULL)")
            conexion.commit()
        finally:
            conexion.close()

        adaptador = AdaptadorLecturaListado(str(ruta))

        with pytest.raises(ErrorAccesoDatos) as error:
            adaptador.consultar("SELECT codigo FROM ofertas")

        assert error.value.motivo == MOTIVO_SIN_TABLA_OFERTAS

    def test_fichero_que_no_es_sqlite(self, tmp_path: Path) -> None:
        ruta = tmp_path / "no_sqlite.db"
        ruta.write_bytes(b"esto no es un fichero SQLite" * 200)

        adaptador = AdaptadorLecturaListado(str(ruta))

        with pytest.raises(ErrorAccesoDatos) as error:
            adaptador.consultar("SELECT codigo FROM ofertas")

        assert error.value.motivo == MOTIVO_NO_VALIDO

    def test_el_error_identifica_el_acceso_a_los_datos(
        self, tmp_path: Path
    ) -> None:
        adaptador = AdaptadorLecturaListado(str(tmp_path / "no_existe.db"))

        with pytest.raises(ErrorAccesoDatos) as error:
            adaptador.consultar("SELECT codigo FROM ofertas")

        assert not isinstance(error.value, sqlite3.Error)
        assert "No se puede acceder a los datos" in str(error.value)
        assert error.value.detalle


# ---------------------------------------------------------------------------
# Pruebas: lectura concurrente con un escritor (ALT-005)
# ---------------------------------------------------------------------------

class TestLecturaConcurrente:
    """La lectura en mode=ro convive con un escritor sobre el mismo fichero."""

    def test_lectura_en_wal_con_escritor_abierto(self, tmp_path: Path) -> None:
        ruta = str(tmp_path / "wal.db")
        escritor = sqlite3.connect(ruta)
        try:
            escritor.execute("PRAGMA journal_mode = WAL")
            escritor.execute(_SCHEMA)
            _insertar(escritor, codigo="061234567890")
            escritor.commit()

            adaptador = AdaptadorLecturaListado(ruta)
            filas = adaptador.consultar("SELECT codigo FROM ofertas")
            assert [fila["codigo"] for fila in filas] == ["061234567890"]

            # La lectura no bloquea al escritor ni aborta su escritura.
            _insertar(escritor, codigo="061234567891")
            escritor.commit()

            assert len(adaptador.consultar("SELECT codigo FROM ofertas")) == 2
        finally:
            escritor.close()
