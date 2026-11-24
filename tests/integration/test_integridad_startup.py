"""Pruebas de integración del arranque y apagado de la integridad (TASK-014).

Montan la aplicación real con ``TestClient`` y un entorno temporal (config de
prueba y ruta base de PDFs en ``tmp_path``) y comprueban que la tarea de la
integridad convive con el planificador del buscador, la ingesta, la purga y la
tarea del histórico, que su configuración ausente o malformada no bloquea el
resto de la API, que el apagado la cancela antes que el planificador y que la
integración no crea ningún SQLite nuevo ni altera ``data/job_emcan.db``.

Los hilos reales de las tareas no llegan a ejecutar trabajo: la tarea de
integridad se fuerza a esperar la hora programada y su ``_ejecutar_dia`` se
sustituye por un doble que solo anota llamadas, de modo que no se descarga
ningún PDF ni se consulta el buscador real.
"""

import hashlib
import importlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from source.api.buscador.scheduler import Scheduler
from source.api.config import ErrorConfiguracion as ErrorConfiguracionPDF
from source.api.historico.task import TareaHistorico
from source.api.integridad.task import AccionArranque, TareaIntegridad
from source.api.persistencia.ingestion import TareaIngesta
from source.api.persistencia.purge import TareaPurga

RUTA_BD_REAL = Path("data/job_emcan.db")
ESPERA_MAXIMA = 5.0


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

    return Entorno(
        tmp_path=tmp_path,
        ruta_bd=ruta_bd,
        ruta_bd_historico=ruta_bd_historico,
        pdfs_dir=pdfs_dir,
        seen_codes_path=str(seen_codes_path),
        config_persistencia_path=config_persistencia,
        config_historico_path=config_historico,
        config_integridad_path=config_integridad,
    )


def _parchear(monkeypatch, entorno: Entorno) -> list[int]:
    """Aplica los parches comunes y devuelve el registro de ejecuciones."""
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
    ejecuciones: list[int] = []
    monkeypatch.setattr(
        TareaIntegridad,
        "_ejecutar_dia",
        lambda self: ejecuciones.append(1) or None,
    )
    return ejecuciones


def _arrancar(monkeypatch, entorno: Entorno):
    """Parchea, recarga ``main`` y devuelve (módulo, registro de ejecuciones)."""
    ejecuciones = _parchear(monkeypatch, entorno)
    import source.api.main as main_mod

    return importlib.reload(main_mod), ejecuciones


def _esperar(condicion, timeout: float = ESPERA_MAXIMA) -> bool:
    """Espera a que se cumpla una condición, sondeando en intervalos cortos."""
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        if condicion():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def app_lista(tmp_path, monkeypatch):
    """Devuelve (client, main_mod, entorno, ejecuciones) con la app arrancada."""
    entorno = _crear_entorno(tmp_path)
    ejecuciones = _parchear(monkeypatch, entorno)
    import source.api.main as main_mod

    main_mod = importlib.reload(main_mod)
    with TestClient(main_mod.app) as client:
        yield client, main_mod, entorno, ejecuciones


# ---------------------------------------------------------------------------
# Arranque: todas las tareas activas
# ---------------------------------------------------------------------------


class TestArranque:
    """Comprueba que la integridad convive con las demás tareas (DEC-006)."""

    def test_tareas_activas_tras_arrancar(self, app_lista):
        """Integridad, ingesta, purga, histórico y scheduler quedan activos."""
        client, main_mod, entorno, ejecuciones = app_lista

        tarea = main_mod.app_state.get("tarea_integridad")
        assert tarea is not None
        assert _esperar(
            lambda: tarea._hilo is not None and tarea._hilo.is_alive()
        )

        assert main_mod.app_state.get("tarea_ingesta") is not None
        assert main_mod.app_state.get("tarea_purga") is not None
        assert main_mod.app_state.get("tarea_historico") is not None
        assert main_mod.app_state.get("scheduler") is not None

        # Nada se ha ejecutado todavía: la tarea espera su hora.
        assert ejecuciones == []

    def test_dependencias_de_integridad_en_app_state(self, app_lista):
        """Configuración, almacén e índice de la integridad están en app_state."""
        client, main_mod, entorno, ejecuciones = app_lista

        config = main_mod.app_state.get("config_integridad")
        assert config is not None
        assert config.zona_horaria == "Europe/Madrid"
        assert config.hora_ejecucion == 2
        assert main_mod.app_state.get("almacen_integridad") is not None
        assert main_mod.app_state.get("indice_ejecuciones") is not None

    def test_router_integridad_registrado(self, app_lista):
        """El router de la integridad existe con su prefijo."""
        client, main_mod, entorno, ejecuciones = app_lista

        assert hasattr(main_mod, "integridad_router")
        assert main_mod.integridad_router.prefix == "/integridad"

    def test_health_responde(self, app_lista):
        """El healthcheck sigue respondiendo."""
        client, main_mod, entorno, ejecuciones = app_lista

        respuesta = client.get("/health")
        assert respuesta.status_code == 200
        assert respuesta.json()["status"] == "healthy"


# ---------------------------------------------------------------------------
# Configuración ausente o malformada
# ---------------------------------------------------------------------------


class TestConfiguracionFallida:
    """Una configuración inválida deja la feature fuera sin abortar la app."""

    def test_config_malformada_registra_error_y_no_bloquea(
        self, tmp_path, monkeypatch, caplog
    ):
        """Un YAML malformado se registra y el resto de la API arranca."""
        entorno = _crear_entorno(tmp_path)
        _parchear(monkeypatch, entorno)
        rota = tmp_path / "integridad_rota.yaml"
        rota.write_text(
            "zona_horaria: [Europe/Madrid\n", encoding="utf-8"
        )
        monkeypatch.setattr(
            "source.api.integridad.config.DEFAULT_CONFIG_PATH", rota
        )

        import source.api.main as main_mod

        main_mod = importlib.reload(main_mod)
        with caplog.at_level(logging.ERROR):
            with TestClient(main_mod.app) as client:
                assert client.get("/health").status_code == 200
                assert main_mod.app_state.get("tarea_integridad") is None

        assert any(
            "integridad" in registro.getMessage().lower()
            for registro in caplog.records
        )

    def test_config_ausente_sin_comunidades_no_bloquea(
        self, tmp_path, monkeypatch, caplog
    ):
        """Sin fichero ni comunidades de reserva, la feature queda fuera."""
        entorno = _crear_entorno(tmp_path)
        _parchear(monkeypatch, entorno)
        monkeypatch.setattr(
            "source.api.integridad.config.DEFAULT_CONFIG_PATH",
            tmp_path / "no_existe.yaml",
        )

        def _sin_comunidades():
            raise ErrorConfiguracionPDF(
                "config/comunidades.yaml ausente para la prueba"
            )

        monkeypatch.setattr(
            "source.api.integridad.config.cargar_comunidades", _sin_comunidades
        )

        import source.api.main as main_mod

        main_mod = importlib.reload(main_mod)
        with caplog.at_level(logging.ERROR):
            with TestClient(main_mod.app) as client:
                assert client.get("/health").status_code == 200
                assert main_mod.app_state.get("tarea_integridad") is None

        assert any(
            "integridad" in registro.getMessage().lower()
            for registro in caplog.records
        )


# ---------------------------------------------------------------------------
# Apagado ordenado
# ---------------------------------------------------------------------------


class TestApagado:
    """La tarea de integridad se cancela primero, sin ejecuciones en curso."""

    def test_tarea_integridad_cancelada_al_apagar(self, tmp_path, monkeypatch):
        """Al salir del contexto, el hilo queda parado y no ejecutó nada."""
        entorno = _crear_entorno(tmp_path)
        main_mod, ejecuciones = _arrancar(monkeypatch, entorno)

        with TestClient(main_mod.app):
            tarea = main_mod.app_state.get("tarea_integridad")
            assert tarea is not None
            hilo = tarea._hilo
            assert hilo is not None and hilo.is_alive()

        assert tarea._evento_parada.is_set()
        assert _esperar(lambda: not hilo.is_alive())
        assert ejecuciones == []

    def test_cancelacion_integridad_antes_de_scheduler(
        self, tmp_path, monkeypatch
    ):
        """La integridad se detiene antes que el planificador del buscador."""
        orden: list[str] = []

        entorno = _crear_entorno(tmp_path)
        _parchear(monkeypatch, entorno)

        detener_integridad = TareaIntegridad.detener
        detener_scheduler = Scheduler.detener

        def _detener_integridad(self):
            orden.append("integridad")
            detener_integridad(self)

        def _detener_scheduler(self):
            orden.append("scheduler")
            detener_scheduler(self)

        monkeypatch.setattr(
            TareaIntegridad, "detener", _detener_integridad
        )
        monkeypatch.setattr(Scheduler, "detener", _detener_scheduler)

        main_mod, _ = _arrancar(monkeypatch, entorno)
        with TestClient(main_mod.app):
            pass

        assert "integridad" in orden
        assert "scheduler" in orden
        assert orden.index("integridad") < orden.index("scheduler")

    def test_cancelacion_integridad_antes_de_historico(
        self, tmp_path, monkeypatch
    ):
        """La integridad se detiene antes que la tarea del histórico."""
        orden: list[str] = []

        entorno = _crear_entorno(tmp_path)
        _parchear(monkeypatch, entorno)

        detener_integridad = TareaIntegridad.detener
        detener_historico = TareaHistorico.detener

        def _detener_integridad(self):
            orden.append("integridad")
            detener_integridad(self)

        def _detener_historico(self):
            orden.append("historico")
            detener_historico(self)

        monkeypatch.setattr(
            TareaIntegridad, "detener", _detener_integridad
        )
        monkeypatch.setattr(TareaHistorico, "detener", _detener_historico)

        main_mod, _ = _arrancar(monkeypatch, entorno)
        with TestClient(main_mod.app):
            pass

        assert "integridad" in orden
        assert "historico" in orden
        assert orden.index("integridad") < orden.index("historico")


# ---------------------------------------------------------------------------
# No regresión sobre los módulos existentes
# ---------------------------------------------------------------------------


class TestNoRegresion:
    """Los endpoints existentes responden igual y no se crean SQLite nuevos."""

    def test_endpoints_existentes_responden(self, app_lista):
        """Buscador, persistencia e histórico siguen respondiendo."""
        client, main_mod, entorno, ejecuciones = app_lista

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

    def test_no_crea_sqlite_de_la_integridad(self, app_lista):
        """La ruta base de la integridad no contiene ningún fichero SQLite."""
        client, main_mod, entorno, ejecuciones = app_lista

        assert main_mod.app_state.get("tarea_integridad") is not None
        ficheros = (
            list(entorno.pdfs_dir.rglob("*.db"))
            + list(entorno.pdfs_dir.rglob("*.sqlite"))
            + list(entorno.pdfs_dir.rglob("*.sqlite3"))
            if entorno.pdfs_dir.exists()
            else []
        )
        assert ficheros == []

    def test_bd_de_persistencia_conserva_contenido_y_mtime(
        self, tmp_path, monkeypatch
    ):
        """El arranque no altera ``data/job_emcan.db`` (SUP-003)."""
        antes = _huella(RUTA_BD_REAL)

        entorno = _crear_entorno(tmp_path)
        _parchear(monkeypatch, entorno)
        main_mod, _ = _arrancar(monkeypatch, entorno)
        with TestClient(main_mod.app) as client:
            assert client.get("/health").status_code == 200

        assert _huella(RUTA_BD_REAL) == antes


def _huella(ruta: Path):
    """Tamaño, mtime y SHA-256 del fichero, o ``None`` si no existe."""
    if not ruta.exists():
        return None
    contenido = ruta.read_bytes()
    return (
        len(contenido),
        hashlib.sha256(contenido).hexdigest(),
        ruta.stat().st_mtime_ns,
    )
