# Tareas: api-historico

Estado: aprobado
Revisión: 1
Basado en: requirements@2, design@3
Verificación: correcta

## Resumen

El trabajo se divide en veintiuna tareas (TASK-001..TASK-021) que siguen la cadena de dependencias del diseño: primero la estructura del paquete y la configuración, después la conexión SQLite propia con WAL y las migraciones del esquema auxiliar, luego los repositorios de estado propio (presencia y serie de recuentos, abstenciones y ejecución diaria), a continuación los adaptadores hacia el exterior (estado del buscador, cliente de `persistencia-api`, lectura de solo lectura del SQLite de `api-persistencia` e invocación en proceso del parser del PDF), después los tres evaluadores y el guardián de recuento, luego la tarea programada diaria y su arranque y apagado en el proceso FastAPI, los endpoints de consulta del histórico, la verificación de integración, las dos tareas de contrato (`implementation-first`) y por último la actualización del mapa de arquitectura. Cada tarea de implementación incluye sus propias pruebas; solo la verificación de extremo a extremo se separa como tarea de integración.

Los componentes del histórico son detalle de implementación interno del módulo `API` y no reciben identificador propio en el mapa de arquitectura: todas las tareas llevan su línea `Módulo` con el identificador `APP`, aunque el código viva en `source/api/historico/`. La actualización del mapa (TASK-021) se limita a la descripción del módulo `API` y a los dos contratos nuevos.

`api-historico` no modifica `api-buscador`, `api-persistencia` ni `api-pdf-parser`: la integración es por contrato HTTP (`GET /buscador/status`, `POST /persistencia/ofertas`, `GET /persistencia/ofertas/vigentes`, `GET /persistencia/ofertas/{comunidad}/{codigo}`), por lectura directa en modo solo lectura (`mode=ro`) de `data/job_emcan.db` y por invocación en proceso del parser del PDF de difusión.

## Orden de implementación

1. TASK-001 Estructura del paquete y dependencias → TASK-002 Configuración del histórico.
2. TASK-003 Conexión SQLite propia con WAL → TASK-004 Migraciones del esquema propio.
3. TASK-005 Repositorio de presencia y serie de recuentos → TASK-006 Repositorio de abstenciones → TASK-007 Repositorio de ejecución diaria.
4. TASK-008 Adaptador del estado del buscador → TASK-009 Cliente de `persistencia-api` → TASK-010 Adaptador de lectura `mode=ro` → TASK-011 Adaptador del listado oficial del PDF.
5. TASK-012 Evaluador de cierre por fecha → TASK-013 Evaluador de desaparición y contador de ausencias → TASK-014 Guardián de recuento.
6. TASK-015 Tarea diaria programada → TASK-016 Arranque y apagado en la aplicación.
7. TASK-017 Endpoints de consulta del histórico.
8. TASK-018 Verificación de integración.
9. TASK-019..TASK-020 Contratos (implementation-first).
10. TASK-021 Actualización del mapa (descripción del módulo `API` y dos contratos).

## Tareas

### [x] TASK-001 Estructura del paquete del histórico y dependencias

- **Cubre:** REQ-001, REQ-010, SUP-002, DEC-001, DEC-003
- **Componente:** api-historico | source/api/historico
- **Módulo:** APP
- **Depende de:** -
- **Alcance:** Crear el subpaquete `source/api/historico/` con su `__init__.py` y los módulos hosting de los componentes del diseño, y declarar en `pyproject.toml` las dependencias que exige el diseño (`httpx` para los clientes HTTP de `GET /buscador/status` y de `persistencia-api`, `pdfplumber` para el parseo en proceso del PDF de difusión, la librería de zona horaria estándar para NFR-001 y el mecanismo de planificación en proceso), sin introducir motor de base de datos servidor ni extensión vectorial.
- **Hecho cuando:** el subpaquete `source/api/historico` se importa sin errores, las dependencias declaradas cubren las que usa el diseño y el runner de pruebas recorre `tests/` sin fallos de colección; y el paquete no referencia ni importa `api-buscador`, `api-persistencia` ni `api-pdf-parser` de forma que los modifique.
- **Pruebas automáticas:**
  - La suite arranca sin errores de importación de `source.api.historico` ni de las dependencias declaradas.
  - Una comprobación confirma que `httpx`, `pdfplumber` y el soporte de zona horaria están disponibles en el entorno de pruebas.
  - El paquete no importa ni referencia un motor de base de datos servidor (SQLAlchemy, PostgreSQL, MySQL) ni una extensión de SQLite para vectores.
  - El paquete no escribe ni modifica ficheros bajo `source/api/buscador/`, `source/api/persistencia/` ni `source/api/parser.py`, `source/api/downloader.py` y `source/api/assembler.py`, conforme a SUP-002.
- **Prueba manual:**
  1. Instalar el proyecto en un entorno virtual limpio y ejecutar la suite de pruebas: termina sin fallos por dependencias ausentes.

### [x] TASK-002 Fichero de configuración del histórico

- **Cubre:** REQ-005, REQ-008, NFR-001, NFR-003, SUP-001, DEC-001, DEC-005
- **Componente:** config-historico | config/historico.yaml
- **Módulo:** APP
- **Depende de:** TASK-001
- **Alcance:** Crear el fichero de configuración `config/historico.yaml` con la zona horaria (por defecto `Europe/Madrid`), la hora de ejecución diaria del cierre (por defecto posterior a la pasada del buscador), el número de ausencias consecutivas (por defecto `2`), el umbral de caída del recuento (por defecto `30` %) y el recuento mínimo (por defecto `70`), la ruta del fichero SQLite propio del histórico (por defecto `data/job_emcan_historico.db`), la ruta del SQLite de `api-persistencia` que se leerá en solo lectura (por defecto `data/job_emcan.db`), la URL base del buscador y de la API de persistencia, y la comunidad y el identificador de comunidad del PDF de difusión, e implementar su carga con valores por defecto y error controlado ante fichero ausente o malformado.
- **Hecho cuando:** la carga devuelve la configuración completa con los valores por defecto del diseño cuando no se indican otros, un fichero ausente o malformado produce un error controlado que identifica la configuración como origen, la zona horaria cargada es válida y utilizable para obtener la fecha local, y las rutas son relativas a la raíz del proyecto.
- **Pruebas automáticas:**
  - La carga del fichero `config/historico.yaml` devuelve zona horaria, hora de ejecución, número de ausencias consecutivas, umbral de caída, recuento mínimo, ruta del SQLite propio, ruta del SQLite de persistencia, URL base del buscador, URL base de persistencia y comunidad.
  - Sin fichero de configuración, la zona horaria es `Europe/Madrid`, el número de ausencias consecutivas es `2`, el umbral de caída es `30` y el recuento mínimo es `70`, conforme a REQ-005, REQ-008 y NFR-003.
  - Un fichero con YAML malformado, con un submapa que no es un mapa o con un campo de tipo incorrecto produce un error controlado que identifica el campo problemático.
  - Una zona horaria inválida se rechaza con un error controlado que la identifica, conforme a NFR-001.
  - La configuración no contiene ninguna ruta de servidor de base de datos ni credenciales.
- **Prueba manual:**
  1. Abrir `config/historico.yaml` y comprobar que contiene los campos con sus valores por defecto.
  2. Cambiar el umbral de caída al 20 % y el recuento mínimo a 80, recargar la configuración y comprobar que los nuevos valores son los que se aplican.

### [ ] TASK-003 Conexión única al SQLite propio del histórico

- **Cubre:** REQ-005, REQ-008, REQ-011, NFR-002, SUP-003, DEC-001
- **Componente:** db-connection-historico | source/api/historico/connection.py
- **Módulo:** APP
- **Depende de:** TASK-002
- **Alcance:** Implementar el componente que abre o crea el fichero SQLite propio del histórico configurado, crea el directorio `data/` si falta, activa `PRAGMA journal_mode = WAL`, configura `busy_timeout` y expone el contexto de conexión y de transacción para el resto de componentes, sin tocar el SQLite de `api-persistencia` ni ningún módulo de otra feature.
- **Hecho cuando:** tras inicializar el histórico existe el fichero `data/job_emcan_historico.db` con modo `wal`, `busy_timeout` queda establecido en un valor mayor que cero, las transacciones se pueden abrir y confirmar o deshacer, y el fichero `data/job_emcan.db` no se ha creado ni modificado por este componente.
- **Pruebas automáticas:**
  - Con una ruta temporal inexistente, la inicialización crea el directorio y el fichero SQLite propio y el directorio contiene un único fichero `.db` del histórico.
  - `PRAGMA journal_mode` devuelve `wal` tras la inicialización y `PRAGMA busy_timeout` devuelve un valor mayor que cero.
  - Una transacción confirmada deja los cambios persistidos y una transacción deshecha no los deja.
  - El componente no abre ninguna conexión de escritura sobre la ruta del SQLite de `api-persistencia` configurada, conforme a SUP-003.
  - No se abre ninguna conexión de red ni se requiere ningún servidor de base de datos.
- **Prueba manual:**
  1. Arrancar el histórico con la configuración por defecto y comprobar que aparece `data/job_emcan_historico.db` con WAL activo y que `data/job_emcan.db` conserva su marca de modificación.

### [ ] TASK-004 Migraciones secuenciales del esquema propio del histórico

- **Cubre:** REQ-005, REQ-008, REQ-011, NFR-002, SUP-003, DEC-001, ALT-010
- **Componente:** schema-migrator-historico | source/api/historico/migrations.py
- **Módulo:** APP
- **Depende de:** TASK-003
- **Alcance:** Implementar el migrador que crea y mantiene la tabla de versión del esquema y aplica migraciones numeradas secuenciales y transaccionales sobre el SQLite propio, creando las tablas del modelo de datos lógico del diseño: presencia en listado (por comunidad, código y fecha de listado, con su marca de presencia o ausencia), serie de recuentos (recuento total y marca de tiempo de cada pasada), abstenciones de cierre (motivo, marca de tiempo, recuentos y códigos afectados) y ejecución diaria (fecha de ejecución). El esquema propio no contiene ofertas.
- **Hecho cuando:** sobre un fichero recién creado existen las cuatro tablas con las columnas del modelo de datos lógico y la tabla de versión refleja la versión aplicada; un fichero ya migrado no reejecuta migraciones; y una versión futura o un fichero no abrirse abortan el arranque con error explícito.
- **Pruebas automáticas:**
  - Tras migrar desde cero existen las tablas de presencia en listado, serie de recuentos, abstenciones de cierre y ejecución diaria, con sus columnas.
  - Ninguna tabla propia del histórico contiene una columna de oferta ni duplica la tabla `ofertas`, conforme a SUP-003 y DEC-001.
  - La tabla de versión contiene la versión esperada con su marca de aplicación.
  - Al migrar un fichero ya en la versión esperada no se ejecuta ninguna migración nueva y la versión no cambia.
  - Un fichero con versión superior a la esperada aborta con error explícito y no se modifica.
  - Una migración que falla deja el esquema en el estado anterior y el arranque se aborta.
- **Prueba manual:**
  1. Migrar un fichero desde cero y revisar el esquema resultante con una herramienta de inspección de SQLite: tablas, columnas e índices.
  2. Arrancar dos veces seguidas y comprobar que la segunda vez no se reejecuta ninguna migración.

### [x] TASK-005 Repositorio de presencia en listado y serie de recuentos

- **Cubre:** REQ-005, REQ-008, REQ-011, NFR-003, SUP-003, DEC-001, DEC-005, ALT-007
- **Componente:** historico-presencia-repository | source/api/historico/presencia_repository.py
- **Módulo:** APP
- **Depende de:** TASK-004
- **Alcance:** Implementar el repositorio que persiste la presencia o ausencia de cada código candidato en cada listado oficial, con clave por comunidad, código y fecha del listado, y que permite consultar las últimas apariciones y ausencias de un código para contar ausencias consecutivas; e implementar en el mismo componente la serie histórica de recuentos del listado, que registra el recuento total y su marca de tiempo y devuelve el recuento anterior al actual.
- **Hecho cuando:** registrar la presencia de un código para una fecha y consultarla devuelve la marca de presencia; registrar la ausencia para esa misma fecha devuelve la ausencia; la consulta de las últimas apariciones de un código devuelve las fechas ordenadas de más reciente a más antigua; y el registro de un recuento lo añade a la serie y devuelve el recuento anterior y el actual, con la serie vacía cuando no hay histórico.
- **Pruebas automáticas:**
  - Registrar presencia y ausencia del mismo código en fechas distintas y consultar su histórico devuelve las dos marcas con sus fechas, conforme a REQ-005.
  - Registrar dos veces el mismo código para la misma fecha no duplica el registro y la última marca prevalece.
  - La consulta del último recuento anterior devuelve el recuento de la pasada previa y el actual, conforme a REQ-008.
  - Sobre una serie vacía, la consulta del recuento anterior no devuelve ningún valor en lugar de fallar, conforme a ALT-010.
  - El componente no escribe en ninguna base de datos de ofertas y no duplica su contenido, conforme a SUP-003.
- **Prueba manual:**
  1. Registrar presencia y ausencia simuladas y consultar el histórico de un código: comprobar que devuelve las fechas y las marcas correctas.

### [ ] TASK-006 Repositorio de abstenciones de cierre

- **Cubre:** REQ-006, REQ-008, REQ-011, SUP-003, DEC-001, DEC-005
- **Componente:** abstenciones-repository | source/api/historico/abstenciones_repository.py
- **Módulo:** APP
- **Depende de:** TASK-004
- **Alcance:** Implementar el repositorio que registra cada abstención de cierre con su motivo, su marca de tiempo, los recuentos relevantes y los códigos afectados, y que permite consultarlas de forma ordenada por marca de tiempo, con filtros por motivo y por rango de fechas.
- **Hecho cuando:** una abstención registrada conserva motivo, marca de tiempo, recuento anterior, recuento actual, umbral aplicado y códigos afectados, y la consulta las devuelve ordenadas de más reciente a más antigua; una abstención sin recuentos ni códigos afectados se registra con esos campos vacíos y no falla.
- **Pruebas automáticas:**
  - Registrar una abstención con recuentos y códigos y consultarla devuelve los cinco datos intactos, conforme a REQ-011.
  - Registrar una abstención por pasada fallida con el estado consultado del buscador y consultarla devuelve el motivo, la marca de tiempo y el estado, conforme a REQ-006.
  - Registrar una abstención por caída anómala devuelve el recuento anterior, el actual y el umbral aplicado, conforme a REQ-008.
  - Registrar una abstención por oferta excluida devuelve el código de la oferta y el motivo, conforme a REQ-007 y REQ-011.
  - La consulta filtrada por motivo devuelve solo las abstenciones de ese motivo.
  - La consulta por rango de fechas devuelve solo las abstenciones dentro del rango.
  - El componente no escribe en la base de datos de ofertas, conforme a SUP-003.
- **Prueba manual:**
  1. Registrar tres abstenciones con motivos distintos y consultarlas: comprobar el orden y que cada una conserva sus datos.

### [x] TASK-007 Repositorio de ejecución diaria

- **Cubre:** REQ-011, NFR-002, SUP-003, DEC-001, ALT-006
- **Componente:** ejecucion-repository | source/api/historico/ejecucion_repository.py
- **Módulo:** APP
- **Depende de:** TASK-004
- **Alcance:** Implementar el repositorio que registra la fecha, en la zona horaria configurada, de cada ejecución del cierre diario y que consulta si ya existe una ejecución para ese día, de modo que el cierre se ejecute como máximo una vez al día.
- **Hecho cuando:** tras registrar la ejecución de un día, la consulta de "¿se ejecutó hoy?" devuelve que sí; registrar una segunda ejecución el mismo día no crea un segundo registro efectivo para ese día; y la consulta de un día distinto devuelve que no.
- **Pruebas automáticas:**
  - Registrar la ejecución y consultar el día actual devuelve que ya se ejecutó, conforme a NFR-002.
  - Registrar dos veces la ejecución del mismo día no genera dos registros para esa fecha, conforme a ALT-006.
  - La consulta de un día anterior o posterior devuelve que no se ejecutó.
  - La fecha registrada corresponde a la zona horaria configurada y no a la del sistema, conforme a NFR-001.
  - Tras un reinicio de la aplicación, el registro de ejecución sigue disponible, conforme a DEC-001.
  - El componente no escribe en la base de datos de ofertas, conforme a SUP-003.
- **Prueba manual:**
  1. Registrar la ejecución del día y consultar si se ejecutó hoy: comprobar que devuelve que sí tras reiniciar la aplicación.

### [ ] TASK-008 Adaptador del estado del buscador

- **Cubre:** REQ-006, REQ-007, REQ-008, SUP-002, DEC-003, ALT-001, ALT-008
- **Componente:** buscador-status-adapter | source/api/historico/buscador_client.py
- **Módulo:** APP
- **Depende de:** TASK-002
- **Alcance:** Implementar el cliente HTTP que consulta `GET /buscador/status` en la URL base configurada y normaliza la respuesta para los evaluadores: expone el total del listado, la marca de tiempo de la última pasada, el error global y el conjunto de códigos con error por oferta, distinguiendo de forma explícita el error HTTP o de red, el `error_global` no vacío y la `ultima_pasada` nula. No modifica `api-buscador` ni lanza pasadas ni descarga fichas.
- **Hecho cuando:** el adaptador devuelve el estado publicado por el buscador con la estructura real de `GET /buscador/status` y, ante un error HTTP o de red, un `error_global` no vacío o una `ultima_pasada` nula, comunica un estado no utilizable que permite al evaluador abstenerse, sin lanzar excepción.
- **Pruebas automáticas:**
  - Con un cliente de prueba que responde el cuerpo real de `GET /buscador/status`, el adaptador devuelve `in_progress`, `progreso` y `ultima_pasada` con `timestamp`, `comunidad`, `total_listado`, `error_global` y `errores_por_oferta`.
  - La URL solicitada es la URL base configurada más `/buscador/status`.
  - Con `ultima_pasada` nula, el adaptador lo comunica de forma distinguible, conforme a ALT-008.
  - Con `error_global` no vacío, el adaptador lo comunica sin lanzar excepción, conforme a ALT-001.
  - Con un error HTTP o un fallo de red, el adaptador devuelve un error controlado, conforme a ALT-001.
  - El conjunto de códigos con error por oferta se obtiene correctamente y se puede consultar por código, conforme a REQ-007.
  - El cliente solo emite peticiones a `/buscador/status`: no solicita ningún otro endpoint del buscador.
- **Prueba manual:**
  1. Con la aplicación arrancada, consultar el adaptador contra `http://localhost:8000` y comprobar que devuelve el mismo `ultima_pasada` que muestra `GET /buscador/status`.

### [ ] TASK-009 Cliente de la API de persistencia

- **Cubre:** REQ-001, REQ-003, REQ-005, REQ-009, REQ-010, REQ-012, SUP-002, SUP-003, DEC-003, ALT-009
- **Componente:** persistencia-adapter | source/api/historico/persistencia_client.py
- **Módulo:** APP
- **Depende de:** TASK-002
- **Alcance:** Implementar el cliente de `persistencia-api` que expone exactamente las operaciones que la API ofrece: listar las ofertas vigentes, consultar una oferta por su clave natural `(comunidad, codigo)` y crear o actualizar una oferta, usándose esta última solo para pasar el estado a `cerrada` con su `fecha_cierre`. El cliente no crea ofertas nuevas, no lista códigos vistos y no lee ofertas cerradas ni por rango de fechas.
- **Hecho cuando:** el cliente puede listar las ofertas vigentes, consultar una oferta por su clave natural y actualizar el estado de una oferta existente a `cerrada` con su `fecha_cierre`; una consulta de una clave inexistente devuelve un resultado que lo indica de forma explícita; y no existe ninguna operación de cliente que cree una oferta que antes no existía.
- **Pruebas automáticas:**
  - La operación de listar vigentes devuelve solo ofertas con estado `vigente` con sus campos de difusión, conforme a REQ-003 y REQ-004.
  - La operación de consultar por clave natural devuelve el estado actual y las fechas de la oferta, conforme a REQ-009 y REQ-012.
  - La consulta de una `(comunidad, codigo)` inexistente devuelve un resultado que indica que no se encontró, sin excepción.
  - La operación de actualizar a `cerrada` con `fecha_cierre` deja la oferta en estado `cerrada` con la marca de tiempo informada, conforme a REQ-003 y REQ-005.
  - Actualizar a `cerrada` una oferta ya cerrada no modifica su `fecha_cierre` existente, conforme a REQ-005 y REQ-010.
  - Actualizar a `cerrada` no vacía el texto libre ni el contacto, conforme a REQ-010.
  - El cliente no expone ninguna operación de listado de códigos vistos ni de lectura por rango de fechas, conforme a SUP-003.
  - El cliente no escribe ni modifica ficheros bajo `source/api/persistencia/`.
- **Prueba manual:**
  1. Consultar una oferta vigente por su clave natural desde el cliente y comprobar que devuelve el estado y las fechas; actualizarla a `cerrada` y comprobar que conserva el texto y el contacto.

### [ ] TASK-010 Adaptador de lectura histórica en solo lectura

- **Cubre:** REQ-001, REQ-002, REQ-012, SUP-002, SUP-003, DEC-006
- **Componente:** historico-read-adapter | source/api/historico/read_adapter.py
- **Módulo:** APP
- **Depende de:** TASK-002
- **Alcance:** Implementar el componente que abre `data/job_emcan.db` en modo **solo lectura (`mode=ro`)** y consulta directamente la tabla `ofertas` con el esquema documentado, sin escribir, sin crear el fichero si no existe y sin modificar migraciones ni esquema, para servir las consultas históricas por rango de fechas que `persistencia-api` no expone: altas por `fecha_alta`, cierres por `fecha_cierre` o por `fecha_fin_difusion`, y resumen diario de altas y cierres.
- **Hecho cuando:** con un fichero SQLite que simula el esquema de `api-persistencia`, la consulta de altas por rango de `fecha_alta` devuelve las ofertas cuya `fecha_alta` está dentro del rango y ninguna fuera; la consulta de cierres por rango de `fecha_cierre` y por `fecha_fin_difusion` se comporta igual; el resumen diario devuelve el número de altas y de cierres de cada día del rango; y ninguna de estas operaciones escribe en el fichero, que conserva su marca de modificación y su contenido.
- **Pruebas automáticas:**
  - La conexión se abre en modo solo lectura: un intento de escritura sobre ella es rechazado por SQLite, conforme a DEC-006.
  - La lectura no crea el fichero `data/job_emcan.db` si no existe y devuelve un resultado vacío controlado.
  - Una alta con `fecha_alta` dentro del rango aparece en el resultado y una alta fuera del rango no, conforme a REQ-002.
  - Una oferta cerrada con `fecha_cierre` dentro del rango aparece en la consulta de cierres por fecha de cierre, conforme a REQ-012.
  - Una oferta cerrada con `fecha_fin_difusion` dentro del rango aparece en la consulta de cierres por fecha de fin, conforme a REQ-012.
  - El resumen diario incluye el número de altas y el número de cierres de cada día del rango, conforme a REQ-012.
  - Cada resultado incluye comunidad, código, ocupación, municipio, estado, `fecha_alta`, `fecha_fin_difusion` y `fecha_cierre`, conforme a REQ-002 y REQ-012.
  - La marca de modificación del fichero SQLite de `api-persistencia` no cambia tras las lecturas, conforme a SUP-002 y SUP-003.
- **Prueba manual:**
  1. Consultar altas y cierres por rango sobre un fichero SQLite de prueba y comprobar que los rangos y el resumen diario son los esperados y que el fichero no ha cambiado.

### [ ] TASK-011 Adaptador del listado oficial de códigos del PDF

- **Cubre:** REQ-005, SUP-001, SUP-002, DEC-002, ALT-004
- **Componente:** pdf-listado-adapter | source/api/historico/pdf_adapter.py
- **Módulo:** APP
- **Depende de:** TASK-002
- **Alcance:** Implementar el adaptador que obtiene el listado oficial de códigos de oferta del día invocando **en proceso** el módulo de parseo del PDF de difusión (`source/api/parser.py` y `source/api/downloader.py`), sin llamada HTTP a `GET /parse` y sin modificar `api-pdf-parser`, devolviendo el conjunto de códigos y la fecha del listado; y que informa del fallo de forma distinguible cuando el PDF no se puede descargar, el parseo falla o no produce ningún código.
- **Hecho cuando:** con un PDF de difusión disponible, el adaptador devuelve el conjunto de códigos de oferta publicados y la fecha del listado; con un PDF no descargable, con error de parseo o sin ningún código devuelve un fallo controlado que permite al evaluador abstenerse; y no se emite ninguna petición al endpoint `GET /parse` de la propia API.
- **Pruebas automáticas:**
  - Con un descargador y un parser simulados que devuelven una lista de ofertas, el adaptador devuelve el conjunto de códigos y la fecha del listado, conforme a SUP-001.
  - Los códigos se conservan como texto de 12 dígitos con sus ceros iniciales.
  - Con un fallo de descarga, el adaptador devuelve un fallo controlado distinguible, conforme a ALT-004.
  - Con un error de parseo o con un listado sin ningún código, el adaptador devuelve un fallo controlado, conforme a ALT-004.
  - El adaptador invoca el parser en proceso: no se realiza ninguna llamada HTTP a `GET /parse` ni a ningún otro endpoint de la API, conforme a DEC-002.
  - El adaptador no modifica `source/api/parser.py`, `source/api/downloader.py` ni `source/api/assembler.py`.
- **Prueba manual:**
  1. Invocar el adaptador con el PDF de difusión real y comprobar que devuelve el conjunto de códigos y que ninguna petición HTTP a `/parse` aparece en el registro.

### [ ] TASK-012 Evaluador del cierre por fecha de fin de difusión

- **Cubre:** REQ-003, REQ-004, REQ-009, REQ-010, NFR-001, DEC-005, ALT-005
- **Componente:** cierre-fecha-evaluator | source/api/historico/cierre_fecha.py
- **Módulo:** APP
- **Depende de:** TASK-009
- **Alcance:** Implementar el evaluador que recibe las ofertas vigentes con `fecha_fin_difusion` informada, descarta las fechas corruptas o imposibles, compara cada fecha de fin con la fecha actual en la zona horaria configurada y cierra de forma idempotente, a través de `persistencia-adapter`, solo las que tienen fecha de fin estrictamente anterior a la fecha actual; las ofertas con fecha de fin vacía no entran en este evaluador y se derivan al cierre por desaparición.
- **Hecho cuando:** una oferta vigente con `fecha_fin_difusion` del día anterior en la zona horaria configurada pasa a `cerrada` con `fecha_cierre` informada; una oferta cuya fecha de fin es el mismo día permanece `vigente`; una oferta ya cerrada conserva su `fecha_cierre` original al reevaluarse; una oferta con `fecha_fin_difusion` vacía no se cierra por fecha; y una oferta en estado `sin_ficha` nunca se cierra por fecha.
- **Pruebas automáticas:**
  - Con `fecha_fin_difusion = 20/11/2026` y hoy `21/11/2026` en la zona configurada, la oferta pasa a `cerrada` y `fecha_cierre` se rellena con la marca de la detección, conforme a REQ-003.
  - Con `fecha_fin_difusion = 21/11/2026` y hoy `21/11/2026`, la oferta permanece `vigente`.
  - Reevaluar una oferta ya cerrada no cambia su `fecha_cierre` ni genera un segundo cierre, conforme a REQ-003.
  - Una oferta vigente con `fecha_fin_difusion` vacía permanece `vigente` y se devuelve como candidata al cierre por desaparición, conforme a REQ-004.
  - Una fecha con formato distinto de `dd/mm/aaaa` o imposible (por ejemplo, `31/02/2026`) se descarta del cierre por fecha, se informa como fecha inválida y no cambia el estado, conforme a ALT-005.
  - Una oferta en estado `sin_ficha` permanece en `sin_ficha`, conforme a REQ-009.
  - Con otra zona horaria configurada, la comparación usa esa zona, conforme a NFR-001.
  - El cierre no vacía el texto libre ni el contacto, conforme a REQ-010.
- **Prueba manual:**
  1. Ejecutar el evaluador con una oferta cuya fecha de fin es ayer y otra cuya fecha de fin es hoy, y comprobar los dos estados resultantes y la `fecha_cierre` de la primera.

### [ ] TASK-013 Evaluador de desaparición y contador de ausencias consecutivas

- **Cubre:** REQ-004, REQ-005, REQ-007, REQ-009, REQ-010, REQ-011, NFR-003, SUP-001, SUP-003, DEC-002, DEC-004, DEC-005, ALT-003, ALT-004, ALT-007
- **Componente:** desaparicion-evaluator | source/api/historico/desaparicion.py
- **Módulo:** APP
- **Depende de:** TASK-005, TASK-009, TASK-011
- **Alcance:** Implementar el evaluador que recibe las ofertas vigentes sin `fecha_fin_difusion`, el listado oficial del día y los códigos con error por oferta de la última pasada; excluye las que estén en `errores_por_oferta` y las que estén en estado `sin_ficha`; registra en `historico-presencia-repository` la presencia o ausencia de cada código candidata para la fecha del listado; cuenta las ausencias consecutivas consultando el histórico de presencia con el número de ausencias configurado (por defecto `2`, con el margen de un día) y cierra de forma idempotente, a través de `persistencia-adapter`, las que hayan faltado en los últimos listados consecutivos. Si la fuente de respaldo no está disponible o devuelve error, no cierra ninguna oferta y registra la abstención.
- **Hecho cuando:** una oferta sin fecha de fin que aparece en el listado oficial permanece `vigente`; una que falta en el listado actual pero estuvo en el anterior permanece `vigente` por el margen de un día; una que falta en el actual y en el anterior pasa a `cerrada` con `fecha_cierre`; una cuyo código está en `errores_por_oferta` permanece `vigente`; y una que vuelve a aparecer tras haber sido cerrada por desaparición no se reabre.
- **Pruebas automáticas:**
  - Una candidata presente en el listado oficial permanece `vigente`, conforme a REQ-005.
  - Una candidata ausente en el listado actual y presente en el anterior permanece `vigente`, conforme a REQ-005 y al margen de un día.
  - Una candidata ausente en el listado actual y en el anterior pasa a `cerrada` y registra `fecha_cierre`, conforme a REQ-005.
  - Con el número de ausencias consecutivas configurado en `3`, se requieren tres listados sin el código, conforme a NFR-003.
  - Un código presente en `errores_por_oferta` no se cierra y se registra la abstención con su código y el motivo, conforme a REQ-007 y ALT-003.
  - Con la fuente de respaldo no disponible o con error, no se cierra ninguna oferta y se registra la abstención, conforme a REQ-005 y ALT-004.
  - Una oferta en estado `sin_ficha` no se cierra aunque no aparezca en el listado, conforme a REQ-009.
  - Una oferta cerrada por desaparición que reaparece en un listado posterior permanece `cerrada` y su `fecha_cierre` no cambia, conforme a ALT-007 y DEC-004.
  - La presencia o ausencia de cada candidata queda registrada para la fecha del listado, conforme a REQ-005.
  - El cierre no vacía el texto libre ni el contacto, conforme a REQ-010.
- **Prueba manual:**
  1. Simular dos listados consecutivos sin un código y comprobar que la oferta pasa a `cerrada` con `fecha_cierre`, y que una tercera candidata ausente solo en el listado actual sigue `vigente`.

### [ ] TASK-014 Guardián de recuento del listado

- **Cubre:** REQ-008, REQ-011, NFR-003, SUP-003, DEC-005, ALT-002, ALT-010
- **Componente:** recuento-guardian | source/api/historico/recuento_guardian.py
- **Módulo:** APP
- **Depende de:** TASK-005, TASK-008
- **Alcance:** Implementar el guardián que toma el recuento del listado de la última pasada y lo compara con el recuento anterior de la serie propia: si la caída supera el umbral configurado o el recuento actual es inferior al recuento mínimo configurado, se abstiene de cerrar por desaparición y registra la abstención con el recuento anterior, el recuento actual y el umbral aplicado; y si no existe recuento anterior, registra el recuento actual pero se abstiene de cerrar por desaparición.
- **Hecho cuando:** con recuento anterior `93` y actual `60` no se permite el cierre por desaparición y queda registrada la abstención con los dos recuentos y el umbral; con anterior `93` y actual `92` el cierre por desaparición queda permitido; con recuento actual `65` el cierre por desaparición queda bloqueado aunque la caída no supere el umbral; y con los umbrales configurados al `20` % y a `80` son los que se aplican.
- **Pruebas automáticas:**
  - Anterior `93` y actual `60` producen abstención sin permitir cierres por desaparición, conforme a REQ-008 y ALT-002.
  - Anterior `93` y actual `92` permiten el cierre por desaparición, conforme a REQ-008.
  - Actual `65` con anterior `93` produce abstención por recuento mínimo, conforme a REQ-008.
  - La abstención registrada incluye el recuento anterior, el actual y el umbral aplicado, conforme a REQ-011.
  - Sin recuento anterior, el recuento actual se registra y el cierre por desaparición se aplaza, conforme a ALT-010.
  - Con umbral de caída del `20` % y recuento mínimo `80` configurados, se aplican esos valores en lugar de los del `30` % y `70`, conforme a NFR-003.
  - El guardián no escribe en la base de datos de ofertas, conforme a SUP-003.
- **Prueba manual:**
  1. Ejecutar el guardián con un recuento actual claramente menor que el anterior y comprobar que se registra la abstención con los dos recuentos y el umbral.

### [ ] TASK-015 Tarea programada diaria de cierre

- **Cubre:** REQ-001, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008, REQ-009, REQ-010, REQ-011, REQ-012, NFR-001, NFR-002, NFR-003, SUP-001, SUP-002, SUP-003, DEC-001, DEC-003, DEC-004, DEC-005, ALT-001, ALT-002, ALT-003, ALT-004, ALT-005, ALT-006, ALT-007, ALT-008, ALT-009
- **Componente:** historico-task | source/api/historico/task.py
- **Módulo:** APP
- **Depende de:** TASK-006, TASK-007, TASK-008, TASK-009, TASK-011, TASK-012, TASK-013, TASK-014
- **Alcance:** Implementar la tarea programada propia que orquesta el cierre diario a la hora configurada, sin modificar el planificador de `api-buscador`: comprueba en `ejecucion-repository` si ya se ejecutó hoy y, si es así, finaliza sin hacer nada; consulta el estado del buscador y, si no responde, la última pasada es nula o hay error global, registra la abstención y detiene el proceso; pide al guardián de recuento la validación del recuento; ejecuta el cierre por fecha; ejecuta el cierre por desaparición; y registra la ejecución del día. Las escrituras de estado van siempre por `persistencia-adapter` y no se crean ofertas nuevas.
- **Hecho cuando:** la tarea se dispara a la hora configurada, no vuelve a evaluar ofertas en un día en el que ya se ejecutó, con el buscador caído o sin pasada completa no marca ninguna oferta como cerrada y registra la abstención, y con una pasada válida cierra por fecha y por desaparición y registra la ejecución del día sin crear ofertas nuevas.
- **Pruebas automáticas:**
  - Con el reloj controlado, la tarea se dispara una vez al llegar la hora configurada y no se solapa con una ejecución en curso.
  - Con una ejecución ya registrada para el día, la tarea finaliza sin reevaluar ofertas ni regenerar registros de presencia, conforme a ALT-006 y NFR-002.
  - Con el buscador sin respuesta, con `ultima_pasada` nula o con `error_global` no vacío, no se marca ninguna oferta como cerrada y se registra la abstención con el motivo y la marca de tiempo, conforme a REQ-006, ALT-001 y ALT-008.
  - Con una caída anómala del recuento, no se cierra ninguna oferta por desaparición y se registra la abstención, conforme a REQ-008 y ALT-002.
  - Con una pasada válida y una oferta con fecha de fin pasada, la oferta queda `cerrada` con `fecha_cierre`, conforme a REQ-003.
  - Con una pasada válida y una oferta sin fecha de fin ausente de los listados, la oferta queda `cerrada`, conforme a REQ-005.
  - La tarea no crea ninguna oferta nueva ni modifica la `fecha_alta` de ninguna oferta, conforme a REQ-001.
  - La tarea no vacía campos ni elimina embeddings de las ofertas que cierra, conforme a REQ-010 y ALT-009.
  - La tarea se cancela limpiamente sin dejar ejecuciones en curso.
- **Prueba manual:**
  1. Arrancar la tarea con el reloj controlado a la hora configurada y comprobar que se ejecuta una vez y que la segunda ejecución del mismo día no hace nada.

### [ ] TASK-016 Arranque y apagado del histórico en la aplicación

- **Cubre:** REQ-006, REQ-011, NFR-001, NFR-002, SUP-001, SUP-002, SUP-003, DEC-001, DEC-002, ALT-001, ALT-008, ALT-009
- **Componente:** api-service | source/api
- **Módulo:** APP
- **Depende de:** TASK-003, TASK-004, TASK-015
- **Alcance:** Integrar en el ciclo de vida de la aplicación FastAPI existente (`source/api/main.py`, con su `lifespan` y su `app_state`) la carga de la configuración del histórico, la apertura de la conexión propia con WAL, la aplicación de las migraciones propias, el registro del router de consulta y el arranque de la tarea diaria del cierre, de modo que convivan en el mismo proceso el planificador de `api-buscador`, la `ingestion-task` y la `purge-task` de `api-persistencia` y la nueva `historico-task`, sin modificar ninguno de esos módulos; y ordenar el apagado de modo que la tarea del histórico se cancele antes de cerrar su conexión y antes de detener el planificador del buscador.
- **Hecho cuando:** al arrancar la aplicación el fichero SQLite propio del histórico existe, está migrado a la versión esperada y en modo `wal`, la tarea diaria del histórico está activa junto al planificador del buscador, la ingesta y la purga de `api-persistencia`; al apagar la aplicación la tarea del histórico queda cancelada sin dejar ejecuciones en curso, se cierra su conexión y después se detiene el planificador del buscador; y los endpoints existentes de `api-buscador` y `api-persistencia` siguen respondiendo igual.
- **Pruebas automáticas:**
  - Tras arrancar la aplicación, el fichero SQLite propio del histórico existe con `PRAGMA journal_mode` en `wal` y la tabla de versión del esquema propio refleja la versión esperada.
  - Tras arrancar la aplicación, están activas la tarea del histórico, la ingesta, la purga y el planificador del buscador, conforme a la convivencia en el mismo proceso.
  - Al apagar la aplicación, la tarea del histórico queda cancelada y no se inician nuevas ejecuciones.
  - Al apagar, la cancelación de la tarea del histórico ocurre antes del cierre de su conexión y antes de la detención del planificador del buscador.
  - Los endpoints de `api-buscador` y de `api-persistencia` siguen respondiendo igual después de integrar el histórico.
  - Un esquema propio en versión futura aborta el arranque con error explícito y no sobrescribe el fichero.
  - La integración no modifica `source/api/buscador/`, `source/api/persistencia/` ni `source/api/parser.py`, conforme a SUP-002.
  - El arranque no altera el contenido ni la marca de modificación de `data/job_emcan.db`, conforme a SUP-003.
- **Prueba manual:**
  1. Arrancar la aplicación y comprobar que aparecen `data/job_emcan_historico.db` migrado y que la tarea del histórico queda programada.
  2. Detener la aplicación y comprobar que no queda ninguna tarea del histórico viva.

### [ ] TASK-017 Endpoints de consulta del histórico

- **Cubre:** REQ-002, REQ-012, REQ-001, SUP-002, SUP-003, DEC-006
- **Componente:** historico-api | source/api/historico/routes.py
- **Módulo:** APP
- **Depende de:** TASK-010
- **Alcance:** Implementar los endpoints de consulta del histórico: altas por rango de `fecha_alta`, cierres por rango de `fecha_cierre` y por rango de `fecha_fin_difusion`, y resumen diario de altas y cierres por día, servidos desde `historico-read-adapter` sobre el SQLite de `api-persistencia` en modo solo lectura, devolviendo en cada resultado al menos comunidad, código, ocupación, municipio, estado, `fecha_alta`, `fecha_fin_difusion` y `fecha_cierre`. Los endpoints no exigen autenticación, como el resto de la API.
- **Hecho cuando:** un cliente puede consultar las altas de un rango de fechas, los cierres por fecha de cierre y por fecha de fin de difusión, y el resumen diario de altas y cierres; cada resultado incluye los campos mínimos exigidos; y ningún endpoint escribe en la base de datos de persistencia.
- **Pruebas automáticas:**
  - La consulta de altas con un rango devuelve las ofertas cuya `fecha_alta` está dentro del rango y ninguna fuera, conforme a REQ-002.
  - La consulta de cierres por fecha de cierre devuelve las ofertas cerradas cuya `fecha_cierre` está dentro del rango, conforme a REQ-012.
  - La consulta de cierres por fecha de fin de difusión devuelve las ofertas cerradas cuya `fecha_fin_difusion` está dentro del rango, conforme a REQ-012.
  - El resumen diario incluye el número de altas y el número de cierres de cada día, conforme a REQ-012.
  - Cada elemento de las respuestas incluye comunidad, código, ocupación, municipio, estado, `fecha_alta`, `fecha_fin_difusion` y `fecha_cierre`, conforme a REQ-002 y REQ-012.
  - Un rango sin resultados devuelve una lista vacía sin error.
  - Los endpoints no exigen cabeceras de autenticación ni devuelven 401 o 403.
  - Las consultas no modifican la marca de modificación de `data/job_emcan.db`, conforme a SUP-003.
  - El router del histórico no solapa sus rutas con las del buscador ni con las de `api-persistencia`.
- **Prueba manual:**
  1. Consultar los tres endpoints con un rango de fechas sobre una base de prueba y comprobar que los resultados y el resumen diario son los esperados.

### [ ] TASK-018 Verificación de integración del histórico

- **Cubre:** REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008, REQ-009, REQ-010, REQ-011, REQ-012, NFR-001, NFR-002, NFR-003, SUP-001, SUP-002, SUP-003, DEC-001, DEC-002, DEC-003, DEC-004, DEC-005, DEC-006, ALT-001, ALT-002, ALT-003, ALT-004, ALT-005, ALT-006, ALT-007, ALT-008, ALT-009
- **Componente:** api-service | source/api
- **Módulo:** APP
- **Depende de:** TASK-016, TASK-017
- **Alcance:** Verificar de extremo a extremo la comunicación entre la aplicación, la conexión propia, el migrador, los repositorios, los adaptadores, los evaluadores, el guardián y la tarea diaria, montando la aplicación con `GET /buscador/status` simulado, `persistencia-api` en el mismo proceso, un parser del PDF simulado y bases SQLite temporales que simulen el esquema de `api-persistencia`, y cubriendo los casos de cierre por fecha, cierre por desaparición, buscador caído, caída anómala del recuento, doble ejecución diaria y cierre concurrente con la ingesta o la purga.
- **Hecho cuando:** con una pasada simulada válida, el cierre por fecha y por desaparición se aplican y las consultas históricas devuelven las altas y los cierres esperados; con el buscador caído o con recuento anómalo no se cierra ninguna oferta y queda registrada la abstención; y la segunda ejecución del mismo día no vuelve a evaluar ofertas, sin excepciones no controladas.
- **Pruebas automáticas:**
  - Con una pasada válida y una oferta con fecha de fin pasada, la oferta queda `cerrada` con `fecha_cierre` y el cierre aparece en la consulta de cierres por rango, conforme a REQ-003 y REQ-012.
  - Con una oferta sin fecha de fin ausente de dos listados consecutivos, la oferta queda `cerrada` y el cierre aparece en la consulta de cierres, conforme a REQ-005.
  - Con el buscador caído, con `ultima_pasada` nula o con `error_global`, no se cierra ninguna oferta y existe una abstención registrada con su motivo, conforme a REQ-006.
  - Con una caída anómala del recuento no se cierra ninguna oferta por desaparición y la abstención registra los dos recuentos, conforme a REQ-008.
  - Con un código en `errores_por_oferta`, la oferta permanece `vigente` y existe la abstención con el código, conforme a REQ-007.
  - Con una segunda ejecución el mismo día, no se generan cierres nuevos ni registros de presencia adicionales, conforme a NFR-002.
  - Con el parser del PDF simulado en error, no se cierra ninguna oferta por desaparición y se registra la abstención, conforme a REQ-005.
  - Las consultas de altas y de cierres por rango devuelven los datos esperados con los campos mínimos, conforme a REQ-002 y REQ-012.
  - Una oferta cerrada conserva el texto libre y el contacto y no se ve afectada por la purga concurrente de `api-persistencia`, conforme a REQ-010 y ALT-009.
  - Las ofertas en estado `sin_ficha` no se cierran, conforme a REQ-009.
  - La base de datos de `api-persistencia` conserva su contenido tras toda la integración y solo se ha añadido el fichero propio del histórico, conforme a SUP-003.
- **Prueba manual:**
  1. Ejecutar la prueba de integración y revisar el informe: todos los escenarios salen con el resultado esperado.
  2. Revisar el directorio `data/` tras la prueba: aparecen el fichero SQLite propio del histórico y el de persistencia, sin modificaciones en el segundo.

### [ ] TASK-019 Contrato: openapi - endpoints de consulta del histórico

- **Cubre:** REQ-001, REQ-002, REQ-012, SUP-002, SUP-003, DEC-006
- **Componente:** historico-api | source/api/historico/routes.py
- **Módulo:** APP
- **Depende de:** TASK-017, TASK-018
- **Alcance:** Crear el contrato OpenAPI `docs/contracts/openapi/api-historico.yaml` que formaliza los endpoints de consulta de altas, cierres y resumen diario del histórico tal como quedaron implementados: consulta de altas por rango de `fecha_alta`, consulta de cierres por rango de `fecha_cierre`, consulta de cierres por rango de `fecha_fin_difusion` y resumen diario, con el esquema de oferta que incluye los campos mínimos exigidos por REQ-002 y REQ-012.
- **Hecho cuando:** el contrato existe en `docs/contracts/openapi/api-historico.yaml`, describe las operaciones con sus parámetros de rango y sus esquemas de entrada y salida, y coincide con la implementación verificada en TASK-018.
- **Pruebas automáticas:**
  - El YAML del contrato se carga correctamente y contiene las cuatro operaciones con sus respuestas 200.
  - El esquema de oferta del contrato incluye comunidad, código, ocupación, municipio, estado, `fecha_alta`, `fecha_fin_difusion` y `fecha_cierre`.
  - El esquema del resumen diario incluye la fecha y los números de altas y de cierres.
  - Los parámetros de rango de fechas y las rutas del contrato coinciden con los que devuelve la implementación en la prueba de integración.
  - El contrato documenta que los códigos se devuelven como texto de 12 dígitos y las fechas de difusión en `dd/mm/aaaa`.
- **Prueba manual:**
  1. Revisar el contrato y comprobar que aparecen las cuatro interfaces de la fila de contratos afectados.
  2. Comparar el contrato con las respuestas JSON reales obtenidas en TASK-018 y confirmar que no hay campos divergentes.

### [ ] TASK-020 Contrato: configuración - fichero de configuración del histórico

- **Cubre:** REQ-005, REQ-008, NFR-001, NFR-003, SUP-001, SUP-002, DEC-001, DEC-005
- **Componente:** config-historico | config/historico.yaml
- **Módulo:** APP
- **Depende de:** TASK-002, TASK-016
- **Alcance:** Formalizar el contrato de configuración del histórico: documentar el formato exacto del fichero `config/historico.yaml` (zona horaria, hora de ejecución, número de ausencias consecutivas, umbral de caída del recuento, recuento mínimo, ruta del SQLite propio, ruta del SQLite de `api-persistencia` en solo lectura, URL base del buscador y de la API de persistencia, y comunidad e identificador del PDF de difusión) y sus valores por defecto, dejándolo alineado con lo que la carga de TASK-002 interpreta y con lo que la aplicación aplica en TASK-016.
- **Hecho cuando:** el formato queda documentado, el fichero real lo cumple sin ambigüedad y una configuración válida se carga y se aplica sin cambios de código.
- **Pruebas automáticas:**
  - El fichero `config/historico.yaml` se carga con el formato documentado y devuelve la zona horaria, la hora, los tres umbrales y las rutas.
  - Una configuración sin los campos obligatorios se rechaza con un error controlado que identifica el campo ausente.
  - Una configuración con un tipo incorrecto o con una zona horaria inválida se rechaza con un error controlado, conforme a NFR-001.
  - Los valores por defecto documentados (zona `Europe/Madrid`, `2` ausencias, `30` % de caída, `70` de recuento mínimo, `data/job_emcan_historico.db` y `data/job_emcan.db`) coinciden con los que aplica la implementación.
  - El contrato documenta que la ruta del SQLite de persistencia se usa en modo solo lectura, conforme a DEC-006.
  - El contrato no documenta ninguna ruta de servidor de base de datos ni credenciales.
- **Prueba manual:**
  1. Revisar que la fila de contrato (configuración del histórico) queda descrita con el mismo formato que usa el fichero real.
  2. Modificar el fichero siguiendo solo el formato documentado y comprobar que la aplicación arranca con la nueva configuración.

### [ ] TASK-021 Actualización del mapa de arquitectura

- **Cubre:** DEC-001, DEC-002, DEC-003, DEC-004, DEC-005, DEC-006
- **Componente:** api-service | source/api
- **Módulo:** APP
- **Depende de:** TASK-018, TASK-019, TASK-020
- **Alcance:** Actualizar `.sdd/architecture.md` en tres puntos y solo en esos tres: (a) la línea del módulo `API`, cuya responsabilidad pasa a incluir también el histórico de altas y cierres de ofertas; (b) añadir a la sección de contratos la entrada `openapi | docs/contracts/openapi/api-historico.yaml | cliente -> api-historico`; y (c) añadir a la sección de contratos la entrada `configuracion | config/historico.yaml | api-historico -> config-historico`. El mapa **no** gana entradas de módulo para los componentes internos del histórico, que son detalle de implementación dentro del módulo `API` y no reciben identificador propio en el mapa.
- **Hecho cuando:** la línea del módulo `API` de `.sdd/architecture.md` menciona el histórico de altas y cierres en su responsabilidad; la sección de contratos contiene las dos entradas nuevas (`openapi` del histórico y `configuracion` de `config/historico.yaml`); y la sección de módulos no contiene ninguna entrada nueva para los componentes internos del histórico.
- **Pruebas automáticas:**
  - Una comprobación lee `.sdd/architecture.md` y confirma que la línea del módulo `API` incluye el histórico de altas y cierres en su descripción de responsabilidad.
  - Una comprobación confirma que la sección de contratos incluye la entrada `openapi | docs/contracts/openapi/api-historico.yaml | cliente -> api-historico`.
  - Una comprobación confirma que la sección de contratos incluye la entrada `configuracion | config/historico.yaml | api-historico -> config-historico`.
  - Una comprobación confirma que la sección de módulos no ha ganado entradas para los componentes internos del histórico (adaptadores, evaluadores, repositorios, migrador, conexión y tarea programada) ni para el subpaquete `source/api/historico`.
  - Todos los ficheros citados en el mapa existen en el repositorio.
- **Prueba manual:**
  1. Revisar `.sdd/architecture.md` y comprobar que la línea del módulo `API` incluye el histórico en su responsabilidad y que la sección de contratos contiene las dos entradas nuevas.
  2. Revisar la sección de módulos del mapa y comprobar que no se ha añadido ninguna entrada para los componentes internos del histórico.

## Cobertura

| Requisito | Tareas |
|---|---|
| REQ-001 | TASK-001, TASK-009, TASK-010, TASK-015, TASK-017, TASK-018, TASK-019 |
| REQ-002 | TASK-010, TASK-017, TASK-018, TASK-019 |
| REQ-003 | TASK-009, TASK-012, TASK-015, TASK-018 |
| REQ-004 | TASK-012, TASK-013, TASK-015, TASK-018 |
| REQ-005 | TASK-002, TASK-004, TASK-005, TASK-009, TASK-011, TASK-013, TASK-015, TASK-018, TASK-020 |
| REQ-006 | TASK-006, TASK-008, TASK-015, TASK-016, TASK-018 |
| REQ-007 | TASK-006, TASK-008, TASK-013, TASK-015, TASK-018 |
| REQ-008 | TASK-002, TASK-005, TASK-006, TASK-008, TASK-014, TASK-015, TASK-018, TASK-020 |
| REQ-009 | TASK-009, TASK-012, TASK-013, TASK-015, TASK-018 |
| REQ-010 | TASK-001, TASK-009, TASK-012, TASK-013, TASK-015, TASK-018 |
| REQ-011 | TASK-004, TASK-006, TASK-013, TASK-014, TASK-015, TASK-016, TASK-018 |
| REQ-012 | TASK-009, TASK-010, TASK-015, TASK-017, TASK-018, TASK-019 |

| Requisito no funcional | Tareas |
|---|---|
| NFR-001 | TASK-002, TASK-007, TASK-012, TASK-015, TASK-016, TASK-018, TASK-020 |
| NFR-002 | TASK-004, TASK-007, TASK-015, TASK-016, TASK-018 |
| NFR-003 | TASK-002, TASK-005, TASK-013, TASK-014, TASK-015, TASK-018, TASK-020 |

| Decisión | Tareas |
|---|---|
| DEC-001 | TASK-001, TASK-002, TASK-003, TASK-004, TASK-005, TASK-006, TASK-007, TASK-015, TASK-016, TASK-018, TASK-020, TASK-021 |
| DEC-002 | TASK-011, TASK-015, TASK-016, TASK-018, TASK-021 |
| DEC-003 | TASK-001, TASK-008, TASK-009, TASK-015, TASK-018, TASK-021 |
| DEC-004 | TASK-005, TASK-013, TASK-015, TASK-018, TASK-021 |
| DEC-005 | TASK-002, TASK-005, TASK-006, TASK-012, TASK-013, TASK-014, TASK-015, TASK-018, TASK-020, TASK-021 |
| DEC-006 | TASK-010, TASK-017, TASK-018, TASK-019, TASK-020, TASK-021 |

| Supuesto | Tareas |
|---|---|
| SUP-001 | TASK-002, TASK-011, TASK-013, TASK-015, TASK-016, TASK-018, TASK-020 |
| SUP-002 | TASK-001, TASK-008, TASK-009, TASK-010, TASK-011, TASK-015, TASK-016, TASK-017, TASK-018, TASK-019, TASK-020 |
| SUP-003 | TASK-003, TASK-004, TASK-005, TASK-006, TASK-007, TASK-009, TASK-010, TASK-013, TASK-014, TASK-015, TASK-016, TASK-017, TASK-018 |

| Escenario alternativo | Tareas |
|---|---|
| ALT-001 | TASK-008, TASK-015, TASK-016, TASK-018 |
| ALT-002 | TASK-014, TASK-015, TASK-018 |
| ALT-003 | TASK-013, TASK-015, TASK-018 |
| ALT-004 | TASK-011, TASK-013, TASK-015, TASK-018 |
| ALT-005 | TASK-012, TASK-015, TASK-018 |
| ALT-006 | TASK-007, TASK-015, TASK-018 |
| ALT-007 | TASK-005, TASK-013, TASK-015, TASK-018 |
| ALT-008 | TASK-008, TASK-015, TASK-016, TASK-018 |
| ALT-009 | TASK-009, TASK-015, TASK-016, TASK-018 |

## Avisos

- La estrategia de contratos aplicada es `implementation-first`, valor tomado de la opción `contract-strategy` de `.sdd/team.md`. Por eso TASK-019 depende de TASK-017 y TASK-018, y TASK-020 depende de TASK-002 y TASK-016.
- No existe `.sdd/task-types.md`, así que no hay tipos de tarea propios del proyecto que generar.
- Los componentes del histórico (`api-historico`, `config-historico`, `db-connection-historico`, `schema-migrator-historico`, `buscador-status-adapter`, `persistencia-adapter`, `historico-read-adapter`, `pdf-listado-adapter`, `cierre-fecha-evaluator`, `desaparicion-evaluator`, `recuento-guardian`, `historico-presencia-repository`, `abstenciones-repository`, `ejecucion-repository`, `historico-task` y `historico-api`) son **detalle de implementación interno del módulo `API`**: no reciben identificador propio en `.sdd/architecture.md` y no se proponen como módulos nuevos del mapa, conforme a `design@3`. Las tareas que los implementan los citan en su línea `Componente` (con la ruta interna dentro de `source/api/historico/`) y llevan su línea `Módulo` con el identificador `APP`, que es la etiqueta del trabajo; el código permanece en `source/api/historico/`.
- TASK-021 no registra módulos nuevos del histórico. Su alcance se limita a actualizar la línea del módulo `API` de `.sdd/architecture.md` para que su responsabilidad incluya el histórico de altas y cierres, a añadir las dos entradas de contrato (`openapi | docs/contracts/openapi/api-historico.yaml | cliente -> api-historico` y `configuracion | config/historico.yaml | api-historico -> config-historico`) y a comprobar que el mapa no gana entradas de módulo para los componentes internos del histórico.
- `api-buscador`, `api-persistencia` y `api-pdf-parser` no se modifican en ninguna tarea. La compatibilidad se resuelve solo desde `api-historico`: lectura del contrato `GET /buscador/status` (TASK-008), llamadas a `persistencia-api` (`POST /persistencia/ofertas`, `GET /persistencia/ofertas/vigentes`, `GET /persistencia/ofertas/{comunidad}/{codigo}`) (TASK-009), lectura en modo solo lectura `mode=ro` de `data/job_emcan.db` (TASK-010) e invocación en proceso de `source/api/parser.py` y `source/api/downloader.py` (TASK-011), conforme a SUP-001, SUP-002, SUP-003 y DEC-002, DEC-003, DEC-006.
- `persistencia-api` no expone lecturas por rango de fechas ni listados históricos; el hueco está resuelto con `historico-read-adapter` en modo `mode=ro` sobre `data/job_emcan.db`, conforme a SUP-004 y DEC-006. TASK-010 verifica explícitamente que la conexión es de solo lectura y que la marca de modificación del fichero no cambia.
- El diseño deja abierto el mecanismo concreto del planificador en proceso (biblioteca o temporizador propio). TASK-015 y TASK-016 se limitan al comportamiento exigible: ejecución diaria a la hora configurada, una sola vez por día, cancelación limpia al apagar y convivencia con el planificador de `api-buscador`, la `ingestion-task` y la `purge-task` en el mismo proceso FastAPI sin modificarlos.
- El diseño no fija el prefijo de las rutas de `historico-api`. Se adopta por defecto el prefijo `/historico`; si la capa técnica adopta otro, el cambio queda limitado a TASK-017, TASK-018 y TASK-019.
- El diseño no fija la granularidad de la serie de recuentos ni el número de días que se conservan los registros de presencia. TASK-005 se limita a lo exigible: registrar el recuento de cada pasada, devolver el recuento anterior y permitir contar las ausencias consecutivas por código desde el histórico de presencia.
- El modelo de datos lógico del diseño enumera `PresenciaEnListado`, `SerieDeRecuento`, `AbstencionDeCierre` y `EjecucionDiaria` sin fijar nombres de tabla ni de columna. TASK-004 los materializa en cuatro tablas propias del SQLite del histórico; los nombres concretos quedan para el analista técnico.
- El diseño sitúa la serie de recuentos en un componente propio (`historico-presencia-repository` según la lista de componentes y la tabla de interfaces) pero no la nombra de forma explícita. TASK-005 la implementa dentro de `historico-presencia-repository` para no crear un componente no previsto; si la capa técnica prefiere un componente separado, el cambio queda limitado a TASK-005, TASK-014 y TASK-021 (que solo documenta el contrato y la descripción del módulo `API`).
- El requisito REQ-001 y la decisión SUP-003 se verifican por la vía negativa: `api-historico` no tiene ninguna operación de creación de ofertas y toda actualización de estado pasa por `persistencia-adapter`. TASK-009 comprueba que el cliente no expone creación de ofertas nuevas y TASK-015 y TASK-018 comprueban que ninguna ejecución crea ofertas ni altera `fecha_alta`.
- La fila "Llamada interna / Contrato de uso del parser del PDF (existente)" de "Contratos afectados" se cubre con TASK-011, que documenta el contrato de uso en proceso como dependencia interna y no modifica `api-pdf-parser`. La fila "SQLite (solo lectura) / Esquema documentado de `api-persistencia`" se cubre con TASK-010, que fija el uso de `mode=ro` sobre el esquema documentado de la tabla `ofertas`; ninguna de las dos filas genera un fichero de contrato nuevo.
- La fila "HTTP/OpenAPI / `docs/contracts/openapi/api-persistencia.yaml` (existente)" declara que el contrato no se modifica: ninguna tarea toca `api-persistencia` ni su contrato.
- El documento contiene 21 tareas (TASK-001..TASK-021); la numeración es continua y no hay huecos. El apartado "Orden de implementación" los agrupa en 10 pasos numerados, cada uno con las tareas que encadenan.
