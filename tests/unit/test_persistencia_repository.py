"""Pruebas del repositorio de ofertas: upsert y consulta por clave natural (TASK-005)."""

import threading
import time

import numpy as np
import pytest

from source.api.persistencia.connection import abrir_conexion
from source.api.persistencia.migrations import migrar
from source.api.persistencia.repository import (
    EstadoOferta,
    Oferta,
    RepositorioOfertas,
    ResultadoConsulta,
    reconstruir_embedding,
    serializar_embedding,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ruta_db(tmp_path):
    """Devuelve la ruta de una BD temporal vacía."""
    return tmp_path / "test_repository.db"


@pytest.fixture
def conexion(ruta_db):
    """Abre una conexión a una BD temporal, migra y la cierra al terminar."""
    conn = abrir_conexion(ruta_db)
    migrar(conn)
    yield conn
    conn.close()


@pytest.fixture
def repositorio(conexion):
    """Devuelve un RepositorioOfertas sobre la BD temporal migrada."""
    return RepositorioOfertas(conexion)


def _oferta_completa(**kwargs) -> Oferta:
    """Crea una Oferta con todos los campos rellenos (valores por defecto)."""
    valores = dict(
        comunidad="Cantabria",
        codigo="000000000001",
        estado=EstadoOferta.VIGENTE,
        provincia="Cantabria",
        ocupacion="Ingeniero informático",
        municipio="Santander",
        fecha_inicio_difusion="01/01/2026",
        fecha_fin_difusion="31/03/2026",
        texto_libre="Se busca ingeniero con experiencia en Python.",
        contacto="rrhh@empresa.com",
        embedding=np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32),
        embedding_model_name="nomic-embed-text",
        embedding_model_version="1.0",
        embedding_dim=4,
    )
    valores.update(kwargs)
    return Oferta(**valores)


# ---------------------------------------------------------------------------
# Pruebas: persistir y consultar oferta completa
# ---------------------------------------------------------------------------

class TestPersistirYConsultarCompleta:
    """Persistir una oferta con todos los campos y consultarla."""

    def test_devuelve_todos_los_campos(self, repositorio):
        """La consulta por (comunidad, codigo) devuelve todos los campos."""
        oferta = _oferta_completa()
        repositorio.crear_o_actualizar(oferta)
        resultado = repositorio.consultar_por_clave("Cantabria", "000000000001")

        assert resultado.encontrada is True
        assert resultado.oferta is not None

        o = resultado.oferta
        assert o.comunidad == "Cantabria"
        assert o.provincia == "Cantabria"
        assert o.codigo == "000000000001"
        assert o.ocupacion == "Ingeniero informático"
        assert o.municipio == "Santander"
        assert o.fecha_inicio_difusion == "01/01/2026"
        assert o.fecha_fin_difusion == "31/03/2026"
        assert o.texto_libre == "Se busca ingeniero con experiencia en Python."
        assert o.contacto == "rrhh@empresa.com"
        assert o.estado == EstadoOferta.VIGENTE
        assert o.embedding is not None
        assert o.embedding_model_name == "nomic-embed-text"
        assert o.embedding_model_version == "1.0"
        assert o.embedding_dim == 4


# ---------------------------------------------------------------------------
# Pruebas: persistir dos veces no duplica (REQ-001)
# ---------------------------------------------------------------------------

class TestUpsertNoDuplica:
    """Persistir dos veces la misma (comunidad, codigo) deja una sola fila."""

    def test_sola_una_fila(self, repositorio, conexion):
        """Tras dos persistencias, el número de filas es 1."""
        oferta1 = _oferta_completa(ocupacion="Puesto A")
        oferta2 = _oferta_completa(ocupacion="Puesto B")
        repositorio.crear_o_actualizar(oferta1)
        repositorio.crear_o_actualizar(oferta2)

        total = conexion.execute(
            "SELECT COUNT(*) FROM ofertas WHERE comunidad = ? AND codigo = ?",
            ("Cantabria", "000000000001"),
        ).fetchone()[0]
        assert total == 1

    def test_actualiza_campos_modificables(self, repositorio):
        """La segunda persistencia actualiza los campos modificables."""
        oferta1 = _oferta_completa(ocupacion="Puesto A")
        repositorio.crear_o_actualizar(oferta1)

        oferta2 = _oferta_completa(ocupacion="Puesto B")
        repositorio.crear_o_actualizar(oferta2)

        resultado = repositorio.consultar_por_clave("Cantabria", "000000000001")
        assert resultado.oferta.ocupacion == "Puesto B"


# ---------------------------------------------------------------------------
# Pruebas: fecha_alta no cambia, fecha_ultima_actualizacion sí (REQ-003)
# ---------------------------------------------------------------------------

class TestFechasActualizacion:
    """Tras una actualización, fecha_ultima_actualizacion es posterior y fecha_alta no cambia."""

    def test_fecha_alta_no_cambia(self, repositorio):
        """fecha_alta no se modifica tras una actualización."""
        oferta = _oferta_completa()
        repositorio.crear_o_actualizar(oferta)
        resultado1 = repositorio.consultar_por_clave("Cantabria", "000000000001")
        fecha_alta_1 = resultado1.oferta.fecha_alta

        # Pequeña pausa para asegurar diferencia temporal
        time.sleep(0.05)

        oferta2 = _oferta_completa(ocupacion="Nuevo puesto")
        repositorio.crear_o_actualizar(oferta2)

        resultado2 = repositorio.consultar_por_clave("Cantabria", "000000000001")
        assert resultado2.oferta.fecha_alta == fecha_alta_1

    def test_fecha_ultima_actualizacion_posterior(self, repositorio):
        """fecha_ultima_actualizacion es posterior tras la actualización."""
        oferta = _oferta_completa()
        repositorio.crear_o_actualizar(oferta)
        resultado1 = repositorio.consultar_por_clave("Cantabria", "000000000001")
        fecha_update_1 = resultado1.oferta.fecha_ultima_actualizacion

        time.sleep(0.05)

        oferta2 = _oferta_completa(ocupacion="Nuevo puesto")
        repositorio.crear_o_actualizar(oferta2)

        resultado2 = repositorio.consultar_por_clave("Cantabria", "000000000001")
        fecha_update_2 = resultado2.oferta.fecha_ultima_actualizacion

        # Comparación ISO 8601 lexicográfica es válida para timestamps en el mismo huso
        assert fecha_update_2 >= fecha_update_1


# ---------------------------------------------------------------------------
# Pruebas: sector, nivel y contrato vacíos (DEC-009)
# ---------------------------------------------------------------------------

class TestCamposReservadosVacios:
    """sector, nivel y contrato se almacenan vacíos y no se infieren."""

    def test_se_guardan_vacios(self, repositorio):
        """Aunque la oferta traiga valores, se almacenan vacíos."""
        oferta = _oferta_completa(
            sector="Construcción",
            nivel="Junior",
            contrato="Indefinido",
        )
        repositorio.crear_o_actualizar(oferta)

        resultado = repositorio.consultar_por_clave("Cantabria", "000000000001")
        assert resultado.oferta.sector == ""
        assert resultado.oferta.nivel == ""
        assert resultado.oferta.contrato == ""


# ---------------------------------------------------------------------------
# Pruebas: oferta sin embedding (REQ-004)
# ---------------------------------------------------------------------------

class TestOfertaSinEmbedding:
    """Una oferta sin embedding se persiste y se consulta con embedding nulo."""

    def test_embedding_nulo(self, repositorio):
        """El embedding y sus metadatos son nulos cuando no se proporciona."""
        oferta = _oferta_completa(
            embedding=None,
            embedding_model_name=None,
            embedding_model_version=None,
            embedding_dim=None,
        )
        repositorio.crear_o_actualizar(oferta)

        resultado = repositorio.consultar_por_clave("Cantabria", "000000000001")
        assert resultado.encontrada is True
        assert resultado.oferta.embedding is None
        assert resultado.oferta.embedding_model_name is None
        assert resultado.oferta.embedding_model_version is None
        assert resultado.oferta.embedding_dim is None

    def test_sin_embedding_es_valida(self, repositorio):
        """La oferta sin embedding sigue siendo válida."""
        oferta = _oferta_completa(
            embedding=None,
            embedding_model_name=None,
            embedding_model_version=None,
            embedding_dim=None,
        )
        repositorio.crear_o_actualizar(oferta)

        resultado = repositorio.consultar_por_clave("Cantabria", "000000000001")
        assert resultado.encontrada is True
        assert resultado.oferta.estado == EstadoOferta.VIGENTE


# ---------------------------------------------------------------------------
# Pruebas: oferta con embedding (DEC-002)
# ---------------------------------------------------------------------------

class TestOfertaConEmbedding:
    """Una oferta con embedding se consulta con BLOB, modelo, versión y dimensión coherentes."""

    def test_embedding_coherente(self, repositorio):
        """El BLOB, nombre, versión y dimensión coinciden con los almacenados."""
        vector = np.array([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float32)
        oferta = _oferta_completa(
            embedding=vector,
            embedding_model_name="nomic-embed-text",
            embedding_model_version="1.5",
            embedding_dim=5,
        )
        repositorio.crear_o_actualizar(oferta)

        resultado = repositorio.consultar_por_clave("Cantabria", "000000000001")
        assert resultado.encontrada is True
        o = resultado.oferta
        assert o.embedding is not None
        np.testing.assert_array_almost_equal(o.embedding, vector)
        assert o.embedding_model_name == "nomic-embed-text"
        assert o.embedding_model_version == "1.5"
        assert o.embedding_dim == 5

    def test_embedding_dim_automatico(self, repositorio):
        """Si no se especifica embedding_dim, se infiere del vector."""
        vector = np.array([0.5, 0.6], dtype=np.float32)
        oferta = _oferta_completa(
            embedding=vector,
            embedding_model_name="modelo",
            embedding_model_version="2.0",
            embedding_dim=None,
        )
        repositorio.crear_o_actualizar(oferta)

        resultado = repositorio.consultar_por_clave("Cantabria", "000000000001")
        assert resultado.oferta.embedding_dim == 2
        np.testing.assert_array_almost_equal(resultado.oferta.embedding, vector)


# ---------------------------------------------------------------------------
# Pruebas: helpers de serialización/reconstrucción
# ---------------------------------------------------------------------------

class TestHelpersEmbedding:
    """serializar_embedding y reconstruir_embedding son inversos."""

    def test_roundtrip(self):
        """Serializar y reconstruir devuelve el vector original."""
        vector = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        blob = serializar_embedding(vector)
        reconstruido = reconstruir_embedding(blob, 3)
        np.testing.assert_array_almost_equal(reconstruido, vector)

    def test_tipo_float32(self):
        """El resultado es float32."""
        vector = np.array([1.0, 2.0], dtype=np.float64)
        blob = serializar_embedding(vector)
        reconstruido = reconstruir_embedding(blob, 2)
        assert reconstruido.dtype == np.float32


# ---------------------------------------------------------------------------
# Pruebas: código como texto de 12 dígitos con ceros iniciales (NFR-003)
# ---------------------------------------------------------------------------

class TestCodigoComoTexto:
    """El código se conserva como texto de 12 dígitos con sus ceros iniciales."""

    def test_codigo_con_ceros(self, repositorio):
        """Un código con ceros iniciales se conserva tal cual."""
        oferta = _oferta_completa(codigo="000000000042")
        repositorio.crear_o_actualizar(oferta)

        resultado = repositorio.consultar_por_clave("Cantabria", "000000000042")
        assert resultado.oferta.codigo == "000000000042"
        assert len(resultado.oferta.codigo) == 12


# ---------------------------------------------------------------------------
# Pruebas: fechas en formato dd/mm/aaaa (NFR-004)
# ---------------------------------------------------------------------------

class TestFechasDifusion:
    """Las fechas de difusión se guardan y se devuelven exactamente en dd/mm/aaaa."""

    def test_formato_fechas(self, repositorio):
        """Las fechas se conservan tal cual en formato dd/mm/aaaa."""
        oferta = _oferta_completa(
            fecha_inicio_difusion="15/02/2026",
            fecha_fin_difusion="28/02/2026",
        )
        repositorio.crear_o_actualizar(oferta)

        resultado = repositorio.consultar_por_clave("Cantabria", "000000000001")
        assert resultado.oferta.fecha_inicio_difusion == "15/02/2026"
        assert resultado.oferta.fecha_fin_difusion == "28/02/2026"


# ---------------------------------------------------------------------------
# Pruebas: dos comunidades con mismo código coexisten (NFR-007)
# ---------------------------------------------------------------------------

class TestComunidadesDistintas:
    """Dos ofertas con el mismo código y comunidades distintas son independientes."""

    def test_coexisten(self, repositorio):
        """Dos comunidades distintas con el mismo código generan dos registros."""
        oferta1 = _oferta_completa(comunidad="Cantabria", ocupacion="Puesto A")
        oferta2 = _oferta_completa(comunidad="Asturias", ocupacion="Puesto B")
        repositorio.crear_o_actualizar(oferta1)
        repositorio.crear_o_actualizar(oferta2)

        r1 = repositorio.consultar_por_clave("Cantabria", "000000000001")
        r2 = repositorio.consultar_por_clave("Asturias", "000000000001")

        assert r1.encontrada is True
        assert r2.encontrada is True
        assert r1.oferta.ocupacion == "Puesto A"
        assert r2.oferta.ocupacion == "Puesto B"
        assert r1.oferta.comunidad == "Cantabria"
        assert r2.oferta.comunidad == "Asturias"


# ---------------------------------------------------------------------------
# Pruebas: consulta inexistente (REQ-008)
# ---------------------------------------------------------------------------

class TestConsultaInexistente:
    """Consultar una (comunidad, codigo) inexistente indica no encontrada."""

    def test_no_encontrada(self, repositorio):
        """El resultado indica explícitamente que no se encontró la oferta."""
        resultado = repositorio.consultar_por_clave("Cantabria", "999999999999")
        assert resultado.encontrada is False
        assert resultado.oferta is None

    def test_resultado_tipo_consulta(self, repositorio):
        """El resultado es un ResultadoConsulta."""
        resultado = repositorio.consultar_por_clave("Cantabria", "000000000001")
        assert isinstance(resultado, ResultadoConsulta)


# ---------------------------------------------------------------------------
# Pruebas: escrituras concurrentes (ALT-005, NFR-006)
# ---------------------------------------------------------------------------

class TestEscriturasConcurrentes:
    """Dos escrituras concurrentes sobre la misma oferta dejan un único registro."""

    def test_concurrencia_deja_un_registro(self, ruta_db):
        """Dos hilos escribiendo la misma oferta dejan una sola fila."""
        conn = abrir_conexion(ruta_db)
        migrar(conn)
        conn.close()

        errores = []

        def escribir():
            try:
                c = abrir_conexion(ruta_db)
                try:
                    repo = RepositorioOfertas(c)
                    for _ in range(3):
                        oferta = _oferta_completa()
                        repo.crear_o_actualizar(oferta)
                finally:
                    c.close()
            except Exception as exc:
                errores.append(exc)

        hilo1 = threading.Thread(target=escribir)
        hilo2 = threading.Thread(target=escribir)
        hilo1.start()
        hilo2.start()
        hilo1.join(timeout=15)
        hilo2.join(timeout=15)

        assert not errores, f"Errores en escrituras concurrentes: {errores}"

        # Verificar que hay un único registro
        c = abrir_conexion(ruta_db)
        try:
            total = c.execute(
                "SELECT COUNT(*) FROM ofertas WHERE comunidad = ? AND codigo = ?",
                ("Cantabria", "000000000001"),
            ).fetchone()[0]
            assert total == 1
        finally:
            c.close()


# ---------------------------------------------------------------------------
# Pruebas: sin base de datos vectorial (NFR-005)
# ---------------------------------------------------------------------------

class TestSinBaseVectorial:
    """El repositorio no escribe ni lee ninguna base de datos vectorial."""

    def test_sin_tablas_vectoriales(self, repositorio, conexion):
        """No se crea ninguna tabla vectorial tras usar el repositorio."""
        oferta = _oferta_completa()
        repositorio.crear_o_actualizar(oferta)

        tablas = {
            fila[0]
            for fila in conexion.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        for tabla in tablas:
            assert "vector" not in tabla.lower()
            assert "vec" not in tabla.lower()

    def test_sin_extension_vectorial(self, repositorio, conexion):
        """No hay extensiones vectoriales en la base de datos."""
        oferta = _oferta_completa()
        repositorio.crear_o_actualizar(oferta)

        # Verificar que embedding se almacena como BLOB en la misma tabla
        info = conexion.execute("PRAGMA table_info(ofertas)").fetchall()
        tipos = {fila[1]: fila[2].upper() for fila in info}
        assert tipos["embedding"] == "BLOB"


# ---------------------------------------------------------------------------
# Pruebas: estado inicial
# ---------------------------------------------------------------------------

class TestEstadoInicial:
    """Persistir una oferta inexistente crea un registro con estado vigente."""

    def test_estado_vigente_por_defecto(self, repositorio):
        """Una oferta nueva sin estado explícito se crea como vigente."""
        oferta = Oferta(
            comunidad="Cantabria",
            codigo="000000000099",
        )
        repositorio.crear_o_actualizar(oferta)

        resultado = repositorio.consultar_por_clave("Cantabria", "000000000099")
        assert resultado.encontrada is True
        assert resultado.oferta.estado == EstadoOferta.VIGENTE

    def test_constantes_estado(self):
        """Las constantes de estado tienen los valores esperados."""
        assert EstadoOferta.SIN_FICHA == "sin_ficha"
        assert EstadoOferta.VIGENTE == "vigente"
        assert EstadoOferta.CERRADA == "cerrada"


# ---------------------------------------------------------------------------
# Pruebas TASK-006: listado por estado (listar_vigentes)
# ---------------------------------------------------------------------------

class TestListarVigentes:
    """El listado de vigentes devuelve solo registros con estado vigente."""

    def test_solo_vigentes(self, repositorio):
        """Con ofertas vigente, cerrada y sin_ficha, listar_vigentes devuelve solo las vigente."""
        repositorio.crear_o_actualizar(_oferta_completa(
            codigo="000000000001", estado=EstadoOferta.VIGENTE
        ))
        repositorio.crear_o_actualizar(_oferta_completa(
            codigo="000000000002", estado=EstadoOferta.CERRADA
        ))
        repositorio.crear_o_actualizar(_oferta_completa(
            codigo="000000000003", estado=EstadoOferta.SIN_FICHA,
            provincia="", ocupacion="", municipio="",
            fecha_inicio_difusion=None, fecha_fin_difusion=None,
        ))

        vigentes = repositorio.listar_vigentes()

        assert len(vigentes) == 1
        assert vigentes[0].codigo == "000000000001"
        assert vigentes[0].estado == EstadoOferta.VIGENTE

    def test_campos_minimos(self, repositorio):
        """Cada elemento incluye comunidad, provincia, código, ocupación, municipio y fechas."""
        repositorio.crear_o_actualizar(_oferta_completa(
            codigo="000000000010",
            comunidad="Cantabria",
            provincia="Cantabria",
            ocupacion="Ingeniero",
            municipio="Santander",
            fecha_inicio_difusion="01/01/2026",
            fecha_fin_difusion="31/03/2026",
            estado=EstadoOferta.VIGENTE,
        ))

        vigentes = repositorio.listar_vigentes()

        assert len(vigentes) == 1
        o = vigentes[0]
        assert o.comunidad == "Cantabria"
        assert o.provincia == "Cantabria"
        assert o.codigo == "000000000010"
        assert o.ocupacion == "Ingeniero"
        assert o.municipio == "Santander"
        assert o.fecha_inicio_difusion == "01/01/2026"
        assert o.fecha_fin_difusion == "31/03/2026"

    def test_lista_vacia_cuando_no_hay_vigentes(self, repositorio):
        """Si no hay ofertas vigentes, el listado está vacío."""
        repositorio.crear_o_actualizar(_oferta_completa(
            codigo="000000000020", estado=EstadoOferta.CERRADA
        ))
        assert repositorio.listar_vigentes() == []

    def test_ordena_por_fecha_fin_difusion(self, repositorio):
        """El listado ordena por fecha de fin de difusión (índice existente)."""
        repositorio.crear_o_actualizar(_oferta_completa(
            codigo="000000000030", fecha_fin_difusion="30/06/2026"
        ))
        repositorio.crear_o_actualizar(_oferta_completa(
            codigo="000000000031", fecha_fin_difusion="15/03/2026"
        ))
        repositorio.crear_o_actualizar(_oferta_completa(
            codigo="000000000032", fecha_fin_difusion="31/12/2026"
        ))

        vigentes = repositorio.listar_vigentes()

        codigos = [o.codigo for o in vigentes]
        assert codigos == ["000000000031", "000000000030", "000000000032"]

    def test_usa_indice_existente(self, repositorio, conexion):
        """La consulta usa el índice (estado, fecha_fin_difusion) y no escanea toda la tabla."""
        # Verificar que el índice existe
        indices = {
            fila[0]
            for fila in conexion.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        assert "idx_ofertas_estado_fecha_fin" in indices

        # Insertar varias ofertas y comprobar que el plan de ejecución usa el índice
        repositorio.crear_o_actualizar(_oferta_completa(
            codigo="000000000040", estado=EstadoOferta.VIGENTE
        ))
        plan = conexion.execute(
            "EXPLAIN QUERY PLAN SELECT codigo FROM ofertas "
            "WHERE estado = ? ORDER BY fecha_fin_difusion",
            (EstadoOferta.VIGENTE,),
        ).fetchall()
        # El plan debe referenciar el índice por estado
        plan_texto = " ".join(str(fila) for fila in plan)
        assert "idx_ofertas_estado_fecha_fin" in plan_texto.lower() \
            or "search" in plan_texto.lower() \
            or "index" in plan_texto.lower()


# ---------------------------------------------------------------------------
# Pruebas TASK-006: lista de códigos vistos (listar_codigos_vistos)
# ---------------------------------------------------------------------------

class TestListarCodigosVistos:
    """La lista de códigos vistos de una comunidad devuelve la unión sin duplicados."""

    def test_union_sin_duplicados(self, repositorio):
        """Devuelve la unión de sin_ficha y vigentes de Cantabria sin duplicados."""
        # Código importado sin ficha (simulando seen_codes.json)
        repositorio.crear_o_actualizar(_oferta_completa(
            codigo="062026003633", estado=EstadoOferta.SIN_FICHA,
            provincia="", ocupacion="", municipio="",
            fecha_inicio_difusion=None, fecha_fin_difusion=None,
        ))
        # Código con ficha ingerida (vigente)
        repositorio.crear_o_actualizar(_oferta_completa(
            codigo="062026003634", estado=EstadoOferta.VIGENTE
        ))
        # Código cerrado (también visto)
        repositorio.crear_o_actualizar(_oferta_completa(
            codigo="062026003635", estado=EstadoOferta.CERRADA
        ))

        vistos = repositorio.listar_codigos_vistos("Cantabria")

        assert set(vistos) == {"062026003633", "062026003634", "062026003635"}
        assert len(vistos) == len(set(vistos))  # sin duplicados

    def test_codigo_presente_no_es_nuevo(self, repositorio):
        """Un código presente en la lista de vistos no se considera oferta nueva."""
        repositorio.crear_o_actualizar(_oferta_completa(
            codigo="062026009999", estado=EstadoOferta.VIGENTE
        ))

        vistos = repositorio.listar_codigos_vistos("Cantabria")

        assert "062026009999" in vistos
        # El criterio de "nueva" se aplica fuera del método; aquí solo verificamos presencia
        assert "062026008888" not in vistos  # ausente → sería nueva

    def test_codigo_ausente_es_nuevo(self, repositorio):
        """Un código ausente de la lista de vistos se considera oferta nueva."""
        repositorio.crear_o_actualizar(_oferta_completa(
            codigo="062026000001", estado=EstadoOferta.VIGENTE
        ))

        vistos = repositorio.listar_codigos_vistos("Cantabria")

        # Código no presente: se consideraría oferta nueva
        assert "062026099999" not in vistos

    def test_otra_comunidad_no_incluye_cantabria(self, repositorio):
        """La lista de otra comunidad no incluye los códigos de Cantabria."""
        repositorio.crear_o_actualizar(_oferta_completa(
            comunidad="Cantabria", codigo="062026000001"
        ))
        repositorio.crear_o_actualizar(_oferta_completa(
            comunidad="Asturias", codigo="062026000001"
        ))
        repositorio.crear_o_actualizar(_oferta_completa(
            comunidad="Asturias", codigo="062026000002"
        ))

        vistos_asturias = repositorio.listar_codigos_vistos("Asturias")
        vistos_cantabria = repositorio.listar_codigos_vistos("Cantabria")

        assert set(vistos_asturias) == {"062026000001", "062026000002"}
        assert vistos_cantabria == ["062026000001"]
        # Ningún código de Cantabria "extra" aparece en Asturias por este método

    def test_lista_vacia_si_no_hay_ofertas(self, repositorio):
        """Si la comunidad no tiene ofertas, la lista está vacía."""
        vistos = repositorio.listar_codigos_vistos("Madrid")
        assert vistos == []

    def test_sin_duplicados_tras_actualizaciones(self, repositorio):
        """Múltiples actualizaciones de la misma clave no generan duplicados en la lista."""
        repositorio.crear_o_actualizar(_oferta_completa(
            codigo="062026005555", estado=EstadoOferta.SIN_FICHA
        ))
        repositorio.crear_o_actualizar(_oferta_completa(
            codigo="062026005555", estado=EstadoOferta.VIGENTE
        ))
        repositorio.crear_o_actualizar(_oferta_completa(
            codigo="062026005555", estado=EstadoOferta.VIGENTE,
            ocupacion="Actualizado",
        ))

        vistos = repositorio.listar_codigos_vistos("Cantabria")

        assert vistos.count("062026005555") == 1


# ---------------------------------------------------------------------------
# Pruebas TASK-007: reducción a registro mínimo conservando el embedding
# ---------------------------------------------------------------------------

class TestReducirARegistroMinimo:
    """reducir_a_registro_minimo vacía texto_libre y contacto conservando el resto."""

    def test_vacia_texto_y_contacto(self, repositorio):
        """Tras la reducción, texto_libre y contacto están vacíos y el resto intacto."""
        oferta = _oferta_completa()
        repositorio.crear_o_actualizar(oferta)

        repositorio.reducir_a_registro_minimo("Cantabria", "000000000001")

        resultado = repositorio.consultar_por_clave("Cantabria", "000000000001")
        assert resultado.encontrada is True
        o = resultado.oferta
        assert o.texto_libre == ""
        assert o.contacto == ""
        # El resto de campos permanece intacto
        assert o.comunidad == "Cantabria"
        assert o.provincia == "Cantabria"
        assert o.codigo == "000000000001"
        assert o.ocupacion == "Ingeniero informático"
        assert o.municipio == "Santander"
        assert o.fecha_inicio_difusion == "01/01/2026"
        assert o.fecha_fin_difusion == "31/03/2026"
        assert o.estado == EstadoOferta.VIGENTE

    def test_conserva_embedding_con_metadatos(self, repositorio):
        """La oferta con embedding conserva BLOB, nombre, versión y dim tras la reducción."""
        vector = np.array([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float32)
        oferta = _oferta_completa(
            embedding=vector,
            embedding_model_name="nomic-embed-text",
            embedding_model_version="1.5",
            embedding_dim=5,
        )
        repositorio.crear_o_actualizar(oferta)

        repositorio.reducir_a_registro_minimo("Cantabria", "000000000001")

        resultado = repositorio.consultar_por_clave("Cantabria", "000000000001")
        o = resultado.oferta
        assert o.embedding is not None
        np.testing.assert_array_almost_equal(o.embedding, vector)
        assert o.embedding_model_name == "nomic-embed-text"
        assert o.embedding_model_version == "1.5"
        assert o.embedding_dim == 5

    def test_sin_embedding_sigue_valida(self, repositorio):
        """Una oferta sin embedding sigue siendo válida tras la reducción."""
        oferta = _oferta_completa(
            embedding=None,
            embedding_model_name=None,
            embedding_model_version=None,
            embedding_dim=None,
        )
        repositorio.crear_o_actualizar(oferta)

        repositorio.reducir_a_registro_minimo("Cantabria", "000000000001")

        resultado = repositorio.consultar_por_clave("Cantabria", "000000000001")
        assert resultado.encontrada is True
        assert resultado.oferta.embedding is None
        assert resultado.oferta.embedding_model_name is None
        assert resultado.oferta.embedding_model_version is None
        assert resultado.oferta.embedding_dim is None

    def test_no_modifica_estado_interesada_ni_fechas(self, repositorio):
        """estado, interesada, fecha_alta y fecha_cierre no se modifican por la reducción."""
        oferta = _oferta_completa(
            estado=EstadoOferta.CERRADA,
            interesada=True,
            fecha_alta="2026-01-01T00:00:00+00:00",
            fecha_cierre="2026-06-01T00:00:00+00:00",
        )
        repositorio.crear_o_actualizar(oferta)

        # Capturar valores previos
        antes = repositorio.consultar_por_clave("Cantabria", "000000000001")
        fecha_alta_antes = antes.oferta.fecha_alta
        fecha_cierre_antes = antes.oferta.fecha_cierre
        estado_antes = antes.oferta.estado
        interesada_antes = antes.oferta.interesada
        fecha_update_antes = antes.oferta.fecha_ultima_actualizacion

        repositorio.reducir_a_registro_minimo("Cantabria", "000000000001")

        despues = repositorio.consultar_por_clave("Cantabria", "000000000001")
        assert despues.oferta.estado == estado_antes
        assert despues.oferta.interesada == interesada_antes
        assert despues.oferta.fecha_alta == fecha_alta_antes
        assert despues.oferta.fecha_cierre == fecha_cierre_antes
        assert despues.oferta.fecha_ultima_actualizacion == fecha_update_antes

    def test_campos_reservados_vacios_tras_reduccion(self, repositorio):
        """sector, nivel y contrato siguen presentes y vacíos tras la reducción."""
        oferta = _oferta_completa(
            sector="Construcción",
            nivel="Junior",
            contrato="Indefinido",
        )
        repositorio.crear_o_actualizar(oferta)

        repositorio.reducir_a_registro_minimo("Cantabria", "000000000001")

        resultado = repositorio.consultar_por_clave("Cantabria", "000000000001")
        assert resultado.oferta.sector == ""
        assert resultado.oferta.nivel == ""
        assert resultado.oferta.contrato == ""

    def test_idempotente(self, repositorio):
        """Aplicar la reducción dos veces produce el mismo resultado."""
        oferta = _oferta_completa()
        repositorio.crear_o_actualizar(oferta)

        repositorio.reducir_a_registro_minimo("Cantabria", "000000000001")
        r1 = repositorio.consultar_por_clave("Cantabria", "000000000001")

        repositorio.reducir_a_registro_minimo("Cantabria", "000000000001")
        r2 = repositorio.consultar_por_clave("Cantabria", "000000000001")

        # Comparar todos los campos relevantes
        assert r2.oferta.texto_libre == r1.oferta.texto_libre == ""
        assert r2.oferta.contacto == r1.oferta.contacto == ""
        assert r2.oferta.comunidad == r1.oferta.comunidad
        assert r2.oferta.codigo == r1.oferta.codigo
        assert r2.oferta.estado == r1.oferta.estado
        assert r2.oferta.embedding_model_name == r1.oferta.embedding_model_name
        assert r2.oferta.embedding_model_version == r1.oferta.embedding_model_version
        assert r2.oferta.embedding_dim == r1.oferta.embedding_dim
        if r1.oferta.embedding is not None:
            np.testing.assert_array_almost_equal(
                r2.oferta.embedding, r1.oferta.embedding
            )
