"""Pruebas de integración end-to-end de la persistencia (TASK-014).

Verifica de extremo a extremo la comunicación entre todos los componentes:
- Aplicación FastAPI con TestClient
- Conexión SQLite con WAL
- Migraciones
- Repositorio de ofertas
- Importador de seen_codes.json
- Cliente del buscador (simulado)
- Tarea de ingesta (ciclo manual)
- Tarea de purga (ejecución manual)
- Endpoints de persistencia

Escenarios cubiertos:
1. seen_codes.json de 3 códigos + pasada con 1 existente + 1 nueva → 4 registros
2. Consulta por clave natural devuelve ficha completa con reservados vacíos
3. Listado de vigentes devuelve solo vigentes
4. Códigos vistos devuelve los 4
5. Idempotencia: mismo timestamp no crea filas nuevas
6. Buscador caído (error HTTP) no cambia la BD
7. ultima_pasada nula no cambia la BD
8. Cierre + purga conserva embedding y vacía texto/contacto
9. seen_codes.json conserva su contenido original
10. Códigos con ceros iniciales (12 dígitos)
11. Fechas en formato dd/mm/aaaa
12. BD es un único fichero SQLite en modo WAL sin servidor ni tabla vectorial
"""

import importlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from source.api.persistencia.client import (
    ClienteBuscador,
    EstadoBuscador,
    ResultadoConsultaEstado,
    UltimaPasada,
)
from source.api.persistencia.connection import transaccion
from source.api.persistencia.repository import EstadoOferta, Oferta


# ---------------------------------------------------------------------------
# Códigos de prueba (12 dígitos con ceros iniciales, NFR-003)
# ---------------------------------------------------------------------------

CODIGO_EXISTENTE_1 = "000000000001"  # en seen_codes.json Y en la pasada
CODIGO_EXISTENTE_2 = "000000000002"  # solo en seen_codes.json
CODIGO_EXISTENTE_3 = "000000000003"  # solo en seen_codes.json
CODIGO_NUEVO = "000000000004"        # solo en la pasada (nueva oferta)

TIMESTAMP_PASADA_1 = "2026-01-15T10:00:00+00:00"


# ---------------------------------------------------------------------------
# Helpers para construir respuestas simuladas
# ---------------------------------------------------------------------------

def _construir_estado_con_pasada(
    timestamp: str,
    ofertas_nuevas: list[dict],
    comunidad: str = "Cantabria",
) -> ResultadoConsultaEstado:
    """Construye un ResultadoConsultaEstado con una última pasada."""
    return ResultadoConsultaEstado(
        estado=EstadoBuscador(
            in_progress=False,
            progreso=None,
            ultima_pasada=UltimaPasada(
                timestamp=timestamp,
                comunidad=comunidad,
                total_listado=len(ofertas_nuevas),
                error_global="",
                errores_por_oferta=[],
                ofertas_nuevas=ofertas_nuevas,
            ),
        ),
    )


def _construir_estado_sin_pasada() -> ResultadoConsultaEstado:
    """Construye un ResultadoConsultaEstado sin última pasada (ALT-002)."""
    return ResultadoConsultaEstado(
        estado=EstadoBuscador(
            in_progress=False,
            progreso=None,
            ultima_pasada=None,
        ),
    )


def _construir_estado_error_http() -> ResultadoConsultaEstado:
    """Construye un ResultadoConsultaEstado con error (ALT-001)."""
    return ResultadoConsultaEstado(
        estado=None,
        error="Error HTTP 500 al consultar el estado del buscador.",
    )


def _ofertas_pasada_1() -> list[dict]:
    """Ofertas de la primera pasada simulada.

    Incluye:
    - CODIGO_EXISTENTE_1 (ya visto en seen_codes.json → se completa a vigente)
    - CODIGO_NUEVO (totalmente nueva)
    Las fechas están en formato dd/mm/aaaa (NFR-004).
    """
    return [
        {
            "comunidad": "Cantabria",
            "numero_oferta": CODIGO_EXISTENTE_1,
            "provincia": "Cantabria",
            "ocupacion": "Ingeniero de sistemas",
            "municipio": "Santander",
            "fecha_inicio_difusion": "15/01/2026",
            "fecha_fin_difusion": "15/02/2026",
            "texto_libre": "Se busca ingeniero con experiencia en Python.",
            "contacto": "rrhh@empresa.com",
        },
        {
            "comunidad": "Cantabria",
            "numero_oferta": CODIGO_NUEVO,
            "provincia": "Cantabria",
            "ocupacion": "Analista de datos",
            "municipio": "Torrelavega",
            "fecha_inicio_difusion": "15/01/2026",
            "fecha_fin_difusion": "28/02/2026",
            "texto_libre": "Analista para proyecto de datos.",
            "contacto": "datos@empresa.com",
        },
    ]


# ---------------------------------------------------------------------------
# Configuración del entorno temporal
# ---------------------------------------------------------------------------

def _crear_entorno(tmp_path: Path) -> dict:
    """Crea ficheros de configuración y datos temporales."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    ruta_bd = str(data_dir / "test_integration.db")

    # seen_codes.json con 3 códigos (NFR-003: 12 dígitos con ceros iniciales)
    seen_codes_path = data_dir / "seen_codes.json"
    codigos_vistos = [CODIGO_EXISTENTE_1, CODIGO_EXISTENTE_2, CODIGO_EXISTENTE_3]
    contenido_json = json.dumps(codigos_vistos, ensure_ascii=False)
    seen_codes_path.write_text(contenido_json, encoding="utf-8")

    # Conservar el contenido original para verificar que no cambia (REQ-018)
    contenido_original = seen_codes_path.read_text(encoding="utf-8")

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
        "seen_codes_path": seen_codes_path,
        "contenido_original": contenido_original,
    }


def _aplicar_parches(monkeypatch, entorno, estado_mock):
    """Aplica todos los monkeypatches necesarios para la integración."""
    # Parchear configuración del buscador
    from source.api.buscador.models import ConfigBuscador

    config_buscador = ConfigBuscador(
        ruta_seen_codes=str(entorno["seen_codes_path"]),
    )
    monkeypatch.setattr(
        "source.api.buscador.config.cargar_configuracion",
        lambda: config_buscador,
    )

    # Parchear ruta de configuración de persistencia
    monkeypatch.setattr(
        "source.api.persistencia.config.DEFAULT_CONFIG_PATH",
        Path(str(entorno["tmp_path"] / "config" / "persistencia.yaml")),
    )

    # Evitar que el Scheduler del buscador arranque hilos reales
    from source.api.buscador.scheduler import Scheduler

    monkeypatch.setattr(Scheduler, "iniciar", lambda self: None)
    monkeypatch.setattr(Scheduler, "detener", lambda self: None)

    # Evitar que la tarea de integridad descargue el PDF real o purgue data/pdfs:
    # al arrancar puede adelantar la comprobación del día y tocar el disco real.
    from source.api.integridad.task import TareaIntegridad
    monkeypatch.setattr(TareaIntegridad, "iniciar", lambda self: None)

    # Parchear ClienteBuscador.consultar_estado con respuesta controlable
    def mock_consultar_estado(self_cliente):
        return estado_mock["respuesta"]

    monkeypatch.setattr(
        ClienteBuscador, "consultar_estado", mock_consultar_estado
    )


# ---------------------------------------------------------------------------
# Prueba de integración end-to-end
# ---------------------------------------------------------------------------


def test_integracion_completa_persistencia(tmp_path, monkeypatch):
    """Verificación de extremo a extremo de la persistencia (TASK-014).

    Ejecuta todos los escenarios de forma secuencial:
    1. Arranque con importación de seen_codes.json
    2. Pasada nueva con 1 existente + 1 nueva
    3. Consulta y listado por endpoints
    4. Idempotencia
    5. Buscador caído y ultima_pasada nula
    6. Cierre + purga con embedding
    7. Integridad de seen_codes.json
    8. Códigos con ceros iniciales y fechas dd/mm/aaaa
    9. BD SQLite WAL sin servidor ni vectores
    """
    # ==================================================================
    # SETUP
    # ==================================================================
    entorno = _crear_entorno(tmp_path)

    # Contenedor mutable para controlar las respuestas del ClienteBuscador
    estado_mock = {"respuesta": _construir_estado_sin_pasada()}

    _aplicar_parches(monkeypatch, entorno, estado_mock)

    # Recargar main para que tome los parches
    import source.api.main as main_mod

    importlib.reload(main_mod)

    with TestClient(main_mod.app) as client:
        repo = main_mod.app_state["repositorio"]
        conexion = main_mod.app_state["conexion_persistencia"]
        tarea_ingesta = main_mod.app_state["tarea_ingesta"]
        tarea_purga = main_mod.app_state["tarea_purga"]

        # ==============================================================
        # 1. Importación inicial de códigos vistos
        # ==============================================================
        for codigo in [CODIGO_EXISTENTE_1, CODIGO_EXISTENTE_2, CODIGO_EXISTENTE_3]:
            resultado = repo.consultar_por_clave("Cantabria", codigo)
            assert resultado.encontrada, (
                f"El código {codigo} debería existir tras la importación"
            )
            assert resultado.oferta is not None
            assert resultado.oferta.estado == EstadoOferta.SIN_FICHA
            # Campos reservados vacíos (SUP-011)
            assert resultado.oferta.sector == ""
            assert resultado.oferta.nivel == ""
            assert resultado.oferta.contrato == ""

        # ==============================================================
        # 2. Pasada nueva: 1 existente + 1 nueva → 4 códigos
        # ==============================================================
        estado_mock["respuesta"] = _construir_estado_con_pasada(
            timestamp=TIMESTAMP_PASADA_1,
            ofertas_nuevas=_ofertas_pasada_1(),
        )

        resultado_ciclo = tarea_ingesta._ejecutar_ciclo()
        assert resultado_ciclo.ejecutado is True
        assert resultado_ciclo.ofertas_procesadas == 2

        # CODIGO_EXISTENTE_1 pasó de sin_ficha a vigente
        resultado = repo.consultar_por_clave("Cantabria", CODIGO_EXISTENTE_1)
        assert resultado.encontrada
        assert resultado.oferta.estado == EstadoOferta.VIGENTE
        assert resultado.oferta.ocupacion == "Ingeniero de sistemas"
        assert resultado.oferta.texto_libre == (
            "Se busca ingeniero con experiencia en Python."
        )

        # CODIGO_NUEVO fue creado como vigente
        resultado = repo.consultar_por_clave("Cantabria", CODIGO_NUEVO)
        assert resultado.encontrada
        assert resultado.oferta.estado == EstadoOferta.VIGENTE
        assert resultado.oferta.ocupacion == "Analista de datos"

        # Los otros 2 códigos siguen en sin_ficha
        for codigo in [CODIGO_EXISTENTE_2, CODIGO_EXISTENTE_3]:
            resultado = repo.consultar_por_clave("Cantabria", codigo)
            assert resultado.encontrada
            assert resultado.oferta.estado == EstadoOferta.SIN_FICHA

        # ==============================================================
        # 3. sector, nivel y contrato vacíos tras la ingesta (DEC-009)
        # ==============================================================
        for codigo in [CODIGO_EXISTENTE_1, CODIGO_NUEVO]:
            resultado = repo.consultar_por_clave("Cantabria", codigo)
            assert resultado.encontrada
            assert resultado.oferta.sector == "", (
                f"sector debe estar vacío para {codigo}"
            )
            assert resultado.oferta.nivel == "", (
                f"nivel debe estar vacío para {codigo}"
            )
            assert resultado.oferta.contrato == "", (
                f"contrato debe estar vacío para {codigo}"
            )

        # ==============================================================
        # 4. Endpoint de consulta por clave natural (ficha completa)
        # ==============================================================
        respuesta = client.get(
            f"/persistencia/ofertas/Cantabria/{CODIGO_EXISTENTE_1}"
        )
        assert respuesta.status_code == 200
        datos = respuesta.json()

        assert datos["comunidad"] == "Cantabria"
        assert datos["codigo"] == CODIGO_EXISTENTE_1
        assert datos["estado"] == EstadoOferta.VIGENTE
        assert datos["provincia"] == "Cantabria"
        assert datos["ocupacion"] == "Ingeniero de sistemas"
        assert datos["municipio"] == "Santander"
        assert datos["texto_libre"] == (
            "Se busca ingeniero con experiencia en Python."
        )
        assert datos["contacto"] == "rrhh@empresa.com"
        # Reservados vacíos
        assert datos["sector"] == ""
        assert datos["nivel"] == ""
        assert datos["contrato"] == ""

        # ==============================================================
        # 5. Endpoint de listado de vigentes
        # ==============================================================
        respuesta = client.get("/persistencia/ofertas/vigentes")
        assert respuesta.status_code == 200
        vigentes = respuesta.json()

        codigos_vigentes = [o["codigo"] for o in vigentes]
        assert CODIGO_EXISTENTE_1 in codigos_vigentes
        assert CODIGO_NUEVO in codigos_vigentes
        # Los sin_ficha NO deben aparecer
        assert CODIGO_EXISTENTE_2 not in codigos_vigentes
        assert CODIGO_EXISTENTE_3 not in codigos_vigentes
        assert len(vigentes) == 2

        # ==============================================================
        # 6. Endpoint de códigos vistos (4 códigos)
        # ==============================================================
        respuesta = client.get("/persistencia/codigos-vistos/Cantabria")
        assert respuesta.status_code == 200
        datos_respuesta = respuesta.json()

        assert datos_respuesta["comunidad"] == "Cantabria"
        codigos = datos_respuesta["codigos"]
        assert len(codigos) == 4
        assert CODIGO_EXISTENTE_1 in codigos
        assert CODIGO_EXISTENTE_2 in codigos
        assert CODIGO_EXISTENTE_3 in codigos
        assert CODIGO_NUEVO in codigos

        # ==============================================================
        # 7. Idempotencia: mismo timestamp no crea filas nuevas
        # ==============================================================
        total_antes = conexion.execute(
            "SELECT COUNT(*) FROM ofertas"
        ).fetchone()[0]

        estado_mock["respuesta"] = _construir_estado_con_pasada(
            timestamp=TIMESTAMP_PASADA_1,
            ofertas_nuevas=_ofertas_pasada_1(),
        )

        resultado_ciclo = tarea_ingesta._ejecutar_ciclo()
        assert resultado_ciclo.ejecutado is False
        assert "ya_importado" in resultado_ciclo.motivo_omision

        total_despues = conexion.execute(
            "SELECT COUNT(*) FROM ofertas"
        ).fetchone()[0]
        assert total_despues == total_antes

        # ==============================================================
        # 8. Buscador caído (error HTTP) no cambia la BD (ALT-001)
        # ==============================================================
        total_antes = conexion.execute(
            "SELECT COUNT(*) FROM ofertas"
        ).fetchone()[0]

        estado_mock["respuesta"] = _construir_estado_error_http()

        resultado_ciclo = tarea_ingesta._ejecutar_ciclo()
        assert resultado_ciclo.ejecutado is False

        total_despues = conexion.execute(
            "SELECT COUNT(*) FROM ofertas"
        ).fetchone()[0]
        assert total_despues == total_antes

        # ==============================================================
        # 9. ultima_pasada nula no cambia la BD (ALT-002)
        # ==============================================================
        estado_mock["respuesta"] = _construir_estado_sin_pasada()

        resultado_ciclo = tarea_ingesta._ejecutar_ciclo()
        assert resultado_ciclo.ejecutado is False
        assert resultado_ciclo.motivo_omision == "ultima_pasada_nula"

        total_despues = conexion.execute(
            "SELECT COUNT(*) FROM ofertas"
        ).fetchone()[0]
        assert total_despues == total_antes

        # ==============================================================
        # 10. Cierre + purga conserva embedding (REQ-005, REQ-006, ALT-006)
        # ==============================================================
        # Crear embedding de prueba (128 floats float32)
        embedding = np.arange(128, dtype=np.float32)

        # Crear oferta con todos los campos incluyendo embedding
        oferta_completa = Oferta(
            comunidad="Cantabria",
            codigo="000000000010",
            estado=EstadoOferta.CERRADA,
            provincia="Cantabria",
            ocupacion="Técnico de mantenimiento",
            municipio="Castro-Urdiales",
            fecha_inicio_difusion="01/01/2026",
            fecha_fin_difusion="31/01/2026",
            texto_libre="Texto completo de la oferta.",
            contacto="contacto@test.com",
            embedding=embedding,
            embedding_model_name="nomic-embed-text",
            embedding_model_version="v1.0",
            embedding_dim=128,
        )
        repo.crear_o_actualizar(oferta_completa)

        # Simular cierre hace 30 días (más que los 7 días de retención)
        fecha_cierre_antigua = (
            datetime.now(timezone.utc) - timedelta(days=30)
        ).isoformat()

        with transaccion(conexion):
            conexion.execute(
                "UPDATE ofertas SET fecha_cierre = ? "
                "WHERE comunidad = ? AND codigo = ?",
                (fecha_cierre_antigua, "Cantabria", "000000000010"),
            )

        # Ejecutar la purga manualmente
        tarea_purga._purgar()

        # Verificar que texto_libre y contacto están vacíos
        resultado = repo.consultar_por_clave("Cantabria", "000000000010")
        assert resultado.encontrada
        oferta = resultado.oferta
        # reducir_a_registro_minimo pone NULL; consultar_por_clave convierte a ""
        assert oferta.texto_libre == "" or oferta.texto_libre is None
        assert oferta.contacto == "" or oferta.contacto is None

        # Verificar que el embedding se conserva
        assert oferta.embedding is not None
        assert len(oferta.embedding) == 128
        np.testing.assert_array_almost_equal(oferta.embedding, embedding)
        assert oferta.embedding_model_name == "nomic-embed-text"
        assert oferta.embedding_model_version == "v1.0"
        assert oferta.embedding_dim == 128

        # ==============================================================
        # 11. seen_codes.json conserva su contenido original (REQ-018)
        # ==============================================================
        contenido_actual = entorno["seen_codes_path"].read_text(encoding="utf-8")
        assert contenido_actual == entorno["contenido_original"]

        # ==============================================================
        # 12. Códigos con ceros iniciales (12 dígitos, NFR-003)
        # ==============================================================
        for codigo in [
            CODIGO_EXISTENTE_1, CODIGO_EXISTENTE_2,
            CODIGO_EXISTENTE_3, CODIGO_NUEVO,
        ]:
            resultado = repo.consultar_por_clave("Cantabria", codigo)
            assert resultado.encontrada
            assert len(resultado.oferta.codigo) == 12
            assert resultado.oferta.codigo == codigo
            assert resultado.oferta.codigo.startswith("0")

        # ==============================================================
        # 13. Fechas en formato dd/mm/aaaa (NFR-004)
        # ==============================================================
        respuesta = client.get(
            f"/persistencia/ofertas/Cantabria/{CODIGO_EXISTENTE_1}"
        )
        assert respuesta.status_code == 200
        datos = respuesta.json()

        assert datos["fecha_inicio_difusion"] == "15/01/2026"
        assert datos["fecha_fin_difusion"] == "15/02/2026"

        # ==============================================================
        # 14. BD SQLite WAL sin servidor ni tabla vectorial
        #     (NFR-001, NFR-002, NFR-005)
        # ==============================================================
        ruta_bd = Path(entorno["ruta_bd"])
        assert ruta_bd.exists()
        assert ruta_bd.is_file()

        # journal_mode = WAL
        modo = conexion.execute("PRAGMA journal_mode").fetchone()[0]
        assert modo == "wal"

        # No hay tablas de vectores ni extensiones vectoriales
        tablas = conexion.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        nombres_tablas = {t[0] for t in tablas}
        assert "ofertas" in nombres_tablas
        assert "ingesta_log" in nombres_tablas
        assert "schema_version" in nombres_tablas
        for nombre in nombres_tablas:
            assert "vector" not in nombre.lower()
            assert "vss" not in nombre.lower()

        # No hay columnas de tipo vector
        columnas_ofertas = conexion.execute(
            "PRAGMA table_info(ofertas)"
        ).fetchall()
        tipos_columnas = {col[2].upper() for col in columnas_ofertas}
        assert "VECTOR" not in tipos_columnas

        # busy_timeout > 0
        timeout = conexion.execute("PRAGMA busy_timeout").fetchone()[0]
        assert timeout > 0
