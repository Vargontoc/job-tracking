"""Pruebas unitarias del AdaptadorLecturaHistorica (TASK-010)."""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

import pytest

from source.api.historico.read_adapter import (
    AdaptadorLecturaHistorica,
    OfertaResumen,
    ResumenDiario,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _fila_oferta(
    comunidad: str = "Cantabria",
    codigo: str = "012345678901",
    ocupacion: str = "Programador",
    municipio: str = "Santander",
    estado: str = "vigente",
    fecha_alta: str = "2026-11-20T10:00:00+00:00",
    fecha_cierre: str | None = None,
    fecha_fin_difusion: str | None = None,
) -> tuple:
    """Genera una tupla completa para insertar en la tabla ofertas."""
    return (
        comunidad,
        "Cantabria",
        codigo,
        ocupacion,
        municipio,
        "",  # sector
        "",  # nivel
        "",  # contrato
        fecha_fin_difusion,  # fecha_inicio_difusion (simplificado)
        fecha_fin_difusion,
        estado,
        "Texto de prueba",
        "contacto@test.com",
        None,  # embedding
        None,  # embedding_model_name
        None,  # embedding_model_version
        None,  # embedding_dim
        0,  # interesada
        fecha_alta,
        fecha_cierre,
        fecha_alta,  # fecha_ultima_actualizacion
    )


# ---------------------------------------------------------------------------
# Fijtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def bd_con_datos(tmp_path: Path) -> str:
    """BD temporal con varias ofertas en distintas fechas."""
    ruta = str(tmp_path / "test_persistencia.db")
    conn = sqlite3.connect(ruta)
    conn.execute(_SCHEMA)

    ofertas = [
        _fila_oferta(codigo="000000000001", fecha_alta="2026-11-18T08:00:00+00:00"),
        _fila_oferta(codigo="000000000002", fecha_alta="2026-11-19T09:00:00+00:00"),
        _fila_oferta(
            codigo="000000000003",
            fecha_alta="2026-11-19T10:00:00+00:00",
            estado="cerrada",
            fecha_cierre="2026-11-21T12:00:00+00:00",
            fecha_fin_difusion="2026-11-20",
        ),
        _fila_oferta(
            codigo="000000000004",
            fecha_alta="2026-11-20T07:00:00+00:00",
            estado="cerrada",
            fecha_cierre="2026-11-22T15:00:00+00:00",
            fecha_fin_difusion="2026-11-21",
        ),
    ]
    conn.executemany(
        """INSERT INTO ofertas
           (comunidad, provincia, codigo, ocupacion, municipio,
            sector, nivel, contrato, fecha_inicio_difusion,
            fecha_fin_difusion, estado, texto_libre, contacto,
            embedding, embedding_model_name, embedding_model_version,
            embedding_dim, interesada, fecha_alta, fecha_cierre,
            fecha_ultima_actualizacion)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ofertas,
    )
    conn.commit()
    conn.close()
    return ruta


@pytest.fixture()
def adaptador(bd_con_datos: str) -> AdaptadorLecturaHistorica:
    return AdaptadorLecturaHistorica(bd_con_datos)


# ---------------------------------------------------------------------------
# Pruebas: modo solo lectura
# ---------------------------------------------------------------------------

class TestSoloLectura:
    """La conexión debe abrirse en modo solo lectura (DEC-006)."""

    def test_escritura_rechazada(self, bd_con_datos: str) -> None:
        """Un intento de escritura sobre la conexión de solo lectura es rechazado."""
        adaptador = AdaptadorLecturaHistorica(bd_con_datos)
        conn = adaptador._abrir()
        assert conn is not None
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO ofertas (comunidad, codigo, estado, fecha_alta, fecha_ultima_actualizacion) VALUES ('X', '999999999999', 'vigente', '2026-11-22', '2026-11-22')")
        conn.close()

    def test_fichero_inexistente_devuelve_vacio(self, tmp_path: Path) -> None:
        """Si el fichero no existe, las consultas devuelven listas vacías."""
        ruta = str(tmp_path / "no_existe.db")
        adaptador = AdaptadorLecturaHistorica(ruta)
        assert adaptador.altas_por_fecha("2026-01-01", "2026-12-31") == []
        assert adaptador.cierres_por_fecha("2026-01-01", "2026-12-31") == []
        resumen = adaptador.resumen_diario("2026-11-20")
        assert resumen == ResumenDiario(fecha="2026-11-20", altas=0, cierres=0)
        # El fichero NO se ha creado
        assert not os.path.exists(ruta)


# ---------------------------------------------------------------------------
# Pruebas: altas por fecha
# ---------------------------------------------------------------------------

class TestAltasPorFecha:
    """Consultas de altas por rango de fecha_alta."""

    def test_altas_dentro_del_rango(self, adaptador: AdaptadorLecturaHistorica) -> None:
        resultado = adaptador.altas_por_fecha("2026-11-19", "2026-11-19")
        assert len(resultado) == 2
        codigos = {o.codigo for o in resultado}
        assert codigos == {"000000000002", "000000000003"}

    def test_altas_rango_amplio(self, adaptador: AdaptadorLecturaHistorica) -> None:
        resultado = adaptador.altas_por_fecha("2026-11-18", "2026-11-20")
        assert len(resultado) == 4

    def test_altas_fuera_del_rango(self, adaptador: AdaptadorLecturaHistorica) -> None:
        resultado = adaptador.altas_por_fecha("2026-12-01", "2026-12-31")
        assert resultado == []

    def test_altas_campos_incluidos(self, adaptador: AdaptadorLecturaHistorica) -> None:
        resultado = adaptador.altas_por_fecha("2026-11-18", "2026-11-18")
        assert len(resultado) == 1
        oferta = resultado[0]
        assert oferta.comunidad == "Cantabria"
        assert oferta.codigo == "000000000001"
        assert oferta.ocupacion == "Programador"
        assert oferta.municipio == "Santander"
        assert oferta.fecha_alta.startswith("2026-11-18")
        assert oferta.fecha_cierre is None


# ---------------------------------------------------------------------------
# Pruebas: cierres por fecha
# ---------------------------------------------------------------------------

class TestCierresPorFecha:
    """Consultas de cierres por rango de fecha_cierre."""

    def test_cierres_dentro_del_rango(self, adaptador: AdaptadorLecturaHistorica) -> None:
        resultado = adaptador.cierres_por_fecha("2026-11-21", "2026-11-21")
        assert len(resultado) == 1
        assert resultado[0].codigo == "000000000003"
        assert resultado[0].fecha_cierre is not None

    def test_cierres_rango_amplio(self, adaptador: AdaptadorLecturaHistorica) -> None:
        resultado = adaptador.cierres_por_fecha("2026-11-21", "2026-11-22")
        assert len(resultado) == 2
        codigos = {o.codigo for o in resultado}
        assert codigos == {"000000000003", "000000000004"}

    def test_cierres_sin_resultados(self, adaptador: AdaptadorLecturaHistorica) -> None:
        resultado = adaptador.cierres_por_fecha("2026-01-01", "2026-01-31")
        assert resultado == []

    def test_cierres_solo_con_fecha_cierre(self, adaptador: AdaptadorLecturaHistorica) -> None:
        """Las ofertas sin fecha_cierre no aparecen en la consulta de cierres."""
        resultado = adaptador.cierres_por_fecha("2026-11-18", "2026-12-31")
        codigos = {o.codigo for o in resultado}
        # Las ofertas 1 y 2 no tienen fecha_cierre
        assert "000000000001" not in codigos
        assert "000000000002" not in codigos


class TestCierresPorFechaFinDifusion:
    """Consultas de cierres por rango de fecha_fin_difusion."""

    def test_cierres_fin_difusion_dentro_del_rango(self, adaptador: AdaptadorLecturaHistorica) -> None:
        """Ofertas con fecha_fin_difusion en el rango aparecen."""
        resultado = adaptador.cierres_por_fecha_fin_difusion("2026-11-20", "2026-11-20")
        assert len(resultado) == 1
        assert resultado[0].codigo == "000000000003"

    def test_cierres_fin_difusion_rango_amplio(self, adaptador: AdaptadorLecturaHistorica) -> None:
        resultado = adaptador.cierres_por_fecha_fin_difusion("2026-11-20", "2026-11-21")
        assert len(resultado) == 2
        codigos = {o.codigo for o in resultado}
        assert codigos == {"000000000003", "000000000004"}

    def test_cierres_fin_difusion_sin_resultados(self, adaptador: AdaptadorLecturaHistorica) -> None:
        resultado = adaptador.cierres_por_fecha_fin_difusion("2026-01-01", "2026-01-31")
        assert resultado == []


# ---------------------------------------------------------------------------
# Pruebas: resumen diario
# ---------------------------------------------------------------------------

class TestResumenDiario:
    """Resumen diario de altas y cierres para una fecha."""

    def test_resumen_con_altas_y_cierres(self, adaptador: AdaptadorLecturaHistorica) -> None:
        # 2026-11-20: 1 alta (codigo 4) y 0 cierres
        resumen = adaptador.resumen_diario("2026-11-20")
        assert resumen.fecha == "2026-11-20"
        assert resumen.altas == 1
        assert resumen.cierres == 0

    def test_resumen_dia_con_cierres(self, adaptador: AdaptadorLecturaHistorica) -> None:
        resumen = adaptador.resumen_diario("2026-11-21")
        assert resumen.altas == 0
        assert resumen.cierres == 1

    def test_resumen_dia_sin_datos(self, adaptador: AdaptadorLecturaHistorica) -> None:
        resumen = adaptador.resumen_diario("2026-01-01")
        assert resumen == ResumenDiario(fecha="2026-01-01", altas=0, cierres=0)

    def test_resumen_dia_con_ambos(self, bd_con_datos: str) -> None:
        """Crear una oferta con alta y cierre el mismo día."""
        conn = sqlite3.connect(bd_con_datos)
        conn.execute(
            """INSERT INTO ofertas
               (comunidad, provincia, codigo, ocupacion, municipio,
                sector, nivel, contrato, fecha_inicio_difusion,
                fecha_fin_difusion, estado, texto_libre, contacto,
                embedding, embedding_model_name, embedding_model_version,
                embedding_dim, interesada, fecha_alta, fecha_cierre,
                fecha_ultima_actualizacion)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            _fila_oferta(
                codigo="000000000005",
                fecha_alta="2026-11-25T08:00:00+00:00",
                estado="cerrada",
                fecha_cierre="2026-11-25T18:00:00+00:00",
            ),
        )
        conn.commit()
        conn.close()

        adaptador = AdaptadorLecturaHistorica(bd_con_datos)
        resumen = adaptador.resumen_diario("2026-11-25")
        assert resumen.altas == 1
        assert resumen.cierres == 1


# ---------------------------------------------------------------------------
# Pruebas: no modifica el fichero
# ---------------------------------------------------------------------------

class TestNoModificaFichero:
    """Las lecturas no modifican la marca de modificación del fichero."""

    def test_marca_modificacion_no_cambia(self, adaptador: AdaptadorLecturaHistorica, bd_con_datos: str) -> None:
        mtime_antes = os.path.getmtime(bd_con_datos)
        time.sleep(0.05)  # pequeña pausa para asegurar diferencia de resolución

        # Ejecutar todas las consultas
        adaptador.altas_por_fecha("2026-11-01", "2026-12-31")
        adaptador.cierres_por_fecha("2026-11-01", "2026-12-31")
        adaptador.cierres_por_fecha_fin_difusion("2026-11-01", "2026-12-31")
        adaptador.resumen_diario("2026-11-20")

        mtime_despues = os.path.getmtime(bd_con_datos)
        assert mtime_antes == mtime_despues
