"""Pruebas de la purga de PDFs y metadatos por la fecha del nombre.

Cubren TASK-005 sobre `source/api/integridad/purger.py`: `purgar(base,
dias_retencion, hoy)` elimina cada `<aaaa-mm-dd>.pdf` y su
`<aaaa-mm-dd>.meta.json` cuando la fecha del nombre queda fuera de la ventana
de retención (REQ-002), decide solo por esa fecha y nunca por el `mtime`
(DEC-004), conserva el día en curso y la antigüedad exactamente igual a la
retención, purga igual el PDF con parseo fallido (DEC-002) e ignora los
nombres que no siguen el patrón. Todo se ejecuta sobre `tmp_path`: no se toca
ningún directorio real del proyecto ni se crea ningún fichero SQLite.
"""

import json
import os
import time
from datetime import date, timedelta
from pathlib import Path

from source.api.integridad.purger import purgar

COMUNIDAD = "cantabria"
OTRA_COMUNIDAD = "madrid"
HOY = date(2026, 11, 23)
CONTENIDO = b"%PDF-1.4 contenido de prueba del PDF de difusion\n"


def _escribir_dia(
    base: Path,
    comunidad: str,
    fecha: date,
    veredicto: str = "concordante",
) -> tuple[Path, Path]:
    """Deja el PDF de un día y su `.meta.json`, como los guarda `pdf-store`."""
    carpeta = base / comunidad
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta_pdf = carpeta / f"{fecha.isoformat()}.pdf"
    ruta_meta = carpeta / f"{fecha.isoformat()}.meta.json"
    ruta_pdf.write_bytes(CONTENIDO)
    ruta_meta.write_text(
        json.dumps({"veredicto": veredicto, "recuento_pdf": 92}),
        encoding="utf-8",
    )
    return ruta_pdf, ruta_meta


def _nombres(carpeta: Path) -> set[str]:
    """Nombres de los ficheros presentes en una carpeta."""
    return {fichero.name for fichero in carpeta.iterdir() if fichero.is_file()}


def _ficheros_sqlite(base: Path) -> list[Path]:
    """Ficheros con aspecto de base de datos SQLite bajo la ruta base."""
    sufijos = (".db", ".sqlite", ".sqlite3", ".db-wal", ".db-shm")
    return [
        fichero
        for fichero in base.rglob("*")
        if fichero.is_file() and fichero.name.lower().endswith(sufijos)
    ]


def test_mas_de_la_ventana_elimina_el_pdf_y_sus_metadatos(
    tmp_path: Path,
) -> None:
    """Con más días que la retención desaparecen el PDF y su `.meta.json`."""
    antiguo = HOY - timedelta(days=40)
    ruta_pdf, ruta_meta = _escribir_dia(tmp_path, COMUNIDAD, antiguo)

    eliminados = purgar(tmp_path, 30, HOY)

    assert set(eliminados) == {ruta_pdf, ruta_meta}
    assert len(eliminados) == 2
    assert not ruta_pdf.exists()
    assert not ruta_meta.exists()
    assert _nombres(tmp_path / COMUNIDAD) == set()


def test_exactamente_la_ventana_se_conserva(tmp_path: Path) -> None:
    """La ventana es inclusiva: 30 días de antigüedad se conservan."""
    justo_en_la_ventana = HOY - timedelta(days=30)
    ruta_pdf, ruta_meta = _escribir_dia(tmp_path, COMUNIDAD, justo_en_la_ventana)

    eliminados = purgar(tmp_path, 30, HOY)

    assert eliminados == []
    assert ruta_pdf.is_file()
    assert ruta_meta.is_file()


def test_dentro_de_la_ventana_se_conserva(tmp_path: Path) -> None:
    """Un día reciente se conserva con sus metadatos."""
    reciente = HOY - timedelta(days=5)
    ruta_pdf, ruta_meta = _escribir_dia(tmp_path, COMUNIDAD, reciente)

    eliminados = purgar(tmp_path, 30, HOY)

    assert eliminados == []
    assert ruta_pdf.is_file()
    assert ruta_meta.is_file()


def test_el_dia_en_curso_nunca_se_elimina(tmp_path: Path) -> None:
    """Ni con retención cero ni con una fecha futura se borra el día de hoy."""
    ruta_pdf, ruta_meta = _escribir_dia(tmp_path, COMUNIDAD, HOY)
    futuro_pdf, futuro_meta = _escribir_dia(
        tmp_path, COMUNIDAD, HOY + timedelta(days=1)
    )

    eliminados = purgar(tmp_path, 0, HOY)

    assert eliminados == []
    for ruta in (ruta_pdf, ruta_meta, futuro_pdf, futuro_meta):
        assert ruta.is_file()


def test_decide_por_el_nombre_y_no_por_el_mtime(tmp_path: Path) -> None:
    """La antigüedad sale del nombre: el `mtime` no cambia la decisión."""
    antiguo = HOY - timedelta(days=40)
    reciente = HOY - timedelta(days=5)
    ruta_antigua, meta_antigua = _escribir_dia(tmp_path, COMUNIDAD, antiguo)
    ruta_reciente, _ = _escribir_dia(tmp_path, COMUNIDAD, reciente)

    # El fichero antiguo tiene una marca de modificación de ahora mismo...
    ahora = time.time()
    os.utime(ruta_antigua, (ahora, ahora))
    # ...y el reciente, una de 1970 (DEC-004).
    os.utime(ruta_reciente, (0, 0))

    eliminados = purgar(tmp_path, 30, HOY)

    assert set(eliminados) == {ruta_antigua, meta_antigua}
    assert not ruta_antigua.exists()
    assert ruta_reciente.is_file()


def test_la_retencion_configurada_de_7_dias_se_aplica(tmp_path: Path) -> None:
    """Con `dias_retencion=7` se conservan 7 días y se elimina el octavo."""
    dentro = HOY - timedelta(days=7)
    fuera = HOY - timedelta(days=8)
    ruta_dentro, _ = _escribir_dia(tmp_path, COMUNIDAD, dentro)
    ruta_fuera, meta_fuera = _escribir_dia(tmp_path, COMUNIDAD, fuera)

    eliminados = purgar(tmp_path, 7, HOY)

    assert set(eliminados) == {ruta_fuera, meta_fuera}
    assert ruta_dentro.is_file()
    assert not ruta_fuera.exists()
    assert not meta_fuera.exists()


def test_el_pdf_con_parseo_fallido_se_purga_con_el_mismo_plazo(
    tmp_path: Path,
) -> None:
    """Un día con veredicto `fallido` se purga igual que uno correcto (DEC-002)."""
    fallido = HOY - timedelta(days=35)
    ruta_pdf, ruta_meta = _escribir_dia(
        tmp_path, COMUNIDAD, fallido, veredicto="fallido"
    )

    eliminados = purgar(tmp_path, 30, HOY)

    assert set(eliminados) == {ruta_pdf, ruta_meta}
    assert not ruta_pdf.exists()
    assert not ruta_meta.exists()


def test_los_nombres_fuera_del_patron_no_se_tocan(tmp_path: Path) -> None:
    """Solo los nombres `<aaaa-mm-dd>.pdf` y `.meta.json` entran en la purga."""
    carpeta = tmp_path / COMUNIDAD
    carpeta.mkdir(parents=True)
    ajenos = [
        "otro.pdf",
        "2026-1-1.pdf",
        "2026-13-01.pdf",
        "2026-11-23.pdf.bak",
        "2026-11-23.meta.json.bak",
        "notas.txt",
    ]
    for nombre in ajenos:
        (carpeta / nombre).write_bytes(CONTENIDO)

    eliminados = purgar(tmp_path, 30, HOY)

    assert eliminados == []
    assert _nombres(carpeta) == set(ajenos)


def test_sin_directorio_base_ni_comunidades_no_falla(tmp_path: Path) -> None:
    """Una ruta base inexistente o vacía devuelve una lista vacía sin error."""
    assert purgar(tmp_path / "no-existe", 30, HOY) == []

    (tmp_path / COMUNIDAD).mkdir()
    assert purgar(tmp_path, 30, HOY) == []
    assert (tmp_path / COMUNIDAD).is_dir()


def test_la_purga_recorre_todas_las_comunidades_sin_borrar_directorios(
    tmp_path: Path,
) -> None:
    """Cada comunidad se purga por separado y su directorio permanece."""
    antiguo = HOY - timedelta(days=45)
    reciente = HOY - timedelta(days=2)
    pdf_antiguo, meta_antiguo = _escribir_dia(tmp_path, COMUNIDAD, antiguo)
    pdf_reciente, _ = _escribir_dia(tmp_path, OTRA_COMUNIDAD, reciente)
    _escribir_dia(tmp_path, OTRA_COMUNIDAD, antiguo)

    eliminados = purgar(tmp_path, 30, HOY)

    assert set(eliminados) == {
        pdf_antiguo,
        meta_antiguo,
        tmp_path / OTRA_COMUNIDAD / f"{antiguo.isoformat()}.pdf",
        tmp_path / OTRA_COMUNIDAD / f"{antiguo.isoformat()}.meta.json",
    }
    assert pdf_reciente.is_file()
    assert (tmp_path / COMUNIDAD).is_dir()
    assert (tmp_path / OTRA_COMUNIDAD).is_dir()


def test_la_purga_no_crea_ni_abre_sqlite(tmp_path: Path) -> None:
    """La purga solo trabaja sobre los ficheros del árbol (DEC-001)."""
    _escribir_dia(tmp_path, COMUNIDAD, HOY - timedelta(days=40))
    _escribir_dia(tmp_path, OTRA_COMUNIDAD, HOY)

    purgar(tmp_path, 30, HOY)

    assert _ficheros_sqlite(tmp_path) == []
