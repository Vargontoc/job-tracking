"""Pruebas unitarias del repositorio de consulta del listado (TASK-007).

Trabajan sobre un SQLite temporal que simula el esquema real de
api-persistencia y cubren el orden, el desempate, la paginación, el filtrado
textual en memoria, los campos purgados, la visibilidad por estado y la
garantía de solo lectura.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from source.api.listado.read_adapter import AdaptadorLecturaListado
from source.api.listado.repository import (
    OfertaListado,
    RepositorioListado,
    ResultadoListado,
)

# Misma tabla `ofertas` que tests/unit/test_historico_read_adapter.py y
# tests/unit/test_listado_read_adapter.py: replica el esquema real.
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
    *,
    ocupacion: str = "Programador",
    municipio: str = "Santander",
    provincia: str = "Cantabria",
    sector: str = "",
    estado: str = "vigente",
    fecha_inicio: str = "15/11/2026",
    fecha_fin: str = "20/11/2026",
    texto_libre: str = "Texto libre de la oferta",
    contacto: str = "contacto@test.com",
) -> None:
    """Inserta una oferta con los valores por defecto del esquema simulado."""
    conexion.execute(
        _SQL_INSERT,
        (
            "Cantabria",
            provincia,
            codigo,
            ocupacion,
            municipio,
            sector,
            "",
            "",
            fecha_inicio,
            fecha_fin,
            estado,
            texto_libre,
            contacto,
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


def _crear_bd(ruta: str | Path, ofertas: list[dict[str, Any]]) -> str:
    """Crea el SQLite temporal y puebla las ofertas indicadas."""
    conexion = sqlite3.connect(str(ruta))
    try:
        conexion.execute(_SCHEMA)
        for oferta in ofertas:
            _insertar(conexion, **oferta)
        conexion.commit()
    finally:
        conexion.close()
    return str(ruta)


def _bd(tmp_path: Path, ofertas: list[dict[str, Any]]) -> str:
    """Crea una base temporal de uso exclusivo de una prueba."""
    return _crear_bd(tmp_path / "job_emcan.db", ofertas)


def _repositorio(ruta: str) -> RepositorioListado:
    """Repositorio apoyado en el adaptador de solo lectura."""
    return RepositorioListado(AdaptadorLecturaListado(ruta))


class _AdaptadorEspia:
    """Adaptador que registra las consultas SQL que recibe."""

    def __init__(self, adaptador: AdaptadorLecturaListado) -> None:
        self._adaptador = adaptador
        self.consultas: list[str] = []

    def consultar(
        self, consulta: str, parametros: Sequence[object] = ()
    ) -> list[Any]:
        self.consultas.append(consulta)
        return self._adaptador.consultar(consulta, parametros)


# ---------------------------------------------------------------------------
# Pruebas: orden y desempate (REQ-007, SUP-004)
# ---------------------------------------------------------------------------

class TestOrden:
    """Fecha de inicio descendente y desempate por código ascendente."""

    def test_orden_por_fecha_descendente(self, tmp_path: Path) -> None:
        ruta = _bd(
            tmp_path,
            [
                {"codigo": "000000000015", "fecha_inicio": "15/11/2026"},
                {"codigo": "000000000030", "fecha_inicio": "30/11/2026"},
                {"codigo": "000000000020", "fecha_inicio": "20/11/2026"},
            ],
        )

        resultado = _repositorio(ruta).consultar({})

        assert [oferta.codigo for oferta in resultado.items] == [
            "000000000030",
            "000000000020",
            "000000000015",
        ]

    def test_desempate_por_codigo_ascendente(self, tmp_path: Path) -> None:
        ruta = _bd(
            tmp_path,
            [
                {"codigo": "061234567891", "fecha_inicio": "20/11/2026"},
                {"codigo": "061234567890", "fecha_inicio": "20/11/2026"},
            ],
        )

        resultado = _repositorio(ruta).consultar({})

        assert [oferta.codigo for oferta in resultado.items] == [
            "061234567890",
            "061234567891",
        ]


# ---------------------------------------------------------------------------
# Pruebas: paginación sin filtros textuales (REQ-007, DEC-002, ALT-003)
# ---------------------------------------------------------------------------

class TestPaginacionSinTexto:
    """Sin filtros textuales, el total se cuenta en SQL y la página va en SQL."""

    def test_total_por_count_y_pagina_por_limit_offset(self, tmp_path: Path) -> None:
        ruta = _bd(
            tmp_path,
            [{"codigo": f"{numero:012d}"} for numero in range(1, 6)],
        )
        repositorio = _repositorio(ruta)

        primera = repositorio.consultar({}, offset=0, tamano_pagina=2)
        segunda = repositorio.consultar({}, offset=2, tamano_pagina=2)

        assert primera.total == 5
        assert [oferta.codigo for oferta in primera.items] == [
            "000000000001",
            "000000000002",
        ]
        assert primera.pagina == 1
        assert primera.tamano_pagina == 2
        assert [oferta.codigo for oferta in segunda.items] == [
            "000000000003",
            "000000000004",
        ]
        assert segunda.pagina == 2

    def test_cincuenta_ofertas_pagina_21_a_40(self, tmp_path: Path) -> None:
        ruta = _bd(
            tmp_path,
            [{"codigo": f"{numero:012d}"} for numero in range(1, 51)],
        )

        resultado = _repositorio(ruta).consultar({}, offset=20, tamano_pagina=20)

        assert resultado.total == 50
        assert [oferta.codigo for oferta in resultado.items] == [
            f"{numero:012d}" for numero in range(21, 41)
        ]
        assert resultado.pagina == 2

    def test_offset_mayor_o_igual_que_el_total(self, tmp_path: Path) -> None:
        ruta = _bd(
            tmp_path,
            [{"codigo": f"{numero:012d}"} for numero in range(1, 6)],
        )

        resultado = _repositorio(ruta).consultar({}, offset=10, tamano_pagina=10)

        assert resultado.items == []
        assert resultado.total == 5

    def test_la_consulta_sin_texto_usa_limit_y_offset(self, tmp_path: Path) -> None:
        ruta = _bd(tmp_path, [{"codigo": "000000000001"}])
        espia = _AdaptadorEspia(AdaptadorLecturaListado(ruta))
        espia_registro = _repositorio_espia(espia)

        espia_registro.consultar({}, offset=0, tamano_pagina=1)

        assert any("COUNT(*)" in consulta for consulta in espia.consultas)
        assert any("LIMIT ? OFFSET ?" in consulta for consulta in espia.consultas)


def _repositorio_espia(espia: _AdaptadorEspia) -> RepositorioListado:
    """Repositorio con el adaptador espía (sin comprobar el tipo nominal)."""
    return RepositorioListado(espia)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Pruebas: filtros textuales en memoria (REQ-002, DEC-002, NFR-003)
# ---------------------------------------------------------------------------

class TestFiltroTexto:
    """El texto libre se aplica después de recuperar las candidatas."""

    def test_tecnico_encuentra_la_ocupacion_con_tilde(self, tmp_path: Path) -> None:
        ruta = _bd(
            tmp_path,
            [
                {"codigo": "000000000001", "ocupacion": "Técnico de sistemas"},
                {"codigo": "000000000002", "ocupacion": "Albañil"},
            ],
        )

        resultado = _repositorio(ruta).consultar({"texto": "tecnico"})

        assert resultado.total == 1
        assert [oferta.codigo for oferta in resultado.items] == ["000000000001"]
        assert resultado.filtros_aplicados == {"texto": "tecnico"}

    def test_texto_sin_coincidencias(self, tmp_path: Path) -> None:
        ruta = _bd(tmp_path, [{"codigo": "000000000001"}])

        resultado = _repositorio(ruta).consultar({"texto": "astronauta"})

        assert resultado.items == []
        assert resultado.total == 0

    def test_el_total_es_el_del_conjunto_filtrado(self, tmp_path: Path) -> None:
        ofertas = [
            {"codigo": f"{numero:012d}", "ocupacion": "Albañil"}
            for numero in range(1, 6)
        ]
        ofertas.append({"codigo": "000000000006", "ocupacion": "Técnico"})
        ruta = _bd(tmp_path, ofertas)

        resultado = _repositorio(ruta).consultar({"texto": "tecnico"})

        assert resultado.total == 1
        assert [oferta.codigo for oferta in resultado.items] == ["000000000006"]

    def test_no_aplica_limit_offset_antes_de_filtrar(self, tmp_path: Path) -> None:
        # Cinco ofertas más recientes que no coinciden y una más antigua que sí:
        # si SQL paginara antes de filtrar, la coincidencia no aparecería.
        ofertas = [
            {
                "codigo": f"{numero:012d}",
                "ocupacion": "Albañil",
                "fecha_inicio": f"{numero:02d}/12/2026",
            }
            for numero in range(1, 6)
        ]
        ofertas.append(
            {
                "codigo": "000000000099",
                "ocupacion": "Técnico de sistemas",
                "fecha_inicio": "01/11/2026",
            }
        )
        ruta = _bd(tmp_path, ofertas)
        espia = _AdaptadorEspia(AdaptadorLecturaListado(ruta))

        resultado = _repositorio_espia(espia).consultar(
            {"texto": "tecnico"}, offset=0, tamano_pagina=2
        )

        assert resultado.total == 1
        assert [oferta.codigo for oferta in resultado.items] == ["000000000099"]
        assert not any("LIMIT" in consulta for consulta in espia.consultas)
        assert any("ORDER BY" in consulta for consulta in espia.consultas)

    def test_texto_y_municipio_se_combinan(self, tmp_path: Path) -> None:
        ruta = _bd(
            tmp_path,
            [
                {
                    "codigo": "000000000001",
                    "ocupacion": "Programador",
                    "municipio": "SANTANDER",
                },
                {
                    "codigo": "000000000002",
                    "ocupacion": "Programador",
                    "municipio": "Torrelavega",
                },
            ],
        )

        resultado = _repositorio(ruta).consultar(
            {"texto": "programador", "municipio": "santander"}
        )

        assert resultado.total == 1
        assert [oferta.codigo for oferta in resultado.items] == ["000000000001"]

    def test_pagina_se_recorta_tras_filtrar_en_memoria(self, tmp_path: Path) -> None:
        # Dos candidatas recientes que no coinciden y tres que sí: la página se
        # recorta sobre el conjunto ya filtrado, no sobre las filas de SQL.
        ruta = _bd(
            tmp_path,
            [
                {
                    "codigo": "000000000001",
                    "ocupacion": "Albañil",
                    "fecha_inicio": "30/11/2026",
                },
                {
                    "codigo": "000000000002",
                    "ocupacion": "Albañil",
                    "fecha_inicio": "29/11/2026",
                },
                {
                    "codigo": "000000000003",
                    "ocupacion": "Técnico A",
                    "fecha_inicio": "03/11/2026",
                },
                {
                    "codigo": "000000000004",
                    "ocupacion": "Técnico B",
                    "fecha_inicio": "02/11/2026",
                },
                {
                    "codigo": "000000000005",
                    "ocupacion": "Técnico C",
                    "fecha_inicio": "01/11/2026",
                },
            ],
        )

        resultado = _repositorio(ruta).consultar(
            {"texto": "tecnico"}, offset=1, tamano_pagina=1
        )

        assert resultado.total == 3
        assert [oferta.codigo for oferta in resultado.items] == ["000000000004"]


# ---------------------------------------------------------------------------
# Pruebas: rango de fechas y fecha vacía (REQ-005, ALT-004, SUP-004)
# ---------------------------------------------------------------------------

class TestFechas:
    """Rango inclusive y ofertas sin fecha válida al final y fuera del rango."""

    def test_rango_de_fechas_inclusive(self, tmp_path: Path) -> None:
        ruta = _bd(
            tmp_path,
            [
                {"codigo": "000000000001", "fecha_inicio": "01/11/2026"},
                {"codigo": "000000000002", "fecha_inicio": "15/11/2026"},
                {"codigo": "000000000003", "fecha_inicio": "30/11/2026"},
            ],
        )

        resultado = _repositorio(ruta).consultar(
            {"fecha_desde": "10/11/2026", "fecha_hasta": "20/11/2026"}
        )

        assert [oferta.codigo for oferta in resultado.items] == ["000000000002"]
        assert resultado.total == 1

    def test_fecha_vacia_al_final_y_fuera_del_rango(self, tmp_path: Path) -> None:
        ruta = _bd(
            tmp_path,
            [
                {"codigo": "000000000001", "fecha_inicio": "15/11/2026"},
                {"codigo": "000000000002", "fecha_inicio": "20/11/2026"},
                {"codigo": "000000000003", "fecha_inicio": ""},
            ],
        )
        repositorio = _repositorio(ruta)

        sin_rango = repositorio.consultar({})
        con_rango = repositorio.consultar(
            {"fecha_desde": "10/11/2026", "fecha_hasta": "20/11/2026"}
        )

        assert [oferta.codigo for oferta in sin_rango.items] == [
            "000000000002",
            "000000000001",
            "000000000003",
        ]
        assert [oferta.codigo for oferta in con_rango.items] == [
            "000000000002",
            "000000000001",
        ]


# ---------------------------------------------------------------------------
# Pruebas: campos purgados (ALT-006, REQ-008)
# ---------------------------------------------------------------------------

class TestCamposPurgados:
    """Una oferta purgada se devuelve con texto y contacto vacíos."""

    def test_campos_vacios_no_coinciden_ni_rompen_la_oferta(
        self, tmp_path: Path
    ) -> None:
        ruta = _bd(
            tmp_path,
            [
                {
                    "codigo": "000000000001",
                    "texto_libre": "",
                    "contacto": "",
                }
            ],
        )
        repositorio = _repositorio(ruta)

        sin_filtro = repositorio.consultar({})
        con_texto = repositorio.consultar({"texto": "python"})

        assert len(sin_filtro.items) == 1
        assert sin_filtro.items[0].texto_libre == ""
        assert sin_filtro.items[0].contacto == ""
        assert sin_filtro.items[0].ocupacion == "Programador"
        assert con_texto.items == []
        assert con_texto.total == 0


# ---------------------------------------------------------------------------
# Pruebas: visibilidad por estado (REQ-006, SUP-003)
# ---------------------------------------------------------------------------

class TestVisibilidad:
    """``vigente`` por defecto, ``cerrada`` solo si se pide, ``sin_ficha`` nunca."""

    def test_por_defecto_solo_vigente(self, tmp_path: Path) -> None:
        ruta = _bd(
            tmp_path,
            [
                {"codigo": "000000000001", "estado": "vigente"},
                {"codigo": "000000000002", "estado": "cerrada"},
                {"codigo": "000000000003", "estado": "sin_ficha"},
            ],
        )

        resultado = _repositorio(ruta).consultar({})

        assert [oferta.codigo for oferta in resultado.items] == ["000000000001"]

    def test_incluir_cerradas_anade_cerrada_sin_sin_ficha(self, tmp_path: Path) -> None:
        ruta = _bd(
            tmp_path,
            [
                {"codigo": "000000000001", "estado": "vigente"},
                {"codigo": "000000000002", "estado": "cerrada"},
                {"codigo": "000000000003", "estado": "sin_ficha"},
            ],
        )

        resultado = _repositorio(ruta).consultar({"incluir_cerradas": True})

        assert {oferta.codigo for oferta in resultado.items} == {
            "000000000001",
            "000000000002",
        }
        assert resultado.filtros_aplicados == {"incluir_cerradas": True}


# ---------------------------------------------------------------------------
# Pruebas: forma del resultado (REQ-008)
# ---------------------------------------------------------------------------

class TestResultado:
    """La oferta lleva los once campos y el resultado sus metadatos."""

    def test_oferta_con_los_once_campos(self, tmp_path: Path) -> None:
        ruta = _bd(
            tmp_path,
            [
                {
                    "codigo": "061234567890",
                    "ocupacion": "Programador",
                    "municipio": "Santander",
                    "provincia": "Cantabria",
                    "sector": "",
                    "fecha_inicio": "15/11/2026",
                    "fecha_fin": "30/11/2026",
                    "estado": "vigente",
                    "contacto": "rrhh@test.com",
                    "texto_libre": "Buscamos programador Python",
                }
            ],
        )

        resultado = _repositorio(ruta).consultar({})

        assert isinstance(resultado, ResultadoListado)
        assert isinstance(resultado.items[0], OfertaListado)
        oferta = resultado.items[0]
        assert oferta.comunidad == "Cantabria"
        assert oferta.codigo == "061234567890"
        assert oferta.ocupacion == "Programador"
        assert oferta.municipio == "Santander"
        assert oferta.provincia == "Cantabria"
        assert oferta.sector == ""
        assert oferta.fecha_inicio_difusion == "15/11/2026"
        assert oferta.fecha_fin_difusion == "30/11/2026"
        assert oferta.estado == "vigente"
        assert oferta.contacto == "rrhh@test.com"
        assert oferta.texto_libre == "Buscamos programador Python"

    def test_pagina_y_filtros_aplicados_en_los_metadatos(self, tmp_path: Path) -> None:
        ruta = _bd(
            tmp_path,
            [{"codigo": f"{numero:012d}"} for numero in range(1, 6)],
        )

        resultado = _repositorio(ruta).consultar(
            {"fecha_desde": "10/11/2026", "sector": "  "},
            offset=4,
            tamano_pagina=20,
        )

        assert resultado.pagina == 1
        assert resultado.tamano_pagina == 20
        assert resultado.filtros_aplicados == {"fecha_desde": "10/11/2026"}


# ---------------------------------------------------------------------------
# Pruebas: solo lectura (REQ-010)
# ---------------------------------------------------------------------------

class TestSoloLectura:
    """Las consultas no cambian ni la marca de modificación ni las filas."""

    def test_marca_de_modificacion_y_filas_no_cambian(self, tmp_path: Path) -> None:
        ruta = _bd(
            tmp_path,
            [{"codigo": f"{numero:012d}"} for numero in range(1, 4)],
        )
        conexion = sqlite3.connect(ruta)
        try:
            filas_antes = conexion.execute(
                "SELECT COUNT(*) FROM ofertas"
            ).fetchone()[0]
        finally:
            conexion.close()
        mtime_antes = os.stat(ruta).st_mtime_ns
        repositorio = _repositorio(ruta)

        repositorio.consultar({})
        repositorio.consultar({"texto": "programador"})
        repositorio.consultar(
            {"fecha_desde": "01/11/2026", "fecha_hasta": "30/11/2026"},
            offset=1,
            tamano_pagina=1,
        )

        conexion = sqlite3.connect(ruta)
        try:
            filas_despues = conexion.execute(
                "SELECT COUNT(*) FROM ofertas"
            ).fetchone()[0]
        finally:
            conexion.close()

        assert os.stat(ruta).st_mtime_ns == mtime_antes
        assert filas_despues == filas_antes
