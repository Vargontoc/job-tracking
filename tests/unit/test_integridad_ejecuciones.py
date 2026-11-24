"""Pruebas del índice de ejecuciones de la integridad del último mes.

Cubren el registro de una ejecución con su marca de tiempo, resultado, errores
por comunidad, veredicto agregado y referencias a los `.meta.json` del día; la
consulta de la ventana de 30 días con sus extremos y su orden descendente; la
escritura atómica sin temporales; la relectura desde disco; el índice ausente,
corrupto o parcialmente ilegible; el uso de la zona horaria configurada
(NFR-004) y la ausencia de ficheros SQLite (DEC-001). Todo se ejecuta sobre
`tmp_path`: no se toca ningún directorio real del proyecto.
"""

import ast
import inspect
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from source.api.integridad import ejecuciones as modulo_ejecuciones
from source.api.integridad.ejecuciones import (
    ESTADO_INDICE_AUSENTE,
    ESTADO_INDICE_ILEGIBLE,
    ESTADO_INDICE_OK,
    Ejecucion,
    IndiceEjecuciones,
)

COMUNIDAD = "cantabria"
OTRA_COMUNIDAD = "madrid"
HOY = date(2026, 11, 23)
TIMESTAMP_HOY = "2026-11-23T02:00:00+01:00"


def _indice(
    base: Path, zona: str = "Europe/Madrid"
) -> IndiceEjecuciones:
    """Crea el índice de ejecuciones sobre el directorio temporal."""
    return IndiceEjecuciones(base, zona)


def _entrada(
    timestamp: str,
    resultado: str = "ok",
    veredicto: str = "concordante",
) -> Ejecucion:
    """Ejecución de prueba que apunta al `.meta.json` del día."""
    return Ejecucion(
        resultado_global=resultado,
        veredicto_agregado=veredicto,
        referencias=[{"fecha": "2026-11-23", "comunidad": COMUNIDAD}],
        timestamp=timestamp,
    )


def _ficheros(carpeta: Path) -> set[str]:
    """Nombres de los ficheros presentes en una carpeta."""
    return {fichero.name for fichero in carpeta.iterdir() if fichero.is_file()}


def _datos(ruta: Path) -> dict:
    """Contenido JSON del índice."""
    return json.loads(ruta.read_text(encoding="utf-8"))


def test_el_indice_se_guarda_en_la_ruta_base(tmp_path: Path) -> None:
    """El índice vive en `<base>/ejecuciones.json` (DEC-001)."""
    indice = _indice(tmp_path)

    assert indice.base == tmp_path
    assert indice.ruta_indice == tmp_path / "ejecuciones.json"


def test_registrar_crea_el_indice_con_la_entrada_completa(
    tmp_path: Path,
) -> None:
    """La entrada guarda sus cinco campos y la referencia al día (REQ-008)."""
    indice = _indice(tmp_path)
    entrada = _entrada(TIMESTAMP_HOY, "ok", "concordante")

    guardada = indice.registrar(entrada)

    datos = _datos(indice.ruta_indice)
    assert datos["version"] == 1
    assert datos["ejecuciones"] == [entrada.a_diccionario()]
    assert datos["ejecuciones"][0] == {
        "timestamp": TIMESTAMP_HOY,
        "resultado_global": "ok",
        "errores_por_comunidad": [],
        "veredicto_agregado": "concordante",
        "referencias": [{"fecha": "2026-11-23", "comunidad": COMUNIDAD}],
    }
    assert guardada == entrada


def test_registrar_genera_el_timestamp_si_falta(tmp_path: Path) -> None:
    """Sin marca de tiempo, se genera en la zona configurada (NFR-004)."""
    indice = _indice(tmp_path)

    guardada = indice.registrar(Ejecucion(resultado_global="ok"))

    assert guardada.timestamp
    momento = datetime.fromisoformat(guardada.timestamp)
    assert momento.utcoffset() == datetime.now(
        ZoneInfo("Europe/Madrid")
    ).utcoffset()
    assert _datos(indice.ruta_indice)["ejecuciones"][0]["timestamp"] == (
        guardada.timestamp
    )


def test_la_ventana_del_ultimo_mes_es_inclusiva_y_excluye_lo_anterior(
    tmp_path: Path,
) -> None:
    """Entran hoy y hoy - 30 días; no entra hoy - 31 días (REQ-009)."""
    indice = _indice(tmp_path)
    dentro_hoy = _entrada(TIMESTAMP_HOY)
    dentro_limite = _entrada("2026-10-24T02:00:00+01:00")
    fuera = _entrada("2026-10-23T02:00:00+01:00")
    indice.registrar(dentro_hoy)
    indice.registrar(dentro_limite)
    indice.registrar(fuera)

    consultadas = indice.consultar_ultimo_mes(HOY)

    assert consultadas == [dentro_hoy, dentro_limite]


def test_la_consulta_ordena_de_mas_reciente_a_mas_antigua(
    tmp_path: Path,
) -> None:
    """Registradas en cualquier orden, se devuelven de reciente a viejo."""
    indice = _indice(tmp_path)
    primero = _entrada("2026-11-20T02:00:00+01:00")
    ultimo = _entrada("2026-11-22T02:00:00+01:00")
    intermedio = _entrada("2026-11-21T02:00:00+01:00")
    for ejecucion in (primero, ultimo, intermedio):
        indice.registrar(ejecucion)

    consultadas = indice.consultar_ultimo_mes(HOY)

    assert consultadas == [ultimo, intermedio, primero]


def test_la_consulta_ordena_por_instante_convertido_a_la_zona(
    tmp_path: Path,
) -> None:
    """Marcas de tiempo con distinto desfase se ordenan por su instante."""
    indice = _indice(tmp_path)
    anterior = _entrada("2026-11-23T02:00:00+01:00")
    posterior = _entrada("2026-11-23T03:30:00+00:00")
    indice.registrar(anterior)
    indice.registrar(posterior)

    consultadas = indice.consultar_ultimo_mes(HOY)

    assert consultadas == [posterior, anterior]


def test_la_ventana_admite_datetime_ademas_de_date(tmp_path: Path) -> None:
    """Un `datetime` se reduce a su fecha al consultar la ventana."""
    indice = _indice(tmp_path)
    entrada = _entrada(TIMESTAMP_HOY)
    indice.registrar(entrada)

    consultadas = indice.consultar_ultimo_mes(
        datetime(2026, 11, 23, 23, 0, tzinfo=ZoneInfo("Europe/Madrid"))
    )

    assert consultadas == [entrada]


def test_una_ejecucion_con_errores_parciales_guarda_comunidad_y_mensaje(
    tmp_path: Path,
) -> None:
    """Cada error por comunidad guarda comunidad y mensaje (REQ-008)."""
    indice = _indice(tmp_path)
    ejecucion = Ejecucion(
        resultado_global="parcial",
        veredicto_agregado="fallido",
        errores_por_comunidad=[
            {"comunidad": COMUNIDAD, "mensaje": "error HTTP 503"}
        ],
        referencias=[
            {"fecha": "2026-11-23", "comunidad": COMUNIDAD},
            {"fecha": "2026-11-23", "comunidad": OTRA_COMUNIDAD},
        ],
        timestamp=TIMESTAMP_HOY,
    )

    indice.registrar(ejecucion)

    entrada = _datos(indice.ruta_indice)["ejecuciones"][0]
    assert entrada["errores_por_comunidad"] == [
        {"comunidad": COMUNIDAD, "mensaje": "error HTTP 503"}
    ]
    assert entrada["referencias"] == [
        {"fecha": "2026-11-23", "comunidad": COMUNIDAD},
        {"fecha": "2026-11-23", "comunidad": OTRA_COMUNIDAD},
    ]
    assert indice.leer().ejecuciones == [ejecucion]


def test_la_escritura_es_atomica_y_no_deja_temporales(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El índice se escribe en un temporal y se renombra (DEC-001)."""
    indice = _indice(tmp_path)
    ruta = indice.ruta_indice
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

    indice.registrar(_entrada(TIMESTAMP_HOY))
    monkeypatch.undo()

    assert len(observaciones) == 1
    observada = observaciones[0]
    assert observada["destino"] == ruta
    assert observada["temporal"].parent == ruta.parent
    assert observada["temporal"].name == ruta.name + ".tmp"
    assert observada["definitiva_existe_antes"] is False
    assert json.loads(observada["contenido"]) == _datos(ruta)
    assert _ficheros(tmp_path) == {ruta.name}


def test_releer_desde_disco_devuelve_las_mismas_entradas(
    tmp_path: Path,
) -> None:
    """Otra instancia sobre la misma base lee lo mismo que se registró."""
    indice = _indice(tmp_path)
    primera = indice.registrar(_entrada("2026-11-21T02:00:00+01:00"))
    segunda = indice.registrar(_entrada("2026-11-22T02:00:00+01:00"))

    lectura = _indice(tmp_path).leer()

    assert lectura.estado == ESTADO_INDICE_OK
    assert lectura.es_valido
    assert lectura.ejecuciones == [primera, segunda]


def test_un_indice_ausente_se_lee_como_indice_vacio_valido(
    tmp_path: Path,
) -> None:
    """Sin fichero, la lectura es un índice vacío válido (REQ-009)."""
    indice = _indice(tmp_path)

    lectura = indice.leer()

    assert lectura.estado == ESTADO_INDICE_AUSENTE
    assert lectura.es_valido
    assert lectura.ejecuciones == []
    assert indice.consultar_ultimo_mes(HOY) == []
    assert not indice.ruta_indice.exists()


@pytest.mark.parametrize(
    "contenido",
    [
        '{"version": 1, "ejecuciones": [',
        "no es json",
        "[]",
        '{"version": 1}',
    ],
    ids=["json-truncado", "texto-suelto", "raiz-lista", "sin-ejecuciones"],
)
def test_un_indice_corrupto_se_comunica_sin_modificar_el_fichero(
    tmp_path: Path, contenido: str
) -> None:
    """Un índice ilegible se comunica y no se trata como uno válido."""
    indice = _indice(tmp_path)
    indice.ruta_indice.write_text(contenido, encoding="utf-8")
    escrito = indice.ruta_indice.read_bytes()

    lectura = indice.leer()

    assert lectura.estado == ESTADO_INDICE_ILEGIBLE
    assert not lectura.es_valido
    assert lectura.ejecuciones == []
    assert lectura.motivo
    assert indice.consultar_ultimo_mes(HOY) == []
    assert indice.ruta_indice.read_bytes() == escrito


def test_un_indice_corrupto_no_impide_registrar_una_ejecucion(
    tmp_path: Path,
) -> None:
    """Tras un índice corrupto, registrar lo reescribe con la entrada nueva."""
    indice = _indice(tmp_path)
    indice.ruta_indice.write_text(
        '{"version": 1, "ejecuciones": [', encoding="utf-8"
    )

    guardada = indice.registrar(_entrada(TIMESTAMP_HOY))

    lectura = indice.leer()
    assert lectura.estado == ESTADO_INDICE_OK
    assert lectura.ejecuciones == [guardada]


def test_al_reescribir_conserva_las_entradas_recuperables(
    tmp_path: Path,
) -> None:
    """Una entrada válida junto a una ilegible se conserva al registrar."""
    indice = _indice(tmp_path)
    recuperable = _entrada("2026-11-21T02:00:00+01:00")
    indice.ruta_indice.write_text(
        json.dumps(
            {
                "version": 1,
                "ejecuciones": [
                    recuperable.a_diccionario(),
                    {"timestamp": 42},
                ],
            }
        ),
        encoding="utf-8",
    )

    lectura = indice.leer()
    nueva = indice.registrar(_entrada("2026-11-23T02:00:00+01:00"))

    assert lectura.estado == ESTADO_INDICE_ILEGIBLE
    assert lectura.ejecuciones == [recuperable]
    assert "1 entradas ilegibles" in lectura.motivo
    assert indice.leer().ejecuciones == [recuperable, nueva]


def test_el_timestamp_usa_la_zona_configurada_y_no_la_del_sistema(
    tmp_path: Path,
) -> None:
    """La marca de tiempo usa la zona configurada y no la del sistema."""
    indice = _indice(tmp_path, "Pacific/Kiritimati")
    local_antes = datetime.now(ZoneInfo("Pacific/Kiritimati"))

    guardada = indice.registrar(Ejecucion(resultado_global="ok"))

    momento = datetime.fromisoformat(guardada.timestamp)
    assert momento.utcoffset() == timedelta(hours=14)
    assert guardada.timestamp.endswith("+14:00")
    assert momento.utcoffset() != datetime.now(
        ZoneInfo("Europe/Madrid")
    ).utcoffset()
    assert abs((momento - local_antes).total_seconds()) < 120


def test_registrar_crea_la_ruta_base_si_no_existe(tmp_path: Path) -> None:
    """La ruta base de PDFs se crea si todavía no existe."""
    base = tmp_path / "data" / "pdfs"
    indice = _indice(base)

    indice.registrar(_entrada(TIMESTAMP_HOY))

    assert indice.ruta_indice == base / "ejecuciones.json"
    assert indice.ruta_indice.is_file()


def test_el_indice_no_crea_ficheros_sqlite(tmp_path: Path) -> None:
    """Registrar y consultar no crea ningún fichero SQLite (DEC-001)."""
    indice = _indice(tmp_path)

    indice.registrar(_entrada(TIMESTAMP_HOY))
    indice.consultar_ultimo_mes(HOY)

    sufijos = (".db", ".sqlite", ".sqlite3", ".db-wal", ".db-shm")
    ficheros = [
        fichero
        for fichero in tmp_path.rglob("*")
        if fichero.is_file() and fichero.name.lower().endswith(sufijos)
    ]
    assert ficheros == []


def test_el_modulo_no_importa_sqlite() -> None:
    """El módulo no importa SQLite ni un motor de base de datos."""
    arbol = ast.parse(inspect.getsource(modulo_ejecuciones))
    importados: set[str] = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            importados.update(alias.name for alias in nodo.names)
        elif isinstance(nodo, ast.ImportFrom) and nodo.module:
            importados.add(nodo.module)

    prohibidos = ("sqlite3", "sqlalchemy", "psycopg", "mysql")
    for nombre in importados:
        assert not any(
            prohibido in nombre.lower() for prohibido in prohibidos
        ), nombre
