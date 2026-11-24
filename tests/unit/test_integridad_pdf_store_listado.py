"""Pruebas del PDF huérfano y del listado de PDFs conservados de la integridad.

Cubren TASK-004 sobre `source/api/integridad/pdf_store.py`: la detección del
día incompleto (PDF sin `.meta.json`, ALT-007), la regeneración de los
metadatos con el hash recalculado desde el PDF sin reescribirlo, y el listado
de PDFs conservados con fecha, comunidad, ruta y metadatos disponibles
(REQ-009). Todo se ejecuta sobre `tmp_path`: no se toca ningún directorio
real del proyecto ni se crea ningún fichero SQLite.
"""

import hashlib
from datetime import date
from pathlib import Path

import pytest

from source.api.integridad import pdf_store
from source.api.integridad.pdf_store import (
    VEREDICTO_CONCORDANTE,
    AlmacenPDFs,
    ErrorPDFAusente,
    MetaDia,
    PdfConservado,
)

COMUNIDAD = "cantabria"
OTRA_COMUNIDAD = "madrid"
FECHA = date(2026, 11, 23)
OTRA_FECHA = date(2026, 11, 22)
CONTENIDO = b"%PDF-1.4 contenido de prueba del PDF de difusion\n"


def _almacen(base: Path, zona: str = "Europe/Madrid") -> AlmacenPDFs:
    """Crea un almacén sobre el directorio temporal de la prueba."""
    return AlmacenPDFs(base, zona)


def _escribir_pdf_suelto(
    base: Path, comunidad: str, fecha: date, contenido: bytes = CONTENIDO
) -> Path:
    """Deja un PDF sin `.meta.json`, como una escritura interrumpida."""
    ruta = base / comunidad / f"{fecha.isoformat()}.pdf"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(contenido)
    return ruta


def _nombres(carpeta: Path) -> set[str]:
    """Nombres de los ficheros presentes en una carpeta."""
    return {fichero.name for fichero in carpeta.iterdir() if fichero.is_file()}


def test_pdf_sin_meta_se_detecta_como_huerfano(tmp_path: Path) -> None:
    """Un PDF del día sin `.meta.json` es un día incompleto (ALT-007)."""
    almacen = _almacen(tmp_path)
    _escribir_pdf_suelto(tmp_path, COMUNIDAD, FECHA)

    assert almacen.detectar_huerfano(COMUNIDAD, FECHA) is True


def test_sin_pdf_no_es_huerfano(tmp_path: Path) -> None:
    """Sin PDF no hay día incompleto, aunque tampoco haya metadatos."""
    almacen = _almacen(tmp_path)

    assert almacen.detectar_huerfano(COMUNIDAD, FECHA) is False


def test_pdf_y_meta_completos_no_son_huerfano(tmp_path: Path) -> None:
    """Con el PDF y su `.meta.json` el día está completo."""
    almacen = _almacen(tmp_path)
    almacen.guardar_pdf(COMUNIDAD, FECHA, CONTENIDO)

    assert almacen.detectar_huerfano(COMUNIDAD, FECHA) is False


def test_un_meta_fallido_sin_pdf_no_es_huerfano(tmp_path: Path) -> None:
    """Un día `fallido` tiene metadatos aunque no tenga PDF (ALT-003)."""
    almacen = _almacen(tmp_path)
    almacen.escribir_fallido(COMUNIDAD, FECHA, "error HTTP 503")

    assert almacen.detectar_huerfano(COMUNIDAD, FECHA) is False


def test_regenerar_meta_escribe_el_hash_recalculado_desde_el_pdf(
    tmp_path: Path,
) -> None:
    """Regenerar calcula el hash desde el PDF y deja escritos los metadatos."""
    almacen = _almacen(tmp_path)
    _escribir_pdf_suelto(tmp_path, COMUNIDAD, FECHA)
    assert not almacen.ruta_meta(COMUNIDAD, FECHA).exists()

    regenerado = almacen.regenerar_meta(
        COMUNIDAD,
        FECHA,
        MetaDia(
            recuento_pdf=92,
            recuento_buscador=93,
            diferencia=1,
            tolerancia_absoluta=1,
            tolerancia_relativa_pct=5,
            umbral_cordura=70,
            veredicto=VEREDICTO_CONCORDANTE,
        ),
    )

    lectura = almacen.leer_meta(COMUNIDAD, FECHA)
    assert lectura.es_valido is True
    assert lectura.meta == regenerado
    assert regenerado.hash == hashlib.sha256(CONTENIDO).hexdigest()
    assert regenerado.recuento_pdf == 92
    assert regenerado.recuento_buscador == 93
    assert regenerado.diferencia == 1
    assert regenerado.veredicto == VEREDICTO_CONCORDANTE
    assert regenerado.timestamp
    assert almacen.detectar_huerfano(COMUNIDAD, FECHA) is False


def test_regenerar_meta_no_vuelve_a_escribir_el_pdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La regeneración solo escribe el `.meta.json`, nunca el PDF."""
    almacen = _almacen(tmp_path)
    ruta_pdf = _escribir_pdf_suelto(tmp_path, COMUNIDAD, FECHA)
    mtime_previo = ruta_pdf.stat().st_mtime_ns
    rutas_escritas: list[Path] = []
    escribir_original = pdf_store._escribir_atomico

    def escribir_espiado(ruta: Path, contenido: bytes) -> None:
        rutas_escritas.append(Path(ruta))
        escribir_original(ruta, contenido)

    monkeypatch.setattr(pdf_store, "_escribir_atomico", escribir_espiado)

    almacen.regenerar_meta(COMUNIDAD, FECHA, MetaDia(recuento_pdf=92))

    assert rutas_escritas == [almacen.ruta_meta(COMUNIDAD, FECHA)]
    assert ruta_pdf.read_bytes() == CONTENIDO
    assert ruta_pdf.stat().st_mtime_ns == mtime_previo
    assert _nombres(ruta_pdf.parent) == {
        ruta_pdf.name,
        almacen.ruta_meta(COMUNIDAD, FECHA).name,
    }


def test_regenerar_meta_sin_pdf_lanza_el_error_propio(tmp_path: Path) -> None:
    """Sin PDF no se inventan metadatos: hay un error controlado y propio."""
    almacen = _almacen(tmp_path)

    with pytest.raises(ErrorPDFAusente):
        almacen.regenerar_meta(COMUNIDAD, FECHA, MetaDia(recuento_pdf=92))

    assert not almacen.ruta_meta(COMUNIDAD, FECHA).exists()


def test_listado_devuelve_un_elemento_por_pdf(tmp_path: Path) -> None:
    """El listado devuelve un elemento por PDF con fecha, comunidad y ruta."""
    almacen = _almacen(tmp_path)
    almacen.guardar_pdf(COMUNIDAD, FECHA, CONTENIDO)
    almacen.guardar_pdf(OTRA_COMUNIDAD, OTRA_FECHA, b"%PDF-1.4 otro contenido")
    _escribir_pdf_suelto(tmp_path, COMUNIDAD, OTRA_FECHA)

    conservados = almacen.listar_conservados()

    assert len(conservados) == 3
    assert all(isinstance(elemento, PdfConservado) for elemento in conservados)
    assert {(elemento.comunidad, elemento.fecha) for elemento in conservados} == {
        (COMUNIDAD, FECHA),
        (COMUNIDAD, OTRA_FECHA),
        (OTRA_COMUNIDAD, OTRA_FECHA),
    }
    for elemento in conservados:
        assert elemento.ruta == (
            tmp_path / elemento.comunidad / f"{elemento.fecha.isoformat()}.pdf"
        )
        assert elemento.ruta.is_file()
        assert elemento.ruta.name.startswith(elemento.fecha.isoformat())
        assert elemento.ruta.parent.name == elemento.comunidad


def test_listado_adjunta_los_metadatos_cuando_existen(tmp_path: Path) -> None:
    """Cada elemento lleva su `.meta.json` cuando existe y es legible."""
    almacen = _almacen(tmp_path)
    guardado = almacen.guardar_pdf(
        COMUNIDAD,
        FECHA,
        CONTENIDO,
        MetaDia(
            recuento_pdf=92,
            recuento_buscador=93,
            diferencia=1,
            veredicto=VEREDICTO_CONCORDANTE,
        ),
    )

    (conservado,) = almacen.listar_conservados()

    assert conservado.meta == guardado
    assert conservado.meta.hash == hashlib.sha256(CONTENIDO).hexdigest()
    assert conservado.meta.recuento_pdf == 92
    assert conservado.meta.veredicto == VEREDICTO_CONCORDANTE


def test_listado_sin_metadatos_deja_el_meta_vacio(tmp_path: Path) -> None:
    """Un PDF sin `.meta.json` se lista con `meta` en `None` y sin error."""
    almacen = _almacen(tmp_path)
    _escribir_pdf_suelto(tmp_path, COMUNIDAD, FECHA)

    (conservado,) = almacen.listar_conservados()

    assert conservado.meta is None
    assert conservado.ruta.is_file()


def test_listado_omite_un_meta_ilegible_sin_excluir_el_pdf(
    tmp_path: Path,
) -> None:
    """Un `.meta.json` corrupto se omite en los metadatos, no en el listado."""
    almacen = _almacen(tmp_path)
    _escribir_pdf_suelto(tmp_path, COMUNIDAD, FECHA)
    almacen.ruta_meta(COMUNIDAD, FECHA).write_text(
        '{"hash": "abc", ', encoding="utf-8"
    )
    almacen.guardar_pdf(COMUNIDAD, OTRA_FECHA, CONTENIDO)

    conservados = almacen.listar_conservados()

    assert len(conservados) == 2
    corrupto = next(
        elemento for elemento in conservados if elemento.fecha == FECHA
    )
    correcto = next(
        elemento for elemento in conservados if elemento.fecha == OTRA_FECHA
    )
    assert corrupto.meta is None
    assert corrupto.ruta.is_file()
    assert correcto.meta is not None


@pytest.mark.parametrize("crear_carpeta", [True, False])
def test_listado_sin_pdfs_es_lista_vacia(
    tmp_path: Path, crear_carpeta: bool
) -> None:
    """Un directorio de comunidad vacío o inexistente no produce error."""
    almacen = _almacen(tmp_path)
    if crear_carpeta:
        (tmp_path / COMUNIDAD).mkdir(parents=True)

    assert almacen.listar_conservados() == []


def test_listado_sin_directorio_base_es_lista_vacia(tmp_path: Path) -> None:
    """Sin la ruta base de PDFs el listado es una lista vacía, sin error."""
    almacen = _almacen(tmp_path / "no-existe")

    assert almacen.listar_conservados() == []


def test_listado_ignora_los_nombres_fuera_del_patron(tmp_path: Path) -> None:
    """Solo los nombres `<aaaa-mm-dd>.pdf` cuentan como PDFs conservados."""
    almacen = _almacen(tmp_path)
    carpeta = tmp_path / COMUNIDAD
    carpeta.mkdir(parents=True)
    for nombre in (
        "otro.pdf",
        "2026-1-1.pdf",
        "2026-13-01.pdf",
        "2026-11-23.pdf.bak",
        "2026-11-23.meta.json",
    ):
        (carpeta / nombre).write_bytes(b"%PDF-1.4 ruido")
    _escribir_pdf_suelto(tmp_path, COMUNIDAD, FECHA)

    conservados = almacen.listar_conservados()

    assert len(conservados) == 1
    assert conservados[0].fecha == FECHA
    assert conservados[0].ruta.name == "2026-11-23.pdf"


def test_listado_e_huerfano_no_crean_ficheros_sqlite(tmp_path: Path) -> None:
    """El listado y la regeneración no crean ni abren SQLite (DEC-001)."""
    almacen = _almacen(tmp_path)
    _escribir_pdf_suelto(tmp_path, COMUNIDAD, FECHA)
    almacen.guardar_pdf(OTRA_COMUNIDAD, FECHA, CONTENIDO)

    assert almacen.detectar_huerfano(COMUNIDAD, FECHA) is True
    almacen.regenerar_meta(
        COMUNIDAD,
        FECHA,
        MetaDia(
            recuento_pdf=92,
            recuento_buscador=93,
            diferencia=1,
            veredicto=VEREDICTO_CONCORDANTE,
        ),
    )
    almacen.listar_conservados()

    sufijos = (".db", ".sqlite", ".sqlite3", ".db-wal", ".db-shm")
    ficheros = [
        fichero
        for fichero in tmp_path.rglob("*")
        if fichero.is_file() and fichero.name.lower().endswith(sufijos)
    ]
    assert ficheros == []
