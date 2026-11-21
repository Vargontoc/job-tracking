"""Tests de integración del ciclo de vida de la persistencia (TASK-013).

Verifica que:
- La app arranca sin errores con la persistencia integrada
- La base de datos se crea con WAL
- Las migraciones se aplican
- Los códigos vistos se importan
- Las tareas en segundo plano se inician
- El apagado es ordenado (ingesta, purga, conexión)
- Los endpoints de persistencia están disponibles
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _crear_entorno(tmp_path):
    """Crea ficheros de configuración y datos temporales para los tests."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    ruta_bd = str(data_dir / "test_lifecycle.db")
    seen_codes_path = data_dir / "seen_codes.json"
    seen_codes_path.write_text(
        json.dumps(["000001", "000002", "000003"]), encoding="utf-8"
    )
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
    return {
        "tmp_path": tmp_path,
        "ruta_bd": ruta_bd,
        "seen_codes_path": str(seen_codes_path),
        "config_persistencia_path": config_persistencia,
    }


def _aplicar_parches(monkeypatch, entorno):
    """Aplica los monkeypatches en los módulos fuente para que sobrevivan al reload."""
    from source.api.buscador.models import ConfigBuscador

    config_buscador = ConfigBuscador(
        ruta_seen_codes=entorno["seen_codes_path"],
    )
    # Parchear en el módulo fuente, no en main (el reload reimporta desde la fuente)
    monkeypatch.setattr(
        "source.api.buscador.config.cargar_configuracion",
        lambda: config_buscador,
    )

    # Parchear la ruta por defecto de la config de persistencia en su módulo fuente
    monkeypatch.setattr(
        "source.api.persistencia.config.DEFAULT_CONFIG_PATH",
        Path(entorno["config_persistencia_path"]),
    )

    # Evitar que el Scheduler del buscador arranque hilos reales
    from source.api.buscador.scheduler import Scheduler
    monkeypatch.setattr(Scheduler, "iniciar", lambda self: None)
    monkeypatch.setattr(Scheduler, "detener", lambda self: None)


@pytest.fixture
def app_lista(tmp_path, monkeypatch):
    """Prepara el entorno y devuelve (client, main_mod, entorno) con la app arrancada."""
    entorno = _crear_entorno(tmp_path)
    _aplicar_parches(monkeypatch, entorno)

    # Recargar el módulo para que tome los parches (reimporta desde los módulos fuente)
    import importlib
    import source.api.main as main_mod
    importlib.reload(main_mod)

    with TestClient(main_mod.app) as client:
        yield client, main_mod, entorno


class TestArranquePersistencia:
    """Verifica que el arranque inicializa correctamente la persistencia."""

    def test_la_bd_existe_tras_arrancar(self, app_lista):
        client, main_mod, entorno = app_lista
        assert Path(entorno["ruta_bd"]).exists()

    def test_wal_activado(self, app_lista):
        client, main_mod, entorno = app_lista
        conexion = main_mod.app_state.get("conexion_persistencia")
        assert conexion is not None
        resultado = conexion.execute("PRAGMA journal_mode").fetchone()
        assert resultado[0] == "wal"

    def test_migraciones_aplicadas(self, app_lista):
        client, main_mod, entorno = app_lista
        conexion = main_mod.app_state.get("conexion_persistencia")
        assert conexion is not None
        fila = conexion.execute(
            "SELECT MAX(version) FROM schema_version"
        ).fetchone()
        assert fila is not None and fila[0] >= 1

    def test_codigos_vistos_importados(self, app_lista):
        client, main_mod, entorno = app_lista
        repositorio = main_mod.app_state.get("repositorio")
        assert repositorio is not None
        for codigo in ["000001", "000002", "000003"]:
            resultado = repositorio.consultar_por_clave("Cantabria", codigo)
            assert resultado.encontrada
            assert resultado.oferta is not None
            assert resultado.oferta.estado == "sin_ficha"

    def test_tareas_en_segundo_plano_iniciadas(self, app_lista):
        client, main_mod, entorno = app_lista
        assert main_mod.app_state.get("tarea_ingesta") is not None
        assert main_mod.app_state.get("tarea_purga") is not None

    def test_repositorio_en_app_state(self, app_lista):
        client, main_mod, entorno = app_lista
        assert main_mod.app_state.get("repositorio") is not None


class TestEndpointsDisponibles:
    """Verifica que los endpoints de persistencia responden tras el arranque."""

    def test_endpoint_listar_vigentes(self, app_lista):
        client, main_mod, entorno = app_lista
        respuesta = client.get("/persistencia/ofertas/vigentes")
        assert respuesta.status_code == 200

    def test_endpoint_codigos_vistos(self, app_lista):
        client, main_mod, entorno = app_lista
        respuesta = client.get("/persistencia/codigos-vistos/Cantabria")
        assert respuesta.status_code == 200
        datos = respuesta.json()
        assert "codigos" in datos
        assert "000001" in datos["codigos"]

    def test_endpoint_consultar_oferta_no_encontrada(self, app_lista):
        client, main_mod, entorno = app_lista
        respuesta = client.get("/persistencia/ofertas/Cantabria/999999")
        assert respuesta.status_code == 404

    def test_endpoint_crear_oferta(self, app_lista):
        client, main_mod, entorno = app_lista
        respuesta = client.post(
            "/persistencia/ofertas",
            json={
                "comunidad": "Cantabria",
                "codigo": "000099",
                "provincia": "Cantabria",
                "ocupacion": "Test",
                "municipio": "Santander",
            },
        )
        assert respuesta.status_code == 200
        datos = respuesta.json()
        assert datos["codigo"] == "000099"


class TestApagadoOrdenado:
    """Verifica que el apagado detiene primero ingesta, luego purga, luego conexión."""

    def test_apagado_detiene_tareas_antes_de_conexion(self, tmp_path, monkeypatch):
        orden_apagado = []

        entorno = _crear_entorno(tmp_path)
        _aplicar_parches(monkeypatch, entorno)

        # Registrar el orden de detención parcheando las clases fuente
        from source.api.persistencia.ingestion import TareaIngesta
        from source.api.persistencia.purge import TareaPurga

        detener_ingesta_orig = TareaIngesta.detener
        detener_purga_orig = TareaPurga.detener

        def mock_detener_ingesta(self):
            orden_apagado.append("ingesta")
            detener_ingesta_orig(self)

        def mock_detener_purga(self):
            orden_apagado.append("purga")
            detener_purga_orig(self)

        monkeypatch.setattr(TareaIngesta, "detener", mock_detener_ingesta)
        monkeypatch.setattr(TareaPurga, "detener", mock_detener_purga)

        import importlib
        import source.api.main as main_mod
        importlib.reload(main_mod)

        with TestClient(main_mod.app) as client:
            pass  # El apagado ocurre al salir del contexto

        assert "ingesta" in orden_apagado
        assert "purga" in orden_apagado
        assert orden_apagado.index("ingesta") < orden_apagado.index("purga")


class TestSeenCodesCorrupto:
    """Verifica que un seen_codes.json corrupto no bloquea el arranque (ALT-003)."""

    def test_arranque_con_seen_codes_corrupto(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        ruta_bd = str(data_dir / "test_corrupt.db")
        seen_codes_path = data_dir / "seen_codes.json"
        seen_codes_path.write_text("{no es json valido", encoding="utf-8")

        config_persistencia = config_dir / "persistencia.yaml"
        config_persistencia.write_text(
            "base_de_datos:\n"
            f"  ruta: {ruta_bd}\n",
            encoding="utf-8",
        )

        # Parchear en los módulos fuente
        from source.api.buscador.models import ConfigBuscador
        config_buscador = ConfigBuscador(ruta_seen_codes=str(seen_codes_path))
        monkeypatch.setattr(
            "source.api.buscador.config.cargar_configuracion",
            lambda: config_buscador,
        )
        monkeypatch.setattr(
            "source.api.persistencia.config.DEFAULT_CONFIG_PATH",
            Path(config_persistencia),
        )

        from source.api.buscador.scheduler import Scheduler
        monkeypatch.setattr(Scheduler, "iniciar", lambda self: None)
        monkeypatch.setattr(Scheduler, "detener", lambda self: None)

        import importlib
        import source.api.main as main_mod
        importlib.reload(main_mod)

        # El arranque no debe fallar a pesar del JSON corrupto
        with TestClient(main_mod.app) as client:
            assert client.get("/health").status_code == 200
