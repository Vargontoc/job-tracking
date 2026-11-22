# Requisitos: api-historico

Estado: aprobado
Revisión: 2
Verificación: correcta

## Contexto

Esta feature cierra el ciclo de **FUN-003** (histórico de altas y cierres). Se alimenta de la base de datos que `api-persistencia` mantiene como fuente de verdad, consulta el estado publicado por `api-buscador` para aplicar márgenes de seguridad y, como respaldo para ofertas sin fecha de fin de difusión, puede usar el listado oficial extraído del PDF de difusión. No modifica `api-buscador`, `api-persistencia`, `api-pdf-parser` ni `.sdd`.

## Referencias

- `docs/product/producto.md`: FUN-003, FUN-014, PDEC-002, PDEC-011, PDEC-014, PDEC-016, PDEC-019, nota línea 15.
- `specs/api-persistencia/requirements.md`: REQ-003, REQ-017, REQ-018, SUP-011, SUP-013.
- `specs/api-persistencia/design.md`: esquema `ofertas`, estados `sin_ficha`/`vigente`/`cerrada`, campos `fecha_fin_difusion`, `fecha_cierre`, `fecha_alta`.
- `specs/api-buscador/requirements.md`: REQ-013, REQ-015.
- `source/api/buscador/models.py`, `source/api/buscador/routes.py`, `source/api/buscador/coordinator.py`: contrato de `GET /buscador/status`.
- `specs/api-pdf-parser/requirements.md`: módulo de parseo del PDF de difusión, invocado en proceso por `api-historico` (no mediante el endpoint HTTP `GET /parse`).
- `.sdd/project.md` y `.sdd/architecture.md`.

## Fuera de alcance

- Modificar `api-buscador`, `api-persistencia`, `api-pdf-parser` o `.sdd/`.
- Descargar fichas de oferta o lanzar pasadas del buscador.
- Enviar avisos por Telegram ni construir interfaz de usuario.
- Calcular encaje, gestionar perfiles o generar embeddings.
- Gestionar estados de candidatura (`interesada`, `inscrito`, etc.) ni búsqueda semántica.
- Implementar la purga de registros: `api-persistencia` ya la define en su alcance (PDEC-016).

## Requisitos funcionales

### REQ-001 No duplicar la ingesta de altas

- **Requisito:** El sistema no creará ni actualizará ofertas por sí mismo; considerará que una oferta está dada de alta cuando `api-persistencia` persiste una nueva oferta con estado `vigente` a partir de `ofertas_nuevas` publicadas por `api-buscador`.
- **Criterios de aceptación:**
  - Dado que `api-persistencia` acaba de crear una oferta en estado `vigente` a partir de `ofertas_nuevas`, cuando consulta el histórico de altas, entonces la oferta aparece como alta.
  - Dado un código importado desde `data/seen_codes.json` con estado `sin_ficha`, cuando se consultan altas, entonces no se cuenta como alta aunque `api-persistencia` lo tenga registrado.
  - Dado una ejecución del histórico sin nuevas ofertas ingeridas, cuando finaliza, entonces no crea registros ni modifica estados en la base de datos.

### REQ-002 Consultar altas por fecha

- **Requisito:** El sistema deberá permitir consultar las ofertas dadas de alta en un rango de fechas, usando la `fecha_alta` que `api-persistencia` registró al crear el registro.
- **Criterios de aceptación:**
  - Dadas dos fechas y una oferta cuya `fecha_alta` está dentro del rango, cuando se consultan altas, entonces la oferta aparece en el resultado.
  - Dadas dos fechas y una oferta cuya `fecha_alta` está fuera del rango, cuando se consultan altas, entonces la oferta no aparece en el resultado.
  - Dado el resultado de una consulta de altas, cuando se revisa, entonces incluye al menos comunidad, código, ocupación, municipio, fecha de inicio de difusión y estado.

### REQ-003 Cierre por fecha de fin de difusión

- **Requisito:** El sistema deberá cerrar una oferta en estado `vigente` cuya `fecha_fin_difusion` no esté vacía y sea estrictamente anterior a la fecha actual en la zona horaria configurada, cambiando su estado a `cerrada` y registrando `fecha_cierre` en formato ISO 8601 la primera vez que se detecta el cierre.
- **Criterios de aceptación:**
  - Dada una oferta vigente con `fecha_fin_difusion = 20/11/2026` y hoy = 21/11/2026, cuando se ejecuta el cierre por fecha, entonces el estado pasa a `cerrada` y `fecha_cierre` se rellena con la marca de tiempo de la detección.
  - Dada una oferta vigente con `fecha_fin_difusion = 21/11/2026` y hoy = 21/11/2026, cuando se ejecuta el cierre por fecha, entonces el estado permanece `vigente`.
  - Dada una oferta ya cerrada por este requisito, cuando se vuelve a ejecutar el cierre por fecha, entonces `fecha_cierre` no cambia y no se genera un segundo registro de cierre.
  - Dada una oferta vigente con `fecha_fin_difusion` vacía, cuando se ejecuta el cierre por fecha, entonces no se marca como cerrada y se deriva al cierre por desaparición (REQ-005).

### REQ-004 Pasar al respaldo las fichas sin fecha de fin

- **Requisito:** Cuando una oferta vigente no publique `fecha_fin_difusion`, el sistema no la cerrará por fecha y la considerará candidata al cierre por desaparición del listado.
- **Criterios de aceptación:**
  - Dada una oferta vigente sin `fecha_fin_difusion`, cuando se ejecuta el cierre por fecha, entonces su estado sigue siendo `vigente`.
  - Dada la misma oferta, cuando el cierre por desaparición está habilitado, entonces se evalúa según REQ-005.
  - Dada una oferta vigente con `fecha_fin_difusion` informada, cuando se ejecuta el cierre por fecha, entonces se evalúa según REQ-003 y no entra en el cierre por desaparición.

### REQ-005 Cierre por desaparición del listado (respaldo)

- **Requisito:** Donde una oferta vigente no tenga `fecha_fin_difusion`, el sistema deberá poder cerrarla cuando su código falte en N listados oficiales consecutivos, usando el listado oficial del día obtenido en proceso a partir del PDF de difusión (SUP-001) y respetando el margen de un día (N = 2 por defecto, configurable).
- **Criterios de aceptación:**
  - Dado una oferta vigente sin `fecha_fin_difusion` que aparece en el listado oficial actual, cuando se ejecuta el cierre por desaparición, entonces permanece `vigente`.
  - Dado una oferta vigente sin `fecha_fin_difusion` ausente del listado oficial actual pero presente en el anterior, cuando se ejecuta el cierre por desaparición, entonces permanece `vigente` (margen de un día).
  - Dado una oferta vigente sin `fecha_fin_difusion` ausente del listado oficial actual y del anterior, cuando se ejecuta el cierre por desaparición, entonces el estado pasa a `cerrada` y se registra `fecha_cierre`.
  - Dado que la fuente de respaldo no está disponible o devuelve error, cuando se ejecuta el cierre por desaparición, entonces no se marca ninguna oferta como cerrada y se registra la abstención.
  - Dada una oferta ya cerrada, cuando se vuelve a evaluar la desaparición, entonces no se modifica su `fecha_cierre`.

### REQ-006 No cerrar si la pasada del buscador falla

- **Requisito:** Si `GET /buscador/status` indica `error_global`, `ultima_pasada` nula o el buscador no responde, el sistema no marcará ninguna oferta como cerrada y dejará constancia de la abstención.
- **Criterios de aceptación:**
  - Dado que `GET /buscador/status` devuelve `ultima_pasada = null`, cuando se ejecuta el proceso de cierres, entonces no se marca ninguna oferta como cerrada.
  - Dado que `GET /buscador/status` devuelve `error_global` no vacío, cuando se ejecuta el proceso de cierres, entonces no se marca ninguna oferta como cerrada.
  - Dado que el buscador no responde, cuando se ejecuta el proceso de cierres, entonces no se marca ninguna oferta como cerrada.
  - En cada caso, cuando finaliza el proceso, entonces queda registrado el motivo de abstención, la marca de tiempo y el recuento consultado.

### REQ-007 No cerrar por desaparición las ofertas con error en la última pasada

- **Requisito:** El sistema no cerrará por desaparición del listado una oferta cuyo código aparezca en `errores_por_oferta` de la última pasada del buscador.
- **Criterios de aceptación:**
  - Dada una oferta vigente sin `fecha_fin_difusion` cuyo código está en `errores_por_oferta`, cuando se evalúa el cierre por desaparición, entonces permanece `vigente`.
  - Dada una oferta vigente sin `fecha_fin_difusion` cuyo código no está en `errores_por_oferta`, cuando se evalúa el cierre por desaparición, entonces se aplican las reglas normales.
  - Dado el registro de abstenciones, cuando una oferta se ha excluido por estar en `errores_por_oferta`, entonces figuran su código y el motivo.

### REQ-008 Protección ante caída anómala del recuento

- **Requisito:** Antes de aplicar cierres por desaparición, el sistema comparará `total_listado` de la última pasada exitosa con el de la pasada anterior; si la caída supera el 30 % o el recuento es inferior a 70 ofertas, se abstendrá de cerrar y dejará constancia.
- **Criterios de aceptación:**
  - Dado que el recuento anterior fue 93 y el actual es 60, cuando se ejecuta el cierre por desaparición, entonces no se marca ninguna oferta como cerrada.
  - Dado que el recuento anterior fue 93 y el actual es 92, cuando se ejecuta el cierre por desaparición, entonces se aplican las reglas normales.
  - Dado que el recuento actual es 65, cuando se ejecuta el cierre por desaparición, entonces no se marca ninguna oferta como cerrada aunque la caída no supere el 30 %.
  - Cuando se produce una abstención por caída anómala, entonces queda registrado el recuento anterior, el actual y el umbral aplicado.

### REQ-009 No cerrar ofertas `sin_ficha`

- **Requisito:** El sistema no marcará como cerradas automáticamente las ofertas en estado `sin_ficha`, ni por fecha ni por desaparición del listado.
- **Criterios de aceptación:**
  - Dada una oferta en estado `sin_ficha` sin `fecha_fin_difusion`, cuando se ejecutan los cierres, entonces permanece en `sin_ficha`.
  - Dada una oferta en estado `sin_ficha` que no aparece en el listado oficial, cuando se ejecuta el cierre por desaparición, entonces permanece en `sin_ficha`.
  - Dada una oferta en estado `sin_ficha` que posteriormente se ingiere como `vigente`, cuando se ejecutan los cierres, entonces se evalúa como oferta vigente.

### REQ-010 No adelantar ni duplicar la purga

- **Requisito:** El sistema solo marcará ofertas como `cerrada` y registrará `fecha_cierre`; no eliminará ni reducirá campos antes de que `api-persistencia` aplique su política de purga tras `fecha_cierre`.
- **Criterios de aceptación:**
  - Dada una oferta cerrada, cuando `api-historico` finaliza su proceso, entonces el texto libre y el contacto siguen presentes (si la purga de `api-persistencia` aún no ha actuado).
  - Dado que una oferta cerrada no ha superado los 7 días desde `fecha_cierre`, cuando se consulta, entonces conserva todos sus campos.
  - Dado el código de `api-historico`, cuando se revisa, entonces no contiene lógica de reducción a registro mínimo ni de eliminación de embeddings.

### REQ-011 Registrar abstenciones de cierre

- **Requisito:** Cada vez que el sistema se abstenga de cerrar ofertas por un margen de seguridad, dejará constancia del motivo, la marca de tiempo, los recuentos relevantes y los códigos afectados.
- **Criterios de aceptación:**
  - Dado que se ha abstenido por pasada fallida, cuando se consulta el registro de abstenciones, entonces aparece el motivo, la marca de tiempo y el estado consultado del buscador.
  - Dado que se ha abstenido por caída anómala del recuento, cuando se consulta el registro, entonces aparecen el recuento anterior, el actual y el umbral.
  - Dado que se ha abstenido porque una oferta estaba en `errores_por_oferta`, cuando se consulta el registro, entonces aparece el código de la oferta y el motivo.

### REQ-012 Consultar cierres y resumen del histórico

- **Requisito:** El sistema deberá permitir consultar las ofertas cerradas en un rango de fechas (por `fecha_cierre` o por `fecha_fin_difusion`) y obtener un resumen de altas y cierres agrupado por día.
- **Criterios de aceptación:**
  - Dadas dos fechas y una oferta cerrada cuya `fecha_cierre` está dentro del rango, cuando se consultan cierres, entonces la oferta aparece en el resultado.
  - Dadas dos fechas y una oferta cerrada cuya `fecha_fin_difusion` está dentro del rango, cuando se consultan cierres por fecha de fin, entonces la oferta aparece en el resultado.
  - Dado un resumen diario de histórico, cuando se consulta, entonces incluye el número de altas y el número de cierres de cada día.
  - Dado el resultado de cualquier consulta histórica, cuando se revisa, entonces incluye al menos comunidad, código, ocupación, municipio, estado, `fecha_alta`, `fecha_fin_difusion` y `fecha_cierre`.

## Requisitos no funcionales

### NFR-001 Zona horaria para comparaciones de fecha

- **Requisito:** El sistema deberá usar una zona horaria configurable para determinar la fecha actual en las comparaciones de cierre; el valor por defecto será `Europe/Madrid`.
- **Criterios de aceptación:**
  - Dada la configuración por defecto, cuando se compara una `fecha_fin_difusion` con la fecha actual, entonces se usa `Europe/Madrid`.
  - Dada una configuración con otra zona horaria válida, cuando se compara una fecha, entonces se usa la zona configurada.

### NFR-002 Ejecución diaria del cierre

- **Requisito:** El proceso de cierre deberá ejecutarse como máximo una vez al día, tras la pasada programada del buscador.
- **Criterios de aceptación:**
  - Dado un día en el que ya se ha ejecutado el cierre, cuando se solicita una nueva ejecución, entonces no se vuelven a evaluar las ofertas hasta el día siguiente.
  - Dado un día sin ejecución previa, cuando llega la hora configurada, entonces se ejecuta una sola vez.

### NFR-003 Configuración de umbrales

- **Requisito:** Los umbrales de protección (caída de recuento, recuento mínimo, número de ausencias consecutivas) deberán ser configurables sin modificar código.
- **Criterios de aceptación:**
  - Dado un fichero de configuración con un umbral de caída del 20 %, cuando se ejecuta el cierre por desaparición, entonces se usa el 20 % en lugar del 30 % por defecto.
  - Dado un fichero de configuración con un recuento mínimo de 80, cuando se ejecuta el cierre por desaparición, entonces se usa 80 en lugar del 70 por defecto.
  - Dado un fichero de configuración con N = 3 ausencias consecutivas, cuando se ejecuta el cierre por desaparición, entonces se requieren tres listados sin el código.

## Supuestos

### SUP-001 Fuente de respaldo para el cierre por desaparición

- **Tipo:** decisional
- **Descripción:** Para cerrar ofertas sin `fecha_fin_difusion` se invocará en proceso el módulo de parseo del PDF de difusión (`api-pdf-parser`) para obtener el listado oficial de códigos del día. Si el PDF no se puede descargar o el parseo devuelve errores, el cierre por desaparición se suspende. No se realiza llamada HTTP ni se usa el endpoint `GET /parse`. Alternativas descartadas: comparar solo `total_listado` (no aporta la lista de códigos) y descargar el listado HTML desde `api-historico` (tocaría la fuente del buscador y duplicaría lógica de `api-buscador`).
- **Impacto:** REQ-005, REQ-006, REQ-008, NFR-003.
- **Estado:** validado

### SUP-002 No modificar features aprobadas

- **Tipo:** contextual
- **Descripción:** `api-buscador`, `api-persistencia`, `api-pdf-parser` y `.sdd/` permanecen aprobados e inalterados; `api-historico` se integra leyendo sus contratos y consultando sus endpoints.
- **Impacto:** Todos los requisitos.
- **Estado:** validado

### SUP-003 `api-persistencia` como fuente de verdad

- **Tipo:** contextual
- **Descripción:** `api-historico` no mantiene su propia base de datos de ofertas; lee y actualiza el estado a través de la API de persistencia, que ya garantiza unicidad por `(comunidad, codigo)` y conserva `fecha_alta` y `fecha_cierre`.
- **Impacto:** REQ-001, REQ-002, REQ-010, REQ-012.
- **Estado:** validado

## Preguntas abiertas

Ninguna.

## Trazabilidad

| Requisito | Funcionalidad de producto | Decisión de producto |
|---|---|---|
| REQ-001 | FUN-003 | PDEC-014, PDEC-016 |
| REQ-002 | FUN-003 | PDEC-014 |
| REQ-003 | FUN-003 | PDEC-014 |
| REQ-004 | FUN-003 | PDEC-014 |
| REQ-005 | FUN-003 | PDEC-002, PDEC-014 |
| REQ-006 | FUN-003, FUN-014 | PDEC-011 |
| REQ-007 | FUN-003 | PDEC-011 |
| REQ-008 | FUN-003, FUN-014 | PDEC-011, PDEC-014 |
| REQ-009 | FUN-003 | PDEC-016, SUP-011 (api-persistencia) |
| REQ-010 | FUN-003 | PDEC-016 |
| REQ-011 | FUN-003, FUN-014 | PDEC-011 |
| REQ-012 | FUN-003 | PDEC-014 |
| NFR-001 | - | Convención de arquitectura |
| NFR-002 | - | PDEC-015 |
| NFR-003 | - | PDEC-011 |
| SUP-001 | FUN-003, FUN-014 | PDEC-013, PDEC-014 |
