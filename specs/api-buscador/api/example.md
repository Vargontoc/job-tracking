# Ejemplos de uso: api-buscador

## `api-service` (subpaquete `buscador`)

El subpaquete `source.api.buscador` agrupa los componentes del rastreador del
buscador HTML de Emplea Cantabria. Se importa como cualquier otro paquete de
Python y no referencia ningún motor de base de datos (DEC-002).

```python
import source.api.buscador

print(source.api.buscador.__doc__)
```

La dependencia `selectolax` se usa para el parseo HTML del listado y de las
fichas del portal.

```python
from selectolax.lexbor import LexborHTMLParser

arbol = LexborHTMLParser("<html><body><p>hola</p></body></html>")
print(arbol.css_first("p").text())
```

## `response-assembler`

Las entidades de dominio del rastreador son dataclasses puras sin persistencia
ni serialización a disco. `OfertaBuscador` conserva los ocho campos que
publica la ficha del portal, con `sector`, `nivel` y `contrato` reservados
pero siempre vacíos (DEC-009).

```python
from source.api.buscador.models import (
    ConfigBuscador,
    ErrorOferta,
    OfertaBuscador,
    ResultadoPasada,
)


config = ConfigBuscador(
    hora_pasada=1,
    url_listado="https://example.com/listado",
    url_ficha="https://example.com/ficha",
    user_agent="job-emcan-tracking (+contacto@example.com)",
    delay_peticiones=10,
    tamano_pagina=75,
)

oferta = OfertaBuscador(
    numero_oferta="062026003633",
    ocupacion="Cocinero/a",
    municipio="SANTANDER",
    provincia="CANTABRIA",
    fecha_inicio_difusion="18/11/2026",
    fecha_fin_difusion="03/12/2026",
    texto_libre="Preparación de menús diarios.",
    contacto="Email: ejemplo@empresa.com",
)
print(oferta.comunidad)  # "Cantabria" (SUP-003)
print(oferta.sector)     # "" (DEC-009, reservado y vacío)
print(oferta.nivel)      # ""
print(oferta.contrato)   # ""

resultado = ResultadoPasada(
    timestamp="2026-11-18T01:00:00",
    comunidad="Cantabria",
    total_listado=93,
    error_global="",
    errores_por_oferta=[
        ErrorOferta(
            codigo="062026003484",
            mensaje="Timeout al descargar la ficha.",
        )
    ],
    ofertas_nuevas=[oferta],
)
print(resultado.total_listado, len(resultado.ofertas_nuevas))
```

## `config-buscador`

El componente carga la configuración del buscador desde `config/buscador.yaml`
y devuelve una entidad `ConfigBuscador`. Los campos opcionales ausentes toman
sus valores por defecto (hora 1, delay 10 s, página 75, purga 7 días). Si el
fichero no existe, devuelve una configuración por defecto. Si el YAML es
malformado o está vacío, lanza `ErrorConfiguracion`.

```python
from source.api.buscador.config import cargar_configuracion, ErrorConfiguracion


try:
    config = cargar_configuracion()
except ErrorConfiguracion as error:
    print(error)
else:
    print(config.hora_pasada)        # 1 (01:00)
    print(config.tamano_pagina)      # 75
    print(config.delay_peticiones)   # 10
    print(config.url_listado)
    print(config.user_agent)
```

## `run-coordinator`

Coordina una pasada completa del rastreador: carga códigos vistos, recorre el
listado, parsea fichas de códigos nuevos, guarda códigos vistos actualizados,
purge HTML fallidos antiguos y ensambla el resultado. Implementa exclusión
mutua para evitar pasadas concurrentes.

```python
import httpx
from pathlib import Path

from source.api.buscador.coordinator import CoordinadorPasada
from source.api.buscador.models import ConfigBuscador
from source.api.buscador.rate_limiter import LimitadorPeticiones


config = ConfigBuscador(
    url_listado="https://empleacantabria.es/ofertas-cantabria",
    url_ficha="https://empleacantabria.es/ofertas-cantabria/-/oferta",
    user_agent="JobEmcanTracking/1.0",
    tamano_pagina=75,
)

limitador = LimitadorPeticiones(delay_segundos=10.0, user_agent=config.user_agent)

with httpx.Client() as cliente:
    coordinador = CoordinadorPasada(
        config=config,
        cliente=cliente,
        limitador=limitador,
        ruta_seen_codes=Path("data/seen_codes.json"),
        ruta_failed_htmls=Path("data/failed_htmls"),
        dias_purga=7,
    )

    # Ejecutar una pasada
    resultado = coordinador.ejecutar_pasada()

    print(f"Total: {resultado.total_listado}")
    print(f"Nuevas: {len(resultado.ofertas_nuevas)}")
    print(f"Errores: {len(resultado.errores_por_oferta)}")

    # Verificar estado compartido
    print(f"Pasada en curso: {coordinador.pasada_en_curso}")  # False
    print(f"Último resultado: {coordinador.ultimo_resultado is not None}")  # True
```

El coordinador mantiene estado compartido (protegido por lock) para que el
scheduler y los endpoints puedan consultar el progreso y el último resultado:

```python
# Consultar progreso durante una pasada en curso
progreso = coordinador.progreso
print(f"Inicio: {progreso.hora_inicio}")
print(f"Procesados: {progreso.codigos_procesados}/{progreso.total_codigos}")

# Consultar último resultado
if coordinador.ultimo_resultado:
    print(f"Error global: {coordinador.ultimo_resultado.error_global}")
```

## `state-store`

El componente gestiona el único estado persistente de la feature: el fichero
JSON de códigos ya vistos (`data/seen_codes.json`). Lee el conjunto de códigos
al arrancar; si el fichero no existe, lo crea vacío. La escritura une los
códigos nuevos a los anteriores sin duplicados. No usa bases de datos (DEC-002).

```python
from pathlib import Path
from source.api.buscador.state import leer_codigos_vistos, guardar_codigos_vistos


ruta = Path("data/seen_codes.json")
codigos = leer_codigos_vistos(ruta)
print(f"Códigos vistos: {len(codigos)}")

# Guardar códigos nuevos (une con los existentes, sin duplicados)
guardar_codigos_vistos(ruta, {"062026003633", "062026003484"})
```

## `rate-limiter`

El componente regula el intervalo mínimo entre todas las peticiones HTTP salientes al portal (listado, fichas y reintentos). Es un limitador único y compartido que garantiza al menos 10 segundos entre peticiones consecutivas. La primera petición no espera. Aplica el User-Agent de la configuración. No incluye credenciales ni cabeceras de autenticación (NFR-001, NFR-003).

```python
from source.api.buscador.rate_limiter import LimitadorPeticiones

# Crear limitador compartido (una sola instancia en toda la aplicación)
limitador = LimitadorPeticiones(
    delay_segundos=10.0,
    user_agent="JobEmcanTracking/1.0 (+contacto@example.com)",
)

# Antes de cada petición HTTP al portal:
limitador.esperar()
# ... luego hacer la petición con httpx usando limitador.user_agent
```

## `api-buscador` (fixtures)

Las pruebas del buscador usan muestras HTML reales del contrato del portal
(`docs/contracts/html/empleacantabria/`), copiadas en `tests/fixtures/buscador/`
para que los tests sean autocontenidos. El contrato HTML es la única fuente de
verdad: las muestras conservan la estructura real del portal (clases, ids,
atributos) y los tests verifican que se pueden parsear con `selectolax`.

```python
from pathlib import Path
from selectolax.lexbor import LexborHTMLParser


ruta = Path("tests/fixtures/buscador/listado_pagina_1.html")
html = ruta.read_text(encoding="utf-8")
arbol = LexborHTMLParser(html)

# Extraer códigos de oferta de las filas del listado
enlaces = arbol.css("a[href*='/ofertas-cantabria/-/oferta/']")
codigos = [a.text() for a in enlaces]
print(f"Códigos en la página: {codigos}")  # ["062026003633", "062026003632", ...]

# Leer el total de ofertas del texto de paginación
small = arbol.css_first("small.search-results")
print(small.text(strip=True))  # "Mostrando el intervalo 1 - 75 de 93 resultados."
```

## Pruebas de integración end-to-end

Las pruebas de integración (TASK-017) verifican el flujo completo del rastreador simulando el portal con respuestas mock. Se usan los fixtures HTML reales de `tests/fixtures/buscador/` y un cliente HTTP mock para controlar las respuestas.

```python
from pathlib import Path
from fastapi.testclient import TestClient
from source.api.main import app, app_state
from source.api.buscador.coordinator import CoordinadorPasada
from source.api.buscador.models import ConfigBuscador
from source.api.buscador.rate_limiter import LimitadorPeticiones


class ClienteHTTPMock:
    """Cliente HTTP mock que simula respuestas del portal."""
    
    def __init__(self):
        self.respuestas = {}
    
    def get(self, url, timeout=30.0):
        if url in self.respuestas:
            return self.respuestas[url]
        
        class RespuestaMock:
            status_code = 404
            text = ""
            def raise_for_status(self):
                raise RuntimeError(f"HTTP {self.status_code}")
        
        return RespuestaMock()
    
    def agregar_respuesta(self, url, html, status_code=200):
        class RespuestaMock:
            def __init__(self, status, text):
                self.status_code = status
                self.text = text
            def raise_for_status(self):
                if self.status_code >= 400:
                    raise RuntimeError(f"HTTP {self.status_code}")
        
        self.respuestas[url] = RespuestaMock(status_code, html)


# Configurar cliente mock con fixtures
cliente = ClienteHTTPMock()
fixtures_dir = Path("tests/fixtures/buscador")

listado_html = (fixtures_dir / "listado_pagina_1.html").read_text(encoding="utf-8")
cliente.agregar_respuesta(
    "https://empleacantabria.es/ofertas-cantabria?_delta=75&_cur=1",
    listado_html
)

# Configurar coordinador
config = ConfigBuscador(
    url_listado="https://empleacantabria.es/ofertas-cantabria",
    url_ficha="https://empleacantabria.es/ofertas-cantabria/-/oferta",
    tamano_pagina=75,
)

coordinador = CoordinadorPasada(
    config=config,
    cliente=cliente,
    limitador=LimitadorPeticiones(delay_segundos=0.0),
    ruta_seen_codes=Path("data/seen_codes.json"),
    ruta_failed_htmls=Path("data/failed_htmls"),
)

# Ejecutar prueba de integración
app_state["coordinador"] = coordinador

with TestClient(app) as test_client:
    response = test_client.post("/buscador/run")
    resultado = response.json()
    
    print(f"Total ofertas: {resultado['total_listado']}")
    print(f"Ofertas nuevas: {len(resultado['ofertas_nuevas'])}")
    print(f"Errores: {len(resultado['errores_por_oferta'])}")
```

## `list-scraper`

El componente recorre el listado paginado del buscador, extrayendo los
códigos de oferta de 12 dígitos de cada página y deduciendo el total desde
`small.search-results`. Sigue la paginación hasta la última página (con
tamaño configurable, por defecto 75) y detecta el estado de listado vacío.
Todas las peticiones pasan por el limitador global (DEC-003).

```python
import httpx

from source.api.buscador.rate_limiter import LimitadorPeticiones
from source.api.buscador.scraper import recorrer_listado


limitador = LimitadorPeticiones(
    delay_segundos=10.0,
    user_agent="JobEmcanTracking/1.0 (+contacto@example.com)",
)

with httpx.Client() as cliente:
    resultado = recorrer_listado(
        cliente=cliente,
        url_listado="https://empleacantabria.es/ofertas-cantabria",
        limitador=limitador,
        tamano_pagina=75,
        codigos_vistos={"062026003633"},  # ya vistos en pasadas anteriores
    )

print(f"Total: {resultado.total}")
print(f"Nuevos: {len(resultado.codigos)}")
print(f"Páginas: {resultado.paginas_solicitadas}")
if resultado.error_global:
    print(f"Error: {resultado.error_global}")
```

## `detail-parser`

El componente descarga y parsea la ficha de una oferta individual, extrayendo
los campos publicados por el portal (número de oferta, ocupación, municipio,
provincia, fechas de difusión, texto libre y contacto). Los campos `sector`,
`nivel` y `contrato` se mantienen vacíos porque el portal no los publica
(DEC-009). Todas las peticiones pasan por el limitador global y se reintenta
una vez si falla (DEC-007).

```python
import httpx

from source.api.buscador.rate_limiter import LimitadorPeticiones
from source.api.buscador.parser import parsear_ficha


limitador = LimitadorPeticiones(
    delay_segundos=10.0,
    user_agent="JobEmcanTracking/1.0 (+contacto@example.com)",
)

with httpx.Client() as cliente:
    resultado = parsear_ficha(
        cliente=cliente,
        url_base="https://empleacantabria.es/ofertas-cantabria/-/oferta",
        codigo="062026003633",
        limitador=limitador,
    )

if resultado.oferta:
    print(f"Oferta: {resultado.oferta.numero_oferta}")
    print(f"Ocupación: {resultado.oferta.ocupacion}")
    print(f"Municipio: {resultado.oferta.municipio}")
    print(f"Provincia: {resultado.oferta.provincia}")
    print(f"Fecha inicio: {resultado.oferta.fecha_inicio_difusion}")
    print(f"Fecha fin: {resultado.oferta.fecha_fin_difusion}")
    print(f"Texto libre: {resultado.oferta.texto_libre[:100]}...")
    print(f"Contacto: {resultado.oferta.contacto}")
    # Campos reservados siempre vacíos (DEC-009)
    print(f"Sector: '{resultado.oferta.sector}'")
    print(f"Nivel: '{resultado.oferta.nivel}'")
    print(f"Contrato: '{resultado.oferta.contrato}'")
else:
    print(f"Error: {resultado.error}")
    # El HTML se conserva solo en caso de error para diagnóstico
    if resultado.html:
        print(f"HTML disponible para archivado: {len(resultado.html)} bytes")
```

## `html-archive`

El componente archiva el HTML original de las fichas cuyo parseo falló, para
diagnóstico posterior. Guarda el HTML en `data/failed_htmls/` con nombre
`<codigo>_<fecha>.html`. Si el directorio no existe, lo crea. Si no se puede
escribir, devuelve un error controlado sin interrumpir la pasada.

```python
from pathlib import Path
from source.api.buscador.archive import archivar_html_fallido, ErrorArchivado


# Tras un fallo de parseo con HTML disponible:
codigo = "062026003633"
html = "<html><body>Error de parseo...</body></html>"
fecha = "2026-01-15"  # Fecha en formato ISO
directorio = Path("data/failed_htmls")

try:
    ruta = archivar_html_fallido(codigo, html, fecha, directorio)
    print(f"HTML archivado en: {ruta}")
except ErrorArchivado as error:
    print(f"No se pudo archivar el HTML: {error}")
    # El error no interrumpe la pasada, solo se registra
```

## `archive-purger`

El componente elimina los HTML fallidos con más de 7 días de antigüedad. La
antigüedad se calcula a partir de la fecha embebida en el nombre del fichero
(`<codigo>_<yyyy-mm-dd>.html`), no del mtime del sistema de archivos. Los
ficheros sin fecha reconocible o con fecha inválida se ignoran. Si el
directorio no existe, no falla.

```python
from pathlib import Path
from source.api.buscador.purger import purgar_html_caducados


directorio = Path("data/failed_htmls")
eliminados = purgar_html_caducados(directorio, dias_purga=7)

print(f"Se eliminaron {len(eliminados)} HTML fallidos antiguos:")
for ruta in eliminados:
    print(f"  - {ruta.name}")
```

## `response-assembler`

Ensambla el resultado estructurado de una pasada del rastreador. Construye un
`ResultadoPasada` con los metadatos de ejecución, errores y ofertas nuevas. Si
hay error global, excluye las ofertas nuevas.

```python
from source.api.buscador.assembler import ensamblar_resultado_pasada
from source.api.buscador.models import OfertaBuscador, ErrorOferta


# Ejemplo: pasada exitosa con ofertas nuevas
ofertas = [
    OfertaBuscador(
        numero_oferta="062026003484",
        ocupacion="Desarrollador",
        municipio="Santander",
        provincia="Cantabria",
        fecha_inicio_difusion="01/01/2026",
        fecha_fin_difusion="31/01/2026",
        texto_libre="Puesto de desarrollo",
        contacto="email@example.com",
    ),
]

resultado = ensamblar_resultado_pasada(
    timestamp_inicio="2026-01-18T01:00:00",
    timestamp_fin="2026-01-18T01:05:00",
    ofertas_nuevas=ofertas,
    errores_por_oferta=[],
    error_global="",
    total_listado=10,
)

print(f"Total ofertas: {resultado.total_listado}")
print(f"Nuevas: {len(resultado.ofertas_nuevas)}")
print(f"Errores: {len(resultado.errores_por_oferta)}")
```

Si hay error global, las ofertas nuevas se excluyen automáticamente:

```python
resultado = ensamblar_resultado_pasada(
    timestamp_inicio="2026-01-18T01:00:00",
    timestamp_fin="2026-01-18T01:02:00",
    ofertas_nuevas=ofertas,  # Se ignoran por el error global
    errores_por_oferta=[ErrorOferta("062026003484", "Parseo fallido")],
    error_global="Timeout al conectar con el portal",
    total_listado=0,
)

print(resultado.error_global)  # "Timeout al conectar con el portal"
print(len(resultado.ofertas_nuevas))  # 0 (excluidas por error global)
```

## `scheduler`

Planificador que ejecuta una pasada automática diariamente a la hora configurada.
Si al momento de ejecutar ya hay una pasada en curso, omite la ejecución.
El scheduler se ejecuta en un hilo daemon en segundo plano y puede detenerse
gracefully.

```python
from source.api.buscador.coordinator import CoordinadorPasada
from source.api.buscador.models import ConfigBuscador
from source.api.buscador.scheduler import Scheduler


# Configurar hora de ejecución (ej: 01:00)
config = ConfigBuscador(hora_pasada=1)

# Crear coordinador (ver ejemplo en run-coordinator)
coordinador = CoordinadorPasada(...)

# Crear e iniciar scheduler
scheduler = Scheduler(coordinador, config)
scheduler.iniciar()

# El scheduler ejecutará una pasada diariamente a las 01:00
# Si hay una pasada en curso, omitirá la ejecución

# Para detener el scheduler (ej: al apagar la API)
scheduler.detener()
```

El scheduler acepta un reloj inyectable para testing:

```python
from datetime import datetime
from source.api.buscador.scheduler import Scheduler


class RelojControlado:
    def __init__(self, ahora: datetime):
        self._ahora = ahora

    def now(self) -> datetime:
        return self._ahora

    def sleep(self, segundos: float) -> None:
        pass  # No dormir en tests


reloj = RelojControlado(datetime(2026, 11, 18, 0, 59, 59))
scheduler = Scheduler(coordinador, config, reloj=reloj)
```

## `manual-trigger`

Endpoint HTTP `POST /buscador/run` que permite ejecutar una pasada manual del rastreador. Acepta un cuerpo JSON opcional con una lista de códigos históricos. Si no se proporciona, usa el fichero `data/seen_codes.json`. Devuelve el resultado de la pasada en formato JSON con la estructura de REQ-013.

```python
import httpx


# Ejecutar pasada manual sin códigos históricos (usa seen_codes.json)
response = httpx.post("http://localhost:8000/buscador/run")
resultado = response.json()

print(f"Total ofertas: {resultado['total_listado']}")
print(f"Ofertas nuevas: {len(resultado['ofertas_nuevas'])}")
print(f"Errores: {len(resultado['errores_por_oferta'])}")

# Ejecutar pasada manual con códigos históricos específicos
codigos_historicos = ["062026003484", "062026003485", "062026003486"]
response = httpx.post(
    "http://localhost:8000/buscador/run",
    json={"historical_codes": codigos_historicos}
)
resultado = response.json()

# Si hay una pasada en curso, el endpoint devuelve una respuesta de omisión
if resultado["error_global"] == "Ya hay una pasada en curso":
    print("Pasada omitida: ya hay una en curso")
```

El endpoint no requiere autenticación (NFR-003) y siempre devuelve HTTP 200, incluso si hay errores en la pasada o si está en curso otra pasada.

## `status-endpoint`

Endpoint HTTP `GET /buscador/status` que devuelve el estado actual del rastreador: si hay una pasada en curso, su progreso, y el resumen de la última pasada finalizada.

```python
import httpx


# Consultar estado del rastreador
response = httpx.get("http://localhost:8000/buscador/status")
estado = response.json()

if estado["in_progress"]:
    progreso = estado["progreso"]
    print(f"Pasada en curso desde {progreso['hora_inicio']}")
    print(f"Progreso: {progreso['codigos_procesados']}/{progreso['total_codigos']}")
else:
    print("No hay pasada en curso")

if estado["ultima_pasada"]:
    ultima = estado["ultima_pasada"]
    print(f"Última pasada: {ultima['timestamp']}")
    print(f"Total ofertas: {ultima['total_listado']}")
    print(f"Ofertas nuevas: {len(ultima['ofertas_nuevas'])}")
    print(f"Errores: {len(ultima['errores_por_oferta'])}")
else:
    print("No hay pasadas registradas")
```

El endpoint no requiere autenticación (NFR-003) y siempre devuelve HTTP 200, incluso si no hay pasadas registradas o si el coordinador no está disponible (en cuyo caso devuelve HTTP 503).

## `api-service` (lifespan)

La aplicación FastAPI gestiona el ciclo de vida del rastreador mediante un `lifespan` que:

**Al arrancar:**
- Lee la configuración desde `config/buscador.yaml` (o usa valores por defecto si no existe)
- Crea `data/seen_codes.json` si no existe (fichero vacío `[]`)
- Instancia el scheduler con la hora configurada

**Al apagar:**
- Detiene el scheduler gracefulmente
- Espera a que termine el hilo activo
- Limpia recursos

```python
from fastapi.testclient import TestClient
from source.api.main import app


# El TestClient maneja automáticamente el lifespan
with TestClient(app) as client:
    # La aplicación está arrancada con scheduler activo
    response = client.get("/buscador/status")
    print(f"Estado: {response.json()}")

# Al salir del bloque, el scheduler se detiene automáticamente
```

En producción, la aplicación se arranca con `uvicorn`:

```bash
uvicorn source.api.main:app --host 0.0.0.0 --port 8000
```

Al detener el servidor (Ctrl+C), el scheduler se cancela gracefulmente sin dejar tareas huérfanas.

