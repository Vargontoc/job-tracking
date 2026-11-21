# Sprint 01: api-pdf-parser - api

Estado: aprobado

## Alcance

- Tareas: TASK-001, TASK-002, TASK-003, TASK-004, TASK-005, TASK-006, TASK-007, TASK-008, TASK-009, TASK-010, TASK-011, TASK-012, TASK-013, TASK-014, TASK-015 (de `specs/api-pdf-parser/tasks.md`)
- Dependencias internas: TASK-002←TASK-001; TASK-003←TASK-001,TASK-002; TASK-004←TASK-001; TASK-005←TASK-004; TASK-006←TASK-002,TASK-005; TASK-007←TASK-004,TASK-005; TASK-008←TASK-001; TASK-009←TASK-002,TASK-006,TASK-007,TASK-008; TASK-010←TASK-003,TASK-009; TASK-011←TASK-010; TASK-012←TASK-010,TASK-011; TASK-013←TASK-003; TASK-014←TASK-001; TASK-015←TASK-001,TASK-010,TASK-014.
- Dependencias externas: Ninguna.

## Origen SDD

- Requirements: 2
- Design: 1
- Tasks: 1

## Enfoque técnico

API FastAPI síncrona con un único endpoint `GET /parse` (sin parámetros ni cuerpo) que orquesta el flujo: cargar el config-map (`config/comunidades.yaml`) → descargar cada PDF con `httpx` (timeout explícito, errores por comunidad) → extraer texto con `pdfplumber` y segmentar por heurísticas de línea → ensamblar la respuesta agregada por comunidad. Sin persistencia ni inferencia.

- El código va en `source/api/` (ajustado desde `src/api_pdf_parser` del diseño, porque `team.md` registra `source/api/**`).
- Entidades de dominio como dataclasses puras (`models.py`), sin DB ni serialización a disco.
- Módulos pequeños y de responsabilidad única: `config.py` (config-map), `downloader.py`, `parser.py` (extracción+segmentación+campos), `assembler.py` (response-assembler), `routes/parse.py` + `main.py` (api-service). KISS/YAGNI.
- Fallos por comunidad dentro del cuerpo (HTTP 200); solo errores globales de la API devuelven 4xx/5xx.
- Contratos implementation-first (TASK-012 tras TASK-010/011; TASK-013 tras TASK-003).

## Cambios por tarea

### TASK-001 Estructura del paquete y declaración de dependencias

- **Ficheros:** `source/api/__init__.py` (nuevo): paquete vacío del módulo; `pyproject.toml` (nuevo, raíz): dependencias fastapi, httpx, pdfplumber, PyYAML y runner pytest; `tests/unit/test_imports.py` (nuevo): smoke test de importación y dependencias. Componente `api-service` → `source/api/` (propuesta).
- **Enfoque:** paquete importable y dependencias alineadas con el diseño; `pytest` recorre `tests/` sin fallos de colección. Sin dependencias de DB ni de Ollama.
- **Pruebas automáticas:** `tests/unit/test_imports.py` — importar `source.api` no lanza error; comprobar que `fastapi`, `httpx`, `pdfplumber` y `yaml` están disponibles. Comando: `pytest tests/unit/test_imports.py`.
- **Prueba manual:** instalar en un venv limpio y ejecutar `pytest`: termina sin fallos por dependencias ausentes.

### TASK-002 Modelos de dominio sin persistencia

- **Ficheros:** `source/api/models.py` (nuevo): dataclasses `ComunidadConfigurada`, `SectorProfesional`, `Oferta`, `ResultadoPorComunidad`. Componente `api-service` → `source/api/models.py` (propuesta).
- **Enfoque:** entidades puras con los campos de REQ-004/REQ-005 (denominación, municipio, código de oferta, fecha de publicación, oficina, descripción, sector profesional, comunidad); campos ausentes representables como vacío sin inventar valor; sin campo `empresa` ni dependencias de DB/serialización.
- **Pruebas automáticas:** `tests/unit/test_models.py` — `Oferta` con todos los campos conserva valores; `Oferta` sin oficina ni municipio queda con esos campos vacíos y no expone campo `empresa`; `ResultadoPorComunidad` se construye con estado `ok` y con `error`+mensaje. Comando: `pytest tests/unit/test_models.py`.
- **Prueba manual:** revisar que las entidades cubren exactamente el modelo lógico del diseño, sin campos de persistencia.

### TASK-003 Mapa interno de comunidades y su carga

- **Ficheros:** `config/comunidades.yaml` (nuevo): mapa con la comunidad inicial Cantabria → URL de su PDF de difusión; `source/api/config.py` (nuevo): carga el fichero y devuelve lista de `ComunidadConfigurada` (id+URL). Componente `config-map` → `config/comunidades.yaml` + `source/api/config.py` (propuesta).
- **Enfoque:** lectura YAML (PyYAML) que devuelve las comunidades con identificador y URL; error controlado e identificable como de configuración ante fichero ausente/malformado; añadir una comunidad no requiere cambios de código.
- **Pruebas automáticas:** `tests/unit/test_config.py` — cargar el fichero devuelve ≥1 comunidad con id y URL; un fichero con una comunidad adicional devuelve esa comunidad; fichero ausente/malformado produce error controlado que identifica la configuración como origen. Comando: `pytest tests/unit/test_config.py`.
- **Prueba manual:** abrir `config/comunidades.yaml` y verificar id+URL; añadir una comunidad de prueba y recargar: aparece sin tocar código.

### TASK-004 Extracción de texto del PDF y limpieza de pies de página

- **Ficheros:** `source/api/parser.py` (nuevo): extracción de texto plano con `pdfplumber` sobre todas las páginas y limpieza de pies; `tests/fixtures/sample.pdf` (nuevo): PDF de prueba mínimo. Componente `pdf-parser` → `source/api/parser.py` (propuesta).
- **Enfoque:** iterar páginas con `pdfplumber`, eliminar líneas `Ofertas en difusión a fecha ... Página N de M` conservando el orden de las líneas; error controlado ante bytes que no son un PDF válido.
- **Pruebas automáticas:** `tests/unit/test_parser.py` — `sample.pdf` devuelve texto no vacío; el texto no contiene `Ofertas en difusión a fecha`; una oferta partida entre dos páginas conserva el orden sin huecos/duplicados; bytes no-PDF → error controlado. Comando: `pytest tests/unit/test_parser.py`.
- **Prueba manual:** comparar `tests/fixtures/sample.pdf` con el texto extraído línea a línea salvo los pies; confirmar que `Ofertas en difusión` no aparece.

### TASK-005 Segmentación del texto en sectores y ofertas

- **Ficheros:** `source/api/parser.py` (modificar): añadir segmentación en sectores y ofertas. Componente `pdf-parser` → `source/api/parser.py` (propuesta).
- **Enfoque:** cada oferta empieza en `Oferta: <código>` (precedida del título y el municipio) y termina justo antes de la siguiente oferta, sector o pie; hereda el `Sector Profesional:` más cercano por encima; el texto posterior a la última oferta, hasta el pie, se incorpora a ella.
- **Pruebas automáticas:** `tests/unit/test_segmentation.py` — el nº de ofertas sobre `docs/contracts/pdf/ofertas_cantabria.txt` coincide con el nº de líneas `Oferta:`; cada oferta tiene el sector del encabezado que la precede; una oferta antes de cualquier sector no hereda sector de otra; el texto final hasta el pie pertenece a la última oferta. Comando: `pytest tests/unit/test_segmentation.py`.
- **Prueba manual:** recorrer la lista segmentada y comprobar contra la muestra que ninguna oferta se parte ni se fusiona.

### TASK-006 Extracción de los campos de cada oferta

- **Ficheros:** `source/api/parser.py` (modificar): añadir extracción de campos por oferta segmentada. Componente `pdf-parser` → `source/api/parser.py` (propuesta).
- **Enfoque:** extraer denominación (título multilínea), municipio (sin la marca de provincia `( CANTABRIA )`), código (`Oferta:`), fecha (`dd/mm/aaaa`), oficina (`Oficina:`), descripción (texto corrido hasta la siguiente oferta). Orden de referencia: título → municipio → `Oferta:` → fecha → `Oficina:` → descripción. Campos ausentes quedan vacíos; nunca se inventa campo `empresa`.
- **Pruebas automáticas:** `tests/unit/test_parser.py` — código conserva `062026003484`; fecha `dd/mm/aaaa`; oficina es el valor tras `Oficina:`; municipio sin el paréntesis de provincia; título multilínea íntegro sin la línea de municipio; descripción completa sin fragmentos de pie; oferta sin `Oficina:` → campo vacío sin error; título y descripción en la misma línea → sin error; ninguna oferta lleva campo `empresa`. Comando: `pytest tests/unit/test_parser.py`.
- **Prueba manual:** comparar 3 ofertas de la muestra (título multilínea, descripción larga, cortada por salto de página) con los campos extraídos.

### TASK-007 PDF sin ofertas o no parseable

- **Ficheros:** `source/api/parser.py` (modificar): caso de PDF sin ofertas/sin texto/sin sectores. Componente `pdf-parser` → `source/api/parser.py` (propuesta).
- **Enfoque:** PDF vacío, sin texto extraíble o sin ninguna línea `Oferta:` (incluso con sectores) devuelven lista de ofertas vacía sin excepción no controlada.
- **Pruebas automáticas:** `tests/unit/test_parser.py` — texto sin `Oferta:` → lista vacía; texto con sectores pero sin ofertas → lista vacía; PDF sin texto extraíble → lista vacía, no excepción. Comando: `pytest tests/unit/test_parser.py`.
- **Prueba manual:** procesar un PDF de texto vacío y comprobar que el resultado indica ausencia de ofertas, sin trazas de error.

### TASK-008 Descarga del PDF de cada comunidad

- **Ficheros:** `source/api/downloader.py` (nuevo): descarga con `httpx`. Componente `pdf-downloader` → `source/api/downloader.py` (propuesta).
- **Enfoque:** GET con timeout explícito y sin credenciales ni cabeceras de autenticación; devuelve bytes del PDF en éxito o un error controlado con su causa (código HTTP, timeout, conexión) sin propagar excepción al flujo de la API.
- **Pruebas automáticas:** `tests/unit/test_downloader.py` — cliente HTTP de prueba 200 → devuelve esos bytes; error HTTP → error con el código; timeout → error de tiempo de espera agotado; fallo de conexión → error controlado; la petición usa timeout explícito y sin credenciales. Comando: `pytest tests/unit/test_downloader.py`.
- **Prueba manual:** invocar la descarga con la URL real de Cantabria y comprobar que los bytes empiezan por la cabecera de un PDF (`%PDF`).

### TASK-009 Ensamblado de la respuesta por comunidad

- **Ficheros:** `source/api/assembler.py` (nuevo): agrupa ofertas y errores por comunidad. Componente `response-assembler` → `source/api/assembler.py` (propuesta; el diseño lo dejaba sin fichero).
- **Enfoque:** metadatos del proceso en la raíz (comunidades procesadas, total de ofertas, marca de tiempo); por comunidad: estado `ok`/`error`, lista de ofertas (con identificador de comunidad) y mensaje de error opcional; comunidad sin ofertas → `ok` con lista vacía.
- **Pruebas automáticas:** `tests/unit/test_assembler.py` — 2 comunidades con ofertas → un resultado por comunidad y cada oferta con id de comunidad; comunidad con error de descarga → `error` + mensaje no vacío, sin lista; comunidad sin ofertas → `ok` lista vacía; raíz con metadatos (procesadas, total, timestamp); total == suma de ofertas. Comando: `pytest tests/unit/test_assembler.py`.
- **Prueba manual:** revisar una respuesta agregada con una comunidad correcta y otra con error y comprobar que se distingue el origen de cada dato.

### TASK-010 Endpoint de parseo y aplicación FastAPI

- **Ficheros:** `source/api/routes/__init__.py` (nuevo); `source/api/routes/parse.py` (nuevo): ruta `GET /parse`; `source/api/main.py` (nuevo): aplicación FastAPI que monta la ruta. Componente `api-service` → `source/api/main.py` + `source/api/routes/parse.py` (propuesta).
- **Enfoque:** endpoint `GET /parse` sin cuerpo ni parámetros; lee el config-map, descarga cada PDF, lo parsea y ensambla el resultado; sin persistencia (no importa ni abre motor de DB); configuración ausente → error global 4xx/5xx.
- **Pruebas automáticas:** `tests/integration/test_api.py` — el esquema expone `GET /parse` sin parámetros ni cuerpo; petición con descargas simuladas → 200 con resultados por comunidad; el paquete no importa motores de DB (SQLite/SQLAlchemy); no se crea/modifica fichero de DB tras una petición; configuración ausente → código de error global. Comando: `pytest tests/integration/test_api.py`.
- **Prueba manual:** levantar la app y consultar `/parse` → JSON con resultados por comunidad; confirmar que no acepta URL ni subida de fichero y no deja ficheros de persistencia.

### TASK-011 Verificación de integración del endpoint

- **Ficheros:** `tests/integration/test_api.py` (modificar): escenario end-to-end con `pdf-downloader` y `pdf-parser` simulados. Componente `api-service` → `source/api/` (propuesta).
- **Enfoque:** `TestClient` con descarga y parseo simulados; tres comunidades: una con ofertas, una con fallo de descarga y una con PDF sin ofertas; respuesta HTTP 200 con tres resultados que reflejan esos casos.
- **Pruebas automáticas:** `tests/integration/test_api.py` — resultado por comunidad; comunidad con URL inaccesible → `error` + mensaje y el resto se procesa; comunidad sin ofertas → `ok` lista vacía; cada oferta con denominación/municipio/código/fecha/oficina/descripción/sector/comunidad; los fallos por comunidad no cambian el HTTP (sigue 200); no se crea fichero de DB. Comando: `pytest tests/integration/test_api.py`.
- **Prueba manual:** ejecutar la prueba de integración y revisar que los tres escenarios salen con el estado esperado.

### TASK-012 Contrato: openapi - endpoint de parseo por comunidades

- **Ficheros:** `docs/contracts/openapi/api-pdf-parser.yaml` (nuevo): contrato OpenAPI del endpoint verificado. Componente `api-service` → `docs/contracts/openapi/api-pdf-parser.yaml` (propuesta; tarea del documentador).
- **Enfoque:** documentar `GET /parse` sin parámetros de entrada, la respuesta 200 con la estructura agregada por comunidad (esquemas de comunidad, oferta y sector) y los errores globales 4xx/5xx; implementation-first, coincide con lo verificado en TASK-011; los fallos por comunidad no reciben código HTTP de error.
- **Pruebas automáticas:** `tests/contract/test_openapi_contract.py` (nuevo) — el YAML carga y contiene la operación de parseo con su 200 y los esquemas; documenta errores globales sin asignar códigos de error a fallos por comunidad; los campos del esquema de oferta coinciden con la respuesta de la integración. Comando: `pytest tests/contract/test_openapi_contract.py`.
- **Prueba manual:** revisar las tres interfaces (endpoint, respuesta agregada, errores globales) y comparar el contrato con el JSON real de TASK-011.

### TASK-013 Contrato: configuración - formato del mapa interno comunidad => URL de PDF

- **Ficheros:** `config/comunidades.yaml` (modificar): formalizar y documentar el formato (identificador, URL del PDF, reglas de alta de una comunidad) alineado con la carga de TASK-003. Componente `config-map` → `config/comunidades.yaml` (propuesta; tarea del documentador; la fila "Configuración" apunta al propio fichero, no a `docs/contracts/`).
- **Enfoque:** documentar el formato exacto del mapa (identificador de comunidad, URL del PDF de difusión, reglas para añadir una comunidad); el fichero lo cumple sin ambigüedad; una entrada con campo obligatorio ausente se rechaza con error controlado que identifica entrada y campo.
- **Pruebas automáticas:** `tests/contract/test_config_contract.py` (nuevo) — el fichero carga con el formato documentado y devuelve ≥1 comunidad con URL; una comunidad adicional carga y se devuelve; una entrada sin campo obligatorio se rechaza identificando entrada y campo. Comando: `pytest tests/contract/test_config_contract.py`.
- **Prueba manual:** revisar que la fila de contrato queda descrita con el mismo formato del fichero real; dar de alta una comunidad siguiendo solo el formato documentado y comprobar que el endpoint la procesa.

### TASK-014 Modelfile de referencia para Ollama

- **Ficheros:** `Modelfile` (nuevo, raíz): definición de modelo para Ollama como artefacto inerte. Componente `model-file` → `Modelfile` (propuesta).
- **Enfoque:** definición de referencia para uso futuro; la API no lo referencia ni ejecuta inferencia; sin llamadas a Ollama ni dependencias de inferencia en el código ni en `pyproject.toml`.
- **Pruebas automáticas:** `tests/contract/test_modelfile.py` (nuevo) — `Modelfile` existe y no está vacío; no hay referencias a Ollama/inferencia en `source/api/`; `pyproject.toml` no incluye clientes de Ollama. Comando: `pytest tests/contract/test_modelfile.py`.
- **Prueba manual:** revisar el contenido del `Modelfile` y confirmar que la API no invoca Ollama ni ejecuta inferencia en ningún punto.

### TASK-015 docker-compose.yaml para levantar la API

- **Ficheros:** `docker-compose.yaml` (nuevo, raíz): servicio único de la API sobre Python 3.12 con `0.0.0.0:8000` ↔ puerto `8000` del host; `Dockerfile` (nuevo, raíz): imagen de la API. Componente `docker-compose` → `docker-compose.yaml` + `Dockerfile` (propuesta).
- **Enfoque:** contenedor único de la API, sin servicio Ollama ni volumen de DB; `docker-compose up` levanta y responde en `http://localhost:8000`; `docker compose config` valida.
- **Pruebas automáticas:** `tests/contract/test_docker_compose.py` (nuevo) — el yaml define exactamente un servicio de API sobre Python 3.12 con el mapeo del puerto 8000; sin servicio Ollama ni volumen de DB; `docker compose config` valida sin errores. Comando: `pytest tests/contract/test_docker_compose.py`.
- **Prueba manual:** `docker-compose up --build` y comprobar que el contenedor queda arriba; consultar `http://localhost:8000` y el endpoint de parseo; confirmar que solo se levanta el contenedor de la API.

## Orden de implementación

1. TASK-001 (habilitada por: sin dependencias)
2. TASK-002 (habilitada por: TASK-001 entregada — paquete importable y dependencias declaradas)
3. TASK-003 (habilitada por: TASK-002 entregada — entidades de dominio definidas), TASK-004 (habilitada por: TASK-001) y TASK-008 (habilitada por: TASK-001) — en paralelo
4. TASK-005 (habilitada por: TASK-004 entregada — extracción y limpieza de texto)
5. TASK-006 (habilitada por: TASK-005 entregada) y TASK-007 (habilitada por: TASK-005 entregada) — en paralelo
6. TASK-009 (habilitada por: TASK-006, TASK-007 y TASK-008 entregadas)
7. TASK-010 (habilitada por: TASK-003 y TASK-009 entregadas)
8. TASK-011 (habilitada por: TASK-010 entregada — endpoint expuesto)
9. TASK-012 (habilitada por: TASK-010 y TASK-011 entregadas) y TASK-013 (habilitada por: TASK-003 entregada) — en paralelo (implementation-first)
10. TASK-014 (habilitada por: TASK-001 entregada)
11. TASK-015 (habilitada por: TASK-010 y TASK-014 entregadas)

## Riesgos y dudas técnicas

- **Rutas fuera de `source/api/**`:** `config/comunidades.yaml`, `pyproject.toml`, `tests/`, `docs/contracts/openapi/api-pdf-parser.yaml`, `Modelfile`, `docker-compose.yaml` y `Dockerfile` quedan fuera de la ruta `source/api/**` registrada en `.sdd/team.md` para el módulo `api`. Antes de implementar hay que ampliar la lista de rutas del módulo (o acordar otro responsable) para que el desarrollador y el documentador puedan escribirlas sin bloqueo.
- **Ubicación del response-assembler:** el diseño lo dejaba sin fichero; se propone `source/api/assembler.py` como módulo propio (KISS y testeable). Confirmable al implementar.
- **Prefijo del endpoint:** se adopta `GET /parse` por defecto (API local de una sola operación). Si se adoptara `/api/v1/parse`, habría que ajustar la ruta, el contrato (TASK-012) y la integración (TASK-011).
- **Contrato de configuración fuera de `docs/contracts/`:** la fila "Configuración" apunta al propio `config/comunidades.yaml` (ubicación del diseño). Si se prefiere la convención `docs/contracts/<protocolo>/`, decidir antes de TASK-013.
- **Heurísticas frágiles ante cambios del formato del PDF:** mitigar con la muestra real `docs/contracts/pdf/ofertas_cantabria.txt` y sus anomalías (título y descripción fundidos, oficina `TORRELAVEGAs`, títulos multilínea, descripciones cortadas por salto de página).

## Validación

- Suite del módulo: pendiente
- Integración: pendiente
- Validación manual: pendiente
