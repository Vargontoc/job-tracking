# Sprint 05: api-integridad - api

Estado: aprobado

## Alcance

- Tareas: TASK-001, TASK-002, TASK-003, TASK-004, TASK-005, TASK-006, TASK-007, TASK-008, TASK-009, TASK-010, TASK-011, TASK-012, TASK-013, TASK-014, TASK-015, TASK-016, TASK-017, TASK-018, TASK-019, TASK-020, TASK-021 (de `specs/api-integridad/tasks.md`)
- Dependencias internas: TASK-002←TASK-001; TASK-003←TASK-002; TASK-004←TASK-003; TASK-005←TASK-004; TASK-006←TASK-002; TASK-007←TASK-006; TASK-008←TASK-002; TASK-009←TASK-007,TASK-008; TASK-010←TASK-003; TASK-011←TASK-003; TASK-012←TASK-005,TASK-006,TASK-007,TASK-008,TASK-009,TASK-010,TASK-011; TASK-013←TASK-012; TASK-014←TASK-002,TASK-012,TASK-013; TASK-015←TASK-009,TASK-011; TASK-016←TASK-011; TASK-017←TASK-004; TASK-018←TASK-014,TASK-015,TASK-016,TASK-017; TASK-019←TASK-015,TASK-016,TASK-017,TASK-018; TASK-020←TASK-002,TASK-014; TASK-021←TASK-018,TASK-019,TASK-020.
- Dependencias externas:
  - `api-pdf-parser` (Sprint 01 aprobado, `docs/sprints/api/api-pdf-parser.md`) — condición de entrega: `source/api/downloader.py` (`descargar_pdf(url, *, cliente=None) -> bytes | ErrorDescarga`) y `source/api/parser.py` (`extraer_texto_pdf`, `extraer_ofertas`, `extraer_ofertas_desde_pdf`) importables e invocables en proceso, sin modificar `source/api/parser.py`, `source/api/downloader.py` ni `source/api/assembler.py`. La consumen TASK-006 y TASK-007.
  - `api-buscador` (Sprint 02 aprobado, `docs/sprints/api/api-buscador.md`) — condición de entrega: `GET /buscador/status` implementado y respondiendo con `in_progress`, `progreso` y `ultima_pasada` (`timestamp`, `comunidad`, `total_listado`, `error_global`, `errores_por_oferta`), sin modificar `source/api/buscador/**`. La consumen TASK-008, TASK-014 y TASK-018.
  - `api-persistencia` (Sprint 03 aprobado, `docs/sprints/api/api-persistencia.md`) — condición de entrega: `ingestion-task` y `purge-task` arrancadas desde el `lifespan` de `source/api/main.py` con su conexión SQLite `data/job_emcan.db`, sin modificar `source/api/persistencia/**`. Convive en el mismo proceso; la consumen TASK-014 y TASK-018 (comprobación de no regresión).
  - `api-historico` (Sprint 04 aprobado, `docs/sprints/api/api-historico.md`) — condición de entrega: `historico-task` y su router registrados en el `lifespan` de `source/api/main.py`, con su conexión `data/job_emcan_historico.db`, sin modificar `source/api/historico/**`. Convive en el mismo proceso; la consumen TASK-014 y TASK-018 (orden de apagado y endpoints intactos).

## Origen SDD

- Requirements: 2
- Design: 3
- Tasks: 1

## Resumen

Se añade al proceso FastAPI existente el subpaquete `source/api/integridad/` con la comprobación diaria del PDF oficial de difusión: configuración propia (`config/integridad.yaml`), almacén de PDFs y metadatos sobre el sistema de archivos (`data/pdfs/<comunidad>/<aaaa-mm-dd>.pdf` + `.meta.json`), tres adaptadores (descarga y parseo del PDF invocados **en proceso** sobre `source/api/downloader.py` y `source/api/parser.py`, y cliente HTTP de `GET /buscador/status`), un comparador de recuentos con veredicto informativo, un almacén de avisos, un índice de ejecuciones en JSON, una tarea diaria en hilo propio y tres endpoints de consulta bajo el prefijo `/integridad`.

- Sin SQLite propio y sin base vectorial: la fuente de verdad del día es el `.meta.json` junto al PDF y el índice es `data/pdfs/ejecuciones.json` (DEC-001, DEC-003, DEC-004).
- Sin dependencias nuevas: `httpx`, `pdfplumber`, `PyYAML` y `tzdata` ya están en `pyproject.toml`; `zoneinfo`, `threading`, `hashlib`, `json` y `datetime` son de la stdlib. Planificador con `threading` + reloj inyectable (`RelojProtocol`/`RelojReal` locales del subpaquete, sin importar de `api-historico`), coherente con los sprints 02, 03 y 04.
- Sin notificaciones externas: los avisos son registros consultables dentro del `.meta.json` (SUP-007).
- No se modifica `api-buscador`, `api-persistencia`, `api-pdf-parser` ni `api-historico`: la integración es por contrato HTTP, por invocación en proceso y por convivencia de tareas programadas (SUP-002, SUP-004, SUP-005, DEC-006).
- Los componentes de la integridad son detalle interno del módulo `API` y no reciben identificador en el mapa: TASK-021 solo actualiza la línea de `API` y añade los dos contratos nuevos.
- Contratos `implementation-first`: TASK-019 tras TASK-018, TASK-020 tras TASK-002/TASK-014 y TASK-021 al final.

## Tareas

### TASK-001 Estructura del paquete de la integridad y dependencias

- **Cubre:** REQ-001, REQ-002, SUP-003, SUP-005, DEC-001, DEC-003
- **Componente:** integridad-task | `source/api/integridad`
- **Depende de:** -
- **Ficheros:** `source/api/integridad/__init__.py` (nuevo) — subpaquete importable; `source/api/integridad/{config,pdf_store,purger,downloader_adapter,parser_adapter,buscador_client,comparador,avisos,ejecuciones,task,routes}.py` (nuevos) — un módulo hosting por componente del diseño, creado como esqueleto con solo docstring y rellenado en su tarea; `pyproject.toml` (sin cambios: `httpx`, `pdfplumber`, `PyYAML` y `tzdata` ya declarados; `zoneinfo`, `threading`, `hashlib`, `json`, `datetime` y `pathlib` son stdlib).
- **Enfoque:** replicar la disposición de `source/api/historico/` (un módulo por componente, docstring de cabecera, sin estado global compartido). No se declara ninguna dependencia nueva ni se introduce motor de base de datos servidor, extensión vectorial de SQLite ni biblioteca externa de *scheduling*. El paquete no importa ni escribe nada de `source/api/buscador/`, `source/api/persistencia/`, `source/api/historico/`, `source/api/parser.py`, `source/api/downloader.py` ni `source/api/assembler.py`; en las tareas siguientes solo se *importan* las funciones públicas de descarga y parseo.
- **Alcance:** crear el subpaquete y los módulos hosting de los componentes del diseño y declarar en `pyproject.toml` las dependencias que exige el diseño (`httpx`, `pdfplumber`, `pyyaml`, zona horaria estándar y mecanismo de planificación en proceso), sin motor de base de datos servidor ni extensión vectorial.
- **Hecho cuando:** el subpaquete `source/api/integridad` se importa sin errores, las dependencias declaradas cubren las que usa el diseño y el runner de pruebas recorre `tests/` sin fallos de colección; y el paquete no altera `api-buscador`, `api-persistencia`, `api-pdf-parser` ni `api-historico`.
- **Pruebas automáticas:** `tests/unit/test_integridad_imports.py` (nuevo) — importar `source.api.integridad` no lanza error; `httpx`, `pdfplumber`, `yaml` y `zoneinfo.ZoneInfo` están disponibles; el paquete no importa SQLAlchemy, PostgreSQL, MySQL ni extensiones vectoriales; no escribe ni modifica ficheros bajo `source/api/buscador/`, `source/api/persistencia/`, `source/api/historico/`, `source/api/parser.py`, `source/api/downloader.py` ni `source/api/assembler.py` (SUP-005); no crea ni abre ningún fichero SQLite (DEC-001). Comando: `pytest tests/unit/test_integridad_imports.py`.
- **Prueba manual:** instalar en un venv limpio (`pip install -e .`) y ejecutar `pytest`: termina sin fallos por dependencias ausentes ni por colección.

### TASK-002 Fichero de configuración de la integridad

- **Cubre:** REQ-001, REQ-002, REQ-003, NFR-001, NFR-002, NFR-004, SUP-001, SUP-003, DEC-001, DEC-005, DEC-007
- **Componente:** config-integridad | `config/integridad.yaml`
- **Depende de:** TASK-001
- **Ficheros:** `config/integridad.yaml` (nuevo) — valores de la integridad con cabecera de contrato al estilo de `config/historico.yaml`; `source/api/integridad/config.py` (nuevo) — dataclass `ConfigIntegridad` (con submapas opcionales `rutas` y `buscador`), excepción `ErrorConfiguracionIntegridad` y `cargar_configuracion(ruta=Path("config/integridad.yaml"))`.
- **Enfoque:** copiar el patrón de `source/api/historico/config.py` y `source/api/config.py`: lectura con `yaml.safe_load`, fichero ausente → `ConfigIntegridad` con valores por defecto, y error controlado que nombra el campo problemático para YAML malformado, raíz que no sea mapa, submapa que no sea mapa, tipo incorrecto (los enteros no admiten booleanos), zona horaria inválida (`zoneinfo.ZoneInfo`), hora fuera de `0-23`, hora con minutos/fracciones/lista, `margen_catchup` negativo o no entero, tolerancias o umbral negativos. Campos y valores por defecto: `zona_horaria="Europe/Madrid"`, `hora_ejecucion=2` (02:00, posterior a la pasada del buscador de las 01:00 en `config/buscador.yaml`), `margen_catchup=60`, `dias_retencion=30`, `tolerancia_absoluta=1`, `tolerancia_relativa_pct=5`, `umbral_cordura=70`, `rutas.base_pdfs="data/pdfs"`, `buscador.url_base="http://localhost:8000"` y `comunidades`. Si `comunidades` no se declara en el fichero, se reutiliza `source.api.config.cargar_comunidades()` (que devuelve `list[ComunidadConfigurada]` con `identificador` y `url_pdf`) en lugar de duplicar la carga de `config/comunidades.yaml`. Rutas relativas a la raíz del proyecto; sin rutas de servidor de BD ni credenciales.
- **Alcance:** crear el fichero con zona horaria, hora de ejecución, margen de catch-up, días de retención, tolerancia absoluta, tolerancia relativa, umbral de cordura, ruta base de PDFs, URL base del buscador y comunidades, e implementar su carga con valores por defecto y error controlado ante fichero ausente o malformado.
- **Hecho cuando:** la carga devuelve la configuración completa con los valores por defecto cuando no se indican otros; un fichero ausente o malformado produce un error controlado que identifica la configuración como origen; la zona horaria cargada es válida y utilizable para obtener la fecha local; la hora es un entero en 0-23, el margen de catch-up es un entero ≥ 0 y las rutas son relativas a la raíz del proyecto.
- **Pruebas automáticas:** `tests/unit/test_integridad_config.py` (nuevo) — la carga completa devuelve zona horaria, hora, margen, días de retención, dos tolerancias, umbral, ruta base, URL base y comunidades; sin fichero → `Europe/Madrid`, `2`, `60`, `30`, `1`, `5`, `70` (NFR-001, NFR-002, SUP-001, DEC-007); YAML malformado, submapa no mapa o tipo incorrecto → error que identifica el campo; zona horaria inválida → error que la identifica (NFR-004); hora `24`, con minutos, con fracciones o como lista → error que la identifica (NFR-001); margen negativo o no entero → error (DEC-007); umbral o tolerancia negativos → error (NFR-002); la configuración no contiene rutas de servidor de BD ni credenciales. Comando: `pytest tests/unit/test_integridad_config.py`.
- **Prueba manual:** abrir `config/integridad.yaml` y comprobar los campos con sus valores por defecto; cambiar la hora a `5` y el margen a `30`, recargar y comprobar que se aplican los nuevos valores.

### TASK-003 Almacén de PDFs y de metadatos del día

- **Cubre:** REQ-002, REQ-005, NFR-003, SUP-001, SUP-003, DEC-001, DEC-002, DEC-003, ALT-003, ALT-007
- **Componente:** pdf-store | `source/api/integridad/pdf_store.py`
- **Depende de:** TASK-002
- **Ficheros:** `source/api/integridad/pdf_store.py` (nuevo) — `AlmacenPDFs(base, zona_horaria)` con `ruta_pdf(comunidad, fecha)`, `ruta_meta(comunidad, fecha)`, `guardar_pdf(...) -> MetaDia`, `escribir_meta(...)`, `leer_meta(...)` y `escribir_fallido(comunidad, fecha, motivo)`.
- **Enfoque:** el árbol se resuelve siempre por `<base>/<comunidad>/<aaaa-mm-dd>.pdf` y su `<aaaa-mm-dd>.meta.json` (SUP-003); el directorio de la comunidad se crea si no existe. Escritura atómica en ambos casos: fichero temporal en el **mismo** directorio y `os.replace`/`Path.replace` al nombre definitivo, con limpieza del temporal ante excepción. Hash con `hashlib.sha256` sobre el contenido (DEC-003). El `.meta.json` es un diccionario JSON con `hash`, `recuento_pdf`, `recuento_buscador`, `diferencia`, `tolerancia_absoluta`, `tolerancia_relativa_pct`, `umbral_cordura`, `veredicto`, `errores`, `avisos` y `timestamp` (REQ-005); el estado del día se expresa con el veredicto (`ok`/`concordante`, `divergente`, `fallido`). Un `.meta.json` ilegible se comunica con un resultado controlado propio (no se devuelve un día válido) y se deja intacto. Ningún fichero SQLite.
- **Alcance:** implementar el almacén que gestiona el árbol de PDFs y metadatos, la escritura atómica del PDF y del `.meta.json`, el hash SHA-256 y la escritura de un `.meta.json` en estado `fallido` cuando la descarga falla, sin conservar PDF.
- **Hecho cuando:** tras guardar un PDF existen el `.pdf` y su `.meta.json` con el hash y los campos del día; el PDF queda visible en el nombre definitivo solo tras el `rename`, sin temporales remanentes; un `.meta.json` en estado `fallido` existe sin PDF asociado; y el hash guardado coincide con el SHA-256 del contenido.
- **Pruebas automáticas:** `tests/unit/test_integridad_pdf_store.py` (nuevo) — existe `data/pdfs/<comunidad>/<aaaa-mm-dd>.pdf` con fecha y comunidad identificables (REQ-002, SUP-003); el hash del `.meta.json` coincide con el SHA-256 del contenido (DEC-003); escritura atómica del PDF y del `.meta.json` sin temporales remanentes y con JSON válido (DEC-001); `.meta.json` `fallido` con mensaje sin PDF asociado (ALT-003, DEC-002); el `.meta.json` incluye hash, recuentos, diferencia, tolerancias, umbral, veredicto, errores y timestamp (REQ-005); lectura de un `.meta.json` corrupto se comunica y no se interpreta como día válido; no se crea ningún fichero SQLite (DEC-001); el directorio de la comunidad se crea si no existe. Todas las pruebas sobre `tmp_path`. Comando: `pytest tests/unit/test_integridad_pdf_store.py`.
- **Prueba manual:** guardar un PDF de prueba y revisar `data/pdfs/<comunidad>/`: aparecen el PDF y el `.meta.json` con el hash, y no queda ningún fichero temporal.

### TASK-004 PDF huérfano y listado de PDFs conservados

- **Cubre:** REQ-002, REQ-005, REQ-009, SUP-003, DEC-002, ALT-007
- **Componente:** pdf-store | `source/api/integridad/pdf_store.py`
- **Depende de:** TASK-003
- **Ficheros:** `source/api/integridad/pdf_store.py` (modificar) — añadir `detectar_huerfano(comunidad, fecha) -> bool`, `regenerar_meta(comunidad, fecha, meta)` y `listar_conservados() -> list[PdfConservado]`.
- **Enfoque:** el día está incompleto cuando existe el `.pdf` y no el `.meta.json` (ALT-007): se informa del estado y se permite recalcular el hash desde el PDF y generar el `.meta.json` con los campos del día, sin escribir el PDF. `listar_conservados()` recorre `<base>/<comunidad>/` con `Path.glob("*.pdf")`, extrae fecha y comunidad, y adjunta el `.meta.json` cuando existe; un `.meta.json` ilegible se omite en la parte de metadatos pero **no** excluye el PDF; un directorio de comunidad inexistente o vacío devuelve lista vacía sin error.
- **Alcance:** implementar sobre el mismo almacén la detección y el tratamiento del PDF huérfano y el listado de PDFs conservados con fecha, comunidad y ruta identificable.
- **Hecho cuando:** ante un PDF del día sin `.meta.json` el almacén informa de que el día está incompleto y permite regenerar metadatos; el listado devuelve un elemento por cada `<aaaa-mm-dd>.pdf` con fecha, comunidad y ruta; y un `.meta.json` ilegible no impide listar el resto.
- **Pruebas automáticas:** `tests/unit/test_integridad_pdf_store_listado.py` (nuevo) — PDF sin `.meta.json` detectado como huérfano (ALT-007); metadatos regenerados con hash recalculado y campos del día; listado con un elemento por PDF con fecha, comunidad y ruta (REQ-009); `.meta.json` ilegible omitido del listado de metadatos sin impedir listar los PDFs; directorio de comunidad vacío o inexistente → lista vacía sin error; sin ficheros SQLite (DEC-001). Comando: `pytest tests/unit/test_integridad_pdf_store_listado.py`.
- **Prueba manual:** colocar un PDF suelto sin `.meta.json` en el directorio de una comunidad y ejecutar el listado: aparece como PDF conservado y se informa del día incompleto.

### TASK-005 Purga de PDFs por la fecha del nombre

- **Cubre:** REQ-002, SUP-003, DEC-002, DEC-004
- **Componente:** pdf-purger | `source/api/integridad/purger.py`
- **Depende de:** TASK-004
- **Ficheros:** `source/api/integridad/purger.py` (nuevo) — `purgar(base, dias_retencion, hoy) -> list[Path]` (devuelve lo eliminado) y helper `_fecha_del_nombre(nombre)`.
- **Enfoque:** recorrer `<base>/<comunidad>/` y decidir por la fecha **del nombre** (`datetime.date.fromisoformat` sobre el `stem`, exigiendo el patrón `<aaaa-mm-dd>`), nunca por `mtime` (DEC-004). Se eliminan `.pdf` y `.meta.json` cuando `(hoy - fecha).days > dias_retencion`; se conservan los de antigüedad exactamente igual a la retención (ventana inclusiva) y siempre el día en curso (`fecha >= hoy`). Los nombres que no siguen el patrón se ignoran. El `.meta.json` se identifica por el mismo `stem`, de modo que el `.pdf` con parseo fallido y sus metadatos se purgan con el mismo plazo (DEC-002). `hoy` se recibe como parámetro (la tarea diaria lo calcula con la zona configurada). Sin SQLite.
- **Alcance:** implementar la purga del árbol de PDFs y metadatos por fecha del nombre más antigua que la retención configurada, sin eliminar el día en curso ni los de la ventana.
- **Hecho cuando:** tras la purga no queda ningún PDF ni `.meta.json` anterior a la ventana; se conservan los de 30 días o menos; el día en curso se conserva siempre; y la antigüedad se determina por el nombre aunque el `mtime` sea reciente.
- **Pruebas automáticas:** `tests/unit/test_integridad_purger.py` (nuevo) — más de 30 días → elimina `.pdf` y `.meta.json` (REQ-002); exactamente 30 días → conserva; menos de 30 → conserva; el día en curso nunca se elimina; fichero antiguo con `mtime` reciente se elimina (DEC-004); con `dias_retencion=7` se aplica ventana de 7 días; el `.pdf` con parseo fallido y su `.meta.json` se purgan igual (DEC-002); nombres fuera del patrón no se tocan (DEC-004); sin ficheros SQLite (DEC-001). Comando: `pytest tests/unit/test_integridad_purger.py`.
- **Prueba manual:** preparar PDFs con nombres de hace 40, 30 y 5 días y ejecutar la purga: solo desaparece el de 40 días.

### TASK-006 Adaptador de descarga del PDF de difusión

- **Cubre:** REQ-001, REQ-002, SUP-003, SUP-005, DEC-002, ALT-003
- **Componente:** downloader-adapter | `source/api/integridad/downloader_adapter.py`
- **Depende de:** TASK-002
- **Ficheros:** `source/api/integridad/downloader_adapter.py` (nuevo) — `AdaptadorDescarga(descargador=source.api.downloader.descargar_pdf, cliente=None)` con `descargar(url) -> bytes | ErrorDescargaIntegridad`.
- **Enfoque:** delegar en `source.api.downloader.descargar_pdf(url, cliente=...)` (que ya devuelve `bytes | ErrorDescarga` con `mensaje`), sin reimplementar la descarga y sin emitir peticiones HTTP a la propia API (SUP-005); el adaptador no escribe en disco: devuelve los bytes al llamante (la escritura es de `pdf-store`). El descargador es inyectable para las pruebas (cliente `httpx` de prueba o doble del propio descargador). `ErrorDescarga` se propaga como error controlado distinguible —error HTTP, tiempo de espera o conexión comparten la forma `ErrorDescarga.mensaje`, que es lo que necesita ALT-003— sin lanzar excepción. La URL `url_pdf` de cada comunidad viene de su entrada en `config/comunidades.yaml`.
- **Alcance:** implementar el adaptador que descarga el PDF de difusión de una comunidad invocando en proceso `source/api/downloader.py` y normaliza su resultado para el almacén, sin llamar al endpoint `GET /parse` ni descargar fichas.
- **Hecho cuando:** con un descargador simulado que devuelve bytes, el adaptador devuelve esos bytes sin escribir en disco; con un error controlado lo propaga de forma distinguible sin lanzar excepción; y no emite ninguna petición HTTP a `GET /parse`.
- **Pruebas automáticas:** `tests/unit/test_integridad_downloader_adapter.py` (nuevo) — cliente de prueba con PDF válido → devuelve los bytes (REQ-001); error HTTP → error controlado con mensaje (ALT-003); timeout y error de conexión → error controlado distinguible (ALT-003); no se realiza ninguna llamada HTTP a `GET /parse` ni a otro endpoint de la API (SUP-005); no modifica `source/api/downloader.py` ni `source/api/assembler.py`; no descarga fichas del buscador. Comando: `pytest tests/unit/test_integridad_downloader_adapter.py`.
- **Prueba manual:** invocar el adaptador con la URL real del PDF de difusión y comprobar que devuelve los bytes y que en el registro no aparece ninguna petición a `/parse`.

### TASK-007 Adaptador de parseo del PDF de difusión

- **Cubre:** REQ-003, REQ-004, SUP-003, SUP-005, DEC-002, ALT-004
- **Componente:** parser-adapter | `source/api/integridad/parser_adapter.py`
- **Depende de:** TASK-006
- **Ficheros:** `source/api/integridad/parser_adapter.py` (nuevo) — `AdaptadorParseo(extractor_texto=source.api.parser.extraer_texto_pdf, extractor_ofertas=source.api.parser.extraer_ofertas)` con `parsear(contenido, comunidad) -> RecuentoPDF | ErrorParseoIntegridad`.
- **Enfoque:** invocar **en proceso** `source/api/parser.py` sin llamada HTTP a `GET /parse` (SUP-005) y sin reescribir parseo. `extraer_ofertas_desde_pdf` devuelve `[]` tanto con PDF válido sin ofertas como con PDF ilegible (captura `ErrorParseoPDF` y lo convierte en lista vacía), por lo que el adaptador compone las dos funciones públicas: `extraer_texto_pdf(contenido)` (que **sí** lanza `ErrorParseoPDF`) y después `extraer_ofertas(texto, comunidad)`. Así se distingue ALT-004 (PDF ilegible → error controlado, veredicto `fallido`) de un PDF válido con cero ofertas (recuento `0` sin error, que el comparador resolverá por umbral de cordura). `ErrorParseoPDF` se traduce a un error de parseo propio, distinguible del error de descarga de TASK-006, sin propagar excepción.
- **Alcance:** implementar el adaptador que extrae el recuento de ofertas del PDF descargado invocando en proceso el módulo de parseo existente, devolviendo el número de ofertas y la comunidad, o un error de parseo controlado cuando el PDF no es legible.
- **Hecho cuando:** con un PDF válido devuelve el recuento y la comunidad; con bytes que no son PDF legible devuelve un error de parseo controlado distinguible; y no emite ninguna petición HTTP a la propia API.
- **Pruebas automáticas:** `tests/unit/test_integridad_parser_adapter.py` (nuevo) — con `tests/fixtures/sample.pdf` (o un PDF generado con ofertas conocidas) devuelve el recuento exacto y la comunidad (REQ-003); con bytes no PDF devuelve error de parseo controlado, distinguible del error de descarga (ALT-004); con PDF válido sin ofertas devuelve recuento `0` sin error (ALT-004); no se realiza ninguna llamada HTTP a `GET /parse` ni a otro endpoint (SUP-005); no modifica `source/api/parser.py` ni `source/api/assembler.py`. Comando: `pytest tests/unit/test_integridad_parser_adapter.py`.
- **Prueba manual:** invocar el adaptador con el PDF real de difusión y comprobar que devuelve un recuento cercano a 92 ofertas, el valor observado el 10/11/2026.

### TASK-008 Adaptador del estado del buscador

- **Cubre:** REQ-003, REQ-006, SUP-004, SUP-006, DEC-005, ALT-005, ALT-006
- **Componente:** buscador-status-adapter | `source/api/integridad/buscador_client.py`
- **Depende de:** TASK-002
- **Ficheros:** `source/api/integridad/buscador_client.py` (nuevo) — `ClienteEstadoBuscador(url_base, cliente=None)` con `consultar_estado() -> EstadoBuscador | EstadoBuscadorNoUtilizable`.
- **Enfoque:** cliente HTTP propio de la integridad (no importa `source/api/persistencia/client.py` ni el de `api-historico`) que pide `<url_base>/buscador/status` con `httpx` inyectable y normaliza el cuerpo real: `in_progress`, `progreso` y `ultima_pasada` con `timestamp`, `comunidad`, `total_listado`, `error_global` y `errores_por_oferta`. Expone `total_listado` y distingue explícitamente, sin lanzar excepción, tres resultados no utilizables: error HTTP o de red, `ultima_pasada` nula (o sin `total_listado`) y `error_global` no vacío (ALT-005/ALT-006). Solo emite peticiones a `/buscador/status`: no lanza pasadas, no descarga fichas y no modifica `source/api/buscador/` (SUP-004).
- **Alcance:** implementar el cliente HTTP de `GET /buscador/status`, normalizar `total_listado` y distinguir error de red, `ultima_pasada` nula y `error_global` no vacío.
- **Hecho cuando:** devuelve el estado publicado por el buscador con la estructura real de `GET /buscador/status` y, ante error HTTP o de red, `ultima_pasada` nula o `error_global` no vacío, comunica un estado no utilizable que impide al comparador emitir `concordante`, sin lanzar excepción.
- **Pruebas automáticas:** `tests/unit/test_integridad_buscador_client.py` (nuevo) — cuerpo real → devuelve `in_progress`, `progreso` y `ultima_pasada` con sus cinco campos (SUP-006); la URL solicitada es `<url_base>/buscador/status`; `ultima_pasada` nula → estado no utilizable distinguible (ALT-005); `error_global` no vacío → estado no utilizable sin excepción (ALT-006); error HTTP y fallo de red → error controlado (ALT-005); solo peticiones a `/buscador/status`; no modifica `source/api/buscador/` ni su contrato (SUP-004). Comando: `pytest tests/unit/test_integridad_buscador_client.py`.
- **Prueba manual:** con la aplicación arrancada, consultar el adaptador contra `http://localhost:8000` y comprobar que devuelve el mismo `total_listado` que `GET /buscador/status`.

### TASK-009 Comparador de recuentos y emisión del veredicto

- **Cubre:** REQ-003, REQ-004, REQ-006, NFR-002, SUP-001, SUP-006, DEC-005, ALT-004, ALT-005, ALT-006
- **Componente:** comparador-veredicto | `source/api/integridad/comparador.py`
- **Depende de:** TASK-007, TASK-008
- **Ficheros:** `source/api/integridad/comparador.py` (nuevo) — `ComparadorRecuentos(tolerancia_absoluta, tolerancia_relativa_pct, umbral_cordura)` con `comparar(recuento_pdf, estado_buscador) -> ResultadoComparacion` (veredicto, recuentos, diferencia, tolerancias, umbral y motivo).
- **Enfoque:** función pura, sin E/S, que aplica DEC-005: `concordante` si la diferencia entra en la tolerancia **absoluta** o en la **relativa** (la más permisiva), y `divergente` en cualquier otro caso; sigue además dos reglas de anulación: recuento del PDF por debajo del umbral de cordura → `divergente` con independencia del `total_listado` (ALT-004), y estado del buscador no utilizable (error HTTP/red, `ultima_pasada` nula, `error_global`) → `divergente` con el motivo de la causa (ALT-005/ALT-006). La regla relativa se calcula solo si `total_listado > 0` para no dividir por cero (con recuentos distintos de cero se resuelve por tolerancia absoluta). El resultado siempre incluye recuento PDF, `total_listado`, diferencia, tolerancias aplicadas y motivo (REQ-005). El veredicto es informativo: no bloquea cierres (REQ-006).
- **Alcance:** implementar el comparador que recibe los dos recuentos y los umbrales configurados, emite `concordante` o `divergente` con la regla más permisiva y aplica el umbral de cordura y el estado no utilizable del buscador, con el motivo concreto de cada caso.
- **Hecho cuando:** dos recuentos dentro de la tolerancia absoluta o relativa producen `concordante`; una diferencia que supere ambas produce `divergente`; un recuento por debajo del umbral produce `divergente`; y el resultado incluye los dos recuentos, la diferencia y los umbrales aplicados.
- **Pruebas automáticas:** `tests/unit/test_integridad_comparador.py` (nuevo) — `92`/`93` con tolerancias `1` y `5 %` → `concordante` (SUP-001, NFR-002); diferencia `1` aceptada por la absoluta aunque la relativa no se cumpla; diferencia que solo cabe en la relativa aceptada; diferencia fuera de ambas → `divergente` (REQ-004); `65` con umbral `70` → `divergente` aunque la diferencia sea cero (NFR-002, ALT-004); `70` con umbral `70` no diverge por umbral; recuento `0` → `divergente` por umbral (ALT-004); buscador no utilizable (HTTP, `ultima_pasada` nula, `error_global`) → no `concordante` y motivo que identifica la causa (ALT-005, ALT-006); el resultado incluye recuentos, diferencia y umbrales (REQ-005); con tolerancias y umbral distintos se aplican esos (NFR-002). Comando: `pytest tests/unit/test_integridad_comparador.py`.
- **Prueba manual:** comparar `92`/`93` y después `65`/`93`: el primero `concordante` y el segundo `divergente` por el umbral.

### TASK-010 Almacén de avisos de fallo y divergencia

- **Cubre:** REQ-007, REQ-008, SUP-007, DEC-001, DEC-002, ALT-003, ALT-006
- **Componente:** avisos-store | `source/api/integridad/avisos.py`
- **Depende de:** TASK-003
- **Ficheros:** `source/api/integridad/avisos.py` (nuevo) — `AlmacenAvisos(almacen_pdf)` con `registrar_divergencia(comunidad, fecha, resultado)`, `registrar_fallo(comunidad, fecha, motivo)` y `consultar(desde, hasta)`.
- **Enfoque:** el aviso se **anexa** a la lista `avisos` del `.meta.json` del día de esa comunidad, reescribiéndolo con la escritura atómica de `pdf-store` (DEC-001), de modo que cada aviso queda asociado a su día y es consultable por rango leyendo los `.meta.json` del rango. Un aviso de divergencia lleva fecha, comunidad, `recuento_pdf`, `total_listado`, `diferencia`, tolerancias/umbral aplicados y motivo (REQ-007); uno de fallo lleva fecha, comunidad y motivo (ALT-003/ALT-006). Los avisos son registros internos: no se envía nada por Telegram ni por ningún cliente de notificación externo (SUP-007) ni se crea ningún fichero SQLite (DEC-001).
- **Alcance:** implementar el almacén que registra como aviso consultable en el `.meta.json` del día cada fallo de descarga, fallo de parseo y divergencia de recuentos, y que consulta los avisos de un rango de fechas.
- **Hecho cuando:** tras una divergencia, el aviso contiene fecha, recuento del PDF, `total_listado`, diferencia, umbral aplicado y motivo; tras un fallo de descarga o parseo, contiene fecha, comunidad y motivo; y la consulta por rango devuelve los avisos de ese rango.
- **Pruebas automáticas:** `tests/unit/test_integridad_avisos.py` (nuevo) — divergencia → aviso con los seis datos (REQ-007); fallo de descarga → aviso con fecha, comunidad y motivo (ALT-003); fallo de parseo → ídem; consulta por rango devuelve los del rango y excluye los de fuera (REQ-009); los avisos quedan en el `.meta.json` del día correspondiente (DEC-001); no se envía ningún mensaje por Telegram ni se invoca cliente de notificación (SUP-007); sin ficheros SQLite (DEC-001). Comando: `pytest tests/unit/test_integridad_avisos.py`.
- **Prueba manual:** provocar una divergencia y revisar la entrada `avisos` del `.meta.json` del día: aparecen fecha, recuentos, diferencia, umbral y motivo.

### TASK-011 Índice de ejecuciones del último mes

- **Cubre:** REQ-005, REQ-008, REQ-009, NFR-001, NFR-004, DEC-001, ALT-008
- **Componente:** avisos-store | `source/api/integridad/ejecuciones.py`
- **Depende de:** TASK-003
- **Ficheros:** `source/api/integridad/ejecuciones.py` (nuevo) — `IndiceEjecuciones(base, zona_horaria)` con `registrar(ejecucion)`, `consultar_ultimo_mes(hoy)` y `leer()`.
- **Enfoque:** fichero JSON ligero en `<base>/ejecuciones.json` (`data/pdfs/ejecuciones.json` por defecto, aviso del `tasks.md`): lista de entradas con `timestamp`, `resultado_global`, `errores_por_comunidad` (lista de `{comunidad, mensaje}`) y `veredicto_agregado`, más la referencia por fecha y comunidad a los `.meta.json`. Escritura atómica (temporal en el mismo directorio + `replace`) y estructura `{version, ejecuciones: [...]}` para permitir evolución; la marca de tiempo se genera en la zona horaria configurada (NFR-004). La consulta filtra la ventana de 30 días y ordena de más reciente a más antigua. Un índice ilegible o corrupto se comunica como tal (resultado controlado) y no impide registrar una ejecución nueva: se reescribe el índice con la entrada nueva. Sin SQLite (DEC-001).
- **Alcance:** implementar el índice de ejecuciones bajo la ruta base de PDFs que registra cada ejecución con marca de tiempo, resultado global, errores por comunidad y veredicto agregado, y consulta las de los últimos 30 días ordenadas de más reciente a más antigua.
- **Hecho cuando:** tras una ejecución el índice contiene su entrada completa; la consulta del último mes devuelve solo esa ventana y en orden descendente; y el índice sobrevive a un reinicio porque está en disco.
- **Pruebas automáticas:** `tests/unit/test_integridad_ejecuciones.py` (nuevo) — entrada con timestamp, resultado, errores y veredicto (REQ-008); consulta de 30 días solo con esa ventana (REQ-009); orden descendente (REQ-009); ejecución con errores parciales registra comunidad y mensaje (REQ-008); escritura atómica sin temporales (DEC-001); relectura desde disco devuelve las mismas entradas; índice corrupto se comunica y no impide registrar una ejecución nueva; sin SQLite (DEC-001); el timestamp corresponde a la zona configurada y no a la del sistema (NFR-004). Comando: `pytest tests/unit/test_integridad_ejecuciones.py`.
- **Prueba manual:** registrar dos ejecuciones simuladas y consultar las del último mes: aparecen las dos, de más reciente a más antigua.

### TASK-012 Tarea programada diaria de integridad

- **Cubre:** REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008, REQ-009, NFR-001, NFR-002, NFR-003, NFR-004, SUP-001, SUP-003, SUP-004, SUP-005, SUP-007, DEC-001, DEC-002, DEC-004, DEC-005, DEC-006, ALT-001, ALT-002, ALT-003, ALT-004, ALT-005, ALT-006, ALT-007, ALT-008
- **Componente:** integridad-task | `source/api/integridad/task.py`
- **Depende de:** TASK-005, TASK-006, TASK-007, TASK-008, TASK-009, TASK-010, TASK-011
- **Ficheros:** `source/api/integridad/task.py` (nuevo) — `TareaIntegridad(config, almacen, adaptador_descarga, adaptador_parseo, cliente_buscador, comparador, avisos, ejecuciones, purger, reloj=None)` con `iniciar()`, `detener()` y `_ejecutar_dia()`; `RelojProtocol`/`RelojReal` locales del subpaquete (sin importar de `api-historico`).
- **Enfoque:** hilo daemon propio con `threading.Event` de parada y reloj inyectable, igual que `api-historico/task.py` y `api-buscador/scheduler.py`; **no** se toca el planificador del buscador (SUP-004, DEC-006). Cada disparo calcula hoy con la zona configurada (NFR-004) y, para cada comunidad de la configuración: consulta el `.meta.json` de hoy y, si existe válido (`ok`/`concordante` o `fallido`), no descarga ni parsea (ALT-001/ALT-002, NFR-003); si existe el PDF sin metadatos, lo reprocesa como huérfano (ALT-007); si no hay nada, descarga → guarda atómica con hash → parsea → consulta el buscador → compara → completa el `.meta.json` con umbrales y timestamp → registra aviso si el veredicto no es `concordante`. Descarga fallida → `.meta.json` `fallido` sin PDF (ALT-003); parseo fallido → PDF conservado y veredicto `fallido` (DEC-002). Al terminar todas las comunidades calcula el veredicto global como el más grave (`fallido` > `divergente` > `concordante`, ALT-008), lo registra en el índice de ejecuciones y lanza la purga. Un lock/Event evita solapamiento entre disparos; `detener()` cancela el hilo sin dejar ejecución en curso. Sin Telegram ni canales externos (SUP-007); sin SQLite (DEC-001).
- **Alcance:** implementar la tarea programada propia que orquesta la comprobación diaria a la hora y zona configuradas, sin modificar el planificador de `api-buscador`, con idempotencia por `.meta.json`, veredicto por comunidad y ejecución global con purga final.
- **Hecho cuando:** se dispara a la hora configurada en la zona configurada; un `.meta.json` previo de la misma comunidad y fecha omite descarga, parseo y comparación; una descarga fallida deja el día `fallido` sin PDF y con el error; un parseo fallido conserva el PDF y deja `fallido`; una comparación correcta deja veredicto y recuentos; y al terminar registra la ejecución global con sus errores por comunidad.
- **Pruebas automáticas:** `tests/unit/test_integridad_task.py` (nuevo) — con reloj controlado se dispara una vez a la hora configurada y no se solapa (NFR-001, DEC-006); `.meta.json` de hoy `ok` → omite descarga, parseo y comparación (ALT-001, NFR-003); `.meta.json` de hoy `fallido` → no reintenta (ALT-002); descarga en error → día `fallido`, sin PDF, con aviso (ALT-003, REQ-007); parseo en error → PDF conservado y veredicto `fallido` (DEC-002); PDF sin `.meta.json` → reprocesado y día completo (ALT-007); dos comunidades → un `.meta.json` y un veredicto por comunidad y global más grave (ALT-008); hoy se calcula con la zona configurada (NFR-004); no lanza ni altera `api-buscador`, `api-persistencia` ni `api-historico` (SUP-004); no envía avisos externos (SUP-007); cancelación limpia sin ejecuciones en curso. Todos los dobles sobre `tmp_path`. Comando: `pytest tests/unit/test_integridad_task.py`.
- **Prueba manual:** arrancar la tarea con reloj controlado a la hora configurada y comprobar que se ejecuta una vez y que una segunda ejecución del mismo día no vuelve a descargar el PDF.

### TASK-013 Recuperación del día en curso con margen de catch-up

- **Cubre:** REQ-001, REQ-005, NFR-001, NFR-003, DEC-007, ALT-009
- **Componente:** integridad-task | `source/api/integridad/task.py`
- **Depende de:** TASK-012
- **Ficheros:** `source/api/integridad/task.py` (modificar) — lógica de arranque en `iniciar()` (cálculo de `hora`/`hora + margen` y programación de la ejecución única) y helper `_decidir_arranque(ahora, hay_meta_hoy) -> AccionArranque`.
- **Enfoque:** decisión puramente funcional sobre el reloj inyectable y la existencia del `.meta.json` de hoy, nunca sobre memoria (DEC-007): antes de `hora` → solo la ejecución programada normal; dentro de `[hora, hora + margen]` y sin metadatos → una única ejecución diferida a `hora + margen` (que al llegar comprueba de nuevo si sigue sin metadatos); después de `hora + margen` y sin metadatos → ejecución inmediata; con `.meta.json` de hoy (`ok` o `fallido`) → no se hace nada. La ejecución diferida y la normal comparten el mismo guardia de idempotencia y el mismo lock, de modo que no se duplican (ALT-009). Nunca se procesan días anteriores ni se rellenan días perdidos. Con `margen_catchup=0`, un arranque posterior a la hora ejecuta de inmediato.
- **Alcance:** implementar la lógica de catch-up al arrancar apoyada en el `.meta.json` del día y no en memoria, con los cuatro casos de `hora`, `hora + margen` e inexistencia de metadatos.
- **Hecho cuando:** el arranque antes de la hora no dispara nada inmediato; dentro del margen programa una única ejecución para `hora + margen`; después del margen ejecuta de inmediato; y en los tres casos sin metadatos previos se comprueba exactamente una vez el día en curso.
- **Pruebas automáticas:** `tests/unit/test_integridad_catchup.py` (nuevo) — arranque antes de `hora` → nada inmediato y ejecución normal programada (DEC-007); dentro de la ventana sin metadatos → una única ejecución a `hora + margen` (ALT-009); al llegar a `hora + margen` sin metadatos → ejecuta la comprobación; después de `hora + margen` sin metadatos → ejecución inmediata; con `.meta.json` de hoy `ok` o `fallido` → nada (ALT-002/ALT-009); `margen=0` → inmediata tras la hora; días pasados presentes y sin metadatos de hoy → no se tocan; tras reinicio, un día ya procesado no se reprocesa; la ejecución del margen no se duplica con la normal. Comando: `pytest tests/unit/test_integridad_catchup.py`.
- **Prueba manual:** arrancar dentro de la ventana de margen y comprobar que no se ejecuta de inmediato y que a `hora + margen` se ejecuta una sola vez.

### TASK-014 Arranque y apagado de la integridad en la aplicación

- **Cubre:** REQ-001, REQ-006, NFR-001, NFR-004, SUP-002, SUP-003, DEC-001, DEC-006, ALT-009
- **Componente:** api-service | `source/api`
- **Depende de:** TASK-002, TASK-012, TASK-013
- **Ficheros:** `source/api/main.py` (modificar) — dentro del `lifespan`: bloque nuevo tras el del histórico que carga `config/integridad.yaml`, instancia almacén, adaptadores, comparador, avisos, índice, purga y `TareaIntegridad`, y los guarda en `app_state` (`config_integridad`, `almacen_integridad`, `indice_ejecuciones`, `tarea_integridad`); `app.include_router(integridad_router)` a nivel de módulo; en el apagado, `tarea_integridad.detener()` como **primer** paso, antes de la tarea del histórico, de las conexiones y del `scheduler`.
- **Enfoque:** seguir el patrón de los bloques de persistencia e histórico: `try/except` que registra el error y deja la feature fuera de servicio (`app_state["tarea_integridad"] = None`, `logger.error`) sin abortar el arranque del resto. La integridad no abre conexiones ni recursos compartidos (todo son ficheros bajo la ruta base), de modo que su parada no depende de cerrar nada más. Orden de apagado de este sprint hacia los anteriores: `tarea_integridad` → `tarea_historico` → `conexion_historico` → `tarea_ingesta`/`tarea_purga` → `conexion_persistencia` → `scheduler`/`cliente_http` (DEC-006). No se modifica `source/api/buscador/`, `source/api/persistencia/`, `source/api/historico/` ni `source/api/parser.py` (SUP-002); el arranque no toca `data/job_emcan.db` (SUP-003).
- **Alcance:** integrar en el ciclo de vida de la aplicación FastAPI la configuración, el almacén, los adaptadores, el comparador, los avisos, el índice, el router de consulta y la tarea diaria propia, de modo que convivan el planificador del buscador, `ingestion-task`, `purge-task`, `historico-task` y `integridad-task`, y ordenar el apagado.
- **Hecho cuando:** al arrancar, la tarea de la integridad queda activa junto a las demás; si la configuración falla, el error se registra y el resto de la API sigue arrancando sin la feature; al apagar, la tarea queda cancelada sin ejecuciones en curso; y los endpoints existentes siguen respondiendo igual.
- **Pruebas automáticas:** `tests/integration/test_integridad_startup.py` (nuevo) — tras arrancar están activas la tarea de integridad, la ingesta, la purga, la del histórico y el planificador (DEC-006); configuración ausente o malformada → error registrado y API disponible sin la feature; al apagar, la tarea queda cancelada y no inicia ejecuciones; la cancelación ocurre antes de detener el planificador; los endpoints de `api-buscador`, `api-persistencia` y `api-historico` responden igual; no se modifica `source/api/buscador/`, `source/api/persistencia/`, `source/api/historico/` ni `source/api/parser.py` (SUP-002); no se crea ningún fichero SQLite de la integridad (DEC-001); `data/job_emcan.db` conserva contenido y marca de modificación (SUP-003). Comando: `pytest tests/integration/test_integridad_startup.py`.
- **Prueba manual:** arrancar la aplicación y comprobar que la tarea de la integridad queda programada junto a las demás; detenerla y comprobar que no queda viva ninguna tarea de la integridad.

### TASK-015 Endpoint del último veredicto de integridad

- **Cubre:** REQ-006, REQ-009, SUP-002, SUP-006, DEC-001, DEC-005, ALT-008
- **Componente:** integridad-api | `source/api/integridad/routes.py`
- **Depende de:** TASK-009, TASK-011
- **Ficheros:** `source/api/integridad/routes.py` (nuevo) — `router = APIRouter(prefix="/integridad", tags=["integridad"])` con `GET /integridad/ultimo` y modelos Pydantic de salida.
- **Enfoque:** el endpoint lee, a través de `pdf-store`, el `.meta.json` más reciente (fecha máxima presente; a igualdad, la última ejecución del índice) y devuelve el veredicto global junto con el desglose por comunidad (fecha, comunidad, `recuento_pdf`, `recuento_buscador`, diferencia, tolerancias, umbral y resultado) y un booleano `cierre_recomendado` (`true` solo si hay veredicto `concordante` de hoy; `false` si es `divergente`, `fallido` o no hay veredicto de hoy, REQ-006). Con varias comunidades aplica la gravedad de ALT-008. Es de solo lectura (no escribe nada, no toca `data/job_emcan.db`, SUP-002), omite los `.meta.json` ilegibles sin error y no exige autenticación, como el resto de la API. El veredicto es informativo: no bloquea ni modifica los cierres de `api-historico`.
- **Alcance:** implementar la consulta del último veredicto con el desglose por comunidad e indicar si los cierres del día están recomendados, sin bloquear los cierres de `api-historico` y sin autenticación.
- **Hecho cuando:** con veredicto almacenado devuelve el más reciente con fecha, comunidad, recuentos, diferencia y resultado; con `divergente`, `fallido` o sin veredicto de hoy indica que no se recomienda cerrar; con `concordante` de hoy indica que sí.
- **Pruebas automáticas:** `tests/integration/test_integridad_api_ultimo.py` (nuevo) — devuelve el más reciente con sus campos (REQ-009); `divergente` de hoy → no recomendable (REQ-006); `fallido` de hoy → no recomendable; sin veredicto de hoy → no recomendable; `concordante` de hoy → recomendable; varias comunidades → global y desglose (ALT-008); `.meta.json` ilegible omitido sin error; no escribe y no modifica `data/job_emcan.db` (SUP-002); sin 401/403 ni cabeceras de autenticación. Comando: `pytest tests/integration/test_integridad_api_ultimo.py`.
- **Prueba manual:** consultar el endpoint con un día `divergente` y con un día `concordante` y comprobar que la recomendación cambia en consecuencia.

### TASK-016 Endpoint de las ejecuciones del último mes

- **Cubre:** REQ-008, REQ-009, SUP-002, SUP-007, DEC-001
- **Componente:** integridad-api | `source/api/integridad/routes.py`
- **Depende de:** TASK-011
- **Ficheros:** `source/api/integridad/routes.py` (modificar) — `GET /integridad/ejecuciones` y su modelo de salida.
- **Enfoque:** lectura del índice de ejecuciones a través de `IndiceEjecuciones.consultar_ultimo_mes(hoy)` con hoy en la zona configurada; devuelve las entradas de la ventana de 30 días con marca de tiempo, resultado global, errores por comunidad y veredicto agregado, e incluye los avisos registrados en esas ejecuciones (leídos del `.meta.json` referenciado, omitiendo los ilegibles). Un índice ausente o ilegible devuelve lista vacía sin error. Solo lectura, sin autenticación y sin ningún canal de notificación externo (SUP-002, SUP-007).
- **Alcance:** implementar la consulta de las ejecuciones del último mes con su marca de tiempo, resultado global, errores por comunidad, veredicto agregado y avisos.
- **Hecho cuando:** con ejecuciones en los últimos 30 días las devuelve con marca de tiempo y resultado; con ejecuciones más antiguas no las devuelve; y una ejecución con errores parciales expone la comunidad afectada y su mensaje.
- **Pruebas automáticas:** `tests/integration/test_integridad_api_ejecuciones.py` (nuevo) — devuelve las de los últimos 30 días (REQ-009); errores parciales con comunidad y mensaje (REQ-008); las de más de 30 días no aparecen; orden de más reciente a más antigua; los avisos son consultables en la respuesta (REQ-007); índice ausente o ilegible → lista vacía sin error; no escribe ni modifica `data/job_emcan.db` (SUP-002); sin integraciones de notificación externa (SUP-007). Comando: `pytest tests/integration/test_integridad_api_ejecuciones.py`.
- **Prueba manual:** consultar el endpoint con un índice de prueba y comprobar que devuelve solo las ejecuciones del último mes con sus avisos.

### TASK-017 Endpoint de los PDFs conservados

- **Cubre:** REQ-002, REQ-009, SUP-003, DEC-001, DEC-004
- **Componente:** integridad-api | `source/api/integridad/routes.py`
- **Depende de:** TASK-004
- **Ficheros:** `source/api/integridad/routes.py` (modificar) — `GET /integridad/pdfs` y su modelo de salida.
- **Enfoque:** lectura con `AlmacenPDFs.listar_conservados()`: un elemento por PDF con fecha, comunidad y ruta identificable, y, cuando existe `.meta.json`, hash, recuento y veredicto; los PDF sin metadatos aparecen igualmente, sin datos de metadatos y sin error (ALT-007); un `.meta.json` ilegible se omite en la parte de metadatos sin impedir listar los PDFs; sin directorio de PDFs → lista vacía. Refleja lo que queda tras la purga (no hay PDFs fuera de la ventana de retención, DEC-004). Solo lectura: no escribe ni borra ficheros, no toca `data/job_emcan.db` (SUP-003) y no exige autenticación.
- **Alcance:** implementar la consulta de los PDFs conservados con fecha, comunidad, ruta identificable y metadatos disponibles.
- **Hecho cuando:** con PDFs conservados los devuelve con fecha, comunidad y ruta; los PDF sin `.meta.json` aparecen listados; y el listado refleja lo que queda tras la purga.
- **Pruebas automáticas:** `tests/integration/test_integridad_api_pdfs.py` (nuevo) — un elemento por PDF con fecha, comunidad y ruta (REQ-009); cada elemento incluye hash, recuento y veredicto si hay `.meta.json` (REQ-005); PDF sin `.meta.json` listado sin metadatos y sin error (ALT-007); `.meta.json` ilegible omitido sin impedir listar; sin directorio → lista vacía sin error (REQ-009); no aparecen PDFs fuera de la ventana tras la purga (REQ-002, DEC-004); no escribe ni borra y no modifica `data/job_emcan.db` (SUP-003); sin 401/403. Comando: `pytest tests/integration/test_integridad_api_pdfs.py`.
- **Prueba manual:** consultar el endpoint con varios PDFs conservados y comprobar que fecha, comunidad y ruta son correctos en cada elemento.

### TASK-018 Verificación de integración de la integridad

- **Cubre:** REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008, REQ-009, NFR-001, NFR-002, NFR-003, NFR-004, SUP-001, SUP-003, SUP-004, SUP-005, SUP-007, DEC-001, DEC-002, DEC-003, DEC-004, DEC-005, DEC-006, DEC-007, ALT-001, ALT-002, ALT-003, ALT-004, ALT-005, ALT-006, ALT-007, ALT-008, ALT-009
- **Componente:** api-service | `source/api`
- **Depende de:** TASK-014, TASK-015, TASK-016, TASK-017
- **Ficheros:** `tests/integration/test_integridad_integration.py` (nuevo) — extremo a extremo con `TestClient`, `GET /buscador/status` simulado, descargador y parser del PDF simulados, directorio temporal de PDFs y reloj controlado.
- **Enfoque:** montar la aplicación real (o el `lifespan` con configuración de prueba temporal) sustituyendo solo los dobles externos permitidos: cliente HTTP del estado del buscador, descargador y parser del PDF, y la ruta base de PDFs apuntando a `tmp_path`. Se ejecuta la tarea diaria de forma controlada y se consultan los tres endpoints; se comprueba que el `.meta.json`, el índice y los avisos quedan coherentes con el veredicto, que la segunda ejecución del mismo día no descarga ni escribe un segundo veredicto, y que `data/job_emcan.db` conserva contenido y `mtime` (SUP-003). No se crea ningún SQLite nuevo (DEC-001).
- **Alcance:** verificar de extremo a extremo la comunicación entre la aplicación, la configuración, el almacén, los tres adaptadores, el comparador, los avisos, el índice, la tarea diaria y los endpoints, con los dobles descritos.
- **Hecho cuando:** con una pasada válida y recuentos concordantes el día queda `concordante` y los tres endpoints devuelven lo esperado; con divergencia o fallo el día queda `divergente` o `fallido`, existe el aviso y la recomendación de cierre es negativa; y la segunda ejecución del mismo día no descarga ni genera un segundo veredicto, sin excepciones no controladas.
- **Pruebas automáticas:** `tests/integration/test_integridad_integration.py` — `92`/`93` → `concordante` y cierre recomendable (REQ-004, REQ-006); `92`/`80` → `divergente`, aviso con recuentos, diferencia, umbral y motivo, y cierre no recomendable (REQ-003, REQ-007); recuento `65` → `divergente` por umbral aunque los recuentos coincidan (NFR-002, ALT-004); descarga en error → `fallido`, sin PDF para la fecha y aviso con comunidad y motivo (ALT-003); parseo en error → PDF conservado, `fallido` y aviso (DEC-002); buscador sin `ultima_pasada` o con `error_global` → `divergente` con motivo (ALT-005, ALT-006); segunda ejecución el mismo día → sin nueva descarga ni segundo veredicto (ALT-001); día `fallido` previo no se reintenta (ALT-002); arranque dentro del margen → una única ejecución a `hora + margen` y comprobación única del día (ALT-009, DEC-007); tras la purga, el endpoint de PDFs no devuelve los de más de la ventana y sí el del día (REQ-002, DEC-004); el endpoint de ejecuciones devuelve las del mes con sus avisos (REQ-008, REQ-009); el directorio de datos contiene los `.meta.json` y PDFs esperados y ningún SQLite nuevo (DEC-001); `data/job_emcan.db` conserva contenido y `mtime` (SUP-003). Comando: `pytest tests/integration/test_integridad_integration.py`.
- **Prueba manual:** ejecutar la prueba de integración y revisar el informe (todos los escenarios con el resultado esperado); revisar el directorio de datos: aparecen los PDFs y `.meta.json` esperados, sin ficheros SQLite nuevos.

### TASK-019 Contrato: openapi - endpoints de consulta de la integridad

- **Cubre:** REQ-006, REQ-009, SUP-002, SUP-007, DEC-001, DEC-005
- **Componente:** integridad-api | `source/api/integridad/routes.py`
- **Depende de:** TASK-015, TASK-016, TASK-017, TASK-018
- **Ficheros:** `docs/contracts/openapi/api-integridad.yaml` (nuevo). Tarea del documentador.
- **Enfoque:** formalizar `GET /integridad/ultimo`, `GET /integridad/ejecuciones` y `GET /integridad/pdfs` tal como quedaron implementados (implementation-first, tras TASK-018), con esquemas de salida (fecha, comunidad, recuentos, diferencia, umbrales, veredicto, `cierre_recomendado`, ejecuciones y PDFs) y respuestas de error, coherentes con los modelos Pydantic de `routes.py` y con las respuestas reales capturadas en TASK-018. Documenta que el veredicto es informativo y no bloquea los cierres de `api-historico` (REQ-006) y que no hay autenticación.
- **Alcance:** crear el contrato OpenAPI que formaliza los tres endpoints de consulta con sus esquemas de entrada y salida y sus respuestas de error.
- **Hecho cuando:** el contrato existe en `docs/contracts/openapi/api-integridad.yaml`, describe las tres operaciones con sus esquemas y respuestas 200 y coincide con la implementación verificada en TASK-018.
- **Pruebas automáticas:** `tests/contract/test_integridad_openapi.py` (nuevo) — el YAML carga y contiene las tres operaciones con respuesta 200; el esquema del veredicto incluye fecha, comunidad, ambos recuentos, diferencia, umbrales y veredicto (REQ-009); el de ejecuciones incluye marca de tiempo, resultado global, errores por comunidad y veredicto agregado (REQ-008); el de PDFs incluye fecha, comunidad y ruta identificable (REQ-009); documenta que el veredicto es informativo (REQ-006); rutas y campos coinciden con la implementación de TASK-018. Comando: `pytest tests/contract/test_integridad_openapi.py`.
- **Prueba manual:** revisar el contrato y comprobar las tres interfaces de la fila de contratos afectados; comparar con las respuestas JSON reales de TASK-018 y confirmar que no hay campos divergentes.

### TASK-020 Contrato: configuración - fichero de configuración de la integridad

- **Cubre:** REQ-001, REQ-002, REQ-003, NFR-001, NFR-002, NFR-004, SUP-001, SUP-003, DEC-005, DEC-007
- **Componente:** config-integridad | `config/integridad.yaml`
- **Depende de:** TASK-002, TASK-014
- **Ficheros:** `config/integridad.yaml` (modificar: documentar el formato en la cabecera, como `config/historico.yaml`). Tarea del documentador.
- **Enfoque:** documentar el formato exacto y los valores por defecto (zona horaria, hora de ejecución, margen de catch-up, días de retención, tolerancia absoluta, tolerancia relativa, umbral de cordura, ruta base de PDFs, URL base del buscador y comunidades —con la remisión a `config/comunidades.yaml` cuando no se declaren—), las reglas de validación (zona IANA válida, enteros sin booleanos, hora 0-23, margen ≥ 0, tolerancias y umbral ≥ 0, rutas relativas a la raíz) y el layout de almacenamiento `<ruta_base>/<comunidad>/<aaaa-mm-dd>.pdf` con su `<aaaa-mm-dd>.meta.json` (SUP-003). Alineado con la carga de TASK-002 y con lo que aplica TASK-014. Sin rutas de servidor de BD ni credenciales.
- **Alcance:** formalizar el contrato de configuración de la integridad, dejándolo alineado con lo que la carga de TASK-002 interpreta y con lo que la aplicación aplica en TASK-014.
- **Hecho cuando:** el formato queda documentado, el fichero real lo cumple sin ambigüedad y una configuración válida se carga y se aplica sin cambios de código.
- **Pruebas automáticas:** `tests/contract/test_integridad_config_contract.py` (nuevo) — el fichero carga con el formato documentado y devuelve zona, hora, margen, días de retención, dos tolerancias, umbral, ruta base y comunidades; un campo obligatorio ausente se rechaza identificándolo; tipo incorrecto, hora fuera de rango o zona inválida se rechazan (NFR-001, NFR-004); margen negativo se rechaza (DEC-007); los valores por defecto documentados (`Europe/Madrid`, `2`, `60`, `30`, `1`, `5`, `70`, `data/pdfs`) coinciden con la implementación; documenta el layout `<ruta_base>/<comunidad>/<aaaa-mm-dd>.pdf` (SUP-003); sin rutas de servidor ni credenciales. Comando: `pytest tests/contract/test_integridad_config_contract.py`.
- **Prueba manual:** revisar que la fila de contrato (configuración de la integridad) queda descrita con el mismo formato que usa el fichero real; modificar el fichero siguiendo solo el formato documentado y comprobar que la aplicación arranca con la nueva configuración.

### TASK-021 Actualización del mapa de arquitectura

- **Cubre:** DEC-001, DEC-002, DEC-003, DEC-004, DEC-005, DEC-006, DEC-007
- **Componente:** api-service | `source/api`
- **Depende de:** TASK-018, TASK-019, TASK-020
- **Ficheros:** `.sdd/architecture.md` (modificar). Tarea del documentador.
- **Enfoque:** tres cambios y solo esos tres (design@3): (a) la línea del módulo `API` pasa a `API | source/api | API FastAPI de parseo de PDFs, rastreo del buscador, persistencia, histórico e integridad de ofertas | -`; (b) añadir a contratos `openapi | docs/contracts/openapi/api-integridad.yaml | cliente -> api-integridad`; (c) añadir a contratos `configuracion | config/integridad.yaml | api-integridad -> config-integridad`. El mapa **no** gana entradas de módulo para los componentes internos de la integridad (almacén, adaptadores, comparador, avisos, índice, purga, tarea programada, endpoints) ni para `source/api/integridad`.
- **Alcance:** actualizar `.sdd/architecture.md` solo en la línea del módulo `API` y en las dos entradas de contrato nuevas.
- **Hecho cuando:** la línea de `API` menciona la integridad; contratos contiene las dos entradas nuevas; y la sección de módulos no contiene ninguna entrada nueva de la integridad.
- **Pruebas automáticas:** `tests/contract/test_integridad_architecture.py` (nuevo) — la línea de `API` incluye "integridad" en su responsabilidad; contratos incluye `openapi | docs/contracts/openapi/api-integridad.yaml | cliente -> api-integridad`; incluye `configuracion | config/integridad.yaml | api-integridad -> config-integridad`; módulos no ha ganado entradas para los componentes internos ni para `source/api/integridad`; todos los ficheros citados existen en el repositorio. Comando: `pytest tests/contract/test_integridad_architecture.py`.
- **Prueba manual:** revisar `.sdd/architecture.md` y comprobar la línea de `API`, las dos entradas de contrato y la ausencia de entradas nuevas de módulo para la integridad.

## Orden de implementación

1. TASK-001 (habilitada por: sin dependencias)
2. TASK-002 (habilitada por: TASK-001 entregada — subpaquete importable)
3. TASK-003 (habilitada por: TASK-002 entregada — configuración cargable)
4. TASK-004 (habilitada por: TASK-003 entregada — almacén con escritura atómica y hash) y TASK-006 y TASK-008 (habilitadas por: TASK-002 entregada) — en paralelo
5. TASK-005 (habilitada por: TASK-004 entregada — listado de conservados) y TASK-007 (habilitada por: TASK-006 entregada) — en paralelo
6. TASK-009 (habilitada por: TASK-007 y TASK-008 entregadas) y TASK-010 y TASK-011 (habilitadas por: TASK-003 entregada) — en paralelo
7. TASK-012 (habilitada por: TASK-005, TASK-006, TASK-007, TASK-008, TASK-009, TASK-010 y TASK-011 entregadas)
8. TASK-013 (habilitada por: TASK-012 entregada)
9. TASK-014 (habilitada por: TASK-002, TASK-012 y TASK-013 entregadas — y por los sprints 02, 03 y 04 ya integrados en el `lifespan`)
10. TASK-015 (habilitada por: TASK-009 y TASK-011 entregadas), TASK-016 (habilitada por: TASK-011 entregada) y TASK-017 (habilitada por: TASK-004 entregada) — en paralelo
11. TASK-018 (habilitada por: TASK-014, TASK-015, TASK-016 y TASK-017 entregadas)
12. TASK-019 (habilitada por: TASK-015, TASK-016, TASK-017 y TASK-018 entregadas — implementation-first) y TASK-020 (habilitada por: TASK-002 y TASK-014 entregadas) — en paralelo
13. TASK-021 (habilitada por: TASK-018, TASK-019 y TASK-020 entregadas)

## Riesgos y dudas técnicas

- **Sin dependencias nuevas en `pyproject.toml`:** `httpx`, `pdfplumber`, `PyYAML` y `tzdata` (Windows) ya están declarados y `zoneinfo`/`threading` son stdlib, así que TASK-001 solo verifica disponibilidad. Añadir una biblioteca de *scheduling* externa contradiría la decisión de planificador en proceso con `threading` (coherente con los sprints 02–04).
- **`extraer_ofertas_desde_pdf` no distingue PDF ilegible de PDF sin ofertas:** `source/api/parser.py` captura `ErrorParseoPDF` y devuelve `[]`, pero TASK-007 exige un error de parseo controlado y distinguible (ALT-004) frente a un recuento `0` sin error. El adaptador compone las dos funciones públicas (`extraer_texto_pdf`, que sí lanza, y `extraer_ofertas`) sin modificar `parser.py` (SUP-005). Si se prefiere usar solo `extraer_ofertas_desde_pdf`, ALT-004 se degradaría a "recuento 0 por umbral"; el cambio queda acotado a TASK-007 y TASK-018.
- **Comunidades por defecto:** si `config/integridad.yaml` no declara `comunidades`, la carga reutiliza `source.api.config.cargar_comunidades()`, que lanza su `ErrorConfiguracion` si `config/comunidades.yaml` falta o es inválido. Se propone propagarlo como error controlado de la config de la integridad (y que TASK-014 deje la feature fuera de servicio, sin silenciar a lista vacía). Confirmable en TASK-002 y TASK-014.
- **Ruta del índice y prefijo de endpoints:** el diseño no los fija; se adoptan `data/pdfs/ejecuciones.json` y el prefijo `/integridad` (aviso del `tasks.md` 517). Un cambio queda limitado a TASK-011, TASK-015, TASK-016, TASK-017, TASK-018 y TASK-019.
- **`total_listado` igual a 0 en el comparador:** la regla relativa divide por el recuento del buscador; se calcula solo si `total_listado > 0` para evitar `ZeroDivisionError`. Con el umbral de cordura por defecto el veredicto ya sería `divergente`. Confirmable en TASK-009.
- **Concurrencia con `historico-task` a las 02:00:** ambas tareas pueden ejecutarse a la vez; el veredicto es informativo y `api-historico` no lo consume, por lo que no afecta a la corrección (aviso de `design@3`). No se resuelve en este sprint.
- **Tareas del documentador:** TASK-019, TASK-020 y TASK-021 son `Contrato:`/mapa; las cierra el documentador, no el desarrollador. La implementación debe dejar los endpoints y el formato del YAML estables antes de TASK-018 en adelante.
- **Zona horaria en Windows:** depende de `tzdata` (ya declarado). El timestamp del `.meta.json`, del índice y la fecha del nombre del PDF se calculan siempre con la zona configurada, nunca con la del sistema (NFR-004).

## Validación

- Suite del módulo: pendiente
- Integración: pendiente
- Validación manual: pendiente
