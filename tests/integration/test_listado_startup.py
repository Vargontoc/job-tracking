"""Pruebas de integración del arranque del listado en la aplicación (TASK-010).

Montan la aplicación real con ``TestClient`` y un entorno temporal (config de
prueba y SQLite en ``tmp_path``) para comprobar que el router del listado queda
registrado con sus dos rutas, que su estado compartido está en ``app_state``,
que no solapa rutas con los routers de los sprints 02–05, que una configuración
malformada registra el error y deja la feature fuera sin abortar el arranque, y
que la integración no altera ``data/job_emcan.db`` ni escribe en ``data/pdfs``
ni modifica los paquetes de los sprints anteriores.

Los hilos reales de las tareas de fondo no ejecutan trabajo: el planificador del
buscador no arranca, la ingesta, la purga, el histórico y la integridad tienen
sus métodos de ejecución sustituidos por dobles, de modo que no hay red real ni
escrituras en ``data/``.
"""

import hashlib
import importlib
import logging
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from source.api.buscador.scheduler import Scheduler
from source.api.historico.task import TareaHistorico
from source.api.integridad.task import AccionArranque, TareaIntegridad
from source.api.persistencia.ingestion import TareaIngesta
from source.api.persistencia.purge import TareaPurga

#: SQLite real de api-persistencia: el arranque no debe tocarlo (REQ-010).
RUTA_BD_REAL = Path("data/job_emcan.db")

#: Filtros que debe anunciar ``GET /listado/filtros`` (DEC-005).
_FILTROS_ESPERADOS = [
    "texto",
    "sector",
    "municipio",
    "fecha_desde",
    "fecha_hasta",
    "incluir_cerradas",
]

#: Paquetes de los sprints 02–05 que la feature no debe modificar (SUP-005).
_DIRECTORIOS_PROTEGIDOS = (
    "source/api/buscador",
    "source/api/persistencia",
    "source/api/historico",
    "source/api/integridad",
)
_FICHEROS_PROTEGIDOS = (
    "source/api/parser.py",
    "source/api/downloader.py",
    "source/api/assembler.py",
)


# ---------------------------------------------------------------------------
# Entorno temporal
# ---------------------------------------------------------------------------


@dataclass
class Entorno:
    """Rutas del entorno de prueba dentro de ``tmp_path``."""

    tmp_path: Path
    ruta_bd: str
    ruta_bd_historico: str
    pdfs_dir: Path
    seen_codes_path: str
    config_persistencia_path: Path
    config_historico_path: Path
    config_integridad_path: Path
    config_listado_path: Path


def _crear_entorno(tmp_path: Path) -> Entorno:
    """Crea configuraciones y datos temporales para el arranque de la app."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    pdfs_dir = data_dir / "pdfs"

    ruta_bd = str(data_dir / "persistencia.db")
    ruta_bd_historico = str(data_dir / "historico.db")

    seen_codes_path = data_dir / "seen_codes.json"
    seen_codes_path.write_text("[]", encoding="utf-8")

    config_persistencia = config_dir / "persistencia.yaml"
    config_persistencia.write_text(
        "base_de_datos:\n"
        f"  ruta: {ruta_bd}\n"
        "buscador:\n"
        "  url_base: http://localhost:19999\n"
        "ingesta:\n"
        "  cadencia_segundos: 3600\n"
        "purga:\n"
        "  dias_retencion: 7\n"
        "  frecuencia_segundos: 86400\n",
        encoding="utf-8",
    )

    config_historico = config_dir / "historico.yaml"
    config_historico.write_text(
        "zona_horaria: Europe/Madrid\n"
        "hora_ejecucion: 2\n"
        "ausencias_consecutivas: 2\n"
        "umbral_caida_pct: 30\n"
        "recuento_minimo: 70\n"
        "rutas:\n"
        f"  sqlite_historico: {ruta_bd_historico}\n"
        f"  sqlite_persistencia: {ruta_bd}\n"
        "buscador:\n"
        "  url_base: http://localhost:19999\n"
        "persistencia:\n"
        "  url_base: http://localhost:19999\n"
        "pdf:\n"
        "  comunidad: Cantabria\n"
        "  identificador: cantabria\n",
        encoding="utf-8",
    )

    config_integridad = config_dir / "integridad.yaml"
    config_integridad.write_text(
        "zona_horaria: Europe/Madrid\n"
        "hora_ejecucion: 2\n"
        "margen_catchup: 60\n"
        "dias_retencion: 30\n"
        "tolerancia_absoluta: 1\n"
        "tolerancia_relativa_pct: 5\n"
        "umbral_cordura: 70\n"
        "rutas:\n"
        f"  base_pdfs: {pdfs_dir}\n"
        "buscador:\n"
        "  url_base: http://localhost:19999\n"
        "comunidades:\n"
        "  - identificador: cantabria\n"
        "    url_pdf: http://localhost:19999/cantabria.pdf\n",
        encoding="utf-8",
    )

    # El listado lee el mismo SQLite de persistencia en modo solo lectura.
    # Sin comillas: la ruta de Windows conserva sus separadores como literal.
    config_listado = config_dir / "listado.yaml"
    config_listado.write_text(
        f"ruta_bd: {ruta_bd}\n"
        "tamano_pagina_por_defecto: 20\n"
        "tamano_pagina_maximo: 100\n",
        encoding="utf-8",
    )

    return Entorno(
        tmp_path=tmp_path,
        ruta_bd=ruta_bd,
        ruta_bd_historico=ruta_bd_historico,
        pdfs_dir=pdfs_dir,
        seen_codes_path=str(seen_codes_path),
        config_persistencia_path=config_persistencia,
        config_historico_path=config_historico,
        config_integridad_path=config_integridad,
        config_listado_path=config_listado,
    )


def _parchear(monkeypatch, entorno: Entorno) -> None:
    """Aísla las tareas de fondo y apunta la configuración a ``tmp_path``."""
    from source.api.buscador.models import ConfigBuscador

    config_buscador = ConfigBuscador(
        ruta_seen_codes=entorno.seen_codes_path,
    )
    monkeypatch.setattr(
        "source.api.buscador.config.cargar_configuracion",
        lambda: config_buscador,
    )

    monkeypatch.setattr(
        "source.api.persistencia.config.DEFAULT_CONFIG_PATH",
        Path(entorno.config_persistencia_path),
    )
    monkeypatch.setattr(
        "source.api.historico.config.DEFAULT_CONFIG_PATH",
        Path(entorno.config_historico_path),
    )
    monkeypatch.setattr(
        "source.api.integridad.config.DEFAULT_CONFIG_PATH",
        Path(entorno.config_integridad_path),
    )
    monkeypatch.setattr(
        "source.api.listado.config.DEFAULT_CONFIG_PATH",
        Path(entorno.config_listado_path),
    )

    # Evitar que el planificador del buscador arranque un hilo real.
    monkeypatch.setattr(Scheduler, "iniciar", lambda self: None)

    # Los hilos de las tareas existentes siguen vivos, pero no ejecutan trabajo
    # real: ni peticiones HTTP ni escrituras en sus bases de datos.
    monkeypatch.setattr(TareaIngesta, "_ejecutar_ciclo", lambda self: None)
    monkeypatch.setattr(
        TareaPurga, "_ejecutar_purga_si_posible", lambda self: None
    )
    monkeypatch.setattr(
        TareaHistorico, "ejecutar_cierre_diario", lambda self: None
    )

    # Evitar que la tarea del histórico espere horas en su hilo.
    monkeypatch.setattr(
        TareaHistorico,
        "_esperar_hora_configurada",
        lambda self: self._evento_parada.wait(timeout=0.05),
    )

    # La tarea de integridad espera su hora y no ejecuta trabajo real: así no
    # se descarga ningún PDF ni se consulta el buscador.
    monkeypatch.setattr(
        TareaIntegridad,
        "_decidir_arranque",
        lambda self, ahora, hay_meta_hoy: AccionArranque.ESPERAR_NORMAL,
    )
    monkeypatch.setattr(
        TareaIntegridad, "_ejecutar_dia", lambda self: None
    )


@pytest.fixture
def app_lista(tmp_path, monkeypatch):
    """Devuelve (client, main_mod, entorno) con la aplicación arrancada."""
    entorno = _crear_entorno(tmp_path)
    _parchear(monkeypatch, entorno)
    import source.api.main as main_mod

    main_mod = importlib.reload(main_mod)
    with TestClient(main_mod.app) as client:
        yield client, main_mod, entorno


# ---------------------------------------------------------------------------
# Arranque: router y estado del listado
# ---------------------------------------------------------------------------


class TestArranque:
    """El listado queda integrado en el ciclo de vida (REQ-001)."""

    def test_rutas_del_listado_responden(self, app_lista):
        """``GET /listado`` y ``GET /listado/filtros`` no devuelven 404."""
        client, main_mod, entorno = app_lista

        listado = client.get("/listado")
        assert listado.status_code == 200
        assert listado.status_code != 404
        cuerpo = listado.json()
        assert cuerpo["items"] == []
        assert cuerpo["total"] == 0

        filtros = client.get("/listado/filtros")
        assert filtros.status_code == 200
        assert filtros.status_code != 404
        assert [f["nombre"] for f in filtros.json()["filtros"]] == (
            _FILTROS_ESPERADOS
        )

    def test_estado_del_listado_en_app_state(self, app_lista):
        """La configuración, el adaptador y el repositorio están en app_state."""
        client, main_mod, entorno = app_lista

        config = main_mod.app_state.get("config_listado")
        assert config is not None
        assert config.ruta_bd == entorno.ruta_bd
        assert config.tamano_pagina_por_defecto == 20
        assert config.tamano_pagina_maximo == 100
        assert main_mod.app_state.get("adaptador_listado") is not None
        assert main_mod.app_state.get("repositorio_listado") is not None

    def test_router_del_listado_registrado(self, app_lista):
        """El router del listado existe con su prefijo."""
        client, main_mod, entorno = app_lista

        assert hasattr(main_mod, "listado_router")
        assert main_mod.listado_router.prefix == "/listado"


# ---------------------------------------------------------------------------
# No solape de rutas
# ---------------------------------------------------------------------------


class TestRutasSinSolape:
    """El listado no comparte rutas con los routers de los sprints 02–05."""

    def test_rutas_del_listado_no_solapan(self, app_lista):
        """Ninguna ruta (método, camino) coincide con otra de la API."""
        client, main_mod, entorno = app_lista

        def _rutas(router) -> set[tuple[str, str]]:
            # En algunas versiones de FastAPI ``routes`` incluye objetos
            # internos sin ``path``: se ignoran.
            pares: set[tuple[str, str]] = set()
            for ruta in router.routes:
                camino = getattr(ruta, "path", None)
                if camino is None:
                    continue
                for metodo in getattr(ruta, "methods", set()):
                    pares.add((camino, metodo))
            return pares

        listado = _rutas(main_mod.listado_router)
        for router in (
            main_mod.buscador_router,
            main_mod.persistencia_router,
            main_mod.historico_router,
            main_mod.integridad_router,
        ):
            assert listado.isdisjoint(_rutas(router))

    def test_app_no_duplica_rutas(self, app_lista):
        """La aplicación no registra dos veces la misma ruta y método."""
        client, main_mod, entorno = app_lista

        # ``app.routes`` puede incluir objetos internos de FastAPI sin ``path``
        # (``_IncludedRouter``): solo se comparan las rutas reales.
        pares = []
        for ruta in main_mod.app.routes:
            camino = getattr(ruta, "path", None)
            if camino is None:
                continue
            pares.append(
                (camino, tuple(sorted(getattr(ruta, "methods", set()))))
            )
        assert len(pares) == len(set(pares))


# ---------------------------------------------------------------------------
# Configuración malformada
# ---------------------------------------------------------------------------


class TestConfiguracionFallida:
    """Una configuración inválida deja el listado fuera sin abortar la app."""

    def test_config_malformada_registra_error_y_no_bloquea(
        self, tmp_path, monkeypatch, caplog
    ):
        """Un YAML malformado se registra y el resto de la API arranca."""
        entorno = _crear_entorno(tmp_path)
        _parchear(monkeypatch, entorno)
        rota = tmp_path / "listado_roto.yaml"
        rota.write_text("ruta_bd: [data/job_emcan.db\n", encoding="utf-8")
        monkeypatch.setattr(
            "source.api.listado.config.DEFAULT_CONFIG_PATH", rota
        )

        import source.api.main as main_mod

        main_mod = importlib.reload(main_mod)
        with caplog.at_level(logging.ERROR):
            with TestClient(main_mod.app) as client:
                assert client.get("/health").status_code == 200
                assert main_mod.app_state.get("config_listado") is None
                assert (
                    main_mod.app_state.get("repositorio_listado") is None
                )
                # La feature fuera de servicio responde 503, no aborta.
                assert client.get("/listado").status_code == 503
                # Los filtros son estáticos y siguen disponibles.
                assert client.get("/listado/filtros").status_code == 200
                # El resto de tareas arranca igual.
                assert (
                    main_mod.app_state.get("tarea_integridad") is not None
                )

        assert any(
            "listado" in registro.getMessage().lower()
            for registro in caplog.records
        )

    def test_config_ausente_usa_valores_por_defecto(
        self, tmp_path, monkeypatch
    ):
        """Sin fichero de configuración se aplican los valores por defecto."""
        entorno = _crear_entorno(tmp_path)
        _parchear(monkeypatch, entorno)
        monkeypatch.setattr(
            "source.api.listado.config.DEFAULT_CONFIG_PATH",
            tmp_path / "no_existe.yaml",
        )

        import source.api.main as main_mod

        main_mod = importlib.reload(main_mod)
        with TestClient(main_mod.app) as client:
            assert client.get("/health").status_code == 200
            config = main_mod.app_state.get("config_listado")
            assert config is not None
            assert config.ruta_bd == "data/job_emcan.db"
            assert config.tamano_pagina_por_defecto == 20
            assert config.tamano_pagina_maximo == 100


# ---------------------------------------------------------------------------
# No regresión y aislamiento
# ---------------------------------------------------------------------------


class TestNoRegresion:
    """Los endpoints existentes responden y no hay escrituras no deseadas."""

    def test_endpoints_de_los_sprints_02_05_responden(self, app_lista):
        """Buscador, persistencia, histórico e integridad siguen igual."""
        client, main_mod, entorno = app_lista

        assert client.get("/buscador/status").status_code == 200
        assert (
            client.get("/persistencia/ofertas/vigentes").status_code == 200
        )
        assert (
            client.get(
                "/historico/resumen",
                params={"desde": "2026-11-01", "hasta": "2026-11-02"},
            ).status_code
            == 200
        )
        assert client.get("/integridad/ultimo").status_code == 200
        assert client.get("/integridad/pdfs").status_code == 200

    def test_no_escribe_en_data_pdfs(self, app_lista):
        """El arranque no crea PDFs ni bases en ``data/pdfs``."""
        client, main_mod, entorno = app_lista

        if entorno.pdfs_dir.exists():
            ficheros = [ruta for ruta in entorno.pdfs_dir.rglob("*") if ruta.is_file()]
            assert ficheros == []

    def test_no_modifica_paquetes_previos(self, tmp_path, monkeypatch):
        """La integración no altera los paquetes de los sprints 01–05."""
        antes = _huella_codigo()

        entorno = _crear_entorno(tmp_path)
        _parchear(monkeypatch, entorno)

        import source.api.main as main_mod

        main_mod = importlib.reload(main_mod)
        with TestClient(main_mod.app) as client:
            assert client.get("/health").status_code == 200
            assert client.get("/listado/filtros").status_code == 200

        assert _huella_codigo() == antes

    def test_bd_real_conserva_contenido_y_mtime(self, tmp_path, monkeypatch):
        """El arranque no altera ``data/job_emcan.db`` (REQ-010, SUP-005)."""
        antes = _huella(RUTA_BD_REAL)

        entorno = _crear_entorno(tmp_path)
        _parchear(monkeypatch, entorno)

        import source.api.main as main_mod

        main_mod = importlib.reload(main_mod)
        with TestClient(main_mod.app) as client:
            assert client.get("/health").status_code == 200
            assert client.get("/listado/filtros").status_code == 200

        assert _huella(RUTA_BD_REAL) == antes


# ---------------------------------------------------------------------------
# Huellas
# ---------------------------------------------------------------------------


def _huella(ruta: Path):
    """Tamaño, SHA-256 y mtime del fichero, o ``None`` si no existe."""
    if not ruta.exists():
        return None
    contenido = ruta.read_bytes()
    return (
        len(contenido),
        hashlib.sha256(contenido).hexdigest(),
        ruta.stat().st_mtime_ns,
    )


def _huella_codigo() -> dict[str, tuple[int, int]]:
    """Tamaño y mtime de los ``.py`` de los paquetes protegidos."""
    huellas: dict[str, tuple[int, int]] = {}
    for directorio in _DIRECTORIOS_PROTEGIDOS:
        for ruta in Path(directorio).rglob("*.py"):
            if "__pycache__" in ruta.parts:
                continue
            info = ruta.stat()
            huellas[str(ruta)] = (info.st_size, info.st_mtime_ns)
    for fichero in _FICHEROS_PROTEGIDOS:
        ruta = Path(fichero)
        if ruta.exists():
            info = ruta.stat()
            huellas[str(ruta)] = (info.st_size, info.st_mtime_ns)
    return huellas
