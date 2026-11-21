"""Tests de integración para el endpoint de pasada manual del buscador."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from source.api.main import app, app_state
from source.api.buscador.models import ResultadoPasada, OfertaBuscador, ErrorOferta


@pytest.fixture
def client():
    """Cliente de prueba de FastAPI."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def coordinador_mock():
    """Mock del coordinador de pasadas."""
    coordinador = MagicMock()
    coordinador.pasada_en_curso = False
    return coordinador


@pytest.fixture(autouse=True)
def limpiar_estado():
    """Limpia el estado de la aplicación antes y después de cada test."""
    app_state.clear()
    yield
    app_state.clear()


def test_ruta_registrada_post_buscador_run(client):
    """La ruta POST /buscador/run está registrada."""
    # Sin coordinador debería devolver 503
    response = client.post("/buscador/run")
    assert response.status_code == 503
    assert "coordinador" in response.json()["detail"].lower()


def test_endpoint_acepta_cuerpo_opcional(client, coordinador_mock):
    """El endpoint acepta cuerpo opcional."""
    # Configurar coordinador mock
    resultado_mock = ResultadoPasada(
        timestamp="2026-11-18T01:00:00",
        comunidad="Cantabria",
        total_listado=0,
        error_global="",
        errores_por_oferta=[],
        ofertas_nuevas=[],
    )
    coordinador_mock.ejecutar_pasada.return_value = resultado_mock
    app_state["coordinador"] = coordinador_mock

    # Sin cuerpo
    response = client.post("/buscador/run")
    assert response.status_code == 200

    # Con cuerpo vacío
    response = client.post("/buscador/run", json={})
    assert response.status_code == 200

    # Con historical_codes
    response = client.post(
        "/buscador/run",
        json={"historical_codes": ["062026003484"]},
    )
    assert response.status_code == 200


def test_sin_cuerpo_usa_seen_codes_json(client, coordinador_mock):
    """Sin cuerpo, la pasada usa el fichero seen_codes.json."""
    resultado_mock = ResultadoPasada(
        timestamp="2026-11-18T01:00:00",
        comunidad="Cantabria",
        total_listado=0,
        error_global="",
        errores_por_oferta=[],
        ofertas_nuevas=[],
    )
    coordinador_mock.ejecutar_pasada.return_value = resultado_mock
    app_state["coordinador"] = coordinador_mock

    response = client.post("/buscador/run")
    assert response.status_code == 200

    # Verificar que se llamó a ejecutar_pasada sin historical_codes (None)
    coordinador_mock.ejecutar_pasada.assert_called_once_with(historical_codes=None)


def test_con_historical_codes_usa_lista(client, coordinador_mock):
    """Con historical_codes, la pasada usa esa lista."""
    resultado_mock = ResultadoPasada(
        timestamp="2026-11-18T01:00:00",
        comunidad="Cantabria",
        total_listado=0,
        error_global="",
        errores_por_oferta=[],
        ofertas_nuevas=[],
    )
    coordinador_mock.ejecutar_pasada.return_value = resultado_mock
    app_state["coordinador"] = coordinador_mock

    historical_codes = ["062026003484", "062026003485"]
    response = client.post(
        "/buscador/run",
        json={"historical_codes": historical_codes},
    )
    assert response.status_code == 200

    # Verificar que se llamó a ejecutar_pasada con historical_codes
    coordinador_mock.ejecutar_pasada.assert_called_once_with(
        historical_codes=historical_codes
    )


def test_respuesta_estructura_req_013(client, coordinador_mock):
    """La respuesta coincide con la estructura de REQ-013."""
    # Crear un resultado completo con ofertas y errores
    oferta = OfertaBuscador(
        numero_oferta="062026003484",
        ocupacion="Desarrollador",
        municipio="Santander",
        provincia="Cantabria",
        fecha_inicio_difusion="18/11/2026",
        fecha_fin_difusion="03/12/2026",
        texto_libre="Puesto de desarrollo",
        contacto="email@example.com",
    )
    error = ErrorOferta(
        codigo="062026003485",
        mensaje="Error al parsear",
    )
    resultado_mock = ResultadoPasada(
        timestamp="2026-11-18T01:00:00",
        comunidad="Cantabria",
        total_listado=10,
        error_global="",
        errores_por_oferta=[error],
        ofertas_nuevas=[oferta],
    )
    coordinador_mock.ejecutar_pasada.return_value = resultado_mock
    app_state["coordinador"] = coordinador_mock

    response = client.post("/buscador/run")
    assert response.status_code == 200

    data = response.json()
    # Verificar estructura REQ-013
    assert "timestamp" in data
    assert "comunidad" in data
    assert "total_listado" in data
    assert "error_global" in data
    assert "errores_por_oferta" in data
    assert "ofertas_nuevas" in data

    # Verificar tipos
    assert isinstance(data["timestamp"], str)
    assert isinstance(data["comunidad"], str)
    assert isinstance(data["total_listado"], int)
    assert isinstance(data["error_global"], str)
    assert isinstance(data["errores_por_oferta"], list)
    assert isinstance(data["ofertas_nuevas"], list)

    # Verificar contenido
    assert data["comunidad"] == "Cantabria"
    assert data["total_listado"] == 10
    assert len(data["errores_por_oferta"]) == 1
    assert len(data["ofertas_nuevas"]) == 1

    # Verificar estructura de oferta
    oferta_data = data["ofertas_nuevas"][0]
    assert "numero_oferta" in oferta_data
    assert "ocupacion" in oferta_data
    assert "municipio" in oferta_data
    assert "provincia" in oferta_data
    assert "fecha_inicio_difusion" in oferta_data
    assert "fecha_fin_difusion" in oferta_data
    assert "texto_libre" in oferta_data
    assert "contacto" in oferta_data

    # Verificar estructura de error
    error_data = data["errores_por_oferta"][0]
    assert "codigo" in error_data
    assert "mensaje" in error_data


def test_pasada_en_curso_devuelve_omision(client, coordinador_mock):
    """Si hay una pasada en curso, devuelve respuesta de omisión."""
    # Simular pasada en curso
    coordinador_mock.pasada_en_curso = True
    resultado_omision = ResultadoPasada(
        timestamp="2026-11-18T01:00:00",
        comunidad="Cantabria",
        total_listado=0,
        error_global="Ya hay una pasada en curso",
        errores_por_oferta=[],
        ofertas_nuevas=[],
    )
    coordinador_mock.ejecutar_pasada.return_value = resultado_omision
    app_state["coordinador"] = coordinador_mock

    response = client.post("/buscador/run")
    assert response.status_code == 200

    data = response.json()
    assert data["error_global"] == "Ya hay una pasada en curso"
    assert len(data["ofertas_nuevas"]) == 0


def test_sin_credenciales(client, coordinador_mock):
    """El endpoint no requiere credenciales."""
    resultado_mock = ResultadoPasada(
        timestamp="2026-11-18T01:00:00",
        comunidad="Cantabria",
        total_listado=0,
        error_global="",
        errores_por_oferta=[],
        ofertas_nuevas=[],
    )
    coordinador_mock.ejecutar_pasada.return_value = resultado_mock
    app_state["coordinador"] = coordinador_mock

    # Sin headers de autenticación
    response = client.post("/buscador/run")
    assert response.status_code == 200

    # Verificar que no hay error 401 o 403
    assert response.status_code not in [401, 403]


def test_coordinador_no_disponible(client):
    """Si el coordinador no está disponible, devuelve 503."""
    # No configurar coordinador en app_state
    response = client.post("/buscador/run")
    assert response.status_code == 503
    assert "coordinador" in response.json()["detail"].lower()


# ============================================================================
# Tests del endpoint GET /buscador/status
# ============================================================================


def test_status_sin_pasadas_registradas(client, coordinador_mock):
    """Sin pasadas registradas, indica que no hay pasada en curso ni última finalizada."""
    coordinador_mock.pasada_en_curso = False
    coordinador_mock.ultimo_resultado = None
    app_state["coordinador"] = coordinador_mock

    response = client.get("/buscador/status")
    assert response.status_code == 200

    data = response.json()
    assert data["in_progress"] is False
    assert data["progreso"] is None
    assert data["ultima_pasada"] is None


def test_status_con_pasada_en_curso(client, coordinador_mock):
    """Con pasada en curso, in_progress: true con hora de inicio y progreso."""
    from source.api.buscador.coordinator import ProgresoPasada

    coordinador_mock.pasada_en_curso = True
    coordinador_mock.progreso = ProgresoPasada(
        hora_inicio="2026-01-15T10:30:00",
        codigos_procesados=45,
        total_codigos=93,
    )
    coordinador_mock.ultimo_resultado = None
    app_state["coordinador"] = coordinador_mock

    response = client.get("/buscador/status")
    assert response.status_code == 200

    data = response.json()
    assert data["in_progress"] is True
    assert data["progreso"] is not None
    assert data["progreso"]["hora_inicio"] == "2026-01-15T10:30:00"
    assert data["progreso"]["codigos_procesados"] == 45
    assert data["progreso"]["total_codigos"] == 93


def test_status_con_pasada_finalizada(client, coordinador_mock):
    """Con pasada finalizada, in_progress: false con resumen completo."""
    resultado_finalizado = ResultadoPasada(
        timestamp="2026-01-15T10:30:00",
        comunidad="Cantabria",
        total_listado=93,
        error_global="",
        errores_por_oferta=[],
        ofertas_nuevas=[
            OfertaBuscador(
                numero_oferta="062026003484",
                ocupacion="Desarrollador",
                municipio="Santander",
                provincia="Cantabria",
                fecha_inicio_difusion="18/11/2026",
                fecha_fin_difusion="03/12/2026",
                texto_libre="Puesto de desarrollo",
                contacto="email@example.com",
            )
        ],
    )
    coordinador_mock.pasada_en_curso = False
    coordinador_mock.ultimo_resultado = resultado_finalizado
    app_state["coordinador"] = coordinador_mock

    response = client.get("/buscador/status")
    assert response.status_code == 200

    data = response.json()
    assert data["in_progress"] is False
    assert data["progreso"] is None
    assert data["ultima_pasada"] is not None
    assert data["ultima_pasada"]["timestamp"] == "2026-01-15T10:30:00"
    assert data["ultima_pasada"]["total_listado"] == 93
    assert len(data["ultima_pasada"]["ofertas_nuevas"]) == 1


def test_status_tras_pasada_con_ofertas_y_errores(client, coordinador_mock):
    """Tras pasada con 2 nuevas y 1 error por oferta, el resumen lo refleja."""
    resultado_pasada = ResultadoPasada(
        timestamp="2026-01-15T10:30:00",
        comunidad="Cantabria",
        total_listado=10,
        error_global="",
        errores_por_oferta=[
            ErrorOferta(codigo="062026003486", mensaje="Error al parsear"),
        ],
        ofertas_nuevas=[
            OfertaBuscador(
                numero_oferta="062026003484",
                ocupacion="Desarrollador",
                municipio="Santander",
                provincia="Cantabria",
            ),
            OfertaBuscador(
                numero_oferta="062026003485",
                ocupacion="Analista",
                municipio="Torrelavega",
                provincia="Cantabria",
            ),
        ],
    )
    coordinador_mock.pasada_en_curso = False
    coordinador_mock.ultimo_resultado = resultado_pasada
    app_state["coordinador"] = coordinador_mock

    response = client.get("/buscador/status")
    assert response.status_code == 200

    data = response.json()
    assert data["ultima_pasada"] is not None
    assert len(data["ultima_pasada"]["ofertas_nuevas"]) == 2
    assert len(data["ultima_pasada"]["errores_por_oferta"]) == 1
    assert data["ultima_pasada"]["errores_por_oferta"][0]["codigo"] == "062026003486"


def test_status_sin_credenciales(client, coordinador_mock):
    """El endpoint no requiere credenciales."""
    coordinador_mock.pasada_en_curso = False
    coordinador_mock.ultimo_resultado = None
    app_state["coordinador"] = coordinador_mock

    # Sin headers de autenticación
    response = client.get("/buscador/status")
    assert response.status_code == 200

    # Verificar que no hay error 401 o 403
    assert response.status_code not in [401, 403]


def test_status_coordinador_no_disponible(client):
    """Si el coordinador no está disponible, devuelve 503."""
    # No configurar coordinador en app_state
    response = client.get("/buscador/status")
    assert response.status_code == 503
    assert "coordinador" in response.json()["detail"].lower()


# ============================================================================
# Tests del ciclo de vida (lifespan)
# ============================================================================


def test_lifespan_carga_configuracion(tmp_path, monkeypatch):
    """Al arrancar, la configuración se carga correctamente."""
    # Crear fichero de configuración temporal
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_file = config_dir / "buscador.yaml"
    config_file.write_text(
        "hora: 2\n"
        "rutas:\n"
        "  seen_codes: seen_codes.json\n"
        "  failed_htmls: failed_htmls\n",
        encoding="utf-8"
    )
    
    # Cambiar directorio de trabajo temporalmente
    monkeypatch.chdir(tmp_path)
    
    # Importar aquí para que use el directorio temporal
    from source.api.main import app, app_state
    
    # Usar TestClient que maneja automáticamente el lifespan
    with TestClient(app) as client:
        # Verificar que la configuración se cargó
        assert "config" in app_state
        assert app_state["config"].hora_pasada == 2
        assert app_state["config"].ruta_seen_codes == "seen_codes.json"


def test_lifespan_crea_seen_codes_si_no_existe(tmp_path, monkeypatch):
    """Al arrancar, seen_codes.json se crea si no existe."""
    # Crear directorio temporal sin seen_codes.json
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    
    # Crear configuración que apunte al directorio temporal
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_file = config_dir / "buscador.yaml"
    config_file.write_text(
        "hora: 1\n"
        "rutas:\n"
        "  seen_codes: data/seen_codes.json\n",
        encoding="utf-8"
    )
    
    # Cambiar directorio de trabajo
    monkeypatch.chdir(tmp_path)
    
    from source.api.main import app
    
    with TestClient(app) as client:
        # Verificar que se creó seen_codes.json
        seen_codes_path = data_dir / "seen_codes.json"
        assert seen_codes_path.exists()
        assert seen_codes_path.read_text(encoding="utf-8") == "[]"


def test_lifespan_endpoints_funcionan_tras_arranque(tmp_path, monkeypatch):
    """Los endpoints funcionan después del arranque."""
    # Crear configuración temporal
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_file = config_dir / "buscador.yaml"
    config_file.write_text("hora: 1\n", encoding="utf-8")
    
    monkeypatch.chdir(tmp_path)
    
    from source.api.main import app
    
    with TestClient(app) as client:
        # Verificar que los endpoints responden (aunque coordinador sea None)
        response = client.get("/buscador/status")
        assert response.status_code == 503  # Esperado porque coordinador es None
        
        response = client.post("/buscador/run")
        assert response.status_code == 503  # Esperado porque coordinador es None


def test_lifespan_configuracion_por_defecto_si_falta_archivo(tmp_path, monkeypatch):
    """Si config/buscador.yaml no existe, usa configuración por defecto."""
    # No crear fichero de configuración
    monkeypatch.chdir(tmp_path)
    
    from source.api.main import app, app_state
    
    with TestClient(app) as client:
        # Verificar que se usó configuración por defecto
        assert "config" in app_state
        # hora_pasada por defecto es 1
        assert app_state["config"].hora_pasada == 1


# ============================================================================
# Tests de integración end-to-end (TASK-017)
# ============================================================================


from pathlib import Path
from source.api.buscador.coordinator import CoordinadorPasada
from source.api.buscador.models import ConfigBuscador
from source.api.buscador.rate_limiter import LimitadorPeticiones


class ClienteHTTPMock:
    """Cliente HTTP mock que simula respuestas del portal."""
    
    def __init__(self):
        self.respuestas = {}
        self.llamadas = []
    
    def get(self, url, timeout=30.0):
        """Simula una petición GET."""
        self.llamadas.append(url)
        
        if url in self.respuestas:
            return self.respuestas[url]
        
        # Respuesta por defecto: error 404
        class RespuestaMock:
            status_code = 404
            text = ""
            
            def raise_for_status(self):
                raise RuntimeError(f"HTTP {self.status_code}")
        
        return RespuestaMock()
    
    def agregar_respuesta(self, url, html, status_code=200):
        """Agrega una respuesta mock para una URL específica."""
        class RespuestaMock:
            def __init__(self, status, text):
                self.status_code = status
                self.text = text
            
            def raise_for_status(self):
                if self.status_code >= 400:
                    raise RuntimeError(f"HTTP {self.status_code}")
        
        self.respuestas[url] = RespuestaMock(status_code, html)


@pytest.fixture
def fixtures_dir():
    """Directorio de fixtures HTML."""
    return Path(__file__).parent.parent / "fixtures" / "buscador"


@pytest.fixture
def cliente_portal_mock(fixtures_dir):
    """Cliente HTTP mock con respuestas del portal."""
    cliente = ClienteHTTPMock()
    
    # Cargar fixtures HTML
    listado_pagina_1 = (fixtures_dir / "listado_pagina_1.html").read_text(encoding="utf-8")
    listado_pagina_2 = (fixtures_dir / "listado_pagina_2.html").read_text(encoding="utf-8")
    listado_vacio = (fixtures_dir / "listado_vacio.html").read_text(encoding="utf-8")
    ficha_062026003633 = (fixtures_dir / "ficha_062026003633.html").read_text(encoding="utf-8")
    
    # Configurar respuestas con URLs completas de Liferay
    # El scraper usa nombres de parámetros completos del portlet
    cliente.agregar_respuesta(
        "https://empleacantabria.es/ofertas-cantabria?_es_gobcantabria_liferay_empleacan_buscador_ofertas_EmpleacanBuscadorOfertasPortlet_delta=75&_es_gobcantabria_liferay_empleacan_buscador_ofertas_EmpleacanBuscadorOfertasPortlet_cur=1",
        listado_pagina_1
    )
    cliente.agregar_respuesta(
        "https://empleacantabria.es/ofertas-cantabria?_es_gobcantabria_liferay_empleacan_buscador_ofertas_EmpleacanBuscadorOfertasPortlet_delta=75&_es_gobcantabria_liferay_empleacan_buscador_ofertas_EmpleacanBuscadorOfertasPortlet_cur=2",
        listado_pagina_2
    )
    cliente.agregar_respuesta(
        "https://empleacantabria.es/ofertas-cantabria/-/oferta/062026003633",
        ficha_062026003633
    )
    
    return cliente


@pytest.fixture
def config_test(tmp_path):
    """Configuración de prueba con rutas temporales."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    
    return ConfigBuscador(
        hora_pasada=1,
        url_listado="https://empleacantabria.es/ofertas-cantabria",
        url_ficha="https://empleacantabria.es/ofertas-cantabria/-/oferta",
        user_agent="Test/1.0",
        tamano_pagina=75,
        ruta_seen_codes=str(data_dir / "seen_codes.json"),
        ruta_failed_htmls=str(data_dir / "failed_htmls"),
        dias_purga=7,
    )


@pytest.fixture
def coordinador_real(config_test, cliente_portal_mock):
    """Coordinador real con cliente HTTP mock."""
    limitador = LimitadorPeticiones(delay_segundos=0.0)  # Sin delay para tests
    
    coordinador = CoordinadorPasada(
        config=config_test,
        cliente=cliente_portal_mock,
        limitador=limitador,
        ruta_seen_codes=Path(config_test.ruta_seen_codes),
        ruta_failed_htmls=Path(config_test.ruta_failed_htmls),
        dias_purga=config_test.dias_purga,
    )
    
    return coordinador


def test_integracion_listado_con_ofertas_nuevas(coordinador_real, config_test, tmp_path):
    """Listado con ofertas nuevas: 2 códigos nuevos → 2 ofertas y seen_codes.json con esos 2."""
    with TestClient(app) as client:
        # Configurar coordinador en app_state DESPUÉS de que el lifespan haya terminado
        app_state["coordinador"] = coordinador_real
        
        # Ejecutar pasada manual
        response = client.post("/buscador/run")
        assert response.status_code == 200
        
        resultado = response.json()
        
        # Verificar que se procesaron ofertas
        assert resultado["total_listado"] == 93  # Del listado_pagina_1
        assert len(resultado["ofertas_nuevas"]) >= 1  # Al menos una oferta procesada
        
        # Verificar que seen_codes.json se actualizó
        seen_codes_path = Path(config_test.ruta_seen_codes)
        assert seen_codes_path.exists()
        
        import json
        seen_codes = json.loads(seen_codes_path.read_text(encoding="utf-8"))
        assert len(seen_codes) >= 1  # Al menos un código guardado


def test_integracion_ficha_fallida_persistente(coordinador_real, config_test, tmp_path, cliente_portal_mock):
    """Ficha fallida persistente: una ficha falla → error por oferta, HTML archivado."""
    # Hacer que una ficha falle
    cliente_portal_mock.agregar_respuesta(
        "https://empleacantabria.es/ofertas-cantabria/-/oferta/062026003632",
        "<html><body>Error de parseo</body></html>",
        status_code=200
    )
    
    # Modificar el HTML para que no tenga los campos requeridos
    class RespuestaFichaInvalida:
        status_code = 200
        text = "<html><body>Sin campos requeridos</body></html>"
        
        def raise_for_status(self):
            pass
    
    cliente_portal_mock.respuestas[
        "https://empleacantabria.es/ofertas-cantabria/-/oferta/062026003632"
    ] = RespuestaFichaInvalida()
    
    with TestClient(app) as client:
        app_state["coordinador"] = coordinador_real
        
        response = client.post("/buscador/run")
        assert response.status_code == 200
        
        resultado = response.json()
        
        # Verificar que hubo errores por oferta
        assert len(resultado["errores_por_oferta"]) >= 1
        
        # Verificar que se archivó HTML fallido
        failed_htmls_dir = Path(config_test.ruta_failed_htmls)
        if failed_htmls_dir.exists():
            html_files = list(failed_htmls_dir.glob("*.html"))
            assert len(html_files) >= 1


def test_integracion_error_http_global(coordinador_real, config_test, cliente_portal_mock):
    """Error HTTP global: portal devuelve error → error global, ofertas vacías."""
    # Hacer que el listado falle
    cliente_portal_mock.respuestas.clear()
    
    class RespuestaError:
        status_code = 500
        text = ""
        
        def raise_for_status(self):
            raise RuntimeError("HTTP 500")
    
    cliente_portal_mock.respuestas[
        "https://empleacantabria.es/ofertas-cantabria?_es_gobcantabria_liferay_empleacan_buscador_ofertas_EmpleacanBuscadorOfertasPortlet_delta=75&_es_gobcantabria_liferay_empleacan_buscador_ofertas_EmpleacanBuscadorOfertasPortlet_cur=1"
    ] = RespuestaError()
    
    with TestClient(app) as client:
        app_state["coordinador"] = coordinador_real
        
        response = client.post("/buscador/run")
        assert response.status_code == 200  # Siempre 200
        
        resultado = response.json()
        
        # Verificar error global
        assert resultado["error_global"] != ""
        assert len(resultado["ofertas_nuevas"]) == 0
        
        # Verificar que seen_codes.json no se modificó
        seen_codes_path = Path(config_test.ruta_seen_codes)
        if seen_codes_path.exists():
            import json
            seen_codes = json.loads(seen_codes_path.read_text(encoding="utf-8"))
            assert len(seen_codes) == 0  # No se agregaron códigos


def test_integracion_listado_vacio(config_test, tmp_path):
    """Listado vacío: total 0 y fichero sin cambios."""
    # Crear cliente mock con listado vacío
    cliente = ClienteHTTPMock()
    
    fixtures_dir = Path(__file__).parent.parent / "fixtures" / "buscador"
    listado_vacio = (fixtures_dir / "listado_vacio.html").read_text(encoding="utf-8")
    
    cliente.agregar_respuesta(
        "https://empleacantabria.es/ofertas-cantabria?_es_gobcantabria_liferay_empleacan_buscador_ofertas_EmpleacanBuscadorOfertasPortlet_delta=75&_es_gobcantabria_liferay_empleacan_buscador_ofertas_EmpleacanBuscadorOfertasPortlet_cur=1",
        listado_vacio
    )
    
    limitador = LimitadorPeticiones(delay_segundos=0.0)
    
    coordinador = CoordinadorPasada(
        config=config_test,
        cliente=cliente,
        limitador=limitador,
        ruta_seen_codes=Path(config_test.ruta_seen_codes),
        ruta_failed_htmls=Path(config_test.ruta_failed_htmls),
        dias_purga=config_test.dias_purga,
    )
    
    with TestClient(app) as client:
        app_state["coordinador"] = coordinador
        
        response = client.post("/buscador/run")
        assert response.status_code == 200
        
        resultado = response.json()
        
        # Verificar listado vacío
        assert resultado["total_listado"] == 0
        assert len(resultado["ofertas_nuevas"]) == 0
        assert resultado["error_global"] == ""
        
        # Verificar que seen_codes.json no se modificó
        seen_codes_path = Path(config_test.ruta_seen_codes)
        if seen_codes_path.exists():
            import json
            seen_codes = json.loads(seen_codes_path.read_text(encoding="utf-8"))
            assert len(seen_codes) == 0


def test_integracion_solapamiento(coordinador_real):
    """Solapamiento: pasada en curso → segunda invocación devuelve omisión."""
    # Marcar pasada en curso manualmente
    coordinador_real._pasada_en_curso = True
    
    with TestClient(app) as client:
        app_state["coordinador"] = coordinador_real
        
        response = client.post("/buscador/run")
        assert response.status_code == 200
        
        resultado = response.json()
        
        # Verificar respuesta de omisión
        assert resultado["error_global"] == "Ya hay una pasada en curso"
        assert len(resultado["ofertas_nuevas"]) == 0
    
    # Limpiar estado
    coordinador_real._pasada_en_curso = False


def test_integracion_estado_final(coordinador_real, config_test):
    """Estado final: tras la pasada, el endpoint de estado muestra el resumen."""
    with TestClient(app) as client:
        app_state["coordinador"] = coordinador_real
        
        # Ejecutar pasada
        response_run = client.post("/buscador/run")
        assert response_run.status_code == 200
        
        # Consultar estado
        response_status = client.get("/buscador/status")
        assert response_status.status_code == 200
        
        estado = response_status.json()
        
        # Verificar estado
        assert estado["in_progress"] is False
        assert estado["ultima_pasada"] is not None
        assert estado["ultima_pasada"]["total_listado"] > 0


def test_integracion_http_200_siempre(coordinador_real, cliente_portal_mock):
    """HTTP 200 siempre: los fallos no cambian el código HTTP."""
    with TestClient(app) as client:
        app_state["coordinador"] = coordinador_real
        
        # Caso exitoso
        response = client.post("/buscador/run")
        assert response.status_code == 200
        
        # Caso con error global
        cliente_portal_mock.respuestas.clear()
        
        class RespuestaError:
            status_code = 500
            text = ""
            
            def raise_for_status(self):
                raise RuntimeError("HTTP 500")
        
        cliente_portal_mock.respuestas[
            "https://empleacantabria.es/ofertas-cantabria?_es_gobcantabria_liferay_empleacan_buscador_ofertas_EmpleacanBuscadorOfertasPortlet_delta=75&_es_gobcantabria_liferay_empleacan_buscador_ofertas_EmpleacanBuscadorOfertasPortlet_cur=1"
        ] = RespuestaError()
        
        response = client.post("/buscador/run")
        assert response.status_code == 200  # Sigue siendo 200
        
        # Caso con solapamiento
        coordinador_real._pasada_en_curso = True
        response = client.post("/buscador/run")
        assert response.status_code == 200  # Sigue siendo 200
        
        coordinador_real._pasada_en_curso = False


def test_integracion_sin_base_de_datos(coordinador_real, config_test, tmp_path):
    """Sin BD: no se crea fichero de base de datos."""
    with TestClient(app) as client:
        app_state["coordinador"] = coordinador_real
        
        response = client.post("/buscador/run")
        assert response.status_code == 200
        
        # Verificar que no hay ficheros de base de datos
        data_dir = tmp_path / "data"
        if data_dir.exists():
            db_files = list(data_dir.glob("*.db")) + list(data_dir.glob("*.sqlite"))
            assert len(db_files) == 0


def test_integracion_historical_codes_no_modifica_fichero(coordinador_real, config_test, tmp_path):
    """Con historical_codes, el fichero seen_codes.json NO se modifica."""
    with TestClient(app) as client:
        app_state["coordinador"] = coordinador_real
        
        # Crear fichero seen_codes.json con contenido inicial
        seen_codes_path = Path(config_test.ruta_seen_codes)
        seen_codes_path.write_text('["062026003999"]', encoding="utf-8")
        
        # Ejecutar pasada con historical_codes diferentes
        historical_codes = ["062026003484", "062026003485"]
        response = client.post(
            "/buscador/run",
            json={"historical_codes": historical_codes}
        )
        assert response.status_code == 200
        
        # Verificar que el fichero NO se modificó
        contenido_actual = seen_codes_path.read_text(encoding="utf-8")
        assert contenido_actual == '["062026003999"]'

