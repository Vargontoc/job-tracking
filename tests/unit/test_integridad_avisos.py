"""Pruebas del almacén de avisos de la integridad.

Cubren el registro de una divergencia y de un fallo como aviso anexado al
`.meta.json` del día, la consulta por rango de fechas y los casos de límite:
día sin metadatos, metadatos ilegibles, ausencia de canales de notificación
externa (SUP-007) y ausencia de ficheros SQLite (DEC-001). Todo se ejecuta
sobre `tmp_path`: no se toca ningún directorio real del proyecto.
"""

import ast
import inspect
import json
from datetime import date
from pathlib import Path

import pytest

from source.api.integridad import avisos as modulo_avisos
from source.api.integridad.avisos import (
    TIPO_DIVERGENCIA,
    TIPO_FALLO,
    AlmacenAvisos,
    ErrorAvisoIntegridad,
)
from source.api.integridad.comparador import ResultadoComparacion
from source.api.integridad.pdf_store import (
    VEREDICTO_DIVERGENTE,
    VEREDICTO_FALLIDO,
    AlmacenPDFs,
    MetaDia,
)

COMUNIDAD = "cantabria"
OTRA_COMUNIDAD = "madrid"
FECHA = date(2026, 11, 23)
CONTENIDO = b"%PDF-1.4 contenido de prueba del PDF de difusion\n"


def _almacen(base: Path) -> AlmacenPDFs:
    """Crea el almacén de PDFs sobre el directorio temporal de la prueba."""
    return AlmacenPDFs(base, "Europe/Madrid")


def _resultado_divergente() -> ResultadoComparacion:
    """Resultado del comparador para una divergencia de recuentos."""
    return ResultadoComparacion(
        veredicto=VEREDICTO_DIVERGENTE,
        recuento_pdf=80,
        recuento_buscador=93,
        diferencia=13,
        tolerancia_absoluta=1,
        tolerancia_relativa_pct=5,
        umbral_cordura=70,
        motivo="Diferencia de 13 ofertas fuera de las tolerancias.",
    )


def _dia_divergente(almacen: AlmacenPDFs, fecha: date = FECHA) -> None:
    """Deja el día con PDF y un `.meta.json` en estado `divergente`."""
    almacen.guardar_pdf(
        COMUNIDAD,
        fecha,
        CONTENIDO,
        MetaDia(
            recuento_pdf=80,
            recuento_buscador=93,
            diferencia=13,
            tolerancia_absoluta=1,
            tolerancia_relativa_pct=5,
            umbral_cordura=70,
            veredicto=VEREDICTO_DIVERGENTE,
        ),
    )


def _meta_guardado(
    almacen: AlmacenPDFs, comunidad: str = COMUNIDAD, fecha: date = FECHA
) -> dict:
    """Lee como diccionario el `.meta.json` del día indicado."""
    return json.loads(
        almacen.ruta_meta(comunidad, fecha).read_text(encoding="utf-8")
    )


def test_una_divergencia_genera_aviso_con_los_datos(tmp_path: Path) -> None:
    """El aviso de divergencia lleva los datos de la comparación (REQ-007)."""
    almacen = _almacen(tmp_path)
    _dia_divergente(almacen)
    avisos = AlmacenAvisos(almacen)

    aviso = avisos.registrar_divergencia(
        COMUNIDAD, FECHA, _resultado_divergente()
    )

    assert aviso["tipo"] == TIPO_DIVERGENCIA
    assert aviso["fecha"] == "2026-11-23"
    assert aviso["comunidad"] == COMUNIDAD
    assert aviso["recuento_pdf"] == 80
    assert aviso["total_listado"] == 93
    assert aviso["diferencia"] == 13
    assert aviso["tolerancia_absoluta"] == 1
    assert aviso["tolerancia_relativa_pct"] == 5
    assert aviso["umbral_cordura"] == 70
    assert aviso["motivo"] == (
        "Diferencia de 13 ofertas fuera de las tolerancias."
    )


def test_el_aviso_queda_en_el_meta_del_dia_sin_perder_el_resto(
    tmp_path: Path,
) -> None:
    """El aviso se anexa al `.meta.json` del día y conserva sus campos (DEC-001)."""
    almacen = _almacen(tmp_path)
    _dia_divergente(almacen)
    avisos = AlmacenAvisos(almacen)

    aviso = avisos.registrar_divergencia(
        COMUNIDAD, FECHA, _resultado_divergente()
    )

    datos = _meta_guardado(almacen)
    assert datos["avisos"] == [aviso]
    assert datos["veredicto"] == VEREDICTO_DIVERGENTE
    assert datos["recuento_pdf"] == 80
    assert datos["hash"] == almacen.leer_meta(COMUNIDAD, FECHA).meta.hash
    assert almacen.ruta_pdf(COMUNIDAD, FECHA).read_bytes() == CONTENIDO


def test_un_fallo_de_descarga_genera_aviso(tmp_path: Path) -> None:
    """Un fallo de descarga deja aviso con fecha, comunidad y motivo (ALT-003)."""
    almacen = _almacen(tmp_path)
    almacen.escribir_fallido(COMUNIDAD, FECHA, "error HTTP 503")
    avisos = AlmacenAvisos(almacen)

    aviso = avisos.registrar_fallo(COMUNIDAD, FECHA, "error HTTP 503")

    assert aviso == {
        "tipo": TIPO_FALLO,
        "fecha": "2026-11-23",
        "comunidad": COMUNIDAD,
        "motivo": "error HTTP 503",
    }
    assert _meta_guardado(almacen)["avisos"] == [aviso]
    assert not almacen.ruta_pdf(COMUNIDAD, FECHA).exists()


def test_un_fallo_de_parseo_genera_aviso_y_conserva_el_pdf(
    tmp_path: Path,
) -> None:
    """Un fallo de parseo deja aviso con su motivo y el PDF conservado (DEC-002)."""
    almacen = _almacen(tmp_path)
    almacen.guardar_pdf(
        COMUNIDAD,
        FECHA,
        CONTENIDO,
        MetaDia(veredicto=VEREDICTO_FALLIDO, errores=["PDF ilegible"]),
    )
    avisos = AlmacenAvisos(almacen)

    aviso = avisos.registrar_fallo(COMUNIDAD, FECHA, "PDF ilegible")

    assert aviso["fecha"] == "2026-11-23"
    assert aviso["comunidad"] == COMUNIDAD
    assert aviso["motivo"] == "PDF ilegible"
    assert _meta_guardado(almacen)["avisos"] == [aviso]
    assert almacen.ruta_pdf(COMUNIDAD, FECHA).read_bytes() == CONTENIDO


def test_los_avisos_se_anexan_sin_perder_los_anteriores(
    tmp_path: Path,
) -> None:
    """Un segundo aviso del mismo día se añade detrás del primero."""
    almacen = _almacen(tmp_path)
    _dia_divergente(almacen)
    avisos = AlmacenAvisos(almacen)

    primero = avisos.registrar_fallo(COMUNIDAD, FECHA, "reintento manual")
    segundo = avisos.registrar_divergencia(
        COMUNIDAD, FECHA, _resultado_divergente()
    )

    assert _meta_guardado(almacen)["avisos"] == [primero, segundo]


def test_un_aviso_sin_total_listado_conserva_los_nulos(
    tmp_path: Path,
) -> None:
    """Sin estado utilizable del buscador el aviso guarda nulos (ALT-005)."""
    almacen = _almacen(tmp_path)
    _dia_divergente(almacen)
    avisos = AlmacenAvisos(almacen)
    resultado = ResultadoComparacion(
        veredicto=VEREDICTO_DIVERGENTE,
        recuento_pdf=80,
        recuento_buscador=None,
        diferencia=None,
        tolerancia_absoluta=1,
        tolerancia_relativa_pct=5,
        umbral_cordura=70,
        motivo="Estado del buscador no utilizable: error de red",
    )

    aviso = avisos.registrar_divergencia(COMUNIDAD, FECHA, resultado)

    assert aviso["total_listado"] is None
    assert aviso["diferencia"] is None
    assert "error de red" in aviso["motivo"]


def test_la_consulta_por_rango_devuelve_los_del_rango_y_excluye_los_de_fuera(
    tmp_path: Path,
) -> None:
    """La consulta filtra por fecha y devuelve las comunidades del rango (REQ-009)."""
    almacen = _almacen(tmp_path)
    avisos = AlmacenAvisos(almacen)
    antes = date(2026, 11, 20)
    dentro = date(2026, 11, 22)
    despues = date(2026, 11, 25)
    _dia_divergente(almacen, antes)
    _dia_divergente(almacen, dentro)
    _dia_divergente(almacen, despues)
    almacen.guardar_pdf(OTRA_COMUNIDAD, dentro, CONTENIDO)
    avisos.registrar_fallo(COMUNIDAD, antes, "fuera por abajo")
    avisos.registrar_fallo(COMUNIDAD, dentro, "dentro cantabria")
    avisos.registrar_fallo(OTRA_COMUNIDAD, dentro, "dentro madrid")
    avisos.registrar_fallo(COMUNIDAD, despues, "fuera por arriba")

    consultados = avisos.consultar(date(2026, 11, 21), date(2026, 11, 23))

    assert [aviso["motivo"] for aviso in consultados] == [
        "dentro cantabria",
        "dentro madrid",
    ]
    assert all(aviso["fecha"] == "2026-11-22" for aviso in consultados)
    assert {aviso["comunidad"] for aviso in consultados} == {
        COMUNIDAD,
        OTRA_COMUNIDAD,
    }


def test_la_consulta_incluye_los_extremos_del_rango(tmp_path: Path) -> None:
    """El rango de la consulta es inclusivo por ambos extremos."""
    almacen = _almacen(tmp_path)
    avisos = AlmacenAvisos(almacen)
    primero = date(2026, 11, 20)
    ultimo = date(2026, 11, 22)
    _dia_divergente(almacen, primero)
    _dia_divergente(almacen, ultimo)
    avisos.registrar_fallo(COMUNIDAD, primero, "extremo inferior")
    avisos.registrar_fallo(COMUNIDAD, ultimo, "extremo superior")

    consultados = avisos.consultar(primero, ultimo)

    assert [aviso["fecha"] for aviso in consultados] == [
        "2026-11-20",
        "2026-11-22",
    ]


def test_la_consulta_omite_metas_ausentes_e_ilegibles(tmp_path: Path) -> None:
    """Un `.meta.json` ausente o ilegible se omite sin error (DEC-001)."""
    almacen = _almacen(tmp_path)
    avisos = AlmacenAvisos(almacen)
    valido = date(2026, 11, 22)
    corrupto = date(2026, 11, 23)
    _dia_divergente(almacen, valido)
    avisos.registrar_fallo(COMUNIDAD, valido, "único legible")
    ruta_corrupta = almacen.ruta_meta(COMUNIDAD, corrupto)
    ruta_corrupta.write_text('{"avisos": [', encoding="utf-8")

    consultados = avisos.consultar(date(2026, 11, 20), date(2026, 11, 25))

    assert [aviso["motivo"] for aviso in consultados] == ["único legible"]


def test_la_consulta_sin_directorio_devuelve_lista_vacia(
    tmp_path: Path,
) -> None:
    """Sin ruta base de PDFs la consulta no produce error."""
    avisos = AlmacenAvisos(_almacen(tmp_path / "no-existe"))

    assert avisos.consultar(date(2026, 11, 20), date(2026, 11, 25)) == []


def test_la_consulta_completa_fecha_y_comunidad_de_avisos_antiguos(
    tmp_path: Path,
) -> None:
    """Un aviso sin fecha ni comunidad en el fichero se devuelve completo."""
    almacen = _almacen(tmp_path)
    almacen.escribir_meta(
        COMUNIDAD,
        FECHA,
        MetaDia(
            veredicto=VEREDICTO_FALLIDO,
            avisos=[{"motivo": "aviso heredado"}],
        ),
    )
    avisos = AlmacenAvisos(almacen)

    consultados = avisos.consultar(FECHA, FECHA)

    assert consultados == [
        {
            "motivo": "aviso heredado",
            "fecha": "2026-11-23",
            "comunidad": COMUNIDAD,
        }
    ]


def test_registrar_sin_meta_lanza_error_controlado_sin_crear_ficheros(
    tmp_path: Path,
) -> None:
    """Sin `.meta.json` del día no se inventa un día válido (DEC-001)."""
    almacen = _almacen(tmp_path)
    avisos = AlmacenAvisos(almacen)

    with pytest.raises(ErrorAvisoIntegridad):
        avisos.registrar_fallo(COMUNIDAD, FECHA, "error HTTP 503")

    assert not almacen.ruta_meta(COMUNIDAD, FECHA).exists()
    assert not almacen.ruta_pdf(COMUNIDAD, FECHA).exists()
    assert not (tmp_path / COMUNIDAD).exists()


def test_registrar_con_meta_ilegible_lanza_error_y_no_toca_el_fichero(
    tmp_path: Path,
) -> None:
    """Un `.meta.json` ilegible no se sobrescribe ni se trata como válido."""
    almacen = _almacen(tmp_path)
    ruta_meta = almacen.ruta_meta(COMUNIDAD, FECHA)
    ruta_meta.parent.mkdir(parents=True)
    ruta_meta.write_text('{"hash": "abc", ', encoding="utf-8")
    contenido_previo = ruta_meta.read_bytes()
    avisos = AlmacenAvisos(almacen)

    with pytest.raises(ErrorAvisoIntegridad):
        avisos.registrar_divergencia(
            COMUNIDAD, FECHA, _resultado_divergente()
        )

    assert ruta_meta.read_bytes() == contenido_previo


def test_el_almacen_no_importa_clientes_de_notificacion() -> None:
    """El módulo no importa ningún canal de notificación externo (SUP-007)."""
    arbol = ast.parse(inspect.getsource(modulo_avisos))
    importados: set[str] = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            importados.update(alias.name for alias in nodo.names)
        elif isinstance(nodo, ast.ImportFrom) and nodo.module:
            importados.add(nodo.module)

    prohibidos = ("telegram", "notif", "smtp", "requests", "mail")
    for nombre in importados:
        assert not any(
            prohibido in nombre.lower() for prohibido in prohibidos
        ), nombre


def test_el_almacen_no_crea_ficheros_sqlite(tmp_path: Path) -> None:
    """Registrar y consultar avisos no crea ningún fichero SQLite (DEC-001)."""
    almacen = _almacen(tmp_path)
    _dia_divergente(almacen)
    avisos = AlmacenAvisos(almacen)

    avisos.registrar_fallo(COMUNIDAD, FECHA, "error de red")
    avisos.registrar_divergencia(COMUNIDAD, FECHA, _resultado_divergente())
    avisos.consultar(FECHA, FECHA)

    sufijos = (".db", ".sqlite", ".sqlite3", ".db-wal", ".db-shm")
    ficheros = [
        fichero
        for fichero in tmp_path.rglob("*")
        if fichero.is_file() and fichero.name.lower().endswith(sufijos)
    ]
    assert ficheros == []
