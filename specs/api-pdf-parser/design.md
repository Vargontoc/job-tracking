# Diseño: api-pdf-parser

Estado: aprobado
Revisión: 1
Basado en: requirements@2
Verificación: correcta

## Resumen

Se propone una API FastAPI síncrona con un único endpoint de parseo que lee un mapa interno de comunidades, descarga los PDF de difusión con `httpx`, extrae las ofertas con `pdfplumber` mediante heurísticas de línea (sectores, códigos de oferta, municipios y pies de página) y devuelve el resultado agregado por comunidad en la respuesta HTTP, sin persistencia ni inferencia. Se entregan además un `Modelfile` de referencia inerte y un `docker-compose.yaml` que levanta solo el contenedor de la API.

## Supuestos sobre el sistema actual

- El proyecto no tiene arquitectura previa definida en `.sdd/architecture.md` (plantilla vacía); este diseño propone los primeros módulos y contratos.
- No existe API previa; el endpoint es nuevo.
- La autenticación está fuera del alcance de esta feature (SUP-001 pendiente, asumida como API pública local).
- El mapa comunidad => URL es un artefacto de configuración estático gestionado por el propio repositorio, no por el cliente.
- Los PDFs tienen la estructura observada en `docs/contracts/ofertas_cantabria.txt`: sectores encabezados por `Sector Profesional:`, ofertas delimitadas por la línea `Oferta: <código>`, título multilínea hasta el municipio, fecha y oficina en líneas consecutivas (o interrumpidas por salto de página), y descripción multilínea hasta la siguiente oferta, sector o pie `Ofertas en difusión...`.

## Componentes

| Componente | Responsabilidad | Existente o nuevo |
|---|---|---|
| api-service | Aplicación FastAPI que expone el endpoint de parseo y orquesta el flujo. | nuevo |
| config-map | Fichero de configuración con el mapa interno comunidad => URL de PDF. | nuevo |
| pdf-downloader | Descarga el contenido binario de cada PDF usando `httpx`, con timeout y manejo de errores por comunidad. | nuevo |
| pdf-parser | Extrae texto del PDF con `pdfplumber` y lo segmenta en ofertas y sectores mediante heurísticas. | nuevo |
| response-assembler | Construye la respuesta JSON agregando ofertas y errores por comunidad. | nuevo |
| model-file | Artefacto `Modelfile` de referencia para Ollama; no se ejecuta. | nuevo |
| docker-compose | Definición para levantar solo el contenedor de la API. | nuevo |

## Flujo principal

1. El cliente invoca el endpoint de parseo de `api-service`.
2. `api-service` lee el `config-map` para obtener la lista de comunidades y sus URLs.
3. Para cada comunidad, `api-service` solicita a `pdf-downloader` la descarga del PDF.
4. `pdf-downloader` realiza la petición HTTP y, si tiene éxito, devuelve los bytes del PDF; si falla, devuelve un error controlado.
5. `api-service` pasa los bytes a `pdf-parser`, que extrae el texto completo, identifica los sectores profesionales y segmenta cada oferta.
6. `pdf-parser` devuelve, para cada oferta, los campos requeridos: denominación, municipio, código, fecha, oficina, descripción, sector profesional y comunidad.
7. `response-assembler` agrupa el resultado por comunidad, incluyendo ofertas parseadas y los errores de descarga/parseo sin interrumpir el resto.
8. `api-service` devuelve la respuesta JSON al cliente.

## Flujos alternativos y de fallo

### ALT-001 Fallo de descarga de una comunidad

- **Condición:** La URL de una comunidad es inaccesible, devuelve un código de error HTTP o se agota el timeout.
- **Comportamiento:** `pdf-downloader` informa del fallo a `api-service`; el proceso continúa con el resto de comunidades. `response-assembler` incluye la comunidad con estado de error y un mensaje descriptivo.
- **Responsable:** pdf-downloader
- **Resultado:** Respuesta HTTP 200 con el resultado parcial y el error detallado por comunidad.
- **Cubre:** REQ-007

### ALT-002 PDF descargado vacío o sin ofertas

- **Condición:** El PDF no contiene texto, no tiene sectores reconocidos o no se encuentra ninguna línea `Oferta:`.
- **Comportamiento:** `pdf-parser` devuelve una lista vacía de ofertas para esa comunidad. `response-assembler` marca la comunidad como procesada sin ofertas.
- **Responsable:** pdf-parser
- **Resultado:** Respuesta HTTP 200 con la comunidad en estado `ok` y lista de ofertas vacía.
- **Cubre:** REQ-008

### ALT-003 PDF con ofertas incompletas o campos ausentes

- **Condición:** Una oferta no contiene alguno de los campos esperados (por ejemplo, oficina ausente o líneas malformadas).
- **Comportamiento:** `pdf-parser` extrae los campos presentes y omite los ausentes (sin inventar valores). La oferta se incluye con los campos disponibles.
- **Responsable:** pdf-parser
- **Resultado:** Ofertas con campos opcionales faltantes; no se genera error.
- **Cubre:** REQ-004

### ALT-004 Oferta cortada por salto de página

- **Condición:** El pie de página `Ofertas en difusión...` o un salto de página divide el título, la fecha o la oficina de una oferta.
- **Comportamiento:** `pdf-parser` detecta y elimina las líneas de pie de página y reconstruye la oferta considerando la secuencia de líneas a lo largo de todas las páginas.
- **Responsable:** pdf-parser
- **Resultado:** Ofertas reconstruidas sin fragmentos de pie de página.
- **Cubre:** REQ-003

## Interfaces entre componentes

| Origen | Destino | Qué se comunica | Protocolo |
|---|---|---|---|
| Cliente | api-service | Petición de parseo sin cuerpo ni URL | HTTP (OpenAPI) |
| api-service | config-map | Lista de comunidades y URLs | lectura de fichero de configuración |
| api-service | pdf-downloader | Petición de descarga para una comunidad | llamada interna |
| pdf-downloader | URL externa | GET del PDF | HTTPS |
| pdf-downloader | api-service | Bytes del PDF o error por comunidad | llamada interna |
| api-service | pdf-parser | Bytes del PDF | llamada interna |
| pdf-parser | api-service | Lista de ofertas con campos y sector | llamada interna |
| api-service | response-assembler | Ofertas y errores por comunidad | llamada interna |
| response-assembler | api-service | Respuesta agregada final | llamada interna |

## Contrato de API

- **Endpoint propuesto:** `GET /parse` (o `GET /api/v1/parse` si se adopta prefijo de versión).
- **Petición:** Sin cuerpo ni parámetros obligatorios; el cliente no envía URL ni sube ficheros.
- **Respuesta exitosa (HTTP 200):**
  - Objeto raíz con metadatos del proceso (por ejemplo, comunidades procesadas, total de ofertas, timestamp).
  - Lista de resultados por comunidad; cada elemento indica el identificador de comunidad, el estado (`ok`/`error`), la lista de ofertas parseadas y, en caso de error, un mensaje descriptivo.
  - Cada oferta incluye: denominación, municipio, código de oferta, fecha de publicación, oficina, descripción completa, sector profesional y comunidad de origen.
- **Errores globales:** Solo se devuelven códigos HTTP 4xx/5xx cuando la propia API no puede atender la petición (por ejemplo, error interno no controlado o configuración ausente). Los fallos de descarga o parseo de una comunidad se comunican dentro del cuerpo JSON con estado por comunidad, sin bloquear al resto.

## Modelo de datos lógico

- **ComunidadConfigurada:** identificador único de comunidad y URL de su PDF de difusión. Relación: se lee desde el config-map y se usa para lanzar descargas.
- **ResultadoPorComunidad:** comunidad, estado, lista de ofertas y mensaje de error opcional. Relación: agrupa las ofertas extraídas de un mismo PDF.
- **Oferta:** denominación del puesto, municipio, código de oferta, fecha de publicación, oficina de empleo, descripción textual, sector profesional y comunidad de origen. Relación: pertenece a un ResultadoPorComunidad y a un SectorProfesional.
- **SectorProfesional:** nombre del sector tal como aparece en el PDF. Relación: contiene muchas Ofertas.

## Decisiones

### DEC-001 Extracción de texto con pdfplumber y heurísticas de línea

- **Decisión:** Usar `pdfplumber` para extraer el texto plano del PDF y aplicar heurísticas basadas en patrones de línea (`Sector Profesional:`, `Oferta:`, municipio, `Oficina:`, pie de página) en lugar de OCR o modelos de lenguaje.
- **Alternativas descartadas:** OCR (más lento y no necesario porque el PDF ya contiene texto) e inferencia con Ollama (excluida explícitamente por los requisitos).
- **Cubre:** REQ-003, REQ-004, REQ-008, SUP-003

### DEC-002 Segmentación de ofertas por el patrón de código

- **Decisión:** Cada oferta comienza en la línea que contiene `Oferta: <código>` (precedida por el título multilínea y el municipio) y termina justo antes de la siguiente línea con `Oferta:` o de un nuevo encabezado de sector/pie de página. Los sectores se heredan hasta el siguiente `Sector Profesional:`.
- **Alternativas descartadas:** Segmentación por bloques de coordenadas espaciales (más frágil ante variaciones de maquetación) y segmentación por expresiones regulares únicamente (insuficiente para descripciones multilínea).
- **Cubre:** REQ-003, REQ-004

### DEC-003 Configuración estática en un fichero de configuración

- **Decisión:** El mapa comunidad => URL se almacena en un fichero de configuración versionado (por ejemplo, YAML o JSON) en el repositorio.
- **Alternativas descartadas:** Variables de entorno (menos escalable para muchas comunidades) y base de datos (excluida por requisitos).
- **Cubre:** REQ-001, REQ-002, REQ-005, SUP-002

### DEC-004 Endpoint único síncrono para todas las comunidades

- **Decisión:** Exponer un único endpoint `GET` que procesa todas las comunidades configuradas en una sola petición y devuelve el resultado completo.
- **Alternativas descartadas:** Endpoint por comunidad con parámetro (el cliente no envía URL ni identificador, y los requisitos piden recorrer todas) y proceso asíncrono con callback (sobrepasa el alcance actual).
- **Cubre:** REQ-001, REQ-002, REQ-006

### DEC-005 Respuesta HTTP 200 con errores por comunidad

- **Decisión:** Ante fallos parciales (descarga o parseo de una comunidad), la API responde HTTP 200 incluyendo el error dentro del resultado de esa comunidad; solo errores globales de la API producen códigos 4xx/5xx.
- **Alternativas descartadas:** Fallo total con excepción (contradice REQ-007) y lista plana de ofertas sin metadatos por comunidad (dificulta REQ-005 y REQ-007).
- **Cubre:** REQ-006, REQ-007, REQ-008

### DEC-006 Modelfile inerte y docker-compose.yaml mínimo

- **Decisión:** Incluir un `Modelfile` en el repositorio como referencia futura, sin que la API ni el `docker-compose.yaml` lo usen. El `docker-compose.yaml` define únicamente el servicio de la API sobre Python 3.12, exponiendo `0.0.0.0:8000` mapeado al puerto `8000` del host.
- **Alternativas descartadas:** Incluir servicio Ollama en compose (fuera de alcance) y no entregar Modelfile (incumple REQ-009).
- **Cubre:** REQ-009, REQ-010

## Riesgos

- **Cambios en el formato del PDF de difusión:** Si la estructura de sectores o la ubicación de campos cambia, el parser dejará de extraer ofertas correctamente. Mitigación: tests con PDFs reales de ejemplo y monitorización del número de ofertas extraídas.
- **Ofertas con títulos o descripciones especialmente largos:** Pueden generar ambigüedad al separar ofertas. Mitigación: validar la heurística contra múltiples páginas del fichero de ejemplo y ajustar los delimitadores.
- **Timeout o bloqueo por parte del servidor de PDFs:** Puede ralentizar la respuesta de la API. Mitigación: timeout explícito en `pdf-downloader` y procesamiento por comunidad sin bloqueos cruzados.
- **Dependencia de la configuración estática:** Añadir nuevas comunidades requiere modificar el repositorio. Mitigación: formato de config-map sencillo y documentado.

## Trazabilidad

| Requisito | Componentes | Decisiones |
|---|---|---|
| REQ-001 | api-service, config-map | DEC-003, DEC-004 |
| REQ-002 | api-service, pdf-downloader | DEC-003, DEC-004 |
| REQ-003 | pdf-parser | DEC-001, DEC-002 |
| REQ-004 | pdf-parser | DEC-001, DEC-002 |
| REQ-005 | pdf-parser, response-assembler | DEC-003, DEC-005 |
| REQ-006 | api-service, response-assembler | DEC-004, DEC-005 |
| REQ-007 | pdf-downloader, response-assembler | DEC-005 |
| REQ-008 | pdf-parser, response-assembler | DEC-001, DEC-005 |
| REQ-009 | model-file | DEC-006 |
| REQ-010 | docker-compose | DEC-006 |

## Contratos afectados

| Protocolo | Contrato | Cambio |
|---|---|---|
| HTTP/OpenAPI | `docs/contracts/openapi/api-pdf-parser.yaml` (nuevo) | Define el endpoint de parseo, la estructura de la respuesta agregada por comunidad y los códigos de error globales. |
| Configuración | `config/comunidades.yaml` (nuevo) | Mapa interno comunidad => URL de PDF de difusión. |

## Cambios sugeridos al mapa

- `+ Módulo: api-pdf-parser | src/api_pdf_parser | API que parsea PDFs de ofertas por comunidad | -`
- `+ Módulo: config-map | config/comunidades.yaml | Mapa interno comunidad => URL de PDF | -`
- `+ Contrato: openapi | docs/contracts/openapi/api-pdf-parser.yaml | cliente -> api-pdf-parser`

## Estrategia de tests

- **Tests unitarios del parser:** Usar el texto extraído de `docs/contracts/ofertas_cantabria.txt` (o un PDF de prueba reducido) para verificar que se identifican los sectores, se segmentan las ofertas y se extraen los campos requeridos, incluyendo descripciones multilínea y ofertas cortadas por salto de página.
- **Tests del downloader con mocks:** Sustituir `httpx` por un cliente de prueba que devuelva bytes de PDF, errores HTTP y timeouts, comprobando que un fallo no bloquea al resto de comunidades.
- **Tests de integración del endpoint:** Lanzar la aplicación FastAPI con `TestClient`, mockear descargas y verificar que la respuesta JSON contiene ofertas con comunidad y sector, y errores por comunidad cuando corresponde.
- **Tests de configuración:** Validar que el fichero de config-map se carga correctamente y que una comunidad nueva se procesa sin cambios de código.
- **Tests de contratos:** Verificar que el `Modelfile` existe y que el `docker-compose.yaml` levanta el contenedor y responde en `localhost:8000`.

## Estructura de ficheros del repositorio

```
.
├── .sdd/
│   ├── architecture.md
│   └── project.md
├── config/
│   └── comunidades.yaml          # mapa interno comunidad => URL
├── docs/
│   └── contracts/
│       ├── ofertas_cantabria.txt # muestra de texto del PDF
│       └── openapi/
│           └── api-pdf-parser.yaml
├── src/
│   └── api_pdf_parser/
│       ├── __init__.py
│       ├── main.py               # aplicación FastAPI y endpoint
│       ├── config.py             # carga del config-map
│       ├── downloader.py         # descarga de PDFs con httpx
│       ├── parser.py             # extracción y segmentación con pdfplumber
│       ├── models.py             # entidades lógicas (sin persistencia)
│       └── routes/
│           └── parse.py          # ruta del endpoint de parseo
├── tests/
│   ├── fixtures/
│   │   └── sample.pdf            # PDF de prueba (mínimo)
│   ├── unit/
│   │   ├── test_parser.py
│   │   ├── test_downloader.py
│   │   └── test_config.py
│   └── integration/
│       └── test_api.py
├── Modelfile                     # definición de referencia para Ollama (inerte)
├── docker-compose.yaml           # solo contenedor de la API
├── pyproject.toml                # dependencias: FastAPI, httpx, pdfplumber
└── README.md
```
