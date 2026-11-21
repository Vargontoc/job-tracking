"""Tests de integración para los endpoints de la API de persistencia (TASK-012)."""

import base64

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from source.api.persistencia.connection import abrir_conexion
from source.api.persistencia.migrations import migrar
from source.api.persistencia.repository import (
    EstadoOferta,
    Oferta,
    RepositorioOfertas,
)
from source.api.persistencia.routes import router as persistencia_router


@pytest.fixture
def bd_temporal(tmp_path):
    """Crea una BD SQLite temporal y migrada."""
    ruta = tmp_path / "test.db"
    conexion = abrir_conexion(ruta)
    migrar(conexion)
    yield conexion
    conexion.close()


@pytest.fixture
def repositorio(bd_temporal):
    """Repositorio de ofertas sobre la BD temporal."""
    return RepositorioOfertas(bd_temporal)


@pytest.fixture
def client(repositorio):
    """Cliente de prueba con el repositorio inyectado en app_state."""
    from source.api.main import app_state

    test_app = FastAPI()
    test_app.include_router(persistencia_router)

    # Inyectar el repositorio en app_state (como lo haría TASK-013 en lifespan)
    app_state["repositorio"] = repositorio
    try:
        with TestClient(test_app) as c:
            yield c
    finally:
        app_state.pop("repositorio", None)


def _embedding_a_base64(vector: np.ndarray) -> str:
    """Helper: numpy float32 -> base64."""
    blob = np.asarray(vector, dtype=np.float32).tobytes()
    return base64.b64encode(blob).decode("ascii")


def _datos_oferta(**overrides) -> dict:
    """Datos mínimos para crear una oferta."""
    datos = {
        "comunidad": "Cantabria",
        "codigo": "062026099999",
        "provincia": "Cantabria",
        "ocupacion": "Ingeniero informático",
        "municipio": "Santander",
        "fecha_inicio_difusion": "01/01/2026",
        "fecha_fin_difusion": "31/03/2026",
        "estado": "vigente",
        "texto_libre": "Descripción de prueba",
        "contacto": "empresa@example.com",
    }
    datos.update(overrides)
    return datos


# ---------------------------------------------------------------------------
# POST /persistencia/ofertas
# ---------------------------------------------------------------------------

class TestCrearOferta:
    """Tests del endpoint de creación/actualización."""

    def test_crear_oferta_devuelve_confirmacion(self, client):
        """Crear una oferta devuelve la confirmación con comunidad, codigo y estado."""
        datos = _datos_oferta()
        response = client.post("/persistencia/ofertas", json=datos)

        assert response.status_code == 200
        cuerpo = response.json()
        assert cuerpo["comunidad"] == "Cantabria"
        assert cuerpo["codigo"] == "062026099999"
        assert cuerpo["estado"] == "vigente"

    def test_actualizar_oferta_no_duplica(self, client, repositorio):
        """Actualizar dos veces la misma oferta no crea una segunda fila."""
        datos = _datos_oferta()
        client.post("/persistencia/ofertas", json=datos)

        # Actualizar con datos distintos
        datos["ocupacion"] = "Analista de datos"
        client.post("/persistencia/ofertas", json=datos)

        # Consultar: solo una oferta, con los datos actualizados
        resultado = repositorio.consultar_por_clave("Cantabria", "062026099999")
        assert resultado.encontrada
        assert resultado.oferta.ocupacion == "Analista de datos"

    def test_crear_oferta_sin_embedding(self, client):
        """Se puede crear una oferta sin embedding (es válido y opcional)."""
        datos = _datos_oferta()
        # Sin campo embedding
        response = client.post("/persistencia/ofertas", json=datos)
        assert response.status_code == 200

    def test_crear_oferta_con_embedding_base64(self, client, repositorio):
        """Crear una oferta con embedding en base64 lo persiste correctamente."""
        vector = np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float32)
        datos = _datos_oferta(
            embedding=_embedding_a_base64(vector),
            embedding_model_name="nomic-embed-text",
            embedding_model_version="v1",
            embedding_dim=4,
        )
        response = client.post("/persistencia/ofertas", json=datos)
        assert response.status_code == 200

        resultado = repositorio.consultar_por_clave("Cantabria", "062026099999")
        assert resultado.encontrada
        assert resultado.oferta.embedding is not None
        np.testing.assert_array_almost_equal(
            resultado.oferta.embedding, vector
        )


# ---------------------------------------------------------------------------
# GET /persistencia/ofertas/{comunidad}/{codigo}
# ---------------------------------------------------------------------------

class TestConsultarOferta:
    """Tests del endpoint de consulta por clave natural."""

    def test_consultar_oferta_existente(self, client):
        """Consultar una oferta existente devuelve todos los campos."""
        client.post("/persistencia/ofertas", json=_datos_oferta())

        response = client.get("/persistencia/ofertas/Cantabria/062026099999")
        assert response.status_code == 200
        cuerpo = response.json()

        # Campos de REQ-002
        assert cuerpo["comunidad"] == "Cantabria"
        assert cuerpo["codigo"] == "062026099999"
        assert cuerpo["provincia"] == "Cantabria"
        assert cuerpo["ocupacion"] == "Ingeniero informático"
        assert cuerpo["municipio"] == "Santander"
        assert cuerpo["fecha_inicio_difusion"] == "01/01/2026"
        assert cuerpo["fecha_fin_difusion"] == "31/03/2026"
        assert cuerpo["texto_libre"] == "Descripción de prueba"
        assert cuerpo["contacto"] == "empresa@example.com"
        # Estado
        assert cuerpo["estado"] == "vigente"
        # Embedding y metadatos (nulos si no se proporcionaron)
        assert cuerpo["embedding"] is None
        assert cuerpo["embedding_model_name"] is None
        assert cuerpo["embedding_model_version"] is None
        assert cuerpo["embedding_dim"] is None
        # Fechas de gestión
        assert cuerpo["fecha_alta"] is not None
        assert cuerpo["fecha_ultima_actualizacion"] is not None

    def test_consultar_oferta_inexistente_devuelve_404(self, client):
        """Consultar una oferta inexistente devuelve 404 explícita."""
        response = client.get("/persistencia/ofertas/Cantabria/999999999999")
        assert response.status_code == 404
        detalle = response.json()["detail"]
        assert "no se encontró" in detalle.lower() or "999999999999" in detalle

    def test_consultar_oferta_con_embedding(self, client):
        """La consulta devuelve el embedding en base64 y sus metadatos."""
        vector = np.array([0.5, 1.5, 2.5], dtype=np.float32)
        datos = _datos_oferta(
            embedding=_embedding_a_base64(vector),
            embedding_model_name="nomic-embed-text",
            embedding_model_version="v1.5",
            embedding_dim=3,
        )
        client.post("/persistencia/ofertas", json=datos)

        response = client.get("/persistencia/ofertas/Cantabria/062026099999")
        assert response.status_code == 200
        cuerpo = response.json()

        assert cuerpo["embedding"] is not None
        assert cuerpo["embedding_model_name"] == "nomic-embed-text"
        assert cuerpo["embedding_model_version"] == "v1.5"
        assert cuerpo["embedding_dim"] == 3

        # Verificar que el base64 se puede decodificar de vuelta
        blob = base64.b64decode(cuerpo["embedding"])
        reconstruido = np.frombuffer(blob, dtype=np.float32)
        np.testing.assert_array_almost_equal(reconstruido, vector)


# ---------------------------------------------------------------------------
# GET /persistencia/ofertas/vigentes
# ---------------------------------------------------------------------------

class TestListarVigentes:
    """Tests del listado de ofertas vigentes."""

    def test_listar_vigentes_solo_devuelve_vigentes(self, client, repositorio):
        """El listado solo devuelve ofertas con estado 'vigente'."""
        # Crear ofertas en distintos estados
        repositorio.crear_o_actualizar(Oferta(
            comunidad="Cantabria",
            codigo="062026000001",
            estado=EstadoOferta.VIGENTE,
            ocupacion="Vigente 1",
        ))
        repositorio.crear_o_actualizar(Oferta(
            comunidad="Cantabria",
            codigo="062026000002",
            estado=EstadoOferta.CERRADA,
            ocupacion="Cerrada",
        ))
        repositorio.crear_o_actualizar(Oferta(
            comunidad="Cantabria",
            codigo="062026000003",
            estado=EstadoOferta.SIN_FICHA,
            ocupacion="Sin ficha",
        ))
        repositorio.crear_o_actualizar(Oferta(
            comunidad="Cantabria",
            codigo="062026000004",
            estado=EstadoOferta.VIGENTE,
            ocupacion="Vigente 2",
        ))

        response = client.get("/persistencia/ofertas/vigentes")
        assert response.status_code == 200
        cuerpo = response.json()
        assert len(cuerpo) == 2
        estados = {o["estado"] for o in cuerpo}
        assert estados == {"vigente"}
        codigos = {o["codigo"] for o in cuerpo}
        assert codigos == {"062026000001", "062026000004"}

    def test_listar_vigentes_vacio(self, client):
        """Sin ofertas vigentes, devuelve una lista vacía."""
        response = client.get("/persistencia/ofertas/vigentes")
        assert response.status_code == 200
        assert response.json() == []


# ---------------------------------------------------------------------------
# GET /persistencia/codigos-vistos/{comunidad}
# ---------------------------------------------------------------------------

class TestCodigosVistos:
    """Tests del listado de códigos vistos."""

    def test_codigos_vistos_incluye_importados_y_ingeridos(self, client, repositorio):
        """Devuelve la unión de códigos importados (sin_ficha) e ingeridos (vigente)."""
        # Código importado (sin_ficha, como los de seen_codes.json)
        repositorio.crear_o_actualizar(Oferta(
            comunidad="Cantabria",
            codigo="062026000001",
            estado=EstadoOferta.SIN_FICHA,
        ))
        # Código ingerido con ficha completa (vigente)
        repositorio.crear_o_actualizar(Oferta(
            comunidad="Cantabria",
            codigo="062026000002",
            estado=EstadoOferta.VIGENTE,
            ocupacion="Ingeniero",
        ))

        response = client.get("/persistencia/codigos-vistos/Cantabria")
        assert response.status_code == 200
        cuerpo = response.json()
        assert cuerpo["comunidad"] == "Cantabria"
        assert set(cuerpo["codigos"]) == {"062026000001", "062026000002"}

    def test_codigos_vistos_sin_duplicados(self, client, repositorio):
        """No devuelve duplicados aunque el código haya cambiado de estado."""
        # Crear y luego actualizar el mismo código
        repositorio.crear_o_actualizar(Oferta(
            comunidad="Cantabria",
            codigo="062026000001",
            estado=EstadoOferta.SIN_FICHA,
        ))
        repositorio.crear_o_actualizar(Oferta(
            comunidad="Cantabria",
            codigo="062026000001",
            estado=EstadoOferta.VIGENTE,
            ocupacion="Ahora con ficha",
        ))

        response = client.get("/persistencia/codigos-vistos/Cantabria")
        cuerpo = response.json()
        assert cuerpo["codigos"].count("062026000001") == 1

    def test_codigos_vistos_otra_comunidad_no_incluye_cantabria(
        self, client, repositorio
    ):
        """Los códigos de Cantabria no aparecen en la lista de otra comunidad."""
        repositorio.crear_o_actualizar(Oferta(
            comunidad="Cantabria",
            codigo="062026000001",
            estado=EstadoOferta.VIGENTE,
        ))
        repositorio.crear_o_actualizar(Oferta(
            comunidad="Asturias",
            codigo="332026000001",
            estado=EstadoOferta.VIGENTE,
        ))

        response = client.get("/persistencia/codigos-vistos/Asturias")
        cuerpo = response.json()
        assert "062026000001" not in cuerpo["codigos"]
        assert "332026000001" in cuerpo["codigos"]


# ---------------------------------------------------------------------------
# Sin autenticación (SUP-008)
# ---------------------------------------------------------------------------

class TestSinAutenticacion:
    """Los endpoints no exigen cabeceras de autenticación."""

    def test_post_sin_autenticacion(self, client):
        """POST /persistencia/ofertas no exige autenticación."""
        response = client.post(
            "/persistencia/ofertas", json=_datos_oferta()
        )
        assert response.status_code == 200
        assert response.status_code not in (401, 403)

    def test_get_consulta_sin_autenticacion(self, client):
        """GET consulta no exige autenticación."""
        client.post("/persistencia/ofertas", json=_datos_oferta())
        response = client.get("/persistencia/ofertas/Cantabria/062026099999")
        assert response.status_code == 200
        assert response.status_code not in (401, 403)

    def test_get_vigentes_sin_autenticacion(self, client):
        """GET vigentes no exige autenticación."""
        response = client.get("/persistencia/ofertas/vigentes")
        assert response.status_code == 200
        assert response.status_code not in (401, 403)

    def test_get_codigos_vistos_sin_autenticacion(self, client):
        """GET códigos vistos no exige autenticación."""
        response = client.get("/persistencia/codigos-vistos/Cantabria")
        assert response.status_code == 200
        assert response.status_code not in (401, 403)


# ---------------------------------------------------------------------------
# Respuesta JSON sin SQL (el consumidor no ejecuta SQL)
# ---------------------------------------------------------------------------

class TestRespuestaJson:
    """Los endpoints devuelven JSON con los campos de la oferta."""

    def test_consulta_es_json_con_campos_oferta(self, client):
        """La respuesta de consulta es JSON con todos los campos de la oferta."""
        client.post("/persistencia/ofertas", json=_datos_oferta())
        response = client.get("/persistencia/ofertas/Cantabria/062026099999")
        assert response.status_code == 200

        cuerpo = response.json()
        # Verificar que es un dict (JSON) con los campos esperados
        assert isinstance(cuerpo, dict)
        campos_esperados = {
            "comunidad", "provincia", "codigo", "ocupacion", "municipio",
            "sector", "nivel", "contrato", "fecha_inicio_difusion",
            "fecha_fin_difusion", "estado", "texto_libre", "contacto",
            "embedding", "embedding_model_name", "embedding_model_version",
            "embedding_dim", "interesada", "fecha_alta", "fecha_cierre",
            "fecha_ultima_actualizacion",
        }
        assert campos_esperados.issubset(set(cuerpo.keys()))

    def test_listado_vigentes_es_json(self, client):
        """El listado de vigentes es una lista JSON."""
        response = client.get("/persistencia/ofertas/vigentes")
        assert response.status_code == 200
        cuerpo = response.json()
        assert isinstance(cuerpo, list)

    def test_codigos_vistos_es_json(self, client):
        """Los códigos vistos son un JSON con comunidad y lista de códigos."""
        response = client.get("/persistencia/codigos-vistos/Cantabria")
        assert response.status_code == 200
        cuerpo = response.json()
        assert isinstance(cuerpo, dict)
        assert "comunidad" in cuerpo
        assert "codigos" in cuerpo
        assert isinstance(cuerpo["codigos"], list)
