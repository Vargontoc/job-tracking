# Tareas: api-persistencia

Estado: aprobado
Revisión: 1
Basado en: requirements@5, design@2
Verificación: correcta

## Resumen

El trabajo se divide en diecisiete tareas (TASK-001..TASK-017) que siguen la cadena de dependencias del diseño: primero la estructura del paquete y la configuración, después la conexión SQLite con WAL y las migraciones del esquema, luego el repositorio de ofertas, el importador de códigos vistos y el cliente del buscador, a continuación las dos tareas periódicas (ingesta y purga), los endpoints de persistencia, la integración del arranque y apagado con la aplicación FastAPI existente, la verificación de integración, las dos tareas de contrato (implementation-first) y por último la actualización del mapa de arquitectura. Cada tarea de implementación incluye sus propias pruebas; solo la verificación de extremo a extremo se separa como tarea de integración.

La ingesta y la purga conviven en el mismo proceso FastAPI que el planificador diario de `api-buscador`, sin modificar `api-buscador` en ningún punto.

## Orden de implementación

1. TASK-001 Estructura del paquete y dependencias → TASK-002 Configuración de la persistencia.
2. TASK-003 Conexión SQLite con WAL y pragmas → TASK-004 Migraciones y esquema.
3. TASK-005 Repositorio de ofertas: upsert y consulta → TASK-006 Listado por estado y códigos vistos → TASK-007 Purga de campos a registro mínimo.
4. TASK-008 Importador de `data/seen_codes.json` → TASK-009 Cliente HTTP de `/buscador/status`.
5. TASK-010 Tarea periódica de ingesta → TASK-011 Tarea periódica de purga.
6. TASK-012 Endpoints de persistencia.
7. TASK-013 Arranque y apagado en la aplicación.
8. TASK-014 Verificación de integración.
9. TASK-015..TASK-016 Contratos (implementation-first).
10. TASK-017 Actualización del mapa.

## Tareas

### [x] TASK-001 Estructura del paquete de persistencia y dependencias

- **Cubre:** NFR-001, NFR-005, DEC-001, DEC-002
- **Componente:** api-persistencia | source/api/persistencia
- **Módulo:** api-persistencia
- **Depende de:** -
- **Alcance:** Crear el subpaquete `source/api/persistencia/` con su `__init__.py` y declarar en `pyproject.toml` las dependencias que exige el diseño (`httpx` para el cliente del buscador y numpy para la reconstrucción del embedding como `float32`), sin introducir motor de base de datos servidor ni extensión vectorial.
- **Hecho cuando:** el subpaquete `source/api/persistencia` se importa sin errores, las dependencias declaradas cubren las que usa el diseño y el runner de pruebas recorre `tests/` sin fallos de colección.
- **Pruebas automáticas:**
  - La suite arranca sin errores de importación de `source.api.persistencia` ni de las dependencias declaradas.
  - Una comprobación confirma que `httpx` y `numpy` están disponibles en el entorno de pruebas.
  - El paquete no importa ni referencia un motor de base de datos servidor (SQLAlchemy, PostgreSQL, MySQL) ni una extensión de SQLite para vectores, conforme a NFR-001 y NFR-005.
- **Prueba manual:**
  1. Instalar el proyecto en un entorno virtual limpio y ejecutar la suite de pruebas: termina sin fallos por dependencias ausentes.

### [x] TASK-002 Fichero de configuración de la persistencia

- **Cubre:** REQ-011, REQ-018, NFR-001, SUP-001, SUP-015, DEC-001
- **Componente:** config-persistencia | config/persistencia.yaml
- **Módulo:** config-persistencia
- **Depende de:** TASK-001
- **Alcance:** Crear el fichero de configuración `config/persistencia.yaml` con la ruta del fichero SQLite (por defecto `data/job_emcan.db`), la URL base del buscador (por defecto `http://localhost:8000`), la cadencia de ingesta en segundos (por defecto `300`), los días de retención de la purga (por defecto `7`) y la frecuencia de la purga en segundos (por defecto `86400`), e implementar su carga con valores por defecto y error controlado ante fichero ausente o malformado.
- **Hecho cuando:** la carga devuelve la configuración completa con los valores por defecto del diseño cuando no se indican otros, un fichero ausente o malformado produce un error controlado que identifica la configuración como origen, y la ruta de la base de datos es relativa a la raíz del proyecto.
- **Pruebas automáticas:**
  - La carga del fichero `config/persistencia.yaml` devuelve ruta de base de datos, URL base del buscador, cadencia de ingesta, días de retención y frecuencia de purga.
  - Sin fichero de configuración, la ruta es `data/job_emcan.db`, la URL base es `http://localhost:8000`, la cadencia de ingesta son 300 s, la retención son 7 días y la frecuencia de purga son 86400 s.
  - Un fichero ausente produce un error controlado, no una excepción no controlada.
  - Un fichero con YAML malformado o con un campo de tipo incorrecto produce un error controlado que identifica el campo problemático.
  - La configuración no contiene ninguna ruta de servidor de base de datos ni credenciales, conforme a NFR-001.
- **Prueba manual:**
  1. Abrir `config/persistencia.yaml` y comprobar que contiene los cinco campos con sus valores por defecto.
  2. Cambiar la cadencia de ingesta y la retención, recargar la configuración y comprobar que los nuevos valores son los que se aplican.

### [x] TASK-003 Conexión única a SQLite con WAL y pragmas

- **Cubre:** REQ-010, REQ-011, NFR-001, NFR-002, NFR-006, DEC-001, DEC-008, ALT-004, ALT-005
- **Componente:** db-connection | source/api/persistencia/connection.py
- **Módulo:** db-connection
- **Depende de:** TASK-002
- **Alcance:** Implementar el componente que abre o crea el fichero SQLite único configurado, crea el directorio `data/` si falta, activa `PRAGMA journal_mode = WAL`, configura `busy_timeout`, y expone el contexto de conexión y de transacción para el resto de componentes, sin depender de ningún servidor de base de datos.
- **Hecho cuando:** tras inicializar la persistencia existe un único fichero `.db` en la ruta configurada, `PRAGMA journal_mode` devuelve `wal`, `busy_timeout` queda establecido en un valor mayor que cero y las transacciones se pueden abrir y confirmar o deshacer.
- **Pruebas automáticas:**
  - Con una ruta temporal inexistente, la inicialización crea el directorio y el fichero SQLite y el directorio contiene un único fichero `.db`.
  - `PRAGMA journal_mode` devuelve `wal` tras la inicialización, conforme a NFR-002 y REQ-011.
  - `PRAGMA busy_timeout` devuelve un valor mayor que cero.
  - Una transacción confirmada deja los cambios persistidos y una transacción deshecha no los deja, conforme a ALT-005.
  - Dos escrituras concurrentes sobre el mismo fichero terminan ambas sin error `SQLITE_BUSY` no controlado y sin datos corruptos.
  - No se abre ninguna conexión de red ni se requiere ningún servidor de base de datos, conforme a NFR-001.
- **Prueba manual:**
  1. Arrancar la persistencia con la configuración por defecto y comprobar que aparece `data/job_emcan.db` y que solo hay un fichero de base de datos en el árbol del proyecto.

### [x] TASK-004 Migraciones secuenciales y esquema SQLite

- **Cubre:** REQ-010, REQ-007, NFR-005, NFR-007, SUP-002, SUP-003, SUP-010, DEC-002, DEC-003, DEC-004, DEC-007, ALT-004
- **Componente:** schema-migrator | source/api/persistencia/migrations.py
- **Módulo:** schema-migrator
- **Depende de:** TASK-003
- **Alcance:** Implementar el migrador que crea y mantiene la tabla `schema_version` (`version INTEGER PRIMARY KEY`, `applied_at TEXT`), aplica migraciones numeradas secuencialmente y transaccionales, y crea el esquema inicial con las tablas `ofertas` (incluidas las columnas `embedding_dim` e `interesada`, esta última con valor por defecto `0`), `ingesta_log` (`id`, `ultimo_timestamp`, `actualizado_en`), la restricción UNIQUE `(comunidad, codigo)` y los índices `(estado, fecha_fin_difusion)` y `(embedding_model_name, embedding_model_version)`.
- **Hecho cuando:** sobre una base de datos recién creada existen las tres tablas con todas las columnas del esquema conceptual del diseño, la restricción UNIQUE `(comunidad, codigo)` está activa, los tres índices existen, y la tabla `schema_version` refleja la versión aplicada; una base de datos ya migrada no reejecuta migraciones; una base de datos en versión futura o un fichero no abrirse abortan el arranque con error explícito.
- **Pruebas automáticas:**
  - Sobre una base de datos vacía, tras migrar existen las tablas `schema_version`, `ofertas` e `ingesta_log`.
  - La tabla `ofertas` tiene las columnas `comunidad`, `provincia`, `codigo`, `ocupacion`, `municipio`, `sector`, `nivel`, `contrato`, `fecha_inicio_difusion`, `fecha_fin_difusion`, `estado`, `texto_libre`, `contacto`, `embedding`, `embedding_model_name`, `embedding_model_version`, `embedding_dim`, `interesada`, `fecha_alta`, `fecha_cierre` y `fecha_ultima_actualizacion`.
  - `embedding` es de tipo BLOB, `embedding_dim` es entero y `interesada` es entero con valor por defecto `0`, conforme a DEC-002 y DEC-007.
  - No existe ninguna tabla de vectores ni ninguna extensión vectorial cargada, conforme a NFR-005.
  - Insertar dos ofertas con la misma comunidad y el mismo código viola la restricción UNIQUE, conforme a REQ-007.
  - Los índices `(estado, fecha_fin_difusion)` y `(embedding_model_name, embedding_model_version)` existen.
  - La tabla `schema_version` contiene la versión esperada con su `applied_at`.
  - Al migrar una base de datos ya en la versión esperada, no se ejecuta ninguna migración nueva y la versión no cambia.
  - Una base de datos con versión superior a la esperada aborta con error explícito y no modifica el fichero, conforme a ALT-004.
  - Una migración que falla deja el esquema en el estado anterior (se deshace la transacción) y el arranque se aborta.
- **Prueba manual:**
  1. Migrar una base de datos desde cero y revisar el esquema resultante con una herramienta de inspección de SQLite: tablas, columnas, índices y restricción única.
  2. Arrancar dos veces seguidas y comprobar que la segunda vez no se reejecuta ninguna migración.

### [x] TASK-005 Repositorio de ofertas: upsert y consulta por clave natural

- **Cubre:** REQ-001, REQ-002, REQ-003, REQ-004, REQ-007, REQ-008, NFR-003, NFR-004, NFR-005, NFR-007, SUP-002, SUP-006, SUP-007, SUP-011, DEC-002, DEC-003, DEC-008, ALT-005
- **Componente:** ofertas-repository | source/api/persistencia/repository.py
- **Módulo:** ofertas-repository
- **Depende de:** TASK-004
- **Alcance:** Implementar la abstracción de escritura y lectura de ofertas sobre la clave natural `(comunidad, codigo)`: crear o actualizar una oferta sin duplicar la fila, registrar la fecha y hora de última modificación, tratar los campos `sector`, `nivel` y `contrato` como vacíos, conservar el embedding con su nombre, versión y dimensión, y consultar una oferta por su comunidad y su código devolviendo todos los campos persistidos.
- **Hecho cuando:** persistir una oferta inexistente crea un registro con todos los campos recibidos y estado `vigente`; persistir de nuevo la misma `(comunidad, codigo)` actualiza los campos modificables sin duplicar la fila y actualiza `fecha_ultima_actualizacion`; una consulta por clave natural devuelve todos los campos persistidos y una consulta inexistente indica de forma explícita que no se encontró la oferta.
- **Pruebas automáticas:**
  - Persistir una oferta con todos los campos y consultar por `(comunidad, codigo)` devuelve comunidad, provincia, código, ocupación, municipio, fechas de difusión, texto libre, contacto, estado, embedding y metadatos del modelo, conforme a REQ-002 y REQ-004.
  - Persistir dos veces la misma `(comunidad, codigo)` deja una sola fila y la segunda vez actualiza los campos modificables, conforme a REQ-001.
  - Tras una actualización, `fecha_ultima_actualizacion` es distinta o posterior a la anterior y `fecha_alta` no cambia.
  - `sector`, `nivel` y `contrato` se almacenan vacíos y no se infieren de ningún otro campo.
  - Una oferta sin embedding se persiste y se consulta con el embedding nulo y sus metadatos nulos, y sigue siendo válida, conforme a REQ-004.
  - Una oferta con embedding se consulta con el BLOB, el nombre del modelo, la versión y `embedding_dim` coherentes con los almacenados, conforme a DEC-002.
  - El código se conserva como texto de 12 dígitos con sus ceros iniciales, conforme a NFR-003.
  - Las fechas de difusión se guardan y se devuelven exactamente en formato `dd/mm/aaaa`, conforme a NFR-004.
  - Dos ofertas con el mismo código y comunidades distintas coexisten como registros independientes, conforme a NFR-007.
  - Consultar una `(comunidad, codigo)` inexistente devuelve un resultado que indica de forma explícita que no se encontró, conforme a REQ-008.
  - Dos escrituras concurrentes sobre la misma oferta dejan un único registro, equivalente a ejecutarlas en serie, conforme a ALT-005 y NFR-006.
  - El repositorio no escribe ni lee ninguna base de datos vectorial ni usa una extensión vectorial, conforme a NFR-005.
- **Prueba manual:**
  1. Persistir una oferta real con los campos que publica la ficha y consultarla: comprobar que los valores devueltos coinciden con los enviados y que los tres campos reservados vienen vacíos.

### [x] TASK-006 Listado por estado y lista de códigos vistos

- **Cubre:** REQ-009, REQ-016, REQ-015, SUP-010, SUP-011, DEC-003, ALT-005
- **Componente:** ofertas-repository | source/api/persistencia/repository.py
- **Módulo:** ofertas-repository
- **Depende de:** TASK-005
- **Alcance:** Implementar en el repositorio el listado de ofertas por estado (con el estado `vigente` como caso principal, usando el índice `(estado, fecha_fin_difusion)`) y la consulta de la lista de códigos vistos de una comunidad, que devuelve tanto los códigos importados desde `data/seen_codes.json` como los procedentes de fichas completas ingeridas.
- **Hecho cuando:** el listado de ofertas vigentes devuelve solo registros con estado `vigente` e incluye al menos comunidad, provincia, código, ocupación, municipio y fechas de difusión; la lista de códigos vistos de una comunidad devuelve todos sus códigos sin duplicados, y la consulta por código no presente en la lista identifica la oferta como nueva.
- **Pruebas automáticas:**
  - Con ofertas en estado `vigente`, `cerrada` y `sin_ficha`, el listado de vigentes devuelve solo las `vigente`, conforme a REQ-009.
  - Cada elemento del listado incluye comunidad, provincia, código, ocupación, municipio, fecha de inicio y fecha de fin de difusión.
  - La lista de códigos vistos de Cantabria devuelve la unión de los códigos importados sin ficha y los de fichas ingeridas, sin duplicados, conforme a REQ-016.
  - Un código presente en la lista de vistos no se considera oferta nueva y uno ausente sí, conforme al criterio de REQ-016.
  - La lista de códigos vistos de otra comunidad no incluye los de Cantabria, conforme a NFR-007.
  - El listado ordena por fecha de fin de difusión usando el índice existente y no escanea la tabla completa de forma incontrolada.
- **Prueba manual:**
  1. Con ofertas vigentes, cerradas y sin ficha en la base de datos, listar las vigentes y comprobar que solo aparecen las vigentes con los campos mínimos exigidos.

### [x] TASK-007 Reducción a registro mínimo conservando el embedding

- **Cubre:** REQ-005, REQ-006, NFR-005, SUP-004, SUP-006, DEC-002, DEC-007, ALT-006
- **Componente:** ofertas-repository | source/api/persistencia/repository.py
- **Módulo:** ofertas-repository
- **Depende de:** TASK-005
- **Alcance:** Implementar en el repositorio la operación que reduce una oferta al registro mínimo: vaciar `texto_libre` y `contacto` y conservar el resto de campos, incluido el embedding con su nombre, versión y dimensión, sin tocar `interesada` ni las fechas de alta, cierre y actualización.
- **Hecho cuando:** tras la reducción, `texto_libre` y `contacto` están vacíos y siguen presentes comunidad, provincia, código, ocupación, municipio, `sector`, `nivel`, `contrato`, fechas de difusión, estado, embedding, `embedding_model_name`, `embedding_model_version` y `embedding_dim`.
- **Pruebas automáticas:**
  - Una oferta con texto y contacto, tras la reducción, tiene ambos campos vacíos y el resto de campos intactos, conforme a REQ-006.
  - Una oferta con embedding conserva el BLOB, el nombre del modelo, la versión y `embedding_dim` tras la reducción, conforme a REQ-005 y DEC-002.
  - Una oferta sin embedding sigue siendo válida tras la reducción y su embedding permanece nulo.
  - `estado`, `interesada`, `fecha_alta` y `fecha_cierre` no se modifican por la reducción.
  - Los tres campos `sector`, `nivel` y `contrato` siguen presentes y vacíos tras la reducción, conforme a DEC-009 y SUP-011.
  - La reducción es idempotente: aplicarla dos veces produce el mismo resultado.
- **Prueba manual:**
  1. Reducir una oferta con embedding y consultar el registro: comprobar que no quedan texto ni contacto y que el embedding sigue disponible con sus metadatos.

### [x] TASK-008 Importador idempotente de `data/seen_codes.json`

- **Cubre:** REQ-013, REQ-014, REQ-015, REQ-018, NFR-003, SUP-011, SUP-013, DEC-006, ALT-003
- **Componente:** seen-codes-importer | source/api/persistencia/importer.py
- **Módulo:** seen-codes-importer
- **Depende de:** TASK-006
- **Alcance:** Implementar el importador que lee `data/seen_codes.json` como lista plana de códigos de texto, y por cada código que no exista en la base de datos crea un registro con comunidad `Cantabria`, estado `sin_ficha` y el resto de campos vacíos (provincia, `sector`, `nivel`, `contrato`, fechas de difusión, `texto_libre`, `contacto` y embedding), sin modificar nunca el fichero de origen y sin escribir en él.
- **Hecho cuando:** la importación crea un registro por cada código del JSON que aún no exista, deja constancia del número de códigos importados, y al repetirla con el mismo JSON no crea duplicados e informa de cero importados; los códigos que no empiezan por `06` también se importan como comunidad `Cantabria`.
- **Pruebas automáticas:**
  - Con un JSON de 103 códigos, la importación crea 103 registros con esos códigos y con estado `sin_ficha`, conforme a REQ-013.
  - Cada registro importado tiene comunidad `Cantabria`, provincia vacía, `sector`, `nivel` y `contrato` vacíos, fechas de difusión vacías, `texto_libre` y `contacto` vacíos y embedding nulo, conforme a SUP-011.
  - Los códigos que no empiezan por `06` se importan igualmente con comunidad `Cantabria`, conforme a SUP-011.
  - El resultado de la importación informa del número de códigos importados y del número de códigos ya existentes, conforme a REQ-013.
  - Repetir la importación con el mismo JSON no crea filas nuevas y el contador de importados es cero, conforme a REQ-014.
  - Un JSON con un código nuevo entre dos importaciones crea únicamente el registro de ese código, conforme a REQ-014.
  - Los códigos se conservan como texto de 12 dígitos con sus ceros iniciales, conforme a NFR-003.
  - Un fichero `data/seen_codes.json` ausente se registra y la importación continúa sin fallar, conforme a ALT-003.
  - Un fichero con JSON inválido o que no es una lista se registra como error y la importación continúa sin modificar la base de datos, conforme a ALT-003.
  - El fichero `data/seen_codes.json` no se modifica ni se toca su marca de tiempo tras la importación, conforme a SUP-013 y REQ-018.
- **Prueba manual:**
  1. Ejecutar la importación con el `data/seen_codes.json` real y comprobar que la base de datos contiene un registro por código, todos en estado `sin_ficha`.
  2. Comprobar que el `data/seen_codes.json` sigue con el mismo contenido y la misma fecha de modificación.

### [x] TASK-009 Cliente HTTP de `GET /buscador/status`

- **Cubre:** REQ-017, REQ-018, ALT-001, ALT-002, SUP-014
- **Componente:** buscador-client | source/api/persistencia/client.py
- **Módulo:** buscador-client
- **Depende de:** TASK-002
- **Alcance:** Implementar el cliente HTTP que consulta `GET /buscador/status` en la URL base configurada y devuelve el resultado publicado en memoria: `in_progress`, `progreso` y `ultima_pasada` con `timestamp`, `comunidad`, `total_listado`, `error_global`, `errores_por_oferta` y `ofertas_nuevas`, distinguiendo de forma explícita los casos de error HTTP, fallo de red, `error_global` no vacío y `ultima_pasada` nula.
- **Hecho cuando:** el cliente devuelve el estado publicado por el buscador con la estructura real de `GET /buscador/status`, y ante un error HTTP o de red devuelve un error controlado sin lanzar excepción; nunca lanza peticiones de pasada ni de descarga de fichas.
- **Pruebas automáticas:**
  - Con un cliente de prueba que responde el cuerpo real de `GET /buscador/status`, el cliente devuelve `in_progress`, `progreso` y `ultima_pasada` con sus seis campos.
  - La URL solicitada es la URL base configurada más `/buscador/status`.
  - Con una respuesta que incluye `ultima_pasada` nula, el cliente lo comunica de forma distinguible, conforme a ALT-002.
  - Con una respuesta con `error_global` no vacío, el cliente lo comunica sin lanzar excepción, conforme a ALT-001.
  - Con un error HTTP o un fallo de red, el cliente devuelve un error controlado, conforme a ALT-001.
  - El cliente no solicita ningún otro endpoint del buscador: solo se emite una petición a `/buscador/status` por consulta.
  - El cliente no escribe en la base de datos ni modifica ningún fichero de `data/`.
- **Prueba manual:**
  1. Con la aplicación arrancada, consultar el cliente contra `http://localhost:8000` y comprobar que devuelve el mismo `ultima_pasada` que muestra `GET /buscador/status`.

### [x] TASK-010 Tarea periódica de ingesta de ofertas completas

- **Cubre:** REQ-017, REQ-018, REQ-001, REQ-002, REQ-003, REQ-015, NFR-006, SUP-014, SUP-015, DEC-003, DEC-005, DEC-008, ALT-001, ALT-002
- **Componente:** ingestion-task | source/api/persistencia/ingestion.py
- **Módulo:** ingestion-task
- **Depende de:** TASK-007, TASK-009
- **Alcance:** Implementar la tarea periódica que, en cada ciclo, consulta `GET /buscador/status` mediante el cliente, compara el `timestamp` de `ultima_pasada` con el último importado almacenado en `ingesta_log`, y solo cuando difiere envía cada oferta de `ofertas_nuevas` al repositorio para su persistencia antes de registrar ese `timestamp` como importado.
- **Hecho cuando:** con una pasada nueva, todas las ofertas de `ofertas_nuevas` quedan almacenadas con comunidad, provincia, código, ocupación, municipio, fechas de difusión, texto libre y contacto, con `sector`, `nivel` y `contrato` vacíos y estado `vigente`, y el `timestamp` de la pasada queda registrado en `ingesta_log`; con el mismo `timestamp` la tarea no hace nada; y ante `ultima_pasada` nula, `error_global` o buscador caído no se persiste nada ni se avanza el `timestamp`.
- **Pruebas automáticas:**
  - Con un `timestamp` nuevo y dos ofertas nuevas, la base de datos contiene ambas con todos los campos y con estado `vigente`, conforme a REQ-017.
  - Las ofertas ingeridas tienen `sector`, `nivel` y `contrato` vacíos, conforme a REQ-002 y DEC-009.
  - Repetir la ingesta con el mismo `timestamp` no duplica registros ni vuelve a marcar el resultado como importado, conforme a REQ-017.
  - Un código previamente importado desde `seen_codes.json` con estado `sin_ficha` aparece en `ofertas_nuevas`: el registro se completa con los datos de la ficha y su estado pasa a `vigente`, sin crear un duplicado, conforme a REQ-015.
  - Un código ya existente con estado `vigente` y datos completos no se duplica ni se sobrescribe con valores vacíos.
  - Con `ultima_pasada` nula no se persiste ninguna oferta y no se avanza el `timestamp` importado, conforme a ALT-002.
  - Con `error_global` no vacío no se persiste ninguna oferta y el estado consultado queda registrado en el log, conforme a ALT-001.
  - Con el buscador caído o con error HTTP no se persiste ninguna oferta y el estado consultado queda registrado en el log, conforme a ALT-001.
  - El `timestamp` importado se recupera de `ingesta_log` al reiniciar la aplicación, de modo que tras un reinicio no se reimporta una pasada ya importada.
  - El estado del `timestamp` importado queda en `ingesta_log` con su marca `actualizado_en`.
  - La tarea se programa con la cadencia configurada y se cancela sin dejar ejecuciones en curso.
- **Prueba manual:**
  1. Arrancar la aplicación con una pasada real del buscador y comprobar en la base de datos que las ofertas nuevas de la última pasada están almacenadas con estado `vigente`.
  2. Reiniciar la aplicación y comprobar que la pasada ya importada no vuelve a importarse.

### [x] TASK-011 Tarea periódica de purga por retención

- **Cubre:** REQ-005, REQ-006, REQ-003, SUP-004, DEC-002, DEC-007, DEC-008, ALT-006
- **Componente:** purge-task | source/api/persistencia/purge.py
- **Módulo:** purge-task
- **Depende de:** TASK-007
- **Alcance:** Implementar la tarea periódica que consulta las ofertas en estado `cerrada` cuya `fecha_cierre` supere los días de retención configurados y cuyo flag `interesada` sea `false`, y las reduce a registro mínimo mediante el repositorio, sin tocar el resto de campos ni el embedding.
- **Hecho cuando:** una oferta cerrada no marcada como interesada que supera el plazo queda con `texto_libre` y `contacto` vacíos y con el embedding conservado; una oferta dentro del plazo no se toca; una oferta con `interesada` en `true` se omite y conserva su texto y su contacto.
- **Pruebas automáticas:**
  - Una oferta cerrada cuya `fecha_cierre` es anterior al plazo configurado queda reducida a registro mínimo, conforme a REQ-006.
  - La oferta reducida conserva el embedding con su nombre, versión y dimensión, conforme a REQ-005 y DEC-002.
  - Una oferta cerrada cuya `fecha_cierre` está dentro del plazo no se modifica.
  - Una oferta cerrada con `interesada` en `true` se omite y conserva `texto_libre` y `contacto`, conforme a ALT-006.
  - Una oferta en estado `vigente` o `sin_ficha` nunca se purga aunque su fecha de cierre exista.
  - La tarea se programa con la frecuencia configurada y se cancela sin dejar ejecuciones en curso.
  - La purga no modifica la fila de `ingesta_log` ni el estado de las ofertas.
- **Prueba manual:**
  1. Cerrar una oferta, simular el paso del plazo de retención y ejecutar la purga: comprobar que desaparecen el texto y el contacto y que el embedding sigue disponible.

### [x] TASK-012 Endpoints de la API de persistencia

- **Cubre:** REQ-001, REQ-008, REQ-009, REQ-012, REQ-016, SUP-008, DEC-003
- **Componente:** persistencia-api | source/api/persistencia/routes.py
- **Módulo:** persistencia-api
- **Depende de:** TASK-006
- **Alcance:** Implementar los endpoints que exponen al resto de módulos las operaciones de lectura y escritura de ofertas: crear o actualizar una oferta, consultarla por comunidad y código, listar las ofertas vigentes y listar los códigos vistos de una comunidad, devolviendo estructuras de datos que incluyan los campos definidos en REQ-002 sin que el consumidor necesite ejecutar SQL.
- **Hecho cuando:** un cliente puede crear o actualizar una oferta, consultarla por `(comunidad, codigo)`, listar las vigentes y obtener los códigos vistos de una comunidad; una consulta de una oferta inexistente indica de forma explícita que no se encontró; y ningún endpoint exige credenciales.
- **Pruebas automáticas:**
  - El endpoint de creación o actualización devuelve la confirmación o el registro actualizado, conforme a REQ-012.
  - El endpoint de consulta devuelve todos los campos de REQ-002 más el estado, el embedding y sus metadatos, conforme a REQ-012 y REQ-008.
  - La consulta de una `(comunidad, codigo)` inexistente devuelve una respuesta que indica de forma explícita que no se encontró la oferta, conforme a REQ-008.
  - El listado de vigentes devuelve solo ofertas con estado `vigente`, conforme a REQ-009.
  - El listado de códigos vistos de una comunidad devuelve los códigos importados y los ingeridos, conforme a REQ-016.
  - Actualizar dos veces la misma oferta no crea una segunda fila, conforme a REQ-001.
  - Los endpoints no exigen cabeceras de autenticación ni devuelven 401 o 403, conforme a SUP-008.
  - Los endpoints funcionan sin que el consumidor ejecute SQL: la respuesta es JSON con los campos de la oferta.
- **Prueba manual:**
  1. Crear una oferta desde el endpoint, consultarla y comprobar que devuelve todos los campos guardados.
  2. Consultar una oferta inexistente y comprobar que la respuesta indica que no se encontró.

### [X] TASK-013 Arranque y apagado de la persistencia en la aplicación

- **Cubre:** REQ-010, REQ-011, REQ-013, REQ-017, REQ-018, NFR-001, NFR-002, SUP-001, SUP-015, DEC-001, DEC-004, DEC-005, DEC-006, DEC-008, ALT-003, ALT-004
- **Componente:** api-service | source/api
- **Módulo:** API
- **Depende de:** TASK-004, TASK-008, TASK-010, TASK-011, TASK-012
- **Alcance:** Integrar en el ciclo de vida de la aplicación FastAPI existente la carga de la configuración de persistencia, la apertura de la conexión con WAL, la aplicación de las migraciones, la importación inicial de `data/seen_codes.json` y el arranque de las tareas periódicas de ingesta y purga junto al planificador ya presente de `api-buscador`, de modo que todas las tareas conviven en el mismo proceso, y el apagado detenga primero las tareas de persistencia y después el planificador del buscador.
- **Hecho cuando:** al arrancar la aplicación la base de datos queda migrada a la versión esperada, `data/seen_codes.json` se ha importado y las tareas de ingesta y purga están activas junto al planificador del buscador; al apagar la aplicación la ingesta y la purga se cancelan sin dejar ejecuciones en curso y el planificador del buscador se detiene después; y un esquema en versión futura o un `seen_codes.json` corrupto no impiden el arranque de la API por el lado de la persistencia.
- **Pruebas automáticas:**
  - Tras arrancar la aplicación, la base de datos existe en la ruta configurada, `PRAGMA journal_mode` devuelve `wal` y `schema_version` refleja la versión esperada.
  - Tras arrancar la aplicación, `data/seen_codes.json` ha sido importado y la base de datos contiene los códigos con estado `sin_ficha`.
  - Tras arrancar la aplicación, están activas la tarea de ingesta, la tarea de purga y el planificador del buscador, conforme a la convivencia en el mismo proceso.
  - Al apagar la aplicación, la ingesta y la purga quedan canceladas y no se inician nuevas ejecuciones.
  - Al apagar, la cancelación de la ingesta y la purga ocurre antes de la detención del planificador del buscador.
  - Un `seen_codes.json` corrupto no impide el arranque de la API, conforme a ALT-003.
  - Un esquema en versión futura aborta el arranque con error explícito y no sobrescribe el fichero, conforme a ALT-004.
  - El arranque de la aplicación no altera el contenido de `data/seen_codes.json`, conforme a SUP-013.
  - Los endpoints existentes de `api-buscador` siguen respondiendo igual después de integrar la persistencia.
- **Prueba manual:**
  1. Arrancar la aplicación y comprobar que aparecen `data/job_emcan.db`, que la base de datos tiene las tablas esperadas y que la tarea de ingesta hace su primera consulta al buscador.
  2. Detener la aplicación y comprobar que no queda ninguna tarea de persistencia viva.

### [X] TASK-014 Verificación de integración de la persistencia

- **Cubre:** REQ-001, REQ-002, REQ-003, REQ-009, REQ-010, REQ-011, REQ-012, REQ-013, REQ-014, REQ-015, REQ-016, REQ-017, REQ-018, NFR-001, NFR-002, NFR-003, NFR-004, NFR-005, NFR-006, NFR-007, SUP-011, SUP-015, DEC-002, DEC-003, DEC-005, DEC-006, DEC-007, ALT-001, ALT-002, ALT-003, ALT-005, ALT-006
- **Componente:** api-service | source/api
- **Módulo:** API
- **Depende de:** TASK-013
- **Alcance:** Verificar de extremo a extremo la comunicación entre la aplicación, la conexión, el migrador, el repositorio, el importador, el cliente del buscador y las dos tareas periódicas, montando la aplicación con cliente de prueba, un `seen_codes.json` temporal y un `GET /buscador/status` simulado, y cubriendo los casos de pasada nueva, buscador caído, `ultima_pasada` nula, código ya importado y cierre con purga posterior.
- **Hecho cuando:** con una pasada simulada, la aplicación persiste las ofertas nuevas, expone la consulta y el listado por sus endpoints, la segunda ingesta del mismo `timestamp` no duplica, el `seen_codes.json` queda intacto y, tras cerrar una oferta y vencer el plazo, la purga la reduce conservando el embedding, sin excepciones no controladas.
- **Pruebas automáticas:**
  - Con un `seen_codes.json` de tres códigos y una pasada simulada que publica una de esos códigos más otra nueva, la base de datos contiene los cuatro códigos: tres en `sin_ficha` y uno en `vigente` con la ficha completa, conforme a REQ-013, REQ-015 y REQ-017.
  - El endpoint de consulta por `(comunidad, codigo)` devuelve la ficha completa con los campos de REQ-002 y `sector`, `nivel` y `contrato` vacíos.
  - El endpoint de listado de vigentes devuelve solo las ofertas en estado `vigente`, conforme a REQ-009.
  - El endpoint de códigos vistos devuelve los cuatro códigos, conforme a REQ-016.
  - Repetir la ingesta con el mismo `timestamp` no crea filas nuevas, conforme a REQ-014.
  - Con el buscador caído y con `ultima_pasada` nula, la base de datos no cambia, conforme a ALT-001 y ALT-002.
  - Tras cerrar una oferta y simular el vencimiento del plazo, la purga vacía texto y contacto y conserva el embedding, conforme a REQ-006 y ALT-006.
  - Tras la integración, `data/seen_codes.json` conserva su contenido original, conforme a REQ-018.
  - Los códigos se leen con sus ceros iniciales y las fechas en `dd/mm/aaaa`, conforme a NFR-003 y NFR-004.
  - La base de datos es un único fichero SQLite en modo `wal` sin servidor de base de datos ni tabla vectorial, conforme a NFR-001, NFR-002 y NFR-005.
- **Prueba manual:**
  1. Ejecutar la prueba de integración y revisar el informe: todos los escenarios salen con el resultado esperado.
  2. Revisar el directorio `data/` tras la prueba: solo existe el fichero SQLite único y el `seen_codes.json` sin cambios.

### [x] TASK-015 Contrato: openapi - operaciones de persistencia

- **Cubre:** REQ-001, REQ-008, REQ-009, REQ-012, REQ-016, SUP-008, DEC-002, DEC-003
- **Componente:** persistencia-api | source/api/persistencia/routes.py
- **Módulo:** persistencia-api
- **Depende de:** TASK-012, TASK-014
- **Alcance:** Crear el contrato OpenAPI `docs/contracts/openapi/api-persistencia.yaml` que formaliza las operaciones de persistencia expuestas al resto de módulos tal como quedaron implementadas: crear o actualizar oferta, consultar por comunidad y código, listar ofertas vigentes y listar códigos vistos, con el esquema de oferta que incluye los campos de REQ-002 más estado, embedding con nombre, versión y dimensión, y las respuestas de error por oferta no encontrada.
- **Hecho cuando:** el contrato existe en `docs/contracts/openapi/api-persistencia.yaml`, describe las cuatro operaciones con sus esquemas de entrada y salida, recoge la respuesta de oferta no encontrada exigida por REQ-008, y coincide con la implementación verificada en TASK-014.
- **Pruebas automáticas:**
  - El YAML del contrato se carga correctamente y contiene las cuatro operaciones con sus respuestas 200 y 404 de oferta no encontrada.
  - El esquema de oferta del contrato incluye comunidad, provincia, código, ocupación, municipio, `sector`, `nivel`, `contrato`, fechas de difusión, estado, texto libre, contacto, `embedding`, `embedding_model_name`, `embedding_model_version` y `embedding_dim`.
  - El esquema del contrato describe el embedding como BLOB binario y `embedding_dim` como entero, conforme a DEC-002.
  - El contrato documenta que los códigos se devuelven como texto de 12 dígitos y las fechas de difusión en `dd/mm/aaaa`.
  - Las rutas y los nombres de campo del contrato coinciden con los que devuelve la implementación en la prueba de integración.
- **Prueba manual:**
  1. Revisar el contrato y comprobar que aparecen las cuatro interfaces de la fila de contratos afectados.
  2. Comparar el contrato con las respuestas JSON reales obtenidas en TASK-014 y confirmar que no hay campos divergentes.

### [x] TASK-016 Contrato: configuración - fichero de configuración de la persistencia

- **Cubre:** REQ-011, REQ-018, NFR-001, SUP-001, SUP-015, DEC-001, DEC-005, DEC-006
- **Componente:** config-persistencia | config/persistencia.yaml
- **Módulo:** config-persistencia
- **Depende de:** TASK-002, TASK-013
- **Alcance:** Formalizar el contrato de configuración de la persistencia: documentar el formato exacto del fichero `config/persistencia.yaml` (ruta de la base de datos, URL base del buscador, cadencia de ingesta, días de retención y frecuencia de purga) y sus valores por defecto, dejándolo alineado con lo que la carga de TASK-002 interpreta y con lo que la aplicación de TASK-013 aplica.
- **Hecho cuando:** el formato queda documentado, el fichero real lo cumple sin ambigüedad y una configuración válida se carga y se aplica sin cambios de código.
- **Pruebas automáticas:**
  - El fichero `config/persistencia.yaml` se carga con el formato documentado y devuelve la ruta, la URL base, la cadencia, la retención y la frecuencia.
  - Una configuración sin los campos obligatorios se rechaza con un error controlado que identifica el campo ausente.
  - Una configuración con un tipo incorrecto se rechaza con un error controlado.
  - Los valores por defecto documentados (ruta `data/job_emcan.db`, URL `http://localhost:8000`, cadencia 300 s, retención 7 días, frecuencia 86400 s) coinciden con los que aplica la implementación.
  - El contrato no documenta ninguna ruta de servidor de base de datos ni credenciales, conforme a NFR-001.
- **Prueba manual:**
  1. Revisar que la fila de contrato (configuración de la persistencia) queda descrita con el mismo formato que usa el fichero real.
  2. Modificar el fichero siguiendo solo el formato documentado y comprobar que la aplicación arranca con la nueva configuración.

### [X] TASK-017 Actualización del mapa de arquitectura

- **Cubre:** DEC-001, DEC-002, DEC-003, DEC-004, DEC-005, DEC-006, DEC-007, DEC-008
- **Componente:** api-service | source/api
- **Módulo:** API
- **Depende de:** TASK-014, TASK-015, TASK-016
- **Alcance:** Registrar en `.sdd/architecture.md` los módulos nuevos de persistencia, el contrato OpenAPI de persistencia y el contrato de configuración, y actualizar la descripción del módulo `API` para que incluya también la persistencia de ofertas, con los identificadores y rutas definitivos realmente implementados.
- **Hecho cuando:** el mapa contiene una entrada por cada módulo nuevo implementado con su identificador, ruta, responsabilidad y dependencias, la entrada del contrato OpenAPI de persistencia y la del contrato de configuración, y el módulo `API` actualizado con las rutas reales del repositorio.
- **Pruebas automáticas:**
  - Una comprobación lee `.sdd/architecture.md` y confirma que aparecen los identificadores de todos los módulos nuevos de persistencia con una ruta no vacía.
  - Una comprobación confirma que la sección de contratos incluye el OpenAPI de persistencia y el contrato de configuración de la persistencia.
  - Una comprobación confirma que la descripción del módulo `API` ya no se limita al parseo de PDFs y al rastreador del buscador.
  - Todos los ficheros citados en el mapa existen en el repositorio.
- **Prueba manual:**
  1. Revisar `.sdd/architecture.md` y comprobar que cada módulo nuevo de persistencia tiene su identificador, su ruta y sus dependencias, y que las rutas coinciden con los ficheros realmente creados.

## Cobertura

| Requisito | Tareas |
|---|---|
| REQ-001 | TASK-005, TASK-010, TASK-012, TASK-014, TASK-015 |
| REQ-002 | TASK-005, TASK-010, TASK-012, TASK-014 |
| REQ-003 | TASK-005, TASK-010, TASK-011, TASK-014 |
| REQ-004 | TASK-005 |
| REQ-005 | TASK-007, TASK-011, TASK-014 |
| REQ-006 | TASK-007, TASK-011, TASK-014 |
| REQ-007 | TASK-004, TASK-005 |
| REQ-008 | TASK-005, TASK-012, TASK-014, TASK-015 |
| REQ-009 | TASK-006, TASK-012, TASK-014, TASK-015 |
| REQ-010 | TASK-003, TASK-004, TASK-013, TASK-014 |
| REQ-011 | TASK-002, TASK-003, TASK-013, TASK-014, TASK-016 |
| REQ-012 | TASK-012, TASK-014, TASK-015 |
| REQ-013 | TASK-008, TASK-013, TASK-014 |
| REQ-014 | TASK-008, TASK-014 |
| REQ-015 | TASK-006, TASK-008, TASK-010, TASK-014 |
| REQ-016 | TASK-006, TASK-012, TASK-014, TASK-015 |
| REQ-017 | TASK-009, TASK-010, TASK-013, TASK-014 |
| REQ-018 | TASK-002, TASK-008, TASK-009, TASK-010, TASK-013, TASK-014, TASK-016 |

| Requisito no funcional | Tareas |
|---|---|
| NFR-001 | TASK-001, TASK-002, TASK-003, TASK-013, TASK-014, TASK-016 |
| NFR-002 | TASK-003, TASK-013, TASK-014 |
| NFR-003 | TASK-005, TASK-008, TASK-014 |
| NFR-004 | TASK-005, TASK-014 |
| NFR-005 | TASK-001, TASK-004, TASK-005, TASK-007, TASK-014 |
| NFR-006 | TASK-003, TASK-005, TASK-010, TASK-014 |
| NFR-007 | TASK-004, TASK-005, TASK-006 |

| Decisión | Tareas |
|---|---|
| DEC-001 | TASK-001, TASK-002, TASK-003, TASK-013, TASK-016, TASK-017 |
| DEC-002 | TASK-001, TASK-004, TASK-005, TASK-007, TASK-011, TASK-014, TASK-015, TASK-017 |
| DEC-003 | TASK-004, TASK-005, TASK-006, TASK-010, TASK-014, TASK-015, TASK-017 |
| DEC-004 | TASK-004, TASK-013, TASK-017 |
| DEC-005 | TASK-009, TASK-010, TASK-013, TASK-016, TASK-017 |
| DEC-006 | TASK-008, TASK-013, TASK-016, TASK-017 |
| DEC-007 | TASK-004, TASK-007, TASK-011, TASK-014, TASK-017 |
| DEC-008 | TASK-003, TASK-004, TASK-005, TASK-010, TASK-011, TASK-013, TASK-017 |

| Supuesto | Tareas |
|---|---|
| SUP-001 | TASK-002, TASK-013, TASK-016 |
| SUP-002 | TASK-004, TASK-005 |
| SUP-003 | TASK-004 |
| SUP-004 | TASK-007, TASK-011 |
| SUP-005 | TASK-004, TASK-005 |
| SUP-006 | TASK-005, TASK-007 |
| SUP-007 | TASK-005 |
| SUP-008 | TASK-012, TASK-015 |
| SUP-009 | TASK-005, TASK-006 |
| SUP-010 | TASK-004, TASK-006 |
| SUP-011 | TASK-005, TASK-006, TASK-007, TASK-008, TASK-014 |
| SUP-012 | TASK-004, TASK-005 (SUP-012 descartado: no genera trabajo; el esquema usa solo `estado`) |
| SUP-013 | TASK-008, TASK-013, TASK-014 |
| SUP-014 | TASK-009, TASK-010 |
| SUP-015 | TASK-002, TASK-010, TASK-013, TASK-014, TASK-016 |

| Escenario alternativo | Tareas |
|---|---|
| ALT-001 | TASK-009, TASK-010, TASK-014 |
| ALT-002 | TASK-009, TASK-010, TASK-014 |
| ALT-003 | TASK-008, TASK-013, TASK-014 |
| ALT-004 | TASK-003, TASK-004, TASK-013 |
| ALT-005 | TASK-003, TASK-005, TASK-006, TASK-014 |
| ALT-006 | TASK-007, TASK-011, TASK-014 |

## Avisos

- La estrategia de contratos aplicada es `implementation-first`, valor tomado de la opción `contract-strategy` de `.sdd/team.md`. Por eso TASK-015 depende de TASK-012 y TASK-014, y TASK-016 depende de TASK-002 y TASK-013.
- Los módulos `api-persistencia`, `config-persistencia`, `db-connection`, `schema-migrator`, `ofertas-repository`, `seen-codes-importer`, `buscador-client`, `ingestion-task`, `purge-task` y `persistencia-api` **no existen todavía en `.sdd/architecture.md`**; sus identificadores y rutas proceden de la tabla "Cambios sugeridos al mapa" del diseño. Las tareas que los implementan llevan su `Componente` con la ruta propuesta en el diseño y su línea `Módulo` con el identificador del mapa; TASK-017 es la que fija las rutas definitivas y registra las entradas. Hoy solo constan en el mapa `API` y `CONFIG-MAP`.
- El diseño deja el mecanismo concreto del planificador en proceso sin fixar (biblioteca o temporizador propio). TASK-010 y TASK-011 se limitan al comportamiento exigible: ejecución periódica con la cadencia y la frecuencia configuradas, cancelación limpia al apagar y no solapamiento entre la ingesta y la purga sobre el mismo conjunto de ofertas. La elección técnica queda para el analista.
- El diseño no fija la semántica exacta del estado HTTP para "oferta no encontrada" en el endpoint de consulta. Se adopta por defecto `404` con cuerpo de error, en coherencia con el estilo de la aplicación existente (`HTTPException`); si la capa técnica prefiere `200` con resultado vacío, el cambio queda limitado a TASK-012, TASK-014 y TASK-015.
- El diseño no fija el prefijo de las rutas de la API de persistencia. Se adopta por defecto el prefijo `/persistencia`; si la capa técnica adopta otro, el cambio queda limitado a TASK-012, TASK-014 y TASK-015.
- La tabla `ingesta_log` del diseño tiene columna `id INTEGER PRIMARY KEY` y se usa para conservar el último `timestamp` importado. TASK-010 la usa como almacenamiento del estado de la ingesta y TASK-013 comprueba su recuperación tras un reinicio; la unicidad del registro no está especificada en el diseño y queda para el analista.
- La convivencia con el planificador diario de `api-buscador` en el mismo proceso FastAPI se refleja en TASK-013: la aplicación ya existente (`source/api/main.py`) mantiene su `lifespan` y el `app_state`; las tareas de persistencia se añaden ahí sin alterar el comportamiento de `api-buscador` ni sus endpoints. En el apagado, la ingesta y la purga se cancelan antes que el planificador del buscador.
- `api-buscador` no se modifica en ninguna tarea. La compatibilidad se resuelve solo desde `api-persistencia`, leyendo `data/seen_codes.json` (TASK-008) y consultando `GET /buscador/status` (TASK-009, TASK-010), conforme a SUP-013.
- El campo `interesada` es un booleano reservado para `api-candidaturas` con valor por defecto `0`; no debe confundirse con los estados de candidatura (`me interesa`, `inscrito`, `entrevista`, `descartada`), que no se almacenan en este esquema (SUP-009).
- No existe `.sdd/task-types.md`, así que no hay tipos de tarea propios del proyecto que generar.
- El documento contiene 17 tareas (TASK-001..TASK-017). Las referencias a `DEC-009` en TASK-007 y TASK-010 son citas cruzadas a la decisión de `api-buscador` (y al contrato HTML) sobre dejar `sector`, `nivel` y `contrato` vacíos; no es una decisión de esta feature, cuyo rango propio es DEC-001..DEC-008. `SUP-009` se cita en la tabla de cobertura solo como delimitación de alcance: los estados de candidatura siguen reservados para `api-candidaturas`.
- La tabla de cobertura refleja exactamente las líneas `Cubre:` de cada tarea. `SUP-012` aparece ahí solo como constancia de que está descartado y no origina trabajo; la distinción entre código visto y oferta con ficha se hace solo con el campo `estado`, conforme a DEC-003.
