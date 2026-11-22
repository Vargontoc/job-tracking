# Diseño: api-historico

Estado: aprobado
Revisión: 3
Basado en: requirements@2
Verificación: correcta

## Resumen

`api-historico` cierra el ciclo de FUN-003 sin modificar las features aprobadas: consulta el estado de `api-buscador` para aplicar márgenes de seguridad, actualiza el estado de las ofertas a `cerrada` exclusivamente a través de `persistencia-api`, y como respaldo para ofertas sin fecha de fin de difusión invoca en proceso el parser del PDF de difusión. El módulo añade una tarea programada de cierre, evaluadores de fecha y de desaparición, un registro de abstenciones y endpoints de consulta de histórico. El estado propio del histórico (presencia, abstenciones, recuentos y ejecución diaria) vive en tablas propias; para las consultas históricas que `persistencia-api` no ofrece, `historico-read-adapter` lee directamente en modo solo lectura el fichero SQLite de `api-persistencia`.

## Supuestos sobre el sistema actual

- La API FastAPI vive en `source/api/` y expone `GET /buscador/status` en el mismo proceso, con el último resultado solo en memoria (`source/api/buscador/coordinator.py`).
- `api-persistencia` mantiene la base de datos SQLite `data/job_emcan.db` como fuente de verdad, con WAL y `busy_timeout`, y expone `persistencia-api` con cuatro operaciones: crear/actualizar oferta, consultar por `(comunidad, codigo)`, listar ofertas vigentes y listar códigos vistos.
- `api-pdf-parser` (`source/api/parser.py`, `source/api/downloader.py`, `source/api/assembler.py`) puede ser invocado en proceso para obtener el listado oficial de códigos de un PDF de difusión.
- El buscador y el PDF publican los códigos de oferta como texto de 12 dígitos y las fechas de difusión en formato `dd/mm/aaaa`.
- `api-buscador`, `api-persistencia` y `api-pdf-parser` no se modifican; `api-historico` se integra leyendo sus contratos y usando sus operaciones públicas.

## Componentes

| Componente | Responsabilidad | Existente o nuevo |
|---|---|---|
| api-service | Aplicación FastAPI que arranca las migraciones propias del histórico, registra la tarea programada de cierre y expone los endpoints de consulta. | existente (se extiende) |
| config-historico | Fichero de configuración con zona horaria, hora de ejecución, umbrales de seguridad, número de ausencias consecutivas y rutas de datos. | nuevo |
| schema-migrator-historico | Aplica migraciones secuenciales y transaccionales en el fichero SQLite propio del histórico. | nuevo |
| db-connection-historico | Gestiona la conexión única al SQLite propio, activa WAL y configura `busy_timeout`. | nuevo |
| buscador-status-adapter | Consulta `GET /buscador/status` y normaliza el resultado para el evaluador de cierres. | nuevo |
| persistencia-adapter | Cliente de `persistencia-api`: lista ofertas vigentes, consulta por clave natural y actualiza el estado a `cerrada`. No lee ofertas cerradas ni por rangos de fecha. | nuevo |
| historico-read-adapter | Conexión de solo lectura (`mode=ro`) al fichero SQLite de `api-persistencia` para servir consultas históricas por rango de fechas que `persistencia-api` no expone. No escribe, no modifica migraciones ni esquema. | nuevo |
| pdf-listado-adapter | Invoca en proceso el parser del PDF de difusión para obtener el listado oficial de códigos del día. | nuevo |
| cierre-fecha-evaluator | Evalúa ofertas `vigente` con `fecha_fin_difusion` informada y decide cuáles cerrar por fecha. | nuevo |
| desaparicion-evaluator | Evalúa ofertas `vigente` sin `fecha_fin_difusion` usando el histórico de presencia y el listado oficial del día. | nuevo |
| recuento-guardian | Compara el recuento actual con el anterior, aplica umbrales de caída y mínimo, y registra abstenciones. | nuevo |
| historico-presencia-repository | Persiste la presencia/ausencia de cada código en cada pasada oficial. | nuevo |
| abstenciones-repository | Registra cada abstención de cierre con motivo, marca de tiempo, recuentos y códigos afectados. | nuevo |
| ejecucion-repository | Controla que el cierre se ejecute como máximo una vez al día. | nuevo |
| historico-task | Tarea programada propia que orquesta el cierre diario tras la pasada esperada del buscador. No modifica el scheduler de `api-buscador`. | nuevo |
| historico-api | Endpoints de consulta de altas, cierres y resumen diario del histórico. | nuevo |

## Operaciones de `persistencia-api` que consume `api-historico`

`persistencia-api` expone, según `specs/api-persistencia/design.md` y `specs/api-persistencia/tasks.md`, las siguientes operaciones:

| Operación | Uso por `api-historico` | Requisitos que cubre |
|---|---|---|
| Crear o actualizar oferta (`POST /persistencia/ofertas`) | **No se usa para crear ofertas.** Solo para actualizar el estado a `cerrada` y la `fecha_cierre` a través de `persistencia-api`. | REQ-003, REQ-005, REQ-009, REQ-010 |
| Consultar oferta por `(comunidad, codigo)` | Verificar el estado actual de una oferta antes de cerrar y atender consultas puntuales en `historico-api`. | REQ-012 |
| Listar ofertas vigentes | Obtener las candidatas a cierre por fecha y por desaparición. | REQ-003, REQ-004, REQ-005, REQ-009 |
| Listar códigos vistos de una comunidad | **No se usa directamente.** El filtrado de vigentes sin fecha de fin se resuelve sobre el listado de vigentes. | - |

**Hueco identificado:** `persistencia-api` no expone operaciones de lectura por rango de `fecha_alta`, `fecha_cierre` o `fecha_fin_difusion`, ni listado de ofertas `cerrada`, ni resumen diario de altas y cierres. Estas lecturas son necesarias para REQ-002 y REQ-012. El diseño las resuelve con `historico-read-adapter` en modo `ro` sobre `data/job_emcan.db`, validado en SUP-004.

## Supuestos decisionales

### SUP-004 Lecturas históricas no cubiertas por `persistencia-api`

- **Tipo:** decisional
- **Descripción:** `persistencia-api` solo ofrece crear/actualizar oferta, consultar por clave natural, listar vigentes y listar códigos vistos. Para REQ-002 (altas por rango de `fecha_alta`) y REQ-012 (cierres por rango de `fecha_cierre` o `fecha_fin_difusion`, y resumen diario) faltan operaciones de lectura. Se elige la opción (a); las opciones (b) y (c) quedan descartadas y registradas como alternativas.
  - **(a) Lectura directa de solo lectura (elegida):** `historico-read-adapter` abre `data/job_emcan.db` en modo `ro` y consulta directamente la tabla `ofertas` usando el esquema documentado. No escribe, no modifica `api-persistencia` ni sus migraciones. Las escrituras de estado siguen yendo por `persistencia-api`.
  - **(b) Copia propia del histórico (descartada):** `api-historico` registraría en su propia base de datos cada alta y cierre que observa y serviría REQ-002/REQ-012 desde ahí. Requiere un backfill inicial de las ofertas ya existentes y duplica parcialmente el histórico.
  - **(c) Ampliar `persistencia-api` (descartada):** añadir endpoints de lectura histórica en `api-persistencia`. Esto obligaría a revisar `specs/api-persistencia` y contradice SUP-002 y la restricción de no tocar features aprobadas.
- **Impacto:** REQ-002, REQ-012.
- **Estado:** validado

### SUP-005 Ubicación del estado propio del histórico

- **Tipo:** decisional
- **Descripción:** `.sdd/project.md` declara "SQLite (un solo fichero, WAL) como base de datos". Se elige la opción (i) para el estado propio de `api-historico`; la opción (ii) queda descartada y registrada como alternativa.
  - **(i) Segundo fichero SQLite propio (`data/job_emcan_historico.db`) (elegido):** tablas propias para presencia, abstenciones, recuentos y ejecución diaria, gestionadas por el migrador propio de `api-historico`. No contiene ofertas; el estado de las ofertas sigue en `data/job_emcan.db`. Respeta el control de versiones de `api-persistencia`, evita interferir con su migrador y deja claro que `api-historico` no gestiona ofertas, solo estado auxiliar.
  - **(ii) Tablas propias dentro de `data/job_emcan.db` (descartada):** añadir tablas con prefijo `historico_` en la misma base de datos. Esto obliga a compartir el fichero con `api-persistencia` sin poder gestionar el versionado de su esquema, ya que `schema-migrator` de `api-persistencia` pertenece a otra feature aprobada y no se toca.
- **Impacto:** REQ-005, REQ-008, REQ-011, NFR-002; el arranque aplica primero las migraciones propias de `api-historico` y luego registra la tarea programada.
- **Estado:** validado

## Flujo principal

1. Al arrancar `api-service`, `db-connection-historico` crea o abre el fichero SQLite propio del histórico (`data/job_emcan_historico.db` por defecto), activa WAL y configura `busy_timeout`.
2. `schema-migrator-historico` consulta la versión actual y aplica las migraciones pendientes de forma secuencial y transaccional.
3. `api-service` arranca `historico-task` como tarea programada propia, a la hora configurada y tras la pasada esperada del buscador. No modifica el scheduler de `api-buscador`.
4. Cuando llega la hora, `historico-task` consulta `ejecucion-repository`; si ya se ejecutó en el día actual, finaliza sin hacer nada.
5. `historico-task` pide a `buscador-status-adapter` el estado del buscador. Si no responde, `ultima_pasada` es nula o hay `error_global`, se registra una abstención y se detiene el proceso.
6. `recuento-guardian` recupera el recuento anterior de la serie propia, compara el `total_listado` actual y aplica los umbrales de caída y mínimo. Si se incumplen, registra una abstención y se detiene el proceso.
7. `cierre-fecha-evaluator` solicita a `persistencia-adapter` las ofertas `vigente` con `fecha_fin_difusion` no vacía, filtra las fechas corruptas/imposibles y cierra idempotentemente, a través de `persistencia-adapter`, las que tienen `fecha_fin_difusion` estrictamente anterior a la fecha actual en la zona horaria configurada.
8. `desaparicion-evaluator` solicita a `persistencia-adapter` las ofertas `vigente` sin `fecha_fin_difusion`, excluye las que estén en `errores_por_oferta` y las que estén en estado `sin_ficha`.
9. `pdf-listado-adapter` invoca en proceso el parser del PDF para obtener el listado oficial de códigos del día. Si la fuente no está disponible o devuelve error, se registra una abstención y no se cierra ninguna oferta por desaparición.
10. `historico-presencia-repository` registra, para cada código candidato, si está presente o ausente en el listado oficial de hoy, usando como clave la fecha del listado.
11. `desaparicion-evaluator` cuenta las ausencias consecutivas consultando el histórico de presencia; si un código ha faltado en los últimos N listados consecutivos (con margen de un día cuando N=2), se cierra idempotentemente a través de `persistencia-adapter`.
12. Los cierres aplican el cambio de estado a `cerrada` y la `fecha_cierre` solo la primera vez, usando siempre `persistencia-adapter`.
13. Los resúmenes y consultas históricas se sirven desde `historico-api`, usando `historico-read-adapter` (lectura directa de solo lectura del SQLite de `api-persistencia`) para los rangos de fecha y el resumen diario.

## Flujos alternativos y de fallo

### ALT-001 Buscador no responde o la última pasada falló

- **Condición:** `GET /buscador/status` devuelve error HTTP, el cuerpo indica `error_global` no vacío o `ultima_pasada` es nula.
- **Comportamiento:** `historico-task` no marca ninguna oferta como cerrada; delega en `abstenciones-repository` el registro del motivo, la marca de tiempo y el estado consultado.
- **Responsable:** buscador-status-adapter
- **Resultado:** Ninguna oferta cambia de estado; la abstención queda disponible para consulta.
- **Cubre:** REQ-006

### ALT-002 Caída anómala del recuento del buscador

- **Condición:** La caída de `total_listado` respecto al recuento anterior supera el umbral configurado o el recuento actual es inferior al mínimo configurado.
- **Comportamiento:** `recuento-guardian` aborta el cierre por desaparición y registra una abstención con recuento anterior, recuento actual y umbral aplicado.
- **Responsable:** recuento-guardian
- **Resultado:** No se cierra ninguna oferta por desaparición; el cierre por fecha puede haberse ejecutado previamente de forma independiente.
- **Cubre:** REQ-008

### ALT-003 Oferta en errores por oferta de la última pasada

- **Condición:** El código de una oferta candidata a cierre por desaparición aparece en `errores_por_oferta` de la última pasada.
- **Comportamiento:** `desaparicion-evaluator` excluye ese código del cierre y registra la abstención con el código y el motivo.
- **Responsable:** desaparicion-evaluator
- **Resultado:** La oferta permanece `vigente` aunque no esté en el listado oficial.
- **Cubre:** REQ-007

### ALT-004 Fuente de respaldo no disponible o con error

- **Condición:** El PDF de difusión no se puede descargar, el parser devuelve un error global o no produce ningún código.
- **Comportamiento:** `pdf-listado-adapter` informa del fallo; `desaparicion-evaluator` no cierra ninguna oferta por desaparición y se registra la abstención.
- **Responsable:** pdf-listado-adapter
- **Resultado:** Las ofertas sin `fecha_fin_difusion` permanecen `vigente`.
- **Cubre:** REQ-005

### ALT-005 Fecha de fin de difusión corrupta o imposible

- **Condición:** `fecha_fin_difusion` no sigue el patrón `dd/mm/aaaa` o representa una fecha imposible (por ejemplo, 31/02).
- **Comportamiento:** `cierre-fecha-evaluator` descarta la oferta del cierre por fecha, la trata como candidata a desaparición si está habilitada y registra el código como excluido por fecha inválida.
- **Responsable:** cierre-fecha-evaluator
- **Resultado:** El estado de la oferta no cambia por fecha.
- **Cubre:** REQ-003, REQ-004

### ALT-006 Doble ejecución en el mismo día

- **Condición:** `historico-task` se dispara una segunda vez en el mismo día calendario de la zona horaria configurada.
- **Comportamiento:** `ejecucion-repository` detecta que ya existe un registro del día y `historico-task` finaliza sin reevaluar ofertas.
- **Responsable:** ejecucion-repository
- **Resultado:** No se producen cierres adicionales ni se regeneran registros de presencia.
- **Cubre:** NFR-002

### ALT-007 Oferta reaparece en el listado tras haber sido cerrada por desaparición

- **Condición:** Una oferta previamente cerrada por desaparición vuelve a aparecer en un listado oficial posterior.
- **Comportamiento:** El sistema no reabre automáticamente la oferta; la decisión de reapertura corresponde a un flujo manual futuro fuera del alcance de esta feature.
- **Responsable:** desaparicion-evaluator
- **Resultado:** La oferta permanece `cerrada` y su `fecha_cierre` no cambia.
- **Cubre:** REQ-005

### ALT-008 Reinicio del buscador y pérdida del resultado en memoria

- **Condición:** `api-buscador` se reinicia y `_ultimo_resultado` desaparece, por lo que `GET /buscador/status` devuelve `ultima_pasada = null`.
- **Comportamiento:** `historico-task` se abstiene de cerrar y registra la abstención. No se considera ningún recuento anterior válido hasta que haya una nueva pasada completa.
- **Responsable:** buscador-status-adapter
- **Resultado:** Ninguna oferta cambia de estado.
- **Cubre:** REQ-006

### ALT-009 Cierre concurrente con ingesta o purga

- **Condición:** `historico-task` se ejecuta mientras `ingestion-task` o `purge-task` están escribiendo en la base de datos principal.
- **Comportamiento:** Las escrituras sobre SQLite se serializan gracias a WAL y `busy_timeout`. `persistencia-adapter` espera a que la transacción en curso termine; el cierre por fecha y por desaparición se ejecutan como transacciones independientes.
- **Responsable:** persistencia-adapter
- **Resultado:** No se producen cierres parciales ni corrupciones; el resultado es equivalente a una ejecución tras otra.
- **Cubre:** REQ-010

### ALT-010 Primer día o reinicio sin recuento anterior

- **Condición:** No existe ningún recuento previo en `SerieDeRecuento` (primer arranque o pérdida del histórico propio).
- **Comportamiento:** `recuento-guardian` registra el recuento actual pero se abstiene de cerrar por desaparición, ya que no puede validar la caída.
- **Responsable:** recuento-guardian
- **Resultado:** El cierre por fecha se ejecuta normalmente; el cierre por desaparición queda aplazado al día siguiente.
- **Cubre:** REQ-008

## Interfaces entre componentes

| Origen | Destino | Qué se comunica | Protocolo |
|---|---|---|---|
| api-service | db-connection-historico | Solicitud de conexión y transacción | llamada interna |
| api-service | schema-migrator-historico | Orden de migrar al arranque | llamada interna |
| api-service | historico-task | Configuración y señal de arranque/parada | llamada interna |
| historico-task | buscador-status-adapter | Estado del buscador | HTTP (OpenAPI) |
| historico-task | persistencia-adapter | Actualización de estado a `cerrada` y listado de vigentes | HTTP (OpenAPI) |
| historico-task | pdf-listado-adapter | Listado oficial de códigos del día | llamada interna |
| historico-task | recuento-guardian | Recuento actual y serie histórica | llamada interna |
| historico-task | cierre-fecha-evaluator | Ofertas candidatas y fecha actual | llamada interna |
| historico-task | desaparicion-evaluator | Ofertas candidatas, listado oficial y errores por oferta | llamada interna |
| historico-task | historico-presencia-repository | Registro de presencia/ausencia del día | llamada interna |
| historico-task | abstenciones-repository | Registro de abstenciones | llamada interna |
| historico-task | ejecucion-repository | Control de ejecución diaria | llamada interna |
| historico-api | historico-read-adapter | Consultas por rango de fechas y resumen diario | SQLite (solo lectura) |
| Cliente | historico-api | Consultas de altas, cierres y resumen | HTTP (OpenAPI) |

## Modelo de datos lógico

- **Oferta:** entidad gestionada por `api-persistencia` en `data/job_emcan.db`. `api-historico` actualiza su estado a través de `persistencia-api` y la consulta directamente en modo solo lectura para histórico.
- **PresenciaEnListado:** registro de si un código de oferta estuvo presente o ausente en un listado oficial de una fecha determinada. Relaciones: ninguna; se consulta por `(comunidad, codigo, fecha_listado)`.
- **SerieDeRecuento:** registro histórico de `total_listado` y `timestamp` de cada pasada del buscador. Relaciones: ninguna.
- **AbstencionDeCierre:** registro de cada vez que el sistema se abstuvo de cerrar, con motivo, marca de tiempo, recuentos y códigos afectados. Relaciones: ninguna.
- **EjecucionDiaria:** registro de la fecha en que se ejecutó el cierre, para garantizar la frecuencia máxima diaria. Relaciones: ninguna.

## Decisiones

### DEC-001 Segundo fichero SQLite propio para el estado del histórico

- **Decisión:** `api-historico` persiste su estado propio (presencia, abstenciones, serie de recuentos y ejecución diaria) en un fichero SQLite independiente (`data/job_emcan_historico.db`), gestionado por su propio migrador y con WAL activado. El estado de las ofertas sigue en `data/job_emcan.db` gestionado por `api-persistencia`.
- **Justificación frente a `.sdd/project.md`:** el stack declara "SQLite (un solo fichero, WAL) como base de datos", referido a la base de datos de ofertas. El segundo fichero almacena solo estado auxiliar del histórico y no duplica la base de ofertas. SUP-005 valida esta elección.
- **Alternativas descartadas:** Reutilizar la base de datos de `api-persistencia` añadiendo tablas propias (tocaría el mismo fichero y obligaría a compartir el control de versiones de esquema con una feature aprobada que no se modifica); almacenar el histórico en JSON (pierde integridad referencial y consultas eficientes); no persistir el histórico (imposibilita contar ausencias consecutivas tras reinicios).
- **Cubre:** REQ-005, REQ-008, REQ-011, NFR-002

### DEC-002 Parser del PDF invocado en proceso

- **Decisión:** El listado oficial del día se obtiene invocando en proceso el módulo de parseo del PDF de difusión (`api-pdf-parser`), sin llamada HTTP a `GET /parse`.
- **Alternativas descartadas:** Llamar al endpoint `GET /parse` (contradice SUP-001); descargar el listado HTML desde `api-historico` (tocaría la fuente del buscador y duplicaría lógica de `api-buscador`); comparar solo `total_listado` (no aporta la lista de códigos necesaria para detectar desapariciones).
- **Cubre:** REQ-005, SUP-001

### DEC-003 No modificar `api-buscador`

- **Decisión:** `api-historico` no modifica `api-buscador`; consulta `GET /buscador/status` como cliente HTTP y respeta los márgenes de seguridad que ese contrato publica.
- **Alternativas descartadas:** Hacer que `api-buscador` persista sus resultados (contradice SUP-002 y el alcance de `api-buscador`); que `api-historico` lea el fichero `data/seen_codes.json` como respaldo (no contiene el recuento ni los errores por oferta).
- **Cubre:** REQ-006, REQ-007, REQ-008, SUP-002

### DEC-004 No reabrir ofertas que reaparecen

- **Decisión:** Si una oferta cerrada por desaparición vuelve a aparecer en un listado oficial posterior, el sistema no cambia automáticamente su estado a `vigente`.
- **Alternativas descartadas:** Reabrir automáticamente (crearía ciclos de cierre/apertura no controlados y podría sobrescribir la fecha de cierre histórica); ignorar la reaparición sin registrarla (se pierde trazabilidad; por eso se sigue registrando la presencia aunque no se cambie el estado).
- **Cubre:** REQ-005

### DEC-005 Tres evaluadores separados: fecha, desaparición y recuento

- **Decisión:** El cierre por fecha, el cierre por desaparición y la protección por recuento se implementan como evaluadores independientes, cada uno con su responsabilidad clara.
- **Alternativas descartadas:** Un único evaluador que mezcle criterios (dificulta las pruebas y el registro de abstenciones por motivo); aplicar cierre por desaparición también a ofertas con `fecha_fin_difusion` informada (contradice REQ-004).
- **Cubre:** REQ-003, REQ-004, REQ-005, REQ-008

### DEC-006 Lectura histórica de solo lectura sobre `data/job_emcan.db`

- **Decisión:** Para REQ-002 y REQ-012 se usa `historico-read-adapter`, una conexión SQLite de solo lectura (`mode=ro`) al fichero SQLite de `api-persistencia`, sin escribir ni modificar migraciones. La fuente de verdad sigue siendo `api-persistencia`; `api-historico` no duplica el histórico de ofertas.
- **Alternativas descartadas:** Ampliar `persistencia-api` (contradice SUP-002 y la restricción de no tocar features aprobadas); mantener una copia propia del histórico (duplica datos y requiere backfill inicial).
- **Cubre:** REQ-002, REQ-012

## Riesgos

- **PDF no disponible o cambiado de formato:** si el PDF no se descarga o su estructura cambia, `pdf-listado-adapter` devolverá error y el cierre por desaparición se suspenderá. Mitigación: registro detallado de abstenciones y monitorización del número de códigos extraídos.
- **Reinicio del buscador y pérdida del resultado en memoria:** si `api-buscador` se reinicia, `ultima_pasada` desaparece y `api-historico` se abstendrá hasta la siguiente pasada. Mitigación: la ejecución diaria se programa tras la hora esperada de la pasada del buscador.
- **Doble ejecución diaria:** si el scheduler dispara la tarea más de una vez, `ejecucion-repository` evita reevaluar ofertas el mismo día.
- **Reloj o zona horaria incorrecta:** las comparaciones de fecha dependen de la zona horaria configurada. Mitigación: valor por defecto `Europe/Madrid`, configurable, y uso explícito de la fecha local para todos los cálculos.
- **Ofertas que reaparecen tras cerrarse:** el sistema no las reabre automáticamente, lo que puede requerir una acción manual futura. Mitigación: la presencia se sigue registrando en el histórico, de modo que la interfaz futura pueda detectar la anomalía.
- **Datos de fecha corruptos:** fechas imposibles o mal formadas se detectan y excluyen del cierre por fecha, derivándose al cierre por desaparición si procede.
- **Dependencia del esquema de `api-persistencia` para lecturas históricas:** si el esquema de `ofertas` cambia en una versión futura de `api-persistencia`, `historico-read-adapter` puede dejar de funcionar. Mitigación: el acoplamiento es de solo lectura sobre columnas estables (`comunidad`, `codigo`, `estado`, `fecha_alta`, `fecha_cierre`, `fecha_fin_difusion`, `ocupacion`, `municipio`) y se detectará en tests de integración.

## Trazabilidad

| Requisito | Componentes | Decisiones |
|---|---|---|
| REQ-001 | persistencia-adapter, historico-read-adapter | DEC-006 |
| REQ-002 | historico-read-adapter, historico-api | DEC-006 |
| REQ-003 | cierre-fecha-evaluator, persistencia-adapter | DEC-005 |
| REQ-004 | cierre-fecha-evaluator, desaparicion-evaluator | DEC-005 |
| REQ-005 | desaparicion-evaluator, pdf-listado-adapter, historico-presencia-repository, persistencia-adapter | DEC-002, DEC-004 |
| REQ-006 | buscador-status-adapter, historico-task, abstenciones-repository | DEC-003 |
| REQ-007 | desaparicion-evaluator, buscador-status-adapter, abstenciones-repository | DEC-003 |
| REQ-008 | recuento-guardian, abstenciones-repository, ejecucion-repository | DEC-001, DEC-005 |
| REQ-009 | cierre-fecha-evaluator, desaparicion-evaluator, persistencia-adapter | - |
| REQ-010 | persistencia-adapter | DEC-001 |
| REQ-011 | abstenciones-repository, recuento-guardian, buscador-status-adapter, desaparicion-evaluator | DEC-001 |
| REQ-012 | historico-read-adapter, historico-api | DEC-006 |
| NFR-001 | cierre-fecha-evaluator, config-historico | - |
| NFR-002 | historico-task, ejecucion-repository | DEC-001 |
| NFR-003 | config-historico, recuento-guardian, desaparicion-evaluator | - |

## Contratos afectados

| Protocolo | Contrato | Cambio |
|---|---|---|
| HTTP/OpenAPI | `docs/contracts/openapi/api-historico.yaml` (nuevo) | Define los endpoints de consulta de altas, cierres y resumen diario del histórico. Siguiendo la estrategia `implementation-first` de `.sdd/team.md`, el contrato se derivará de la implementación. |
| Configuración | `config/historico.yaml` (nuevo) | Configuración de `api-historico`: zona horaria, hora de ejecución, número de ausencias consecutivas, umbrales de caída y recuento mínimo, y rutas de datos. |
| HTTP/OpenAPI | `docs/contracts/openapi/api-persistencia.yaml` (existente) | `api-historico` consume las operaciones de lectura/escritura de ofertas expuestas por `persistencia-api`; no se modifica el contrato. |
| Llamada interna | Contrato de uso del parser del PDF (existente) | `api-historico` invoca en proceso las funciones de `api-pdf-parser` para obtener el listado de códigos; el contrato de uso se documenta como dependencia interna. |
| SQLite (solo lectura) | Esquema documentado de `api-persistencia` | `historico-read-adapter` lee directamente la tabla `ofertas` de `data/job_emcan.db` en modo `ro` para REQ-002 y REQ-012, sin modificar el esquema ni las migraciones. Validado en SUP-004. |

## Cambios sugeridos al mapa

Los componentes descritos en este diseño (`cierre-fecha-evaluator`, `desaparicion-evaluator`, `historico-read-adapter`, etc.) son detalle interno de implementación dentro del módulo `API` y no reciben identificador propio en el mapa de arquitectura. El usuario ha decidido que el trabajo se etiquete como `APP` a efectos de tareas, aunque el código permanece en `source/api/historico/`.

- `~ Módulo: API | source/api | API FastAPI de parseo de PDFs, rastreo del buscador, persistencia y histórico de ofertas | -`
- `+ Contrato: openapi | docs/contracts/openapi/api-historico.yaml | cliente -> api-historico`
- `+ Contrato: configuracion | config/historico.yaml | api-historico -> config-historico`

## Estrategia de tests

- **Tests del evaluador de fechas:** comparación de `fecha_fin_difusion` con la fecha actual en la zona horaria configurada, detección de fechas corruptas/imposibles e idempotencia del cierre.
- **Tests del contador de ausencias:** simulación de series de presencia/ausencia, reinicio del contador al reaparecer, aplicación de N consecutivas y margen de un día.
- **Tests del recuento-guardian:** caída por encima del umbral, recuento por debajo del mínimo, primer día sin histórico y registro de abstenciones.
- **Tests de idempotencia:** reejecución sobre una oferta ya cerrada no modifica `fecha_cierre`.
- **Tests de registro de abstenciones:** pasada fallida, caída de recuento, oferta en `errores_por_oferta` y PDF no disponible.
- **Tests de integración con base de datos temporal:** persistencia de presencia, abstenciones y ejecuciones diarias.
- **Tests con parser del PDF mockeado:** verificar que `pdf-listado-adapter` alimenta correctamente al evaluador de desaparición y que los errores del parser producen abstención.
- **Tests de la tarea programada:** disparo correcto a la hora configurada, omisión en doble ejecución y abstención cuando el buscador no ha completado pasada.
- **Tests de arranque/apagado:** aplicación de migraciones propias, arranque de la tarea programada y cierre limpio sin dejar transacciones abiertas.
- **Tests de los endpoints de consulta:** altas por rango de `fecha_alta`, cierres por `fecha_cierre` o `fecha_fin_difusion`, y resumen diario de altas y cierres, usando una base temporal que simule el esquema de `api-persistencia`.

## Avisos

- `api-historico` no modifica `api-buscador`, `api-persistencia`, `api-pdf-parser` ni `.sdd/`; la integración se realiza exclusivamente a través de los contratos públicos, las llamadas en proceso documentadas y, para lecturas históricas no cubiertas, una conexión de solo lectura al SQLite de `api-persistencia`.
- El fichero SQLite propio del histórico es `data/job_emcan_historico.db` por defecto; la ruta es configurable en `config/historico.yaml`. Decidido en SUP-005.
- Las lecturas históricas por rango de fecha se resuelven con `historico-read-adapter` en modo `ro` sobre `data/job_emcan.db`, validado en SUP-004.
- No se proponen módulos nuevos en el mapa de arquitectura para los componentes del histórico; estos son detalle de implementación interno del módulo `API`. La actualización del mapa se limita a la descripción del módulo `API` y a los dos contratos nuevos (`api-historico` y `config/historico.yaml`).
- La estrategia de contratos del equipo es `implementation-first`, por lo que el OpenAPI de `api-historico` se actualizará a partir del código una vez implementado.
