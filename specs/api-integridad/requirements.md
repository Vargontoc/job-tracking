# Requisitos: api-integridad

Estado: aprobado
Revisión: 2
Verificación: correcta (actualizada tras validación de supuestos)

## Contexto

Esta feature completa la parte operativa de **FUN-014**: descarga diaria del PDF oficial de difusión, conservación del último mes, comparación de su recuento con el `total_listado` publicado por `api-buscador` y emisión de un veredicto de integridad informativo que indica cuándo los cierres no deberían producirse. Hoy no se integra con `api-historico` ni se le impide marcar cierres; el veredicto es consultable y los consumidores futuros (incluido `api-historico`) podrán actuar sobre él. No modifica `api-pdf-parser`, `api-buscador`, `api-persistencia` ni `api-historico`; se integra con sus contratos y componentes existentes.

## Referencias

- `docs/product/producto.md`: FUN-014, PDEC-011, PDEC-013, PDEC-014, pregunta abierta línea 146.
- `specs/api-pdf-parser/requirements.md`, `design.md`, `tasks.md`: descarga y parseo implementados, sin persistencia ni conservación del PDF.
- `specs/api-buscador/requirements.md`: `GET /buscador/status` y su `ultima_pasada.total_listado`.
- `source/api/buscador/models.py`, `source/api/buscador/routes.py`: estructura de `ultima_pasada`.
- `specs/api-historico/requirements.md`, `design.md`: feature aprobada que marca cierres y no se modifica.
- `specs/api-persistencia/requirements.md`, `design.md`: base de datos `data/job_emcan.db` y estados de oferta.
- `.sdd/project.md`, `.sdd/architecture.md`, `.sdd/team.md`: stack, módulo `API`, convenciones y estrategia `implementation-first`.

## Fuera de alcance

- Modificar `api-buscador`, `api-persistencia`, `api-pdf-parser` o `api-historico`.
- Descargar fichas individuales del buscador o lanzar pasadas del buscador.
- Enviar avisos por Telegram ni construir interfaz de usuario.
- Reescribir la lógica de parseo del PDF; se reutiliza la existente.
- Calcular encajes, gestionar embeddings ni estados de candidatura.
- Integrar el veredicto con `api-historico` ni modificar su comportamiento de cierre; el veredicto es informativo y consultable.

## Requisitos funcionales

### REQ-001 Descarga diaria del PDF de difusión

- **Requisito:** Cuando llegue la hora configurada, el sistema deberá descargar una vez al día, para cada comunidad configurada, el PDF oficial de difusión usando el descargador existente de `api-pdf-parser`, y registrar la fecha, comunidad, resultado y errores.
- **Criterios de aceptación:**
  - Dado un día sin ejecución previa, cuando llega la hora configurada, entonces el sistema descarga el PDF de cada comunidad configurada.
  - Dado que ya existe una descarga exitosa para hoy, cuando se dispara el proceso de nuevo, entonces no se vuelve a descargar el PDF para la misma comunidad.
  - Dada una comunidad configurada, cuando la descarga finaliza, entonces queda registrada la fecha, la comunidad, el estado (éxito o fallo) y, si aplica, el mensaje de error.

### REQ-002 Conservación del PDF del último mes

- **Requisito:** El sistema deberá almacenar cada PDF descargado con un nombre identificable por fecha y comunidad, y eliminar los PDF que superen el período de retención configurado (30 días por defecto).
- **Criterios de aceptación:**
  - Dado un PDF descargado correctamente el 22/11/2026 para Cantabria, cuando finaliza el proceso, entonces existe un fichero cuyo nombre permite identificar la fecha y la comunidad.
  - Dado un PDF almacenado con más de 30 días de antigüedad, cuando se ejecuta la limpieza diaria, entonces el fichero se elimina.
  - Dado un PDF almacenado con 30 días o menos, cuando se ejecuta la limpieza diaria, entonces el fichero se conserva.
  - Dado que la descarga o el parseo del día fallan, cuando finaliza el proceso, entonces no se conserva un PDF válido para esa fecha y comunidad, y el fallo queda registrado.

### REQ-003 Comparación de recuentos con el buscador

- **Requisito:** Cuando el PDF se haya parseado correctamente, el sistema deberá comparar el número de ofertas extraídas del PDF con el valor `total_listado` de la última pasada publicada por `api-buscador`.
- **Criterios de aceptación:**
  - Dado un PDF con 92 ofertas y un `total_listado` de 93, cuando se ejecuta la comparación, entonces el sistema registra ambos recuentos y la diferencia.
  - Dado que `GET /buscador/status` no devuelve `ultima_pasada`, cuando se ejecuta la comparación, entonces no se emite veredicto favorable y se registra el motivo.
  - Dado que `ultima_pasada` contiene un `error_global` no vacío, cuando se ejecuta la comparación, entonces no se emite veredicto favorable y se registra el motivo.

### REQ-004 Emisión del veredicto de integridad

- **Requisito:** El sistema deberá emitir un veredicto diario de integridad (`concordante`, `divergente` o `fallido`) aplicando la tolerancia y el umbral de cordura configurados.
- **Criterios de aceptación:**
  - Dados recuentos dentro de la tolerancia configurada y el recuento del PDF por encima del umbral de cordura, cuando se completa la comparación, entonces el veredicto es `concordante`.
  - Dados recuentos fuera de la tolerancia o el recuento del PDF por debajo del umbral de cordura, cuando se completa la comparación, entonces el veredicto es `divergente`.
  - Dado un fallo de descarga o parseo del PDF, cuando finaliza el proceso, entonces el veredicto es `fallido`.

### REQ-005 Persistencia del veredicto diario

- **Requisito:** El sistema deberá persistir el veredicto de integridad de cada día, incluyendo la marca de tiempo, la comunidad, ambos recuentos, la diferencia, los umbrales aplicados y el resultado.
- **Criterios de aceptación:**
  - Dado un proceso de integridad completado, cuando se consulta el veredicto del día, entonces existe un registro con timestamp, comunidad, recuento PDF, recuento buscador, diferencia, umbrales y veredicto.
  - Dado que el mismo día se ejecuta dos veces con éxito, cuando se revisan los registros, entonces no se generan dos veredictos duplicados para esa comunidad y fecha.

### REQ-006 Veredicto informativo de integridad

- **Requisito:** El sistema deberá exponer el último veredicto de integridad como un registro consultable que indique si los cierres del día están recomendados; mientras el veredicto sea `divergente`, `fallido` o inexistente, el veredicto señalará que no se recomienda cerrar ofertas.
- **Criterios de aceptación:**
  - Dado un veredicto `divergente` para hoy, cuando se consulta el estado de integridad, entonces la respuesta indica que cerrar ofertas no es recomendable.
  - Dado un veredicto `fallido` para hoy, cuando se consulta el estado de integridad, entonces la respuesta indica que cerrar ofertas no es recomendable.
  - Dado que no existe veredicto para hoy, cuando se consulta el estado de integridad, entonces la respuesta indica que cerrar ofertas no es recomendable.
  - Dado un veredicto `concordante` para hoy, cuando se consulta el estado de integridad, entonces la respuesta indica que cerrar ofertas es recomendable, sin perjuicio de las protecciones propias de `api-historico`.
  - Dado el código de la feature, cuando se revisa, entonces no contiene lógica que impida o bloquee directamente los cierres de `api-historico`.

### REQ-007 Aviso de fallo o divergencia

- **Requisito:** Cuando se produzca un fallo de descarga, un fallo de parseo o una divergencia de recuentos, el sistema deberá registrar un aviso consultable con fecha, recuentos, umbral y motivo. No se enviará Telegram.
- **Criterios de aceptación:**
  - Dada una divergencia de recuentos, cuando se produce, entonces existe un aviso con la fecha, el recuento del PDF, el `total_listado`, la diferencia, el umbral aplicado y el motivo.
  - Dado un fallo de descarga o parseo, cuando se produce, entonces existe un aviso con la fecha, la comunidad afectada y el motivo.
  - Dado el código de la feature, cuando se revisa, entonces no contiene integración con Telegram ni otro canal de notificación externo.

### REQ-008 Registro de ejecuciones

- **Requisito:** El sistema deberá registrar cada ejecución del proceso de integridad con su marca de tiempo, el resultado global, los errores por comunidad y el veredicto emitido.
- **Criterios de aceptación:**
  - Dada una ejecución exitosa, cuando finaliza, entonces el registro contiene la marca de tiempo, el resultado `ok`, el veredicto y los recuentos.
  - Dada una ejecución con errores parciales, cuando finaliza, entonces el registro contiene la comunidad afectada y el mensaje de error.

### REQ-009 Consulta del estado de integridad

- **Requisito:** El sistema deberá permitir consultar el último veredicto de integridad, las ejecuciones del último mes y los PDFs conservados.
- **Criterios de aceptación:**
  - Dado al menos un veredicto almacenado, cuando se consulta el último veredicto, entonces se devuelve el más reciente con fecha, comunidad, recuentos, diferencia y resultado.
  - Dadas ejecuciones en los últimos 30 días, cuando se consultan las ejecuciones del último mes, entonces se devuelven con su marca de tiempo y resultado.
  - Dados PDFs conservados, cuando se consultan los PDFs almacenados, entonces se devuelven con fecha, comunidad y ruta identificable.

## Requisitos no funcionales

### NFR-001 Hora de ejecución configurable

- **Requisito:** El proceso diario de integridad deberá ejecutarse a una hora entera del día configurable (0-23); el valor por defecto será las 02:00, tras la pasada esperada del buscador.
- **Criterios de aceptación:**
  - Dada una configuración por defecto, cuando el reloj alcanza las 02:00, entonces se inicia el proceso.
  - Dada una configuración con hora 05:00, cuando el reloj alcanza las 05:00, entonces se inicia el proceso y no a las 02:00.

### NFR-002 Umbrales de tolerancia configurables

- **Requisito:** La tolerancia de recuentos y el umbral de cordura del PDF deberán ser configurables sin modificar código.
- **Criterios de aceptación:**
  - Dada una configuración con tolerancia absoluta de 1 y relativa del 5 %, cuando se comparan recuentos, entonces se aplica la regla más permisiva de ambas.
  - Dada una configuración con umbral de cordura de 70 ofertas, cuando el recuento del PDF es 65, entonces el veredicto es `divergente`.

### NFR-003 Frecuencia máxima diaria

- **Requisito:** El proceso de integridad se ejecutará como máximo una vez por día calendario para cada comunidad.
- **Criterios de aceptación:**
  - Dado que ya se ejecutó correctamente hoy para Cantabria, cuando se dispara de nuevo hoy, entonces no se descarga ni se parsea de nuevo el PDF para Cantabria.

### NFR-004 Zona horaria configurable

- **Requisito:** El sistema deberá usar una zona horaria configurable para determinar el día actual; el valor por defecto será `Europe/Madrid`.
- **Criterios de aceptación:**
  - Dada la configuración por defecto, cuando se determina el día actual, entonces se usa `Europe/Madrid`.
  - Dada una configuración con otra zona horaria válida, cuando se determina el día actual, entonces se usa la zona configurada.

## Supuestos

### SUP-001 Tolerancia en la comparación de recuentos

- **Tipo:** decisional
- **Descripción:** Se compara el recuento de ofertas extraídas del PDF con `total_listado` de la última pasada del buscador. Dado que el 10/11/2026 el PDF arrojó 92 ofertas y el buscador 93, una igualdad estricta provocaría bloqueos permanentes en condiciones normales. **Decisión validada:** aplicar una tolerancia configurable compuesta por (a) diferencia absoluta máxima de 1 oferta y (b) diferencia relativa máxima del 5 %, usando el límite más permisivo; además, el veredicto será siempre `divergente` si el recuento del PDF queda por debajo del umbral de cordura configurable (por defecto 70 ofertas, coherente con la protección de `api-historico`). Alternativas descartadas: igualdad estricta (provocaría veredictos `divergente` en condiciones normales) y tolerancia relativa única sin umbral absoluto (menos explícita para diferencias pequeñas).
- **Impacto:** REQ-003, REQ-004, REQ-006, NFR-002.
- **Estado:** validado

### SUP-002 Alcance del veredicto: informativo, sin integración con `api-historico`

- **Tipo:** decisional
- **Descripción:** `api-integridad` emite y persiste un veredicto diario consultable, pero `api-historico` ya está aprobado y no se modifica. **Decisión validada:** el veredicto es informativo: indica si los recuentos concuerdan y si los cierres están recomendados, pero no impide por sí mismo que `api-historico` marque cierres. Alternativas descartadas: (a) que `api-historico` consulte el veredicto y se abstenga de cerrar (requeriría revisar una feature aprobada) y (b) que `api-integridad` deje el veredicto en un registro compartido que `api-historico` ya lea (hoy no existe tal sitio compartido).
- **Impacto:** REQ-006; el cumplimiento completo de FUN-014 («no se marcan cierres») queda a expensas de una revisión futura de `api-historico`.
- **Estado:** validado

### SUP-003 Ruta y nombre de almacenamiento de PDFs

- **Tipo:** decisional
- **Descripción:** **Decisión validada:** almacenar los PDFs en `data/pdfs/<comunidad>/<aaaa-mm-dd>.pdf` y conservar un fichero de metadatos asociado `data/pdfs/<comunidad>/<aaaa-mm-dd>.meta.json` con hash, recuento y resultado del parseo. La ruta base será configurable, manteniendo el patrón `<comunidad>/<aaaa-mm-dd>.pdf`. Alternativa descartada: almacenar directamente en `data/pdfs/<aaaa-mm-dd>_<comunidad>.pdf` con metadatos en una tabla SQLite propia (más compleja y menos directa para recuperación de PDFs).
- **Impacto:** REQ-001, REQ-002, REQ-009.
- **Estado:** validado

### SUP-004 Fuente principal y comprobación secundaria

- **Tipo:** contextual
- **Descripción:** El buscador HTML es la fuente principal de ofertas y el PDF oficial es solo una comprobación de integridad, conforme a PDEC-013. `api-integridad` no reemplaza al buscador ni modifica su comportamiento.
- **Impacto:** Alcance general; REQ-003.
- **Estado:** validado

### SUP-005 Reutilización del parseo de `api-pdf-parser`

- **Tipo:** contextual
- **Descripción:** `api-integridad` reutilizará el descargador y el parser existentes de `api-pdf-parser` (`source/api/downloader.py`, `source/api/parser.py`, `source/api/assembler.py`) mediante llamada en proceso, sin invocar el endpoint `GET /parse` ni reescribir la lógica de parseo.
- **Impacto:** REQ-001, REQ-003.
- **Estado:** validado

### SUP-006 `api-buscador` no expone la lista de códigos

- **Tipo:** contextual
- **Descripción:** `GET /buscador/status` publica `total_listado` como entero pero no expone la lista de códigos del listado. Por tanto, `api-integridad` solo podrá comparar recuentos, no conjuntos de códigos.
- **Impacto:** REQ-003, REQ-004.
- **Estado:** validado

### SUP-007 Sin notificaciones externas

- **Tipo:** contextual
- **Descripción:** Los avisos de divergencia o fallo serán registros consultables dentro del sistema. No se enviarán mensajes por Telegram, correo ni ningún otro canal externo.
- **Impacto:** REQ-007.
- **Estado:** validado

## Preguntas abiertas

Ninguna.

## Avisos

- El cumplimiento completo de FUN-014 («si el recuento del PDF y el del buscador divergen, no se marcan cierres y se avisa») requiere que algún consumidor actúe sobre el veredicto de integridad. Hoy `api-integridad` solo emite y persiste el veredicto; no modifica `api-historico`, que sigue siendo el único responsable de marcar cierres. Por tanto, el bloqueo efectivo queda a expensas de una revisión futura de `api-historico` o de otro mecanismo que consuma el veredicto.
- El veredicto es informativo y consultable: indica si los cierres están recomendados, pero no los impide directamente.

## Trazabilidad

| Requisito / Supuesto | Funcionalidad de producto | Decisión de producto |
|---|---|---|
| REQ-001 | FUN-014 | PDEC-013 |
| REQ-002 | FUN-014 | Línea 146 de `producto.md` |
| REQ-003 | FUN-014 | PDEC-013 |
| REQ-004 | FUN-014 | PDEC-013, SUP-001 |
| REQ-005 | FUN-014 | PDEC-013 |
| REQ-006 | FUN-014 | PDEC-011, SUP-002 |
| REQ-007 | FUN-014 | PDEC-011 |
| REQ-008 | FUN-014 | PDEC-011 |
| REQ-009 | FUN-014 | PDEC-013 |
| NFR-001 | - | PDEC-015 |
| NFR-002 | - | SUP-001 |
| NFR-003 | - | PDEC-015 |
| NFR-004 | - | Convención de arquitectura |
| SUP-001 | FUN-014 | PDEC-013 |
| SUP-002 | FUN-014 | PDEC-011 |
| SUP-003 | FUN-014 | - |
| SUP-004 | FUN-014 | PDEC-013 |
| SUP-005 | FUN-014 | PDEC-013 |
| SUP-006 | FUN-014 | - |
| SUP-007 | FUN-014 | - |
