"""Pruebas del almacén de PDFs y metadatos del día de la integridad.

Cubren el árbol `<base>/<comunidad>/<aaaa-mm-dd>.pdf` con su `.meta.json`,
la escritura atómica, el hash SHA-256, el día `fallido`, los campos del
modelo y la lectura controlada de metadatos ausentes o corruptos. Todo se
ejecuta sobre `tmp_path`: no se toca ningún directorio real del proyecto.
"""

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from source.api.integridad.pdf_store import (
    ESTADO_META_AUSENTE,
    ESTADO_META_ILEGIBLE,
    ESTADO_META_OK,
    VEREDICTO_CONCORDANTE,
    VEREDICTO_FALLIDO,
    AlmacenPDFs,
    MetaDia,
)

COMUNIDAD = "cantabria"
OTRA_COMUNIDAD = "madrid"
FECHA = date(2026, 11, 23)
CONTENIDO = b"%PDF-1.4 contenido de prueba del PDF de difusion\n"
CAMPOS_ESPERADOS = {
    "hash",
    "recuento_pdf",
    "recuento_buscador",
    "diferencia",
    "tolerancia_absoluta",
    "tolerancia_relativa_pct",
    "umbral_cordura",
    "veredicto",
    "errores",
    "avisos",
    "timestamp",
}


def _almacen(base: Path, zona: str = "Europe/Madrid") -> AlmacenPDFs:
    """Crea un almacén sobre el directorio temporal de la prueba."""
    return AlmacenPDFs(base, zona)


def _ficheros(carpeta: Path) -> set[str]:
    """Nombres de los ficheros presentes en una carpeta."""
    return {fichero.name for fichero in carpeta.iterdir() if fichero.is_file()}


def _meta_guardado(almacen: AlmacenPDFs, comunidad: str = COMUNIDAD) -> dict:
    """Lee como diccionario el `.meta.json` del día de la prueba."""
    return json.loads(
        almacen.ruta_meta(comunidad, FECHA).read_text(encoding="utf-8")
    )


def test_rutas_identifican_comunidad_y_fecha(tmp_path: Path) -> None:
    """Las rutas son `<base>/<comunidad>/<aaaa-mm-dd>.pdf` y su `.meta.json`."""
    almacen = _almacen(Path(str(tmp_path)))

    assert almacen.ruta_pdf(COMUNIDAD, FECHA) == (
        tmp_path / COMUNIDAD / "2026-11-23.pdf"
    )
    assert almacen.ruta_meta(COMUNIDAD, FECHA) == (
        tmp_path / COMUNIDAD / "2026-11-23.meta.json"
    )
    assert almacen.base == tmp_path


def test_ruta_admite_datetime_y_lo_reduce_a_su_fecha(tmp_path: Path) -> None:
    """Un `datetime` se reduce a su fecha para componer el nombre."""
    almacen = _almacen(tmp_path)
    momento = datetime(2026, 11, 23, 2, 0, tzinfo=ZoneInfo("Europe/Madrid"))

    assert almacen.ruta_pdf(COMUNIDAD, momento).name == "2026-11-23.pdf"


def test_guardar_pdf_crea_el_directorio_de_la_comunidad(
    tmp_path: Path,
) -> None:
    """Si el directorio de la comunidad no existe, se crea al guardar."""
    almacen = _almacen(tmp_path)
    carpeta = tmp_path / COMUNIDAD
    assert not carpeta.exists()

    almacen.guardar_pdf(COMUNIDAD, FECHA, CONTENIDO)

    assert carpeta.is_dir()


def test_guardar_pdf_crea_el_pdf_y_su_meta(tmp_path: Path) -> None:
    """Tras guardar existen el PDF y su `.meta.json` con el hash del contenido."""
    almacen = _almacen(tmp_path)

    meta = almacen.guardar_pdf(COMUNIDAD, FECHA, CONTENIDO)

    ruta_pdf = almacen.ruta_pdf(COMUNIDAD, FECHA)
    assert ruta_pdf.is_file()
    assert ruta_pdf.read_bytes() == CONTENIDO
    assert ruta_pdf.parent.name == COMUNIDAD
    assert ruta_pdf.name == "2026-11-23.pdf"
    assert almacen.ruta_meta(COMUNIDAD, FECHA).is_file()
    assert meta.hash == hashlib.sha256(CONTENIDO).hexdigest()


def test_el_hash_del_meta_coincide_con_el_sha256_del_contenido(
    tmp_path: Path,
) -> None:
    """El hash guardado es el SHA-256 del contenido del PDF (DEC-003)."""
    almacen = _almacen(tmp_path)
    almacen.guardar_pdf(COMUNIDAD, FECHA, CONTENIDO)

    datos = _meta_guardado(almacen)

    assert datos["hash"] == hashlib.sha256(CONTENIDO).hexdigest()


def test_la_escritura_del_pdf_es_atomica(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El PDF se escribe en un temporal y se renombra al nombre definitivo."""
    almacen = _almacen(tmp_path)
    definitiva = almacen.ruta_pdf(COMUNIDAD, FECHA)
    carpeta = definitiva.parent
    observaciones: list[dict] = []
    replace_original = Path.replace

    def replace_espiado(ruta_temporal: Path, ruta_destino: Path) -> Path:
        observaciones.append(
            {
                "temporal": ruta_temporal,
                "destino": Path(ruta_destino),
                "definitiva_existe_antes": Path(ruta_destino).exists(),
                "contenido": ruta_temporal.read_bytes(),
            }
        )
        return replace_original(ruta_temporal, ruta_destino)

    monkeypatch.setattr(Path, "replace", replace_espiado)

    almacen.guardar_pdf(COMUNIDAD, FECHA, CONTENIDO)
    monkeypatch.undo()

    assert len(observaciones) == 2
    primera = observaciones[0]
    assert primera["destino"] == definitiva
    assert primera["temporal"].parent == carpeta
    assert primera["temporal"].name == definitiva.name + ".tmp"
    assert primera["definitiva_existe_antes"] is False
    assert primera["contenido"] == CONTENIDO

    assert definitiva.read_bytes() == CONTENIDO
    assert _ficheros(carpeta) == {
        definitiva.name,
        almacen.ruta_meta(COMUNIDAD, FECHA).name,
    }


def test_la_escritura_del_meta_es_atomica_y_el_json_es_valido(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El `.meta.json` se escribe con temporal y `replace` y es JSON válido."""
    almacen = _almacen(tmp_path)
    ruta_meta = almacen.ruta_meta(COMUNIDAD, FECHA)
    meta = MetaDia(
        recuento_pdf=92,
        recuento_buscador=93,
        diferencia=1,
        veredicto=VEREDICTO_CONCORDANTE,
    )
    observaciones: list[dict] = []
    replace_original = Path.replace

    def replace_espiado(ruta_temporal: Path, ruta_destino: Path) -> Path:
        observaciones.append(
            {
                "temporal": ruta_temporal,
                "destino": Path(ruta_destino),
                "definitiva_existe_antes": Path(ruta_destino).exists(),
            }
        )
        return replace_original(ruta_temporal, ruta_destino)

    monkeypatch.setattr(Path, "replace", replace_espiado)

    almacen.escribir_meta(COMUNIDAD, FECHA, meta)
    monkeypatch.undo()

    assert len(observaciones) == 1
    assert observaciones[0]["destino"] == ruta_meta
    assert observaciones[0]["temporal"].parent == ruta_meta.parent
    assert observaciones[0]["temporal"].name == ruta_meta.name + ".tmp"
    assert observaciones[0]["definitiva_existe_antes"] is False

    assert isinstance(json.loads(ruta_meta.read_text(encoding="utf-8")), dict)
    assert _ficheros(ruta_meta.parent) == {ruta_meta.name}


def test_meta_fallido_se_escribe_sin_pdf(tmp_path: Path) -> None:
    """Un día fallido tiene `.meta.json` con el motivo y ningún PDF (ALT-003)."""
    almacen = _almacen(tmp_path)

    almacen.escribir_fallido(COMUNIDAD, FECHA, "error HTTP 503")

    datos = _meta_guardado(almacen)
    assert datos["veredicto"] == VEREDICTO_FALLIDO
    assert datos["errores"] == ["error HTTP 503"]
    assert datos["timestamp"]
    assert not almacen.ruta_pdf(COMUNIDAD, FECHA).exists()
    assert _ficheros(tmp_path / COMUNIDAD) == {
        almacen.ruta_meta(COMUNIDAD, FECHA).name
    }


def test_el_meta_incluye_todos_los_campos_del_modelo(tmp_path: Path) -> None:
    """El `.meta.json` contiene los campos del modelo lógico (REQ-005)."""
    almacen = _almacen(tmp_path)
    meta = MetaDia(
        recuento_pdf=92,
        recuento_buscador=93,
        diferencia=1,
        tolerancia_absoluta=1,
        tolerancia_relativa_pct=5,
        umbral_cordura=70,
        veredicto=VEREDICTO_CONCORDANTE,
        errores=[],
        avisos=[{"motivo": "prueba"}],
    )

    almacen.guardar_pdf(COMUNIDAD, FECHA, CONTENIDO, meta)
    datos = _meta_guardado(almacen)

    assert CAMPOS_ESPERADOS <= set(datos)
    assert datos["recuento_pdf"] == 92
    assert datos["recuento_buscador"] == 93
    assert datos["diferencia"] == 1
    assert datos["tolerancia_absoluta"] == 1
    assert datos["tolerancia_relativa_pct"] == 5
    assert datos["umbral_cordura"] == 70
    assert datos["veredicto"] == VEREDICTO_CONCORDANTE
    assert datos["errores"] == []
    assert datos["avisos"] == [{"motivo": "prueba"}]
    assert datos["hash"] == hashlib.sha256(CONTENIDO).hexdigest()
    datetime.fromisoformat(datos["timestamp"])


def test_guardar_pdf_conserva_los_campos_recibidos_y_calcula_hash_y_timestamp(
    tmp_path: Path,
) -> None:
    """El hash y la marca de tiempo se recalculan siempre en el almacén."""
    almacen = _almacen(tmp_path)
    meta = MetaDia(
        recuento_pdf=92,
        veredicto=VEREDICTO_CONCORDANTE,
        hash="hash-inventado",
        timestamp="2000-01-01T00:00:00+00:00",
    )

    guardado = almacen.guardar_pdf(COMUNIDAD, FECHA, CONTENIDO, meta)

    assert guardado.recuento_pdf == 92
    assert guardado.veredicto == VEREDICTO_CONCORDANTE
    assert guardado.hash == hashlib.sha256(CONTENIDO).hexdigest()
    assert guardado.timestamp != "2000-01-01T00:00:00+00:00"


def test_el_timestamp_usa_la_zona_horaria_configurada(tmp_path: Path) -> None:
    """La marca de tiempo se genera con la zona del constructor (NFR-004)."""
    almacen = _almacen(tmp_path, "Asia/Tokyo")

    meta = almacen.guardar_pdf(COMUNIDAD, FECHA, CONTENIDO)

    assert meta.timestamp.endswith("+09:00")
    momento = datetime.fromisoformat(meta.timestamp)
    assert momento.utcoffset().total_seconds() == 9 * 3600


def test_leer_meta_devuelve_los_campos(tmp_path: Path) -> None:
    """La lectura de un `.meta.json` legible devuelve sus campos."""
    almacen = _almacen(tmp_path)
    original = MetaDia(
        recuento_pdf=92,
        recuento_buscador=93,
        diferencia=1,
        tolerancia_absoluta=1,
        tolerancia_relativa_pct=5,
        umbral_cordura=70,
        veredicto=VEREDICTO_CONCORDANTE,
        errores=["fallo leve"],
        avisos=[{"motivo": "prueba"}],
    )
    guardado = almacen.guardar_pdf(COMUNIDAD, FECHA, CONTENIDO, original)

    lectura = almacen.leer_meta(COMUNIDAD, FECHA)

    assert lectura.estado == ESTADO_META_OK
    assert lectura.es_valido is True
    assert lectura.meta == guardado


def test_leer_meta_inexistente_devuelve_estado_ausente(tmp_path: Path) -> None:
    """Sin `.meta.json` la lectura devuelve estado `ausente`, no un día válido."""
    almacen = _almacen(tmp_path)

    lectura = almacen.leer_meta(COMUNIDAD, FECHA)

    assert lectura.estado == ESTADO_META_AUSENTE
    assert lectura.meta is None
    assert lectura.es_valido is False


def test_leer_meta_corrupto_se_comunica_y_deja_el_fichero_intacto(
    tmp_path: Path,
) -> None:
    """Un `.meta.json` ilegible se comunica y no se interpreta como válido."""
    almacen = _almacen(tmp_path)
    ruta_meta = almacen.ruta_meta(COMUNIDAD, FECHA)
    ruta_meta.parent.mkdir(parents=True)
    ruta_meta.write_text('{"hash": "abc", ', encoding="utf-8")
    contenido_previo = ruta_meta.read_bytes()

    lectura = almacen.leer_meta(COMUNIDAD, FECHA)

    assert lectura.estado == ESTADO_META_ILEGIBLE
    assert lectura.meta is None
    assert lectura.es_valido is False
    assert lectura.motivo
    assert ruta_meta.read_bytes() == contenido_previo


@pytest.mark.parametrize(
    "contenido",
    [
        "[]",
        "{}",
        '{"hash": "abc"}',
        '{"hash": 1, "recuento_pdf": "dos"}',
    ],
)
def test_leer_meta_con_contenido_que_no_es_del_modelo_se_comunica(
    tmp_path: Path, contenido: str
) -> None:
    """Un JSON válido con otra forma no se acepta como metadatos del día."""
    almacen = _almacen(tmp_path)
    ruta_meta = almacen.ruta_meta(COMUNIDAD, FECHA)
    ruta_meta.parent.mkdir(parents=True)
    ruta_meta.write_text(contenido, encoding="utf-8")

    lectura = almacen.leer_meta(COMUNIDAD, FECHA)

    assert lectura.estado == ESTADO_META_ILEGIBLE
    assert lectura.meta is None
    assert lectura.es_valido is False


def test_cada_comunidad_tiene_su_propio_arbol(tmp_path: Path) -> None:
    """Dos comunidades guardan el mismo día en carpetas distintas."""
    almacen = _almacen(tmp_path)

    almacen.guardar_pdf(COMUNIDAD, FECHA, CONTENIDO)
    almacen.guardar_pdf(OTRA_COMUNIDAD, FECHA, b"%PDF-1.4 otro contenido")

    assert almacen.ruta_pdf(COMUNIDAD, FECHA).parent == tmp_path / COMUNIDAD
    assert almacen.ruta_pdf(OTRA_COMUNIDAD, FECHA).parent == (
        tmp_path / OTRA_COMUNIDAD
    )


def test_el_almacen_no_crea_ficheros_sqlite(tmp_path: Path) -> None:
    """El almacén no crea ni abre ningún fichero de base de datos (DEC-001)."""
    almacen = _almacen(tmp_path)

    almacen.guardar_pdf(COMUNIDAD, FECHA, CONTENIDO)
    almacen.escribir_fallido(COMUNIDAD, date(2026, 11, 24), "error de descarga")

    sufijos = (".db", ".sqlite", ".sqlite3", ".db-wal", ".db-shm")
    ficheros = [
        fichero
        for fichero in tmp_path.rglob("*")
        if fichero.is_file() and fichero.name.lower().endswith(sufijos)
    ]
    assert ficheros == []
