# Tareas: api-pdf-parser

Estado: aprobado
Revisión: 1
Basado en: requirements@2, design@1
Verificación: correcta

## Resumen

El trabajo se divide en quince tareas que siguen la cadena de dependencias del diseño: primero la estructura del paquete y las entidades de dominio, después los tres bloques funcionales independientes (carga de configuración, parser de PDF, downloader), a continuación el ensamblado de la respuesta y la API, y por último la verificación de integración, los dos contratos afectados y los artefactos de entrega (`Modelfile` y `docker-compose.yaml`). Cada tarea de implementación incluye sus propias pruebas; solo la verificación de extremo a extremo del endpoint se separa como tarea de integración.

## Orden de implementación

1. TASK-001 Estructura del paquete y dependencias.
2. TASK-002 Modelos de dominio.
3. En paralelo: TASK-003 Configuración, TASK-004 Extracción de texto, TASK-008 Downloader.
4. TASK-005 Segmentación → TASK-006 Campos y TASK-007 Casos sin ofertas.
5. TASK-009 Ensamblado de respuesta (depende de TASK-002, TASK-006, TASK-007, TASK-008).
6. TASK-010 Endpoint y aplicación FastAPI.
7. TASK-011 Verificación de integración del endpoint.
8. TASK-012 Contrato OpenAPI y TASK-013 Contrato de configuración (implementation-first).
9. TASK-014 Modelfile → TASK-015 docker-compose.

## Tareas

### [x] TASK-001 Estructura del paquete y declaración de dependencias

- **Cubre:** DEC-001, DEC-003, DEC-006
- **Componente:** api-service | source/api/**
- **Depende de:** -
- **Alcance:** Crear el paquete del módulo de la API con su `__init__.py` y el fichero `pyproject.toml` con las dependencias que exige el diseño (FastAPI, httpx, pdfplumber, PyYAML y el runner de pruebas), de modo que la aplicación y los tests sean importables y ejecutables.
- **Hecho cuando:** el paquete se importa sin errores, las dependencias declaradas cubren las que usa el diseño y el runner de pruebas recorre `tests/` sin fallos de colección.
- **Pruebas automáticas:**
  - La suite arranca sin errores de importación de `src/api_pdf_parser` ni de ninguna dependencia declarada.
  - Una comprobación confirma que `fastapi`, `httpx`, `pdfplumber` y el lector de YAML están disponibles en el entorno de pruebas.
- **Prueba manual:**
  1. Instalar el proyecto en un entorno virtual limpio y ejecutar la suite de pruebas: termina sin fallos por dependencias ausentes.

### [x] TASK-002 Modelos de dominio sin persistencia

- **Cubre:** REQ-004, REQ-005
- **Componente:** api-service | source/api/models.py
- **Depende de:** TASK-001
- **Alcance:** Definir las entidades lógicas `ComunidadConfigurada`, `SectorProfesional`, `Oferta` y `ResultadoPorComunidad`, con los campos que exige REQ-004 y REQ-005, sin ninguna dependencia de base de datos ni de serialización a disco.
- **Hecho cuando:** existen las cuatro entidades con los campos denominación, municipio, código de oferta, fecha de publicación, oficina, descripción, sector profesional y comunidad, y un campo ausente del documento puede representarse como vacío sin inventar valor.
- **Pruebas automáticas:**
  - Se instancia una `Oferta` con todos los campos y se comprueba que conserva los valores originales.
  - Se instancia una `Oferta` sin oficina y sin municipio y se comprueba que esos campos quedan vacíos y que no aparece ningún campo `empresa` en la entidad.
  - `ResultadoPorComunidad` puede construirse con estado `ok` y con estado `error` más mensaje.
- **Prueba manual:**
  1. Revisar las entidades y comprobar que cubren exactamente el modelo de datos lógico del diseño, sin campos de persistencia.

### [x] TASK-003 Mapa interno de comunidades y su carga

- **Cubre:** REQ-001, REQ-005, DEC-003
- **Componente:** config-map | config/comunidades.yaml + source/api/config.py
- **Depende de:** TASK-001, TASK-002
- **Alcance:** Entregar el fichero de configuración `config/comunidades.yaml` con el caso inicial de Cantabria apuntando a la URL de su PDF de difusión, e implementar la lectura de ese fichero que devuelve la lista de comunidades con su identificador y su URL.
- **Hecho cuando:** la carga del fichero devuelve todas las comunidades configuradas con su identificador y URL, y una comunidad nueva añadida al fichero aparece en la lista sin ningún cambio de código.
- **Pruebas automáticas:**
  - El fichero `config/comunidades.yaml` se carga y devuelve al menos una comunidad con identificador y URL de PDF.
  - Un fichero de configuración con una comunidad adicional devuelve esa comunidad en la lista cargada.
  - Un fichero de configuración ausente o malformado produce un error controlado que identifica la configuración como origen, en lugar de una excepción no controlada.
- **Prueba manual:**
  1. Abrir `config/comunidades.yaml` y comprobar que cada comunidad tiene identificador y URL del PDF de difusión.
  2. Añadir una comunidad de prueba y volver a cargar: aparece en la lista sin tocar código.

### [x] TASK-004 Extracción de texto del PDF y limpieza de pies de página

- **Cubre:** REQ-003, DEC-001, ALT-004
- **Componente:** pdf-parser | source/api/parser.py
- **Depende de:** TASK-001
- **Alcance:** Implementar la extracción del texto plano del PDF con `pdfplumber` sobre todas sus páginas, eliminando las líneas de pie `Ofertas en difusión a fecha ... Página N de M` y conservando el orden de las líneas entre páginas; incluir el PDF de prueba mínimo `tests/fixtures/sample.pdf`.
- **Hecho cuando:** el texto extraído de un PDF con varias páginas llega completo y en orden, sin ninguna línea de pie de página, y un PDF ilegible produce un error controlado en lugar de una excepción sin capturar.
- **Pruebas automáticas:**
  - Extraer el texto de `tests/fixtures/sample.pdf` devuelve texto no vacío.
  - El texto extraído no contiene ninguna coincidencia de `Ofertas en difusión a fecha`.
  - Una oferta partida entre dos páginas aparece con sus líneas en el orden original, sin huecos ni duplicados.
  - Unos bytes que no son un PDF válido producen un error controlado y no una excepción no capturada.
- **Prueba manual:**
  1. Abrir `tests/fixtures/sample.pdf` y el texto extraído y comprobar que corresponden línea a línea salvo los pies de página.
  2. Buscar en el texto extraído la cadena `Ofertas en difusión` y confirmar que no aparece.

### [x] TASK-005 Segmentación del texto en sectores y ofertas

- **Cubre:** REQ-003, REQ-004, DEC-002
- **Componente:** pdf-parser | source/api/parser.py
- **Depende de:** TASK-004
- **Alcance:** Implementar la segmentación del texto ya limpiado en sectores profesionales y ofertas: cada oferta empieza en la línea `Oferta: <código>` precedida del título y del municipio, termina justo antes de la siguiente oferta o de un nuevo sector, y hereda el sector `Sector Profesional:` más cercano por encima.
- **Hecho cuando:** el texto de la muestra real se segmenta en un conjunto de ofertas cuyo número coincide con el de líneas `Oferta:` del fichero, y cada oferta queda asignada al sector profesional que la precede.
- **Pruebas automáticas:**
  - El número de ofertas segmentadas a partir de `docs/contracts/pdf/ofertas_cantabria.txt` coincide con el número de líneas que contienen `Oferta:` en ese fichero.
  - Cada oferta segmentada tiene un sector profesional no vacío igual al del encabezado `Sector Profesional:` que la precede.
  - Una oferta situada antes de cualquier encabezado de sector no hereda ningún sector de otra oferta.
  - El texto posterior a la última oferta del fichero, hasta el pie de página, queda incorporado a esa última oferta.
- **Prueba manual:**
  1. Recorrer la lista de ofertas segmentadas y comprobar contra la muestra real que ninguna oferta se parte en dos ni se fusiona con otra.

### [x] TASK-006 Extracción de los campos de cada oferta

- **Cubre:** REQ-004, ALT-003, ALT-004
- **Componente:** pdf-parser | source/api/parser.py
- **Depende de:** TASK-002, TASK-005
- **Alcance:** Implementar la extracción de los campos de cada oferta segmentada: denominación del puesto (multilínea), municipio, código de oferta, fecha de publicación, oficina de empleo y descripción textual completa, tomando como referencia el orden observado en la muestra real (título, municipio, `Oferta:`, fecha, `Oficina:`, descripción).
- **Hecho cuando:** cada oferta devuelta lleva los campos presentes en el documento y los ausentes quedan vacíos sin inventar valores, y ninguna oferta incluye un campo `empresa`.
- **Pruebas automáticas:**
  - De una oferta de la muestra, el código conserva el formato `062026003484`, la fecha conserva el formato `dd/mm/aaaa` y la oficina es el valor que sigue a `Oficina:`.
  - El municipio se extrae sin la marca de provincia que aparece en el documento (por ejemplo, sin el paréntesis con `CANTABRIA`).
  - La denominación de una oferta de título multilínea incluye todas sus líneas de título y no incorpora la línea del municipio.
  - La descripción contiene el texto corrido completo hasta la siguiente oferta y no contiene fragmentos de pie de página.
  - Una oferta a la que le falta la línea de oficina se devuelve con ese campo vacío y sin generar error.
  - Una oferta cuyo título y descripción aparecen en la misma línea se procesa sin lanzar error.
  - Ninguna oferta producida incluye un campo `empresa` ni un valor inventado en los campos ausentes.
- **Prueba manual:**
  1. Comparar tres ofertas de la muestra (una con título multilínea, una con descripción larga y una cortada por salto de página) con los campos extraídos y confirmar que coinciden.

### [x] TASK-007 PDF sin ofertas o no parseable

- **Cubre:** REQ-008, ALT-002
- **Componente:** pdf-parser | source/api/parser.py
- **Depende de:** TASK-004, TASK-005
- **Alcance:** Implementar el caso en que el PDF descargado no contiene texto, no tiene sectores reconocidos o no incluye ninguna línea `Oferta:`: el parser devuelve una lista de ofertas vacía para esa comunidad, sin excepción no controlada.
- **Hecho cuando:** un PDF vacío, un PDF sin texto extraíble y un texto sin ninguna línea `Oferta:` devuelven todos una lista de ofertas vacía, y ninguno de ellos hace fallar el proceso.
- **Pruebas automáticas:**
  - Un texto sin ninguna línea `Oferta:` devuelve una lista vacía de ofertas.
  - Un texto con encabezados de sector pero sin ofertas devuelve una lista vacía de ofertas.
  - Un PDF sin texto extraíble devuelve una lista vacía de ofertas y no una excepción.
- **Prueba manual:**
  1. Procesar un PDF de texto vacío y comprobar que el resultado indica que no se encontraron ofertas, sin trazas de error.

### [x] TASK-008 Descarga del PDF de cada comunidad

- **Cubre:** REQ-002, REQ-007, ALT-001
- **Componente:** pdf-downloader | source/api/downloader.py
- **Depende de:** TASK-001
- **Alcance:** Implementar la descarga con `httpx` del PDF de una comunidad a partir de su URL, con timeout explícito y retorno de los bytes en caso de éxito o de un error controlado por comunidad en caso de fallo, sin bloquear el resto de comunidades.
- **Hecho cuando:** una descarga correcta devuelve los bytes del PDF y cualquier fallo (código de error HTTP, timeout agotado o error de conexión) devuelve un error controlado con su causa, sin propagar una excepción al flujo de la API.
- **Pruebas automáticas:**
  - Con un cliente HTTP de prueba que responde 200 con bytes de PDF, la descarga devuelve esos mismos bytes.
  - Con un cliente de prueba que responde con código de error HTTP, la descarga devuelve un error controlado que incluye ese código.
  - Con un cliente de prueba que agota el timeout, la descarga devuelve un error controlado que indica tiempo de espera agotado.
  - Con un cliente de prueba que falla la conexión, la descarga devuelve un error controlado.
  - La petición se ejecuta con un timeout explícito configurado y sin credenciales ni cabeceras de autenticación.
- **Prueba manual:**
  1. Invocar la descarga con la URL real de Cantabria y comprobar que devuelve bytes que empiezan por la cabecera de un PDF.

### [x] TASK-009 Ensamblado de la respuesta por comunidad

- **Cubre:** REQ-005, REQ-006, REQ-007, REQ-008, DEC-005
- **Componente:** response-assembler | source/api/assembler.py
- **Depende de:** TASK-002, TASK-006, TASK-007, TASK-008
- **Alcance:** Implementar el componente que agrupa ofertas y errores por comunidad en el cuerpo de la respuesta: metadatos del proceso en la raíz, un resultado por comunidad con su estado (`ok`/`error`), su lista de ofertas y, cuando corresponda, un mensaje de error descriptivo.
- **Hecho cuando:** la respuesta agregada contiene un resultado por cada comunidad procesada con su estado, las ofertas con su identificador de comunidad y, en caso de fallo, un mensaje descriptivo, y las comunidades sin ofertas aparecen con estado `ok` y lista vacía.
- **Pruebas automáticas:**
  - Con dos comunidades con ofertas, la respuesta contiene un resultado por comunidad y cada oferta incluye el identificador de su comunidad de origen.
  - Una comunidad con error de descarga aparece con estado `error` y un mensaje no vacío, y sin lista de ofertas.
  - Una comunidad cuyo PDF no tiene ofertas aparece con estado `ok` y lista de ofertas vacía.
  - La raíz de la respuesta incluye los metadatos del proceso: comunidades procesadas, total de ofertas y marca de tiempo.
  - El total de ofertas de los metadatos coincide con la suma de ofertas de todos los resultados por comunidad.
- **Prueba manual:**
  1. Revisar un ejemplo de respuesta agregada con una comunidad correcta y otra con error y comprobar que se distingue el origen de cada dato.

### [x] TASK-010 Endpoint de parseo y aplicación FastAPI

- **Cubre:** REQ-001, REQ-002, REQ-006, DEC-004
- **Componente:** api-service | source/api/main.py
- **Depende de:** TASK-003, TASK-009
- **Alcance:** Implementar la aplicación FastAPI y el endpoint único de parseo, que lee el mapa de comunidades, descarga cada PDF, lo parsea y devuelve el resultado agregado, sin persistencia en base de datos.
- **Hecho cuando:** la aplicación expone el endpoint de parseo sin cuerpo ni parámetros obligatorios, devuelve HTTP 200 con el listado de ofertas agregado por comunidad y no escribe ni abre ninguna base de datos.
- **Pruebas automáticas:**
  - La aplicación expone el endpoint de parseo con método GET y sin parámetros ni cuerpo en su esquema.
  - Una petición de parseo con las descargas simuladas devuelve HTTP 200 y un cuerpo con resultados por comunidad.
  - El paquete no importa ni referencia un motor de base de datos (SQLite, SQLAlchemy ni similar).
  - Tras atender una petición de parseo, no se ha creado ni modificado ningún fichero de base de datos en el árbol del proyecto.
  - Con la configuración ausente, la API responde con un código de error global (4xx/5xx) y no con un 200 vacío.
- **Prueba manual:**
  1. Levantar la aplicación y consultar la ruta de parseo: se obtiene una respuesta JSON con los resultados por comunidad.
  2. Revisar que la API no acepta ninguna URL ni subida de fichero y que no deja ficheros de persistencia tras ejecutarse.

### [x] TASK-011 Verificación de integración del endpoint

- **Cubre:** REQ-005, REQ-006, REQ-007, REQ-008, ALT-001, ALT-002, ALT-003
- **Componente:** api-service | source/api/
- **Depende de:** TASK-010
- **Alcance:** Verificar de extremo a extremo la comunicación entre `api-service` y `response-assembler` (con `pdf-downloader` y `pdf-parser` simulados) montando la aplicación con cliente de prueba y cubriendo el caso de varias comunidades con resultados distintos.
- **Hecho cuando:** una petición de parseo con tres comunidades simuladas (una con ofertas, una con fallo de descarga y una con PDF sin ofertas) devuelve HTTP 200 con tres resultados de comunidad que reflejan esos tres casos, sin excepciones no controladas.
- **Pruebas automáticas:**
  - La respuesta contiene un resultado por comunidad con estado `ok` y ofertas para la comunidad accesible.
  - La comunidad con URL inaccesible aparece con estado `error` y un mensaje descriptivo, y el resto de comunidades se procesa igualmente.
  - La comunidad cuyo PDF no tiene ofertas aparece con estado `ok` y lista de ofertas vacía.
  - Cada oferta de la respuesta incluye denominación, municipio, código de oferta, fecha, oficina, descripción, sector profesional y comunidad.
  - Ninguno de los fallos por comunidad cambia el código HTTP de la respuesta, que sigue siendo 200.
  - La petición no deja ningún fichero de base de datos creado en el árbol del proyecto.
- **Prueba manual:**
  1. Ejecutar la prueba de integración y revisar el informe: todos los escenarios de comunidad salen con el estado esperado.

### [x] TASK-012 Contrato: openapi - endpoint de parseo por comunidades

- **Cubre:** REQ-005, REQ-006, REQ-007, REQ-008, DEC-004, DEC-005
- **Componente:** api-service | por definir (analista técnico)
- **Depende de:** TASK-010, TASK-011
- **Alcance:** Crear el contrato OpenAPI `docs/contracts/openapi/api-pdf-parser.yaml` que formaliza el endpoint de parseo tal como quedó implementado: operación de parseo sin parámetros de entrada, respuesta 200 con la estructura agregada por comunidad y los códigos de error globales de la propia API.
- **Hecho cuando:** el contrato existe en `docs/contracts/openapi/api-pdf-parser.yaml`, describe la operación de parseo, el esquema de la respuesta agregada por comunidad con sus campos de oferta y los errores globales 4xx/5xx, y coincide con la implementación verificada en TASK-011.
- **Pruebas automáticas:**
  - El YAML del contrato se carga correctamente y contiene la operación de parseo con su respuesta 200 y los esquemas de comunidad, oferta y sector.
  - El contrato documenta los errores globales de la API y no asigna códigos HTTP de error a los fallos por comunidad, que aparecen en el cuerpo con estado por comunidad.
  - Los campos del esquema de oferta del contrato coinciden con los que devuelve la implementación en la prueba de integración.
- **Prueba manual:**
  1. Revisar el contrato y comprobar que aparecen las tres interfaces de la fila: el endpoint de parseo, la estructura de la respuesta agregada por comunidad y los códigos de error globales.
  2. Comparar el contrato con la respuesta JSON real obtenida en TASK-011 y confirmar que no hay campos divergentes.

### [x] TASK-013 Contrato: configuración - formato del mapa interno comunidad => URL de PDF

- **Cubre:** REQ-001, REQ-005, DEC-003
- **Componente:** config-map | por definir (analista técnico)
- **Depende de:** TASK-003
- **Alcance:** Formalizar el contrato de configuración del mapa interno: documentar el formato exacto del fichero `config/comunidades.yaml` (identificador de comunidad, URL del PDF de difusión y reglas de alta de una comunidad nueva) y dejarlo alineado con lo que la carga de TASK-003 interpreta.
- **Hecho cuando:** el formato del mapa queda documentado en el contrato de configuración, el fichero `config/comunidades.yaml` lo cumple sin ambigüedad y una comunidad añadida siguiendo el formato documentado se procesa sin cambios de código.
- **Pruebas automáticas:**
  - El fichero `config/comunidades.yaml` se carga con el formato documentado y devuelve al menos la comunidad de ejemplo con su URL.
  - Un fichero con una comunidad adicional se carga correctamente y devuelve esa comunidad.
  - Una entrada con un campo obligatorio ausente se rechaza con un error controlado que identifica la entrada y el campo.
- **Prueba manual:**
  1. Revisar que la fila de contrato (mapa interno comunidad => URL de PDF) queda descrita con el mismo formato que usa el fichero real.
  2. Dar de alta una comunidad nueva siguiendo solo el formato documentado y comprobar que el endpoint la procesa.

### [x] TASK-014 Modelfile de referencia para Ollama

- **Cubre:** REQ-009, DEC-006
- **Componente:** model-file | Modelfile
- **Depende de:** TASK-001
- **Alcance:** Crear en la raíz del repositorio el fichero `Modelfile` con la definición de un modelo para Ollama, como artefacto inerte de referencia para uso futuro, sin que la API lo referencie ni ejecute inferencia.
- **Hecho cuando:** existe `Modelfile` en la raíz del repositorio con la definición del modelo y el código de la API no contiene ninguna llamada a Ollama ni ejecución de inferencia.
- **Pruebas automáticas:**
  - El fichero `Modelfile` existe en la raíz del repositorio y no está vacío.
  - Una búsqueda en `src/api_pdf_parser` no encuentra referencias a Ollama, a su API HTTP ni a llamadas de inferencia.
  - La lista de dependencias del proyecto no incluye clientes de Ollama ni de inferencia.
- **Prueba manual:**
  1. Revisar el contenido del `Modelfile` y comprobar que define un modelo coherente con el uso futuro previsto en el proyecto.
  2. Revisar el código de la API y confirmar que no invoca Ollama ni ejecuta inferencia en ningún punto.

### [x] TASK-015 docker-compose.yaml para levantar la API

- **Cubre:** REQ-010, DEC-006, REQ-009
- **Componente:** docker-compose | docker-compose.yaml + Dockerfile
- **Depende de:** TASK-001, TASK-010, TASK-014
- **Alcance:** Crear el `docker-compose.yaml` y el `Dockerfile` necesario para construir y levantar únicamente el contenedor de la API sobre Python 3.12, con el puerto `8000` del host mapeado a `0.0.0.0:8000`, sin servicio de Ollama ni persistencia.
- **Hecho cuando:** `docker-compose up` levanta el contenedor de la API y responde en `http://localhost:8000`, el endpoint de parseo devuelve el resultado esperado y no se levanta ningún otro servicio.
- **Pruebas automáticas:**
  - El `docker-compose.yaml` se carga y define exactamente un servicio de API con base Python 3.12 y el mapeo del puerto 8000 del host.
  - El `docker-compose.yaml` no define ningún servicio de Ollama ni volumen de base de datos.
  - `docker compose config` valida el fichero sin errores.
- **Prueba manual:**
  1. Ejecutar `docker-compose up --build` y comprobar que el contenedor de la API queda en estado arriba.
  2. Consultar `http://localhost:8000` y el endpoint de parseo y verificar que responden con el resultado esperado.
  3. Confirmar que solo se levanta el contenedor de la API y que no hay ningún servicio de inferencia en ejecución.

## Cobertura

| Requisito | Tareas |
|---|---|
| REQ-001 | TASK-003, TASK-010, TASK-013 |
| REQ-002 | TASK-008, TASK-010 |
| REQ-003 | TASK-004, TASK-005 |
| REQ-004 | TASK-002, TASK-005, TASK-006 |
| REQ-005 | TASK-002, TASK-003, TASK-009, TASK-011, TASK-012, TASK-013 |
| REQ-006 | TASK-009, TASK-010, TASK-011, TASK-012 |
| REQ-007 | TASK-008, TASK-009, TASK-011, TASK-012 |
| REQ-008 | TASK-007, TASK-009, TASK-011, TASK-012 |
| REQ-009 | TASK-014, TASK-015 |
| REQ-010 | TASK-015 |

| Requisito no funcional | Tareas |
|---|---|
| Ninguno (requirements.md §Requisitos no funcionales) | - |

| Decisión | Tareas |
|---|---|
| DEC-001 | TASK-001, TASK-004 |
| DEC-002 | TASK-005 |
| DEC-003 | TASK-001, TASK-003, TASK-013 |
| DEC-004 | TASK-010, TASK-012 |
| DEC-005 | TASK-009, TASK-012 |
| DEC-006 | TASK-001, TASK-014, TASK-015 |

| Escenario alternativo | Tareas |
|---|---|
| ALT-001 | TASK-008, TASK-011 |
| ALT-002 | TASK-007, TASK-011 |
| ALT-003 | TASK-006, TASK-011 |
| ALT-004 | TASK-004, TASK-006 |

## Avisos

- `.sdd/architecture.md` sigue siendo la plantilla vacía: no tiene entradas de módulos ni de contratos. Todos los componentes del diseño (`api-service`, `config-map`, `pdf-downloader`, `pdf-parser`, `response-assembler`, `model-file`, `docker-compose`) son nuevos, así que en todas las tareas su ruta figura como `por definir (analista técnico)`. La capa técnica debe fijar esas rutas al implementar y registrarlas en el mapa.
- `design.md` deja sin fichero asignado el componente `response-assembler`: además de la ruta, el analista decidirá si es un módulo propio o si se integra en el de modelos o en el de la aplicación.
- `design.md` propone en "Estructura de ficheros del repositorio" y "Cambios sugeridos al mapa" estas ubicaciones, que la capa técnica podrá confirmar al implementar: módulo `api-pdf-parser | src/api_pdf_parser` (con `main.py`, `config.py`, `downloader.py`, `parser.py`, `models.py` y `routes/parse.py`), módulo `config-map | config/comunidades.yaml`, contrato `openapi | docs/contracts/openapi/api-pdf-parser.yaml`, y en la raíz `Modelfile` y `docker-compose.yaml`.
- La ruta real de la muestra de texto es `docs/contracts/pdf/ofertas_cantabria.txt`, no `docs/contracts/ofertas_cantabria.txt` como figura en `design.md`. Las tareas usan la ruta real del repositorio.
- `design.md` deja abierto el prefijo del endpoint (`GET /parse` o `GET /api/v1/parse`). Se adopta por defecto `GET /parse` por ser el caso base del propio diseño y por tratarse de una API local con una sola operación; si la capa técnica adopta el prefijo de versión, basta un cambio en la ruta, en el contrato OpenAPI (TASK-012) y en la prueba de integración (TASK-011).
- La estrategia de contratos aplicada es `implementation-first`, valor tomado de la opción `contract-strategy` de `.sdd/team.md`. Por eso TASK-012 depende de TASK-010 y TASK-011, y TASK-013 depende de TASK-003.
- La fila "Configuración" de "Contratos afectados" tiene como artefacto el propio `config/comunidades.yaml`, fuera de `docs/contracts/`; se sigue la ubicación que fija el diseño. Si la capa técnica prefiere la convención `docs/contracts/<protocolo>/`, debe indicarlo antes de implementar TASK-013.
- `docs/contracts/pdf/ofertas_cantabria.txt` contiene anomalías reales que el parser debe tolerar: una línea donde título y descripción aparecen fundidos, una oficina con un sufijo inesperado (`TORRELAVEGAs`), títulos de varias líneas y descripciones partidas por salto de página. Están contempladas en las pruebas de TASK-006.
- `design.md` incluye `README.md` en la estructura de ficheros del repositorio, pero ningún requisito ni decisión pide contenido concreto para él, por lo que no se ha generado tarea. Si la capa técnica lo quiere en esta feature, debe encargarlo aparte.
- No existe `.sdd/task-types.md`, así que no hay tipos de tarea propios del proyecto que generar.
