# Producto: Rastreador de ofertas del Portal de Empleo de Cantabria

## Visión

- **Para quién:** una persona buscando empleo en Cantabria, que consulta las ofertas del Servicio Público de Empleo por su cuenta.
- **Problema que resuelve:** las ofertas en difusión solo se ofrecen como un PDF de ~30 páginas que se regenera cada día, o como un buscador que hay que repasar a mano; en ambos casos hay que releerlo entero para saber qué es nuevo, qué sigue vivo y a qué se ha presentado uno ya.
- **Propuesta de valor:** convierte el listado diario en una lista propia, filtrable y con memoria: me avisa de lo nuevo que encaja con mi perfil y me lleva el seguimiento de mis candidaturas.
- **Alcance:** una sola comunidad por ahora, Cantabria. Ampliar a otras comunidades es evolución prevista, no parte del primer alcance.
- **Restricciones:**
  - No hay API. La fuente principal es el buscador HTML de Emplea Cantabria (listado + ficha por oferta), y se conserva el PDF oficial de "ofertas en difusión" (`consultarOfertasFrm.do?...&modo=verPDF&filtroCA=06&CA=06`) como comprobación de integridad. Ambos son públicos, sin token ni login.
  - Cortesía con el portal: `robots.txt` permite el buscador y pide `Crawl-delay: 10`. Se traduce en User-Agent identificable, una petición cada 10 s como máximo, una pasada al día y enlace a la ficha original siempre visible.
  - Uso personal y no comercial, en local; no se redistribuye ni se republica el contenido, ni se usa para productos de terceros. Se abandona el rastreo si el Servicio Cántabro de Empleo lo solicita.
  - El aviso legal protege el diseño, el código y las marcas; no concede licencia sobre los contenidos ni prohíbe el acceso automatizado.
  - Volumen actual: ~93 ofertas vigentes. Los campos de contacto pueden contener datos personales: se guardan en local y solo se usan para inscribirse.
  - Algunas fichas no publican fecha de fin de difusión; en esos casos el cierre se sigue deduciendo por desaparición del listado.
  - Se pide la ficha solo de las ofertas nuevas. El contenido completo (texto y contacto) se conserva mientras la oferta siga vigente y una semana más si no la he marcado como interesada; pasado ese plazo solo queda un registro mínimo sin texto ni contacto. Es también minimización de datos.
  - La comunidad y la provincia son parte del dato desde el principio, aunque ahora solo se use una: ampliar no debe obligar a rehacer el histórico. El listado nacional de difusión admite el código de cualquier comunidad (comprobado: `CA=01` devuelve Andalucía).
  - Abrir una comunidad nueva es abrir una fuente nueva: su propio portal, sus propios términos de uso y su propio límite de cortesía. No se hereda el permiso de Cantabria.

## Funcionalidades

| ID | Funcionalidad | Valor | Prioridad | Estado | Notas | Especificacion SDD |
|---|---|---|---|---|---|---|
| FUN-001 | Descarga diaria del buscador de ofertas de Cantabria y de la ficha de cada oferta (nº de oferta, ocupación, municipio, fechas de difusión, sector, nivel, contrato, texto libre, contacto) | Sin esto no hay producto | imprescindible | acordada | Listado paginado (75 por página) siempre; ficha solo de las ofertas de código no visto, más reintento de las que fallaron. El HTML original se guarda solo de las fichas que fallan el parseo y de los últimos 7 días. La ficha no publica sector, nivel ni contrato: se guardan vacíos | |
| FUN-002 | Listado filtrable (texto libre, sector, municipio, oficina, fecha) sobre las ofertas vigentes | Sustituye la lectura del PDF | imprescindible | acordada | Orden por fecha descendente | |
| FUN-003 | Histórico: detectar ofertas nuevas y ofertas cerradas (fecha de fin de difusión, o desaparición del listado si la ficha no la publica) | Evita perder novedades y perseguir ofertas muertas | imprescindible | acordada | Requiere margen ante fallos de descarga para no marcar cierres falsos | |
| FUN-004 | Perfil de interés (palabras clave, sectores, municipios) y aviso por Telegram de las ofertas nuevas que encajan | El aviso solo vale si es relevante | imprescindible | acordada | Digest diario, no aviso por oferta; solo lo que supera el umbral configurable | |
| FUN-005 | Ficha de oferta con el texto completo y los datos de contacto listos para copiar | Agiliza la inscripción | deseable | acordada | | |
| FUN-006 | Seguimiento de candidaturas: estado (me interesa / inscrito / entrevista / descartada), notas y recordatorio opcional por oferta | Cierra el ciclo, no solo descubre | deseable | acordada | Recordatorio configurable. "Me interesa" es el único flag de interés: decide qué fichas se conservan y sobrevive al cierre de la oferta | |
| FUN-007 | Ocultar del listado las ofertas descartadas o ya cerradas | Reduce ruido en el día a día | deseable | acordada | Sustituye al par "favoritas / ocultar": el interés ya lo cubre el estado "me interesa" de FUN-006 | |
| FUN-008 | Exportar el listado a CSV | Compartir o analizar fuera | futuro | idea | | |
| FUN-009 | Estadísticas básicas (ofertas nuevas por semana, sectores con más actividad) | Contexto de mercado | futuro | idea | | |
| FUN-010 | Encaje explicado: puntuación de cada oferta contra un perfil en lenguaje natural, con el motivo en dos líneas | Los filtros por palabras clave fallan con descripciones largas | deseable | acordada | Modelo local vía Ollama, resultado cacheado por oferta y versión de perfil | |
| FUN-011 | Búsqueda semántica sobre el histórico ("¿ha salido algo parecido?") | Aprovechar meses de ofertas ya guardadas | futuro | idea | Solo tiene sentido con histórico amplio. Los embeddings se generan al entrar la oferta y se guardan en SQLite desde el principio (PDEC-019), así que el histórico antiguo sigue siendo buscable aunque su texto ya se haya purgado | |
| FUN-012 | Perfil de búsqueda editable: campos estructurados (sectores, municipios, contrato, jornada) + criterios en lenguaje natural, con historial de versiones | Es el criterio único y estable que alimenta filtros, encaje y avisos | imprescindible | acordada | Cambiar el perfil recalcula encajes de ofertas vigentes y descartadas recientes; el histórico antiguo conserva la versión con la que se puntuó | |
| FUN-013 | Consulta puntual con instrucción libre, sin alterar el perfil ni los avisos | Explorar escenarios ("¿y si busco media jornada en Torrelavega?") | deseable | acordada | Devuelve resultado en pantalla; no genera alertas | |
| FUN-014 | Descarga diaria del PDF oficial de ofertas en difusión como comprobación de integridad y prueba de lo publicado | Detecta que el buscador ha fallado o ha cambiado antes de tocar el histórico | deseable | acordada | Si el recuento del PDF y el del buscador divergen, no se marcan cierres y se avisa. Se conserva el PDF del último mes | `specs/api-pdf-parser` (parcial: descarga y parseo) |
| FUN-015 | Ofertas de otra comunidad, con su propia fuente y su propio límite de cortesía | Buscar fuera de Cantabria sin cambiar de herramienta | futuro | idea | Fuera del primer alcance acordado. El histórico nace con comunidad y provincia, así que ampliar no obliga a rehacerlo | |

## Estado de implementación

`[x]` implementado y verificado; `[ ]` pendiente de especificar e implementar. El orden de la lista es el orden en que tiene sentido atacarlas.

- [x] **api-pdf-parser** — mapa interno comunidad → URL, descarga del PDF de difusión y extracción del listado de ofertas (sector, denominación, municipio, código, fecha, oficina, descripción), devuelto por API sin persistencia. Spec: `specs/api-pdf-parser/`. Cubre la **base de FUN-014** y prepara el parseo; no incluye la comparación de recuentos ni la retención del PDF.
- [x] **api-buscador** — listado paginado (75 por página) y ficha de las ofertas nuevas con reintento de las fallidas; User-Agent identificable y una petición cada 10 s. HTML original solo de las fichas que fallan y de los últimos 7 días. Cubre **FUN-001**.
- [X] **api-persistencia** — esquema SQLite: ofertas con comunidad y provincia, estado, fechas de difusión, texto, contacto, `embedding` (BLOB + modelo y versión) y registro mínimo tras la purga. Cubre la base de **FUN-003**, **FUN-006** y **FUN-011**.
- [X ] **api-historico** — altas y cierres por fecha de fin de difusión, con la desaparición del listado como respaldo; margen ante fallos y sin marcar cierres si la descarga falla. Cubre **FUN-003**.
- [ ] **api-integridad** — descarga diaria del PDF, conservación del último mes, comparación de recuento con el buscador y bloqueo de cierres cuando divergen. Completa **FUN-014**.
- [ ] **api-listado** — listado filtrable por texto libre, sector, municipio, oficina y fecha, con las descartadas y cerradas fuera por defecto. Cubre **FUN-002** y **FUN-007**.
- [ ] **api-perfil** — perfil versionado con campos estructurados y criterios en lenguaje natural; varias provincias en el modelo. Cubre **FUN-012**.
- [ ] **api-encaje** — puntuación contra el perfil con Ollama, motivo en dos líneas, resultado cacheado por oferta y versión de perfil, recálculo al cambiar el perfil, y generación del embedding al entrar la oferta. Cubre **FUN-010** y deja listo el índice de **FUN-011**.
- [ ] **api-digest** — digest diario por Telegram a las 09:00, configurable, solo con las ofertas que superan el umbral (7/10 por defecto). Cubre **FUN-004**.
- [ ] **api-candidaturas** — estados (me interesa / inscrito / entrevista / descartada), notas, recordatorio opcional y purga según PDEC-016. Cubre **FUN-005** y **FUN-006**.
- [ ] **api-consulta-puntual** — instrucción libre que no altera perfil ni avisos. Cubre **FUN-013**.
- [ ] **app-interfaz** — listado, ficha con texto y contacto copiable, perfil, seguimiento y configuración (hora del digest, umbral, recordatorios); envoltura con pywebview al final. Cubre **FUN-002**, **FUN-005**, **FUN-006**, **FUN-007**, **FUN-012** y **PDEC-012**.

Sin especificación y fuera del primer alcance (siguen como `idea`): **FUN-008** (CSV), **FUN-009** (estadísticas), **FUN-011** (búsqueda semántica) y **FUN-015** (otras comunidades).

## Opciones de tecnología

### Fuente de datos

| Opción | Ventajas | Costes y riesgos | Fuente y fecha |
|---|---|---|---|
| Buscador HTML de Emplea Cantabria: listado paginado (75 por página) + ficha por oferta | Campos ya estructurados (ocupación, municipio, fechas, contacto); aporta la fecha de fin de difusión, que el PDF no da; el sitio la ofrece en abierto y su `robots.txt` la permite | Portal Liferay con parámetros de portlet largos y cambiantes; ~95 peticiones al día, ~16 min con la cortesía de 10 s | Comprobación propia sobre el portal, 10/11/2026: 93 ofertas, ficha con texto libre, contacto y fin de difusión |
| PDF oficial de ofertas en difusión (SEPE) | Una sola petición; documento cerrado y estable como prueba de lo publicado cada día; el código de comunidad es un parámetro (probado `CA=01` → Andalucía), así que el mismo documento sirve para cualquier comunidad | Texto plano que hay que parsear por anclas; frágil ante cambios de formato; sin fecha de fin de difusión | Prueba sobre el PDF del 10/11/2026: 92 ofertas, 15 sectores; comprobación de `CA=01`, 10/11/2026 |
| Ambas: buscador como fuente principal, PDF como comprobación de integridad | Dato estructurado y verificado por dos vías; detecta fallos o cambios de formato antes de tocar el histórico | Hay que mantener dos extractores | Evaluación propia, 10/11/2026 |
| Terceros (agregadores, EURES) | Menos mantenimiento | Cobertura parcial y datos de segunda mano; no garantiza que la oferta siga vigente | Evaluación propia, 10/11/2026 |

**Recomendación:** buscador HTML como fuente principal y PDF como comprobación de integridad. Si los recuentos divergen o el buscador devuelve muy poco, no se actualiza el histórico y se avisa.

### Interfaz

| Opción | Ventajas | Costes y riesgos | Fuente y fecha |
|---|---|---|---|
| App web local (Python + FastAPI + plantillas, SQLite), se abre en el navegador | Reutiliza el parseo en Python; iteración muy rápida; sin instalación ni empaquetado | Hay que arrancar el servidor; no es "una ventana" de escritorio | Evaluación propia, 10/11/2026 |
| Ventana nativa envolviendo la misma UI web (pywebview) | Apariencia de app de escritorio con el mismo código; un acceso directo y listo | Una capa más que mantener; detalles de empaquetado | Evaluación propia, 10/11/2026 |
| Escritorio con Tauri o Electron | Empaquetado profesional, multiplataforma | Mucho más peso y trabajo para una app personal | Evaluación propia, 10/11/2026 |
| Solo CLI + avisos Telegram | Lo más barato de construir | Sin listado ni seguimiento de candidaturas, que es lo que se ha pedido | Evaluación propia, 10/11/2026 |

**Recomendación:** app web local en Python + SQLite, y envolverla con pywebview cuando el flujo esté validado, para tener ventana propia y doble clic. **Decidido (PDEC-018).**

### Extracción del PDF

| Opción | Ventajas | Costes y riesgos | Fuente y fecha |
|---|---|---|---|
| Librería de PDF + reglas sobre el texto (anclas "Oferta:", "Oficina:", "Sector Profesional:") | Determinista, gratis, auditable; el PDF actual se extrae limpio | Frágil si el portal cambia el formato; hay que detectar y avisar cuando el parseo devuelve poco | Prueba sobre el PDF del 10/11/2026: 92 ofertas, 15 sectores |
| Extracción con modelo de lenguaje | Tolera cambios de formato | Resultados no deterministas; puede inventar campos plausibles; más lento | Evaluación propia, 10/11/2026 |
| Reglas como vía principal + modelo local como respaldo cuando la validación de cordura falla | Mantiene el dato fiable el 99% de los días y cubre el día en que el portal cambie el formato | El respaldo hay que validarlo igual (formato del nº de oferta, recuento, duplicados); no sustituye a las reglas | Evaluación propia, 10/11/2026 |

**Recomendación:** reglas + validación de cordura (si el número de ofertas cae bruscamente, no actualizar el histórico y avisar). Si la validación falla, intento de respaldo con el modelo local, y el resultado entra solo si pasa las mismas comprobaciones. Guardar el PDF original de cada día.

### Modelo local (Ollama) y búsqueda semántica

| Opción | Ventajas | Costes y riesgos | Fuente y fecha |
|---|---|---|---|
| Reglas para extraer + modelo local solo para puntuar encaje (sin RAG) | Datos de entrada deterministas; el modelo aporta donde brillan los LLM; todo queda en local | Segunda pieza que mantener; latencia si no hay GPU; resultados no idénticos entre ejecuciones | Evaluación propia, 10/11/2026 |
| RAG sobre las ofertas vigentes (embeddings + base vectorial) | Permite preguntas en lenguaje natural | El corpus (92 ofertas, ~40-60k caracteres) cabe entero en contexto: la recuperación no aporta y añade fallos | Evaluación propia, 10/11/2026 |
| RAG sobre el histórico acumulado | Responde "¿ha salido algo parecido?" cuando haya miles de ofertas | Necesita meses de datos antes de ser útil; índice vectorial que mantener | Evaluación propia, 10/11/2026 |
| Agente que decide pasos (descargar, consultar, avisar) | Flexibilidad aparente | Bucle no determinista para un proceso que ya es fijo y diario; más formas de fallar | Evaluación propia, 10/11/2026 |

**Recomendación:** núcleo determinista (descarga → parseo por reglas → SQLite → comparación → Telegram) y un modelo local opcional encima para puntuar encaje. RAG se valora en fase 2, sobre el histórico. El agente se descarta.

**Sustituto de pgvector (decidido, PDEC-019):** los embeddings se guardan como BLOB en la propia SQLite (con nombre y versión del modelo) y la similitud se calcula por fuerza bruta con numpy. Sin segunda base de datos ni extensión que cargar; con cientos de miles de vectores la latencia sigue siendo de milisegundos y, si algún día molesta, se migra a `sqlite-vec` reutilizando los vectores ya guardados. `sqlite-vss` está en desuso; ChromaDB y LanceDB añaden una segunda base de datos al lado de SQLite; FAISS obliga a mantener un índice aparte; Qdrant es un servicio que no compensa en uso personal.

Con una RTX 4070 Super (12 GB) se puede usar un modelo de 8B–14B cuantizado y puntuar las ~92 ofertas en pocos minutos, sin prefiltro. Si algún día el volumen se multiplica, el orden a seguir es prefiltro barato por sector/municipio antes que modelo más pequeño.

### Alertas

| Opción | Ventajas | Costes y riesgos | Fuente y fecha |
|---|---|---|---|
| Bot de Telegram | Gratis, llega al móvil, fácil de configurar | Requiere crear bot y guardar el chat_id | Evaluación propia, 10/11/2026 |
| Correo por SMTP | Sin dependencia de Telegram | Credenciales de correo, más propenso a acabar en spam | Evaluación propia, 10/11/2026 |

**Recomendación:** Telegram.

## Decisiones

| ID | Decisión | Motivo | Alternativas descartadas |
|---|---|---|---|
| PDEC-001 | ~~La fuente de datos es el PDF oficial de difusión de Cantabria~~ **Sustituida por PDEC-013** | No había API ni listado HTML conocido cuando se decidió | Scraping del buscador del SEPE; fuentes de terceros |
| PDEC-002 | ~~El cierre de una oferta se deduce por su desaparición del listado, con margen de un día~~ **Sustituida por PDEC-014** | El portal no publicaba estado de cierre | No llevar histórico |
| PDEC-003 | Almacenamiento local en SQLite | Volumen pequeño, uso personal, cero infraestructura | Servidor con base de datos; ficheros JSON |
| PDEC-004 | Aviso por Telegram en un único digest diario | Evita ruido; el listado cambia una vez al día | Aviso inmediato por oferta; correo |
| PDEC-005 | Todo el uso es personal y local | Simplicidad y datos personales en casa | App desplegada en internet |
| PDEC-006 | La extracción de datos es determinista por reglas; el modelo local solo puntúa encaje y, como respaldo, intenta extraer cuando la validación de cordura falla | Un LLM puede inventar campos plausibles; el dato de base debe ser fiable, pero conviene un paracaídas ante cambios de formato | LLM como extractor principal |
| PDEC-007 | RAG se pospone al histórico (fase 2), no sobre las ofertas vigentes | El corpus actual cabe en contexto; la recuperación no aporta valor aún | RAG desde el día uno |
| PDEC-008 | El criterio de encaje vive en un perfil versionado, no en un prompt escrito cada día; el prompt libre es parte del perfil, y las consultas puntuales no lo modifican | Sin criterio estable los encajes no son comparables entre días y el aviso se vuelve ruido; el texto libre captura matices que los campos no | Prompt libre por ejecución; solo campos estructurados |
| PDEC-009 | Al cambiar el perfil se recalculan las ofertas vigentes y las descartadas recientes; el histórico antiguo conserva la versión con la que se puntuó | Mantiene comparabilidad sin reescribir meses de datos | Recalcular todo el histórico en cada cambio; no recalcular nada |
| PDEC-010 | El digest diario incluye solo las ofertas que superan el umbral de encaje, ajustable por el usuario | Menos ruido; el umbral se afina con el uso | Incluir también las de encaje medio en bloques separados |
| PDEC-011 | Si el portal no responde o la descarga falla, se avisa al usuario y no se marca ninguna oferta como cerrada | Un fallo de red no debe convertirse en 92 ofertas "cerradas" | Reintentar en silencio; marcar cierres igualmente |
| PDEC-012 | Hora del digest, umbral de encaje y recordatorios son configurables. Valores por defecto: digest a las 09:00 y umbral de encaje 7/10, revisable tras la primera semana de uso real | Son preferencias personales, no decisiones de producto cerradas | Dejar valores fijos |
| PDEC-013 | La fuente principal es el buscador HTML de Emplea Cantabria (listado + ficha); el PDF se descarga solo como comprobación de integridad | Da campos estructurados y la fecha de fin de difusión, que el PDF no tiene; el PDF obliga a un parseo frágil | PDF como única fuente (PDEC-001, sustituida); agregadores de terceros |
| PDEC-014 | El cierre se toma de la fecha de fin de difusión de la ficha; la desaparición del listado queda como señal de respaldo cuando la ficha no la publica | Deja de ser una deducción con margen y pasa a ser un dato de la fuente | Seguir deduciendo el cierre por desaparición (PDEC-002, sustituida) |
| PDEC-015 | Política de rastreo: User-Agent identificable, máximo una petición cada 10 s, una pasada al día, sin redistribución y con enlace a la ficha original siempre visible | Es lo que pide el `robots.txt` (`Crawl-delay: 10`) y lo coherente con el uso personal; el aviso legal no lo prohíbe ni lo autoriza | Rastreo sin límite de frecuencia; publicar el agregado |
| PDEC-016 | La ficha se pide solo de las ofertas nuevas; el texto y el contacto se conservan mientras la oferta esté vigente y una semana más si no está marcada como interesada, y después se reduce a un registro mínimo (código, ocupación, municipio, sector, fechas). Una oferta marcada como interesada y luego descartada sigue el mismo ciclo de purga | Sin pedir 93 fichas al día el rastreo baja de ~16 min a ~2-3 min y sigue cubriendo lo que importa: lo nuevo. El registro mínimo mantiene histórico, estadísticas y deduplicación sin guardar texto ni contactos que ya no sirven | Pedir todas las fichas cada día; borrar la oferta por completo a la semana (se pierde el histórico); guardar todo indefinidamente; conservar las descartadas que estuvieron interesadas |
| PDEC-017 | El primer alcance es Cantabria. Comunidad y provincia se guardan como parte del dato desde el inicio y el perfil admite varias provincias en el modelo, aunque la interfaz solo use una. Cada comunidad nueva entra como fuente nueva, con su propia revisión de términos y su propia cortesía. La siguiente comunidad no se elige hasta comprobar que el sistema funciona bien con Cantabria | Ampliar después sin rehacer el histórico ni los perfiles; y no dar por heredado un permiso que solo se comprobó para Cantabria | Diseñar para toda España desde el día uno; dejar la comunidad como valor fijo en el código |
| PDEC-018 | Stack: Python + FastAPI con plantillas y SQLite; pywebview para la ventana de escritorio cuando el flujo esté validado; Ollama local para el encaje; Telegram para los avisos. Se descarta Java/JavaFX con PostgreSQL | El trabajo pesado es descargar y parsear, donde Python ahorra la mayor parte del esfuerzo; SQLite no necesita administración y sobra para uso personal; PostgreSQL se justificaba por pgvector, que ya no se usa | Java 21 + JavaFX 21 + PostgreSQL 16 con pgvector; híbrido Python + JavaFX |
| PDEC-019 | Los embeddings viven en SQLite como BLOB (con nombre y versión del modelo) y la similitud se calcula por fuerza bruta con numpy; se generan al entrar la oferta y **se conservan en el registro mínimo** cuando el texto se purga. Sustituyen a pgvector | Sin segunda base de datos ni extensión; el vector pesa ~3 KB y no contiene texto ni contacto, así que respeta la minimización y mantiene FUN-011 útil sobre meses de histórico | pgvector; sqlite-vec desde el día uno; FAISS; ChromaDB; LanceDB; Qdrant; no guardar el vector tras la purga |

## Preguntas abiertas

- [X] Umbral inicial de encaje propuesto: 7/10. Se revisa tras la primera semana de uso real.
- [X] Hora por defecto del digest: propongo 09:00, configurable desde la interfaz.
- [X] ¿Ficha de todas las ofertas cada día o solo de las nuevas? Solo las nuevas, con reintento de las que fallen (PDEC-016).
- [X] ¿Se conserva el PDF original de cada día, o basta con el recuento y el hash para la comprobación de integridad? El PDF ocupa poco, pero se acumula; propongo conservar el del último mes.
  - RESPUESTA: conservar solo el último mes.
- [X] ¿Qué comunidad sería la siguiente, y con qué prioridad? Criterio propuesto: donde de verdad haya intención de buscar, no "cuantas más mejor".
  - RESPUESTA:En esta version solo Cantabria hasta confirmar funcionamiento correcto del sistema.

- [X] ¿El perfil debe admitir varias provincias desde la primera versión, aunque solo haya Cantabria? Propongo que el modelo sí y la interfaz lo oculte, para no migrar datos al ampliar.
  - RESPUESTA: sí, aunque solo se use Cantabria por ahora.

- [x] ¿Una oferta marcada como interesada y luego descartada vuelve al ciclo de purga a la semana, o se conserva por si se recupera? Propongo purgarla igual.
  RESPUESTA: purgar igual.