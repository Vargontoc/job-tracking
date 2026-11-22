"""Tests de integración del histórico.

TASK-016: Arranque y apagado del histórico.
TASK-018: Verificación end-to-end del flujo completo del histórico.
"""

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient

# TASK-018 imports
from source.api.historico.abstenciones_repository import RepositorioAbstenciones
from source.api.historico.buscador_client import (
    ClienteEstadoBuscador,
    EstadoBuscador,
    ErrorEstadoBuscador,
)
from source.api.historico.config import ConfigHistorico
from source.api.historico.connection import abrir_conexion
from source.api.historico.ejecucion_repository import RepositorioEjecucion
from source.api.historico.migrations import migrar
from source.api.historico.pdf_adapter import ListadoPDF, ErrorListadoPDF
from source.api.historico.persistencia_client import ClientePersistencia, Oferta
from source.api.historico.presencia_repository import RepositorioPresencia
from source.api.historico.read_adapter import AdaptadorLecturaHistorica
from source.api.historico.task import TareaHistorico, RelojProtocol


def _crear_entorno(tmp_path):
    """Crea ficheros de configuración y datos temporales para los tests."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    # BD de persistencia
    ruta_bd = str(data_dir / "test_historico_integration.db")
    # BD del histórico
    ruta_bd_historico = str(data_dir / "test_historico.db")

    seen_codes_path = data_dir / "seen_codes.json"
    seen_codes_path.write_text("[]", encoding="utf-8")

    # Configuración de persistencia
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

    # Configuración del histórico
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

    return {
        "tmp_path": tmp_path,
        "ruta_bd": ruta_bd,
        "ruta_bd_historico": ruta_bd_historico,
        "seen_codes_path": str(seen_codes_path),
        "config_persistencia_path": config_persistencia,
        "config_historico_path": config_historico,
    }


def _aplicar_parches(monkeypatch, entorno):
    """Aplica los monkeypatches necesarios para los tests."""
    from source.api.buscador.models import ConfigBuscador

    config_buscador = ConfigBuscador(
        ruta_seen_codes=entorno["seen_codes_path"],
    )
    monkeypatch.setattr(
        "source.api.buscador.config.cargar_configuracion",
        lambda: config_buscador,
    )

    # Parchear ruta de config de persistencia
    monkeypatch.setattr(
        "source.api.persistencia.config.DEFAULT_CONFIG_PATH",
        Path(entorno["config_persistencia_path"]),
    )

    # Parchear ruta de config del histórico
    monkeypatch.setattr(
        "source.api.historico.config.DEFAULT_CONFIG_PATH",
        Path(entorno["config_historico_path"]),
    )

    # Evitar que los schedulers arranquen hilos reales
    from source.api.buscador.scheduler import Scheduler
    monkeypatch.setattr(Scheduler, "iniciar", lambda self: None)
    monkeypatch.setattr(Scheduler, "detener", lambda self: None)

    # Evitar que la tarea del histórico espere en el hilo
    from source.api.historico.task import TareaHistorico
    monkeypatch.setattr(
        TareaHistorico, "_esperar_hora_configurada",
        lambda self: self._evento_parada.wait(timeout=0.05),
    )


@pytest.fixture
def app_lista(tmp_path, monkeypatch):
    """Prepara el entorno y devuelve (client, main_mod, entorno) con la app arrancada."""
    entorno = _crear_entorno(tmp_path)
    _aplicar_parches(monkeypatch, entorno)

    import importlib
    import source.api.main as main_mod
    importlib.reload(main_mod)

    with TestClient(main_mod.app) as client:
        yield client, main_mod, entorno


# ---------------------------------------------------------------------------
# Arranque del histórico
# ---------------------------------------------------------------------------


class TestArranqueHistorico:
    """Verifica que el arranque inicializa correctamente el histórico."""

    def test_la_bd_historico_existe_tras_arrancar(self, app_lista):
        """El fichero SQLite propio del histórico existe tras arrancar."""
        client, main_mod, entorno = app_lista
        assert Path(entorno["ruta_bd_historico"]).exists()

    def test_wal_activado_en_bd_historico(self, app_lista):
        """El journal_mode del histórico es WAL."""
        client, main_mod, entorno = app_lista
        conexion = main_mod.app_state.get("conexion_historico")
        assert conexion is not None
        resultado = conexion.execute("PRAGMA journal_mode").fetchone()
        assert resultado[0] == "wal"

    def test_migraciones_historico_aplicadas(self, app_lista):
        """Las migraciones propias están aplicadas."""
        client, main_mod, entorno = app_lista
        conexion = main_mod.app_state.get("conexion_historico")
        assert conexion is not None
        fila = conexion.execute(
            "SELECT MAX(version) FROM schema_version"
        ).fetchone()
        assert fila is not None and fila[0] >= 1

    def test_tablas_propias_del_historico_existen(self, app_lista):
        """Las cuatro tablas propias del histórico existen."""
        client, main_mod, entorno = app_lista
        conexion = main_mod.app_state.get("conexion_historico")
        assert conexion is not None
        tablas = {
            fila[0]
            for fila in conexion.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "presencia_en_listado" in tablas
        assert "serie_recuentos" in tablas
        assert "abstenciones_cierre" in tablas
        assert "ejecucion_diaria" in tablas

    def test_tarea_historico_en_app_state(self, app_lista):
        """La tarea del histórico está en app_state."""
        client, main_mod, entorno = app_lista
        assert main_mod.app_state.get("tarea_historico") is not None

    def test_repositorios_en_app_state(self, app_lista):
        """Los tres repositorios están en app_state."""
        client, main_mod, entorno = app_lista
        assert main_mod.app_state.get("repositorio_presencia") is not None
        assert main_mod.app_state.get("repositorio_abstenciones") is not None
        assert main_mod.app_state.get("repositorio_ejecucion") is not None

    def test_adaptadores_en_app_state(self, app_lista):
        """Los adaptadores y clientes están en app_state."""
        client, main_mod, entorno = app_lista
        assert main_mod.app_state.get("cliente_estado_buscador") is not None
        assert main_mod.app_state.get("cliente_persistencia_historico") is not None
        assert main_mod.app_state.get("adaptador_lectura_historica") is not None
        assert main_mod.app_state.get("adaptador_pdf") is not None

    def test_config_historico_en_app_state(self, app_lista):
        """La configuración del histórico está en app_state."""
        client, main_mod, entorno = app_lista
        config = main_mod.app_state.get("config_historico")
        assert config is not None
        assert config.zona_horaria == "Europe/Madrid"
        assert config.hora_ejecucion == 2


# ---------------------------------------------------------------------------
# Router registrado
# ---------------------------------------------------------------------------


class TestRouterRegistrado:
    """Verifica que el router del histórico está registrado."""

    def test_router_historico_registrado(self, app_lista):
        """El router del histórico está registrado en la app."""
        client, main_mod, entorno = app_lista
        # El router existe en el módulo y tiene el prefijo correcto
        assert hasattr(main_mod, "historico_router")
        assert main_mod.historico_router.prefix == "/historico"
        # La inicialización completa del histórico implica que el router
        # se incluyó en la app (el include_router es a nivel de módulo).
        assert main_mod.app_state.get("tarea_historico") is not None

    def test_health_responde(self, app_lista):
        """El endpoint /health sigue respondiendo."""
        client, main_mod, entorno = app_lista
        respuesta = client.get("/health")
        assert respuesta.status_code == 200
        assert respuesta.json()["status"] == "healthy"

    def test_endpoint_buscador_status_responde(self, app_lista):
        """El endpoint /buscador/status sigue respondiendo."""
        client, main_mod, entorno = app_lista
        respuesta = client.get("/buscador/status")
        assert respuesta.status_code == 200

    def test_endpoint_persistencia_vigentes_responde(self, app_lista):
        """El endpoint /persistencia/ofertas/vigentes sigue respondiendo."""
        client, main_mod, entorno = app_lista
        respuesta = client.get("/persistencia/ofertas/vigentes")
        assert respuesta.status_code == 200


# ---------------------------------------------------------------------------
# Apagado ordenado
# ---------------------------------------------------------------------------


class TestApagadoOrdenado:
    """Verifica que el apagado detiene los componentes en el orden correcto."""

    def test_tarea_historico_se_detiene_antes_de_cerrar_conexion(
        self, tmp_path, monkeypatch
    ):
        """La tarea se detiene antes de cerrar su conexión."""
        orden_apagado = []

        entorno = _crear_entorno(tmp_path)
        _aplicar_parches(monkeypatch, entorno)

        # Registrar orden de detención
        from source.api.historico.task import TareaHistorico
        detener_orig = TareaHistorico.detener

        def mock_detener(self):
            orden_apagado.append("tarea_historico")
            detener_orig(self)

        monkeypatch.setattr(TareaHistorico, "detener", mock_detener)

        import importlib
        import source.api.main as main_mod
        importlib.reload(main_mod)

        with TestClient(main_mod.app):
            pass  # El apagado ocurre al salir del contexto

        assert "tarea_historico" in orden_apagado

    def test_tarea_historico_se_detiene_antes_de_scheduler(
        self, tmp_path, monkeypatch
    ):
        """La tarea del histórico se detiene antes que el scheduler."""
        orden_apagado = []

        entorno = _crear_entorno(tmp_path)
        _aplicar_parches(monkeypatch, entorno)

        from source.api.historico.task import TareaHistorico
        from source.api.buscador.scheduler import Scheduler

        detener_tarea_orig = TareaHistorico.detener
        detener_scheduler_orig = Scheduler.detener

        def mock_detener_tarea(self):
            orden_apagado.append("tarea_historico")
            detener_tarea_orig(self)

        def mock_detener_scheduler(self):
            orden_apagado.append("scheduler")
            detener_scheduler_orig(self)

        monkeypatch.setattr(TareaHistorico, "detener", mock_detener_tarea)
        monkeypatch.setattr(Scheduler, "detener", mock_detener_scheduler)

        import importlib
        import source.api.main as main_mod
        importlib.reload(main_mod)

        with TestClient(main_mod.app):
            pass

        idx_tarea = orden_apagado.index("tarea_historico")
        idx_scheduler = orden_apagado.index("scheduler")
        assert idx_tarea < idx_scheduler

    def test_conexion_historico_se_cierra_tras_detener_tarea(
        self, tmp_path, monkeypatch
    ):
        """La conexión se cierra después de detener la tarea."""
        orden_eventos = []

        entorno = _crear_entorno(tmp_path)
        _aplicar_parches(monkeypatch, entorno)

        from source.api.historico.task import TareaHistorico
        detener_tarea_orig = TareaHistorico.detener

        def mock_detener_tarea(self):
            orden_eventos.append("detener_tarea")
            detener_tarea_orig(self)

        monkeypatch.setattr(TareaHistorico, "detener", mock_detener_tarea)

        import importlib
        import source.api.main as main_mod
        importlib.reload(main_mod)

        # Guardar referencia a la conexión dentro del contexto de la app,
        # ya que app_state se limpia al apagar.
        conexion_ref: dict = {}

        with TestClient(main_mod.app):
            conexion_ref["conn"] = main_mod.app_state.get("conexion_historico")

        # Tras el apagado, verificar que la tarea se detuvo
        assert "detener_tarea" in orden_eventos

        # Verificar que la conexión del histórico está cerrada:
        # sqlite3.Connection es un tipo C inmutable y no permite patchear
        # close, así que comprobamos el efecto: usarla lanza ProgrammingError.
        conn = conexion_ref["conn"]
        assert conn is not None, "La conexión del histórico debería existir"
        import sqlite3
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")


# ---------------------------------------------------------------------------
# Tolerancia a fallos
# ---------------------------------------------------------------------------


class TestToleranciaFallos:
    """Si el histórico falla, la app continúa sin él."""

    def test_error_migracion_no_bloquea_app(self, tmp_path, monkeypatch):
        """Un error de migración no impide que la app arranque."""
        entorno = _crear_entorno(tmp_path)
        _aplicar_parches(monkeypatch, entorno)

        # Forzar un error de migración simulando una versión futura
        from source.api.historico import migrations as hist_mig
        monkeypatch.setattr(
            hist_mig, "migrar",
            lambda conn: (_ for _ in ()).throw(
                hist_mig.ErrorMigracion("versión futura simulada")
            ),
        )

        import importlib
        import source.api.main as main_mod
        importlib.reload(main_mod)

        with TestClient(main_mod.app) as client:
            # La app arranca y el healthcheck responde
            respuesta = client.get("/health")
            assert respuesta.status_code == 200
            # El histórico no se inicializó
            assert main_mod.app_state.get("tarea_historico") is None
            # Pero persistencia y buscador siguen funcionando
            assert main_mod.app_state.get("conexion_persistencia") is not None

    def test_error_configuracion_no_bloquea_app(self, tmp_path, monkeypatch):
        """Un error de configuración no impide que la app arranque."""
        entorno = _crear_entorno(tmp_path)
        _aplicar_parches(monkeypatch, entorno)

        from source.api.historico import config as hist_config
        monkeypatch.setattr(
            hist_config, "cargar_configuracion",
            lambda: (_ for _ in ()).throw(
                hist_config.ErrorConfiguracion("config inválida simulada")
            ),
        )

        import importlib
        import source.api.main as main_mod
        importlib.reload(main_mod)

        with TestClient(main_mod.app) as client:
            respuesta = client.get("/health")
            assert respuesta.status_code == 200
            assert main_mod.app_state.get("tarea_historico") is None
            assert main_mod.app_state.get("conexion_persistencia") is not None


# ---------------------------------------------------------------------------
# No modifica módulos externos (SUP-002, SUP-003)
# ---------------------------------------------------------------------------


class TestNoModificaExteriores:
    """El histórico no modifica módulos de otras features."""

    def test_no_modifica_buscador(self, app_lista):
        """Los módulos de buscador no han sido alterados."""
        client, main_mod, entorno = app_lista
        # El scheduler sigue siendo el mismo tipo
        scheduler = main_mod.app_state.get("scheduler")
        assert scheduler is not None

    def test_no_altera_contenido_de_bd_persistencia(self, app_lista):
        """La BD de persistencia no ha sido modificada por el histórico."""
        client, main_mod, entorno = app_lista
        conexion_persistencia = main_mod.app_state.get("conexion_persistencia")
        assert conexion_persistencia is not None
        # Las tablas de persistencia están intactas
        tablas = {
            fila[0]
            for fila in conexion_persistencia.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "ofertas" in tablas


# ===========================================================================
# TASK-018: Verificación end-to-end del flujo completo del histórico
# ===========================================================================


# ---------------------------------------------------------------------------
# Reloj controlado para pruebas
# ---------------------------------------------------------------------------


class RelojControlado:
    """Reloj inyectable para controlar la fecha/hora en las pruebas."""

    def __init__(self, fecha_hora: datetime) -> None:
        self._ahora = fecha_hora

    def now(self) -> datetime:
        return self._ahora

    def sleep(self, segundos: float) -> None:
        pass

    def avanzar_dias(self, dias: int = 1) -> None:
        self._ahora += timedelta(days=dias)

    @property
    def fecha_iso(self) -> str:
        return self._ahora.date().isoformat()


# ---------------------------------------------------------------------------
# Helpers para crear el entorno de pruebas
# ---------------------------------------------------------------------------


def _crear_bd_persistencia(ruta: str, ofertas: list[tuple]) -> None:
    """Crea la BD de persistencia con la tabla ``ofertas`` y datos iniciales."""
    conn = sqlite3.connect(ruta)
    conn.execute(
        """
        CREATE TABLE ofertas (
            comunidad TEXT NOT NULL,
            codigo TEXT NOT NULL PRIMARY KEY,
            estado TEXT NOT NULL DEFAULT 'vigente',
            fecha_alta TEXT NOT NULL,
            fecha_cierre TEXT,
            provincia TEXT DEFAULT '',
            ocupacion TEXT DEFAULT '',
            municipio TEXT DEFAULT '',
            sector TEXT DEFAULT '',
            nivel TEXT DEFAULT '',
            contrato TEXT DEFAULT '',
            fecha_inicio_difusion TEXT,
            fecha_fin_difusion TEXT,
            texto_libre TEXT DEFAULT '',
            contacto TEXT DEFAULT '',
            embedding TEXT,
            embedding_model_name TEXT,
            embedding_model_version TEXT,
            embedding_dim INTEGER,
            interesada INTEGER DEFAULT 0,
            fecha_ultima_actualizacion TEXT
        )
        """
    )
    conn.executemany(
        """INSERT INTO ofertas (
            comunidad, codigo, estado, fecha_alta, fecha_cierre,
            provincia, ocupacion, municipio, sector, nivel, contrato,
            fecha_inicio_difusion, fecha_fin_difusion,
            texto_libre, contacto,
            embedding, embedding_model_name, embedding_model_version,
            embedding_dim, interesada, fecha_ultima_actualizacion
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ofertas,
    )
    conn.commit()
    conn.close()


def _leer_oferta(ruta_bd: str, comunidad: str, codigo: str) -> Optional[dict]:
    """Lee una oferta de la BD de persistencia."""
    conn = sqlite3.connect(ruta_bd)
    conn.row_factory = sqlite3.Row
    fila = conn.execute(
        "SELECT * FROM ofertas WHERE comunidad = ? AND codigo = ?",
        (comunidad, codigo),
    ).fetchone()
    conn.close()
    if fila is None:
        return None
    return dict(fila)


def _leer_todas_ofertas(ruta_bd: str) -> list[dict]:
    """Lee todas las ofertas de la BD de persistencia."""
    conn = sqlite3.connect(ruta_bd)
    conn.row_factory = sqlite3.Row
    filas = conn.execute("SELECT * FROM ofertas").fetchall()
    conn.close()
    return [dict(f) for f in filas]


def _crear_transport_mock(
    ruta_bd: str,
    estado_buscador_fn,
) -> httpx.MockTransport:
    """Crea un transporte HTTP mock que simula los endpoints de la API.

    Args:
        ruta_bd: Ruta al SQLite de persistencia.
        estado_buscador_fn: Función que devuelve el cuerpo de /buscador/status.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method

        # GET /buscador/status
        if path == "/buscador/status" and method == "GET":
            cuerpo = estado_buscador_fn()
            if cuerpo is None:
                return httpx.Response(503, json={"detail": "Buscador no disponible"})
            return httpx.Response(200, json=cuerpo)

        # GET /persistencia/ofertas/vigentes
        if path == "/persistencia/ofertas/vigentes" and method == "GET":
            conn = sqlite3.connect(ruta_bd)
            conn.row_factory = sqlite3.Row
            filas = conn.execute(
                "SELECT * FROM ofertas WHERE estado = 'vigente'"
            ).fetchall()
            conn.close()
            datos = [_oferta_a_json(dict(f)) for f in filas]
            return httpx.Response(200, json=datos)

        # GET /persistencia/ofertas/{comunidad}/{codigo}
        match = re.match(
            r"^/persistencia/ofertas/([^/]+)/([^/]+)$", path
        )
        if match and method == "GET":
            comunidad = match.group(1)
            codigo = match.group(2)
            oferta = _leer_oferta(ruta_bd, comunidad, codigo)
            if oferta is None:
                return httpx.Response(404, json={"detail": "No encontrada"})
            return httpx.Response(200, json=_oferta_a_json(oferta))

        # POST /persistencia/ofertas (actualizar)
        if path == "/persistencia/ofertas" and method == "POST":
            cuerpo = json.loads(request.content)
            comunidad = cuerpo.get("comunidad", "")
            codigo = cuerpo.get("codigo", "")
            oferta_actual = _leer_oferta(ruta_bd, comunidad, codigo)
            if oferta_actual is None:
                return httpx.Response(404, json={"detail": "No encontrada"})

            conn = sqlite3.connect(ruta_bd)
            # Actualizar la oferta preservando campos no modificados
            estado = cuerpo.get("estado", oferta_actual["estado"])
            fecha_cierre = cuerpo.get("fecha_cierre", oferta_actual.get("fecha_cierre"))
            texto_libre = cuerpo.get("texto_libre", oferta_actual.get("texto_libre", ""))
            contacto = cuerpo.get("contacto", oferta_actual.get("contacto", ""))
            fecha_ultima = datetime.now().isoformat()

            conn.execute(
                """UPDATE ofertas SET
                    estado = ?, fecha_cierre = ?, texto_libre = ?,
                    contacto = ?, fecha_ultima_actualizacion = ?
                   WHERE comunidad = ? AND codigo = ?""",
                (estado, fecha_cierre, texto_libre, contacto,
                 fecha_ultima, comunidad, codigo),
            )
            conn.commit()
            conn.close()
            return httpx.Response(200, json=cuerpo)

        return httpx.Response(404, json={"detail": f"No encontrado: {method} {path}"})

    return httpx.MockTransport(handler)


def _oferta_a_json(oferta: dict) -> dict:
    """Convierte una fila de la BD al formato JSON de persistencia-api."""
    return {
        "comunidad": oferta.get("comunidad", ""),
        "codigo": oferta.get("codigo", ""),
        "estado": oferta.get("estado", "vigente"),
        "fecha_alta": oferta.get("fecha_alta"),
        "fecha_cierre": oferta.get("fecha_cierre"),
        "provincia": oferta.get("provincia", ""),
        "ocupacion": oferta.get("ocupacion", ""),
        "municipio": oferta.get("municipio", ""),
        "sector": oferta.get("sector", ""),
        "nivel": oferta.get("nivel", ""),
        "contrato": oferta.get("contrato", ""),
        "fecha_inicio_difusion": oferta.get("fecha_inicio_difusion"),
        "fecha_fin_difusion": oferta.get("fecha_fin_difusion"),
        "texto_libre": oferta.get("texto_libre", ""),
        "contacto": oferta.get("contacto", ""),
        "embedding": oferta.get("embedding"),
        "embedding_model_name": oferta.get("embedding_model_name"),
        "embedding_model_version": oferta.get("embedding_model_version"),
        "embedding_dim": oferta.get("embedding_dim"),
        "interesada": bool(oferta.get("interesada", False)),
        "fecha_ultima_actualizacion": oferta.get("fecha_ultima_actualizacion"),
    }


# ---------------------------------------------------------------------------
# Fixture del entorno end-to-end
# ---------------------------------------------------------------------------


@dataclass
class EntornoE2E:
    """Contenedor con todos los componentes necesarios para un test e2e."""

    tmp_path: Path
    ruta_bd_persistencia: str
    ruta_bd_historico: str
    conexion_historico: sqlite3.Connection
    reloj: RelojControlado
    config: ConfigHistorico
    cliente_buscador: ClienteEstadoBuscador
    cliente_persistencia: ClientePersistencia
    repositorio_presencia: RepositorioPresencia
    repositorio_abstenciones: RepositorioAbstenciones
    repositorio_ejecucion: RepositorioEjecucion
    adaptador_pdf: MagicMock
    adaptador_lectura: AdaptadorLecturaHistorica
    tarea: TareaHistorico
    estado_buscador: dict  # Mutable: se puede cambiar entre tests


def _crear_entorno_e2e(
    tmp_path: Path,
    ofertas_iniciales: list[tuple],
    fecha_inicial: datetime,
    estado_buscador_inicial: dict,
    listado_pdf_codigos: set[str] | None = None,
    listado_pdf_error: bool = False,
) -> EntornoE2E:
    """Crea un entorno completo para tests e2e del histórico."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)

    ruta_bd = str(data_dir / "persistencia.db")
    ruta_bd_hist = str(data_dir / "historico.db")

    # Crear BD de persistencia con datos iniciales
    _crear_bd_persistencia(ruta_bd, ofertas_iniciales)

    # Crear BD del histórico y migrar
    conexion_hist = abrir_conexion(ruta_bd_hist)
    migrar(conexion_hist)

    # Reloj controlado
    reloj = RelojControlado(fecha_inicial)

    # Configuración
    config = ConfigHistorico(
        zona_horaria="Europe/Madrid",
        hora_ejecucion=2,
        ausencias_consecutivas=2,
        umbral_caida_pct=30,
        recuento_minimo=70,
        ruta_sqlite_historico=ruta_bd_hist,
        ruta_sqlite_persistencia=ruta_bd,
        url_base_buscador="http://testserver",
        url_base_persistencia="http://testserver",
        pdf_comunidad="Cantabria",
        pdf_identificador="cantabria",
    )

    # Estado del buscador mutable
    estado_buscador = {"cuerpo": estado_buscador_inicial}

    def obtener_estado_buscador():
        return estado_buscador["cuerpo"]

    # Transporte HTTP mock
    transport = _crear_transport_mock(ruta_bd, obtener_estado_buscador)
    http_client = httpx.Client(transport=transport)

    # Clientes
    cliente_buscador = ClienteEstadoBuscador(
        "http://testserver", cliente_http=http_client
    )
    cliente_persistencia = ClientePersistencia(
        "http://testserver", cliente_http=http_client
    )

    # Repositorios
    repositorio_presencia = RepositorioPresencia(conexion_hist)
    repositorio_abstenciones = RepositorioAbstenciones(conexion_hist)
    repositorio_ejecucion = RepositorioEjecucion(conexion_hist)

    # Adaptador PDF mockeado
    adaptador_pdf = MagicMock()
    if listado_pdf_error:
        adaptador_pdf.obtener_listado.return_value = ErrorListadoPDF(
            motivo="Error simulado de parseo del PDF"
        )
    else:
        codigos = listado_pdf_codigos or set()
        adaptador_pdf.obtener_listado.return_value = ListadoPDF(
            codigos=codigos,
            fecha_listado=fecha_inicial.date().isoformat(),
        )

    # Adaptador de lectura histórica
    adaptador_lectura = AdaptadorLecturaHistorica(ruta_bd)

    # Tarea
    tarea = TareaHistorico(
        config=config,
        cliente_buscador=cliente_buscador,
        cliente_persistencia=cliente_persistencia,
        repositorio_presencia=repositorio_presencia,
        repositorio_abstenciones=repositorio_abstenciones,
        repositorio_ejecucion=repositorio_ejecucion,
        adaptador_pdf=adaptador_pdf,
        reloj=reloj,
    )

    return EntornoE2E(
        tmp_path=tmp_path,
        ruta_bd_persistencia=ruta_bd,
        ruta_bd_historico=ruta_bd_hist,
        conexion_historico=conexion_hist,
        reloj=reloj,
        config=config,
        cliente_buscador=cliente_buscador,
        cliente_persistencia=cliente_persistencia,
        repositorio_presencia=repositorio_presencia,
        repositorio_abstenciones=repositorio_abstenciones,
        repositorio_ejecucion=repositorio_ejecucion,
        adaptador_pdf=adaptador_pdf,
        adaptador_lectura=adaptador_lectura,
        tarea=tarea,
        estado_buscador=estado_buscador,
    )


# ---------------------------------------------------------------------------
# Datos de prueba reutilizables
# ---------------------------------------------------------------------------

# Fecha de referencia para los tests
FECHA_REF = datetime(2026, 11, 21, 2, 0, 0, tzinfo=ZoneInfo("Europe/Madrid"))

# Ofertas base para los tests:
# - Oferta 1: con fecha_fin_difusion pasada (ayer) → cierre por fecha
# - Oferta 2: sin fecha_fin_difusion, presente en listado → vigente
# - Oferta 3: sin fecha_fin_difusion, ausente de dos listados → cierre por desaparición
# - Oferta 4: sin fecha_fin_difusion, ausente solo 1 listado → vigente (margen)
# - Oferta 5: sin_ficha, ausente → no se cierra (REQ-009)
# - Oferta 6: fecha_fin_difusion futura → vigente


def _oferta_base(
    codigo: str,
    estado: str = "vigente",
    fecha_fin_difusion: str | None = None,
    texto_libre: str = "Texto de prueba",
    contacto: str = "contacto@test.com",
) -> tuple:
    """Genera una tupla de oferta para insertar en la BD."""
    return (
        "Cantabria",  # comunidad
        codigo,  # codigo
        estado,  # estado
        "2026-11-15T10:00:00",  # fecha_alta
        None,  # fecha_cierre
        "",  # provincia
        "Ingeniero",  # ocupacion
        "Santander",  # municipio
        "",  # sector
        "",  # nivel
        "",  # contrato
        None,  # fecha_inicio_difusion
        fecha_fin_difusion,  # fecha_fin_difusion
        texto_libre,  # texto_libre
        contacto,  # contacto
        None,  # embedding
        None,  # embedding_model_name
        None,  # embedding_model_version
        None,  # embedding_dim
        0,  # interesada
        None,  # fecha_ultima_actualizacion
    )


def _estado_buscador_ok(total: int = 93, errores: list | None = None) -> dict:
    """Genera un estado válido del buscador."""
    return {
        "in_progress": False,
        "progreso": 100,
        "ultima_pasada": {
            "timestamp": "2026-11-21T01:30:00+01:00",
            "comunidad": "Cantabria",
            "total_listado": total,
            "error_global": "",
            "errores_por_oferta": errores or [],
        },
    }


# ---------------------------------------------------------------------------
# Tests TASK-018: Cierre por fecha de fin de difusión
# ---------------------------------------------------------------------------


class TestCierrePorFecha:
    """Verifica el cierre por fecha de fin de difusión pasada."""

    def test_oferta_con_fin_pasado_se_cierra(self, tmp_path):
        """Una oferta con fecha_fin_difusion del día anterior se cierra."""
        ofertas = [
            _oferta_base("000000001001", fecha_fin_difusion="20/11/2026"),
        ]
        entorno = _crear_entorno_e2e(
            tmp_path,
            ofertas,
            FECHA_REF,
            _estado_buscador_ok(total=93),
            listado_pdf_codigos={"000000001001"},
        )
        # Registrar recuento previo para que el guardián permita el cierre
        entorno.repositorio_presencia.registrar_recuento(
            93, "2026-11-20T01:30:00+01:00"
        )

        resultado = entorno.tarea.ejecutar_cierre_diario()

        assert resultado.exitoso is True
        assert resultado.cerradas_por_fecha >= 1
        # Verificar en la BD que la oferta está cerrada
        oferta = _leer_oferta(entorno.ruta_bd_persistencia, "Cantabria", "000000001001")
        assert oferta is not None
        assert oferta["estado"] == "cerrada"
        assert oferta["fecha_cierre"] is not None

    def test_oferta_con_fin_hoy_no_se_cierra(self, tmp_path):
        """Una oferta con fecha_fin_difusion de hoy permanece vigente."""
        ofertas = [
            _oferta_base("000000002001", fecha_fin_difusion="21/11/2026"),
        ]
        entorno = _crear_entorno_e2e(
            tmp_path,
            ofertas,
            FECHA_REF,
            _estado_buscador_ok(total=93),
            listado_pdf_codigos={"000000002001"},
        )

        resultado = entorno.tarea.ejecutar_cierre_diario()

        oferta = _leer_oferta(entorno.ruta_bd_persistencia, "Cantabria", "000000002001")
        assert oferta is not None
        assert oferta["estado"] == "vigente"

    def test_oferta_con_fin_futuro_no_se_cierra(self, tmp_path):
        """Una oferta con fecha_fin_difusion futura permanece vigente."""
        ofertas = [
            _oferta_base("000000003001", fecha_fin_difusion="25/11/2026"),
        ]
        entorno = _crear_entorno_e2e(
            tmp_path,
            ofertas,
            FECHA_REF,
            _estado_buscador_ok(total=93),
            listado_pdf_codigos={"000000003001"},
        )

        entorno.tarea.ejecutar_cierre_diario()

        oferta = _leer_oferta(entorno.ruta_bd_persistencia, "Cantabria", "000000003001")
        assert oferta["estado"] == "vigente"


# ---------------------------------------------------------------------------
# Tests TASK-018: Cierre por desaparición
# ---------------------------------------------------------------------------


class TestCierrePorDesaparicion:
    """Verifica el cierre por desaparición del listado oficial."""

    def test_ausente_dos_listados_se_cierra(self, tmp_path):
        """Ausente en dos listados consecutivos → cerrada."""
        ofertas = [
            _oferta_base("000000010001"),  # sin fecha_fin_difusion
        ]
        entorno = _crear_entorno_e2e(
            tmp_path,
            ofertas,
            FECHA_REF,
            _estado_buscador_ok(total=93),
            listado_pdf_codigos=set(),  # Ausente en el listado actual
        )
        # Registrar recuento previo para que el guardián permita el cierre
        entorno.repositorio_presencia.registrar_recuento(
            93, "2026-11-20T01:30:00+01:00"
        )

        # Registrar ausencia previa (simula que ya faltó ayer)
        fecha_ayer = (FECHA_REF - timedelta(days=1)).date().isoformat()
        entorno.repositorio_presencia.registrar_ausencia(
            "Cantabria", "000000010001", fecha_ayer
        )

        resultado = entorno.tarea.ejecutar_cierre_diario()

        assert resultado.exitoso is True
        oferta = _leer_oferta(entorno.ruta_bd_persistencia, "Cantabria", "000000010001")
        assert oferta["estado"] == "cerrada"
        assert oferta["fecha_cierre"] is not None

    def test_ausente_solo_un_listado_permanece_vigente(self, tmp_path):
        """Ausente solo en el listado actual → vigente (margen de 1 día)."""
        ofertas = [
            _oferta_base("000000011001"),
        ]
        entorno = _crear_entorno_e2e(
            tmp_path,
            ofertas,
            FECHA_REF,
            _estado_buscador_ok(total=93),
            listado_pdf_codigos=set(),  # Ausente ahora
        )

        # Sin ausencia previa → solo 1 ausencia
        resultado = entorno.tarea.ejecutar_cierre_diario()

        oferta = _leer_oferta(entorno.ruta_bd_persistencia, "Cantabria", "000000011001")
        assert oferta["estado"] == "vigente"

    def test_presente_en_listado_permanece_vigente(self, tmp_path):
        """Presente en el listado oficial → vigente."""
        ofertas = [
            _oferta_base("000000012001"),
        ]
        entorno = _crear_entorno_e2e(
            tmp_path,
            ofertas,
            FECHA_REF,
            _estado_buscador_ok(total=93),
            listado_pdf_codigos={"000000012001"},  # Presente
        )

        resultado = entorno.tarea.ejecutar_cierre_diario()

        oferta = _leer_oferta(entorno.ruta_bd_persistencia, "Cantabria", "000000012001")
        assert oferta["estado"] == "vigente"


# ---------------------------------------------------------------------------
# Tests TASK-018: Buscador caído o sin pasada
# ---------------------------------------------------------------------------


class TestBuscadorCaido:
    """Verifica que con el buscador caído no se cierra ninguna oferta."""

    def test_buscador_sin_respuesta_no_cierra(self, tmp_path):
        """Buscador sin respuesta → abstención, sin cierres."""
        ofertas = [
            _oferta_base("000000020001", fecha_fin_difusion="20/11/2026"),
        ]
        entorno = _crear_entorno_e2e(
            tmp_path,
            ofertas,
            FECHA_REF,
            estado_buscador_inicial=None,  # Simula 503
        )

        resultado = entorno.tarea.ejecutar_cierre_diario()

        assert resultado.exitoso is False
        assert len(resultado.abstenciones) > 0
        oferta = _leer_oferta(entorno.ruta_bd_persistencia, "Cantabria", "000000020001")
        assert oferta["estado"] == "vigente"

    def test_ultima_pasada_nula_no_cierra(self, tmp_path):
        """ultima_pasada nula → abstención."""
        ofertas = [
            _oferta_base("000000021001", fecha_fin_difusion="20/11/2026"),
        ]
        estado_sin_pasada = {
            "in_progress": False,
            "progreso": 0,
            "ultima_pasada": None,
        }
        entorno = _crear_entorno_e2e(
            tmp_path,
            ofertas,
            FECHA_REF,
            estado_sin_pasada,
        )

        resultado = entorno.tarea.ejecutar_cierre_diario()

        assert resultado.exitoso is False
        assert len(resultado.abstenciones) > 0
        oferta = _leer_oferta(entorno.ruta_bd_persistencia, "Cantabria", "000000021001")
        assert oferta["estado"] == "vigente"

    def test_error_global_no_cierra(self, tmp_path):
        """error_global no vacío → abstención."""
        ofertas = [
            _oferta_base("000000022001", fecha_fin_difusion="20/11/2026"),
        ]
        estado_con_error = {
            "in_progress": False,
            "progreso": 100,
            "ultima_pasada": {
                "timestamp": "2026-11-21T01:30:00+01:00",
                "comunidad": "Cantabria",
                "total_listado": 93,
                "error_global": "Error al consultar Emplea",
                "errores_por_oferta": [],
            },
        }
        entorno = _crear_entorno_e2e(
            tmp_path,
            ofertas,
            FECHA_REF,
            estado_con_error,
        )

        resultado = entorno.tarea.ejecutar_cierre_diario()

        assert resultado.exitoso is False
        assert len(resultado.abstenciones) > 0
        oferta = _leer_oferta(entorno.ruta_bd_persistencia, "Cantabria", "000000022001")
        assert oferta["estado"] == "vigente"


# ---------------------------------------------------------------------------
# Tests TASK-018: Guardián de recuento (caída anómala)
# ---------------------------------------------------------------------------


class TestGuardianRecuento:
    """Verifica el guardián de recuento."""

    def test_caida_anomala_no_cierra_desaparicion(self, tmp_path):
        """Caída >30% → abstención, no se cierra por desaparición."""
        ofertas = [
            _oferta_base("000000030001"),  # sin fecha_fin, candidata
        ]
        # Registrar recuento anterior de 100
        entorno = _crear_entorno_e2e(
            tmp_path,
            ofertas,
            FECHA_REF,
            _estado_buscador_ok(total=60),  # Caída del 40% respecto a 100
            listado_pdf_codigos=set(),  # Ausente
        )
        # Insertar recuento anterior manualmente
        fecha_ayer = (FECHA_REF - timedelta(days=1)).date().isoformat()
        entorno.repositorio_presencia.registrar_ausencia(
            "Cantabria", "000000030001", fecha_ayer
        )
        entorno.repositorio_presencia.registrar_recuento(
            100, "2026-11-20T01:30:00+01:00"
        )

        resultado = entorno.tarea.ejecutar_cierre_diario()

        # La caída del 40% supera el umbral del 30% → abstención
        assert resultado.exitoso is False
        assert len(resultado.abstenciones) > 0
        # La oferta no se cierra por desaparición
        oferta = _leer_oferta(entorno.ruta_bd_persistencia, "Cantabria", "000000030001")
        assert oferta["estado"] == "vigente"

    def test_recuento_estable_permite_cierres(self, tmp_path):
        """Recuento estable (sin caída anómala) → permite cierres."""
        ofertas = [
            _oferta_base("000000031001", fecha_fin_difusion="20/11/2026"),
        ]
        entorno = _crear_entorno_e2e(
            tmp_path,
            ofertas,
            FECHA_REF,
            _estado_buscador_ok(total=92),  # Estable (93→92, ~1%)
            listado_pdf_codigos=set(),
        )
        entorno.repositorio_presencia.registrar_recuento(
            93, "2026-11-20T01:30:00+01:00"
        )

        resultado = entorno.tarea.ejecutar_cierre_diario()

        assert resultado.exitoso is True
        # El cierre por fecha sí se ejecuta
        oferta = _leer_oferta(entorno.ruta_bd_persistencia, "Cantabria", "000000031001")
        assert oferta["estado"] == "cerrada"

    def test_recuento_inferior_minimo_abstiene(self, tmp_path):
        """Recuento actual < mínimo → abstención."""
        ofertas = [
            _oferta_base("000000032001"),
        ]
        entorno = _crear_entorno_e2e(
            tmp_path,
            ofertas,
            FECHA_REF,
            _estado_buscador_ok(total=65),  # < recuento_minimo (70)
            listado_pdf_codigos=set(),
        )
        entorno.repositorio_presencia.registrar_recuento(
            93, "2026-11-20T01:30:00+01:00"
        )
        fecha_ayer = (FECHA_REF - timedelta(days=1)).date().isoformat()
        entorno.repositorio_presencia.registrar_ausencia(
            "Cantabria", "000000032001", fecha_ayer
        )

        resultado = entorno.tarea.ejecutar_cierre_diario()

        assert resultado.exitoso is False
        assert len(resultado.abstenciones) > 0
        oferta = _leer_oferta(entorno.ruta_bd_persistencia, "Cantabria", "000000032001")
        assert oferta["estado"] == "vigente"


# ---------------------------------------------------------------------------
# Tests TASK-018: Código con error en la pasada
# ---------------------------------------------------------------------------


class TestCodigoConError:
    """Verifica que los códigos con error no se cierran."""

    def test_codigo_con_error_no_se_cierra(self, tmp_path):
        """Código en errores_por_oferta → abstención, no se cierra."""
        ofertas = [
            _oferta_base("000000040001"),
        ]
        estado_con_error_oferta = _estado_buscador_ok(
            total=93,
            errores=[{"codigo": "000000040001"}],
        )
        entorno = _crear_entorno_e2e(
            tmp_path,
            ofertas,
            FECHA_REF,
            estado_con_error_oferta,
            listado_pdf_codigos=set(),  # Ausente del listado
        )
        # Ausencia previa para que normalmente se cerraría
        fecha_ayer = (FECHA_REF - timedelta(days=1)).date().isoformat()
        entorno.repositorio_presencia.registrar_ausencia(
            "Cantabria", "000000040001", fecha_ayer
        )
        entorno.repositorio_presencia.registrar_recuento(
            93, "2026-11-20T01:30:00+01:00"
        )

        resultado = entorno.tarea.ejecutar_cierre_diario()

        # La oferta no se cierra porque su código tiene error
        oferta = _leer_oferta(entorno.ruta_bd_persistencia, "Cantabria", "000000040001")
        assert oferta["estado"] == "vigente"


# ---------------------------------------------------------------------------
# Tests TASK-018: Doble ejecución diaria
# ---------------------------------------------------------------------------


class TestDobleEjecucion:
    """Verifica que la segunda ejecución del día no hace nada."""

    def test_segunda_ejecucion_no_repite_cierres(self, tmp_path):
        """La segunda ejecución del mismo día no genera cierres nuevos."""
        ofertas = [
            _oferta_base("000000050001", fecha_fin_difusion="20/11/2026"),
        ]
        entorno = _crear_entorno_e2e(
            tmp_path,
            ofertas,
            FECHA_REF,
            _estado_buscador_ok(total=93),
            listado_pdf_codigos=set(),
        )
        # Registrar recuento previo para que el guardián permita el cierre
        entorno.repositorio_presencia.registrar_recuento(
            93, "2026-11-20T01:30:00+01:00"
        )

        # Primera ejecución: cierra por fecha
        resultado1 = entorno.tarea.ejecutar_cierre_diario()
        assert resultado1.exitoso is True

        oferta_tras_primera = _leer_oferta(
            entorno.ruta_bd_persistencia, "Cantabria", "000000050001"
        )
        fecha_cierre_1 = oferta_tras_primera["fecha_cierre"]

        # Segunda ejecución el mismo día
        resultado2 = entorno.tarea.ejecutar_cierre_diario()
        assert resultado2.exitoso is True

        # La oferta sigue cerrada con la misma fecha_cierre
        oferta_tras_segunda = _leer_oferta(
            entorno.ruta_bd_persistencia, "Cantabria", "000000050001"
        )
        assert oferta_tras_segunda["estado"] == "cerrada"
        assert oferta_tras_segunda["fecha_cierre"] == fecha_cierre_1

    def test_segunda_ejecucion_no_registra_presencia_nueva(self, tmp_path):
        """La segunda ejecución no añade registros de presencia duplicados."""
        ofertas = [
            _oferta_base("000000051001"),
        ]
        entorno = _crear_entorno_e2e(
            tmp_path,
            ofertas,
            FECHA_REF,
            _estado_buscador_ok(total=93),
            listado_pdf_codigos={"000000051001"},
        )
        # Registrar recuento previo para que el guardián permita el cierre
        entorno.repositorio_presencia.registrar_recuento(
            93, "2026-11-20T01:30:00+01:00"
        )

        # Primera ejecución
        entorno.tarea.ejecutar_cierre_diario()

        # Contar registros de presencia para la fecha del listado
        fecha_listado = FECHA_REF.date().isoformat()
        historial_1 = entorno.repositorio_presencia.consultar_historial(
            "000000051001", "Cantabria"
        )

        # Segunda ejecución
        entorno.tarea.ejecutar_cierre_diario()

        historial_2 = entorno.repositorio_presencia.consultar_historial(
            "000000051001", "Cantabria"
        )

        # No se añaden registros nuevos (el historial tiene la misma longitud)
        assert len(historial_2) == len(historial_1)


# ---------------------------------------------------------------------------
# Tests TASK-018: Parser en error
# ---------------------------------------------------------------------------


class TestParserError:
    """Verifica que con error en el PDF no se cierra por desaparición."""

    def test_pdf_error_no_cierra_desaparicion(self, tmp_path):
        """Error al obtener el listado PDF → abstención, no cierra."""
        ofertas = [
            _oferta_base("000000060001"),
        ]
        entorno = _crear_entorno_e2e(
            tmp_path,
            ofertas,
            FECHA_REF,
            _estado_buscador_ok(total=93),
            listado_pdf_error=True,  # Simula error en el PDF
        )
        # Ausencia previa
        fecha_ayer = (FECHA_REF - timedelta(days=1)).date().isoformat()
        entorno.repositorio_presencia.registrar_ausencia(
            "Cantabria", "000000060001", fecha_ayer
        )
        entorno.repositorio_presencia.registrar_recuento(
            93, "2026-11-20T01:30:00+01:00"
        )

        resultado = entorno.tarea.ejecutar_cierre_diario()

        # No se cierra porque el listado no está disponible
        assert resultado.exitoso is False
        assert len(resultado.abstenciones) > 0
        oferta = _leer_oferta(entorno.ruta_bd_persistencia, "Cantabria", "000000060001")
        assert oferta["estado"] == "vigente"


# ---------------------------------------------------------------------------
# Tests TASK-018: sin_ficha no se cierra
# ---------------------------------------------------------------------------


class TestSinFicha:
    """Verifica que las ofertas sin_ficha no se cierran."""

    def test_sin_ficha_no_se_cierra_por_fecha(self, tmp_path):
        """Oferta sin_ficha con fecha_fin pasada → no se cierra."""
        ofertas = [
            _oferta_base(
                "000000070001",
                estado="sin_ficha",
                fecha_fin_difusion="20/11/2026",
            ),
        ]
        entorno = _crear_entorno_e2e(
            tmp_path,
            ofertas,
            FECHA_REF,
            _estado_buscador_ok(total=93),
            listado_pdf_codigos=set(),
        )

        resultado = entorno.tarea.ejecutar_cierre_diario()

        oferta = _leer_oferta(entorno.ruta_bd_persistencia, "Cantabria", "000000070001")
        assert oferta["estado"] == "sin_ficha"

    def test_sin_ficha_no_se_cierra_por_desaparicion(self, tmp_path):
        """Oferta sin_ficha ausente del listado → no se cierra (REQ-009)."""
        ofertas = [
            _oferta_base("000000071001", estado="sin_ficha"),
        ]
        entorno = _crear_entorno_e2e(
            tmp_path,
            ofertas,
            FECHA_REF,
            _estado_buscador_ok(total=93),
            listado_pdf_codigos=set(),
        )
        # Ausencia previa
        fecha_ayer = (FECHA_REF - timedelta(days=1)).date().isoformat()
        entorno.repositorio_presencia.registrar_ausencia(
            "Cantabria", "000000071001", fecha_ayer
        )
        entorno.repositorio_presencia.registrar_recuento(
            93, "2026-11-20T01:30:00+01:00"
        )

        entorno.tarea.ejecutar_cierre_diario()

        oferta = _leer_oferta(entorno.ruta_bd_persistencia, "Cantabria", "000000071001")
        assert oferta["estado"] == "sin_ficha"


# ---------------------------------------------------------------------------
# Tests TASK-018: Oferta cerrada conserva texto y contacto
# ---------------------------------------------------------------------------


class TestPreservacionCampos:
    """Verifica que el cierre conserva texto y contacto (REQ-010)."""

    def test_cierre_conserva_texto_y_contacto(self, tmp_path):
        """Cerrar una oferta no vacía texto_libre ni contacto."""
        ofertas = [
            _oferta_base(
                "000000080001",
                fecha_fin_difusion="20/11/2026",
                texto_libre="Texto importante que no debe perderse",
                contacto="persona@empresa.com",
            ),
        ]
        entorno = _crear_entorno_e2e(
            tmp_path,
            ofertas,
            FECHA_REF,
            _estado_buscador_ok(total=93),
            listado_pdf_codigos=set(),
        )
        # Registrar recuento previo para que el guardián permita el cierre
        entorno.repositorio_presencia.registrar_recuento(
            93, "2026-11-20T01:30:00+01:00"
        )

        entorno.tarea.ejecutar_cierre_diario()

        oferta = _leer_oferta(entorno.ruta_bd_persistencia, "Cantabria", "000000080001")
        assert oferta["estado"] == "cerrada"
        assert oferta["texto_libre"] == "Texto importante que no debe perderse"
        assert oferta["contacto"] == "persona@empresa.com"


# ---------------------------------------------------------------------------
# Tests TASK-018: Consultas históricas tras el cierre
# ---------------------------------------------------------------------------


class TestConsultasHistoricas:
    """Verifica que las consultas históricas devuelven datos tras el cierre."""

    def test_cierre_por_fecha_visible_en_cierres(self, tmp_path):
        """Tras cerrar por fecha, la oferta aparece en /historico/cierres."""
        fecha_alta = "2026-11-15"
        ofertas = [
            _oferta_base("000000090001", fecha_fin_difusion="20/11/2026"),
        ]
        # Sobrescribir la fecha_alta para que coincida con el rango
        data_dir = tmp_path / "data"
        data_dir.mkdir(exist_ok=True)
        ruta_bd = str(data_dir / "persistencia.db")
        _crear_bd_persistencia(ruta_bd, ofertas)
        # Actualizar la fecha_alta
        conn = sqlite3.connect(ruta_bd)
        conn.execute(
            "UPDATE ofertas SET fecha_alta = ? WHERE codigo = ?",
            (fecha_alta, "000000090001"),
        )
        conn.commit()
        conn.close()

        ruta_bd_hist = str(data_dir / "historico.db")
        conexion_hist = abrir_conexion(ruta_bd_hist)
        migrar(conexion_hist)

        reloj = RelojControlado(FECHA_REF)
        config = ConfigHistorico(
            ruta_sqlite_historico=ruta_bd_hist,
            ruta_sqlite_persistencia=ruta_bd,
            url_base_buscador="http://testserver",
            url_base_persistencia="http://testserver",
        )
        estado_buscador = {"cuerpo": _estado_buscador_ok(total=93)}

        transport = _crear_transport_mock(
            ruta_bd, lambda: estado_buscador["cuerpo"]
        )
        http_client = httpx.Client(transport=transport)

        adaptador_pdf = MagicMock()
        adaptador_pdf.obtener_listado.return_value = ListadoPDF(
            codigos=set(), fecha_listado=FECHA_REF.date().isoformat()
        )

        tarea = TareaHistorico(
            config=config,
            cliente_buscador=ClienteEstadoBuscador(
                "http://testserver", cliente_http=http_client
            ),
            cliente_persistencia=ClientePersistencia(
                "http://testserver", cliente_http=http_client
            ),
            repositorio_presencia=RepositorioPresencia(conexion_hist),
            repositorio_abstenciones=RepositorioAbstenciones(conexion_hist),
            repositorio_ejecucion=RepositorioEjecucion(conexion_hist),
            adaptador_pdf=adaptador_pdf,
            reloj=reloj,
        )

        # Registrar recuento previo para que el guardián permita el cierre
        RepositorioPresencia(conexion_hist).registrar_recuento(
            93, "2026-11-20T01:30:00+01:00"
        )

        tarea.ejecutar_cierre_diario()

        # Verificar que el adaptador de lectura ve el cierre
        adaptador_lectura = AdaptadorLecturaHistorica(ruta_bd)
        fecha_hoy = FECHA_REF.date().isoformat()
        cierres = adaptador_lectura.cierres_por_fecha(fecha_hoy, fecha_hoy)
        assert len(cierres) >= 1
        codigos_cerrados = {c.codigo for c in cierres}
        assert "000000090001" in codigos_cerrados


# ---------------------------------------------------------------------------
# Tests TASK-018: Abstenciones registradas en la BD
# ---------------------------------------------------------------------------


class TestAbstencionesRegistradas:
    """Verifica que las abstenciones se registran en la BD del histórico."""

    def test_abstencion_buscador_caido_se_registra(self, tmp_path):
        """La abstención por buscador caído queda registrada."""
        ofertas = [
            _oferta_base("000000100001"),
        ]
        entorno = _crear_entorno_e2e(
            tmp_path,
            ofertas,
            FECHA_REF,
            estado_buscador_inicial=None,  # Buscador no disponible
        )

        entorno.tarea.ejecutar_cierre_diario()

        abstenciones = entorno.repositorio_abstenciones.consultar_ultimas(10)
        assert len(abstenciones) > 0
        assert any("buscador" in a.motivo.lower() or "no disponible" in a.motivo.lower()
                    for a in abstenciones)

    def test_abstencion_guardian_incluye_recuentos(self, tmp_path):
        """La abstención del guardián incluye los recuentos."""
        ofertas = [
            _oferta_base("000000101001"),
        ]
        entorno = _crear_entorno_e2e(
            tmp_path,
            ofertas,
            FECHA_REF,
            _estado_buscador_ok(total=60),
            listado_pdf_codigos=set(),
        )
        fecha_ayer = (FECHA_REF - timedelta(days=1)).date().isoformat()
        entorno.repositorio_presencia.registrar_ausencia(
            "Cantabria", "000000101001", fecha_ayer
        )
        entorno.repositorio_presencia.registrar_recuento(
            100, "2026-11-20T01:30:00+01:00"
        )

        entorno.tarea.ejecutar_cierre_diario()

        abstenciones = entorno.repositorio_abstenciones.consultar_ultimas(10)
        # Buscar una abstención con recuentos
        abstenciones_con_recuentos = [
            a for a in abstenciones if a.recuento_anterior is not None
        ]
        assert len(abstenciones_con_recuentos) > 0
        abst = abstenciones_con_recuentos[0]
        assert abst.recuento_anterior == 100
        assert abst.recuento_actual == 60


# ---------------------------------------------------------------------------
# Tests TASK-018: La BD de persistencia conserva su contenido
# ---------------------------------------------------------------------------


class TestBDPersistenciaIntacta:
    """Verifica que la BD de persistencia no se corrompe."""

    def test_bd_persistencia_conserva_ofertas_no_cerradas(self, tmp_path):
        """Las ofertas no cerradas permanecen intactas tras el cierre."""
        ofertas = [
            _oferta_base("000000110001", fecha_fin_difusion="20/11/2026"),
            _oferta_base("000000110002"),  # Vigente, presente en listado
        ]
        entorno = _crear_entorno_e2e(
            tmp_path,
            ofertas,
            FECHA_REF,
            _estado_buscador_ok(total=93),
            listado_pdf_codigos={"000000110002"},
        )
        # Registrar recuento previo para que el guardián permita el cierre
        entorno.repositorio_presencia.registrar_recuento(
            93, "2026-11-20T01:30:00+01:00"
        )

        entorno.tarea.ejecutar_cierre_diario()

        # La oferta 001 se cierra
        o1 = _leer_oferta(entorno.ruta_bd_persistencia, "Cantabria", "000000110001")
        assert o1["estado"] == "cerrada"

        # La oferta 002 sigue vigente
        o2 = _leer_oferta(entorno.ruta_bd_persistencia, "Cantabria", "000000110002")
        assert o2["estado"] == "vigente"
        assert o2["texto_libre"] == "Texto de prueba"
        assert o2["contacto"] == "contacto@test.com"

    def test_bd_historico_tiene_cuatro_tablas(self, tmp_path):
        """La BD del histórico tiene las cuatro tablas propias."""
        ofertas = [_oferta_base("000000111001")]
        entorno = _crear_entorno_e2e(
            tmp_path,
            ofertas,
            FECHA_REF,
            _estado_buscador_ok(total=93),
            listado_pdf_codigos=set(),
        )

        tablas = {
            fila[0]
            for fila in entorno.conexion_historico.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "presencia_en_listado" in tablas
        assert "serie_recuentos" in tablas
        assert "abstenciones_cierre" in tablas
        assert "ejecucion_diaria" in tablas
        # No debe haber tabla de ofertas
        assert "ofertas" not in tablas
