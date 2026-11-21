# Sprint 02: api-buscador - api

Estado: aprobado

## Alcance

- Tareas: TASK-001, TASK-002, TASK-003, TASK-004, TASK-005, TASK-006, TASK-007, TASK-008, TASK-009, TASK-010, TASK-011, TASK-012, TASK-013, TASK-014, TASK-015, TASK-016, TASK-017, TASK-018, TASK-019, TASK-020, TASK-021, TASK-022, TASK-023 (de `specs/api-buscador/tasks.md`)
- Dependencias internas: TASK-002←TASK-001; TASK-003←TASK-001,TASK-002; TASK-004←TASK-002; TASK-005←TASK-003; TASK-006←TASK-001; TASK-007←TASK-003,TASK-005,TASK-006; TASK-008←TASK-005,TASK-006; TASK-009←TASK-002; TASK-010←TASK-009; TASK-011←TASK-002,TASK-007,TASK-008; TASK-012←TASK-004,TASK-007,TASK-008,TASK-009,TASK-010,TASK-011; TASK-013←TASK-003,TASK-012; TASK-014←TASK-012; TASK-015←TASK-012; TASK-016←TASK-003,TASK-013; TASK-017←TASK-014,TASK-015,TASK-016; TASK-018←TASK-014,TASK-015,TASK-017; TASK-019←TASK-003; TASK-020←TASK-003,TASK-007; TASK-021←TASK-006,TASK-007,TASK-008; TASK-022←TASK-005,TASK-012,TASK-013; TASK-023←TASK-017,TASK-018,TASK-019,TASK-020,TASK-021,TASK-022.
- Dependencias externas: Ninguna.

## Origen SDD

- Requirements: 5
- Design: 2
- Tasks: 2

## Enfoque técnico

Se añade a la FastAPI síncrona existente un subpaquete `source/api/buscador/` con el rastreador del buscador HTML de Emplea Cantabria: scheduler en proceso (stdlib `threading`, reloj inyectable), rate-limiter global de 10 s, recorrido del listado y parseo de ficha con `selectolax`, estado persistente solo en `data/seen_codes.json`, archivo y purga de HTML fallidos, y dos endpoints (`POST /buscador/run`, `GET /buscador/status`). Sin SQLite ni autenticación.

- Sigue las convenciones de `api-pdf-parser`: dataclasses puras con valores por defecto, excepciones propias (`ErrorConfiguracion`), funciones en español, tests en `tests/unit|integration|contract`.
- El código nuevo vive en `source/api/buscador/` (subpaquete de `source/api`, no módulo nuevo); el subpaquete es importable pero no referencia ningún motor de base de datos (DEC-002).
- Única dependencia externa nueva: `selectolax` en `pyproject.toml`. El planificador es "en proceso" con `threading`, sin librería de scheduling.
- Rutas por defecto `/buscador/run` y `/buscador/status`; los fallos de pasada no cambian el HTTP (200), como en `api-pdf-parser`.
- Contratos implementation-first (TASK-018 tras TASK-017; TASK-019/020 tras TASK-003/007); `sector`, `nivel` y `contrato` se modelan y se devuelven siempre vacíos (DEC-009).

## Cambios por tarea

### TASK-001 Estructura del paquete del buscador y dependencias

- **Ficheros:** `source/api/buscador/__init__.py` (nuevo): subpaquete importable; `pyproject.toml` (modificar): añadir `selectolax` a `[project] dependencies`. Componente `api-service` → `source/api/buscador` (propuesta).
- **Enfoque:** subpaquete vacío que se importa sin errores; única dependencia nueva `selectolax` (DEC-004). El mecanismo de planificación en proceso se resuelve con `threading` de la stdlib, así que no se declara dependencia externa para él. El paquete no importa ni referencia SQLite, SQLAlchemy ni clientes de Ollama (DEC-002).
- **Pruebas automáticas:** `tests/unit/test_buscador_imports.py` (nuevo) — importar `source.api.buscador` no lanza error; `selectolax` está disponible; `source/api/buscador` no importa motores de BD (SQLite/SQLAlchemy). Comando: `pytest tests/unit/test_buscador_imports.py`.
- **Prueba manual:** instalar en un venv limpio (`pip install -e .`) y ejecutar `pytest`: termina sin fallos por dependencias ausentes ni por colección.

### TASK-002 Modelos de dominio del rastreador

- **Ficheros:** `source/api/buscador/models.py` (nuevo): dataclasses `ConfigBuscador`, `OfertaBuscador`, `CodigoVisto`, `HtmlFallido`, `ErrorOferta` y `ResultadoPasada`. Componente `response-assembler` → `source/api/buscador/models.py` (propuesta).
- **Enfoque:** entidades puras sin DB ni serialización a disco. `OfertaBuscador` con los 8 campos que publica la ficha (numero_oferta, ocupacion, municipio, provincia, fecha_inicio_difusion, fecha_fin_difusion, texto_libre, contacto) más `comunidad` con valor por defecto "Cantabria" (SUP-003), y `sector`, `nivel`, `contrato` presentes pero siempre vacíos (DEC-009). `ResultadoPasada` con timestamp, comunidad, total de ofertas del listado, `error_global` (vacío si no hay), `errores_por_oferta` (lista de `ErrorOferta` con código y mensaje) y `ofertas_nuevas`. La provincia es el dato publicado por la ficha, no una copia de la comunidad.
- **Pruebas automáticas:** `tests/unit/test_buscador_models.py` (nuevo) — `OfertaBuscador` conserva los campos publicados; `sector`/`nivel`/`contrato` quedan vacíos sin inferir de otros campos; sin contacto el campo queda vacío y no aparece ningún campo `empresa` ni de persistencia; `ResultadoPasada` se construye con lista de errores vacía y con un error global + un error por oferta; la comunidad por defecto es Cantabria y la provincia no la copia. Comando: `pytest tests/unit/test_buscador_models.py`.
- **Prueba manual:** revisar las entidades y comprobar que cubren el modelo de datos lógico del diseño, con `sector`/`nivel`/`contrato` reservados y vacíos, y sin campos de persistencia.

### TASK-003 Fichero de configuración del buscador y validación de la hora

- **Ficheros:** `config/buscador.yaml` (nuevo): URL del listado, URL de la ficha, hora (01:00), User-Agent, delay (10), tamaño de página (75) y rutas de `seen_codes.json` y `failed_htmls/`; `source/api/buscador/config.py` (nuevo): carga YAML + validación de la hora. Componente `config-buscador` → `config/buscador.yaml` + `source/api/buscador/config.py` (propuesta).
- **Enfoque:** carga con PyYAML siguiendo el patrón de `source/api/config.py` (excepción propia tipo `ErrorConfiguracion`); valores por defecto cuando falta el fichero o el campo (hora 1, delay 10, página 75); la hora se valida como entero único entre 0 y 23; cualquier otro valor (lista, minutos, fracción, cron) se rechaza con error controlado que identifica la configuración como origen.
- **Pruebas automáticas:** `tests/unit/test_buscador_config.py` (nuevo) — carga completa con hora/URLs/User-Agent/delay/página/rutas; sin fichero → hora 1, página 75, delay 10; hora 0 y 23 aceptadas; hora 24 y negativa rechazadas; lista/minutos/fracción/cron rechazados sin dejar estado inválido; User-Agent con nombre del proyecto y medio de contacto (NFR-001); fichero ausente o malformado → error controlado de configuración. Comando: `pytest tests/unit/test_buscador_config.py`.
- **Prueba manual:** abrir `config/buscador.yaml` y comprobar los campos; cambiar la hora a 23, recargar y confirmar que la nueva hora se muestra y la página sigue en 75.

### TASK-004 Fichero local de códigos vistos

- **Ficheros:** `source/api/buscador/state.py` (nuevo): lectura y escritura de `data/seen_codes.json`. Componente `state-store` → `source/api/buscador/state.py` (propuesta).
- **Enfoque:** carga el conjunto de códigos al arrancar; si el fichero no existe, lo crea vacío y devuelve conjunto vacío; la escritura une los códigos nuevos a los anteriores sin duplicados. Único estado persistente de la feature; no abre ni escribe ninguna base de datos (DEC-002). JSON inválido → error controlado que identifica el fichero.
- **Pruebas automáticas:** `tests/unit/test_buscador_state.py` (nuevo) — fichero con 3 códigos devuelve los 3; fichero inexistente → conjunto vacío y fichero creado; guardar un código nuevo conserva los anteriores (recarga devuelve 4); guardar un código ya presente no lo duplica; JSON inválido → error controlado; no se abre ninguna BD. Comando: `pytest tests/unit/test_buscador_state.py`.
- **Prueba manual:** arrancar sin `data/seen_codes.json` y comprobar que aparece vacío; añadir un código a mano, reiniciar y comprobar que se reconoce.

### TASK-005 Limitador global de peticiones al portal

- **Ficheros:** `source/api/buscador/rate_limiter.py` (nuevo). Componente `rate-limiter` → `source/api/buscador/rate_limiter.py` (propuesta).
- **Enfoque:** un único componente compartido que regula todas las peticiones salientes (listado, fichas y reintentos). Garantiza al menos 10 s entre peticiones consecutivas, con reloj inyectable para pruebas; la primera petición no espera; aplica el User-Agent de la configuración y ninguna cabecera de credenciales ni autenticación (NFR-001, NFR-003).
- **Pruebas automáticas:** `tests/unit/test_buscador_rate_limiter.py` (nuevo) — con reloj controlado, dos y tres peticiones consecutivas separadas ≥10 s; la primera no espera; el limitador es compartido (tras una petición de listado la siguiente ficha espera el resto); el User-Agent enviado identifica el proyecto y el contacto; ninguna petición lleva credenciales. Comando: `pytest tests/unit/test_buscador_rate_limiter.py`.
- **Prueba manual:** registrar timestamps de una secuencia real de peticiones y comprobar que ninguna separación es menor de 10 s.

### TASK-006 Muestras HTML del contrato como fixtures de los tests

- **Ficheros:** `tests/fixtures/buscador/` (nuevo): `listado_pagina_1.html`, `listado_pagina_2.html`, `listado_vacio.html` y `ficha_062026003633.html`, copiados (o referenciados) desde `docs/contracts/html/empleacantabria/`. Componente `api-buscador` → `tests/fixtures/buscador` (propuesta).
- **Enfoque:** incorporar las 4 muestras reales (reducidas) del contrato y verificar que conservan la estructura que necesitan los tests: `table.table` → `tbody.table-data` con código en `a[href*="/ofertas-cantabria/-/oferta/"]`, total/rango en `small.search-results`, paginación en `ul.lfr-pagination-buttons` con `_..._delta=75` y `_..._cur=N`, estado vacío con `.lfr-search-container.hide` y "No hay resultados", y ficha con `input[readonly]` por sufijo de `id`. Por defecto se copian (tests autocontenidos); la referencia al contrato es alternativa válida.
- **Pruebas automáticas:** `tests/unit/test_buscador_fixtures.py` (nuevo) — la página 1 declara `1 - 75 de 93` y conserva 3 filas de 12 dígitos; la página 2 declara `76 - 93 de 93`, 3 filas y sin página siguiente; el listado vacío no tiene `small.search-results` y sí el mensaje; la ficha contiene los 6 `input[readonly]` por sufijo y los bloques de texto libre/contacto; los 4 ficheros coinciden con sus originales (si se copiaron) o se resuelven desde la ruta del contrato. Comando: `pytest tests/unit/test_buscador_fixtures.py`.
- **Prueba manual:** comparar cada fixture con su original en `docs/contracts/html/empleacantabria/` y confirmar que no hay campos `sector`, `nivel` ni `contrato` en la ficha.

### TASK-007 Recorrido del listado paginado a 75 ofertas

- **Ficheros:** `source/api/buscador/scraper.py` (nuevo). Componente `list-scraper` → `source/api/buscador/scraper.py` (propuesta).
- **Enfoque:** recorrido con `selectolax` de las filas `table.table → tbody.table-data → tr`, tomando el texto de `a[href*="/ofertas-cantabria/-/oferta/"]` como código de 12 dígitos conservado como texto; deduce el total del texto de `small.search-results` (única fuente del total); sigue la paginación con tamaño 75; detecta la última página por rango + paginación sin "siguiente"; detecta el vacío por `.lfr-search-container.hide` + mensaje, como total 0. Error HTTP, timeout o estructura no reconocida → error global con el punto alcanzado, sin marcar ofertas nuevas. Todas las peticiones pasan por el rate-limiter.
- **Pruebas automáticas:** `tests/unit/test_buscador_scraper.py` (nuevo) — con las dos páginas se reconocen `1 - 75 de 93` y `76 - 93 de 93`, total 93, dos peticiones con tamaño 75; códigos de 12 dígitos como texto sin perder ceros; URL con parámetro de tamaño 75 (NFR-004); la página 2 se reconoce como última; listado vacío → total 0, sin códigos y sin error; variante sin `small.search-results` → error global de parseo; cliente con error HTTP → error global con el código; timeout → error global; segunda página fallida → se detiene e informa de la página alcanzada; listado con todos los códigos ya vistos → ninguna oferta nueva. Comando: `pytest tests/unit/test_buscador_scraper.py`.
- **Prueba manual:** recorrer el buscador real y comprobar que el número de códigos extraídos coincide con el total del portal.

### TASK-008 Descarga y parseo de la ficha de una oferta

- **Ficheros:** `source/api/buscador/parser.py` (nuevo). Componente `detail-parser` → `source/api/buscador/parser.py` (propuesta).
- **Enfoque:** descarga de la ficha a través del rate-limiter y extracción con `selectolax` de los `input[readonly]` por sufijo de `id` (`_numeroOferta`, `_ocupacion`, `_municipio`, `_provincia`, `_fechaInicioDifusion`, `_fechaFinDifusion`) y del texto libre y el contacto tras `label.dAdicionales` / `label.dContacto`. `sector`/`nivel`/`contrato` quedan vacíos sin inferencia (DEC-009); normaliza espacios y saltos; fechas `dd/mm/aaaa`; un único reintento tras la pausa de cortesía (DEC-007); en éxito no conserva el HTML (REQ-010).
- **Pruebas automáticas:** `tests/unit/test_buscador_parser.py` (nuevo) — con la ficha real se extraen `062026003633`, ocupación, `SANTANDER`, `CANTABRIA`, `18/11/2026`, `03/12/2026`, texto libre y contacto; `sector`/`nivel`/`contrato` vacíos; texto libre y contacto normalizados; fechas `dd/mm/aaaa` y número como texto de 12 dígitos; variante sin contacto → contacto vacío y resto conservado; variante con inputs vacíos → campos vacíos sin inventar; cliente que falla en la 1ª y responde en la 2ª → éxito con dos peticiones separadas ≥10 s; cliente que falla siempre → exactamente 2 peticiones y error por oferta persistente; en éxito no devuelve el HTML; todas las peticiones pasan por el limitador con el User-Agent configurado. Comando: `pytest tests/unit/test_buscador_parser.py`.
- **Prueba manual:** pedir la ficha real de una oferta del listado y comprobar los campos extraídos contra el portal, con `sector`/`nivel`/`contrato` vacíos.

### TASK-009 Archivo del HTML de las fichas fallidas

- **Ficheros:** `source/api/buscador/archive.py` (nuevo). Componente `html-archive` → `source/api/buscador/archive.py` (propuesta).
- **Enfoque:** guarda el HTML original de una ficha fallida en `data/failed_htmls/<codigo>_<yyyy-mm-dd>.html`; crea el directorio si falta; si la escritura no es posible devuelve un error por oferta que lo indica sin detener la pasada (ALT-006). El nombre usa el código sin transformar y la fecha ISO.
- **Pruebas automáticas:** `tests/unit/test_buscador_archive.py` (nuevo) — ficha fallida `062026003484` crea `data/failed_htmls/062026003484_<fecha>.html` con el contenido recibido; directorio inexistente → se crea y escribe; directorio no escribible → error controlado sin excepción; nombre con fecha `yyyy-mm-dd` y código intacto; dos archivos del mismo código el mismo día no producen nombres ambiguos ni pérdida. Comando: `pytest tests/unit/test_buscador_archive.py`.
- **Prueba manual:** provocar un fallo de parseo real y comprobar que el fichero aparece en `data/failed_htmls/` con el nombre y contenido esperados.

### TASK-010 Purga de los HTML fallidos caducados

- **Ficheros:** `source/api/buscador/purger.py` (nuevo). Componente `archive-purger` → `source/api/buscador/purger.py` (propuesta).
- **Enfoque:** elimina los ficheros `.html` de `data/failed_htmls/` con más de 7 días de antigüedad, calculada a partir de la fecha `yyyy-mm-dd` del nombre; conserva los de 7 días o menos y no toca `seen_codes.json`. Directorio vacío o inexistente no falla.
- **Pruebas automáticas:** `tests/unit/test_buscador_purger.py` (nuevo) — fichero fechado hace 8 días se elimina; hace exactamente 7 días se conserva; hace 1 día se conserva; directorio vacío/inexistente no falla; solo afecta a `.html` del directorio y no toca `seen_codes.json`. Comando: `pytest tests/unit/test_buscador_purger.py`.
- **Prueba manual:** crear a mano un HTML fallido con fecha antigua, ejecutar la purga y comprobar que desaparece mientras los recientes permanecen.

### TASK-011 Ensamblado del resultado estructurado de la pasada

- **Ficheros:** `source/api/buscador/assembler.py` (nuevo). Componente `response-assembler` → `source/api/buscador/assembler.py` (propuesta).
- **Enfoque:** construye el JSON de resultado con metadatos (timestamp, comunidad Cantabria, total del listado), error global (si lo hay), errores por oferta y ofertas nuevas. Sin persistencia ni referencia a SQLite (DEC-002). Fallo global → lista de ofertas vacía; listado vacío → total 0, sin errores y sin ofertas.
- **Pruebas automáticas:** `tests/unit/test_buscador_assembler.py` (nuevo) — pasada con 2 ofertas nuevas + 1 error por oferta incluye ofertas, total, timestamp y errores; error global → ofertas vacías y total alcanzado; listado vacío → total 0, sin errores ni ofertas; comunidad Cantabria presente; sin campos de persistencia ni referencia a SQLite. Comando: `pytest tests/unit/test_buscador_assembler.py`.
- **Prueba manual:** revisar un resultado de ejemplo con ofertas, error global y error por oferta y comprobar que se distingue el origen de cada dato.

### TASK-012 Coordinador de una pasada y exclusión mutua

- **Ficheros:** `source/api/buscador/coordinator.py` (nuevo). Componente `run-coordinator` → `source/api/buscador/coordinator.py` (propuesta).
- **Enfoque:** ciclo completo de una pasada: carga códigos vistos, recorre el listado, descarta vistos, pide ficha de cada código nuevo, registra para persistir los parseados correctamente, ejecuta la purga al final y libera el estado. Mantiene en memoria el flag "pasada en curso", el último resultado y el progreso, compartidos con el scheduler y el endpoint manual; una segunda solicitud de inicio se rechaza dejando constancia de la omisión (ALT-004). Admite una lista histórica explícita en lugar del fichero local.
- **Pruebas automáticas:** `tests/unit/test_buscador_coordinator.py` (nuevo) — listado de 3 códigos con 1 ya visto → solo se piden 2 fichas; al final `seen_codes.json` contiene solo los parseados correctamente; lista histórica explícita filtra en lugar del fichero; sin lista usa el fichero local; pasada en curso → segunda solicitud rechazada sin lanzar otra y con constancia; al terminar queda listo sin flag residual ni huérfanos; ficha fallida en pasada anterior se vuelve a pedir si sigue en el listado; al terminar se ejecuta la purga; recorrido fallido → error global y sin persistir códigos. Comando: `pytest tests/unit/test_buscador_coordinator.py`.
- **Prueba manual:** lanzar una pasada manual con listado simulado y comprobar `seen_codes.json`: contiene exactamente los códigos parseados correctamente.

### TASK-013 Planificador diario de la pasada automática

- **Ficheros:** `source/api/buscador/scheduler.py` (nuevo). Componente `scheduler` → `source/api/buscador/scheduler.py` (propuesta).
- **Enfoque:** tarea en proceso (thread con reloj inyectable) que calcula la siguiente hora configurada, espera y delega en el coordinador el inicio de una pasada; al terminar reprograma para el día siguiente; se cancela al apagar la API; si ya hay una pasada en curso omite el disparo dejando constancia (ALT-004, REQ-003). Sin librería externa: `threading.Event` para cancelación y función de reloj inyectable para pruebas.
- **Pruebas automáticas:** `tests/unit/test_buscador_scheduler.py` (nuevo) — reloj 00:59:59 con hora 01:00 → sin pasada; reloj 01:00:00 → exactamente una pasada; +24 h → exactamente una pasada más; hora 23 dispara a las 23:00:00; pasada en curso → no inicia otra y queda constancia; cancelar → no inicia más pasadas ni quedan tareas. Comando: `pytest tests/unit/test_buscador_scheduler.py`.
- **Prueba manual:** arrancar la API con la hora configurada a un minuto próximo y observar que la pasada arranca sola a esa hora exacta.

### TASK-014 Endpoint de pasada manual

- **Ficheros:** `source/api/buscador/routes.py` (nuevo): endpoint `POST /buscador/run`; `source/api/main.py` (modificar): registrar la ruta. Componente `manual-trigger` → `source/api/buscador/routes.py` (propuesta).
- **Enfoque:** endpoint HTTP que delega en el coordinador; cuerpo JSON opcional con `historical_codes`; sin cuerpo usa `data/seen_codes.json`; la respuesta es la misma estructura de resultado que la pasada automática; invocación durante una pasada en curso devuelve la respuesta de omisión (HTTP 200) sin iniciar otra (REQ-003, DEC-008). Sin autenticación (NFR-003).
- **Pruebas automáticas:** `tests/integration/test_buscador_api.py` (nuevo) — la ruta está registrada con método POST y acepta cuerpo opcional; sin cuerpo filtra con el fichero local; con `historical_codes` filtra con esa lista; la respuesta coincide con la estructura de REQ-013; pasada en curso → 200 con omisión y sin nueva pasada; sin credenciales ni cabeceras de autenticación. Comando: `pytest tests/integration/test_buscador_api.py::test_manual_run`.
- **Prueba manual:** invocar `POST /buscador/run` sin cuerpo y con lista de códigos históricos, y comprobar el filtrado y la estructura de REQ-013.

### TASK-015 Endpoint de estado de la última pasada

- **Ficheros:** `source/api/buscador/routes.py` (modificar): endpoint `GET /buscador/status`; `source/api/main.py` (modificar): registrar la ruta. Componente `status-endpoint` → `source/api/buscador/routes.py` (propuesta).
- **Enfoque:** lee el estado compartido del coordinador; sin pasada en curso indica explícitamente que no la hay y muestra el resumen de la última finalizada; con pasada en curso indica `in_progress` en true con hora de inicio y progreso; el resumen incluye timestamp, total del listado, ofertas nuevas, error global y errores por oferta. Sin autenticación.
- **Pruebas automáticas:** `tests/integration/test_buscador_api.py` — sin pasadas registradas → indica que no hay pasada en curso ni última finalizada; con pasada en curso → `in_progress` true con hora de inicio y progreso; finalizada → `in_progress` false con el resumen completo; tras una pasada con 2 nuevas y 1 error por oferta el resumen lo refleja; sin credenciales. Comando: `pytest tests/integration/test_buscador_api.py::test_status`.
- **Prueba manual:** consultar el estado en reposo y durante una pasada manual larga, y comprobar la hora de inicio y el resumen.

### TASK-016 Arranque y apagado de la API con el planificador

- **Ficheros:** `source/api/main.py` (modificar): lifespan de FastAPI que carga la configuración del buscador, lee/crea `data/seen_codes.json`, arranca el scheduler con la hora configurada y lo cancela al apagar. Componente `api-service` → `source/api/main.py` (propuesta).
- **Enfoque:** al arrancar se lee `config/buscador.yaml`, se lee `data/seen_codes.json` (creándolo si falta) y queda activo el scheduler; al apagar se cancela sin tareas vivas. Ningún endpoint exige credenciales (NFR-003); con hora inválida se conserva la anterior o la por defecto 01:00 (ALT-005).
- **Pruebas automáticas:** `tests/integration/test_buscador_api.py` — tras arrancar, `data/seen_codes.json` se lee/crea y el scheduler está activo con la hora de configuración; al apagar, el scheduler queda cancelado; cada endpoint responde sin credenciales (sin 401/403); hora inválida → conserva la anterior o 01:00; no se crea ni modifica ningún fichero de BD. Comando: `pytest tests/integration/test_buscador_api.py::test_startup_shutdown`.
- **Prueba manual:** levantar la app, comprobar que `data/seen_codes.json` existe y el endpoint de estado responde; detener y comprobar que no queda tarea de planificación viva.

### TASK-017 Verificación de integración de la pasada completa

- **Ficheros:** `tests/integration/test_buscador_api.py` (modificar): end-to-end con `TestClient` y portal simulado (cliente HTTP de prueba). Componente `api-service` → `source/api/` (propuesta).
- **Enfoque:** monta la aplicación con cliente de prueba y portal simulado; cubre los casos de listado con ofertas nuevas, ficha fallida persistente (HTML archivado), error HTTP global, listado vacío y solapamiento, verificando el estado posterior y que ningún fallo cambie el HTTP (sigue 200).
- **Pruebas automáticas:** `tests/integration/test_buscador_api.py` — listado de 2 códigos nuevos → 2 ofertas y `seen_codes.json` con esos 2; una ficha fallida persistente → error por oferta, HTML archivado y solo el código correcto en el fichero; error HTTP del portal → error global, ofertas vacías y fichero sin cambios; listado vacío → total 0 y fichero sin cambios; pasada en curso → segunda invocación devuelve omisión; tras la pasada el estado muestra el resumen; los fallos no cambian el HTTP (200); no se crea fichero de BD. Comando: `pytest tests/integration/test_buscador_api.py`.
- **Prueba manual:** ejecutar la prueba de integración y revisar que todos los escenarios salen con el resultado esperado; revisar `data/`: solo `seen_codes.json` y `failed_htmls/` con el HTML de la ficha fallida.

### TASK-018 Contrato: openapi - endpoints de pasada manual y de estado

- **Ficheros:** `docs/contracts/openapi/api-buscador.yaml` (nuevo): contrato OpenAPI de los endpoints verificados. Componente `api-service` → contrato openapi (tarea del documentador).
- **Enfoque:** documentar `POST /buscador/run` y `GET /buscador/status` tal como quedaron implementados (implementation-first, tras TASK-017): esquemas de `ResultadoPasada`, `OfertaBuscador` (con `sector`, `nivel` y `contrato` presentes y opcionales, descritos como vacíos porque la ficha no los publica — DEC-009), `ErrorOferta`, el cuerpo opcional `historical_codes` y la respuesta de omisión por solapamiento.
- **Pruebas automáticas:** `tests/contract/test_buscador_openapi.py` (nuevo) — el YAML carga y contiene las dos operaciones con su respuesta 200 y los esquemas; el esquema de oferta incluye `sector`/`nivel`/`contrato` como campos presentes, opcionales y descritos como vacíos; documenta el cuerpo opcional y la omisión; los campos del esquema coinciden con la respuesta de la integración; las rutas coinciden con las registradas. Comando: `pytest tests/contract/test_buscador_openapi.py`.
- **Prueba manual:** comparar el contrato con la respuesta JSON real de TASK-017 y confirmar que no hay campos divergentes.

### TASK-019 Contrato: configuración - fichero de configuración del buscador

- **Ficheros:** `config/buscador.yaml` (documentar formato): formalizar el formato exacto y las reglas de validación alineadas con la carga de TASK-003. Componente `config-buscador` → `config/buscador.yaml` (tarea del documentador; la fila "Configuración" apunta al propio fichero, como en `api-pdf-parser`).
- **Enfoque:** documentar en la cabecera del fichero el formato (URL de listado, URL de ficha, hora como entero único, User-Agent, delay, tamaño de página, rutas de datos y días de purga) y las reglas de validación de la hora; el fichero real cumple el formato sin ambigüedad y una configuración válida se carga sin cambios de código.
- **Pruebas automáticas:** `tests/contract/test_buscador_config_contract.py` (nuevo) — el fichero carga con el formato documentado y devuelve hora/URLs/User-Agent/delay/página/rutas; hora fuera de rango o no entera → error controlado; campos obligatorios ausentes → error que identifica el campo; los valores por defecto (01:00, 10 s, 75, 7 días) coinciden con la implementación. Comando: `pytest tests/contract/test_buscador_config_contract.py`.
- **Prueba manual:** modificar el fichero siguiendo solo el formato documentado y comprobar que la API arranca con la nueva configuración.

### TASK-020 Contrato: configuración - URLs del buscador en el mapa de comunidades

- **Ficheros:** `config/buscador.yaml` (documentar las URLs del buscador); **no** modificar `config/comunidades.yaml`. Componente `config-map` → documentación en el contrato de configuración (tarea del documentador; aviso 8 del tasks.md permite dejar solo la documentación).
- **Enfoque:** decisión adoptada: las URLs del buscador HTML y de la ficha viven en `config/buscador.yaml` (fichero propio del buscador) y `config/comunidades.yaml` se mantiene como mapa exclusivo de PDFs, sin mezclar responsabilidades. La tarea documenta esta relación y el formato de las URLs (coincidentes con las que `scraper.py` y `parser.py` consumen), dejando explícito que una comunidad sin URLs de buscador se trata como no apta para el rastreo.
- **Pruebas automáticas:** `tests/contract/test_buscador_config_contract.py` (modificar) — el caso de Cantabria del buscador declara las URLs de listado y ficha; una configuración de buscador sin URLs → error controlado; la URL del listado devuelta es la que usa el recorrido para construir sus peticiones. Comando: `pytest tests/contract/test_buscador_config_contract.py`.
- **Prueba manual:** revisar que las URLs del buscador y de la ficha coinciden con las del portal y con las usadas en `config/buscador.yaml`.

### TASK-021 Variantes derivadas de las muestras del contrato

- **Ficheros:** `tests/fixtures/buscador/` (nuevos): `ficha_sin_contacto.html`, `listado_sin_total.html` y `ficha_inputs_vacios.html`, derivados de los ficheros del contrato. Componente `api-buscador` → `tests/fixtures/buscador` (propuesta).
- **Enfoque:** tres variantes mínimas derivadas del contrato (única fuente de verdad), sin inventar estructuras: ficha sin bloque de contacto, listado sin `small.search-results` (estructura no reconocida) y ficha con `input` vacíos. Cada variante es una copia modificable del fichero del que sale y es consumida por al menos una prueba.
- **Pruebas automáticas:** `tests/unit/test_buscador_fixtures.py` (modificar) + consumo en `test_buscador_scraper.py` y `test_buscador_parser.py` — la ficha sin contacto se parsea con contacto vacío y resto conservado; el listado sin `small.search-results` se comunica como error global sin excepción; la ficha con inputs vacíos se parsea con campos vacíos sin inventar; cada variante se referencia desde al menos una prueba. Comando: `pytest tests/unit/test_buscador_fixtures.py tests/unit/test_buscador_scraper.py tests/unit/test_buscador_parser.py`.
- **Prueba manual:** comparar cada variante con su fichero del contrato y comprobar que la única diferencia es la que la variante pretende provocar.

### TASK-022 Pruebas de frecuencia de peticiones y de solapamiento

- **Ficheros:** `tests/unit/test_buscador_frequency_overlap.py` (nuevo). Componente `rate-limiter` → `tests/unit/test_buscador_frequency_overlap.py` (propuesta).
- **Enfoque:** verificación con reloj controlado de la frecuencia global en una pasada completa (páginas de listado + fichas + reintento mezclados) y del solapamiento entre scheduler y endpoint manual; ninguna pareja de peticiones consecutivas por debajo de 10 s y ninguna pasada solapada.
- **Pruebas automáticas:** `tests/unit/test_buscador_frequency_overlap.py` — la secuencia completa respeta ≥10 s entre pares consecutivos; la primera petición no espera; con pasada en curso, el disparo del scheduler y la invocación manual se rechazan ambos; con el listado del contrato (93 en dos páginas de 75) el número de peticiones de listado es el esperado; en 24 h simuladas con configuración por defecto hay exactamente una pasada automática. Comando: `pytest tests/unit/test_buscador_frequency_overlap.py`.
- **Prueba manual:** revisar el informe de la prueba y confirmar que todos los intervalos medidos son ≥10 s.

### TASK-023 Actualización del mapa de arquitectura

- **Ficheros:** `.sdd/architecture.md` (modificar): registrar los módulos nuevos, el contrato OpenAPI, las tres convenciones de rastreo y actualizar el módulo `API`. Componente `api-service` → `.sdd/architecture.md` (tarea del documentador).
- **Enfoque:** una entrada por módulo nuevo del buscador con identificador, ruta, responsabilidad y dependencias (api-buscador, config-buscador, scheduler, run-coordinator, rate-limiter, state-store, list-scraper, detail-parser, html-archive, archive-purger, response-assembler, manual-trigger, status-endpoint), el contrato openapi del buscador, las tres convenciones de rastreo (user-agent, delay 10 s, page-size 75) y la descripción de `API` ampliada al rastreo del buscador. Usa las rutas definitivas realmente implementadas.
- **Pruebas automáticas:** `tests/contract/test_buscador_architecture.py` (nuevo) — `.sdd/architecture.md` incluye los identificadores de todos los módulos nuevos con ruta no vacía; la sección de contratos incluye el OpenAPI del buscador; la sección de convenciones incluye las tres de rastreo; la descripción de `API` ya no se limita al parseo de PDFs; todos los ficheros citados existen. Comando: `pytest tests/contract/test_buscador_architecture.py`.
- **Prueba manual:** revisar `.sdd/architecture.md` y comprobar que cada módulo nuevo tiene identificador, ruta y dependencias, y que las rutas coinciden con los ficheros creados.

## Orden de implementación

1. TASK-001 (habilitada por: sin dependencias)
2. TASK-002 (habilitada por: TASK-001 entregada — subpaquete importable y dependencia `selectolax` declarada)
3. TASK-003 (habilitada por: TASK-002 entregada — entidades de dominio definidas)
4. TASK-004 (habilitada por: TASK-002), TASK-005 (habilitada por: TASK-003) y TASK-006 (habilitada por: TASK-001) — en paralelo
5. TASK-007 (habilitada por: TASK-003, TASK-005 y TASK-006 entregadas) y TASK-008 (habilitada por: TASK-005 y TASK-006) — en paralelo
6. TASK-009 (habilitada por: TASK-002) y TASK-010 (habilitada por: TASK-009 entregada) — secuencial
7. TASK-011 (habilitada por: TASK-002, TASK-007 y TASK-008 entregadas)
8. TASK-012 (habilitada por: TASK-004, TASK-007, TASK-008, TASK-009, TASK-010 y TASK-011 entregadas)
9. TASK-013 (habilitada por: TASK-003 y TASK-012), TASK-014 (habilitada por: TASK-012) y TASK-015 (habilitada por: TASK-012) — en paralelo
10. TASK-016 (habilitada por: TASK-003 y TASK-013 entregadas)
11. TASK-017 (habilitada por: TASK-014, TASK-015 y TASK-016 entregadas)
12. TASK-018 (habilitada por: TASK-014, TASK-015 y TASK-017 entregadas), TASK-019 (habilitada por: TASK-003) y TASK-020 (habilitada por: TASK-003 y TASK-007) — en paralelo (implementation-first)
13. TASK-021 (habilitada por: TASK-006, TASK-007 y TASK-008) y TASK-022 (habilitada por: TASK-005, TASK-012 y TASK-013) — en paralelo
14. TASK-023 (habilitada por: TASK-017, TASK-018, TASK-019, TASK-020, TASK-021 y TASK-022 entregadas)

## Riesgos y dudas técnicas

- **Ampliación de rutas del módulo `api` (pendiente antes de implementar):** `config/buscador.yaml` y `data/` quedan fuera de las rutas actuales de `api` en `.sdd/team.md`. `config/`, `tests/` y `docs/contracts/openapi/` ya constan tras `api-pdf-parser`; falta añadir `data/` (para `seen_codes.json` y `failed_htmls/`). Hay que ampliar el registro del módulo `api` antes de TASK-004/TASK-009; sin ello, el desarrollador/documentador quedan bloqueados en esas rutas.
- **Mecanismo de planificación:** se asume scheduler con `threading` de la stdlib (reloj inyectable), sin dependencia externa, alineado con KISS/YAGNI. Si se prefiriera una librería (p. ej. APScheduler), declararla en TASK-001 y ajustar TASK-013/TASK-016.
- **Estructura del subpaquete:** `source/api/buscador/` es subpaquete nuevo (no módulo independiente); convive con los módulos planos de `source/api/` (`main.py`, `config.py`, `models.py`, etc.). Los endpoints del buscador se proponen en `source/api/buscador/routes.py` montados desde `main.py`; el coordinador y el estado compartido se exponen como instancia a nivel de módulo en `coordinator.py` (o vía `app.state` en el lifespan), consumida por `routes.py` y `scheduler.py`.
- **Prefijo de rutas:** se adopta `/buscador/run` y `/buscador/status` por defecto. Si se cambia el prefijo, el ajuste queda limitado a las rutas, el contrato (TASK-018) y la integración (TASK-017).
- **TASK-020 y `config/comunidades.yaml`:** se decide no tocar `config/comunidades.yaml` (sigue como mapa exclusivo de PDFs) y documentar las URLs del buscador en `config/buscador.yaml`; la tarea queda en documentación. Alternativa admitida por el diseño: unificar las URLs en `config/comunidades.yaml`.
- **Fixtures por copia vs referencia:** se propone copiar las 4 muestras a `tests/fixtures/buscador/` (tests autocontenidos); la referencia a `docs/contracts/html/empleacantabria/` es alternativa válida. Confirmable al implementar TASK-006.
- **Deducción del total:** el total 93 se deduce del texto de `small.search-results` (única fuente); una variante sin ese marcador se trata como error global de estructura (TASK-007 y variante de TASK-021).

## Validación

- Suite del módulo: pendiente
- Integración: pendiente
- Validación manual: pendiente
