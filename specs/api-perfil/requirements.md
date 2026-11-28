# Requisitos: api-perfil

Estado: aprobado
Revisión: 2
Verificación: correcta (actualizada tras validación de supuestos decisionales)

## Contexto

Esta feature especifica el perfil de búsqueda editable del usuario, cubriendo **FUN-012** (perfil con campos estructurados, criterios en lenguaje natural e historial de versiones) y dejando preparada la integración con **FUN-004** (palabras clave, sectores, municipios), **FUN-010** (encaje puntuado contra el perfil, cacheado por oferta y versión) y **FUN-013** (consulta puntual que no altera el perfil). El perfil es el criterio único y estable que alimentará los filtros, el encaje y los avisos del digest.

Dado que `api-encaje`, `api-digest`, `api-consulta-puntual` y `app-interfaz` aún no existen, esta feature se limita a modelar, validar y persistir el perfil versionado, y a publicar su versión activa para que consumidores futuros la referencien de forma estable. La siguiente feature prevista es `api-encaje`, que será la primera consumidora de la versión activa del perfil para puntuar el encaje de las ofertas.

## Fuera de alcance

- Puntuación de encaje explicado (**FUN-010**); queda para `api-encaje`.
- Generación de embeddings a partir del perfil o de las ofertas (**FUN-010**, **FUN-011**, **PDEC-019**); queda para `api-encaje`.
- Digest diario por Telegram (**FUN-004**); queda para `api-digest`.
- Consulta puntual con instrucción libre (**FUN-013**); queda para `api-consulta-puntual`.
- Interfaz de usuario (`app-interfaz`).
- Estados de candidatura, seguimiento de candidaturas y ocultación de descartadas (`api-candidaturas`).
- Exportación o importación de perfil.
- Autenticación y autorización.
- Modificación de `api-buscador`, `api-persistencia`, `api-pdf-parser`, `api-historico`, `api-integridad`, `api-listado` o de sus especificaciones aprobadas.
- Recálculo efectivo de encajes de ofertas vigentes y descartadas recientes: no existe aún `api-encaje` ni puntuaciones almacenadas, por lo que ese recálculo es una obligación futura que esta feature no implementa.

## Requisitos funcionales

### REQ-001 Perfil único de la instalación

- **Requisito:** El sistema deberá mantener un único perfil de búsqueda por instalación, identificado de forma implícita sin necesidad de clave externa.
- **Criterios de aceptación:**
  - Dado un entorno recién instalado, cuando se consulta el perfil, entonces existe a lo sumo un perfil activo.
  - Dado un intento de crear un segundo perfil independiente, cuando se resuelve, entonces el sistema lo rechaza o lo trata como una nueva versión del perfil existente.

### REQ-002 Versionado monótono del perfil

- **Requisito:** El sistema deberá asignar a cada versión del perfil un número entero monótono creciente, de modo que una versión mayor siempre represente un cambio posterior en el tiempo.
- **Criterios de aceptación:**
  - Dado un perfil con versiones `1` y `2`, cuando se crea una nueva versión, entonces recibe el número `3`.
  - Dada una versión publicada, cuando se consulta su número, entonces ese número no cambia nunca.

### REQ-003 Historial de versiones inmutable

- **Requisito:** El sistema deberá conservar un historial inmutable de todas las versiones guardadas del perfil, sin permitir su modificación ni borrado.
- **Criterios de aceptación:**
  - Dada una versión existente, cuando se intenta modificar su contenido, entonces la operación se rechaza.
  - Dada una versión existente, cuando se intenta borrarla del historial, entonces la operación se rechaza.
  - Dado un historial con varias versiones, cuando se consulta, entonces se devuelven todas en orden cronológico creciente.

### REQ-004 Campos estructurados del perfil

- **Requisito:** El sistema deberá permitir almacenar campos estructurados como listas de texto: sectores, municipios, provincias, tipos de contrato, jornadas y palabras clave.
- **Criterios de aceptación:**
  - Dado un perfil con sectores, municipios, provincias, tipos de contrato, jornadas y palabras clave, cuando se guarda, entonces cada lista se conserva en la versión correspondiente.
  - Dado un campo estructurado, cuando se consulta una versión, entonces se devuelve el mismo valor que se guardó, tras la normalización definida en SUP-H.

### REQ-005 Criterios en lenguaje natural

- **Requisito:** El sistema deberá permitir almacenar criterios de interés en lenguaje natural, como texto libre, que alimentarán el encaje explicado y el digest futuros.
- **Criterios de aceptación:**
  - Dado un perfil con criterios en lenguaje natural, cuando se guarda, entonces el texto se conserva íntegramente en la versión.
  - Dado un perfil sin criterios en lenguaje natural, cuando se consulta, entonces ese campo se representa como vacío.

### REQ-006 Soporte de varias provincias en el modelo

- **Requisito:** El modelo de perfil deberá admitir varias provincias, aunque la interfaz futura solo utilice Cantabria en el primer alcance.
- **Criterios de aceptación:**
  - Dado un perfil con varias provincias, cuando se guarda, entonces todas se conservan en la versión.
  - Dado un perfil con una sola provincia, cuando se consulta, entonces se devuelve esa provincia como única entrada de la lista.

### REQ-007 Inclusión de palabras clave

- **Requisito:** El sistema deberá permitir almacenar una lista de palabras clave, como campo estructurado adicional del perfil.
- **Criterios de aceptación:**
  - Dado un perfil con palabras clave, cuando se guarda, entonces la lista se conserva en la versión.
  - Dado un perfil sin palabras clave, cuando se consulta, entonces el campo se representa como lista vacía.

### REQ-008 Consultar el perfil activo

- **Requisito:** El sistema deberá permitir consultar el perfil activo junto con el número de versión que lo identifica.
- **Criterios de aceptación:**
  - Dado un perfil guardado, cuando se consulta el perfil activo, entonces se devuelven sus campos estructurados, sus criterios y el número de versión activa.
  - Dado un entorno sin perfil guardado, cuando se consulta el perfil activo, entonces el sistema indica explícitamente que no existe ningún perfil.

### REQ-009 Consultar el historial de versiones

- **Requisito:** El sistema deberá permitir consultar el historial de versiones, devolviendo al menos el número de versión, la marca temporal de creación y una indicación de cuál es la activa.
- **Criterios de aceptación:**
  - Dado un perfil con tres versiones, cuando se consulta el historial, entonces se devuelven tres entradas ordenadas por número de versión.
  - Dado el historial devuelto, cuando se revisa, entonces una de las versiones está marcada como activa.

### REQ-010 Consultar una versión concreta

- **Requisito:** El sistema deberá permitir consultar el contenido completo de una versión del perfil a partir de su número de versión.
- **Criterios de aceptación:**
  - Dada una versión existente, cuando se consulta por su número, entonces se devuelven todos sus campos.
  - Dada una versión inexistente, cuando se consulta por su número, entonces el sistema indica explícitamente que no existe.

### REQ-011 Crear una nueva versión y activarla

- **Requisito:** Cuando el usuario guarda cambios en el perfil, el sistema deberá crear una nueva versión con número inmediatamente superior al actual y activarla como perfil vigente.
- **Criterios de aceptación:**
  - Dado un perfil en versión `2`, cuando se guardan cambios válidos, entonces se crea la versión `3` y pasa a ser la activa.
  - Dada la versión `2`, cuando se activa la `3`, entonces la `2` permanece inmutable en el historial.

### REQ-012 Rollback a una versión anterior

- **Requisito:** El sistema deberá permitir volver a una versión anterior del perfil, creando una nueva versión que copie su contenido y activándola, sin modificar la versión original.
- **Criterios de aceptación:**
  - Dado un perfil en versión `5`, cuando se solicita volver a la versión `3`, entonces se crea una versión `6` con el mismo contenido que la `3` y se activa.
  - Dada la versión `3`, después del rollback, cuando se consulta, entonces sigue existiendo inmutable y con su número original.

### REQ-013 Validación previa sin guardar

- **Requisito:** El sistema deberá permitir validar un borrador de perfil sin crear una nueva versión ni activarla.
- **Criterios de aceptación:**
  - Dado un borrador con datos válidos, cuando se solicita validación, entonces se indica que el borrador es válido y no se crea ninguna versión nueva.
  - Dado un borrador con errores de validación, cuando se solicita validación, entonces se devuelven los errores detectados y no se crea ninguna versión nueva.

### REQ-014 Inmutabilidad de versiones publicadas

- **Requisito:** Una vez creada una versión, el sistema no deberá permitir modificar ninguno de sus campos.
- **Criterios de aceptación:**
  - Dada una versión existente, cuando se intenta alterar cualquier campo, entonces la operación se rechaza con un error de inmutabilidad.
  - Dado el historial tras un intento de modificación, cuando se consulta, entonces ninguna versión ha cambiado.

### REQ-015 Guardado sin cambios respecto a la versión activa

- **Requisito:** Si el contenido a guardar es idéntico, tras la normalización definida en SUP-H, al de la versión activa, el sistema deberá rechazar la operación o indicar que no hay cambios.
- **Criterios de aceptación:**
  - Dado un perfil activo en versión `4`, cuando se envían los mismos datos normalizados, entonces no se crea la versión `5`.
  - Dada la operación de guardado sin cambios, cuando finaliza, entonces se informa al cliente de que el perfil activo ya contiene esos valores.

### REQ-016 Control optimista de concurrencia en la escritura

- **Requisito:** El sistema deberá utilizar control optimista por versión base en las operaciones de escritura: si la versión base indicada no coincide con la versión activa actual, la operación se rechazará.
- **Criterios de aceptación:**
  - Dado un perfil activo en versión `4`, cuando un cliente intenta guardar usando como versión base la `4`, entonces la operación se permite.
  - Dado un perfil activo en versión `4`, cuando un cliente intenta guardar usando como versión base la `3`, entonces la operación se rechaza con un error de conflicto.

### REQ-017 Contenido mínimo del perfil

- **Requisito:** El sistema no deberá permitir guardar una versión cuyo contenido sea completamente vacío: al menos uno de los campos estructurados o los criterios en lenguaje natural deberá contener un valor no vacío.
- **Criterios de aceptación:**
  - Dado un perfil en el que todos los campos estructurados están vacíos y los criterios están vacíos, cuando se intenta guardar, entonces la operación se rechaza.
  - Dado un perfil con al menos un campo estructurado no vacío o criterios no vacíos, cuando se intenta guardar, entonces la validación de contenido mínimo pasa.

### REQ-018 Validación de listas

- **Requisito:** El sistema deberá validar que las listas de sectores, municipios, provincias, tipos de contrato, jornadas y palabras clave no contengan duplicados ni entradas vacías tras la normalización definida en SUP-H.
- **Criterios de aceptación:**
  - Dada una lista con un elemento vacío o solo espacios, cuando se guarda, entonces el elemento se descarta antes de persistir.
  - Dada una lista con duplicados que solo difieran en mayúsculas o tildes, cuando se guarda, entonces se conserva una sola entrada.

### REQ-019 Validación de longitudes y caracteres

- **Requisito:** El sistema deberá rechazar valores que superen los límites de longitud acordados o que contengan caracteres inválidos para los campos del perfil.
- **Criterios de aceptación:**
  - Dado un criterio en lenguaje natural que supera el límite máximo de caracteres, cuando se guarda, entonces la operación se rechaza.
  - Dado un campo estructurado con caracteres de control no permitidos, cuando se guarda, entonces la operación se rechaza.

### REQ-020 Perfil inexistente al arrancar

- **Requisito:** Antes del primer guardado del perfil, el sistema deberá indicar explícitamente que no existe perfil activo, sin crear uno por defecto.
- **Criterios de aceptación:**
  - Dado un entorno sin ningún perfil guardado, cuando se arranca la aplicación, entonces no se crea automáticamente una versión de perfil.
  - Dado un entorno sin perfil, cuando un consumidor futuro consulta el perfil activo, entonces recibe una respuesta que indica la ausencia de perfil.

### REQ-021 Publicación de la versión activa para consumidores

- **Requisito:** El sistema deberá exponer la versión activa del perfil de forma que los consumidores futuros puedan referenciarla de manera estable mediante el número de versión.
- **Criterios de aceptación:**
  - Dado un perfil activo en versión `5`, cuando un consumidor futuro consulta el perfil, entonces recibe el número de versión `5` junto con su contenido.
  - Dado el mismo perfil, cuando se activa la versión `6`, entonces los consumidores futuros reciben el número `6`.

### REQ-022 No alterar el perfil desde consultas puntuales

- **Requisito:** El sistema no deberá modificar el perfil activo ni su historial como consecuencia de operaciones de consulta o de futuras consultas puntuales.
- **Criterios de aceptación:**
  - Dado un perfil activo, cuando se realiza una consulta puntual futura, entonces la versión activa y el historial no cambian.
  - Dado el historial, después de una consulta puntual, cuando se consulta, entonces contiene las mismas versiones que antes.

### REQ-023 Recálculo de encajes como obligación futura

- **Requisito:** Cuando el perfil activo cambie, el sistema deberá permitir que `api-encaje` identifique la nueva versión y recalcule las puntuaciones de las ofertas vigentes y descartadas recientes; esta feature no realizará el recálculo ni añadirá columnas a la tabla de ofertas.
- **Criterios de aceptación:**
  - Dado un cambio de versión del perfil, cuando `api-encaje` consulta la versión activa, entonces obtiene el nuevo número de versión.
  - Dado el esquema de ofertas existente, cuando finaliza una operación de `api-perfil`, entonces no se añaden ni modifican columnas en las ofertas.

### REQ-024 Supervivencia al reinicio

- **Requisito:** El perfil y su historial deberán sobrevivir a reinicios de la aplicación, manteniendo la versión activa y todas las versiones anteriores.
- **Criterios de aceptación:**
  - Dado un perfil guardado, cuando se reinicia la aplicación, entonces la versión activa es la misma que antes del reinicio.
  - Dado un historial con varias versiones, cuando se reinicia la aplicación, entonces todas las versiones siguen disponibles.

### REQ-025 Manejo de almacenamiento no disponible o corrupto

- **Requisito:** Si el almacenamiento del perfil no está disponible o está corrupto, el sistema deberá notificar el error de forma controlada sin perder datos ya confirmados.
- **Criterios de aceptación:**
  - Dado un fallo de escritura en el almacenamiento, cuando se intenta guardar, entonces la operación se rechaza y la versión activa no cambia.
  - Dado un almacenamiento corrupto, cuando se intenta arrancar, entonces se reporta el error antes de aceptar operaciones sobre el perfil.

### REQ-026 Rollback a la versión ya activa

- **Requisito:** Si se solicita volver a la versión que ya está activa, el sistema deberá rechazar la operación o indicar que no hay cambios.
- **Criterios de aceptación:**
  - Dado un perfil activo en versión `5`, cuando se solicita rollback a la versión `5`, entonces no se crea la versión `6`.
  - Dada la operación anterior, cuando finaliza, entonces se informa al cliente de que la versión solicitada ya es la activa.

### REQ-027 Guardado de payload de gran tamaño

- **Requisito:** El sistema deberá rechazar payloads que superen el tamaño máximo permitido para el perfil.
- **Criterios de aceptación:**
  - Dado un payload que excede el límite máximo total, cuando se envía, entonces la operación se rechaza antes de procesar los campos individuales.
  - Dado un payload dentro del límite, cuando se envía, entonces se procesa normalmente.

## Requisitos no funcionales

### NFR-001 Tiempo de respuesta de consulta del perfil

- **Requisito:** El sistema deberá devolver el perfil activo, el historial o una versión concreta en menos de 500 ms en condiciones normales.
- **Criterios de aceptación:**
  - Dado un historial con hasta 100 versiones, cuando se consulta el perfil activo, entonces la respuesta llega en menos de 500 ms.

### NFR-002 Atomicidad de las escrituras

- **Requisito:** Cada operación de guardado o rollback del perfil deberá ser atómica: o se crea la nueva versión y se activa, o no se produce ningún cambio.
- **Criterios de aceptación:**
  - Dado un guardado que falla a mitad de proceso, cuando finaliza, entonces la versión activa sigue siendo la anterior y no queda una versión parcial.

### NFR-003 Concurrencia con ingesta y purga de ofertas

- **Requisito:** El almacenamiento separado del perfil deberá evitar interferencias entre las escrituras del perfil y la ingesta o purga de ofertas.
- **Criterios de aceptación:**
  - Dada una escritura de perfil concurrente con una ingesta de ofertas, cuando ambas finalizan, entonces ambas operaciones quedan consistentes sin bloqueos indefinidos, gracias a que cada dominio usa su propio fichero SQLite.

### NFR-004 Codificación UTF-8

- **Requisito:** El sistema deberá almacenar y devolver todos los campos de texto del perfil en UTF-8, conservando tildes, eñes y otros caracteres Unicode válidos.
- **Criterios de aceptación:**
  - Dado un municipio "Tresviso", cuando se guarda y se consulta, entonces se devuelve exactamente "Tresviso".
  - Dado un criterio con tildes y eñes, cuando se guarda y se consulta, entonces los caracteres se conservan sin alteración.

### NFR-005 Límite de tamaño del payload

- **Requisito:** El sistema no deberá aceptar payloads de perfil superiores a 1 MB.
- **Criterios de aceptación:**
  - Dado un payload de 1,5 MB, cuando se envía, entonces se rechaza.
  - Dado un payload de 500 KB, cuando se envía, entonces se acepta para validación.

### NFR-006 Conservación del historial

- **Requisito:** El sistema no deberá perder versiones históricas del perfil como consecuencia de guardados, rollbacks o reinicios.
- **Criterios de aceptación:**
  - Dado un historial con 10 versiones, después de 10 guardados adicionales, cuando se consulta el historial, entonces contiene las 20 versiones originales.

### NFR-007 Recuperación ante corrupción parcial

- **Requisito:** Si se detecta corrupción en el almacenamiento del perfil, el sistema deberá abortar el arranque o rechazar operaciones sobre el perfil, sin propagar datos corruptos.
- **Criterios de aceptación:**
  - Dado un fichero de almacenamiento de perfil corrupto, cuando se arranca la aplicación, entonces se reporta el error y no se sirven perfiles inconsistentes.

## Supuestos

### SUP-A Dónde vive el perfil

- **Tipo:** decisional
- **Descripción:** El perfil se almacena en un segundo fichero SQLite propio (`data/job_emcan_perfil.db`), con su propia conexión, WAL y `busy_timeout`, independiente de `data/job_emcan.db` y de la tabla `schema_version` de `api-persistencia`. Esto respeta el control de versiones de `api-persistencia`, evita interferir con su migrador y sigue el precedente aceptado de `api-historico`. La alternativa descartada es añadir tablas del perfil en `data/job_emcan.db` con un migrador propio de `api-perfil`, porque implicaría compartir el mismo fichero con dos migradores independientes, aumentando el riesgo de conflictos en el versionado del esquema.
- **Impacto:** REQ-024, REQ-025, NFR-002, NFR-003, NFR-007; el arranque abre y migra el fichero propio del perfil sin tocar `api-persistencia`.
- **Estado:** validado

### SUP-B Un perfil o varios

- **Tipo:** decisional
- **Descripción:** Se decide mantener un único perfil por instalación, con historial de versiones. La alternativa descartada es soportar varios perfiles con nombre, que complicaría el modelo, los criterios de encaje y la configuración del digest sin necesidad en el alcance actual.
- **Impacto:** REQ-001, REQ-002, REQ-011, REQ-012 y todas las operaciones de consulta.
- **Estado:** validado

### SUP-C Rollback

- **Tipo:** decisional
- **Descripción:** Se decide que volver a una versión anterior cree una nueva versión (`n+1`) que copie el contenido de la versión objetivo y se active. La alternativa descartada es reactivar la versión antigua como activa sin crear una nueva, lo que rompería la propiedad de que `version` identifica unívocamente lo que se puntuó en un momento dado.
- **Impacto:** REQ-002, REQ-012, REQ-014, REQ-021 e integración futura con `api-encaje`.
- **Estado:** validado

### SUP-D Campos exactos del perfil

- **Tipo:** decisional
- **Descripción:** Se decide que el perfil contenga los campos estructurados `sectores`, `municipios`, `provincias`, `contrato`, `jornada` y `palabras_clave`, todos ellos como listas de texto, más el texto libre `criterios` como un único bloque de texto. No entra `nivel`. La alternativa descartada es usar solo los campos que menciona FUN-012, omitir `palabras_clave` (a pesar de FUN-004) o modelar `contrato` y `jornada` como valores únicos, lo que limitaría la flexibilidad del perfil.
- **Impacto:** REQ-004, REQ-005, REQ-006, REQ-007, REQ-017, REQ-018, REQ-019 y validación.
- **Estado:** validado

### SUP-E Recálculo de encajes

- **Tipo:** decisional
- **Descripción:** Se decide que `api-perfil` solo publica la versión activa y el historial; el recálculo de encajes de ofertas vigentes y descartadas recientes al cambiar el perfil será responsabilidad de `api-encaje`, que referenciará la versión del perfil. No se añade ninguna columna a la tabla de ofertas en esta feature.
- **Impacto:** REQ-021, REQ-023; FUN-012 queda cubierto parcialmente hasta que exista `api-encaje`.
- **Estado:** validado

### SUP-F Perfil vacío

- **Tipo:** decisional
- **Descripción:** Se decide no permitir guardar una versión en la que todos los campos estructurados estén vacíos y los criterios en lenguaje natural también estén vacíos. Antes del primer guardado, no existe perfil y la API lo indica explícitamente.
- **Impacto:** REQ-017, REQ-020 y experiencia de arranque.
- **Estado:** validado

### SUP-G Concurrencia de edición

- **Tipo:** decisional
- **Descripción:** Se decide usar control optimista con `version_base`: toda operación de escritura deberá indicar la versión activa sobre la que se basa; si no coincide, se rechaza el guardado con conflicto. La alternativa descartada es el bloqueo pesimista, que añade complejidad innecesaria para un uso personal y un único editor.
- **Impacto:** REQ-016 y la operación de guardado/rollback.
- **Estado:** validado

### SUP-H Normalización de listas

- **Tipo:** decisional
- **Descripción:** Se decide que las listas de texto (`sectores`, `municipios`, `provincias`, `contrato`, `jornada`, `palabras_clave`) se normalicen aplicando `trim`, descartando entradas vacías y deduplicando sin distinguir mayúsculas ni tildes, conservando la forma escrita para mostrar. La alternativa descartada es guardar los valores exactamente como llegan, lo que dificultaría la comparación futura con ofertas.
- **Impacto:** REQ-004, REQ-015, REQ-018 y la futura comparación con ofertas.
- **Estado:** validado

## Preguntas abiertas

Ninguna.

## Trazabilidad

| Requisito / Supuesto | Funcionalidad de producto | Decisión de producto |
|---|---|---|
| REQ-001 | FUN-012 | PDEC-008 |
| REQ-002 | FUN-012 | PDEC-008, PDEC-009 |
| REQ-003 | FUN-012 | PDEC-009 |
| REQ-004 | FUN-012 | - |
| REQ-005 | FUN-012 | PDEC-008 |
| REQ-006 | FUN-012 | PDEC-017 |
| REQ-007 | FUN-004 | PDEC-008 |
| REQ-008 | FUN-012 | - |
| REQ-009 | FUN-012 | - |
| REQ-010 | FUN-012 | - |
| REQ-011 | FUN-012 | - |
| REQ-012 | FUN-012 | PDEC-009, SUP-C |
| REQ-013 | FUN-012 | - |
| REQ-014 | FUN-012 | PDEC-009 |
| REQ-015 | FUN-012 | SUP-H |
| REQ-016 | FUN-012 | SUP-G |
| REQ-017 | FUN-012 | SUP-F |
| REQ-018 | FUN-012 | SUP-H |
| REQ-019 | FUN-012 | - |
| REQ-020 | FUN-012 | SUP-F |
| REQ-021 | FUN-010, FUN-012 | PDEC-009, SUP-E |
| REQ-022 | FUN-013 | PDEC-008 |
| REQ-023 | FUN-010, FUN-012 | PDEC-009, SUP-E |
| REQ-024 | FUN-012 | SUP-A |
| REQ-025 | FUN-012 | SUP-A |
| REQ-026 | FUN-012 | SUP-C |
| REQ-027 | FUN-012 | NFR-005 |
| NFR-001 | FUN-012 | - |
| NFR-002 | FUN-012 | SUP-A |
| NFR-003 | FUN-012 | PDEC-017, SUP-A |
| NFR-004 | FUN-012 | - |
| NFR-005 | FUN-012 | - |
| NFR-006 | FUN-012 | PDEC-009 |
| NFR-007 | FUN-012 | SUP-A |
| SUP-A | FUN-012 | PDEC-003 |
| SUP-B | FUN-012 | - |
| SUP-C | FUN-012 | PDEC-009 |
| SUP-D | FUN-004, FUN-012 | PDEC-008, PDEC-017 |
| SUP-E | FUN-010, FUN-012 | PDEC-009 |
| SUP-F | FUN-012 | - |
| SUP-G | FUN-012 | - |
| SUP-H | FUN-004, FUN-012 | PDEC-008 |

## Avisos

- **Cobertura parcial de FUN-012:** esta feature especifica y persistirá el perfil versionado con campos estructurados y criterios en lenguaje natural, pero el recálculo de encajes de ofertas vigentes y descartadas recientes queda pendiente de `api-encaje`. El historial conservará la versión con la que se puntuó, pero `api-perfil` no realiza la puntuación.
- **Cobertura parcial de FUN-004:** se incluyen palabras clave, sectores y municipios en el modelo del perfil, pero el aviso por Telegram y el digest diario quedan fuera del alcance para `api-digest`.
- **Cobertura parcial de FUN-010:** el perfil publica su versión activa para que `api-encaje` pueda cachear y recalcular el encaje por oferta y versión, pero `api-perfil` no calcula embeddings ni puntuaciones.
- **Cobertura parcial de FUN-013:** esta feature garantiza que ninguna operación suya modifica el perfil, pero la consulta puntual con instrucción libre será responsabilidad de `api-consulta-puntual`.
- **Interfaz de usuario:** `app-interfaz` no existe; esta feature es puramente de API y modelo de datos.
- **Persistencia:** el perfil vive en `data/job_emcan_perfil.db`, un segundo fichero SQLite propio con WAL y `busy_timeout`, gestionado por su propio migrador e independiente de `data/job_emcan.db` y de la tabla `schema_version` de `api-persistencia`. Esto sigue el precedente aceptado de `api-historico` y evita tocar `api-persistencia`.
- **No se modifica `api-persistencia`:** la ubicación física del perfil se ha decidido en SUP-A. Se descarta añadir tablas al mismo fichero SQLite con un migrador propio, porque implicaría compartir el fichero con dos migradores independientes.
