# Sprint 03: api-persistencia - api

Estado: aprobado

## Alcance

- Tareas: TASK-001, TASK-002, TASK-003, TASK-004, TASK-005, TASK-006, TASK-007, TASK-008, TASK-009, TASK-010, TASK-011, TASK-012, TASK-013, TASK-014, TASK-015, TASK-016, TASK-017 (de `specs/api-persistencia/tasks.md`)
- Dependencias internas: TASK-002←TASK-001; TASK-003←TASK-002; TASK-004←TASK-003; TASK-005←TASK-004; TASK-006←TASK-005; TASK-007←TASK-005; TASK-008←TASK-006; TASK-009←TASK-002; TASK-010←TASK-007,TASK-009; TASK-011←TASK-007; TASK-012←TASK-006; TASK-013←TASK-004,TASK-008,TASK-010,TASK-011,TASK-012; TASK-014←TASK-013; TASK-015←TASK-012,TASK-014; TASK-016←TASK-002,TASK-013; TASK-017←TASK-014,TASK-015,TASK-016.
- Dependencias externas: `api-buscador` (Sprint 02 aprobado) — condición de entrega: `GET /buscador/status` implementado y `data/seen_codes.json` presente en producción, sin modificar `source/api/buscador/**` ni `config/buscador.yaml`.

## Origen SDD

- Requirements: 5
- Design: 2
- Tasks: 1

## Enfoque técnico

Se añade a la FastAPI síncrona existente un subpaquete `source/api/persistencia/` con la capa de persistencia SQLite única (WAL): conexión con `busy_timeout`, migraciones secuenciales transaccionales, repositorio de ofertas por clave natural `(comunidad, codigo)`, importador idempotente de `data/seen_codes.json`, cliente HTTP de `GET /buscador/status` y dos tareas periódicas (ingesta y purga). Sin servidor de BD, sin base vectorial ni extensión vectorial.

- Sigue las convenciones de `api-buscador`: dataclasses puras con valores por defecto, excepciones propias (`ErrorConfiguracion`), funciones/clases en español, tests en `tests/unit|integration|contract`, y planificador "en proceso" con `threading` de la stdlib + reloj inyectable (`RelojProtocol`/`RelojReal`), como `source/api/buscador/scheduler.py`.
- Mecanismo de planificación: se mantiene `threading` (hilo daemon + `threading.Event` de parada + reloj inyectable). FastAPI es síncrona (endpoints `def`, hilos del threadpool), así que `asyncio` no aporta beneficio y añadiría complejidad; además evita una dependencia externa de scheduling (KISS/YAGNI).
- `ingesta_log`: un único registro con `id=1` actualizado por UPSERT (sin restricción UNIQUE adicional). Decisión del analista documentada en TASK-004/TASK-010.
- Prefijo de rutas por defecto `/persistencia`; "oferta no encontrada" → `404` con `HTTPException`, coherente con el estilo existente. `sector`/`nivel`/`contrato` siempre vacíos (DEC-009); `interesada` INTEGER `0`/`1` con valor por defecto `0`, reservado para `api-candidaturas`.
- Dataclasses colocalizadas con su consumidor (`config.py`, `repository.py`, `client.py`, `importer.py`): el diseño no pide un módulo de modelos propio, así que no se crea `models.py` (KISS).
- No se modifica `source/api/buscador/**` ni `config/buscador.yaml`; la convivencia se resuelve desde el `lifespan` y `app_state` de `source/api/main.py`.

## Cambios por tarea

### TASK-001 Estructura del paquete de persistencia y dependencias

- **Ficheros:** `source/api/persistencia/__init__.py` (nuevo): subpaquete importable; `pyproject.toml` (modificar): añadir `numpy` a `[project] dependencies` (`httpx` ya está declarada). Componente `api-persistencia` → `source/api/persistencia` (propuesta).
- **Enfoque:** subpaquete vacío que se importa sin errores; `numpy` es la única dependencia nueva (para serializar/reconstruir el embedding `float32`); `httpx` ya consta en el proyecto. El planificador en proceso usa `threading` de la stdlib, así que no se declara dependencia para él. El paquete no importa ni referencia un motor de base de datos servidor (SQLAlchemy, PostgreSQL, MySQL) ni una extensión vectorial de SQLite (NFR-001, NFR-005).
- **Pruebas automáticas:** `tests/unit/test_persistencia_imports.py` (nuevo) — importar `source.api.persistencia` no lanza error; `numpy` y `httpx` están disponibles; el paquete no importa motores de BD servidor ni extensiones vectoriales. Comando: `pytest tests/unit/test_persistencia_imports.py`.
- **Prueba manual:** instalar en un venv limpio (`pip install -e .`) y ejecutar `pytest`: termina sin fallos por dependencias ausentes ni por colección.

### TASK-002 Fichero de configuración de la persistencia

- **Ficheros:** `config/persistencia.yaml` (nuevo): estructura anidada del diseño (`base_de_datos.ruta`, `buscador.url_base`, `ingesta.cadencia_segundos`, `purga.dias_retencion`, `purga.frecuencia_segundos`); `source/api/persistencia/config.py` (nuevo): dataclass `ConfigPersistencia` + excepción `ErrorConfiguracion` + `cargar_configuracion(ruta=Path("config/persistencia.yaml"))`. Componente `config-persistencia` → `config/persistencia.yaml` (propuesta).
- **Enfoque:** carga con PyYAML siguiendo el patrón de `source/api/buscador/config.py`: fichero ausente → `ConfigPersistencia` con valores por defecto (coherencia con `api-buscador`); YAML malformado, raíz que no es un mapa o campo con tipo incorrecto → `ErrorConfiguracion` controlado que identifica la configuración o el campo como origen. La ruta de la BD es relativa a la raíz del proyecto. La configuración no contiene rutas de servidor de BD ni credenciales (NFR-001). Ver Riesgos: TASK-002 tiene tensión entre "sin fichero → defaults" y "fichero ausente → error controlado".
- **Pruebas automáticas:** `tests/unit/test_persistencia_config.py` (nuevo) — la carga completa devuelve los 5 campos; sin fichero → ruta `data/job_emcan.db`, URL `http://localhost:8000`, cadencia 300, retención 7, frecuencia 86400; YAML malformado → `ErrorConfiguracion`; tipo incorrecto → error que identifica el campo; no hay claves de servidor ni credenciales. Comando: `pytest tests/unit/test_persistencia_config.py`.
- **Prueba manual:** abrir `config/persistencia.yaml` y comprobar los 5 campos; cambiar cadencia de ingesta y retención, recargar la configuración y comprobar que se aplican los nuevos valores.

### TASK-003 Conexión única a SQLite con WAL y pragmas

- **Ficheros:** `source/api/persistencia/connection.py` (nuevo): `abrir_conexion(ruta) -> sqlite3.Connection` y contexto `transaccion(conexion)`. Componente `db-connection` → `source/api/persistencia/connection.py` (propuesta).
- **Enfoque:** abre o crea el fichero único configurado, crea `data/` si falta, ejecuta `PRAGMA journal_mode = WAL` y configura `busy_timeout` > 0; expone `transaccion()` que confirma o deshace (ALT-005). Conexión única compartida entre hilos (`check_same_thread=False`); las escrituras se serializan con WAL + `busy_timeout` y un lock interno del módulo para el uso seguro de la conexión entre hilos. Sin conexión de red ni servidor (NFR-001).
- **Pruebas automáticas:** `tests/unit/test_persistencia_connection.py` (nuevo) — con ruta temporal inexistente se crea el directorio y un único `.db`; `PRAGMA journal_mode` devuelve `wal`; `busy_timeout` > 0; transacción confirmada persiste y deshecha no; dos escrituras concurrentes terminan sin `SQLITE_BUSY` no controlado y sin corrupción; no se abre conexión de red. Comando: `pytest tests/unit/test_persistencia_connection.py`.
- **Prueba manual:** arrancar la persistencia con la configuración por defecto y comprobar que aparece `data/job_emcan.db` y que solo hay un fichero de base de datos en el árbol del proyecto.

### TASK-004 Migraciones secuenciales y esquema SQLite

- **Ficheros:** `source/api/persistencia/migrations.py` (nuevo): lista `MIGRACIONES` (migraciones numeradas) + `migrar(conexion) -> int`. Componente `schema-migrator` → `source/api/persistencia/migrations.py` (propuesta).
- **Enfoque:** crea `schema_version(version INTEGER PRIMARY KEY, applied_at TEXT)`, aplica migraciones secuenciales y transaccionales. La migración inicial `001` crea `ofertas` (las 21 columnas del esquema conceptual, con `embedding_dim` INTEGER e `interesada` INTEGER DEFAULT 0), `ingesta_log(id, ultimo_timestamp, actualizado_en)` con un único registro `id=1`, la restricción UNIQUE `(comunidad, codigo)` y los índices `(estado, fecha_fin_difusion)` y `(embedding_model_name, embedding_model_version)`. Versión futura o fichero no abrible → aborta con error explícito sin sobrescribir; migración fallida → rollback (ALT-004).
- **Pruebas automáticas:** `tests/unit/test_persistencia_migrations.py` (nuevo) — tras migrar existen `schema_version`, `ofertas` e `ingesta_log`; `ofertas` tiene las 21 columnas; `embedding` es BLOB, `embedding_dim` entero e `interesada` entero con defecto 0; sin tabla ni extensión vectorial; insertar duplicado `(comunidad, codigo)` viola UNIQUE; existen los 2 índices; `schema_version` refleja la versión; BD ya migrada no reejecuta; versión futura aborta sin modificar; migración fallida deshace la transacción. Comando: `pytest tests/unit/test_persistencia_migrations.py`.
- **Prueba manual:** migrar desde cero y revisar el esquema con un inspector de SQLite (tablas, columnas, índices y restricción única); arrancar dos veces y comprobar que la segunda no reejecuta migraciones.

### TASK-005 Repositorio de ofertas: upsert y consulta por clave natural

- **Ficheros:** `source/api/persistencia/repository.py` (nuevo): dataclass `Oferta`, constantes de estado `EstadoOferta` (`sin_ficha`/`vigente`/`cerrada`), helpers `serializar_embedding`/`reconstruir_embedding` (numpy `float32`) y `RepositorioOfertas` con `crear_o_actualizar(oferta)` y `consultar_por_clave(comunidad, codigo)`. Componente `ofertas-repository` → `source/api/persistencia/repository.py` (propuesta).
- **Enfoque:** upsert por `(comunidad, codigo)` sin duplicar la fila; actualiza `fecha_ultima_actualizacion` sin tocar `fecha_alta`; `sector`/`nivel`/`contrato` siempre vacíos; conserva el embedding con nombre, versión y dimensión; código como texto de 12 dígitos y fechas `dd/mm/aaaa`; consulta inexistente devuelve una indicación explícita de no encontrada. No escribe ni lee base vectorial ni extensión vectorial (NFR-005). `numpy` se usa solo para serializar/reconstruir el `float32`, sin calcular embeddings ni similitud.
- **Pruebas automáticas:** `tests/unit/test_persistencia_repository.py` (nuevo) — persistir y consultar devuelve todos los campos; persistir dos veces la misma clave deja una fila y actualiza; `fecha_ultima_actualizacion` avanza y `fecha_alta` no cambia; reservados vacíos; oferta sin embedding es válida; con embedding se recupera BLOB + nombre + versión + `embedding_dim`; código conserva ceros; fechas `dd/mm/aaaa`; mismo código en comunidades distintas coexiste; inexistente indica no encontrada; dos escrituras concurrentes dejan un registro; roundtrip de serialización/reconstrucción `float32` con numpy. Comando: `pytest tests/unit/test_persistencia_repository.py::test_upsert_consulta` (representativo; el fichero cubre el resto de casos).
- **Prueba manual:** persistir una oferta real y consultarla: comprobar que los valores coinciden con los enviados y que los tres campos reservados vienen vacíos.

### TASK-006 Listado por estado y lista de códigos vistos

- **Ficheros:** `source/api/persistencia/repository.py` (modificar): `listar_vigentes()` y `listar_codigos_vistos(comunidad)`. Componente `ofertas-repository` → `source/api/persistencia/repository.py` (propuesta).
- **Enfoque:** listado por estado usando el índice `(estado, fecha_fin_difusion)` y ordenando por fecha de fin de difusión; la lista de códigos vistos es la unión de los códigos importados sin ficha y los procedentes de fichas ingeridas, sin duplicados; un código ausente de la lista se considera oferta nueva. `vigente` es el caso principal (REQ-009).
- **Pruebas automáticas:** `tests/unit/test_persistencia_repository.py` — con `vigente`, `cerrada` y `sin_ficha` el listado devuelve solo las `vigente` con los campos mínimos; códigos vistos de Cantabria = unión sin duplicados; presente no es nueva y ausente sí; otra comunidad no incluye los de Cantabria; usa el índice y no escanea la tabla completa de forma incontrolada. Comando: `pytest tests/unit/test_persistencia_repository.py::test_listado_vigentes` (representativo).
- **Prueba manual:** con ofertas vigentes, cerradas y sin ficha en la base de datos, listar las vigentes y comprobar que solo aparecen las vigentes con los campos mínimos exigidos.

### TASK-007 Reducción a registro mínimo conservando el embedding

- **Ficheros:** `source/api/persistencia/repository.py` (modificar): `reducir_a_registro_minimo(comunidad, codigo)`. Componente `ofertas-repository` → `source/api/persistencia/repository.py` (propuesta).
- **Enfoque:** vacía `texto_libre` y `contacto` y conserva el resto de campos, incluido el embedding con nombre, versión y dimensión; no toca `interesada`, `fecha_alta`, `fecha_cierre` ni `fecha_ultima_actualizacion`; `sector`/`nivel`/`contrato` siguen presentes y vacíos; la operación es idempotente (REQ-006, ALT-006).
- **Pruebas automáticas:** `tests/unit/test_persistencia_repository.py` — con texto/contacto, tras la reducción ambos quedan vacíos y el resto intacto; con embedding se conserva BLOB + nombre + versión + `embedding_dim`; sin embedding sigue válido y nulo; `estado`/`interesada`/`fecha_alta`/`fecha_cierre` no cambian; reservados siguen vacíos; idempotente (aplicar dos veces da el mismo resultado). Comando: `pytest tests/unit/test_persistencia_repository.py::test_reduccion_registro_minimo` (representativo).
- **Prueba manual:** reducir una oferta con embedding y consultar el registro: comprobar que no quedan texto ni contacto y que el embedding sigue disponible con sus metadatos.

### TASK-008 Importador idempotente de `data/seen_codes.json`

- **Ficheros:** `source/api/persistencia/importer.py` (nuevo): dataclass `ResultadoImportacion` (`importados`/`existentes`) + `importar_codigos_vistos(conexion, ruta)`. Componente `seen-codes-importer` → `source/api/persistencia/importer.py` (propuesta).
- **Enfoque:** lee `data/seen_codes.json` como lista plana de códigos de texto; por cada código no existente crea un registro con comunidad `Cantabria`, estado `sin_ficha` y el resto vacío (upsert por clave natural); nunca modifica ni escribe el fichero origen (SUP-013); idempotente. Fichero ausente o JSON inválido/no lista → se registra y continúa sin modificar la base de datos (ALT-003).
- **Pruebas automáticas:** `tests/unit/test_persistencia_importer.py` (nuevo) — JSON de 103 códigos crea 103 registros `sin_ficha`; cada registro con comunidad `Cantabria` y campos vacíos; códigos que no empiezan por `06` también se importan como `Cantabria`; informa de importados y existentes; repetir → 0 importados; código nuevo entre dos → solo ese; códigos con ceros iniciales; fichero ausente → continúa; JSON inválido/no lista → error registrado sin modificar la BD; el fichero no cambia ni su marca de tiempo. Comando: `pytest tests/unit/test_persistencia_importer.py`.
- **Prueba manual:** ejecutar la importación con el `data/seen_codes.json` real y comprobar un registro por código en estado `sin_ficha`; comprobar que el fichero conserva contenido y fecha de modificación.

### TASK-009 Cliente HTTP de `GET /buscador/status`

- **Ficheros:** `source/api/persistencia/client.py` (nuevo): dataclass `EstadoBuscador` + `ClienteBuscador`/`consultar_estado(cliente, url_base)`. Componente `buscador-client` → `source/api/persistencia/client.py` (propuesta).
- **Enfoque:** petición GET a `<url_base>/buscador/status`; devuelve `in_progress`, `progreso` y `ultima_pasada` con sus seis campos (`timestamp`, `comunidad`, `total_listado`, `error_global`, `errores_por_oferta`, `ofertas_nuevas`); distingue de forma explícita los casos de error HTTP, fallo de red, `error_global` no vacío y `ultima_pasada` nula como resultados controlados (sin excepción). Nunca lanza pasadas ni descarga fichas; no escribe en la base de datos ni modifica `data/`. El cliente HTTP es inyectable (httpx) para pruebas.
- **Pruebas automáticas:** `tests/unit/test_persistencia_client.py` (nuevo) — con el cuerpo real devuelve `in_progress`/`progreso`/`ultima_pasada` con sus seis campos; la URL solicitada es `url_base + /buscador/status`; `ultima_pasada` nula se comunica de forma distinguible; `error_global` no vacío sin excepción; error HTTP/red → error controlado; solo se emite una petición a `/buscador/status` por consulta; no escribe en la BD ni en `data/`. Comando: `pytest tests/unit/test_persistencia_client.py`.
- **Prueba manual:** con la aplicación arrancada, consultar el cliente contra `http://localhost:8000` y comprobar que devuelve el mismo `ultima_pasada` que muestra `GET /buscador/status`.

### TASK-010 Tarea periódica de ingesta de ofertas completas

- **Ficheros:** `source/api/persistencia/ingestion.py` (nuevo): `TareaIngesta` (hilo daemon con reloj inyectable `RelojProtocol`/`RelojReal` y `threading.Event`), `iniciar()`/`detener()`. Componente `ingestion-task` → `source/api/persistencia/ingestion.py` (propuesta).
- **Enfoque:** ciclo con la cadencia configurada; consulta el estado vía `buscador-client`; compara `ultima_pasada.timestamp` con `ingesta_log.ultimo_timestamp` y, solo si difiere (y no hay `error_global` ni `ultima_pasada` nula), persiste cada oferta vía el repositorio (upsert: `sin_ficha` → `vigente`; `vigente` no se sobrescribe con vacíos) y luego registra el `timestamp` en `ingesta_log` (id=1). Ante buscador caído/`error_global`/`ultima_pasada` nula no persiste ni avanza el `timestamp` y deja constancia en el log. Cadencia y cancelación limpias; un ciclo no se solapa consigo mismo (guard `_en_ejecucion`).
- **Pruebas automáticas:** `tests/unit/test_persistencia_ingestion.py` (nuevo) — `timestamp` nuevo + 2 ofertas → ambas `vigente` con todos los campos y reservados vacíos; mismo `timestamp` no duplica ni reimporta; código `sin_ficha` en `ofertas_nuevas` se completa a `vigente` sin duplicar; `vigente` existente no se sobrescribe con vacíos; `ultima_pasada` nula/`error_global`/buscador caído → no persiste ni avanza; el `timestamp` se recupera de `ingesta_log` tras reinicio; cadencia configurada y cancelación sin ejecuciones en curso. Comando: `pytest tests/unit/test_persistencia_ingestion.py`.
- **Prueba manual:** arrancar la aplicación con una pasada real y comprobar en la BD que las ofertas nuevas están en `vigente`; reiniciar y comprobar que la pasada ya importada no vuelve a importarse.

### TASK-011 Tarea periódica de purga por retención

- **Ficheros:** `source/api/persistencia/purge.py` (nuevo): `TareaPurga` (hilo daemon con reloj inyectable y `threading.Event`), `iniciar()`/`detener()`. Componente `purge-task` → `source/api/persistencia/purge.py` (propuesta).
- **Enfoque:** con la frecuencia configurada, consulta las ofertas `cerrada` cuya `fecha_cierre` supere los días de retención y cuyo `interesada` sea `0`, y las reduce vía el repositorio; omite `interesada = 1`; nunca purga `vigente`/`sin_ficha`; no modifica `ingesta_log` ni el estado de las ofertas. Frecuencia y cancelación limpias; un ciclo no se solapa consigo mismo.
- **Pruebas automáticas:** `tests/unit/test_persistencia_purge.py` (nuevo) — cerrada fuera de plazo se reduce conservando embedding con nombre/versión/dimensión; dentro de plazo no se modifica; `interesada = 1` se omite conservando texto y contacto; `vigente`/`sin_ficha` nunca se purgan; no modifica `ingesta_log` ni el estado; frecuencia configurada y cancelación sin ejecuciones en curso. Comando: `pytest tests/unit/test_persistencia_purge.py`.
- **Prueba manual:** cerrar una oferta, simular el vencimiento del plazo y ejecutar la purga: comprobar que desaparecen texto y contacto y que el embedding sigue disponible.

### TASK-012 Endpoints de la API de persistencia

- **Ficheros:** `source/api/persistencia/routes.py` (nuevo): `router = APIRouter(prefix="/persistencia", tags=["persistencia"])` con 4 endpoints y modelos Pydantic de entrada/salida. Componente `persistencia-api` → `source/api/persistencia/routes.py` (propuesta).
- **Enfoque:** `POST /persistencia/ofertas` (crear/actualizar), `GET /persistencia/ofertas/{comunidad}/{codigo}` (consulta; `404` con `HTTPException` si no existe), `GET /persistencia/ofertas/vigentes` y `GET /persistencia/codigos-vistos/{comunidad}`; consumen el `RepositorioOfertas` guardado en `app_state` sin que el cliente ejecute SQL. El embedding se expone en JSON como base64 (`type: string, format: byte`) y se convierte a/desde `bytes` en el borde de la API. Sin autenticación (SUP-008).
- **Pruebas automáticas:** `tests/integration/test_persistencia_api.py` (nuevo) — el endpoint de crear/actualizar devuelve el registro; la consulta devuelve todos los campos de REQ-002 + estado + embedding/metadatos; inexistente → 404 explícita; vigentes devuelve solo `vigente`; códigos vistos = importados + ingeridos; doble actualización no crea segunda fila; sin 401/403; respuesta JSON sin SQL. Comando: `pytest tests/integration/test_persistencia_api.py`.
- **Prueba manual:** crear una oferta desde el endpoint, consultarla y comprobar que devuelve todos los campos guardados; consultar una oferta inexistente y comprobar que la respuesta indica que no se encontró.

### TASK-013 Arranque y apagado de la persistencia en la aplicación

- **Ficheros:** `source/api/main.py` (modificar): ampliar `lifespan` para cargar la configuración de persistencia, abrir la conexión, migrar, importar `data/seen_codes.json` y arrancar `TareaIngesta`/`TareaPurga` junto al scheduler del buscador; en el apagado, cancelar ingesta y purga ANTES del scheduler del buscador. Componente `api-service` → `source/api/main.py` (propuesta).
- **Enfoque:** tras el bloque del buscador, se carga `config/persistencia.yaml`, se abre la conexión (`abrir_conexion`), se migra (`migrar`), se importa `seen_codes.json` y se arrancan las dos tareas, guardando todo en `app_state` (p. ej. `conexion_bd`, `repositorio`, `tarea_ingesta`, `tarea_purga`). `seen_codes.json` corrupto/ausente no bloquea el arranque (ALT-003); esquema en versión futura aborta (ALT-004). En el apagado: `detener()` de ingesta y purga, después `detener()` del scheduler del buscador y cierre del cliente HTTP. No altera `data/seen_codes.json` (SUP-013).
- **Pruebas automáticas:** `tests/integration/test_persistencia_api.py` — tras arrancar, la BD existe en la ruta configurada con `wal` y `schema_version` esperado; `seen_codes.json` importado; ingesta/purga/scheduler activos; al apagar, ingesta y purga canceladas antes que el scheduler; `seen_codes.json` corrupto no impide el arranque; versión futura aborta; no se altera `seen_codes.json`; los endpoints de `api-buscador` siguen respondiendo igual. Comando: `pytest tests/integration/test_persistencia_api.py::test_startup_shutdown`.
- **Prueba manual:** arrancar la aplicación y comprobar que aparecen `data/job_emcan.db`, las tablas esperadas y que la ingesta hace su primera consulta; detener la aplicación y comprobar que no queda ninguna tarea de persistencia viva.

### TASK-014 Verificación de integración de la persistencia

- **Ficheros:** `tests/integration/test_persistencia_integration.py` (nuevo): end-to-end con `TestClient`, `seen_codes.json` temporal y `GET /buscador/status` simulado. Componente `api-service` → `source/api/` (propuesta).
- **Enfoque:** monta la aplicación con cliente HTTP de prueba y cubre los casos de pasada nueva, buscador caído, `ultima_pasada` nula, código ya importado y cierre con purga posterior; verifica la persistencia, los endpoints, la idempotencia, la integridad de `seen_codes.json` y la ausencia de excepciones no controladas.
- **Pruebas automáticas:** `tests/integration/test_persistencia_integration.py` — JSON de 3 códigos + pasada con uno de esos + otra nueva → 4 códigos (3 `sin_ficha`, 1 `vigente`); consulta devuelve la ficha completa con reservados vacíos; vigentes devuelve solo `vigente`; códigos vistos devuelve los 4; misma pasada no crea filas; buscador caído/`ultima_pasada` nula no cambia la BD; cierre + plazo → purga conserva embedding; `seen_codes.json` conserva su contenido; códigos con ceros y fechas `dd/mm/aaaa`; único fichero SQLite `wal` sin servidor ni tabla vectorial. Comando: `pytest tests/integration/test_persistencia_integration.py`.
- **Prueba manual:** ejecutar la prueba de integración y revisar el informe: todos los escenarios salen con el resultado esperado; revisar `data/`: solo el fichero SQLite único y el `seen_codes.json` sin cambios.

### TASK-015 Contrato: openapi - operaciones de persistencia

- **Ficheros:** `docs/contracts/openapi/api-persistencia.yaml` (nuevo). Componente `persistencia-api` → contrato openapi (tarea del documentador).
- **Enfoque:** formalizar las 4 operaciones tal como quedaron implementadas (implementation-first, tras TASK-014): crear/actualizar oferta, consultar por `(comunidad, codigo)`, listar vigentes y listar códigos vistos, con el esquema de oferta (REQ-002 + estado + embedding con nombre/versión/dimensión) y las respuestas 200/404 de oferta no encontrada. El embedding se describe como BLOB binario (`type: string, format: byte`) y `embedding_dim` como entero; documenta códigos como texto de 12 dígitos y fechas `dd/mm/aaaa`.
- **Pruebas automáticas:** `tests/contract/test_persistencia_openapi.py` (nuevo) — el YAML carga y contiene las 4 operaciones con sus respuestas 200 y 404; el esquema de oferta incluye los campos (incluidos `sector`/`nivel`/`contrato`, estado, `embedding`, `embedding_model_name`, `embedding_model_version`, `embedding_dim`); embedding como `byte` y `embedding_dim` entero; documenta códigos texto y fechas `dd/mm/aaaa`; rutas y campos coinciden con la integración. Comando: `pytest tests/contract/test_persistencia_openapi.py`.
- **Prueba manual:** revisar el contrato y comprobar las 4 interfaces de la fila de contratos afectados; comparar con las respuestas JSON reales de TASK-014 y confirmar que no hay campos divergentes.

### TASK-016 Contrato: configuración - fichero de configuración de la persistencia

- **Ficheros:** `config/persistencia.yaml` (documentar el formato en la cabecera, como `config/buscador.yaml`). Componente `config-persistencia` (tarea del documentador).
- **Enfoque:** documentar el formato exacto y los valores por defecto de los 5 campos (`base_de_datos.ruta`, `buscador.url_base`, `ingesta.cadencia_segundos`, `purga.dias_retencion`, `purga.frecuencia_segundos`) y las reglas de validación, alineado con la carga de TASK-002 y con lo que la aplicación de TASK-013 aplica. El fichero real cumple el formato sin ambigüedad y una configuración válida se carga sin cambios de código.
- **Pruebas automáticas:** `tests/contract/test_persistencia_config_contract.py` (nuevo) — el fichero carga con el formato documentado y devuelve ruta, URL, cadencia, retención y frecuencia; un campo obligatorio ausente → error que lo identifica; un tipo incorrecto → error controlado; los valores por defecto documentados coinciden con la implementación; sin rutas de servidor de BD ni credenciales. Comando: `pytest tests/contract/test_persistencia_config_contract.py`.
- **Prueba manual:** revisar que la fila de contrato (configuración de la persistencia) queda descrita con el mismo formato que usa el fichero real; modificar el fichero siguiendo solo el formato documentado y comprobar que la aplicación arranca con la nueva configuración.

### TASK-017 Actualización del mapa de arquitectura

- **Ficheros:** `.sdd/architecture.md` (modificar). Componente `api-service` → `.sdd/architecture.md` (tarea del documentador).
- **Enfoque:** registrar los 10 módulos nuevos (`api-persistencia`, `config-persistencia`, `db-connection`, `schema-migrator`, `ofertas-repository`, `seen-codes-importer`, `buscador-client`, `ingestion-task`, `purge-task`, `persistencia-api`) con identificador, ruta, responsabilidad y dependencias, el contrato openapi de persistencia y el contrato de configuración, y actualizar la descripción del módulo `API` para incluir la persistencia. Usa las rutas definitivas realmente implementadas (p. ej. `config-persistencia` → `config/persistencia.yaml + source/api/persistencia/config.py`, reflejando el patrón de `config-buscador`).
- **Pruebas automáticas:** `tests/contract/test_persistencia_architecture.py` (nuevo) — `.sdd/architecture.md` contiene los identificadores de todos los módulos nuevos con ruta no vacía; la sección de contratos incluye el OpenAPI de persistencia y el contrato de configuración; la descripción de `API` ya no se limita al parseo de PDFs y al rastreador del buscador; todos los ficheros citados existen. Comando: `pytest tests/contract/test_persistencia_architecture.py`.
- **Prueba manual:** revisar `.sdd/architecture.md` y comprobar que cada módulo nuevo tiene identificador, ruta y dependencias, y que las rutas coinciden con los ficheros realmente creados.

## Orden de implementación

1. TASK-001 (habilitada por: sin dependencias)
2. TASK-002 (habilitada por: TASK-001 entregada — subpaquete importable y dependencia `numpy` declarada)
3. TASK-003 (habilitada por: TASK-002 entregada — configuración cargable)
4. TASK-004 (habilitada por: TASK-003 entregada — conexión y transacción disponibles)
5. TASK-005 (habilitada por: TASK-004 entregada — esquema migrado)
6. TASK-006 (habilitada por: TASK-005 entregada) y TASK-007 (habilitada por: TASK-005) — en paralelo
7. TASK-008 (habilitada por: TASK-006 entregada) y TASK-009 (habilitada por: TASK-002 entregada) — en paralelo
8. TASK-010 (habilitada por: TASK-007 y TASK-009 entregadas) y TASK-011 (habilitada por: TASK-007) — en paralelo
9. TASK-012 (habilitada por: TASK-006 entregada)
10. TASK-013 (habilitada por: TASK-004, TASK-008, TASK-010, TASK-011 y TASK-012 entregadas)
11. TASK-014 (habilitada por: TASK-013 entregada)
12. TASK-015 (habilitada por: TASK-012 y TASK-014 entregadas — implementation-first) y TASK-016 (habilitada por: TASK-002 y TASK-013 entregadas) — en paralelo
13. TASK-017 (habilitada por: TASK-014, TASK-015 y TASK-016 entregadas)

## Riesgos y dudas técnicas

- **Tensión en TASK-002 (fichero ausente):** el `tasks.md` dice a la vez "sin fichero → valores por defecto" y "fichero ausente → error controlado". Decisión adoptada: `cargar_configuracion()` devuelve los valores por defecto cuando el fichero no existe (coherencia con `source/api/buscador/config.py` y KISS), y reserva `ErrorConfiguracion` para YAML malformado/raíz no mapa/tipo incorrecto. Si se prefiere "error controlado ante ausente", el cambio queda limitado a TASK-002 y TASK-016.
- **Mecanismo de planificación:** `threading` con reloj inyectable y `threading.Event` (como `api-buscador`), sin dependencia externa. Si se prefiriera una librería (p. ej. APScheduler), declararla en TASK-001 y ajustar TASK-010/TASK-011/TASK-013.
- **Unicidad de `ingesta_log`:** se adopta un único registro `id=1` actualizado por UPSERT, sin restricción UNIQUE adicional (KISS). Alternativa admitida: restricción UNIQUE sobre `id` y `INSERT ... ON CONFLICT(id) DO UPDATE`.
- **Llamada HTTP al propio proceso:** la ingesta consulta `GET /buscador/status` vía `buscador.url_base` (por defecto `http://localhost:8000`), es decir, el propio proceso FastAPI, conforme a DEC-005. En pruebas se inyecta un cliente HTTP de prueba; en producción la URL base debe apuntar al puerto real donde sirve la app.
- **Prefijo y estado 404:** se adopta `/persistencia` y `404` para "no encontrada"; cualquier cambio queda acotado a TASK-012, TASK-014 y TASK-015.
- **Embedding en JSON vs BLOB:** en la API el embedding viaja como base64 (`format: byte`); la conversión a `bytes` (BLOB) ocurre en el borde de la API, manteniendo el repositorio sobre `bytes`. `numpy` solo serializa/reconstruye `float32`; esta feature no calcula embeddings.
- **`api-buscador` no se modifica:** la compatibilidad se resuelve solo desde `api-persistencia` (TASK-008 lee el JSON, TASK-009/TASK-010 consultan el status).

## Validación

- Suite del módulo: pendiente
- Integración: pendiente
- Validación manual: pendiente
