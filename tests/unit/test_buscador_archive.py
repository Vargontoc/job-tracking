"""Pruebas unitarias del archivo de HTML de fichas fallidas."""

from pathlib import Path
import pytest

from source.api.buscador.archive import archivar_html_fallido, ErrorArchivado


def test_archiva_html_con_nombre_correcto(tmp_path: Path) -> None:
    """El archivo se crea con el nombre correcto: <codigo>_<fecha>.html"""
    codigo = "062026003484"
    html = "<html><body>Contenido de prueba</body></html>"
    fecha = "2026-01-15"
    
    ruta = archivar_html_fallido(codigo, html, fecha, tmp_path)
    
    assert ruta.name == f"{codigo}_{fecha}.html"
    assert ruta.exists()


def test_contenido_se_guarda_correctamente(tmp_path: Path) -> None:
    """El contenido HTML se guarda correctamente en el archivo."""
    codigo = "062026003633"
    html = "<html><body>Contenido de ficha fallida</body></html>"
    fecha = "2026-01-15"
    
    ruta = archivar_html_fallido(codigo, html, fecha, tmp_path)
    
    contenido = ruta.read_text(encoding="utf-8")
    assert contenido == html


def test_directorio_se_crea_si_no_existe(tmp_path: Path) -> None:
    """Si el directorio no existe, se crea automáticamente."""
    directorio = tmp_path / "failed_htmls"
    assert not directorio.exists()
    
    codigo = "062026003484"
    html = "<html><body>Test</body></html>"
    fecha = "2026-01-15"
    
    ruta = archivar_html_fallido(codigo, html, fecha, directorio)
    
    assert directorio.exists()
    assert ruta.exists()


def test_sobrescribe_si_archivo_ya_existe(tmp_path: Path) -> None:
    """Si el archivo ya existe, se sobrescribe sin error."""
    codigo = "062026003484"
    fecha = "2026-01-15"
    
    # Crear archivo existente con contenido viejo
    ruta_existente = tmp_path / f"{codigo}_{fecha}.html"
    ruta_existente.write_text("contenido viejo", encoding="utf-8")
    
    # Archivar nuevo contenido
    html_nuevo = "<html><body>Contenido nuevo</body></html>"
    ruta = archivar_html_fallido(codigo, html_nuevo, fecha, tmp_path)
    
    contenido = ruta.read_text(encoding="utf-8")
    assert contenido == html_nuevo


def test_error_controlado_si_directorio_no_escribible(tmp_path: Path) -> None:
    """Si no se puede escribir en el directorio, devuelve ErrorArchivado."""
    # Crear un archivo (no un directorio) con el nombre que debería ser el directorio
    archivo_bloqueante = tmp_path / "failed_htmls"
    archivo_bloqueante.write_text("soy un archivo, no un directorio", encoding="utf-8")
    
    codigo = "062026003484"
    html = "<html><body>Test</body></html>"
    fecha = "2026-01-15"
    
    with pytest.raises(ErrorArchivado) as exc_info:
        archivar_html_fallido(codigo, html, fecha, archivo_bloqueante)
    
    assert "No se pudo crear el directorio" in str(exc_info.value)


def test_error_controlado_si_no_se_puede_escribir_archivo(tmp_path: Path) -> None:
    """Si no se puede escribir el archivo, devuelve ErrorArchivado."""
    from unittest.mock import patch
    from pathlib import Path
    
    directorio = tmp_path / "archive"
    codigo = "062026003484"
    html = "<html><body>Test</body></html>"
    fecha = "2026-01-15"
    
    # Simular error de escritura
    with patch.object(Path, 'write_text', side_effect=OSError("Permission denied")):
        with pytest.raises(ErrorArchivado) as exc_info:
            archivar_html_fallido(codigo, html, fecha, directorio)
        
        assert "No se pudo escribir el archivo" in str(exc_info.value)


def test_nombre_usa_fecha_iso_y_codigo_sin_transformaciones(tmp_path: Path) -> None:
    """El nombre del archivo usa fecha ISO y código sin transformaciones."""
    codigo = "062026003633"
    fecha = "2026-12-31"
    
    ruta = archivar_html_fallido(codigo, "<html/>", fecha, tmp_path)
    
    assert ruta.name == "062026003633_2026-12-31.html"


def test_dos_fichas_mismo_codigo_mismo_dia_no_ambiguas(tmp_path: Path) -> None:
    """Archivar dos fichas del mismo código en el mismo día no produce ambigüedad."""
    codigo = "062026003484"
    fecha = "2026-01-15"
    
    # Primera ficha
    html1 = "<html><body>Primera ficha</body></html>"
    ruta1 = archivar_html_fallido(codigo, html1, fecha, tmp_path)
    
    # Segunda ficha (mismo código, misma fecha)
    html2 = "<html><body>Segunda ficha</body></html>"
    ruta2 = archivar_html_fallido(codigo, html2, fecha, tmp_path)
    
    # Ambas rutas son iguales (mismo archivo)
    assert ruta1 == ruta2
    
    # El contenido es el último archivado
    contenido = ruta2.read_text(encoding="utf-8")
    assert contenido == html2
