# Tareas: api-perfil

Estado: aprobado
Revisión: 1
Basado en: requirements@2, design@3
Verificación: correcta

## Resumen

El trabajo se divide en dieciocho tareas (TASK-001..TASK-018) que siguen la cadena de dependencias del diseño: primero la estructura del paquete y la configuración, después la conexión SQLite propia por operación (WAL, `busy_timeout`, `foreign_keys`) y el migrador del esquema propio del perfil con su modo degradado, luego los modelos y DTOs, el normalizador de listas, el validador y el repositorio, a continuación la integración en el ciclo de vida de la aplicación FastAPI, los seis endpoints bajo `/perfil`, la verificación de integración, las dos tareas de contrato (`implementation-first`), la verificación transversal de aislamiento, UTF-8, `AUTOINCREMENT`, claves foráneas y rendimiento, y por último la actualización del mapa de arquitectura. Cada tarea de implementación incluye sus propias pruebas; solo la verificación de extremo a extremo se separa como tarea de integración.

Los componentes del perfil son detalle de implementación interno del módulo `API` y no reciben identificador propio en el mapa de arquitectura: todas las tareas llevan su línea `Módulo` con el identificador `APP`, aunque el código viva en `source/api/perfil/`. La actualización del mapa (TASK-018) se limita a la línea del módulo `API` y a los dos contratos nuevos.

`api-perfil` no modifica `api-buscador`, `api-persistencia`, `api-pdf-parser`, `api-historico`, `api-integridad` ni `api-listado`: el perfil vive en un segundo fichero SQLite propio (`data/job_emcan_perfil.db`) con su propio migrador (`schema_version_perfil`), su propia conexión por operación y su propio `busy_timeout`, sin tocar `data/job_emcan.db` ni la tabla `schema_version` de `api-persistencia`.

## Orden de implementación

1. TASK-001 Estructura del paquete y dependencias → TASK-002 Configuración del perfil.
2. TASK-003 Conexión SQLite por operación → TASK-004 Migrador propio y modo degradado.
3. TASK-005 Modelos y DTOs del perfil → TASK-006 Normalizador de listas → TASK-007 Validador del perfil.
4. TASK-008 Repositorio de versiones y puntero de activa.
5. TASK-009 Arranque y apagado del perfil en la aplicación.
6. TASK-010 Endpoints de consulta → TASK-011 Endpoint de guardado → TASK-012 Endpoint de rollback → TASK-013 Endpoint de validación previa.
7. TASK-014 Verificación de integración.
8. TASK-015..TASK-016 Contratos (implementation-first).
9. TASK-017 Verificación transversal → TASK-018 Actualización del mapa (descripción del módulo `API` y dos contratos).

## Tareas

### [ ] TASK-001 Estructura del paquete del perfil y dependencias

- **Cubre:** REQ-001, REQ-004, REQ-005, REQ-007, SUP-A, SUP-D, DEC-001, DEC-002
- **Componente:** api-perfil | source/api/perfil
- **Módulo:** APP
- **Depende de:** -
- **Alcance:** Crear el subpaquete `source/api/perfil/` con su `__init__.py` y los módulos hosting de los componentes del diseño (`config.py`, `connection.py`, `migrations.py`, `models.py`, `normalizer.py`, `validator.py`, `repository.py`, `routes.py`), y declarar en `pyproject.toml` las dependencias que exige el diseño (`pyyaml` para la carga de `config/perfil.yaml`; SQLite y la librería estándar de Unicode para `NFD`/`casefold`, sin dependencias adicionales), sin introducir motor de base de datos servidor, ni extensión vectorial, ni motor de búsqueda de texto.
- **Hecho cuando:** el subpaquete `source/api/perfil` se importa sin errores, las dependencias declaradas cubren las que usa el diseño y el runner de pruebas recorre `tests/` sin fallos de colección; y el paquete no referencia ni importa `api-buscador`, `api-persistencia`, `api-pdf-parser`, `api-historico`, `api-integridad` ni `api-listado` de forma que los modifique.
- **Pruebas automáticas:**
  - La suite arranca sin errores de importación de `source.api.perfil` ni de las dependencias declaradas.
  - Una comprobación confirma que `yaml` está disponible en el entorno de pruebas.
  - El paquete no importa ni referencia un motor de base de datos servidor (SQLAlchemy, PostgreSQL, MySQL), ni una extensión de SQLite para vectores, ni el módulo `sqlite3` con FTS5 habilitado, conforme a DEC-001.
  - El paquete no escribe ni modifica ficheros bajo `source/api/buscador/`, `source/api/persistencia/`, `source/api/historico/`, `source/api/integridad/`, `source/api/listado/`, `source/api/parser.py`, `source/api/downloader.py` ni `source/api/assembler.py`.
  - El paquete no crea ni abre ningún fichero SQLite en el momento de importarse, conforme a DEC-001.
- **Prueba manual:**
  1. Instalar el proyecto en un entorno virtual limpio y ejecutar la suite de pruebas: termina sin fallos por dependencias ausentes.

### [ ] TASK-002 Fichero de configuración del perfil

- **Cubre:** REQ-019, REQ-027, NFR-001, NFR-005, SUP-A, DEC-001
- **Componente:** config-perfil | config/perfil.yaml
- **Módulo:** APP
- **Depende de:** TASK-001
- **Alcance:** Crear el fichero de configuración `config/perfil.yaml` con la ruta del fichero SQLite propio del perfil (por defecto `data/job_emcan_perfil.db`), el tiempo de espera de escritura `busy_timeout_ms` (por defecto `5000`) y los límites de validación: longitud máxima de cada entrada de lista (por defecto `200`), número máximo de elementos por lista (por defecto `100`), longitud máxima del texto de `criterios` (por defecto `5000`) y tamaño máximo del payload en bytes (por defecto `1048576`, 1 MB); e implementar su carga con valores por defecto y error controlado ante fichero ausente o malformado. La ruta se resuelve relativa a la raíz del proyecto.
- **Hecho cuando:** la carga devuelve la configuración completa con los valores por defecto del diseño cuando no se indican otros, un fichero ausente o malformado produce un error controlado que identifica la configuración como origen, los cinco límites son enteros positivos y la ruta es relativa a la raíz del proyecto.
- **Pruebas automáticas:**
  - La carga del fichero `config/perfil.yaml` devuelve la ruta del SQLite propio, el `busy_timeout` y los cuatro límites de validación.
  - Sin fichero de configuración, la ruta es `data/job_emcan_perfil.db`, el `busy_timeout` es `5000` ms, la longitud máxima de elemento es `200`, el máximo de elementos por lista es `100`, la longitud máxima de `criterios` es `5000` y el tamaño máximo de payload es `1048576` bytes, conforme a NFR-005 y DEC-001.
  - Un fichero con YAML malformado, con una raíz que no es un mapa o con un campo de tipo incorrecto produce un error controlado que identifica el campo problemático.
  - Un límite que no es entero positivo, o un `busy_timeout` negativo o no entero, se rechaza con un error controlado que lo identifica, conforme a NFR-001.
  - La configuración no contiene ninguna ruta de servidor de base de datos ni credenciales.
- **Prueba manual:**
  1. Abrir `config/perfil.yaml` y comprobar que contiene los seis campos con sus valores por defecto.
  2. Cambiar el límite de longitud de elemento a `150`, recargar la configuración y comprobar que el nuevo valor es el que se aplica.

### [ ] TASK-003 Conexión SQLite por operación del perfil

- **Cubre:** REQ-024, REQ-025, NFR-002, NFR-003, SUP-A, DEC-001, DEC-009, ALT-012
- **Componente:** db-connection-perfil | source/api/perfil/connection.py
- **Módulo:** APP
- **Depende de:** TASK-002
- **Alcance:** Implementar el componente que, para **cada operación** del repositorio, abre una conexión SQLite nueva al fichero propio del perfil configurado, crea el directorio padre si falta, activa `PRAGMA journal_mode = WAL`, configura `PRAGMA busy_timeout` con el valor de la configuración y `PRAGMA foreign_keys = ON`, ofrece el contexto de escritura con `BEGIN IMMEDIATE` (adquiriendo el bloqueo de escritura antes de leer la versión activa) y cierra la conexión al terminar. No se mantiene ninguna conexión persistente compartida entre hilos ni se abre conexión sobre la ruta del SQLite de `api-persistencia`.
- **Hecho cuando:** tras una operación, el fichero `data/job_emcan_perfil.db` existe en modo `wal`, `busy_timeout` y `foreign_keys` quedan establecidos en cada conexión, el contexto de escritura usa `BEGIN IMMEDIATE` y confirma o deshace, y la conexión queda cerrada al terminar; y el fichero `data/job_emcan.db` no se ha creado ni modificado por este componente.
- **Pruebas automáticas:**
  - Con una ruta temporal inexistente, la operación crea el directorio y el fichero SQLite propio, conforme a DEC-001.
  - `PRAGMA journal_mode` devuelve `wal` tras la operación y `PRAGMA busy_timeout` devuelve el valor configurado, conforme a DEC-009.
  - `PRAGMA foreign_keys` devuelve un valor distinto de cero en la conexión usada por el repositorio, conforme a DEC-001.
  - Una escritura confirmada deja los cambios persistidos y una escritura deshecha no los deja, conforme a NFR-002.
  - Tras cada operación no queda ninguna conexión abierta sobre el fichero, conforme a DEC-009.
  - El componente no abre ninguna conexión de escritura sobre la ruta del SQLite de `api-persistencia` y no altera su marca de modificación, conforme a SUP-A.
  - Dos escritores concurrentes sobre el mismo fichero no producen errores `SQLITE_BUSY` no controlados ni datos corruptos, conforme a ALT-012.
  - No se abre ninguna conexión de red ni se requiere ningún servidor de base de datos.
- **Prueba manual:**
  1. Arrancar con la configuración por defecto y comprobar que aparece `data/job_emcan_perfil.db` con WAL activo y que `data/job_emcan.db` conserva su marca de modificación.

### [ ] TASK-004 Migrador propio del perfil y modo degradado

- **Cubre:** REQ-020, REQ-024, REQ-025, NFR-007, SUP-A, DEC-001, DEC-008, ALT-011
- **Componente:** schema-migrator-perfil | source/api/perfil/migrations.py
- **Módulo:** APP
- **Depende de:** TASK-003
- **Alcance:** Implementar el migrador que crea y mantiene su propia tabla de versión `schema_version_perfil` (`version INTEGER PRIMARY KEY`, `applied_at TEXT`), aplica migraciones numeradas secuenciales y transaccionales sobre el SQLite propio, y crea el esquema inicial con las tablas `perfil_version` (`version INTEGER PRIMARY KEY AUTOINCREMENT`, `contenido TEXT NOT NULL`, `creado_en TEXT NOT NULL`) y `perfil_activo` (`id INTEGER PRIMARY KEY CHECK (id = 1)`, `version INTEGER NOT NULL` con `FOREIGN KEY` a `perfil_version(version)`), y que detecta una versión de esquema superior a la esperada, un fichero que no es un SQLite válido o un fichero que no se puede abrir. En esos casos comunica un error controlado para que la aplicación marque el perfil como no disponible y los endpoints respondan 503, sin sobrescribir el fichero ni abortar el arranque del resto de la API.
- **Hecho cuando:** sobre un fichero recién creado existen las tres tablas con las columnas y restricciones del esquema conceptual, la tabla `schema_version_perfil` refleja la versión aplicada; un fichero ya migrado no reejecuta migraciones; un fichero en versión futura, corrupto o no abrible produce un error controlado que marca el perfil como no disponible sin modificar el fichero; y el esquema propio no contiene ninguna tabla de ofertas.
- **Pruebas automáticas:**
  - Tras migrar desde cero existen las tablas `schema_version_perfil`, `perfil_version` y `perfil_activo` con sus columnas, conforme a DEC-001.
  - `perfil_version.version` es `INTEGER PRIMARY KEY AUTOINCREMENT`: insertando dos versiones y borrando la de número mayor, la siguiente versión insertada no reutiliza el número borrado, conforme a DEC-010.
  - `perfil_activo` tiene `CHECK (id = 1)`: insertar una fila con `id` distinto de `1` es rechazado por SQLite, conforme a DEC-003.
  - Con `PRAGMA foreign_keys = ON`, insertar en `perfil_activo` una `version` inexistente en `perfil_version` es rechazado por SQLite, conforme a DEC-001.
  - La tabla `schema_version_perfil` contiene la versión esperada con su `applied_at`, y no existe ninguna tabla `schema_version` en el fichero propio del perfil, conforme a SUP-A.
  - Ninguna tabla propia del perfil contiene una columna de oferta ni duplica la tabla `ofertas` de `api-persistencia`, conforme a SUP-A y REQ-023.
  - Al migrar un fichero ya en la versión esperada no se ejecuta ninguna migración nueva y la versión no cambia.
  - Un fichero con versión superior a la esperada produce un error controlado y no modifica el fichero, conforme a ALT-011.
  - Un fichero que no es un SQLite válido o que no se puede abrir produce un error controlado y no se sobrescribe, conforme a ALT-011 y NFR-007.
  - Una migración que falla deja el esquema en el estado anterior y la transacción se deshace, conforme a NFR-002.
- **Prueba manual:**
  1. Migrar un fichero desde cero y revisar el esquema resultante con una herramienta de inspección de SQLite: tablas, columnas, `AUTOINCREMENT`, `CHECK` y clave foránea.
  2. Arrancar dos veces seguidas y comprobar que la segunda vez no se reejecuta ninguna migración.

### [ ] TASK-005 Modelos y DTOs del perfil

- **Cubre:** REQ-004, REQ-005, REQ-006, REQ-007, REQ-008, REQ-009, REQ-010, REQ-021, SUP-D, DEC-002
- **Componente:** perfil-models | source/api/perfil/models.py
- **Módulo:** APP
- **Depende de:** TASK-001
- **Alcance:** Implementar los modelos y DTOs del perfil: el valor de contenido con las seis listas de texto (`sectores`, `municipios`, `provincias`, `contrato`, `jornada`, `palabras_clave`) y el texto libre `criterios`; el DTO de versión con su número, marca temporal de creación y contenido; el DTO de entrada del historial con número, `creado_en` y marca de activa; los DTO de respuesta de las operaciones de consulta, guardado, rollback y validación previa; y el modelo de error común con `codigo`, `mensaje` y `detalles`. La serialización del contenido usa JSON con `ensure_ascii=False` y, al leer, las claves ausentes se tratan como lista vacía (campos de lista) o cadena vacía (`criterios`).
- **Hecho cuando:** el contenido serializado conserva tildes, eñes y caracteres Unicode sin escapes, las claves ausentes se leen como lista vacía o cadena vacía, y los DTOs de respuesta exponen exactamente los campos que fija el diseño para cada operación.
- **Pruebas automáticas:**
  - Serializar un perfil con "Técnico", "Santander" y "Preferencia por teletrabajo" produce JSON con esos caracteres sin escapes Unicode, conforme a NFR-004 y DEC-002.
  - Leer un contenido con las claves ausentes devuelve listas vacías para los campos de lista y cadena vacía para `criterios`, conforme a DEC-002.
  - El DTO de historial expone `version`, `creado_en` y `activa`, conforme a REQ-009.
  - El DTO de versión expone `version`, `creado_en` y el contenido completo, conforme a REQ-010.
  - El modelo de error común expone `codigo`, `mensaje` y `detalles`, con `detalles` nulo por defecto, conforme al modelo de error común del diseño.
  - El modelo de error de validación de contenido permite incluir la lista de campos con error, conforme a ALT-004.
- **Prueba manual:**
  1. Construir un contenido con tildes y eñes, serializarlo e inspeccionar el texto resultante: los caracteres aparecen sin escapes.

### [ ] TASK-006 Normalizador de listas del perfil

- **Cubre:** REQ-004, REQ-006, REQ-007, REQ-015, REQ-018, NFR-004, SUP-H, DEC-007
- **Componente:** perfil-normalizer | source/api/perfil/normalizer.py
- **Módulo:** APP
- **Depende de:** TASK-005
- **Alcance:** Implementar el normalizador de las seis listas de texto del perfil: aplica `trim` a cada entrada, descarta las entradas vacías o compuestas solo de espacios, y deduplica generando una clave de comparación con `NFD` → eliminación de los caracteres de categoría `Mn` → `casefold`, conservando **la primera forma escrita** que aparece en la lista. La normalización no modifica el texto libre `criterios` más allá del `trim` que exija el validador, y no altera la codificación de los caracteres Unicode válidos.
- **Hecho cuando:** una lista con entradas duplicadas que solo difieren en mayúsculas o tildes queda con una sola entrada que conserva la forma escrita de la primera aparición; las entradas vacías o de solo espacios se descartan; y los caracteres Unicode válidos, tildes y eñes se conservan tal cual en la forma conservada.
- **Pruebas automáticas:**
  - La lista `["Técnico", "tecnico"]` queda como `["Técnico"]`: una sola entrada que conserva la forma escrita de la primera, conforme a DEC-007 y REQ-018.
  - La lista `["Técnico", "TECNICO", "técnico"]` queda con una sola entrada, conforme a REQ-018.
  - La lista `["  Santander  ", "", "   "]` queda como `["Santander"]`, conforme a REQ-018 y SUP-H.
  - La entrada "Pymes" y la entrada "PYMES" se consideran duplicados por la clave de comparación, conforme a DEC-007.
  - La lista `["Málaga", "malaga"]` queda con una sola entrada que conserva la tilde de la forma escrita, conforme a DEC-007 y NFR-004.
  - La lista `["Año", "ano"]` queda con una sola entrada, conforme a DEC-007.
  - Una lista con entradas distintas que solo se diferencian en espacios interior se conserva con ambas entradas, conforme a SUP-H.
  - La normalización es estable: normalizar dos veces el resultado no lo altera, conforme a SUP-H.
  - El normalizador no descarta entradas que superen el límite de longitud: esa comprobación corresponde al validador, conforme a REQ-019.
- **Prueba manual:**
  1. Normalizar `["Técnico", "tecnico", "TÉCNICO", "  ", "Pymes", "pymes"]` y comprobar que quedan dos entradas con la forma escrita original de cada grupo.

### [ ] TASK-007 Validador del perfil

- **Cubre:** REQ-013, REQ-015, REQ-017, REQ-018, REQ-019, REQ-027, NFR-005, SUP-F, SUP-H, DEC-006, DEC-011, ALT-003, ALT-004, ALT-005
- **Componente:** perfil-validator | source/api/perfil/validator.py
- **Módulo:** APP
- **Depende de:** TASK-006
- **Alcance:** Implementar el validador del perfil: comprueba el contenido mínimo (al menos un campo estructurado no vacío o `criterios` no vacío), la longitud máxima de cada entrada de lista, el número máximo de elementos por lista, la longitud máxima de `criterios`, la ausencia de caracteres de control no permitidos, el rechazo de entradas que tras la normalización superen los límites, y la comparación del contenido normalizado con el de la versión activa para detectar el caso "sin cambios". Devuelve la lista de errores con el campo y el mensaje de cada uno, y un resultado de validez. El límite de tamaño del payload se comprueba sobre el tamaño total del cuerpo antes de procesar los campos individuales.
- **Hecho cuando:** un borrador válido no produce errores y un borrador con cualquiera de las reglas incumplidas produce un error que identifica el campo concreto; el contenido completamente vacío se rechaza; y un contenido normalizado idéntico al de la versión activa se detecta como "sin cambios".
- **Pruebas automáticas:**
  - Un perfil con todas las listas vacías y `criterios` vacío produce un error de contenido mínimo, conforme a REQ-017 y SUP-F.
  - Un perfil con al menos un sector no vacío y el resto vacío no produce error de contenido mínimo, conforme a REQ-017.
  - Una entrada de lista con longitud mayor que el límite configurado produce un error que identifica el campo, conforme a REQ-019.
  - Una lista con más elementos que el máximo configurado produce un error que identifica el campo, conforme a REQ-019.
  - `criterios` con longitud mayor que el límite configurado produce un error que identifica el campo, conforme a REQ-019.
  - Una entrada con caracteres de control no permitidos produce un error que identifica el campo, conforme a REQ-019.
  - Un perfil con todas las reglas cumplidas no produce ningún error, conforme a REQ-013.
  - Un perfil con varias reglas incumplidas devuelve todos los errores acumulados, no solo el primero, conforme a ALT-004.
  - Un contenido normalizado idéntico al de la versión activa se marca como "sin cambios", conforme a REQ-015 y DEC-006.
  - Un contenido que solo difiere de la versión activa en mayúsculas o tildes se marca como "sin cambios", conforme a REQ-015, SUP-H y DEC-007.
  - Un contenido que difiere de la versión activa en un valor real no se marca como "sin cambios", conforme a REQ-015.
  - El tamaño del payload se comprueba antes de procesar los campos: un payload por encima del límite configurado se rechaza sin analizar los campos, conforme a REQ-027, ALT-003 y NFR-005.
- **Prueba manual:**
  1. Validar un borrador con `criterios` demasiado largo y comprobar que el error identifica el campo `criterios` y su límite.
  2. Validar un borrador idéntico al de la versión activa y comprobar que se informa de "sin cambios".

### [ ] TASK-008 Repositorio de versiones y puntero de activa

- **Cubre:** REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008, REQ-009, REQ-010, REQ-011, REQ-012, REQ-014, REQ-016, REQ-020, REQ-021, REQ-022, REQ-024, REQ-025, REQ-026, NFR-002, NFR-006, SUP-A, SUP-B, SUP-C, SUP-G, DEC-002, DEC-003, DEC-004, DEC-009, DEC-010, ALT-006, ALT-009, ALT-010
- **Componente:** perfil-repository | source/api/perfil/repository.py
- **Módulo:** APP
- **Depende de:** TASK-003, TASK-004
- **Alcance:** Implementar el repositorio del perfil sobre el fichero SQLite propio. **La lectura de la versión activa, el cálculo de la versión `n+1`, la inserción de la nueva fila en `perfil_version` y la actualización o inserción del puntero en `perfil_activo` ocurren en una sola transacción** iniciada con `BEGIN IMMEDIATE`: si cualquier paso falla, la transacción se deshace, la conexión se cierra y no queda ninguna versión parcial ni cambia la versión activa. El número de versión lo asigna el propio SQLite mediante `AUTOINCREMENT`. El control optimista se aplica dentro de la misma transacción: si `version_base` no coincide con la versión activa (y, cuando no existe perfil, solo se acepta `0`), se rechaza la operación con conflicto y no se inserta nada. El componente también ofrece las lecturas del perfil activo, del historial completo ordenado por versión ascendente y de una versión concreta, y la operación de rollback, que copia el contenido de la versión objetivo a una versión nueva `n+1` y la activa sin modificar la versión original.
- **Hecho cuando:** un guardado válido con `version_base` coincidente crea la versión `n+1`, la activa y devuelve su número y contenido; un `version_base` ausente o no numérico se distingue del `version_base` obsoleto; un guardado o rollback fallido deja la versión activa intacta y no deja versiones parciales; y el historial devuelve todas las versiones en orden creciente, con la activa marcada.
- **Pruebas automáticas:**
  - Sin ninguna versión guardada, un guardado con `version_base: 0` crea la versión `1` y la activa, conforme a REQ-020, ALT-009 y DEC-004.
  - Sin ninguna versión guardada, un guardado con `version_base` distinta de `0` se rechaza con conflicto y no crea ninguna versión, conforme a ALT-009.
  - Con la versión activa `2`, un guardado con `version_base: 2` crea la versión `3` y la activa, conforme a REQ-011 y DEC-010.
  - Con la versión activa `4`, un guardado con `version_base: 3` se rechaza con conflicto y no crea ninguna versión ni cambia la activa, conforme a REQ-016 y ALT-006.
  - La versión activa ausente se comunica de forma distinguible del conflicto, conforme a ALT-007 y DEC-004.
  - La versión creada es la inmediatamente superior a la mayor existente y los números nunca se reutilizan, conforme a REQ-002 y DEC-010.
  - La lectura de la versión activa devuelve su número, su contenido y sus campos estructurados, conforme a REQ-008 y REQ-021.
  - Sin perfil guardado, la lectura de la activa comunica de forma explícita que no existe perfil, conforme a REQ-020 y DEC-005.
  - El historial devuelve una entrada por versión con número, `creado_en` y marca de activa, y en orden creciente, conforme a REQ-009.
  - El historial no incluye el contenido completo de cada versión, conforme al diseño de `GET /perfil/versiones`.
  - La lectura de una versión concreta devuelve su contenido completo, conforme a REQ-010.
  - La lectura de una versión inexistente comunica de forma explícita que no existe, conforme a REQ-010 y ALT-002.
  - Una versión guardada no puede modificarse ni borrarse a través del repositorio: no existe operación de actualización ni de borrado de versiones, conforme a REQ-003 y REQ-014.
  - El rollback a una versión anterior crea una versión `n+1` con el mismo contenido que la versión objetivo y la activa, sin modificar la versión original, conforme a REQ-012 y SUP-C.
  - El rollback a la versión ya activa se rechaza con conflicto y no crea ninguna versión, conforme a REQ-026 y ALT-008.
  - El rollback a una versión inexistente se rechaza sin crear ninguna versión, conforme a REQ-010 y ALT-002.
  - Un fallo durante la escritura (error de disco o de permisos simulado) deshace la transacción: la versión activa no cambia y no queda una versión parcial, conforme a REQ-025, NFR-002 y ALT-010.
  - Un error `SQLITE_BUSY` tras agotar el tiempo de espera se traduce en un error controlado de almacenamiento, conforme a ALT-010 y ALT-012.
  - La lectura del perfil activo, el cálculo de `n+1`, la inserción de la versión y la actualización de `perfil_activo` ocurren dentro de la misma transacción: un fallo en la actualización del puntero no deja la versión nueva insertada, conforme a NFR-002.
  - Diez guardados sobre un historial de diez versiones conservan las veinte versiones, conforme a NFR-006.
  - Una lectura o una escritura del perfil no altera ninguna fila de la base de ofertas ni el esquema de `api-persistencia`, conforme a REQ-022 y REQ-023.
- **Prueba manual:**
  1. Guardar un perfil nuevo con `version_base: 0` y comprobar que se crea la versión `1` y queda activa; después consultar el historial y ver una sola entrada con la activa marcada.
  2. Intentar un guardado con `version_base: 0` cuando ya existe la versión `1` y comprobar que se rechaza por conflicto y que el historial sigue con una sola versión.

### [ ] TASK-009 Arranque y apagado del perfil en la aplicación

- **Cubre:** REQ-020, REQ-024, REQ-025, NFR-003, NFR-007, SUP-A, DEC-001, DEC-008, ALT-011
- **Componente:** api-service | source/api
- **Módulo:** APP
- **Depende de:** TASK-002, TASK-004, TASK-008
- **Alcance:** Integrar en el ciclo de vida de la aplicación FastAPI existente (`source/api/main.py`, con su `lifespan` y su `app_state`) la carga de la configuración del perfil, la aplicación de las migraciones propias sobre el fichero `data/job_emcan_perfil.db`, la instanciación del repositorio y el registro del router de `perfil-api`, de modo que convivan en el mismo proceso el planificador de `api-buscador`, la `ingestion-task`, la `purge-task`, la `historico-task` y la `integridad-task`, sin modificar ninguno de esos módulos. Si la configuración, la apertura o la migración del perfil falla, el error se registra, el perfil se marca como no disponible y la aplicación **sigue arrancando** con el resto de features; los endpoints de perfil responderán 503 hasta que se resuelva el problema.
- **Hecho cuando:** al arrancar la aplicación, el fichero SQLite propio del perfil existe, está migrado a la versión esperada y en modo `wal`, el router del perfil queda registrado y el estado compartido del perfil está disponible en `app_state`; con un fichero de perfil corrupto o en versión futura el arranque registra el error, marca el perfil como no disponible y no aborta; y los endpoints existentes de `api-buscador`, `api-persistencia`, `api-historico`, `api-integridad` y `api-listado` siguen respondiendo igual.
- **Pruebas automáticas:**
  - Tras arrancar la aplicación, el fichero SQLite propio del perfil existe con `PRAGMA journal_mode` en `wal` y la tabla `schema_version_perfil` refleja la versión esperada, conforme a DEC-001.
  - Tras arrancar la aplicación, el router del perfil está registrado y sus rutas responden, conforme a REQ-008.
  - Con un fichero de perfil corrupto o no SQLite, el arranque registra el error, marca el perfil como no disponible y la aplicación sigue disponible, sin abortar el arranque de las demás features, conforme a DEC-008 y ALT-011.
  - Con un esquema propio en versión futura, el arranque registra el error y no sobrescribe el fichero, conforme a ALT-011.
  - Con una configuración del perfil ausente o malformada, el arranque registra el error y la aplicación sigue disponible sin la feature, conforme a DEC-008.
  - Los endpoints de `api-buscador`, `api-persistencia`, `api-historico`, `api-integridad` y `api-listado` siguen respondiendo igual después de integrar el perfil.
  - La integración no modifica `source/api/buscador/`, `source/api/persistencia/`, `source/api/historico/`, `source/api/integridad/`, `source/api/listado/` ni `source/api/parser.py`.
  - El arranque no altera el contenido ni la marca de modificación de `data/job_emcan.db`, conforme a SUP-A y NFR-003.
  - Al arrancar sin perfil guardado, no se crea ninguna versión de perfil por defecto, conforme a REQ-020.
- **Prueba manual:**
  1. Arrancar la aplicación y comprobar que aparece `data/job_emcan_perfil.db` migrado y que `GET /perfil/activo` responde.
  2. Sustituir el fichero por uno corrupto, arrancar y comprobar que la aplicación arranca, que `GET /perfil/activo` responde 503 y que el resto de endpoints siguen respondiendo.

### [ ] TASK-010 Endpoints de consulta del perfil

- **Cubre:** REQ-008, REQ-009, REQ-010, REQ-020, REQ-021, REQ-022, NFR-001, SUP-B, DEC-005, ALT-001, ALT-002
- **Componente:** perfil-api | source/api/perfil/routes.py
- **Módulo:** APP
- **Depende de:** TASK-008
- **Alcance:** Implementar los tres endpoints de consulta bajo `/perfil`: `GET /perfil/activo` (devuelve el perfil activo y su número de versión), `GET /perfil/versiones` (devuelve el historial completo con número, marca temporal y marca de activa, sin el contenido de cada versión) y `GET /perfil/versiones/{version}` (devuelve el contenido completo de una versión concreta). Cuando no existe perfil, `GET /perfil/activo` devuelve 200 con `perfil: null` y `version_activa: 0`, y `GET /perfil/versiones` devuelve 200 con `version_activa: 0` y `versiones: []`. Un parámetro `version` no entero o menor que 1 devuelve 400 con el modelo de error común, y un número válido inexistente devuelve 404. Los endpoints no exigen autenticación, como el resto de la API.
- **Hecho cuando:** un cliente puede consultar el perfil activo, el historial y una versión concreta; la ausencia de perfil se comunica con 200 y valores explícitos, no con error; y un parámetro inválido o una versión inexistente producen 400 y 404 respectivamente con el modelo de error común.
- **Pruebas automáticas:**
  - Con un perfil guardado, `GET /perfil/activo` devuelve `version_activa` y el perfil con sus seis listas y sus criterios, conforme a REQ-008.
  - Con un perfil guardado, `GET /perfil/versiones` devuelve una entrada por versión con `version`, `creado_en` y `activa`, en orden creciente, con exactamente una marcada como activa, conforme a REQ-009.
  - `GET /perfil/versiones/{version}` de una versión existente devuelve su número, su marca temporal y su contenido completo, conforme a REQ-010.
  - Sin perfil guardado, `GET /perfil/activo` devuelve 200 con `perfil: null` y `version_activa: 0`, conforme a REQ-020 y ALT-001.
  - Sin perfil guardado, `GET /perfil/versiones` devuelve 200 con `version_activa: 0` y `versiones: []`, conforme a REQ-009 y ALT-001.
  - `GET /perfil/versiones/abc` y `GET /perfil/versiones/0` devuelven 400 con el modelo de error común, conforme a ALT-002.
  - `GET /perfil/versiones/99` de una versión inexistente devuelve 404 con el modelo de error común, conforme a REQ-010 y ALT-002.
  - Las respuestas de error incluyen `codigo`, `mensaje` y `detalles`, conforme al modelo de error común del diseño.
  - Una consulta no altera la versión activa ni el historial, conforme a REQ-022.
  - Los endpoints no exigen cabeceras de autenticación ni devuelven 401 o 403.
  - Los endpoints del perfil no solapan sus rutas con las del buscador, de la persistencia, del histórico, de la integridad ni del listado.
- **Prueba manual:**
  1. Sin perfil guardado, consultar `GET /perfil/activo` y `GET /perfil/versiones` y comprobar que ambos devuelven 200 con la ausencia de perfil explícita.
  2. Tras guardar un perfil, consultar `GET /perfil/versiones/1` y comprobar que devuelve el contenido completo.

### [ ] TASK-011 Endpoint de guardado de una nueva versión

- **Cubre:** REQ-011, REQ-014, REQ-015, REQ-016, REQ-017, REQ-018, REQ-019, REQ-021, REQ-025, REQ-027, NFR-002, NFR-005, SUP-F, SUP-G, DEC-004, DEC-006, ALT-003, ALT-004, ALT-005, ALT-006, ALT-007, ALT-009, ALT-010
- **Componente:** perfil-api | source/api/perfil/routes.py
- **Módulo:** APP
- **Depende de:** TASK-007, TASK-008, TASK-010
- **Alcance:** Implementar el endpoint `POST /perfil/versiones`: valida el cuerpo (JSON bien formado, `version_base` presente y entero, tamaño del payload dentro del límite configurado), normaliza y valida el contenido con el validador, y delega en el repositorio la creación de la versión nueva y su activación. Devuelve 201 con el número de la versión activa y su contenido. Responde 400 con el modelo de error común si el cuerpo es inválido, falta `version_base`, `version_base` no es entero o hay errores de validación de contenido; 409 si `version_base` no coincide con la activa o si el contenido normalizado es idéntico al de la activa; 500 si falla el almacenamiento; y 503 si el perfil no está disponible. El endpoint no crea ninguna versión cuando la validación falla.
- **Hecho cuando:** un guardado válido crea y activa la versión `n+1` y devuelve 201 con su número y su contenido; un `version_base` ausente o no numérico devuelve 400; un `version_base` obsoleto o un contenido sin cambios devuelven 409; y un borrador inválido devuelve 400 con la lista de errores sin crear ninguna versión.
- **Pruebas automáticas:**
  - Con `version_base: 0` y sin perfil previo, la respuesta es 201 con `version_activa: 1` y el contenido enviado, conforme a REQ-011 y ALT-009.
  - Con la versión activa `2` y `version_base: 2`, la respuesta es 201 con `version_activa: 3` y el contenido enviado, conforme a REQ-011.
  - La versión anterior permanece en el historial sin cambios tras el guardado, conforme a REQ-003 y REQ-014.
  - Un cuerpo sin `version_base` devuelve 400 con el modelo de error común, conforme a ALT-007 y DEC-004.
  - Un `version_base` no numérico devuelve 400 con el modelo de error común, conforme a ALT-007 y DEC-004.
  - Con la versión activa `4` y `version_base: 3`, la respuesta es 409 y no se crea ninguna versión, conforme a REQ-016 y ALT-006.
  - Con un contenido normalizado idéntico al de la versión activa, la respuesta es 409 indicando que el perfil activo ya contiene esos valores y no se crea la versión `n+1`, conforme a REQ-015 y ALT-005.
  - Un borrador con todas las listas y `criterios` vacíos devuelve 400 con el error de contenido mínimo y no crea ninguna versión, conforme a REQ-017 y ALT-004.
  - Un borrador con una entrada que supera la longitud máxima devuelve 400 con el error que identifica el campo y no crea ninguna versión, conforme a REQ-019 y ALT-004.
  - Un cuerpo con JSON mal formado devuelve 400 con el modelo de error común y no crea ninguna versión, conforme a DEC-004.
  - Un payload por encima del límite configurado devuelve 400 con el motivo del rechazo antes de procesar los campos, conforme a REQ-027, ALT-003 y NFR-005.
  - Un fallo de almacenamiento simulado devuelve 500 con el modelo de error común y la versión activa no cambia, conforme a REQ-025 y ALT-010.
  - Con el perfil marcado como no disponible, la respuesta es 503 con el modelo de error común, conforme a DEC-008.
  - El guardado no altera ninguna fila de la base de ofertas, conforme a REQ-023.
- **Prueba manual:**
  1. Guardar un perfil nuevo con `version_base: 0` y comprobar que la respuesta es 201 con la versión `1`.
  2. Repetir el guardado con el mismo contenido y comprobar que la respuesta es 409 y que el historial sigue con una sola versión.

### [ ] TASK-012 Endpoint de rollback a una versión anterior

- **Cubre:** REQ-002, REQ-003, REQ-012, REQ-014, REQ-016, REQ-021, REQ-025, REQ-026, NFR-002, SUP-C, SUP-G, DEC-004, DEC-006, ALT-008, ALT-009, ALT-010
- **Componente:** perfil-api | source/api/perfil/routes.py
- **Módulo:** APP
- **Depende de:** TASK-008, TASK-011
- **Alcance:** Implementar el endpoint `POST /perfil/rollback`: valida el cuerpo (JSON bien formado, `version_base` y `version_objetivo` presentes y enteros, `version_objetivo` mayor o igual que 1), comprueba que la versión objetivo exista y no sea la activa, y delega en el repositorio la creación de la versión `n+1` con el contenido copiado de la versión objetivo y su activación. Devuelve 201 con el número de la versión activa y el contenido copiado. Responde 400 si falta algún campo, no son enteros, el JSON está mal formado o `version_objetivo` es menor que 1; 404 si `version_objetivo` no existe; 409 si `version_objetivo` ya es la activa o si `version_base` no coincide con la activa; 500 si falla el almacenamiento; y 503 si el perfil no está disponible.
- **Hecho cuando:** un rollback válido crea la versión `n+1` con el contenido de la versión objetivo y la activa, sin modificar la versión original; y los casos de versión inexistente, versión ya activa y `version_base` obsoleto producen 404 y 409 respectivamente sin crear ninguna versión.
- **Pruebas automáticas:**
  - Con la versión activa `5` y `version_base: 5`, un rollback a la versión `3` devuelve 201 con `version_activa: 6` y el contenido de la versión `3`, conforme a REQ-012 y SUP-C.
  - Tras el rollback, la versión `3` sigue existiendo con su número original y su contenido intacto, conforme a REQ-003 y REQ-014.
  - El historial tras el rollback contiene la versión `6` y mantiene las anteriores, conforme a REQ-012.
  - Un rollback a la versión ya activa devuelve 409 indicando que la versión solicitada ya es la activa y no crea la versión `n+1`, conforme a REQ-026 y ALT-008.
  - Un rollback a una versión inexistente devuelve 404 y no crea ninguna versión, conforme a ALT-002.
  - Un cuerpo sin `version_base` o sin `version_objetivo` devuelve 400 con el modelo de error común, conforme a ALT-007 y DEC-004.
  - Un `version_objetivo` no numérico o menor que 1 devuelve 400 con el modelo de error común, conforme a DEC-004.
  - Un `version_base` obsoleto devuelve 409 y no crea ninguna versión, conforme a REQ-016 y ALT-006.
  - Un fallo de almacenamiento simulado devuelve 500 y la versión activa no cambia, conforme a REQ-025 y ALT-010.
  - Con el perfil marcado como no disponible, la respuesta es 503 con el modelo de error común, conforme a DEC-008.
- **Prueba manual:**
  1. Con tres versiones y la `3` activa, ejecutar un rollback a la `1` y comprobar que la respuesta es 201 con la versión `4` y el contenido de la `1`.
  2. Ejecutar de nuevo un rollback a la `4` (la activa) y comprobar que la respuesta es 409 y que el historial sigue con cuatro versiones.

### [ ] TASK-013 Endpoint de validación previa de un borrador

- **Cubre:** REQ-013, REQ-017, REQ-018, REQ-019, REQ-027, NFR-005, SUP-F, SUP-H, DEC-007, DEC-011, ALT-003, ALT-004
- **Componente:** perfil-api | source/api/perfil/routes.py
- **Módulo:** APP
- **Depende de:** TASK-007, TASK-010
- **Alcance:** Implementar el endpoint `POST /perfil/validar`: recibe el mismo objeto `perfil` que el guardado, sin `version_base`, normaliza y valida el borrador, y devuelve **siempre 200** con `{valido: true|false, errores: [...]}`, donde cada error indica el campo y el mensaje. No crea ninguna versión ni activa ninguna. El 400 se reserva a los errores de transporte: JSON mal formado, tipos incorrectos o payload por encima del límite configurado, y usa el modelo de error común. Devuelve 503 si el perfil no está disponible.
- **Hecho cuando:** un borrador válido devuelve 200 con `valido: true` y la lista de errores vacía; un borrador inválido devuelve 200 con `valido: false` y la lista de errores; y ninguno de los dos casos crea una versión ni cambia la activa.
- **Pruebas automáticas:**
  - Un borrador válido devuelve 200 con `valido: true` y `errores: []`, conforme a REQ-013 y DEC-011.
  - Un borrador con un error de longitud devuelve 200 con `valido: false` y un error que identifica el campo, conforme a REQ-013, ALT-004 y DEC-011.
  - Un borrador con todos los campos vacíos devuelve 200 con `valido: false` y el error de contenido mínimo, conforme a REQ-017.
  - La respuesta de validación **no** usa el modelo de error común: devuelve su propio esquema con `valido` y `errores`, conforme a DEC-011.
  - Ninguna validación crea una versión ni cambia la versión activa, conforme a REQ-013.
  - Un cuerpo con JSON mal formado devuelve 400 con el modelo de error común, conforme a DEC-011.
  - Un cuerpo con tipos incorrectos (por ejemplo, una lista de texto donde se espera un texto) devuelve 400 con el modelo de error común, conforme a DEC-011.
  - Un payload por encima del límite configurado devuelve 400 con el motivo del rechazo, conforme a REQ-027, ALT-003 y NFR-005.
  - Con el perfil marcado como no disponible, la respuesta es 503 con el modelo de error común, conforme a DEC-008.
- **Prueba manual:**
  1. Validar un borrador válido y comprobar que la respuesta es 200 con `valido: true`.
  2. Validar un borrador con `criterios` demasiado largo y comprobar que la respuesta es 200 con `valido: false` y el error por campo.

### [ ] TASK-014 Verificación de integración del perfil

- **Cubre:** REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008, REQ-009, REQ-010, REQ-011, REQ-012, REQ-013, REQ-014, REQ-015, REQ-016, REQ-017, REQ-018, REQ-019, REQ-020, REQ-021, REQ-022, REQ-023, REQ-024, REQ-025, REQ-026, REQ-027, NFR-001, NFR-002, NFR-003, NFR-004, NFR-005, NFR-006, NFR-007, SUP-A, SUP-B, SUP-C, SUP-D, SUP-E, SUP-F, SUP-G, SUP-H, DEC-001, DEC-002, DEC-003, DEC-004, DEC-005, DEC-006, DEC-007, DEC-008, DEC-009, DEC-010, DEC-011, ALT-001, ALT-002, ALT-003, ALT-004, ALT-005, ALT-006, ALT-007, ALT-008, ALT-009, ALT-010, ALT-011, ALT-012
- **Componente:** api-service | source/api
- **Módulo:** APP
- **Depende de:** TASK-009, TASK-010, TASK-011, TASK-012, TASK-013
- **Alcance:** Verificar de extremo a extremo la comunicación entre la aplicación, la configuración, la conexión propia, el migrador, el normalizador, el validador, el repositorio y los seis endpoints, montando la aplicación con un fichero SQLite temporal del perfil y cubriendo los casos de arranque sin perfil, primer guardado, guardado con cambios, guardado sin cambios, `version_base` ausente y obsoleto, rollback válido, rollback a la activa, rollback inexistente, validación previa, reinicio de la aplicación, fichero corrupto, versión de esquema futura y escrituras concurrentes.
- **Hecho cuando:** con la aplicación arrancada, el ciclo completo de versionado del perfil funciona de extremo a extremo (guardar, consultar, rollback y validar) sobre el fichero propio; un reinicio conserva la versión activa y el historial; y un fichero corrupto o en versión futura deja el perfil en 503 sin afectar al resto de la API, sin excepciones no controladas.
- **Pruebas automáticas:**
  - Tras arrancar la aplicación sin perfil, `GET /perfil/activo` devuelve 200 con `perfil: null` y `version_activa: 0`, y `GET /perfil/versiones` devuelve 200 con `versiones: []`, conforme a REQ-020 y ALT-001.
  - Un primer guardado con `version_base: 0` crea la versión `1`, la activa y `GET /perfil/activo` la devuelve, conforme a REQ-011 y ALT-009.
  - Un segundo guardado con `version_base: 1` crea la versión `2` y el historial muestra dos entradas con la `2` activa, conforme a REQ-011.
  - Un guardado con el mismo contenido que la activa devuelve 409 y el historial sigue con dos versiones, conforme a REQ-015.
  - Un guardado con `version_base` ausente devuelve 400 y uno con `version_base` obsoleto devuelve 409, conforme a REQ-016 y ALT-007.
  - Un rollback a la versión `1` crea la versión `3` con el contenido de la `1` y la activa, y la `1` sigue intacta, conforme a REQ-012.
  - Un rollback a la versión activa devuelve 409 y uno a una versión inexistente devuelve 404, conforme a REQ-026.
  - `POST /perfil/validar` con un borrador inválido devuelve 200 con `valido: false` y no crea ninguna versión, conforme a REQ-013 y DEC-011.
  - Tras reiniciar la aplicación, la versión activa es la misma y todas las versiones siguen disponibles, conforme a REQ-024 y NFR-006.
  - Con un fichero de perfil corrupto, la aplicación arranca y los endpoints de perfil devuelven 503 sin servir perfiles inconsistentes, conforme a NFR-007, DEC-008 y ALT-011.
  - Con un esquema propio en versión futura, la aplicación arranca, el perfil queda no disponible y el fichero no se sobrescribe, conforme a ALT-011.
  - Dos escrituras concurrentes sobre el mismo perfil producen una versión `n+1` y un 409 (o una espera y una `n+2`), sin versiones duplicadas ni corrupción, conforme a ALT-006 y ALT-012.
  - Un guardado que falla a mitad de proceso deja la versión activa intacta y no deja versiones parciales, conforme a NFR-002.
  - Un municipio "Tresviso" y un criterio con tildes y eñes se guardan y se devuelven exactamente iguales, conforme a NFR-004.
  - Un payload de 1,5 MB se rechaza y uno de 500 KB se acepta para validación, conforme a NFR-005.
  - Tras toda la integración, `data/job_emcan.db` conserva su contenido y su marca de modificación y no ha ganado ninguna columna, conforme a REQ-023 y SUP-A.
  - Los endpoints existentes de `api-buscador`, `api-persistencia`, `api-historico`, `api-integridad` y `api-listado` siguen respondiendo igual, conforme a SUP-A.
- **Prueba manual:**
  1. Ejecutar la prueba de integración y revisar el informe: todos los escenarios salen con el resultado esperado.
  2. Revisar el directorio `data/` tras la prueba: aparece el fichero SQLite propio del perfil y el de persistencia conserva su contenido.

### [ ] TASK-015 Contrato: openapi - endpoints del perfil

- **Cubre:** REQ-008, REQ-009, REQ-010, REQ-011, REQ-012, REQ-013, REQ-015, REQ-016, REQ-017, REQ-019, REQ-020, REQ-021, REQ-026, REQ-027, NFR-005, SUP-B, SUP-G, DEC-004, DEC-005, DEC-006, DEC-011
- **Componente:** perfil-api | source/api/perfil/routes.py
- **Módulo:** APP
- **Depende de:** TASK-010, TASK-011, TASK-012, TASK-013, TASK-014
- **Alcance:** Crear el contrato OpenAPI `docs/contracts/openapi/api-perfil.yaml` que formaliza las seis operaciones bajo `/perfil` tal como quedaron implementadas: `GET /perfil/activo`, `GET /perfil/versiones`, `GET /perfil/versiones/{version}`, `POST /perfil/versiones`, `POST /perfil/rollback` y `POST /perfil/validar`, con el esquema del contenido del perfil (las seis listas y `criterios`), el esquema de la versión, el esquema del historial, el modelo de error común (`codigo`, `mensaje`, `detalles`) y las respuestas 200, 201, 400, 404, 409, 500 y 503.
- **Hecho cuando:** el contrato existe en `docs/contracts/openapi/api-perfil.yaml`, describe las seis operaciones con sus esquemas de entrada y salida y sus respuestas de error, y coincide con la implementación verificada en TASK-014.
- **Pruebas automáticas:**
  - El YAML del contrato se carga correctamente y contiene las seis operaciones con sus respuestas 200.
  - El esquema del contenido del perfil incluye `sectores`, `municipios`, `provincias`, `contrato`, `jornada`, `palabras_clave` y `criterios`, conforme a SUP-D.
  - El esquema de la respuesta de `GET /perfil/activo` incluye `version_activa` y `perfil` admitiendo `null`, conforme a REQ-020 y DEC-005.
  - El esquema de la respuesta de `GET /perfil/versiones` incluye `version_activa` y `versiones` con `version`, `creado_en` y `activa`, conforme a REQ-009.
  - El esquema de la respuesta de `POST /perfil/validar` incluye `valido` y `errores`, y no usa el modelo de error común para el resultado de validación, conforme a DEC-011.
  - El contrato define el modelo de error común con `codigo`, `mensaje` y `detalles`, conforme al modelo de error común del diseño.
  - El contrato documenta las respuestas 400, 404, 409, 500 y 503 de cada operación, conforme a DEC-004, DEC-006 y DEC-008.
  - El contrato documenta que `version_base` es obligatoria y entera, y que en el primer guardado debe ser `0`, conforme a SUP-G y ALT-009.
  - El contrato documenta el límite máximo de payload de 1 MB, conforme a REQ-027 y NFR-005.
  - El OpenAPI derivado de la implementación coincide con el fichero del contrato en rutas, métodos, esquemas y códigos de respuesta.
- **Prueba manual:**
  1. Revisar el contrato y comprobar que aparecen las seis interfaces de la fila de contratos afectados.
  2. Comparar el contrato con las respuestas JSON reales obtenidas en TASK-014 y confirmar que no hay campos divergentes.

### [ ] TASK-016 Contrato: configuración - fichero de configuración del perfil

- **Cubre:** REQ-019, REQ-027, NFR-001, NFR-005, SUP-A, DEC-001
- **Componente:** config-perfil | config/perfil.yaml
- **Módulo:** APP
- **Depende de:** TASK-002, TASK-009
- **Alcance:** Formalizar el contrato de configuración del perfil: documentar el formato exacto del fichero `config/perfil.yaml` (`perfil.ruta_bd`, `perfil.busy_timeout_ms`, `validacion.longitud_maxima_elemento`, `validacion.maximo_elementos_por_lista`, `validacion.longitud_maxima_criterios` y `validacion.tamano_maximo_payload_bytes`) y sus valores por defecto, dejándolo alineado con lo que la carga de TASK-002 interpreta y con lo que la aplicación aplica en TASK-009.
- **Hecho cuando:** el formato queda documentado, el fichero real lo cumple sin ambigüedad y una configuración válida se carga y se aplica sin cambios de código.
- **Pruebas automáticas:**
  - El fichero `config/perfil.yaml` se carga con el formato documentado y devuelve la ruta, el `busy_timeout` y los cuatro límites.
  - Una configuración sin los campos obligatorios se rechaza con un error controlado que identifica el campo ausente.
  - Una configuración con un tipo incorrecto o con un límite no positivo se rechaza con un error controlado, conforme a NFR-001.
  - Los valores por defecto documentados (`data/job_emcan_perfil.db`, `5000` ms, `200`, `100`, `5000` y `1048576` bytes) coinciden con los que aplica la implementación, conforme a DEC-001.
  - El contrato documenta que la ruta apunta a un fichero SQLite propio del perfil, distinto del de `api-persistencia`, conforme a SUP-A.
  - El contrato no documenta ninguna ruta de servidor de base de datos ni credenciales.
- **Prueba manual:**
  1. Revisar que la fila de contrato (configuración del perfil) queda descrita con el mismo formato que usa el fichero real.
  2. Modificar el fichero siguiendo solo el formato documentado y comprobar que la aplicación arranca con la nueva configuración.

### [ ] TASK-017 Verificación transversal de aislamiento, codificación, integridad y rendimiento

- **Cubre:** REQ-002, REQ-003, REQ-014, REQ-022, REQ-023, REQ-024, NFR-001, NFR-002, NFR-003, NFR-004, NFR-005, NFR-006, NFR-007, SUP-A, SUP-B, SUP-H, DEC-001, DEC-002, DEC-003, DEC-007, DEC-009, DEC-010, ALT-010, ALT-012
- **Componente:** api-service | source/api
- **Módulo:** APP
- **Depende de:** TASK-014
- **Alcance:** Verificar de extremo a extremo las garantías transversales de la feature con un fichero de base de datos de prueba: (a) aislamiento: la feature solo escribe en `data/job_emcan_perfil.db`, no toca `data/job_emcan.db` ni su tabla `schema_version`, y no modifica `api-buscador`, `api-persistencia`, `api-pdf-parser`, `api-historico`, `api-integridad` ni `api-listado`; (b) codificación: todos los campos de texto se guardan y se devuelven en UTF-8 conservando tildes, eñes y caracteres Unicode válidos; (c) integridad: `perfil_version.version` usa `AUTOINCREMENT` y no reutiliza números, `PRAGMA foreign_keys` está activo y `perfil_activo` solo puede tener una fila; (d) rendimiento: con 100 versiones, el perfil activo, el historial y una versión concreta responden en menos de 500 ms; y (e) estabilidad: un historial largo no se pierde tras guardados, rollbacks y reinicios.
- **Hecho cuando:** con 100 versiones, las tres consultas del perfil responden en menos de 500 ms; tras toda la verificación, `data/job_emcan.db` conserva su contenido y su marca de modificación; el texto se conserva íntegro en UTF-8; y la numeración de versiones es monótona y sin reutilización.
- **Pruebas automáticas:**
  - Con 100 versiones, `GET /perfil/activo` responde en menos de 500 ms, conforme a NFR-001.
  - Con 100 versiones, `GET /perfil/versiones` responde en menos de 500 ms, conforme a NFR-001.
  - Con 100 versiones, `GET /perfil/versiones/{version}` responde en menos de 500 ms, conforme a NFR-001.
  - El número de filas de la tabla `ofertas` de `data/job_emcan.db` es idéntico antes y después de toda la verificación, conforme a REQ-023 y SUP-A.
  - La marca de modificación de `data/job_emcan.db` no cambia tras toda la verificación, conforme a SUP-A y NFR-003.
  - La tabla `schema_version` de `api-persistencia` conserva su contenido y su número de versión, conforme a SUP-A.
  - El fichero `data/job_emcan_perfil.db` es el único fichero SQLite que la feature crea o modifica, conforme a DEC-001.
  - Una comparación del contenido de los ficheros de `source/api/buscador/`, `source/api/persistencia/`, `source/api/historico/`, `source/api/integridad/`, `source/api/listado/` y `source/api/parser.py` confirma que la feature no los ha modificado.
  - El código del paquete `source/api/perfil/` no contiene ninguna referencia a la ruta del SQLite de `api-persistencia` ni a la tabla `ofertas`, conforme a REQ-023 y SUP-A.
  - El municipio "Tresviso" se guarda y se devuelve exactamente como "Tresviso", conforme a NFR-004.
  - Un criterio con tildes y eñes se guarda y se devuelve sin alteración, conforme a NFR-004 y DEC-002.
  - El contenido almacenado en `perfil_version.contenido` es JSON válido con las claves esperadas y serializado sin escapes ASCII, conforme a DEC-002.
  - Insertando y borrando la versión de número mayor, la siguiente versión insertada no reutiliza ese número, conforme a REQ-002, REQ-003 y DEC-010.
  - `PRAGMA foreign_keys` está activo en las conexiones del perfil y una `version` inexistente en `perfil_activo` es rechazada, conforme a DEC-001.
  - `perfil_activo` solo admite una fila: insertar una segunda con `id` distinto de `1` es rechazado, conforme a DEC-003.
  - Con un historial de 10 versiones, tras 10 guardados adicionales el historial contiene las 20 versiones, conforme a NFR-006.
  - Un fallo de escritura simulado no deja una versión parcial ni cambia la activa, conforme a NFR-002 y ALT-010.
  - Dos escritores concurrentes no producen versiones duplicadas ni corrupciones, conforme a ALT-012.
- **Prueba manual:**
  1. Ejecutar la prueba de rendimiento con 100 versiones y revisar el tiempo medido en el informe: queda por debajo de 500 ms.
  2. Revisar el directorio `data/` antes y después: el fichero de ofertas conserva su marca de modificación y solo el fichero propio del perfil ha cambiado.

### [ ] TASK-018 Actualización del mapa de arquitectura

- **Cubre:** DEC-001, DEC-002, DEC-003, DEC-004, DEC-005, DEC-006, DEC-007, DEC-008, DEC-009, DEC-010, DEC-011
- **Componente:** api-service | source/api
- **Módulo:** APP
- **Depende de:** TASK-015, TASK-016, TASK-017
- **Alcance:** Actualizar `.sdd/architecture.md` en tres puntos y solo en esos tres: (a) la línea del módulo `API`, cuya responsabilidad pasa a incluir también el perfil de búsqueda versionado; (b) añadir a la sección de contratos la entrada `openapi | docs/contracts/openapi/api-perfil.yaml | cliente -> api-perfil`; y (c) añadir a la sección de contratos la entrada `configuracion | config/perfil.yaml | api-perfil -> config-perfil`. El mapa **no** gana entradas de módulo para los componentes internos del perfil, que son detalle de implementación dentro del módulo `API` y no reciben identificador propio en el mapa.
- **Hecho cuando:** la línea del módulo `API` de `.sdd/architecture.md` menciona el perfil de búsqueda versionado en su responsabilidad; la sección de contratos contiene las dos entradas nuevas (`openapi` del perfil y `configuracion` de `config/perfil.yaml`); y la sección de módulos no contiene ninguna entrada nueva para los componentes internos del perfil.
- **Pruebas automáticas:**
  - Una comprobación lee `.sdd/architecture.md` y confirma que la línea del módulo `API` incluye el perfil de búsqueda versionado en su descripción de responsabilidad.
  - Una comprobación confirma que la sección de contratos incluye la entrada `openapi | docs/contracts/openapi/api-perfil.yaml | cliente -> api-perfil`.
  - Una comprobación confirma que la sección de contratos incluye la entrada `configuracion | config/perfil.yaml | api-perfil -> config-perfil`.
  - Una comprobación confirma que la sección de módulos no ha ganado entradas para los componentes internos del perfil (configuración, conexión, migrador, modelos, normalizador, validador, repositorio y endpoints) ni para el subpaquete `source/api/perfil`.
  - Todos los ficheros citados en el mapa existen en el repositorio.
- **Prueba manual:**
  1. Revisar `.sdd/architecture.md` y comprobar que la línea del módulo `API` incluye el perfil en su responsabilidad y que la sección de contratos contiene las dos entradas nuevas.
  2. Revisar la sección de módulos del mapa y comprobar que no se ha añadido ninguna entrada para los componentes internos del perfil.

## Cobertura

| Requisito | Tareas |
|---|---|
| REQ-001 | TASK-001, TASK-008, TASK-014, TASK-017 |
| REQ-002 | TASK-008, TASK-012, TASK-014, TASK-017 |
| REQ-003 | TASK-008, TASK-011, TASK-012, TASK-014, TASK-017 |
| REQ-004 | TASK-001, TASK-005, TASK-006, TASK-008, TASK-014 |
| REQ-005 | TASK-001, TASK-005, TASK-008, TASK-014 |
| REQ-006 | TASK-005, TASK-006, TASK-008, TASK-014 |
| REQ-007 | TASK-001, TASK-005, TASK-006, TASK-008, TASK-014 |
| REQ-008 | TASK-005, TASK-008, TASK-010, TASK-014 |
| REQ-009 | TASK-005, TASK-008, TASK-010, TASK-014 |
| REQ-010 | TASK-005, TASK-008, TASK-010, TASK-012, TASK-014 |
| REQ-011 | TASK-008, TASK-011, TASK-014 |
| REQ-012 | TASK-008, TASK-012, TASK-014 |
| REQ-013 | TASK-007, TASK-013, TASK-014 |
| REQ-014 | TASK-008, TASK-011, TASK-012, TASK-014, TASK-017 |
| REQ-015 | TASK-006, TASK-007, TASK-011, TASK-014 |
| REQ-016 | TASK-008, TASK-011, TASK-012, TASK-014 |
| REQ-017 | TASK-007, TASK-011, TASK-013, TASK-014 |
| REQ-018 | TASK-006, TASK-007, TASK-014 |
| REQ-019 | TASK-002, TASK-007, TASK-013, TASK-014 |
| REQ-020 | TASK-004, TASK-008, TASK-009, TASK-010, TASK-014 |
| REQ-021 | TASK-005, TASK-008, TASK-011, TASK-012, TASK-014 |
| REQ-022 | TASK-008, TASK-010, TASK-014, TASK-017 |
| REQ-023 | TASK-004, TASK-008, TASK-011, TASK-014, TASK-017 |
| REQ-024 | TASK-003, TASK-004, TASK-008, TASK-009, TASK-014, TASK-017 |
| REQ-025 | TASK-003, TASK-004, TASK-008, TASK-009, TASK-011, TASK-012, TASK-014 |
| REQ-026 | TASK-008, TASK-012, TASK-014 |
| REQ-027 | TASK-002, TASK-007, TASK-011, TASK-013, TASK-014, TASK-015 |

| Requisito no funcional | Tareas |
|---|---|
| NFR-001 | TASK-002, TASK-010, TASK-014, TASK-016, TASK-017 |
| NFR-002 | TASK-003, TASK-004, TASK-008, TASK-011, TASK-012, TASK-014, TASK-017 |
| NFR-003 | TASK-003, TASK-009, TASK-014, TASK-017 |
| NFR-004 | TASK-005, TASK-006, TASK-014, TASK-017 |
| NFR-005 | TASK-002, TASK-007, TASK-011, TASK-013, TASK-014, TASK-015, TASK-017 |
| NFR-006 | TASK-008, TASK-014, TASK-017 |
| NFR-007 | TASK-004, TASK-009, TASK-014, TASK-017 |

| Decisión | Tareas |
|---|---|
| DEC-001 | TASK-001, TASK-002, TASK-003, TASK-004, TASK-009, TASK-014, TASK-016, TASK-017, TASK-018 |
| DEC-002 | TASK-001, TASK-005, TASK-008, TASK-014, TASK-017, TASK-018 |
| DEC-003 | TASK-004, TASK-008, TASK-014, TASK-017, TASK-018 |
| DEC-004 | TASK-008, TASK-011, TASK-012, TASK-015, TASK-018 |
| DEC-005 | TASK-008, TASK-010, TASK-014, TASK-015, TASK-018 |
| DEC-006 | TASK-007, TASK-008, TASK-011, TASK-012, TASK-015, TASK-018 |
| DEC-007 | TASK-005, TASK-006, TASK-007, TASK-013, TASK-014, TASK-017, TASK-018 |
| DEC-008 | TASK-004, TASK-009, TASK-010, TASK-011, TASK-012, TASK-013, TASK-014, TASK-018 |
| DEC-009 | TASK-003, TASK-008, TASK-014, TASK-017, TASK-018 |
| DEC-010 | TASK-004, TASK-008, TASK-014, TASK-017, TASK-018 |
| DEC-011 | TASK-007, TASK-013, TASK-014, TASK-015, TASK-018 |

| Supuesto | Tareas |
|---|---|
| SUP-A | TASK-001, TASK-002, TASK-003, TASK-004, TASK-008, TASK-009, TASK-014, TASK-016, TASK-017 |
| SUP-B | TASK-008, TASK-010, TASK-014, TASK-015, TASK-017 |
| SUP-C | TASK-008, TASK-012, TASK-014 |
| SUP-D | TASK-001, TASK-005, TASK-015 |
| SUP-E | TASK-008, TASK-011, TASK-012, TASK-014 |
| SUP-F | TASK-007, TASK-011, TASK-013, TASK-014 |
| SUP-G | TASK-007, TASK-008, TASK-011, TASK-012, TASK-014, TASK-015 |
| SUP-H | TASK-006, TASK-007, TASK-013, TASK-014, TASK-017 |

| Escenario alternativo | Tareas |
|---|---|
| ALT-001 | TASK-008, TASK-010, TASK-014 |
| ALT-002 | TASK-008, TASK-010, TASK-012 |
| ALT-003 | TASK-007, TASK-011, TASK-013 |
| ALT-004 | TASK-007, TASK-011, TASK-013 |
| ALT-005 | TASK-007, TASK-011 |
| ALT-006 | TASK-008, TASK-011, TASK-012, TASK-014 |
| ALT-007 | TASK-008, TASK-011, TASK-012 |
| ALT-008 | TASK-008, TASK-012 |
| ALT-009 | TASK-008, TASK-011, TASK-014, TASK-015 |
| ALT-010 | TASK-008, TASK-011, TASK-012, TASK-017 |
| ALT-011 | TASK-004, TASK-009, TASK-014 |
| ALT-012 | TASK-003, TASK-008, TASK-014, TASK-017 |

## Avisos

- La estrategia de contratos aplicada es `implementation-first`, valor tomado de la opción `contract-strategy` de `.sdd/team.md`. Por eso TASK-015 depende de las tareas de endpoints y de la verificación de integración, y TASK-016 depende de TASK-002 y TASK-009.
- No existe `.sdd/task-types.md`, así que no hay tipos de tarea propios del proyecto que generar.
- Los componentes del perfil (`api-perfil`, `config-perfil`, `db-connection-perfil`, `schema-migrator-perfil`, `perfil-repository`, `perfil-normalizer`, `perfil-validator` y `perfil-api`) son **detalle de implementación interno del módulo `API`**: no reciben identificador propio en `.sdd/architecture.md` y no se proponen como módulos nuevos del mapa, conforme a `design@3`. Las tareas que los implementan los citan en su línea `Componente` (con la ruta interna dentro de `source/api/perfil/`) y llevan su línea `Módulo` con el identificador `APP`, que es la etiqueta del trabajo; el código permanece en `source/api/perfil/`.
- TASK-018 no registra módulos nuevos del perfil. Su alcance se limita a actualizar la línea del módulo `API` de `.sdd/architecture.md` para que su responsabilidad incluya el perfil de búsqueda versionado, a añadir las dos entradas de contrato (`openapi | docs/contracts/openapi/api-perfil.yaml | cliente -> api-perfil` y `configuracion | config/perfil.yaml | api-perfil -> config-perfil`) y a comprobar que el mapa no gana entradas de módulo para los componentes internos del perfil.
- `api-buscador`, `api-persistencia`, `api-pdf-parser`, `api-historico`, `api-integridad` y `api-listado` no se modifican en ninguna tarea. La compatibilidad se resuelve solo desde `api-perfil`, con un segundo fichero SQLite propio (`data/job_emcan_perfil.db`), su propio migrador (`schema_version_perfil`) y su propia conexión por operación, conforme a SUP-A y DEC-001. `data/job_emcan.db` y la tabla `schema_version` de `api-persistencia` no se tocan en ninguna tarea.
- La regla central de DEC-009 y NFR-002 queda explícita en TASK-008: **la lectura de la versión activa, el cálculo de `n+1`, la inserción de la nueva versión y la actualización del puntero en `perfil_activo` ocurren en una sola transacción iniciada con `BEGIN IMMEDIATE`, y cualquier fallo deshace todo**, de modo que no queda ninguna versión parcial ni cambia la versión activa. La conexión se abre y se cierra por operación.
- La regla central de DEC-010 queda explícita en TASK-008 y TASK-017: el número de versión lo asigna el propio SQLite con `INTEGER PRIMARY KEY AUTOINCREMENT` y nunca se reutiliza un número, incluso si la fila de número mayor se borrase (que en la práctica no ocurre por REQ-003).
- La comparación "sin cambios" (REQ-015, ALT-005, DEC-006) se realiza **después** de normalizar con la clave NFD + eliminación de diacríticos + `casefold`, conservando la forma escrita: por eso "Técnico" y "tecnico" se consideran el mismo valor. La detección de "sin cambios" vive en el validador (TASK-007) y se traduce en 409 en el endpoint de guardado (TASK-011), no en 400.
- El diseño fija el prefijo de rutas `/perfil` y los nombres de operación (`GET /perfil/activo`, `GET /perfil/versiones`, `GET /perfil/versiones/{version}`, `POST /perfil/versiones`, `POST /perfil/rollback`, `POST /perfil/validar`); TASK-010 a TASK-013 los usan tal cual.
- El diseño no fija el nombre exacto de los módulos internos del paquete `source/api/perfil/`; TASK-001 los propone como orientación (`config.py`, `connection.py`, `migrations.py`, `models.py`, `normalizer.py`, `validator.py`, `repository.py`, `routes.py`) y la capa técnica puede renombrarlos sin alterar el alcance de las tareas.
- El diseño no fija el nombre del fichero del contrato OpenAPI más allá de `docs/contracts/openapi/api-perfil.yaml`, ya indicado en la fila de contratos afectados; TASK-015 lo usa tal cual.
- La regla "sin cambios" y la de "rollback a la activa" comparten el código 409 con el conflicto de `version_base` (DEC-006). El `codigo` del modelo de error común (`VALIDACION_ERROR`, `PARAMETRO_INVALIDO`, `PERFIL_NO_ENCONTRADO`, `CONFLICTO_VERSION`, `ERROR_ALMACENAMIENTO`, `SERVICIO_NO_DISPONIBLE`) es el que permite distinguir cada caso en el cuerpo de la respuesta; TASK-015 documenta esos códigos.
- REQ-019 y REQ-027 están cubiertos en dos capas: los límites configurables los aplica el validador (TASK-007) y el rechazo por tamaño total del payload ocurre en el endpoint antes de procesar los campos (TASK-011 y TASK-013, ALT-003). El límite de longitud de elemento no lo aplica el normalizador, que solo recorta y deduplica (TASK-006).
- NFR-001 (menos de 500 ms con hasta 100 versiones) se verifica de extremo a extremo en TASK-017, y de forma puntual en TASK-010 y TASK-014.
- El documento contiene 18 tareas (TASK-001..TASK-018); la numeración es continua y no hay huecos. El apartado "Orden de implementación" los agrupa en 9 pasos numerados, cada uno con las tareas que encadenan.
