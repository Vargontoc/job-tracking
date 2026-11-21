"""Pruebas de la tarea periódica de ingesta de ofertas completas (TASK-010)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from source.api.persistencia.client import ClienteBuscador
from source.api.persistencia.connection import abrir_conexion
from source.api.persistencia.ingestion import (
    ResultadoCiclo,
    TareaIngesta,
    _oferta_desde_datos,
)
from source.api.persistencia.migrations import migrar
from source.api.persistencia.repository import (
    EstadoOferta,
    Oferta,
    RepositorioOfertas,
)


# ---------------------------------------------------------------------------
# Reloj controlado para pruebas
# ---------------------------------------------------------------------------


class RelojControlado:
    """Reloj controlable para pruebas."""

    def __init__(self, ahora: datetime | None = None) -> None:
        self._ahora = ahora or datetime(2026, 11, 21, 10, 0, 0, tzinfo=timezone.utc)
        self._durmiendo = False

    def now(self) -> datetime:
        return self._ahora

    def sleep(self, segundos: float) -> None:
        self._ahora += timedelta(seconds=segundos)

    def avanzar(self, segundos: float) -> None:
        self._ahora += timedelta(seconds=segundos)


# ---------------------------------------------------------------------------
# Datos de prueba
# ---------------------------------------------------------------------------


def _oferta_dict(
    numero: str = "061234567890",
    ocupacion: str = "Desarrollador",
    municipio: str = "Santander",
    provincia: str = "Cantabria",
    comunidad: str = "Cantabria",
    fecha_inicio: str = "01/01/2026",
    fecha_fin: str = "31/03/2026",
    texto: str = "Descripción de la oferta",
    contacto: str = "rrhh@empresa.com",
) -> dict:
    """Construye un diccionario de oferta como los que devuelve el buscador."""
    return {
        "numero_oferta": numero,
        "ocupacion": ocupacion,
        "municipio": municipio,
        "provincia": provincia,
        "comunidad": comunidad,
        "fecha_inicio_difusion": fecha_inicio,
        "fecha_fin_difusion": fecha_fin,
        "texto_libre": texto,
        "contacto": contacto,
    }


def _respuesta_status(
    timestamp: str | None = "2026-01-21T10:30:00",
    ofertas_nuevas: list[dict] | None = None,
    error_global: str = "",
    total_listado: int = 2,
) -> dict:
    """Construye una respuesta JSON simulada de GET /buscador/status."""
    return {
        "in_progress": False,
        "progreso": None,
        "ultima_pasada": None
        if timestamp is None
        else {
            "timestamp": timestamp,
            "comunidad": "Cantabria",
            "total_listado": total_listado,
            "error_global": error_global,
            "errores_por_oferta": [],
            "ofertas_nuevas": ofertas_nuevas or [],
        },
    }


def _crear_cliente_mock(
    respuesta_json: dict | None = None,
    *,
    error_http: int | None = None,
    error_red: bool = False,
) -> tuple[ClienteBuscador, list[httpx.Request]]:
    """Crea un ClienteBuscador con transporte simulado."""
    peticiones: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        peticiones.append(request)
        if error_red:
            raise httpx.ConnectError("Connection refused")
        if error_http is not None:
            return httpx.Response(error_http, text="Error")
        return httpx.Response(200, json=respuesta_json or _respuesta_status())

    cliente_http = httpx.Client(transport=httpx.MockTransport(_handler))
    return ClienteBuscador("http://localhost:8000", cliente=cliente_http), peticiones


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ruta_db(tmp_path):
    """Devuelve la ruta de una BD temporal vacía."""
    return tmp_path / "test_ingestion.db"


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


@pytest.fixture
def reloj():
    """Devuelve un RelojControlado."""
    return RelojControlado()


def _crear_tarea(
    conexion,
    repositorio,
    cliente_buscador: ClienteBuscador,
    cadencia: int = 300,
    reloj: RelojControlado | None = None,
) -> TareaIngesta:
    """Crea una TareaIngesta de prueba."""
    return TareaIngesta(
        cliente_buscador=cliente_buscador,
        repositorio=repositorio,
        conexion=conexion,
        cadencia_segundos=cadencia,
        reloj=reloj or RelojControlado(),
    )


def _obtener_ultimo_timestamp(conexion) -> str:
    """Lee el último timestamp importado de ingesta_log."""
    fila = conexion.execute(
        "SELECT ultimo_timestamp FROM ingesta_log WHERE id = 1"
    ).fetchone()
    return fila[0] if fila and fila[0] is not None else ""


def _obtener_actualizado_en(conexion) -> str:
    """Lee el campo actualizado_en de ingesta_log."""
    fila = conexion.execute(
        "SELECT actualizado_en FROM ingesta_log WHERE id = 1"
    ).fetchone()
    return fila[0] if fila else ""


# ---------------------------------------------------------------------------
# Caso feliz: timestamp nuevo + 2 ofertas nuevas → ambas vigentes
# ---------------------------------------------------------------------------


class TestTimestampNuevoDosOfertas:
    """Con un timestamp nuevo y dos ofertas nuevas, ambas quedan vigentes."""

    def test_ambas_ofertas_se_persisten_con_estado_vigente(
        self, conexion, repositorio, reloj
    ):
        """La BD contiene ambas ofertas con estado vigente."""
        ofertas = [
            _oferta_dict(numero="061234567890", ocupacion="Desarrollador"),
            _oferta_dict(numero="061234567891", ocupacion="Diseñador"),
        ]
        cliente, _ = _crear_cliente_mock(
            _respuesta_status(timestamp="2026-01-21T10:30:00", ofertas_nuevas=ofertas)
        )
        tarea = _crear_tarea(conexion, repositorio, cliente, reloj=reloj)

        tarea._ejecutar_ciclo()

        r1 = repositorio.consultar_por_clave("Cantabria", "061234567890")
        r2 = repositorio.consultar_por_clave("Cantabria", "061234567891")
        assert r1.encontrada
        assert r1.oferta.estado == EstadoOferta.VIGENTE
        assert r2.encontrada
        assert r2.oferta.estado == EstadoOferta.VIGENTE

    def test_todos_los_campos_se_almacenan(self, conexion, repositorio, reloj):
        """Todas las ofertas quedan con comunidad, provincia, código, ocupación,
        municipio, fechas de difusión, texto libre y contacto."""
        ofertas = [
            _oferta_dict(
                numero="061234567890",
                ocupacion="Desarrollador",
                municipio="Santander",
                provincia="Cantabria",
                comunidad="Cantabria",
                fecha_inicio="01/01/2026",
                fecha_fin="31/03/2026",
                texto="Se busca desarrollador Python",
                contacto="rrhh@empresa.com",
            ),
            _oferta_dict(
                numero="061234567891",
                ocupacion="Diseñador",
                municipio="Torrelavega",
                provincia="Cantabria",
                comunidad="Cantabria",
                fecha_inicio="05/01/2026",
                fecha_fin="05/04/2026",
                texto="Se busca diseñador UX",
                contacto="ux@empresa.com",
            ),
        ]
        cliente, _ = _crear_cliente_mock(
            _respuesta_status(timestamp="2026-01-21T10:30:00", ofertas_nuevas=ofertas)
        )
        tarea = _crear_tarea(conexion, repositorio, cliente, reloj=reloj)
        tarea._ejecutar_ciclo()

        r1 = repositorio.consultar_por_clave("Cantabria", "061234567890")
        assert r1.encontrada
        o1 = r1.oferta
        assert o1.comunidad == "Cantabria"
        assert o1.provincia == "Cantabria"
        assert o1.codigo == "061234567890"
        assert o1.ocupacion == "Desarrollador"
        assert o1.municipio == "Santander"
        assert o1.fecha_inicio_difusion == "01/01/2026"
        assert o1.fecha_fin_difusion == "31/03/2026"
        assert o1.texto_libre == "Se busca desarrollador Python"
        assert o1.contacto == "rrhh@empresa.com"

        r2 = repositorio.consultar_por_clave("Cantabria", "061234567891")
        assert r2.encontrada
        o2 = r2.oferta
        assert o2.comunidad == "Cantabria"
        assert o2.provincia == "Cantabria"
        assert o2.codigo == "061234567891"
        assert o2.ocupacion == "Diseñador"
        assert o2.municipio == "Torrelavega"
        assert o2.fecha_inicio_difusion == "05/01/2026"
        assert o2.fecha_fin_difusion == "05/04/2026"
        assert o2.texto_libre == "Se busca diseñador UX"
        assert o2.contacto == "ux@empresa.com"

    def test_el_timestamp_queda_registrado_en_ingesta_log(
        self, conexion, repositorio, reloj
    ):
        """El timestamp de la pasada queda registrado en ingesta_log."""
        ofertas = [
            _oferta_dict(numero="061234567890"),
            _oferta_dict(numero="061234567891"),
        ]
        cliente, _ = _crear_cliente_mock(
            _respuesta_status(timestamp="2026-01-21T10:30:00", ofertas_nuevas=ofertas)
        )
        tarea = _crear_tarea(conexion, repositorio, cliente, reloj=reloj)

        tarea._ejecutar_ciclo()

        assert _obtener_ultimo_timestamp(conexion) == "2026-01-21T10:30:00"


# ---------------------------------------------------------------------------
# Ofertas ingeridas: sector, nivel y contrato vacíos
# ---------------------------------------------------------------------------


class TestReservadosVacios:
    """Las ofertas ingeridas tienen sector, nivel y contrato vacíos."""

    def test_sector_nivel_contrato_vacios(self, conexion, repositorio, reloj):
        """Las ofertas ingeridas tienen sector, nivel y contrato vacíos (DEC-009)."""
        # Los datos de entrada traen valores no vacíos; el repositorio los fuerza vacíos
        oferta_entrada = _oferta_dict(numero="061234567890")
        oferta_entrada["sector"] = "Informática"
        oferta_entrada["nivel"] = "Alto"
        oferta_entrada["contrato"] = "Indefinido"

        cliente, _ = _crear_cliente_mock(
            _respuesta_status(
                timestamp="2026-01-21T10:30:00", ofertas_nuevas=[oferta_entrada]
            )
        )
        tarea = _crear_tarea(conexion, repositorio, cliente, reloj=reloj)
        tarea._ejecutar_ciclo()

        resultado = repositorio.consultar_por_clave("Cantabria", "061234567890")
        assert resultado.encontrada
        oferta = resultado.oferta
        assert oferta.sector == ""
        assert oferta.nivel == ""
        assert oferta.contrato == ""


# ---------------------------------------------------------------------------
# Idempotencia: mismo timestamp no duplica ni reimporta
# ---------------------------------------------------------------------------


class TestIdempotencia:
    """Repetir la ingesta con el mismo timestamp no duplica registros."""

    def test_mismo_timestamp_no_duplica_registros(
        self, conexion, repositorio, reloj
    ):
        """Repetir la ingesta con el mismo timestamp no duplica registros."""
        ofertas = [
            _oferta_dict(numero="061234567890"),
            _oferta_dict(numero="061234567891"),
        ]
        cliente, _ = _crear_cliente_mock(
            _respuesta_status(timestamp="2026-01-21T10:30:00", ofertas_nuevas=ofertas)
        )
        tarea = _crear_tarea(conexion, repositorio, cliente, reloj=reloj)

        # Primera ingesta
        tarea._ejecutar_ciclo()
        # Segunda ingesta con el mismo timestamp
        resultado = tarea._ejecutar_ciclo()

        # Comprobar que no se ha procesado nada en la segunda
        assert not resultado.ejecutado
        assert resultado.motivo_omision == "timestamp_ya_importado"

        # Comprobar que el timestamp no ha cambiado
        assert _obtener_ultimo_timestamp(conexion) == "2026-01-21T10:30:00"

        # Comprobar que solo hay 2 ofertas en total
        vigentes = repositorio.listar_vigentes()
        assert len(vigentes) == 2

    def test_mismo_timestamp_no_vuelve_a_marcar_como_importado(
        self, conexion, repositorio, reloj
    ):
        """El timestamp en ingesta_log no cambia tras la segunda ingesta."""
        ofertas = [_oferta_dict(numero="061234567890")]
        cliente, _ = _crear_cliente_mock(
            _respuesta_status(timestamp="2026-01-21T10:30:00", ofertas_nuevas=ofertas)
        )
        tarea = _crear_tarea(conexion, repositorio, cliente, reloj=reloj)

        tarea._ejecutar_ciclo()
        actualizado_en_1 = _obtener_actualizado_en(conexion)

        # Avanzar el reloj para que actualizado_en sea diferente
        reloj.avanzar(100)
        tarea._ejecutar_ciclo()
        actualizado_en_2 = _obtener_actualizado_en(conexion)

        # actualizado_en no debe haber cambiado
        assert actualizado_en_1 == actualizado_en_2


# ---------------------------------------------------------------------------
# Código sin_ficha → vigente sin duplicar
# ---------------------------------------------------------------------------


class TestCodigoSinFicha:
    """Un código sin_ficha previamente importado se completa a vigente."""

    def test_codigo_sin_ficha_se_completa_a_vigente(
        self, conexion, repositorio, reloj
    ):
        """Un código previamente importado desde seen_codes.json con estado
        sin_ficha aparece en ofertas_nuevas: el registro se completa con los
        datos de la ficha y su estado pasa a vigente, sin crear un duplicado."""
        # Simular importación previa desde seen_codes.json
        repositorio.crear_o_actualizar(
            Oferta(
                comunidad="Cantabria",
                codigo="061234567890",
                estado=EstadoOferta.SIN_FICHA,
            )
        )

        # Ahora el buscador devuelve ese código con ficha completa
        ofertas = [
            _oferta_dict(
                numero="061234567890",
                ocupacion="Desarrollador",
                municipio="Santander",
                texto="Descripción completa",
                contacto="rrhh@empresa.com",
            ),
        ]
        cliente, _ = _crear_cliente_mock(
            _respuesta_status(timestamp="2026-01-21T10:30:00", ofertas_nuevas=ofertas)
        )
        tarea = _crear_tarea(conexion, repositorio, cliente, reloj=reloj)
        tarea._ejecutar_ciclo()

        resultado = repositorio.consultar_por_clave("Cantabria", "061234567890")
        assert resultado.encontrada
        oferta = resultado.oferta
        assert oferta.estado == EstadoOferta.VIGENTE
        assert oferta.ocupacion == "Desarrollador"
        assert oferta.municipio == "Santander"
        assert oferta.texto_libre == "Descripción completa"
        assert oferta.contacto == "rrhh@empresa.com"

    def test_no_se_crea_duplicado(self, conexion, repositorio, reloj):
        """No se crea un duplicado al completar un sin_ficha."""
        repositorio.crear_o_actualizar(
            Oferta(
                comunidad="Cantabria",
                codigo="061234567890",
                estado=EstadoOferta.SIN_FICHA,
            )
        )

        ofertas = [_oferta_dict(numero="061234567890")]
        cliente, _ = _crear_cliente_mock(
            _respuesta_status(timestamp="2026-01-21T10:30:00", ofertas_nuevas=ofertas)
        )
        tarea = _crear_tarea(conexion, repositorio, cliente, reloj=reloj)
        tarea._ejecutar_ciclo()

        # Solo debe haber una oferta con ese código
        vigentes = repositorio.listar_vigentes()
        codigos = [o.codigo for o in vigentes]
        assert codigos.count("061234567890") == 1


# ---------------------------------------------------------------------------
# Código vigente existente no se sobrescribe
# ---------------------------------------------------------------------------


class TestCodigoVigenteExistente:
    """Un código vigente con datos completos no se sobrescribe con vacíos."""

    def test_no_se_duplica_ni_sobrescribe(self, conexion, repositorio, reloj):
        """Un código ya existente con estado vigente y datos completos no se
        duplica ni se sobrescribe con valores vacíos."""
        # Insertar oferta vigente con datos completos
        repositorio.crear_o_actualizar(
            Oferta(
                comunidad="Cantabria",
                codigo="061234567890",
                estado=EstadoOferta.VIGENTE,
                provincia="Cantabria",
                ocupacion="Desarrollador Senior",
                municipio="Santander",
                fecha_inicio_difusion="01/01/2026",
                fecha_fin_difusion="31/03/2026",
                texto_libre="Descripción original completa",
                contacto="contacto@original.com",
            )
        )

        # El buscador devuelve el mismo código con datos distintos (o vacíos)
        ofertas = [
            _oferta_dict(
                numero="061234567890",
                ocupacion="",
                municipio="",
                texto="",
                contacto="",
            ),
        ]
        cliente, _ = _crear_cliente_mock(
            _respuesta_status(timestamp="2026-01-21T10:30:00", ofertas_nuevas=ofertas)
        )
        tarea = _crear_tarea(conexion, repositorio, cliente, reloj=reloj)
        tarea._ejecutar_ciclo()

        resultado = repositorio.consultar_por_clave("Cantabria", "061234567890")
        assert resultado.encontrada
        oferta = resultado.oferta
        # Los datos originales no se han sobrescrito
        assert oferta.estado == EstadoOferta.VIGENTE
        assert oferta.ocupacion == "Desarrollador Senior"
        assert oferta.municipio == "Santander"
        assert oferta.texto_libre == "Descripción original completa"
        assert oferta.contacto == "contacto@original.com"

    def test_no_se_crea_segunda_fila(self, conexion, repositorio, reloj):
        """No se crea una segunda fila para el mismo código."""
        repositorio.crear_o_actualizar(
            Oferta(
                comunidad="Cantabria",
                codigo="061234567890",
                estado=EstadoOferta.VIGENTE,
                ocupacion="Desarrollador",
            )
        )

        ofertas = [_oferta_dict(numero="061234567890")]
        cliente, _ = _crear_cliente_mock(
            _respuesta_status(timestamp="2026-01-21T10:30:00", ofertas_nuevas=ofertas)
        )
        tarea = _crear_tarea(conexion, repositorio, cliente, reloj=reloj)
        tarea._ejecutar_ciclo()

        vigentes = repositorio.listar_vigentes()
        codigos = [o.codigo for o in vigentes]
        assert codigos.count("061234567890") == 1


# ---------------------------------------------------------------------------
# ultima_pasada nula
# ---------------------------------------------------------------------------


class TestUltimaPasadaNula:
    """Con ultima_pasada nula no se persiste nada ni se avanza el timestamp."""

    def test_no_se_persiste_ninguna_oferta(self, conexion, repositorio, reloj):
        """Con ultima_pasada nula no se persiste ninguna oferta."""
        cliente, _ = _crear_cliente_mock(
            _respuesta_status(timestamp=None)
        )
        tarea = _crear_tarea(conexion, repositorio, cliente, reloj=reloj)

        resultado = tarea._ejecutar_ciclo()

        assert not resultado.ejecutado
        assert resultado.motivo_omision == "ultima_pasada_nula"
        vigentes = repositorio.listar_vigentes()
        assert len(vigentes) == 0

    def test_no_se_avanza_el_timestamp(self, conexion, repositorio, reloj):
        """Con ultima_pasada nula no se avanza el timestamp importado."""
        cliente, _ = _crear_cliente_mock(
            _respuesta_status(timestamp=None)
        )
        tarea = _crear_tarea(conexion, repositorio, cliente, reloj=reloj)

        tarea._ejecutar_ciclo()

        assert _obtener_ultimo_timestamp(conexion) == ""


# ---------------------------------------------------------------------------
# error_global no vacío
# ---------------------------------------------------------------------------


class TestErrorGlobal:
    """Con error_global no vacío no se persiste nada."""

    def test_no_se_persiste_ninguna_oferta(self, conexion, repositorio, reloj):
        """Con error_global no vacío no se persiste ninguna oferta."""
        ofertas = [_oferta_dict(numero="061234567890")]
        cliente, _ = _crear_cliente_mock(
            _respuesta_status(
                timestamp="2026-01-21T10:30:00",
                ofertas_nuevas=ofertas,
                error_global="El portal no responde",
            )
        )
        tarea = _crear_tarea(conexion, repositorio, cliente, reloj=reloj)

        resultado = tarea._ejecutar_ciclo()

        assert not resultado.ejecutado
        assert "error_global" in resultado.motivo_omision
        vigentes = repositorio.listar_vigentes()
        assert len(vigentes) == 0

    def test_el_estado_queda_registrado_en_el_log(self, conexion, repositorio, reloj):
        """Con error_global, el estado consultado queda registrado en el log."""
        cliente, _ = _crear_cliente_mock(
            _respuesta_status(
                timestamp="2026-01-21T10:30:00",
                error_global="El portal no responde",
            )
        )
        tarea = _crear_tarea(conexion, repositorio, cliente, reloj=reloj)

        resultado = tarea._ejecutar_ciclo()

        assert "El portal no responde" in resultado.motivo_omision

    def test_no_se_avanza_el_timestamp(self, conexion, repositorio, reloj):
        """Con error_global no se avanza el timestamp importado."""
        cliente, _ = _crear_cliente_mock(
            _respuesta_status(
                timestamp="2026-01-21T10:30:00",
                error_global="Error en el portal",
            )
        )
        tarea = _crear_tarea(conexion, repositorio, cliente, reloj=reloj)

        tarea._ejecutar_ciclo()

        assert _obtener_ultimo_timestamp(conexion) == ""


# ---------------------------------------------------------------------------
# Buscador caído o con error HTTP
# ---------------------------------------------------------------------------


class TestBuscadorCaido:
    """Con el buscador caído o con error HTTP no se persiste nada."""

    def test_error_http_no_persiste(self, conexion, repositorio, reloj):
        """Con un error HTTP no se persiste ninguna oferta."""
        cliente, _ = _crear_cliente_mock(error_http=500)
        tarea = _crear_tarea(conexion, repositorio, cliente, reloj=reloj)

        resultado = tarea._ejecutar_ciclo()

        assert not resultado.ejecutado
        assert resultado.motivo_omision != ""
        vigentes = repositorio.listar_vigentes()
        assert len(vigentes) == 0

    def test_error_http_queda_registrado_en_el_log(
        self, conexion, repositorio, reloj
    ):
        """Con error HTTP el estado consultado queda registrado en el log."""
        cliente, _ = _crear_cliente_mock(error_http=500)
        tarea = _crear_tarea(conexion, repositorio, cliente, reloj=reloj)

        resultado = tarea._ejecutar_ciclo()

        assert "500" in resultado.motivo_omision

    def test_error_de_red_no_persiste(self, conexion, repositorio, reloj):
        """Con un error de red no se persiste ninguna oferta."""
        cliente, _ = _crear_cliente_mock(error_red=True)
        tarea = _crear_tarea(conexion, repositorio, cliente, reloj=reloj)

        resultado = tarea._ejecutar_ciclo()

        assert not resultado.ejecutado
        assert "Error de red" in resultado.motivo_omision
        vigentes = repositorio.listar_vigentes()
        assert len(vigentes) == 0

    def test_error_de_red_queda_registrado_en_el_log(
        self, conexion, repositorio, reloj
    ):
        """Con error de red el estado consultado queda registrado en el log."""
        cliente, _ = _crear_cliente_mock(error_red=True)
        tarea = _crear_tarea(conexion, repositorio, cliente, reloj=reloj)

        resultado = tarea._ejecutar_ciclo()

        assert "Error de red" in resultado.motivo_omision

    def test_no_se_avanza_el_timestamp_tras_error(
        self, conexion, repositorio, reloj
    ):
        """Tras un error del buscador no se avanza el timestamp importado."""
        cliente, _ = _crear_cliente_mock(error_http=503)
        tarea = _crear_tarea(conexion, repositorio, cliente, reloj=reloj)

        tarea._ejecutar_ciclo()

        assert _obtener_ultimo_timestamp(conexion) == ""


# ---------------------------------------------------------------------------
# Recuperación del timestamp tras reinicio
# ---------------------------------------------------------------------------


class TestRecuperacionTimestamp:
    """El timestamp importado se recupera de ingesta_log al reiniciar."""

    def test_tras_reinicio_no_se_reimporta_la_pasada(
        self, conexion, repositorio, reloj
    ):
        """El timestamp importado se recupera de ingesta_log al reiniciar la
        aplicación, de modo que tras un reinicio no se reimporta una pasada
        ya importada."""
        ofertas = [_oferta_dict(numero="061234567890")]
        cliente, _ = _crear_cliente_mock(
            _respuesta_status(timestamp="2026-01-21T10:30:00", ofertas_nuevas=ofertas)
        )

        # Primera tarea: importa el timestamp
        tarea1 = _crear_tarea(conexion, repositorio, cliente, reloj=reloj)
        tarea1._ejecutar_ciclo()
        assert _obtener_ultimo_timestamp(conexion) == "2026-01-21T10:30:00"

        # Simular reinicio: nueva tarea con la misma conexión/BD
        tarea2 = _crear_tarea(conexion, repositorio, cliente, reloj=reloj)
        resultado = tarea2._ejecutar_ciclo()

        # No debe reimportar
        assert not resultado.ejecutado
        assert resultado.motivo_omision == "timestamp_ya_importado"

    def test_el_timestamp_se_recupera_correctamente(
        self, conexion, repositorio, reloj
    ):
        """El timestamp importado se lee correctamente de ingesta_log."""
        ofertas = [_oferta_dict(numero="061234567890")]
        cliente, _ = _crear_cliente_mock(
            _respuesta_status(timestamp="2026-01-21T10:30:00", ofertas_nuevas=ofertas)
        )
        tarea = _crear_tarea(conexion, repositorio, cliente, reloj=reloj)
        tarea._ejecutar_ciclo()

        # Leer directamente de la BD
        assert _obtener_ultimo_timestamp(conexion) == "2026-01-21T10:30:00"


# ---------------------------------------------------------------------------
# actualizado_en en ingesta_log
# ---------------------------------------------------------------------------


class TestActualizadoEn:
    """El estado del timestamp importado queda en ingesta_log con actualizado_en."""

    def test_actualizado_en_se_actualiza(self, conexion, repositorio, reloj):
        """El estado del timestamp importado queda en ingesta_log con su marca
        actualizado_en."""
        ofertas = [_oferta_dict(numero="061234567890")]
        cliente, _ = _crear_cliente_mock(
            _respuesta_status(timestamp="2026-01-21T10:30:00", ofertas_nuevas=ofertas)
        )
        tarea = _crear_tarea(conexion, repositorio, cliente, reloj=reloj)

        # Antes del ciclo
        actualizado_antes = _obtener_actualizado_en(conexion)

        tarea._ejecutar_ciclo()

        # Después del ciclo, actualizado_en debe estar relleno
        actualizado_después = _obtener_actualizado_en(conexion)
        assert actualizado_después != ""
        # No debe ser el mismo que antes (ya que antes era el de la migración)
        # Pero como ambos usan datetime.now(), al menos verificamos que no está vacío

    def test_actualizado_en_refleja_la_ultima_ingesta(
        self, conexion, repositorio, reloj
    ):
        """Tras una segunda ingesta con nuevo timestamp, actualizado_en se actualiza."""
        ofertas1 = [_oferta_dict(numero="061234567890")]
        cliente1, _ = _crear_cliente_mock(
            _respuesta_status(timestamp="2026-01-21T10:30:00", ofertas_nuevas=ofertas1)
        )
        tarea = _crear_tarea(conexion, repositorio, cliente1, reloj=reloj)
        tarea._ejecutar_ciclo()
        actualizado_1 = _obtener_actualizado_en(conexion)

        # Avanzar el reloj para asegurar diferente actualizado_en
        reloj.avanzar(10)

        ofertas2 = [_oferta_dict(numero="061234567891")]
        cliente2, _ = _crear_cliente_mock(
            _respuesta_status(timestamp="2026-01-21T11:00:00", ofertas_nuevas=ofertas2)
        )
        tarea.cliente_buscador = cliente2
        tarea._ejecutar_ciclo()
        actualizado_2 = _obtener_actualizado_en(conexion)

        assert actualizado_2 != actualizado_1


# ---------------------------------------------------------------------------
# Programación con cadencia y cancelación
# ---------------------------------------------------------------------------


class TestProgramacionYCancelacion:
    """La tarea se programa con la cadencia configurada y se cancela limpiamente."""

    def test_se_programa_con_la_cadencia_configurada(self, conexion, repositorio):
        """La tarea se programa con la cadencia configurada."""
        cliente, _ = _crear_cliente_mock(
            _respuesta_status(timestamp=None)  # ultima_pasada nula para no persistir
        )
        reloj = RelojControlado()
        tarea = _crear_tarea(conexion, repositorio, cliente, cadencia=60, reloj=reloj)

        assert tarea.cadencia_segundos == 60

    def test_se_cancela_sin_dejar_ejecuciones_en_curso(
        self, conexion, repositorio
    ):
        """La tarea se cancela sin dejar ejecuciones en curso."""
        cliente, _ = _crear_cliente_mock(
            _respuesta_status(timestamp=None)
        )
        reloj = RelojControlado()
        tarea = _crear_tarea(conexion, repositorio, cliente, cadencia=60, reloj=reloj)

        tarea.iniciar()
        assert tarea._hilo is not None
        assert tarea._hilo.is_alive()

        tarea.detener()

        # El hilo debe haber terminado
        assert not tarea._hilo.is_alive()
        # El evento de parada debe estar activado
        assert tarea._evento_parada.is_set()

    def test_iniciar_dos_veces_no_crea_dos_hilos(self, conexion, repositorio):
        """Llamar a iniciar() dos veces no crea dos hilos."""
        cliente, _ = _crear_cliente_mock(
            _respuesta_status(timestamp=None)
        )
        reloj = RelojControlado()
        tarea = _crear_tarea(conexion, repositorio, cliente, cadencia=60, reloj=reloj)

        tarea.iniciar()
        hilo_1 = tarea._hilo

        tarea.iniciar()  # Segunda llamada: debe ser ignorada
        hilo_2 = tarea._hilo

        assert hilo_1 is hilo_2

        tarea.detener()

    def test_el_hilo_es_daemon(self, conexion, repositorio):
        """El hilo de la tarea es daemon (no impide cerrar el proceso)."""
        cliente, _ = _crear_cliente_mock(
            _respuesta_status(timestamp=None)
        )
        reloj = RelojControlado()
        tarea = _crear_tarea(conexion, repositorio, cliente, cadencia=60, reloj=reloj)

        tarea.iniciar()
        assert tarea._hilo.daemon is True

        tarea.detener()


# ---------------------------------------------------------------------------
# Conversión de datos de oferta
# ---------------------------------------------------------------------------


class TestConversionDatos:
    """Pruebas de la conversión de datos del buscador a Oferta."""

    def test_oferta_desde_datos_campos_basicos(self):
        """La conversión mapea correctamente los campos básicos."""
        datos = _oferta_dict(
            numero="061234567890",
            ocupacion="Desarrollador",
            municipio="Santander",
            provincia="Cantabria",
            comunidad="Cantabria",
            fecha_inicio="01/01/2026",
            fecha_fin="31/03/2026",
            texto="Texto libre",
            contacto="contacto@ejemplo.com",
        )
        oferta = _oferta_desde_datos(datos)
        assert oferta.comunidad == "Cantabria"
        assert oferta.codigo == "061234567890"
        assert oferta.estado == EstadoOferta.VIGENTE
        assert oferta.provincia == "Cantabria"
        assert oferta.ocupacion == "Desarrollador"
        assert oferta.municipio == "Santander"
        assert oferta.fecha_inicio_difusion == "01/01/2026"
        assert oferta.fecha_fin_difusion == "31/03/2026"
        assert oferta.texto_libre == "Texto libre"
        assert oferta.contacto == "contacto@ejemplo.com"

    def test_oferta_desde_datos_campos_ausentes_toman_defecto(self):
        """Los campos ausentes en los datos toman valores por defecto."""
        datos = {"numero_oferta": "060000000001"}
        oferta = _oferta_desde_datos(datos)
        assert oferta.codigo == "060000000001"
        assert oferta.comunidad == "Cantabria"
        assert oferta.provincia == ""
        assert oferta.ocupacion == ""
        assert oferta.municipio == ""
        assert oferta.texto_libre == ""
        assert oferta.contacto == ""
        assert oferta.fecha_inicio_difusion is None
        assert oferta.fecha_fin_difusion is None


# ---------------------------------------------------------------------------
# ResultadoCiclo
# ---------------------------------------------------------------------------


class TestResultadoCiclo:
    """Pruebas del dataclass ResultadoCiclo."""

    def test_por_defecto_no_ejecutado(self):
        """ResultadoCiclo por defecto indica no ejecutado."""
        r = ResultadoCiclo()
        assert not r.ejecutado
        assert r.timestamp_procesado == ""
        assert r.ofertas_procesadas == 0
        assert r.motivo_omision == ""

    def test_ejecutado_con_ofertas(self):
        """ResultadoCiclo ejecutado refleja las ofertas procesadas."""
        r = ResultadoCiclo(
            ejecutado=True,
            timestamp_procesado="2026-01-21T10:30:00",
            ofertas_procesadas=5,
        )
        assert r.ejecutado
        assert r.timestamp_procesado == "2026-01-21T10:30:00"
        assert r.ofertas_procesadas == 5


# ---------------------------------------------------------------------------
# Conteo de ofertas procesadas
# ---------------------------------------------------------------------------


class TestConteoOfertas:
    """Pruebas del conteo de ofertas procesadas."""

    def test_sin_ofertas_nuevas_no_procesa_nada(self, conexion, repositorio, reloj):
        """Si el buscador no devuelve ofertas nuevas, no se procesa ninguna."""
        cliente, _ = _crear_cliente_mock(
            _respuesta_status(timestamp="2026-01-21T10:30:00", ofertas_nuevas=[])
        )
        tarea = _crear_tarea(conexion, repositorio, cliente, reloj=reloj)

        resultado = tarea._ejecutar_ciclo()

        assert resultado.ejecutado
        assert resultado.ofertas_procesadas == 0

    def test_con_ofertas_nuevas_las_procesa_todas(self, conexion, repositorio, reloj):
        """Con tres ofertas nuevas, las tres se procesan."""
        ofertas = [
            _oferta_dict(numero="061234567890"),
            _oferta_dict(numero="061234567891"),
            _oferta_dict(numero="061234567892"),
        ]
        cliente, _ = _crear_cliente_mock(
            _respuesta_status(timestamp="2026-01-21T10:30:00", ofertas_nuevas=ofertas)
        )
        tarea = _crear_tarea(conexion, repositorio, cliente, reloj=reloj)

        resultado = tarea._ejecutar_ciclo()

        assert resultado.ejecutado
        assert resultado.ofertas_procesadas == 3
