"""Pruebas unitarias del coordinador de pasada del rastreador."""

import threading
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from source.api.buscador.coordinator import CoordinadorPasada, ProgresoPasada
from source.api.buscador.models import (
    ConfigBuscador,
    ErrorOferta,
    OfertaBuscador,
    ResultadoPasada,
)
from source.api.buscador.parser import ResultadoFicha
from source.api.buscador.scraper import ResultadoListado


@pytest.fixture
def config_mock(tmp_path: Path) -> ConfigBuscador:
    """Configuración de prueba."""
    return ConfigBuscador(
        url_listado="https://empleacantabria.es/ofertas-cantabria",
        url_ficha="https://empleacantabria.es/ofertas-cantabria/-/oferta",
        user_agent="Test/1.0",
        tamano_pagina=75,
    )


@pytest.fixture
def cliente_mock() -> MagicMock:
    """Cliente HTTP mock."""
    return MagicMock()


@pytest.fixture
def limitador_mock() -> MagicMock:
    """Limitador mock."""
    return MagicMock()


@pytest.fixture
def rutas_tmp(tmp_path: Path) -> tuple[Path, Path]:
    """Rutas temporales para seen_codes y failed_htmls."""
    seen_codes = tmp_path / "seen_codes.json"
    failed_htmls = tmp_path / "failed_htmls"
    return seen_codes, failed_htmls


def _crear_oferta(codigo: str) -> OfertaBuscador:
    """Helper para crear una oferta de prueba."""
    return OfertaBuscador(
        numero_oferta=codigo,
        ocupacion="Test",
        municipio="Santander",
        provincia="Cantabria",
        fecha_inicio_difusion="01/01/2024",
        fecha_fin_difusion="31/01/2024",
        texto_libre="Test",
        contacto="test@test.com",
    )


def test_pasada_exitosa_con_3_codigos_nuevos(
    config_mock: ConfigBuscador,
    cliente_mock: MagicMock,
    limitador_mock: MagicMock,
    rutas_tmp: tuple[Path, Path],
) -> None:
    """Una pasada exitosa con 3 códigos nuevos devuelve 3 ofertas."""
    ruta_seen, ruta_failed = rutas_tmp
    coordinador = CoordinadorPasada(
        config=config_mock,
        cliente=cliente_mock,
        limitador=limitador_mock,
        ruta_seen_codes=ruta_seen,
        ruta_failed_htmls=ruta_failed,
    )

    # Mock del listado: 3 códigos nuevos
    with patch("source.api.buscador.coordinator.recorrer_listado") as mock_listado:
        mock_listado.return_value = ResultadoListado(
            total=3,
            codigos=["062026003484", "062026003485", "062026003486"],
            error_global="",
        )

        # Mock del parser: todas las fichas exitosas
        with patch("source.api.buscador.coordinator.parsear_ficha") as mock_parser:
            mock_parser.side_effect = [
                ResultadoFicha(oferta=_crear_oferta("062026003484"), html="", error=""),
                ResultadoFicha(oferta=_crear_oferta("062026003485"), html="", error=""),
                ResultadoFicha(oferta=_crear_oferta("062026003486"), html="", error=""),
            ]

            resultado = coordinador.ejecutar_pasada()

    assert isinstance(resultado, ResultadoPasada)
    assert resultado.error_global == ""
    assert len(resultado.ofertas_nuevas) == 3
    assert resultado.total_listado == 3
    assert resultado.comunidad == "Cantabria"


def test_pasada_con_codigos_ya_vistos_se_saltan(
    config_mock: ConfigBuscador,
    cliente_mock: MagicMock,
    limitador_mock: MagicMock,
    rutas_tmp: tuple[Path, Path],
) -> None:
    """Los códigos ya vistos se saltan y no se parsean."""
    ruta_seen, ruta_failed = rutas_tmp
    
    # Pre-cargar códigos vistos
    ruta_seen.write_text('["062026003484"]', encoding="utf-8")
    
    coordinador = CoordinadorPasada(
        config=config_mock,
        cliente=cliente_mock,
        limitador=limitador_mock,
        ruta_seen_codes=ruta_seen,
        ruta_failed_htmls=ruta_failed,
    )

    # Mock del listado: 3 códigos, pero uno ya está visto
    with patch("source.api.buscador.coordinator.recorrer_listado") as mock_listado:
        # El scraper ya filtra los vistos, así que solo devuelve 2
        mock_listado.return_value = ResultadoListado(
            total=3,
            codigos=["062026003485", "062026003486"],
            error_global="",
        )

        with patch("source.api.buscador.coordinator.parsear_ficha") as mock_parser:
            mock_parser.side_effect = [
                ResultadoFicha(oferta=_crear_oferta("062026003485"), html="", error=""),
                ResultadoFicha(oferta=_crear_oferta("062026003486"), html="", error=""),
            ]

            resultado = coordinador.ejecutar_pasada()

    # Solo se parsearon 2 fichas (el código ya visto se saltó)
    assert mock_parser.call_count == 2
    assert len(resultado.ofertas_nuevas) == 2


def test_pasada_con_fichas_fallidas_genera_errores(
    config_mock: ConfigBuscador,
    cliente_mock: MagicMock,
    limitador_mock: MagicMock,
    rutas_tmp: tuple[Path, Path],
) -> None:
    """Las fichas fallidas generan errores por oferta y archivan el HTML."""
    ruta_seen, ruta_failed = rutas_tmp
    coordinador = CoordinadorPasada(
        config=config_mock,
        cliente=cliente_mock,
        limitador=limitador_mock,
        ruta_seen_codes=ruta_seen,
        ruta_failed_htmls=ruta_failed,
    )

    with patch("source.api.buscador.coordinator.recorrer_listado") as mock_listado:
        mock_listado.return_value = ResultadoListado(
            total=3,
            codigos=["062026003484", "062026003485", "062026003486"],
            error_global="",
        )

        with patch("source.api.buscador.coordinator.parsear_ficha") as mock_parser:
            # Una exitosa, una fallida, una exitosa
            mock_parser.side_effect = [
                ResultadoFicha(oferta=_crear_oferta("062026003484"), html="", error=""),
                ResultadoFicha(oferta=None, html="<html>error</html>", error="Parseo fallido"),
                ResultadoFicha(oferta=_crear_oferta("062026003486"), html="", error=""),
            ]

            with patch("source.api.buscador.coordinator.archivar_html_fallido") as mock_archivo:
                resultado = coordinador.ejecutar_pasada()

    # Verificar que se archivó el HTML fallido
    assert mock_archivo.call_count == 1
    assert mock_archivo.call_args[1]["codigo"] == "062026003485"

    # Verificar el resultado
    assert resultado.error_global == ""
    assert len(resultado.ofertas_nuevas) == 2
    assert len(resultado.errores_por_oferta) == 1
    assert resultado.errores_por_oferta[0].codigo == "062026003485"


def test_exclusion_mutua_segunda_llamada_rechazada(
    config_mock: ConfigBuscador,
    cliente_mock: MagicMock,
    limitador_mock: MagicMock,
    rutas_tmp: tuple[Path, Path],
) -> None:
    """Si hay una pasada en curso, la segunda llamada se rechaza."""
    ruta_seen, ruta_failed = rutas_tmp
    coordinador = CoordinadorPasada(
        config=config_mock,
        cliente=cliente_mock,
        limitador=limitador_mock,
        ruta_seen_codes=ruta_seen,
        ruta_failed_htmls=ruta_failed,
    )

    # Simular que hay una pasada en curso
    coordinador._pasada_en_curso = True

    # Segunda llamada debe devolver error
    resultado = coordinador.ejecutar_pasada()

    assert resultado.error_global == "Ya hay una pasada en curso"
    assert len(resultado.ofertas_nuevas) == 0


def test_thread_safety_multiples_hilos(
    config_mock: ConfigBuscador,
    cliente_mock: MagicMock,
    limitador_mock: MagicMock,
    rutas_tmp: tuple[Path, Path],
) -> None:
    """Múltiples hilos intentando ejecutar pasadas no rompen el estado."""
    ruta_seen, ruta_failed = rutas_tmp
    coordinador = CoordinadorPasada(
        config=config_mock,
        cliente=cliente_mock,
        limitador=limitador_mock,
        ruta_seen_codes=ruta_seen,
        ruta_failed_htmls=ruta_failed,
    )

    resultados: list[ResultadoPasada] = []
    barrier = threading.Barrier(2)

    def ejecutar_en_hilo() -> None:
        barrier.wait()  # Sincronizar ambos hilos
        resultado = coordinador.ejecutar_pasada()
        resultados.append(resultado)

    # Crear dos hilos
    hilo1 = threading.Thread(target=ejecutar_en_hilo)
    hilo2 = threading.Thread(target=ejecutar_en_hilo)

    with patch("source.api.buscador.coordinator.recorrer_listado") as mock_listado:
        mock_listado.return_value = ResultadoListado(
            total=0,
            codigos=[],
            error_global="",
        )

        hilo1.start()
        hilo2.start()

        hilo1.join()
        hilo2.join()

    # Uno de los hilos debe haber ejecutado la pasada, el otro rechazado
    assert len(resultados) == 2
    exitos = [r for r in resultados if r.error_global == ""]
    rechazados = [r for r in resultados if r.error_global == "Ya hay una pasada en curso"]
    assert len(exitos) == 1
    assert len(rechazados) == 1


def test_progreso_se_actualiza_correctamente(
    config_mock: ConfigBuscador,
    cliente_mock: MagicMock,
    limitador_mock: MagicMock,
    rutas_tmp: tuple[Path, Path],
) -> None:
    """El progreso se actualiza durante la ejecución."""
    ruta_seen, ruta_failed = rutas_tmp
    coordinador = CoordinadorPasada(
        config=config_mock,
        cliente=cliente_mock,
        limitador=limitador_mock,
        ruta_seen_codes=ruta_seen,
        ruta_failed_htmls=ruta_failed,
    )

    progreso_observado: list[tuple[int, int]] = []

    def mock_parser_con_progreso(*args, **kwargs):
        """Mock que observa el progreso después de cada llamada."""
        progreso_observado.append(
            (coordinador._progreso.codigos_procesados, coordinador._progreso.total_codigos)
        )
        return ResultadoFicha(oferta=_crear_oferta("062026003484"), html="", error="")

    with patch("source.api.buscador.coordinator.recorrer_listado") as mock_listado:
        mock_listado.return_value = ResultadoListado(
            total=3,
            codigos=["062026003484", "062026003485", "062026003486"],
            error_global="",
        )

        with patch("source.api.buscador.coordinator.parsear_ficha") as mock_parser:
            mock_parser.side_effect = [
                ResultadoFicha(oferta=_crear_oferta("062026003484"), html="", error=""),
                ResultadoFicha(oferta=_crear_oferta("062026003485"), html="", error=""),
                ResultadoFicha(oferta=_crear_oferta("062026003486"), html="", error=""),
            ]

            resultado = coordinador.ejecutar_pasada()

    # Verificar que el progreso se actualizó
    assert coordinador._progreso.codigos_procesados == 3
    assert coordinador._progreso.total_codigos == 3
    assert coordinador._progreso.hora_inicio != ""


def test_error_global_en_listado_devuelve_error(
    config_mock: ConfigBuscador,
    cliente_mock: MagicMock,
    limitador_mock: MagicMock,
    rutas_tmp: tuple[Path, Path],
) -> None:
    """Si el listado falla, se devuelve error global sin parsear fichas."""
    ruta_seen, ruta_failed = rutas_tmp
    coordinador = CoordinadorPasada(
        config=config_mock,
        cliente=cliente_mock,
        limitador=limitador_mock,
        ruta_seen_codes=ruta_seen,
        ruta_failed_htmls=ruta_failed,
    )

    with patch("source.api.buscador.coordinator.recorrer_listado") as mock_listado:
        mock_listado.return_value = ResultadoListado(
            total=0,
            codigos=[],
            error_global="Error de conexión al portal",
        )

        with patch("source.api.buscador.coordinator.parsear_ficha") as mock_parser:
            resultado = coordinador.ejecutar_pasada()

    # No se debe haber llamado al parser
    assert mock_parser.call_count == 0
    assert resultado.error_global == "Error de conexión al portal"
    assert len(resultado.ofertas_nuevas) == 0


def test_pasada_flag_se_limpia_tras_ejecucion(
    config_mock: ConfigBuscador,
    cliente_mock: MagicMock,
    limitador_mock: MagicMock,
    rutas_tmp: tuple[Path, Path],
) -> None:
    """El flag de pasada en curso se limpia tras la ejecución."""
    ruta_seen, ruta_failed = rutas_tmp
    coordinador = CoordinadorPasada(
        config=config_mock,
        cliente=cliente_mock,
        limitador=limitador_mock,
        ruta_seen_codes=ruta_seen,
        ruta_failed_htmls=ruta_failed,
    )

    assert coordinador.pasada_en_curso is False

    with patch("source.api.buscador.coordinator.recorrer_listado") as mock_listado:
        mock_listado.return_value = ResultadoListado(
            total=0,
            codigos=[],
            error_global="",
        )

        coordinador.ejecutar_pasada()

    # El flag debe estar limpio después
    assert coordinador.pasada_en_curso is False


def test_ultimo_resultado_se_actualiza(
    config_mock: ConfigBuscador,
    cliente_mock: MagicMock,
    limitador_mock: MagicMock,
    rutas_tmp: tuple[Path, Path],
) -> None:
    """El último resultado se actualiza tras la ejecución."""
    ruta_seen, ruta_failed = rutas_tmp
    coordinador = CoordinadorPasada(
        config=config_mock,
        cliente=cliente_mock,
        limitador=limitador_mock,
        ruta_seen_codes=ruta_seen,
        ruta_failed_htmls=ruta_failed,
    )

    assert coordinador.ultimo_resultado is None

    with patch("source.api.buscador.coordinator.recorrer_listado") as mock_listado:
        mock_listado.return_value = ResultadoListado(
            total=1,
            codigos=["062026003484"],
            error_global="",
        )

        with patch("source.api.buscador.coordinator.parsear_ficha") as mock_parser:
            mock_parser.return_value = ResultadoFicha(
                oferta=_crear_oferta("062026003484"),
                html="",
                error="",
            )

            resultado = coordinador.ejecutar_pasada()

    # El último resultado debe estar actualizado
    assert coordinador.ultimo_resultado is not None
    assert coordinador.ultimo_resultado == resultado


def test_historical_codes_usa_lista_en_lugar_de_fichero(
    config_mock: ConfigBuscador,
    cliente_mock: MagicMock,
    limitador_mock: MagicMock,
    rutas_tmp: tuple[Path, Path],
) -> None:
    """Con historical_codes, se usa esa lista en lugar de leer del fichero."""
    ruta_seen, ruta_failed = rutas_tmp
    
    # Pre-cargar fichero con un código
    ruta_seen.write_text('["062026003999"]', encoding="utf-8")
    
    coordinador = CoordinadorPasada(
        config=config_mock,
        cliente=cliente_mock,
        limitador=limitador_mock,
        ruta_seen_codes=ruta_seen,
        ruta_failed_htmls=ruta_failed,
    )

    # Ejecutar pasada con historical_codes diferentes
    historical_codes = ["062026003484", "062026003485"]
    
    with patch("source.api.buscador.coordinator.recorrer_listado") as mock_listado:
        mock_listado.return_value = ResultadoListado(
            total=2,
            codigos=["062026003484", "062026003485"],
            error_global="",
        )
        
        with patch("source.api.buscador.coordinator.parsear_ficha") as mock_parser:
            mock_parser.side_effect = [
                ResultadoFicha(oferta=_crear_oferta("062026003484"), html="", error=""),
                ResultadoFicha(oferta=_crear_oferta("062026003485"), html="", error=""),
            ]
            
            resultado = coordinador.ejecutar_pasada(historical_codes=historical_codes)

    # Verificar que el listado se llamó con los códigos de historical_codes
    # (el scraper ya filtra, así que solo llegan los que no están en historical_codes)
    assert mock_listado.call_args[1]["codigos_vistos"] == set(historical_codes)
    
    # Verificar que el fichero NO se modificó
    contenido_fichero = ruta_seen.read_text(encoding="utf-8")
    assert contenido_fichero == '["062026003999"]'


def test_sin_historical_codes_usa_fichero_y_lo_actualiza(
    config_mock: ConfigBuscador,
    cliente_mock: MagicMock,
    limitador_mock: MagicMock,
    rutas_tmp: tuple[Path, Path],
) -> None:
    """Sin historical_codes, se lee del fichero y se actualiza."""
    ruta_seen, ruta_failed = rutas_tmp
    
    # Pre-cargar fichero con un código
    ruta_seen.write_text('["062026003999"]', encoding="utf-8")
    
    coordinador = CoordinadorPasada(
        config=config_mock,
        cliente=cliente_mock,
        limitador=limitador_mock,
        ruta_seen_codes=ruta_seen,
        ruta_failed_htmls=ruta_failed,
    )

    with patch("source.api.buscador.coordinator.recorrer_listado") as mock_listado:
        mock_listado.return_value = ResultadoListado(
            total=1,
            codigos=["062026003484"],
            error_global="",
        )
        
        with patch("source.api.buscador.coordinator.parsear_ficha") as mock_parser:
            mock_parser.return_value = ResultadoFicha(
                oferta=_crear_oferta("062026003484"),
                html="",
                error="",
            )
            
            resultado = coordinador.ejecutar_pasada()  # Sin historical_codes

    # Verificar que el fichero se actualizó con el nuevo código
    import json
    contenido_fichero = json.loads(ruta_seen.read_text(encoding="utf-8"))
    assert "062026003999" in contenido_fichero
    assert "062026003484" in contenido_fichero
