"""Pruebas del importador idempotente de códigos vistos (TASK-008)."""

import json
import os
import time

import pytest

from source.api.persistencia.connection import abrir_conexion
from source.api.persistencia.importer import (
    ResultadoImportacion,
    importar_codigos_vistos,
)
from source.api.persistencia.migrations import migrar
from source.api.persistencia.repository import (
    EstadoOferta,
    RepositorioOfertas,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ruta_db(tmp_path):
    """Devuelve la ruta de una BD temporal vacía."""
    return tmp_path / "test_importer.db"


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


def _generar_codigos(n: int, prefijo: str = "06") -> list[str]:
    """Genera n códigos de 12 dígitos con ceros iniciales."""
    return [f"{prefijo}{i:010d}" for i in range(1, n + 1)]


def _escribir_json(ruta, datos):
    """Escribe un JSON en la ruta dada."""
    ruta.write_text(json.dumps(datos), encoding="utf-8")


# ---------------------------------------------------------------------------
# Pruebas: importación básica
# ---------------------------------------------------------------------------

class TestImportacionBasica:
    """Importación de un JSON con 103 códigos."""

    def test_importa_103_codigos(self, conexion, tmp_path):
        """Con un JSON de 103 códigos, se crean 103 registros."""
        codigos = _generar_codigos(103)
        ruta_json = tmp_path / "seen_codes.json"
        _escribir_json(ruta_json, codigos)

        resultado = importar_codigos_vistos(conexion, ruta_json)

        assert resultado.importados == 103
        assert resultado.existentes == 0

    def test_todos_estado_sin_ficha(self, conexion, repositorio, tmp_path):
        """Cada registro importado tiene estado sin_ficha."""
        codigos = _generar_codigos(103)
        ruta_json = tmp_path / "seen_codes.json"
        _escribir_json(ruta_json, codigos)

        importar_codigos_vistos(conexion, ruta_json)

        for codigo in codigos:
            resultado = repositorio.consultar_por_clave("Cantabria", codigo)
            assert resultado.encontrada
            assert resultado.oferta.estado == EstadoOferta.SIN_FICHA

    def test_registros_con_campos_vacios(self, conexion, repositorio, tmp_path):
        """Cada registro tiene comunidad Cantabria y resto de campos vacíos."""
        codigos = _generar_codigos(5)
        ruta_json = tmp_path / "seen_codes.json"
        _escribir_json(ruta_json, codigos)

        importar_codigos_vistos(conexion, ruta_json)

        for codigo in codigos:
            resultado = repositorio.consultar_por_clave("Cantabria", codigo)
            assert resultado.encontrada
            oferta = resultado.oferta
            assert oferta.comunidad == "Cantabria"
            assert oferta.provincia == ""
            assert oferta.sector == ""
            assert oferta.nivel == ""
            assert oferta.contrato == ""
            assert oferta.fecha_inicio_difusion is None
            assert oferta.fecha_fin_difusion is None
            assert oferta.texto_libre == ""
            assert oferta.contacto == ""
            assert oferta.embedding is None


# ---------------------------------------------------------------------------
# Pruebas: códigos que no empiezan por 06
# ---------------------------------------------------------------------------

class TestCodigosNo06:
    """Los códigos que no empiezan por 06 también se importan como Cantabria."""

    def test_codigos_no_06_se_importan(self, conexion, repositorio, tmp_path):
        """Códigos con otro prefijo se importan con comunidad Cantabria."""
        codigos = [
            "072026000001",
            "082026000002",
            "092026000003",
            "102026000004",
            "992026000005",
        ]
        ruta_json = tmp_path / "seen_codes.json"
        _escribir_json(ruta_json, codigos)

        resultado = importar_codigos_vistos(conexion, ruta_json)

        assert resultado.importados == 5
        for codigo in codigos:
            resultado_consulta = repositorio.consultar_por_clave(
                "Cantabria", codigo
            )
            assert resultado_consulta.encontrada
            assert resultado_consulta.oferta.comunidad == "Cantabria"
            assert resultado_consulta.oferta.estado == EstadoOferta.SIN_FICHA


# ---------------------------------------------------------------------------
# Pruebas: resultado de la importación
# ---------------------------------------------------------------------------

class TestResultadoImportacion:
    """El resultado informa de importados y existentes."""

    def test_resultado_con_codigos_nuevos(self, conexion, tmp_path):
        """El resultado informa del número de importados y existentes."""
        codigos = _generar_codigos(50)
        ruta_json = tmp_path / "seen_codes.json"
        _escribir_json(ruta_json, codigos)

        resultado = importar_codigos_vistos(conexion, ruta_json)

        assert resultado.importados == 50
        assert resultado.existentes == 0

    def test_resultado_con_mezcla(self, conexion, repositorio, tmp_path):
        """Con códigos nuevos y existentes, el resultado refleja ambos."""
        # Importar primeros 20
        primeros = _generar_codigos(20)
        ruta_json = tmp_path / "seen_codes.json"
        _escribir_json(ruta_json, primeros)
        importar_codigos_vistos(conexion, ruta_json)

        # Ahora importar 50 códigos (20 ya existentes + 30 nuevos)
        todos = _generar_codigos(50)
        _escribir_json(ruta_json, todos)

        resultado = importar_codigos_vistos(conexion, ruta_json)

        assert resultado.importados == 30
        assert resultado.existentes == 20


# ---------------------------------------------------------------------------
# Pruebas: idempotencia
# ---------------------------------------------------------------------------

class TestIdempotencia:
    """Repetir la importación no crea duplicados (REQ-014)."""

    def test_repetir_importacion_cero_importados(self, conexion, tmp_path):
        """Repetir con el mismo JSON → 0 importados, N existentes."""
        codigos = _generar_codigos(30)
        ruta_json = tmp_path / "seen_codes.json"
        _escribir_json(ruta_json, codigos)

        # Primera importación
        resultado1 = importar_codigos_vistos(conexion, ruta_json)
        assert resultado1.importados == 30

        # Segunda importación
        resultado2 = importar_codigos_vistos(conexion, ruta_json)
        assert resultado2.importados == 0
        assert resultado2.existentes == 30

    def test_repetir_no_crea_filas_nuevas(self, conexion, repositorio, tmp_path):
        """Repetir la importación no crea filas nuevas."""
        codigos = _generar_codigos(15)
        ruta_json = tmp_path / "seen_codes.json"
        _escribir_json(ruta_json, codigos)

        importar_codigos_vistos(conexion, ruta_json)
        importar_codigos_vistos(conexion, ruta_json)
        importar_codigos_vistos(conexion, ruta_json)

        # Verificar que hay exactamente 15 códigos
        codigos_vistos = repositorio.listar_codigos_vistos("Cantabria")
        assert len(codigos_vistos) == 15

    def test_codigo_nuevo_entre_dos_importaciones(self, conexion, repositorio, tmp_path):
        """Un JSON con un código nuevo entre dos importaciones solo crea ese."""
        # Primera importación con 10 códigos
        primeros = _generar_codigos(10)
        ruta_json = tmp_path / "seen_codes.json"
        _escribir_json(ruta_json, primeros)
        importar_codigos_vistos(conexion, ruta_json)

        # Segunda importación con 11 códigos (los 10 + 1 nuevo)
        codigo_nuevo = "062026999999"
        todos = primeros + [codigo_nuevo]
        _escribir_json(ruta_json, todos)

        resultado = importar_codigos_vistos(conexion, ruta_json)

        assert resultado.importados == 1
        assert resultado.existentes == 10

        # El nuevo existe
        resultado_consulta = repositorio.consultar_por_clave(
            "Cantabria", codigo_nuevo
        )
        assert resultado_consulta.encontrada


# ---------------------------------------------------------------------------
# Pruebas: conservación de ceros iniciales
# ---------------------------------------------------------------------------

class TestCerosIniciales:
    """Los códigos se conservan como texto de 12 dígitos con ceros iniciales."""

    def test_codigos_con_ceros_iniciales(self, conexion, repositorio, tmp_path):
        """Los códigos mantienen sus 12 dígitos con ceros a la izquierda."""
        codigos = [
            "060000000001",
            "060000000010",
            "062026000100",
        ]
        ruta_json = tmp_path / "seen_codes.json"
        _escribir_json(ruta_json, codigos)

        importar_codigos_vistos(conexion, ruta_json)

        for codigo in codigos:
            resultado = repositorio.consultar_por_clave("Cantabria", codigo)
            assert resultado.encontrada
            assert resultado.oferta.codigo == codigo
            assert len(resultado.oferta.codigo) == 12


# ---------------------------------------------------------------------------
# Pruebas: fichero ausente
# ---------------------------------------------------------------------------

class TestFicheroAusente:
    """Un fichero ausente se registra y la importación continúa (ALT-003)."""

    def test_fichero_ausente_no_falla(self, conexion, tmp_path):
        """Un fichero ausente devuelve 0 importados sin lanzar excepción."""
        ruta_inexistente = tmp_path / "no_existe.json"

        resultado = importar_codigos_vistos(conexion, ruta_inexistente)

        assert resultado.importados == 0
        assert resultado.existentes == 0

    def test_fichero_ausente_no_modifica_bd(self, conexion, repositorio, tmp_path):
        """Un fichero ausente no modifica la base de datos."""
        ruta_inexistente = tmp_path / "no_existe.json"

        importar_codigos_vistos(conexion, ruta_inexistente)

        codigos_vistos = repositorio.listar_codigos_vistos("Cantabria")
        assert len(codigos_vistos) == 0


# ---------------------------------------------------------------------------
# Pruebas: JSON inválido o no lista
# ---------------------------------------------------------------------------

class TestJsonInvalido:
    """JSON inválido o no lista se registra como error (ALT-003)."""

    def test_json_invalido_no_modifica_bd(self, conexion, repositorio, tmp_path):
        """Un JSON con sintaxis inválida no modifica la BD."""
        ruta_json = tmp_path / "seen_codes.json"
        ruta_json.write_text("{esto no es json válido", encoding="utf-8")

        resultado = importar_codigos_vistos(conexion, ruta_json)

        assert resultado.importados == 0
        assert resultado.existentes == 0

        codigos_vistos = repositorio.listar_codigos_vistos("Cantabria")
        assert len(codigos_vistos) == 0

    def test_no_es_lista_no_modifica_bd(self, conexion, repositorio, tmp_path):
        """Un JSON que no es lista (objeto) no modifica la BD."""
        ruta_json = tmp_path / "seen_codes.json"
        _escribir_json(ruta_json, {"codigos": ["062026000001"]})

        resultado = importar_codigos_vistos(conexion, ruta_json)

        assert resultado.importados == 0
        assert resultado.existentes == 0

        codigos_vistos = repositorio.listar_codigos_vistos("Cantabria")
        assert len(codigos_vistos) == 0

    def test_json_vacio_no_modifica_bd(self, conexion, repositorio, tmp_path):
        """Una lista vacía no modifica la BD."""
        ruta_json = tmp_path / "seen_codes.json"
        _escribir_json(ruta_json, [])

        resultado = importar_codigos_vistos(conexion, ruta_json)

        assert resultado.importados == 0
        assert resultado.existentes == 0


# ---------------------------------------------------------------------------
# Pruebas: el fichero no se modifica
# ---------------------------------------------------------------------------

class TestFicheroNoModificado:
    """El fichero JSON no se modifica ni se toca su marca de tiempo (SUP-013)."""

    def test_fichero_no_cambia_contenido(self, conexion, tmp_path):
        """El contenido del fichero JSON no cambia tras la importación."""
        codigos = _generar_codigos(5)
        ruta_json = tmp_path / "seen_codes.json"
        _escribir_json(ruta_json, codigos)

        contenido_antes = ruta_json.read_text(encoding="utf-8")

        importar_codigos_vistos(conexion, ruta_json)

        contenido_despues = ruta_json.read_text(encoding="utf-8")
        assert contenido_antes == contenido_despues

    def test_fichero_no_cambia_mtime(self, conexion, tmp_path):
        """La marca de tiempo del fichero no cambia tras la importación."""
        codigos = _generar_codigos(5)
        ruta_json = tmp_path / "seen_codes.json"
        _escribir_json(ruta_json, codigos)

        # Esperar un poco para asegurar que cualquier escritura cambiaría mtime
        time.sleep(0.1)
        mtime_antes = os.path.getmtime(ruta_json)

        importar_codigos_vistos(conexion, ruta_json)

        mtime_despues = os.path.getmtime(ruta_json)
        assert mtime_antes == mtime_despues
