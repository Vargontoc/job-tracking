"""Pruebas unitarias de la purga de HTML fallidos caducados."""

from datetime import date, timedelta
from pathlib import Path

from source.api.buscador.purger import purgar_html_caducados


def _nombre_archivo(codigo: str, fecha: date) -> str:
    """Construye el nombre de archivo según el formato del contrato."""
    return f"{codigo}_{fecha.isoformat()}.html"


def test_elimina_fichero_con_mas_de_7_dias(tmp_path: Path) -> None:
    """Un fichero fechado hace 8 días se elimina."""
    fecha_antigua = date.today() - timedelta(days=8)
    ruta = tmp_path / _nombre_archivo("062026003484", fecha_antigua)
    ruta.write_text("<html>antiguo</html>", encoding="utf-8")

    eliminados = purgar_html_caducados(tmp_path)

    assert not ruta.exists(), "El fichero de hace 8 días debe eliminarse"
    assert ruta in eliminados


def test_conserva_fichero_con_exactamente_7_dias(tmp_path: Path) -> None:
    """Un fichero fechado hace exactamente 7 días se conserva."""
    fecha_limite = date.today() - timedelta(days=7)
    ruta = tmp_path / _nombre_archivo("062026003484", fecha_limite)
    ruta.write_text("<html>límite</html>", encoding="utf-8")

    eliminados = purgar_html_caducados(tmp_path)

    assert ruta.exists(), "El fichero de hace exactamente 7 días debe conservarse"
    assert ruta not in eliminados


def test_conserva_fichero_con_1_dia(tmp_path: Path) -> None:
    """Un fichero fechado hace 1 día se conserva."""
    fecha_reciente = date.today() - timedelta(days=1)
    ruta = tmp_path / _nombre_archivo("062026003484", fecha_reciente)
    ruta.write_text("<html>reciente</html>", encoding="utf-8")

    eliminados = purgar_html_caducados(tmp_path)

    assert ruta.exists(), "El fichero de hace 1 día debe conservarse"
    assert eliminados == []


def test_directorio_inexistente_no_falla(tmp_path: Path) -> None:
    """Con un directorio inexistente, la purga no falla y devuelve lista vacía."""
    directorio_inexistente = tmp_path / "no_existe"
    assert not directorio_inexistente.exists()

    eliminados = purgar_html_caducados(directorio_inexistente)

    assert eliminados == []


def test_directorio_vacio_no_falla(tmp_path: Path) -> None:
    """Con un directorio vacío, la purga no falla y devuelve lista vacía."""
    eliminados = purgar_html_caducados(tmp_path)
    assert eliminados == []


def test_no_toca_ficheros_no_html(tmp_path: Path) -> None:
    """La purga solo afecta a ficheros .html y no toca otros ficheros."""
    # seen_codes.json no debe tocarse
    seen_codes = tmp_path / "seen_codes.json"
    seen_codes.write_text("[]", encoding="utf-8")

    # Un HTML con fecha antigua sí debe eliminarse
    fecha_antigua = date.today() - timedelta(days=30)
    html_antiguo = tmp_path / _nombre_archivo("062026003484", fecha_antigua)
    html_antiguo.write_text("<html>antiguo</html>", encoding="utf-8")

    eliminados = purgar_html_caducados(tmp_path)

    assert seen_codes.exists(), "seen_codes.json no debe tocarse"
    assert not html_antiguo.exists(), "HTML antiguo debe eliminarse"
    assert html_antiguo in eliminados
    assert seen_codes not in eliminados


def test_ignora_ficheros_sin_fecha_en_nombre(tmp_path: Path) -> None:
    """Ficheros .html sin fecha válida en el nombre se ignoran."""
    fichero_sin_fecha = tmp_path / "sin_fecha.html"
    fichero_sin_fecha.write_text("<html>sin fecha</html>", encoding="utf-8")

    eliminados = purgar_html_caducados(tmp_path)

    assert fichero_sin_fecha.exists(), "HTML sin fecha debe ignorarse"
    assert eliminados == []


def test_ignora_ficheros_con_fecha_invalida(tmp_path: Path) -> None:
    """Ficheros con fecha inválida (ej. mes 13) se ignoran sin eliminar."""
    fichero_invalido = tmp_path / "062026003484_2026-13-40.html"
    fichero_invalido.write_text("<html>inválido</html>", encoding="utf-8")

    eliminados = purgar_html_caducados(tmp_path)

    assert fichero_invalido.exists(), "HTML con fecha inválida debe ignorarse"
    assert eliminados == []


def test_ignora_subdirectorios(tmp_path: Path) -> None:
    """Subdirectorios dentro del directorio de fallidos se ignoran."""
    fecha_antigua = date.today() - timedelta(days=30)
    subdirectorio = tmp_path / "subdir"
    subdirectorio.mkdir()
    # Un archivo antiguo dentro del subdirectorio no debe tocarse
    ruta_en_subdir = subdirectorio / _nombre_archivo("062026003484", fecha_antigua)
    ruta_en_subdir.write_text("<html>en subdir</html>", encoding="utf-8")

    eliminados = purgar_html_caducados(tmp_path)

    assert ruta_en_subdir.exists(), "HTML en subdirectorio no debe tocarse"
    assert eliminados == []


def test_elimina_multiples_antiguos_y_conserva_recientes(tmp_path: Path) -> None:
    """Escenario mixto: elimina los antiguos y conserva los recientes."""
    fechas = [
        (date.today() - timedelta(days=1), "reciente1"),
        (date.today() - timedelta(days=7), "limite"),
        (date.today() - timedelta(days=8), "antiguo1"),
        (date.today() - timedelta(days=30), "antiguo2"),
    ]
    rutas_esperadas = {}
    for fecha, etiqueta in fechas:
        ruta = tmp_path / _nombre_archivo(f"062026003{etiqueta[-2:]}", fecha)
        ruta.write_text(f"<html>{etiqueta}</html>", encoding="utf-8")
        rutas_esperadas[etiqueta] = ruta

    eliminados = purgar_html_caducados(tmp_path)

    # Los recientes y el límite se conservan
    assert rutas_esperadas["reciente1"].exists()
    assert rutas_esperadas["limite"].exists()
    # Los antiguos se eliminan
    assert not rutas_esperadas["antiguo1"].exists()
    assert not rutas_esperadas["antiguo2"].exists()
    assert len(eliminados) == 2
    assert rutas_esperadas["antiguo1"] in eliminados
    assert rutas_esperadas["antiguo2"] in eliminados
