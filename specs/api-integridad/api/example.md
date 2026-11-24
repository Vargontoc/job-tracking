# Ejemplos de uso: config-integridad

## Componente: `config-integridad` (`config/integridad.yaml` y `source/api/integridad/config.py`)

Carga y validación de la configuración de la comprobación diaria de integridad del PDF de difusión. El fichero `config/integridad.yaml` contiene la zona horaria, la hora de ejecución, el margen de catch-up en minutos, los días de retención de los PDFs, la tolerancia absoluta, la tolerancia relativa en porcentaje, el umbral de cordura, la ruta base de los PDFs, la URL base del buscador y, opcionalmente, las comunidades. `cargar_configuracion(ruta)` devuelve un `ConfigIntegridad`; si el fichero no existe aplica los valores por defecto y toma las comunidades de `config/comunidades.yaml`; un YAML malformado, una raíz o un submapa que no sea mapa, un tipo incorrecto, una zona horaria inválida, una hora fuera de 0-23 o un valor negativo lanzan `ErrorConfiguracionIntegridad` identificando el campo problemático. No contiene rutas de servidor de base de datos ni credenciales.

## Ejemplo: cargar la configuración con los valores por defecto

```python
from source.api.integridad.config import cargar_configuracion

# Sin argumentos se lee `config/integridad.yaml` desde la raíz del proyecto.
config = cargar_configuracion()

print(config.zona_horaria)           # "Europe/Madrid"
print(config.hora_ejecucion)         # 2 (02:00)
print(config.margen_catchup)         # 60 minutos
print(config.dias_retencion)         # 30 días
print(config.tolerancia_absoluta)    # 1 oferta
print(config.tolerancia_relativa_pct)  # 5 %
print(config.umbral_cordura)         # 70 ofertas
print(config.ruta_base_pdfs)         # "data/pdfs"
print(config.url_base_buscador)      # "http://localhost:8000"
for comunidad in config.comunidades:
    print(comunidad.identificador, comunidad.url_pdf)
```

## Ejemplo: calcular la fecha local con la zona configurada

```python
from datetime import datetime

from source.api.integridad.config import cargar_configuracion

config = cargar_configuracion()

# `config.zona` devuelve la ZoneInfo configurada (NFR-004).
ahora_local = datetime.now(config.zona)
print(f"Día en curso: {ahora_local.date().isoformat()}")
print(f"Zona: {config.zona.key}")
```

## Ejemplo: leer un fichero de configuración alternativo

```python
from pathlib import Path

from source.api.integridad.config import cargar_configuracion

# Cargar otra ruta (por ejemplo, la de las pruebas).
config = cargar_configuracion(Path("tests/fixtures/integridad.yaml"))
print(config.hora_ejecucion, config.margen_catchup)
```

## Ejemplo: tratar una configuración inválida

```python
from source.api.integridad.config import (
    ErrorConfiguracionIntegridad,
    cargar_configuracion,
)

try:
    config = cargar_configuracion()
except ErrorConfiguracionIntegridad as error:
    # El mensaje nombra el campo problemático (zona, hora, margen, rutas...).
    print(f"Configuración de la integridad no válida: {error}")
```

## Componente: `pdf-store` (`source/api/integridad/pdf_store.py`)

Almacén en disco de los PDFs de difusión y de sus metadatos. Guarda el árbol `<base>/<comunidad>/<aaaa-mm-dd>.pdf` con su fichero asociado `<aaaa-mm-dd>.meta.json`. `AlmacenPDFs(base, zona_horaria)` expone `ruta_pdf(comunidad, fecha)` y `ruta_meta(comunidad, fecha)`, guarda el PDF de forma atómica (temporal en el mismo directorio y `replace`) calculando su SHA-256, escribe el `.meta.json` con los campos del día (`hash`, `recuento_pdf`, `recuento_buscador`, `diferencia`, `tolerancia_absoluta`, `tolerancia_relativa_pct`, `umbral_cordura`, `veredicto`, `errores`, `avisos` y `timestamp` en la zona configurada) y registra un día `fallido` sin PDF cuando la descarga falla. `leer_meta(...)` devuelve un `LecturaMeta` con estado `ok`, `ausente` o `ilegible`, de modo que un `.meta.json` corrupto nunca se confunde con un día válido. `detectar_huerfano(...)` informa del día incompleto (hay PDF y falta el `.meta.json`), `regenerar_meta(...)` reescribe los metadatos recalculando el hash desde el PDF existente sin volver a escribir el PDF (lanza `ErrorPDFAusente` si el PDF no se puede leer) y `listar_conservados()` devuelve un `PdfConservado` por PDF con su `comunidad`, `fecha`, `ruta` y su `meta` opcional. No usa SQLite.

## Ejemplo: guardar el PDF del día con sus metadatos

```python
from datetime import date

from source.api.integridad.pdf_store import AlmacenPDFs, MetaDia

# La ruta base y la zona horaria vienen de `config/integridad.yaml`.
almacen = AlmacenPDFs("data/pdfs", "Europe/Madrid")

hoy = date(2026, 11, 23)
contenido = b"%PDF-1.4 ..."  # bytes devueltos por el adaptador de descarga

meta = MetaDia(
    recuento_pdf=92,
    recuento_buscador=93,
    diferencia=1,
    tolerancia_absoluta=1,
    tolerancia_relativa_pct=5,
    umbral_cordura=70,
    veredicto="concordante",
)

guardado = almacen.guardar_pdf("cantabria", hoy, contenido, meta)
print(guardado.hash)       # SHA-256 del contenido del PDF
print(guardado.timestamp)  # Marca de tiempo ISO 8601 en Europe/Madrid

print(almacen.ruta_pdf("cantabria", hoy))   # data/pdfs/cantabria/2026-11-23.pdf
print(almacen.ruta_meta("cantabria", hoy))  # data/pdfs/cantabria/2026-11-23.meta.json
```

## Ejemplo: leer los metadatos del día sin aceptar un fichero corrupto

```python
from datetime import date

from source.api.integridad.pdf_store import AlmacenPDFs

almacen = AlmacenPDFs("data/pdfs", "Europe/Madrid")

lectura = almacen.leer_meta("cantabria", date(2026, 11, 23))
if lectura.es_valido:
    print(lectura.meta.veredicto, lectura.meta.recuento_pdf)
elif lectura.estado == "ausente":
    print("No hay comprobación de ese día")
else:  # "ilegible": el fichero se deja intacto y no se trata como día válido
    print(f"Metadatos corruptos: {lectura.motivo}")
```

## Ejemplo: registrar un día fallido sin conservar PDF

```python
from datetime import date

from source.api.integridad.pdf_store import AlmacenPDFs

almacen = AlmacenPDFs("data/pdfs", "Europe/Madrid")

# La descarga del PDF falló: queda el motivo y ningún PDF asociado (ALT-003).
meta = almacen.escribir_fallido(
    "cantabria",
    date(2026, 11, 23),
    "error HTTP 503 al descargar el PDF",
)
print(meta.veredicto)  # "fallido"
print(meta.errores)    # ["error HTTP 503 al descargar el PDF"]
```

## Ejemplo: detectar y completar un PDF huérfano

```python
from datetime import date

from source.api.integridad.pdf_store import (
    AlmacenPDFs,
    ErrorPDFAusente,
    MetaDia,
)

almacen = AlmacenPDFs("data/pdfs", "Europe/Madrid")
hoy = date(2026, 11, 23)

# Existe el PDF del día pero no su .meta.json: el día está incompleto (ALT-007).
if almacen.detectar_huerfano("cantabria", hoy):
    print("Día incompleto: hay PDF sin metadatos")

    # El hash se recalcula desde el PDF existente; el PDF no se reescribe.
    try:
        meta = almacen.regenerar_meta(
            "cantabria",
            hoy,
            MetaDia(recuento_pdf=92, veredicto="concordante"),
        )
    except ErrorPDFAusente as error:
        print(f"No se puede regenerar: {error}")
    else:
        print(meta.hash, meta.timestamp)
```

## Ejemplo: listar los PDFs conservados con sus metadatos

```python
from source.api.integridad.pdf_store import AlmacenPDFs

almacen = AlmacenPDFs("data/pdfs", "Europe/Madrid")

for conservado in almacen.listar_conservados():
    print(conservado.comunidad)        # "cantabria"
    print(conservado.fecha)            # date(2026, 11, 23)
    print(conservado.ruta)             # data/pdfs/cantabria/2026-11-23.pdf
    if conservado.meta is None:
        # Sin .meta.json (día incompleto) o con metadatos ilegibles: el PDF
        # se lista igualmente, sin datos de metadatos.
        print("Sin metadatos disponibles")
    else:
        print(conservado.meta.veredicto, conservado.meta.recuento_pdf)
```

## Componente: `pdf-purger` (`source/api/integridad/purger.py`)

Purga del árbol de PDFs por antigüedad. `purgar(base, dias_retencion, hoy)` recorre `<base>/<comunidad>/` y elimina cada `<aaaa-mm-dd>.pdf` junto con su `<aaaa-mm-dd>.meta.json` cuando la fecha **del nombre** queda fuera de la ventana de retención, y devuelve la lista de rutas eliminadas. La antigüedad se decide solo por esa fecha y nunca por el `mtime` (DEC-004), de modo que una copia restaurada no desplaza la ventana. La ventana es inclusiva: un día con exactamente `dias_retencion` de antigüedad se conserva, y el día en curso (`fecha >= hoy`) no se elimina nunca. Los nombres que no siguen el patrón `<aaaa-mm-dd>.pdf` o `<aaaa-mm-dd>.meta.json` se ignoran, no se borra ningún directorio y un PDF con veredicto `fallido` se purga con el mismo plazo que los demás (DEC-002). Si la ruta base no existe, devuelve una lista vacía sin error. No usa SQLite: la tarea diaria le pasa `hoy` ya calculado en la zona horaria configurada.

## Ejemplo: purgar los PDFs fuera de la retención

```python
from datetime import date

from source.api.integridad.purger import purgar

hoy = date(2026, 11, 23)  # la tarea diaria lo calcula en la zona configurada

# Conserva 30 días: se eliminan los PDFs y metadatos anteriores al 24/10/2026.
eliminados = purgar("data/pdfs", 30, hoy)

for ruta in eliminados:
    print(ruta)  # data/pdfs/cantabria/2026-10-14.pdf, ...2026-10-14.meta.json
```

## Ejemplo: purgar con una retención distinta

```python
from datetime import date

from source.api.integridad.config import cargar_configuracion
from source.api.integridad.purger import purgar

config = cargar_configuracion()

# La retención y la ruta base salen de `config/integridad.yaml`.
eliminados = purgar(
    config.ruta_base_pdfs,
    config.dias_retencion,
    date(2026, 11, 23),
)
print(f"Ficheros purgados: {len(eliminados)}")
```

## Componente: `downloader-adapter` (`source/api/integridad/downloader_adapter.py`)

Adaptador de descarga del PDF de difusión. `AdaptadorDescarga` envuelve el descargador existente de `api-pdf-parser` (`source/api/downloader.descargar_pdf`) y lo invoca **en proceso**, sin reimplementar la descarga y sin llamar al endpoint `GET /parse` ni a ningún otro endpoint de la API (SUP-005). `descargar(url)` devuelve los bytes del PDF (REQ-001) o un `ErrorDescargaIntegridad` con un `mensaje` (y su alias `motivo`) que conserva el mensaje del descargador; los fallos HTTP, de tiempo de espera agotado y de conexión llegan así, como resultado controlado y sin lanzar excepción (ALT-003). El error es propio de la integridad y distinguible del `ErrorParseoIntegridad`. El adaptador no escribe nada en disco: la escritura del PDF y de sus metadatos es del almacén (`pdf-store`). El descargador y el cliente `httpx` son inyectables, para usar un doble o un `httpx.Client` de prueba.

## Ejemplo: descargar el PDF de difusión de una comunidad

```python
from source.api.integridad.config import cargar_configuracion
from source.api.integridad.downloader_adapter import AdaptadorDescarga

config = cargar_configuracion()
comunidad = config.comunidades[0]  # p. ej. "cantabria" y su url_pdf

adaptador = AdaptadorDescarga()
resultado = adaptador.descargar(comunidad.url_pdf)

if isinstance(resultado, bytes):
    print(f"PDF de {comunidad.identificador}: {len(resultado)} bytes")
    # La escritura en data/pdfs/<comunidad>/<aaaa-mm-dd>.pdf es de `pdf-store`.
```

## Ejemplo: tratar un fallo de descarga sin excepciones

```python
from source.api.integridad.downloader_adapter import (
    AdaptadorDescarga,
    ErrorDescargaIntegridad,
)

adaptador = AdaptadorDescarga()
resultado = adaptador.descargar(
    "https://ejemplo.test/SNE_ListadoOfertasDifusionWEB/difusion.pdf"
)

if isinstance(resultado, ErrorDescargaIntegridad):
    # HTTP, tiempo de espera agotado o error de conexión (ALT-003).
    print(f"Descarga fallida: {resultado.mensaje}")
    print(f"Motivo para el .meta.json: {resultado.motivo}")
```

## Ejemplo: inyectar el descargador y el cliente en las pruebas

```python
import httpx

from source.api.integridad.downloader_adapter import AdaptadorDescarga

with httpx.Client(
    transport=httpx.MockTransport(
        lambda solicitud: httpx.Response(200, content=b"%PDF-1.4 ...")
    )
) as cliente:
    # `cliente` sustituye el transporte HTTP real del descargador.
    adaptador = AdaptadorDescarga(cliente=cliente)
    contenido = adaptador.descargar("https://ejemplo.test/difusion.pdf")

print(type(contenido))  # bytes
```

## Componente: `parser-adapter` (`source/api/integridad/parser_adapter.py`)

Adaptador del recuento de ofertas del PDF de difusión. `AdaptadorParseo` compone **en proceso** dos funciones públicas del parser existente de `api-pdf-parser` (`source/api/parser.py`): primero `extraer_texto_pdf(contenido)` y después `extraer_ofertas(texto, comunidad)`. No reescribe la lógica de parseo y no llama al endpoint `GET /parse` ni a ningún otro endpoint de la API (SUP-005). `parsear(contenido, comunidad)` devuelve un `RecuentoPDF` con el número de ofertas extraídas y la comunidad (REQ-003), o un `ErrorParseoIntegridad` con un `motivo` (y su alias `mensaje`) cuando `extraer_texto_pdf` lanza `ErrorParseoPDF` porque el documento no es legible. La composición distingue el PDF ilegible (error controlado, veredicto `fallido`, DEC-002) del PDF válido sin ofertas, que devuelve recuento `0` sin error y lo resolverá el comparador por umbral de cordura (ALT-004). El error es propio de la integridad y distinguible del `ErrorDescargaIntegridad`. Los dos extractores son inyectables para las pruebas.

## Ejemplo: contar las ofertas del PDF de difusión

```python
from source.api.integridad.downloader_adapter import AdaptadorDescarga
from source.api.integridad.parser_adapter import AdaptadorParseo, RecuentoPDF

contenido = AdaptadorDescarga().descargar(
    "https://ejemplo.test/SNE_ListadoOfertasDifusionWEB/difusion.pdf"
)

if isinstance(contenido, bytes):
    resultado = AdaptadorParseo().parsear(contenido, "cantabria")
    if isinstance(resultado, RecuentoPDF):
        print(resultado.recuento)     # p. ej. 92 ofertas
        print(resultado.comunidad)    # "cantabria"
```

## Ejemplo: tratar un PDF ilegible sin excepciones

```python
from source.api.integridad.parser_adapter import (
    AdaptadorParseo,
    ErrorParseoIntegridad,
    RecuentoPDF,
)

resultado = AdaptadorParseo().parsear(b"esto no es un PDF", "cantabria")

if isinstance(resultado, ErrorParseoIntegridad):
    # El PDF se conserva y el día se marca con veredicto `fallido` (DEC-002).
    print(f"Parseo fallido: {resultado.motivo}")
elif isinstance(resultado, RecuentoPDF):
    print(f"{resultado.recuento} ofertas de {resultado.comunidad}")
```

## Ejemplo: un PDF válido sin ofertas no es un error

```python
from pathlib import Path

from source.api.integridad.parser_adapter import AdaptadorParseo, RecuentoPDF

# Un PDF legible pero sin ninguna oferta devuelve recuento 0 sin error
# (ALT-004): el comparador decidirá por umbral de cordura.
resultado = AdaptadorParseo().parsear(
    Path("tests/fixtures/sample.pdf").read_bytes(), "cantabria"
)

assert isinstance(resultado, RecuentoPDF)
print(resultado.recuento)  # 0
```

## Ejemplo: inyectar los extractores en las pruebas

```python
from source.api.integridad.parser_adapter import AdaptadorParseo

adaptador = AdaptadorParseo(
    extractor_texto=lambda contenido: "Sector Profesional: SERVICIOS\nOferta: 0001",
    extractor_ofertas=lambda texto, comunidad="": ["oferta simulada"],
)

resultado = adaptador.parsear(b"contenido simulado", "cantabria")
print(resultado.recuento)  # 1
```

## Componente: `buscador-status-adapter` (`source/api/integridad/buscador_client.py`)

Cliente HTTP del estado publicado por `api-buscador`. `ClienteEstadoBuscador(url_base, cliente=None)` consulta **solo** `GET <url_base>/buscador/status` con `httpx` y normaliza el cuerpo real del endpoint: `in_progress`, `progreso` y `ultima_pasada` con `timestamp`, `comunidad`, `total_listado`, `error_global` y `errores_por_oferta`. `consultar_estado()` nunca lanza excepción: devuelve un `EstadoBuscador` —cuya propiedad `total_listado` expone el recuento del listado de forma cómoda (SUP-006)— o un `EstadoBuscadorNoUtilizable` con un `motivo` que identifica la causa: error HTTP o de red, `ultima_pasada` nula o sin `total_listado` (ALT-005) y `error_global` no vacío (ALT-006). Esa distinción es la que permite al comparador no emitir un veredicto `concordante`. El cliente solo pide `/buscador/status`: no lanza pasadas del buscador, no descarga fichas y no modifica `source/api/buscador/` (SUP-004). Si no se le pasa un cliente `httpx`, crea uno por consulta y lo cierra al terminar; es propio de la integridad y no reutiliza el cliente de `api-persistencia` ni el de `api-historico`.

## Ejemplo: consultar el estado y usar el recuento del listado

```python
from source.api.integridad.buscador_client import (
    ClienteEstadoBuscador,
    EstadoBuscador,
)

# La URL base viene de `config/integridad.yaml` (buscador.url_base).
cliente = ClienteEstadoBuscador("http://localhost:8000")
estado = cliente.consultar_estado()

if isinstance(estado, EstadoBuscador):
    print(estado.in_progress)      # False si no hay pasada en curso
    print(estado.progreso)         # None o el progreso de la pasada en curso
    print(estado.ultima_pasada.comunidad)      # "Cantabria"
    print(estado.ultima_pasada.timestamp)      # "2026-11-23T01:00:04"
    print(estado.ultima_pasada.error_global)   # "" si la pasada terminó bien
    print(estado.total_listado)                # 93 ofertas del listado
```

## Ejemplo: tratar un estado no utilizable sin excepciones

```python
from source.api.integridad.buscador_client import (
    ClienteEstadoBuscador,
    EstadoBuscador,
    EstadoBuscadorNoUtilizable,
)

cliente = ClienteEstadoBuscador("http://localhost:8000")
estado = cliente.consultar_estado()

if isinstance(estado, EstadoBuscadorNoUtilizable):
    # Error HTTP o de red, `ultima_pasada` nula o sin `total_listado`
    # (ALT-005) o `error_global` no vacío (ALT-006). El motivo se guarda
    # en el `.meta.json` del día y en los avisos.
    print(f"Estado del buscador no utilizable: {estado.motivo}")
elif isinstance(estado, EstadoBuscador):
    print(f"Recuento del listado: {estado.total_listado}")
```

## Ejemplo: inyectar un cliente HTTP de prueba

```python
import httpx

from source.api.integridad.buscador_client import ClienteEstadoBuscador

cuerpo = {
    "in_progress": False,
    "progreso": None,
    "ultima_pasada": {
        "timestamp": "2026-11-23T01:00:04",
        "comunidad": "Cantabria",
        "total_listado": 93,
        "error_global": "",
        "errores_por_oferta": [],
    },
}

transporte = httpx.MockTransport(
    lambda solicitud: httpx.Response(200, json=cuerpo, request=solicitud)
)
with httpx.Client(transport=transporte) as cliente_http:
    # El cliente de pruebas sustituye el transporte real del buscador.
    estado = ClienteEstadoBuscador(
        "http://localhost:8000", cliente=cliente_http
    ).consultar_estado()

print(estado.total_listado)  # 93
```

## Componente: `comparador-veredicto` (`source/api/integridad/comparador.py`)

Comparador del recuento de ofertas del PDF con el `total_listado` del buscador. `ComparadorRecuentos(tolerancia_absoluta, tolerancia_relativa_pct, umbral_cordura)` recibe los tres valores de `config/integridad.yaml` y `comparar(recuento_pdf, estado_buscador)` devuelve un `ResultadoComparacion` con el veredicto `concordante` o `divergente`, los dos recuentos (el del buscador solo si se conoce), la diferencia absoluta, las tolerancias y el umbral aplicados y el motivo. Se aplica la tolerancia más permisiva: la diferencia entra en la absoluta **o** en la relativa. El veredicto es siempre `divergente` cuando el recuento del PDF no alcanza el umbral de cordura (ALT-004), aunque los recuentos coincidan, y cuando el estado del buscador no es utilizable —error HTTP o de red, `ultima_pasada` nula o `error_global` no vacío (ALT-005, ALT-006)—, con el motivo de la causa. La regla relativa se omite si `total_listado` es cero, de modo que no hay división por cero. Es una función pura: no lee ni escribe ficheros, no consulta el reloj y no lanza excepciones. El veredicto es informativo: no bloquea los cierres de `api-historico` (REQ-006).

## Ejemplo: comparar los recuentos del día con las tolerancias configuradas

```python
from source.api.integridad.buscador_client import EstadoBuscador, UltimaPasada
from source.api.integridad.comparador import ComparadorRecuentos
from source.api.integridad.config import cargar_configuracion

config = cargar_configuracion()

comparador = ComparadorRecuentos(
    config.tolerancia_absoluta,        # 1 oferta
    config.tolerancia_relativa_pct,    # 5 %
    config.umbral_cordura,             # 70 ofertas
)

estado = EstadoBuscador(
    in_progress=False,
    progreso=None,
    ultima_pasada=UltimaPasada(
        timestamp="2026-11-23T01:00:04",
        comunidad="Cantabria",
        total_listado=93,          # el día que el PDF dio 92 ofertas
        error_global="",
    ),
)

resultado = comparador.comparar(92, estado)
print(resultado.veredicto)          # "concordante"
print(resultado.recuento_pdf)       # 92
print(resultado.recuento_buscador)  # 93
print(resultado.diferencia)         # 1
print(resultado.motivo)             # dentro de la tolerancia absoluta
```

## Ejemplo: un recuento por debajo del umbral de cordura

```python
from source.api.integridad.buscador_client import EstadoBuscador, UltimaPasada
from source.api.integridad.comparador import ComparadorRecuentos

comparador = ComparadorRecuentos(1, 5, 70)

estado = EstadoBuscador(
    in_progress=False,
    progreso=None,
    ultima_pasada=UltimaPasada(
        timestamp="2026-11-23T01:00:04",
        comunidad="Cantabria",
        total_listado=65,
        error_global="",
    ),
)

# Aunque los dos recuentos coincidan, 65 no alcanza el umbral de 70 (ALT-004).
resultado = comparador.comparar(65, estado)
print(resultado.veredicto)  # "divergente"
print(resultado.motivo)     # "no alcanza el umbral de cordura (70)"
```

## Ejemplo: un estado del buscador no utilizable no es concordante

```python
from source.api.integridad.buscador_client import ClienteEstadoBuscador
from source.api.integridad.comparador import ComparadorRecuentos

comparador = ComparadorRecuentos(1, 5, 70)

# `EstadoBuscadorNoUtilizable` llega sin lanzar excepción (ALT-005, ALT-006).
estado = ClienteEstadoBuscador("http://localhost:8000").consultar_estado()
resultado = comparador.comparar(92, estado)

if resultado.veredicto == "divergente":
    # El motivo identifica la causa: HTTP, red, `ultima_pasada` nula o
    # `error_global`. Es el texto que se guarda en el `.meta.json` y en el aviso.
    print(resultado.motivo)
    print(resultado.recuento_buscador)  # None: no hay recuento con el que comparar
```

## Ejemplo: usar el resultado al completar los metadatos del día

```python
from datetime import date

from source.api.integridad.comparador import ResultadoComparacion
from source.api.integridad.pdf_store import AlmacenPDFs, MetaDia


def meta_del_dia(resultado: ResultadoComparacion) -> MetaDia:
    """Traslada el veredicto al `.meta.json` del día (REQ-005)."""
    return MetaDia(
        recuento_pdf=resultado.recuento_pdf,
        recuento_buscador=resultado.recuento_buscador,
        diferencia=resultado.diferencia,
        tolerancia_absoluta=resultado.tolerancia_absoluta,
        tolerancia_relativa_pct=resultado.tolerancia_relativa_pct,
        umbral_cordura=resultado.umbral_cordura,
        veredicto=resultado.veredicto,
    )


# `meta_del_dia(resultado)` se escribe con `AlmacenPDFs.guardar_pdf(...)` o
# `AlmacenPDFs.escribir_meta(...)`; la marca de tiempo la pone el almacén.
almacen = AlmacenPDFs("data/pdfs", "Europe/Madrid")
print(almacen.ruta_meta("cantabria", date(2026, 11, 23)))
```

## Componente: `avisos-store` (`source/api/integridad/avisos.py`)

Almacén de avisos de fallo y divergencia. `AlmacenAvisos(almacen_pdf)` recibe el almacén de PDFs (`pdf-store`) y anexa cada aviso a la lista `avisos` del `.meta.json` del día de esa comunidad, reescribiéndolo con la escritura atómica de `pdf-store`, de modo que el aviso queda asociado a su fecha y se puede consultar por rango. `registrar_divergencia(comunidad, fecha, resultado)` guarda fecha, comunidad, recuento del PDF, `total_listado`, diferencia, tolerancia absoluta, tolerancia relativa, umbral de cordura y motivo (REQ-007); `registrar_fallo(comunidad, fecha, motivo)` guarda fecha, comunidad afectada y motivo, tanto para un fallo de descarga como de parseo (ALT-003, DEC-002). Ambos devuelven el aviso escrito. `consultar(desde, hasta)` recorre `<base>/<comunidad>/` y devuelve los avisos de los días del rango con su fecha y su comunidad, ordenados por fecha y comunidad; un `.meta.json` ausente o ilegible se omite sin error (REQ-009). Si el día no tiene metadatos legibles, registrar lanza `ErrorAvisoIntegridad`: no se inventa un día válido ni se sobrescribe un fichero corrupto. Los avisos son registros internos: no se envía nada por Telegram ni por ningún otro canal externo (SUP-007) y no se usa SQLite (DEC-001).

## Ejemplo: registrar el aviso de una divergencia de recuentos

```python
from datetime import date

from source.api.integridad.avisos import AlmacenAvisos
from source.api.integridad.buscador_client import EstadoBuscador, UltimaPasada
from source.api.integridad.comparador import ComparadorRecuentos
from source.api.integridad.config import cargar_configuracion
from source.api.integridad.pdf_store import AlmacenPDFs

config = cargar_configuracion()
almacen = AlmacenPDFs(config.ruta_base_pdfs, config.zona_horaria)
avisos = AlmacenAvisos(almacen)

comparador = ComparadorRecuentos(
    config.tolerancia_absoluta,
    config.tolerancia_relativa_pct,
    config.umbral_cordura,
)
estado = EstadoBuscador(
    in_progress=False,
    progreso=None,
    ultima_pasada=UltimaPasada(
        timestamp="2026-11-23T01:00:04",
        comunidad="Cantabria",
        total_listado=93,
        error_global="",
    ),
)
resultado = comparador.comparar(80, estado)  # veredicto "divergente"

# El aviso se anexa al .meta.json del día y devuelve los datos guardados.
aviso = avisos.registrar_divergencia(
    "cantabria", date(2026, 11, 23), resultado
)
print(aviso["fecha"])           # "2026-11-23"
print(aviso["total_listado"])   # 93
print(aviso["diferencia"])      # 13
print(aviso["motivo"])          # causa de la divergencia
```

## Ejemplo: registrar el aviso de un fallo de descarga o de parseo

```python
from datetime import date

from source.api.integridad.avisos import AlmacenAvisos
from source.api.integridad.pdf_store import AlmacenPDFs

almacen = AlmacenPDFs("data/pdfs", "Europe/Madrid")
avisos = AlmacenAvisos(almacen)

hoy = date(2026, 11, 23)

# La descarga falló: `pdf-store` ya dejó el día `fallido` sin PDF (ALT-003).
almacen.escribir_fallido("cantabria", hoy, "error HTTP 503")
aviso = avisos.registrar_fallo("cantabria", hoy, "error HTTP 503")
print(aviso)  # fecha, comunidad y motivo del fallo
```

## Ejemplo: consultar los avisos de un rango de fechas

```python
from datetime import date

from source.api.integridad.avisos import AlmacenAvisos
from source.api.integridad.pdf_store import AlmacenPDFs

almacen = AlmacenPDFs("data/pdfs", "Europe/Madrid")
avisos = AlmacenAvisos(almacen)

# Rango inclusivo; el almacén diario solo conserva el último mes.
for aviso in avisos.consultar(date(2026, 11, 1), date(2026, 11, 30)):
    print(aviso["fecha"], aviso["comunidad"], aviso["motivo"])
```

## Ejemplo: tratar un día sin metadatos donde anexar el aviso

```python
from datetime import date

from source.api.integridad.avisos import (
    AlmacenAvisos,
    ErrorAvisoIntegridad,
)
from source.api.integridad.pdf_store import AlmacenPDFs

almacen = AlmacenPDFs("data/pdfs", "Europe/Madrid")
avisos = AlmacenAvisos(almacen)

try:
    avisos.registrar_fallo("cantabria", date(2026, 11, 23), "error de red")
except ErrorAvisoIntegridad as error:
    # No existe el .meta.json del día (o no es legible): no se inventa un
    # día válido ni se sobrescribe un fichero corrupto.
    print(f"No se puede registrar el aviso: {error}")
```

## Componente: `avisos-store` — índice de ejecuciones (`source/api/integridad/ejecuciones.py`)

Índice en JSON de las ejecuciones de la comprobación diaria del último mes. `IndiceEjecuciones(base, zona_horaria)` guarda el fichero `<base>/ejecuciones.json` (`data/pdfs/ejecuciones.json` con la ruta base por defecto) con la forma `{"version": 1, "ejecuciones": [...]}`. `registrar(ejecucion)` añade una `Ejecucion` —marca de tiempo, resultado global, errores por comunidad (`{comunidad, mensaje}`), veredicto agregado y referencias `{fecha, comunidad}` a los `.meta.json` del día— y reescribe el índice con escritura atómica (temporal en el mismo directorio y `replace`); si la ejecución no trae marca de tiempo, se genera en la zona horaria configurada y no en la del sistema (NFR-004). `leer()` devuelve un `LecturaIndice` con estado `ok`, `ausente` (índice vacío válido) o `ilegible`, de modo que un índice corrupto se comunica y nunca se confunde con uno válido; al registrar sobre un índice ilegible se reescribe con la entrada nueva conservando las entradas recuperables. `consultar_ultimo_mes(hoy)` devuelve las ejecuciones de la ventana inclusiva de 30 días, de la más reciente a la más antigua. `ruta_indice` expone la ruta del fichero. No usa SQLite.

## Ejemplo: registrar una ejecución correcta y consultar el último mes

```python
from datetime import date

from source.api.integridad.config import cargar_configuracion
from source.api.integridad.ejecuciones import Ejecucion, IndiceEjecuciones

config = cargar_configuracion()
indice = IndiceEjecuciones(config.ruta_base_pdfs, config.zona_horaria)

# Sin `timestamp`, se genera en la zona configurada (Europe/Madrid).
guardada = indice.registrar(
    Ejecucion(
        resultado_global="ok",
        veredicto_agregado="concordante",  # el más grave entre comunidades
        referencias=[{"fecha": "2026-11-23", "comunidad": "cantabria"}],
    )
)
print(guardada.timestamp)  # "2026-11-23T02:00:00+01:00"

for ejecucion in indice.consultar_ultimo_mes(date(2026, 11, 23)):
    print(ejecucion.timestamp, ejecucion.resultado_global)
    print(ejecucion.veredicto_agregado, ejecucion.referencias)
```

## Ejemplo: registrar una ejecución con errores parciales

```python
from source.api.integridad.ejecuciones import Ejecucion, IndiceEjecuciones

indice = IndiceEjecuciones("data/pdfs", "Europe/Madrid")

indice.registrar(
    Ejecucion(
        resultado_global="parcial",
        veredicto_agregado="fallido",
        errores_por_comunidad=[
            {"comunidad": "cantabria", "mensaje": "error HTTP 503"}
        ],
        referencias=[{"fecha": "2026-11-23", "comunidad": "cantabria"}],
    )
)
```

## Ejemplo: leer un índice corrupto sin excepción

```python
from source.api.integridad.ejecuciones import IndiceEjecuciones

indice = IndiceEjecuciones("data/pdfs", "Europe/Madrid")

lectura = indice.leer()
if lectura.estado == "ausente":
    print("Todavía no hay ejecuciones registradas")
elif lectura.estado == "ilegible":
    # El fichero se deja intacto y no se trata como un índice válido.
    print(f"Índice ilegible: {lectura.motivo}")
    print(f"Entradas recuperables: {len(lectura.ejecuciones)}")
else:
    print(f"Ejecuciones guardadas: {len(lectura.ejecuciones)}")
```

## Ejemplo: registrar aunque el índice esté corrupto

```python
from datetime import date

from source.api.integridad.ejecuciones import Ejecucion, IndiceEjecuciones

indice = IndiceEjecuciones("data/pdfs", "Europe/Madrid")

# Un índice corrupto no impide la ejecución del día: se reescribe con la
# entrada nueva, conservando las entradas que se hayan podido recuperar.
guardada = indice.registrar(Ejecucion(resultado_global="ok"))
print(indice.leer().estado)  # "ok"
```

## Ejemplo: la marca de tiempo usa la zona configurada

```python
from source.api.integridad.ejecuciones import Ejecucion, IndiceEjecuciones

# Otra zona válida: la marca de tiempo lleva su desfase (NFR-004).
indice = IndiceEjecuciones("data/pdfs", "Pacific/Kiritimati")

guardada = indice.registrar(Ejecucion(resultado_global="ok"))
print(guardada.timestamp)  # "...T...+14:00"
```

## Componente: `integridad-task` (`source/api/integridad/task.py`)

Tarea programada diaria que orquesta la comprobación de integridad. `TareaIntegridad(config, almacen, adaptador_descarga, adaptador_parseo, cliente_buscador, comparador, avisos, ejecuciones, purger, reloj=None)` corre en su propio hilo daemon (convive con el planificador del buscador, la ingesta, la purga y las tareas del histórico, sin modificarlos, DEC-006). `iniciar()` decide antes de esperar, con `_decidir_arranque(ahora, hay_meta_hoy)`, qué toca en ese arranque (DEC-007, ALT-009): si el día ya está resuelto en todas las comunidades no adelanta nada (`AccionArranque.NINGUNA`); antes de la hora configurada espera la ejecución normal (`ESPERAR_NORMAL`); dentro de la ventana `[hora, hora + margen]` sin metadatos programa una única ejecución para `hora + margen` (`DIFERIDA`, con la espera que calcula `_segundos_hasta_catchup`); y después del margen comprueba el día en el acto (`INMEDIATA`). El criterio de «hay metadatos de hoy» lo da `_hay_meta_hoy()`: **todas** las comunidades necesitan un `.meta.json` de hoy legible con veredicto terminal (`ok`/`concordante`, `divergente` o `fallido`), y se consulta siempre en disco, nunca en memoria, de modo que un reinicio no rompe la frecuencia máxima diaria. La ejecución adelantada comparte el lock y la idempotencia de `_ejecutar_dia()`, no se duplica con la normal y nunca procesa días anteriores. `detener()` señaliza el evento de parada, corta en el acto tanto la espera normal como la diferida y une el hilo sin dejar ejecuciones en curso. Para cada comunidad de la configuración, `_ejecutar_dia()` calcula el día con la zona configurada (NFR-004) y consulta el `.meta.json`: si ya es terminal (`ok`/`concordante` o `fallido`) no descarga ni parsea (ALT-001, ALT-002, NFR-003); si hay PDF sin metadatos utilizables lo reprocesa y regenera (ALT-007); si no hay nada, descarga, guarda de forma atómica con su hash, parsea, consulta `GET /buscador/status`, compara y completa el `.meta.json`. Una descarga fallida deja el día `fallido` sin PDF y un parseo fallido conserva el PDF (ALT-003, DEC-002); ambos casos y las divergencias registran un aviso interno en el `.meta.json` (REQ-007). Al terminar registra la ejecución global —con el veredicto más grave, `fallido` > `divergente` > `concordante`— en el índice (ALT-008, REQ-008) y lanza la purga. Una excepción inesperada de una comunidad se anota en los errores por comunidad y no interrumpe a las demás; un lock impide solapamientos. El reloj es inyectable mediante `RelojProtocol`/`RelojReal`, locales del subpaquete. No envía nada por Telegram ni por otro canal externo (SUP-007) y no usa SQLite (DEC-001).

## Ejemplo: componer y arrancar la tarea diaria

```python
from source.api.integridad.avisos import AlmacenAvisos
from source.api.integridad.buscador_client import ClienteEstadoBuscador
from source.api.integridad.comparador import ComparadorRecuentos
from source.api.integridad.config import cargar_configuracion
from source.api.integridad.downloader_adapter import AdaptadorDescarga
from source.api.integridad.ejecuciones import IndiceEjecuciones
from source.api.integridad.parser_adapter import AdaptadorParseo
from source.api.integridad.pdf_store import AlmacenPDFs
from source.api.integridad.purger import purgar
from source.api.integridad.task import TareaIntegridad

config = cargar_configuracion()
almacen = AlmacenPDFs(config.ruta_base_pdfs, config.zona_horaria)

tarea = TareaIntegridad(
    config,
    almacen,
    AdaptadorDescarga(),
    AdaptadorParseo(),
    ClienteEstadoBuscador(config.url_base_buscador),
    ComparadorRecuentos(
        config.tolerancia_absoluta,
        config.tolerancia_relativa_pct,
        config.umbral_cordura,
    ),
    AlmacenAvisos(almacen),
    IndiceEjecuciones(config.ruta_base_pdfs, config.zona_horaria),
    purgar,  # pdf-purger
)

# Hilo daemon: se dispara a `config.hora_ejecucion` en la zona configurada.
tarea.iniciar()
```

## Ejemplo: saber qué hará la tarea al arrancar

```python
from datetime import datetime
from zoneinfo import ZoneInfo

# `hay_meta_hoy` sale de `_hay_meta_hoy()`: todas las comunidades con su
# `.meta.json` de hoy legible y con veredicto terminal.
zona = ZoneInfo("Europe/Madrid")

accion = tarea._decidir_arranque(
    datetime(2026, 11, 23, 2, 30, tzinfo=zona), hay_meta_hoy=False
)
print(accion.value)  # "diferida": se espera al final del margen

# Segundos que faltan hasta `hora + margen` (02:00 + 60 min = 03:00).
print(tarea._segundos_hasta_catchup(
    datetime(2026, 11, 23, 2, 30, tzinfo=zona)
))  # 1800.0

# Antes de la hora solo se espera la ejecución programada normal.
print(tarea._decidir_arranque(
    datetime(2026, 11, 23, 1, 0, tzinfo=zona), hay_meta_hoy=False
).value)  # "esperar_normal"

# Después del margen, la comprobación del día es inmediata.
print(tarea._decidir_arranque(
    datetime(2026, 11, 23, 10, 0, tzinfo=zona), hay_meta_hoy=False
).value)  # "inmediata"

# Con el día ya resuelto no se adelanta nada, a ninguna hora.
print(tarea._decidir_arranque(
    datetime(2026, 11, 23, 10, 0, tzinfo=zona), hay_meta_hoy=True
).value)  # "ninguna"
```

## Ejemplo: saber si el día en curso ya está resuelto

```python
# Lee el `.meta.json` de hoy de cada comunidad configurada: solo devuelve
# `True` si todas tienen un veredicto terminal (`ok`/`concordante`,
# `divergente` o `fallido`). No usa memoria: tras un reinicio da lo mismo.
if tarea._hay_meta_hoy():
    print("El día ya está resuelto; el arranque no adelanta nada")
else:
    print("Falta alguna comunidad; el arranque aplicará el catch-up")
```

## Ejemplo: detener la tarea sin dejar ejecuciones en curso

```python
# Señaliza el evento de parada, corta la espera y une el hilo.
tarea.detener()
```

## Ejemplo: ejecutar el día de forma controlada y leer el resultado

```python
# En el uso normal lo llama el hilo; en pruebas o en una comprobación manual
# se puede invocar directamente. Es idempotente por el `.meta.json` del día.
resultado = tarea._ejecutar_dia()

if resultado is not None:
    print(resultado.fecha)                 # día en la zona configurada
    print(resultado.veredicto_global)      # "concordante", "divergente" o "fallido"
    print(resultado.veredictos_por_comunidad)   # {"cantabria": "concordante"}
    print(resultado.errores_por_comunidad)      # [] si no hubo excepciones
    print(resultado.referencias)           # [{"fecha": ..., "comunidad": ...}]
```

## Ejemplo: inyectar un reloj controlado en las pruebas

```python
from datetime import datetime
from zoneinfo import ZoneInfo


class RelojFijo:
    """Reloj de prueba con un instante fijo (protocolo `RelojProtocol`)."""

    def __init__(self, momento: datetime) -> None:
        self._momento = momento

    def ahora(self) -> datetime:
        return self._momento


tarea = TareaIntegridad(
    config,
    almacen,
    AdaptadorDescarga(),
    AdaptadorParseo(),
    ClienteEstadoBuscador(config.url_base_buscador),
    ComparadorRecuentos(1, 5, 70),
    AlmacenAvisos(almacen),
    IndiceEjecuciones(config.ruta_base_pdfs, config.zona_horaria),
    purgar,
    reloj=RelojFijo(datetime(2026, 11, 23, 2, 30, tzinfo=ZoneInfo("Europe/Madrid"))),
)

# La fecha del día y la próxima ejecución salen de ese reloj, sin dormir.
print(tarea._segundos_hasta_proxima(datetime(2026, 11, 23, 1, 0, tzinfo=ZoneInfo("Europe/Madrid"))))
```

## Componente: `integridad-api` (`source/api/integridad/routes.py`)

Endpoints de consulta de la integridad. El `router` (`APIRouter(prefix="/integridad", tags=["integridad"])`) expone `GET /integridad/ultimo`, que lee a través del `AlmacenPDFs` de `app_state["almacen_integridad"]` los `.meta.json` del árbol de PDFs, se queda con el día más reciente (fecha máxima; a igualdad, el orden de la última ejecución de `app_state["indice_ejecuciones"]`) y devuelve una `RespuestaUltimoVeredicto` con `fecha`, `veredicto_global`, `cierre_recomendado` y `comunidades`. Cada `VeredictoComunidad` lleva `fecha`, `comunidad`, `recuento_pdf`, `recuento_buscador`, `diferencia`, `tolerancia_absoluta`, `tolerancia_relativa_pct`, `umbral_cordura` y `veredicto`. El veredicto global es el más grave (`fallido` > `divergente` > `concordante`, ALT-008) y `cierre_recomendado` es `True` solo si es `concordante` y es de hoy en la zona de `app_state["config_integridad"]`; un veredicto `divergente`, `fallido` o la falta de veredicto de hoy lo dejan en `False` (REQ-006). Es de solo lectura (no escribe nada y no toca `data/job_emcan.db`, SUP-002), omite los `.meta.json` ilegibles sin error y no exige autenticación, como el resto de la API. Si la feature no se inicializó (`almacen_integridad` ausente o a `None`), responde 503 con un mensaje que lo indica. El veredicto es informativo: no bloquea ni modifica los cierres de `api-historico`.

También expone `GET /integridad/ejecuciones`, que lee el índice de `app_state["indice_ejecuciones"]` con `consultar_ultimo_mes(hoy)` —`hoy` calculado en la zona de `app_state["config_integridad"]`— y devuelve una lista de `EjecucionIntegridadSalida`: una por ejecución de la ventana de 30 días, de la más reciente a la más antigua, con `timestamp`, `resultado_global`, `errores_por_comunidad` (cada uno con `comunidad` y `mensaje`), `veredicto_agregado` y `avisos`. Los avisos se leen de los `.meta.json` que la ejecución referencia (`referencias`) con `app_state["almacen_integridad"]`, y los ilegibles se omiten; un índice ausente o ilegible devuelve una lista vacía sin error. Es igualmente de solo lectura, no exige autenticación y no envía nada por ningún canal de notificación externo (SUP-002, SUP-007).

Y expone `GET /integridad/pdfs`, que lista con `AlmacenPDFs.listar_conservados()` el árbol de `app_state["almacen_integridad"]` y devuelve una lista de `PdfConservadoSalida`: un elemento por PDF con `fecha`, `comunidad` y `ruta` relativa a la ruta base (`<comunidad>/<aaaa-mm-dd>.pdf`, nunca una ruta absoluta del sistema) y, cuando existe el `.meta.json` del día, `hash`, `recuento_pdf`, `recuento_buscador` y `veredicto`. Un PDF sin metadatos, o con un `.meta.json` ilegible, se lista igualmente con esos campos en nulo y sin error (ALT-007); sin directorio de PDFs la respuesta es una lista vacía; los nombres que no siguen el patrón `<aaaa-mm-dd>.pdf` no se listan y el resultado refleja lo que queda tras la purga (DEC-004). Es de solo lectura (no escribe ni borra ningún fichero y no toca `data/job_emcan.db`, SUP-003), no exige autenticación y responde 503 si la integridad no está inicializada.

## Ejemplo: consultar el último veredicto con TestClient

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient

from source.api.integridad import routes

# La app real registra este router en `source/api/main.py`; aquí se monta solo
# el router de consulta.
app = FastAPI()
app.include_router(routes.router)

with TestClient(app) as cliente:
    respuesta = cliente.get("/integridad/ultimo")

print(respuesta.status_code)  # 200 si la integridad está inicializada
datos = respuesta.json()
print(datos["fecha"])                # "2026-11-23", o None si aún no hay días
print(datos["veredicto_global"])     # "concordante", "divergente" o "fallido"
print(datos["cierre_recomendado"])   # True solo con un concordante de hoy
```

## Ejemplo: leer el desglose por comunidad

```python
datos = cliente.get("/integridad/ultimo").json()

for fila in datos["comunidades"]:
    print(fila["comunidad"])          # "cantabria"
    print(fila["fecha"])              # "2026-11-23"
    print(fila["recuento_pdf"])       # 92
    print(fila["recuento_buscador"])  # 93
    print(fila["diferencia"])         # 1
    print(fila["veredicto"])          # "concordante"
```

## Ejemplo: interpretar la recomendación de cierre

```python
datos = cliente.get("/integridad/ultimo").json()

if datos["cierre_recomendado"]:
    print("Los recuentos concuerdan hoy: se pueden cerrar ofertas")
else:
    # Divergente, fallido o sin veredicto de hoy (REQ-006).
    print("No se recomienda cerrar ofertas; revisa el desglose")
```

## Ejemplo: tratar la integridad no disponible

```python
respuesta = cliente.get("/integridad/ultimo")

if respuesta.status_code == 503:
    # La app arrancó sin la integridad (configuración ausente o inválida).
    print(respuesta.json()["detail"])
```

## Ejemplo: consultar las ejecuciones del último mes

```python
respuesta = cliente.get("/integridad/ejecuciones")

print(respuesta.status_code)  # 200, también sin ejecuciones (lista vacía)
for ejecucion in respuesta.json():
    print(ejecucion["timestamp"])         # "2026-11-23T02:00:00+01:00"
    print(ejecucion["resultado_global"])  # "ok", "parcial"...
    print(ejecucion["veredicto_agregado"])  # "concordante", "divergente" o "fallido"
```

## Ejemplo: leer los errores por comunidad y los avisos

```python
for ejecucion in cliente.get("/integridad/ejecuciones").json():
    # Comunidades que fallaron en esa pasada (REQ-008).
    for error in ejecucion["errores_por_comunidad"]:
        print(error["comunidad"], error["mensaje"])

    # Avisos registrados en los .meta.json referenciados por la ejecución
    # (REQ-007): divergencias con recuentos y motivo, o fallos con su motivo.
    for aviso in ejecucion["avisos"]:
        print(aviso["tipo"], aviso["fecha"], aviso["comunidad"], aviso["motivo"])
```

## Ejemplo: interpretar un índice ausente o ilegible

```python
datos = cliente.get("/integridad/ejecuciones").json()

if not datos:
    # Sin ejecuciones registradas todavía, o con `ejecuciones.json` ilegible:
    # el endpoint responde 200 con una lista vacía, sin error.
    print("No hay ejecuciones consultables del último mes")

# Orden garantizado: de la más reciente a la más antigua (REQ-009).
print([ejecucion["timestamp"] for ejecucion in datos])
```

## Ejemplo: consultar los PDFs conservados

```python
respuesta = cliente.get("/integridad/pdfs")

print(respuesta.status_code)  # 200, también sin PDFs (lista vacía)
for pdf in respuesta.json():
    print(pdf["fecha"])        # "2026-11-23"
    print(pdf["comunidad"])    # "cantabria"
    print(pdf["ruta"])         # "cantabria/2026-11-23.pdf", relativa a la base
    print(pdf["veredicto"])    # "concordante", "divergente" o "fallido"
```

## Ejemplo: distinguir un PDF sin metadatos

```python
for pdf in cliente.get("/integridad/pdfs").json():
    if pdf["veredicto"] is None:
        # Sin `.meta.json` (día incompleto) o con metadatos ilegibles: el PDF
        # se lista igualmente, sin datos del día y sin error (ALT-007).
        print(f"{pdf['comunidad']}/{pdf['fecha']}: sin metadatos")
    else:
        print(
            pdf["veredicto"],
            pdf["recuento_pdf"],
            pdf["recuento_buscador"],
            pdf["hash"],
        )
```


