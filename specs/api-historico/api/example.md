# Ejemplos de uso: connection

## Componente: `db-connection-historico` (`source/api/historico/connection.py`)

Conexión única al SQLite propio del histórico (`data/job_emcan_historico.db`). Expone `abrir_conexion(ruta)` que abre o crea el fichero con WAL y `busy_timeout`, y el contexto `transaccion(conexion)` para commits/rollbacks con lock de módulo. Configura `row_factory = sqlite3.Row` para acceso por nombre de columna y `check_same_thread=False` para compartir la conexión entre hilos. No abre ninguna conexión de escritura sobre el SQLite de persistencia ni conexión de red.

## Ejemplo: abrir la conexión del histórico al arrancar

```python
from source.api.historico.connection import abrir_conexion

# Abrir la conexión (crea el directorio data/ y el fichero si faltan).
conexion = abrir_conexion("data/job_emcan_historico.db")
try:
    # Verificar que WAL está activo.
    modo = conexion.execute("PRAGMA journal_mode;").fetchone()[0]
    print(f"Journal mode: {modo}")  # wal

    # busy_timeout configurado a 30000 ms.
    timeout = conexion.execute("PRAGMA busy_timeout;").fetchone()[0]
    print(f"Busy timeout: {timeout} ms")  # 30000
finally:
    conexion.close()
```

## Ejemplo: transacción confirmada

```python
from source.api.historico.connection import abrir_conexion, transaccion

conexion = abrir_conexion("data/job_emcan_historico.db")

# Crear una tabla de ejemplo.
conexion.execute("CREATE TABLE IF NOT EXISTS presencia (codigo TEXT, presente INTEGER);")
conexion.commit()

# Insertar datos dentro de una transacción que se confirma.
with transaccion(conexion) as cx:
    cx.execute("INSERT INTO presencia VALUES ('062026099999', 1);")

# Los cambios persisten fuera del contexto.
fila = conexion.execute(
    "SELECT codigo, presente FROM presencia WHERE codigo = '062026099999';"
).fetchone()
print(f"Código: {fila['codigo']}, Presente: {fila['presente']}")

conexion.close()
```

## Ejemplo: transacción deshecha ante error

```python
from source.api.historico.connection import abrir_conexion, transaccion

conexion = abrir_conexion("data/job_emcan_historico.db")
conexion.execute("CREATE TABLE IF NOT EXISTS presencia (codigo TEXT, presente INTEGER);")
conexion.commit()

# Si el bloque lanza una excepción, la transacción se deshace (ROLLBACK).
try:
    with transaccion(conexion) as cx:
        cx.execute("INSERT INTO presencia VALUES ('062026088888', 1);")
        raise ValueError("Error simulado durante la transacción")
except ValueError:
    pass

# El INSERT no persiste porque se hizo ROLLBACK.
total = conexion.execute("SELECT COUNT(*) FROM presencia WHERE codigo = '062026088888';").fetchone()[0]
print(f"Filas insertadas (debería ser 0): {total}")

conexion.close()
```

## Ejemplo: acceso a columnas por nombre con sqlite3.Row

```python
from source.api.historico.connection import abrir_conexion, transaccion

conexion = abrir_conexion("data/job_emcan_historico.db")

conexion.execute(
    "CREATE TABLE IF NOT EXISTS serie_recuentos "
    "(id INTEGER PRIMARY KEY, recuento_total INTEGER NOT NULL, timestamp TEXT NOT NULL);"
)
conexion.commit()

with transaccion(conexion) as cx:
    cx.execute(
        "INSERT INTO serie_recuentos (recuento_total, timestamp) VALUES (93, '2026-11-22T02:00:00');"
    )

# row_factory = sqlite3.Row permite acceder por nombre de columna.
fila = conexion.execute(
    "SELECT recuento_total, timestamp FROM serie_recuentos ORDER BY id DESC LIMIT 1;"
).fetchone()
print(f"Último recuento: {fila['recuento_total']} en {fila['timestamp']}")

conexion.close()
```

## Componente: `abstenciones-repository` (`source/api/historico/abstenciones_repository.py`)

Repositorio que registra cada abstención de cierre con su motivo, marca de tiempo, recuentos relevantes y códigos afectados. Permite consultarlas ordenadas por timestamp (de más reciente a más antigua), filtrar por motivo y consultar por rango de fechas. Opera sobre la tabla `abstenciones_cierre` del esquema propio del histórico. No escribe en ninguna base de datos de ofertas (SUP-003).

## Ejemplo: registrar una abstención con recuentos y códigos afectados

```python
from source.api.historico.connection import abrir_conexion
from source.api.historico.migrations import migrar
from source.api.historico.abstenciones_repository import RepositorioAbstenciones

conexion = abrir_conexion("data/job_emcan_historico.db")
migrar(conexion)
repo = RepositorioAbstenciones(conexion)

# Registrar una abstención por caída anómala con recuentos y umbral.
id_abstencion = repo.registrar(
    motivo="caida_anomala",
    timestamp="2026-11-22T02:00:00+00:00",
    recuento_anterior=93,
    recuento_actual=50,
    umbral_aplicado="0.5",
    codigos_afectados=["062026099999"],
)
print(f"Abstención registrada con id: {id_abstencion}")

# Consultar las 10 últimas abstenciones.
ultimas = repo.consultar_ultimas(n=10)
for a in ultimas:
    print(f"  {a.timestamp} | {a.motivo} | códigos: {a.codigos_afectados}")

# Filtrar por motivo.
caidas = repo.consultar_por_motivo("caida_anomala")
print(f"Caídas anómalas registradas: {len(caidas)}")

# Consultar por rango de fechas.
rango = repo.consultar_por_rango(
    fecha_inicio="2026-11-01T00:00:00",
    fecha_fin="2026-11-30T23:59:59",
)
print(f"Abstenciones en noviembre: {len(rango)}")

conexion.close()
```

# Ejemplos de uso: ejecucion-repository

## Componente: `ejecucion-repository` (`source/api/historico/ejecucion_repository.py`)

Repositorio que registra la fecha (`YYYY-MM-DD`) de cada ejecución del cierre diario en la tabla `ejecucion_diaria` y permite consultar si ya se ejecutó en un día dado. La inserción es idempotente: registrar la misma fecha dos veces no genera duplicados. No escribe en la base de datos de ofertas.

## Ejemplo: registrar y consultar la ejecución del día

```python
from source.api.historico.connection import abrir_conexion
from source.api.historico.ejecucion_repository import RepositorioEjecucion

conexion = abrir_conexion("data/job_emcan_historico.db")
repo = RepositorioEjecucion(conexion)

# Registrar la ejecución de hoy.
repo.registrar_ejecucion("2026-11-22")

# Comprobar si ya se ejecutó hoy.
print(repo.se_ejecuto_hoy("2026-11-22"))  # True

# Comprobar otro día.
print(repo.se_ejecuto_hoy("2026-11-23"))  # False

# Consultar la última ejecución.
print(repo.obtener_ultima_ejecucion())  # 2026-11-22

conexion.close()
```

# Ejemplos de uso: presencia-repository

## Componente: `historico-presencia-repository` (`source/api/historico/presencia_repository.py`)

Repositorio que persiste la presencia o ausencia de cada código candidato en cada listado oficial, con clave por comunidad, código y fecha del listado; permite consultar las últimas apariciones y ausencias de un código para contar ausencias consecutivas; e incluye la serie histórica de recuentos del listado (registra el recuento total y su marca de tiempo, y devuelve el último recuento). Opera sobre las tablas `presencia_en_listado` y `serie_recuentos` del SQLite propio. No escribe en la base de datos de ofertas (SUP-003).

## Ejemplo: registrar presencia y ausencia y consultar el historial

```python
from source.api.historico.connection import abrir_conexion
from source.api.historico.migrations import migrar
from source.api.historico.presencia_repository import RepositorioPresencia

conexion = abrir_conexion("data/job_emcan_historico.db")
migrar(conexion)
repo = RepositorioPresencia(conexion)

# Registrar presencia de un código en un listado.
repo.registrar_presencia("cantabria", "062026099999", "2026-11-20")

# Registrar ausencia en el listado siguiente.
repo.registrar_ausencia("cantabria", "062026099999", "2026-11-21")

# Consultar el historial del código (de más reciente a más antigua).
historial = repo.consultar_historial("062026099999", comunidad="cantabria")
for fecha, presente in historial:
    print(f"  {fecha} -> {'presente' if presente else 'ausente'}")

# Comprobar ausencias consecutivas.
print(repo.ausencias_consecutivas("062026099999", "cantabria", 2))  # False (solo 1 ausencia)

conexion.close()
```

## Ejemplo: registrar recuentos y obtener el último

```python
from source.api.historico.connection import abrir_conexion
from source.api.historico.migrations import migrar
from source.api.historico.presencia_repository import RepositorioPresencia

conexion = abrir_conexion("data/job_emcan_historico.db")
migrar(conexion)
repo = RepositorioPresencia(conexion)

# Registrar los recuentos de dos pasadas.
repo.registrar_recuento(93, "2026-11-21T02:00:00+00:00")
repo.registrar_recuento(92, "2026-11-22T02:00:00+00:00")

# Obtener el último recuento (el más reciente).
ultimo = repo.obtener_ultimo_recuento()
print(ultimo)  # (92, '2026-11-22T02:00:00+00:00')

# Sobre una serie vacía, devuelve None (ALT-010).
# >>> repo_vacio.obtener_ultimo_recuento() -> None

conexion.close()
```

# Ejemplos de uso: buscador-status-adapter

## Componente: `buscador-status-adapter` (`source/api/historico/buscador_client.py`)

Cliente HTTP que consulta `GET /buscador/status` en la URL base configurada y normaliza la respuesta para los evaluadores del histórico. Devuelve `EstadoBuscador` con el total del listado, la marca de tiempo de la última pasada, la comunidad y los códigos con error por oferta; o `ErrorEstadoBuscador` si hay un error HTTP, de red, si `ultima_pasada` es nula o si `error_global` no está vacío. Nunca lanza excepción. No modifica `api-buscador` ni solicita ningún endpoint distinto de `/buscador/status`.

## Ejemplo: consultar el estado del buscador

```python
import httpx
from source.api.historico.buscador_client import (
    ClienteEstadoBuscador,
    EstadoBuscador,
    ErrorEstadoBuscador,
)

# Crear el cliente con la URL base del buscador.
cliente = ClienteEstadoBuscador(
    "http://localhost:8000",
    cliente_http=httpx.Client(timeout=10.0),
)

# Consultar el estado.
resultado = cliente.consultar_estado()

if isinstance(resultado, EstadoBuscador):
    print(f"Total ofertas: {resultado.total_ofertas}")
    print(f"Timestamp: {resultado.timestamp}")
    print(f"Comunidad: {resultado.comunidad}")
    # Consultar si un código concreto tiene error por oferta.
    if "062026099999" in resultado.errores:
        print("El código 062026099999 tiene error; no se cierra por desaparición")
elif isinstance(resultado, ErrorEstadoBuscador):
    # El evaluador puede abstenerse con el motivo.
    print(f"Estado no utilizable: {resultado.motivo}")
```

# Ejemplos de uso: pdf-listado-adapter

## Componente: `pdf-listado-adapter` (`source/api/historico/pdf_adapter.py`)

Adaptador que obtiene el listado oficial de códigos de oferta del día invocando **en proceso** el downloader y el parser del PDF de difusión (`source/api/downloader.py` y `source/api/parser.py`), sin realizar ninguna llamada HTTP a `GET /parse` ni a ningún otro endpoint. Devuelve `ListadoPDF` con el conjunto de códigos y la fecha del listado, o `ErrorListadoPDF` con el motivo del fallo cuando la descarga no funciona, el parseo no produce ofertas o no se encuentra ningún código.

## Ejemplo: obtener el listado oficial de códigos

```python
from source.api.historico.pdf_adapter import (
    AdaptadorListadoPDF,
    ListadoPDF,
    ErrorListadoPDF,
)

# El constructor recibe la URL del PDF y el identificador de comunidad
# que se pasa al parser para etiquetar las ofertas extraídas.
adaptador = AdaptadorListadoPDF(
    url_pdf="https://example.com/cantabria/difusion.pdf",
    comunidad="Cantabria",
)
resultado = adaptador.obtener_listado()

if isinstance(resultado, ListadoPDF):
    print(f"Fecha del listado: {resultado.fecha_listado}")
    print(f"Códigos encontrados: {len(resultado.codigos)}")
    for codigo in sorted(resultado.codigos):
        print(f"  {codigo}")
elif isinstance(resultado, ErrorListadoPDF):
    print(f"Error: {resultado.motivo}")
    # El evaluador de desaparición debe abstenerse en este caso.
```

# Ejemplos de uso: historico-read-adapter

## Componente: `historico-read-adapter` (`source/api/historico/read_adapter.py`)

Adaptador que abre el SQLite de `api-persistencia` (`data/job_emcan.db`) en modo **solo lectura** (`file:...?mode=ro`) y consulta directamente la tabla `ofertas` para servir las consultas históricas que `persistencia-api` no expone: altas por rango de `fecha_alta`, cierres por rango de `fecha_cierre` y resumen diario de altas y cierres. No crea el fichero si no existe, no escribe y no modifica el esquema. Si el fichero no existe, las consultas devuelven listas vacías sin error.

## Ejemplo: consultar altas por rango de fechas

```python
from source.api.historico.read_adapter import AdaptadorLecturaHistorica

adaptador = AdaptadorLecturaHistorica("data/job_emcan.db")

# Consultar las ofertas dadas de alta entre el 1 y el 15 de noviembre.
altas = adaptador.altas_por_fecha("2026-11-01", "2026-11-15")
for oferta in altas:
    print(f"  {oferta.codigo} | {oferta.ocupacion} | {oferta.municipio} | alta: {oferta.fecha_alta}")
```

## Ejemplo: consultar cierres por rango de fechas

```python
from source.api.historico.read_adapter import AdaptadorLecturaHistorica

adaptador = AdaptadorLecturaHistorica("data/job_emcan.db")

# Consultar las ofertas cerradas entre el 10 y el 20 de noviembre.
cierres = adaptador.cierres_por_fecha("2026-11-10", "2026-11-20")
for oferta in cierres:
    print(f"  {oferta.codigo} | cierre: {oferta.fecha_cierre}")
```

## Ejemplo: resumen diario de altas y cierres

```python
from source.api.historico.read_adapter import AdaptadorLecturaHistorica

adaptador = AdaptadorLecturaHistorica("data/job_emcan.db")

# Resumen de un día concreto.
resumen = adaptador.resumen_diario("2026-11-20")
print(f"Fecha: {resumen.fecha}")
print(f"  Altas: {resumen.altas}")
print(f"  Cierres: {resumen.cierres}")
```

## Ejemplo: fichero inexistente (resultado vacío sin error)

```python
from source.api.historico.read_adapter import AdaptadorLecturaHistorica

# Si el fichero no existe, las consultas devuelven resultados vacíos.
adaptador = AdaptadorLecturaHistorica("data/no_existe.db")
print(adaptador.altas_por_fecha("2026-01-01", "2026-12-31"))  # []
print(adaptador.resumen_diario("2026-11-20"))  # ResumenDiario(fecha='2026-11-20', altas=0, cierres=0)
```

# Ejemplos de uso: persistencia-adapter

## Componente: `persistencia-adapter` (`source/api/historico/persistencia_client.py`)

Cliente HTTP de `persistencia-api` para el histórico. Expone exactamente las tres operaciones que consume `api-historico`: listar ofertas vigentes (`GET /persistencia/ofertas/vigentes`), consultar una oferta por su clave natural `(comunidad, codigo)` (`GET /persistencia/ofertas/{comunidad}/{codigo}`) y cerrar una oferta existente (`POST /persistencia/ofertas` con `estado="cerrada"` y `fecha_cierre`). No crea ofertas nuevas, no lista códigos vistos y no lee por rango de fechas (SUP-003). Los errores HTTP y de red se comunican como `ErrorPersistencia` sin lanzar excepción.

## Ejemplo: listar las ofertas vigentes

```python
from source.api.historico.persistencia_client import (
    ClientePersistencia,
    ErrorPersistencia,
    Oferta,
)

cliente = ClientePersistencia("http://localhost:8000")
resultado = cliente.listar_vigentes()

if isinstance(resultado, ErrorPersistencia):
    print(f"Error al listar vigentes: {resultado.motivo}")
else:
    print(f"Ofertas vigentes: {len(resultado)}")
    for oferta in resultado:
        print(f"  {oferta.codigo} | {oferta.ocupacion} | fin: {oferta.fecha_fin_difusion}")
```

## Ejemplo: consultar una oferta por clave natural

```python
from source.api.historico.persistencia_client import ClientePersistencia

cliente = ClientePersistencia("http://localhost:8000")
resultado = cliente.consultar_por_clave("Cantabria", "062026003633")

if resultado.error is not None:
    print(f"Error: {resultado.error.motivo}")
elif resultado.encontrada:
    oferta = resultado.oferta
    print(f"Estado: {oferta.estado}, alta: {oferta.fecha_alta}")
else:
    print("Oferta no encontrada")
```

## Ejemplo: cerrar una oferta existente

```python
from source.api.historico.persistencia_client import (
    ClientePersistencia,
    ErrorPersistencia,
)

cliente = ClientePersistencia("http://localhost:8000")
resultado = cliente.cerrar_oferta(
    "Cantabria", "062026003633", "2026-11-21T02:00:00+00:00"
)

if isinstance(resultado, ErrorPersistencia):
    print(f"Error al cerrar: {resultado.motivo}")
elif resultado is True:
    print("Oferta cerrada correctamente (o ya estaba cerrada)")
else:  # resultado is False
    print("La oferta no existe")
```

# Ejemplos de uso: cierre-fecha-evaluator

## Componente: `cierre-fecha-evaluator` (`source/api/historico/cierre_fecha.py`)

Evaluador del cierre por fecha de fin de difusión. Recibe las ofertas vigentes, descarta las fechas corruptas o imposibles (ALT-005), compara cada fecha de fin con la fecha actual en la zona horaria configurada (NFR-001) y cierra de forma idempotente, a través de `persistencia-adapter`, solo las que tienen fecha de fin estrictamente anterior a hoy (REQ-003). Las ofertas con fecha de fin vacía se devuelven como candidatas al cierre por desaparición (REQ-004). Las ofertas en estado `sin_ficha` nunca se cierran por fecha (REQ-009). Los errores al cerrar se capturan sin lanzar excepción.

## Ejemplo: evaluar el cierre por fecha de fin de difusión

```python
from source.api.historico.cierre_fecha import EvaluadorCierreFecha
from source.api.historico.persistencia_client import ClientePersistencia, Oferta

# Crear el cliente de persistencia (TASK-009).
cliente = ClientePersistencia("http://localhost:8000")

# Crear el evaluador con la zona horaria configurada.
evaluador = EvaluadorCierreFecha(
    cliente_persistencia=cliente,
    zona_horaria="Europe/Madrid",
)

# Obtener las ofertas vigentes.
vigentes = cliente.listar_vigentes()
if not isinstance(vigentes, list):
    print(f"Error: {vigentes.motivo}")
else:
    # Evaluar el cierre por fecha.
    resultado = evaluador.evaluar(vigentes)

    print(f"Cerradas: {resultado.cerradas}")
    print(f"Errores: {resultado.errores}")
    print(f"Fechas inválidas: {resultado.fechas_invalidas}")
    print(f"Candidatas a desaparición: "
          f"{[o.codigo for o in resultado.candidatas_desaparicion]}")
```

## Ejemplo: usar un reloj inyectable para pruebas

```python
from datetime import date
from source.api.historico.cierre_fecha import (
    EvaluadorCierreFecha,
    RelojFijo,
)
from source.api.historico.persistencia_client import Oferta

# Reloj fijo que simula el 21 de noviembre de 2026.
reloj = RelojFijo(date(2026, 11, 21))

evaluador = EvaluadorCierreFecha(
    cliente_persistencia=cliente_mock,
    zona_horaria="Europe/Madrid",
    reloj=reloj,
)

# Una oferta con fecha de fin del 20/11/2026 (ayer) se cerrará.
oferta = Oferta(
    comunidad="Cantabria",
    codigo="062026003633",
    estado="vigente",
    fecha_fin_difusion="20/11/2026",
)
resultado = evaluador.evaluar([oferta])
print(resultado.cerradas)  # ['062026003633']

# Una oferta con fecha de fin del 21/11/2026 (hoy) permanece vigente.
oferta_hoy = Oferta(
    comunidad="Cantabria",
    codigo="062026004444",
    estado="vigente",
    fecha_fin_difusion="21/11/2026",
)
resultado = evaluador.evaluar([oferta_hoy])
print(resultado.cerradas)  # []
```

## Ejemplo: ofertas sin fecha de fin derivadas al cierre por desaparición

```python
from source.api.historico.cierre_fecha import EvaluadorCierreFecha
from source.api.historico.persistencia_client import Oferta

evaluador = EvaluadorCierreFecha(
    cliente_persistencia=cliente_mock,
    zona_horaria="Europe/Madrid",
)

# Oferta sin fecha_fin_difusion → candidata a desaparición (REQ-004).
oferta_sin_fecha = Oferta(
    comunidad="Cantabria",
    codigo="062026009999",
    estado="vigente",
    fecha_fin_difusion=None,
)
resultado = evaluador.evaluar([oferta_sin_fecha])
print(resultado.cerradas)  # []
print([o.codigo for o in resultado.candidatas_desaparicion])
# ['062026009999']
```

## Ejemplo: fechas inválidas descartadas sin excepción

```python
from source.api.historico.cierre_fecha import EvaluadorCierreFecha
from source.api.historico.persistencia_client import Oferta

evaluador = EvaluadorCierreFecha(
    cliente_persistencia=cliente_mock,
    zona_horaria="Europe/Madrid",
)

# Fecha con formato incorrecto.
oferta1 = Oferta(
    comunidad="Cantabria",
    codigo="062026001111",
    fecha_fin_difusion="2026-11-20",
)
# Fecha imposible (31 de febrero).
oferta2 = Oferta(
    comunidad="Cantabria",
    codigo="062026002222",
    fecha_fin_difusion="31/02/2026",
)
resultado = evaluador.evaluar([oferta1, oferta2])
print(resultado.fechas_invalidas)  # ['062026001111', '062026002222']
print(resultado.errores)  # Mensajes con los códigos y fechas problemáticas.
```

# Ejemplos de uso: recuento-guardian

## Componente: `recuento-guardian` (`source/api/historico/recuento_guardian.py`)

Guardián que valida el recuento del listado antes de permitir cierres por desaparición. Compara el recuento actual con el último registrado en la serie propia: si la caída porcentual supera el umbral configurado o el actual es inferior al recuento mínimo, devuelve «no permitido» y registra la abstención (REQ-008, ALT-002). Sin recuento anterior, registra el actual y aplaza el cierre (ALT-010). No escribe en la base de datos de ofertas (SUP-003).

## Ejemplo: validar un recuento con histórico previo

```python
from source.api.historico.connection import abrir_conexion
from source.api.historico.migrations import migrar
from source.api.historico.presencia_repository import RepositorioPresencia
from source.api.historico.abstenciones_repository import RepositorioAbstenciones
from source.api.historico.recuento_guardian import GuardianRecuento

conexion = abrir_conexion("data/job_emcan_historico.db")
migrar(conexion)

repo_presencia = RepositorioPresencia(conexion)
repo_abstenciones = RepositorioAbstenciones(conexion)

# Simular un recuento previo de 93 ofertas.
repo_presencia.registrar_recuento(93, "2026-11-21T02:00:00+00:00")

# Crear el guardián con los umbrales por defecto (30% caída, 70 mínimo).
guardian = GuardianRecuento(
    repositorio_presencia=repo_presencia,
    abstenciones=repo_abstenciones,
    umbral_caida_pct=30,
    recuento_minimo=70,
)

# Caída pequeña (93 → 92, ~1%): se permite el cierre.
resultado = guardian.validar(92, "2026-11-22T02:00:00+00:00")
print(resultado.permitido)           # True
print(resultado.motivo_abstencion)   # None

# Caída grande (92 → 60, ~35%): abstención por umbral de caída.
resultado = guardian.validar(60, "2026-11-23T02:00:00+00:00")
print(resultado.permitido)           # False
print(resultado.motivo_abstencion)   # 'Caída del 34.8% supera el umbral del 30%'

conexion.close()
```

## Ejemplo: primer recuento sin histórico (ALT-010)

```python
from source.api.historico.recuento_guardian import GuardianRecuento

# Sin recuentos previos en la serie.
guardian = GuardianRecuento(
    repositorio_presencia=repo_presencia,
    abstenciones=repo_abstenciones,
    umbral_caida_pct=30,
    recuento_minimo=70,
)

# Primer recuento: se registra y se aplaza el cierre.
resultado = guardian.validar(93, "2026-11-22T02:00:00+00:00")
print(resultado.permitido)           # False
print(resultado.motivo_abstencion)   # 'Sin recuento anterior: se aplaza ...'
```

## Ejemplo: recuento inferior al mínimo

```python
# Actual 65 con umbral mínimo 70: abstención por mínimo (aunque la caída
# también pueda superar el umbral, la comprobación de mínimo tiene prioridad).
resultado = guardian.validar(65, "2026-11-24T02:00:00+00:00")
print(resultado.permitido)           # False
print("minimo" in resultado.motivo_abstencion.lower())  # True
```

## Ejemplo: consultar las abstenciones registradas

```python
# Tras varias validaciones con abstención, consultar el repositorio.
abstenciones = repo_abstenciones.consultar_ultimas(n=5)
for a in abstenciones:
    print(f"  {a.timestamp} | {a.motivo}")
    print(f"    anterior={a.recuento_anterior}, actual={a.recuento_actual}")
    print(f"    umbral: {a.umbral_aplicado}")
```

# Ejemplos de uso: desaparicion-evaluator

## Componente: `desaparicion-evaluator` (`source/api/historico/desaparicion.py`)

Evaluador de desaparición y ausencias consecutivas. Recibe las ofertas vigentes sin ``fecha_fin_difusion``, el listado oficial del día y los códigos con error por oferta de la última pasada; excluye las ``sin_ficha`` (REQ-009) y las que estén en ``errores_por_oferta`` (REQ-007/ALT-003); registra presencia o ausencia en el repositorio de presencia; cuenta las ausencias consecutivas y cierra de forma idempotente, a través de ``persistencia-adapter``, las que hayan faltado en los últimos N listados consecutivos (por defecto N=2, margen de un día). Los errores se capturan sin lanzar excepción. No escribe en la base de datos de ofertas (SUP-003).

## Ejemplo: evaluar desaparición de ofertas candidatas

```python
from source.api.historico.connection import abrir_conexion
from source.api.historico.migrations import migrar
from source.api.historico.presencia_repository import RepositorioPresencia
from source.api.historico.abstenciones_repository import RepositorioAbstenciones
from source.api.historico.persistencia_client import ClientePersistencia, Oferta
from source.api.historico.desaparicion import EvaluadorDesaparicion

conexion = abrir_conexion("data/job_emcan_historico.db")
migrar(conexion)

repo_presencia = RepositorioPresencia(conexion)
repo_abstenciones = RepositorioAbstenciones(conexion)
cliente = ClientePersistencia("http://localhost:8000")

# Crear el evaluador con N=2 ausencias consecutivas (margen de un día).
evaluador = EvaluadorDesaparicion(
    repositorio_presencia=repo_presencia,
    cliente_persistencia=cliente,
    abstenciones=repo_abstenciones,
    n_ausencias=2,
)

# Ofertas vigentes sin fecha_fin_difusion (candidatas a desaparición).
candidatas = [
    Oferta(comunidad="Cantabria", codigo="062026003633", estado="vigente"),
    Oferta(comunidad="Cantabria", codigo="062026004444", estado="vigente"),
]

# Listado oficial de códigos del día (extraído del PDF de difusión).
listado_oficial = {"062026003633"}  # La 062026004444 no está.

# Códigos con error en la pasada del buscador.
errores_por_oferta: set[str] = set()

resultado = evaluador.evaluar(
    candidatas, listado_oficial, errores_por_oferta, "2026-11-22"
)

print(f"Cerradas: {resultado.cerradas}")
print(f"Errores: {resultado.errores}")
```

## Ejemplo: candidatos con códigos con error (abstención)

```python
# Un código con error en la pasada no se cierra; se registra abstención.
errores = {"062026004444"}

resultado = evaluador.evaluar(
    candidatas, listado_oficial, errores, "2026-11-22"
)

# La oferta 062026004444 no se cierra y queda registrada como abstención.
print(f"Cerradas: {resultado.cerradas}")  # []
abstenciones = repo_abstenciones.consultar_ultimas(n=1)
for a in abstenciones:
    print(f"  {a.motivo} | códigos: {a.codigos_afectados}")
```

## Ejemplo: configurar N=3 ausencias consecutivas

```python
# Con N=3, se requieren tres listados consecutivos sin el código.
evaluador_3 = EvaluadorDesaparicion(
    repositorio_presencia=repo_presencia,
    cliente_persistencia=cliente,
    abstenciones=repo_abstenciones,
    n_ausencias=3,
)

# Tras tres ausencias consecutivas, la oferta se cierra.
resultado = evaluador_3.evaluar(
    candidatas, set(), set(), "2026-11-24"
)
print(f"Cerradas tras 3 ausencias: {resultado.cerradas}")
```

## Ejemplo: presencia/ausencia registrada en el repositorio

```python
# Tras evaluar, el repositorio contiene la marca de presencia/ausencia.
historial = repo_presencia.consultar_historial(
    "062026003633", comunidad="Cantabria"
)
for fecha, presente in historial:
    print(f"  {fecha} -> {'presente' if presente else 'ausente'}")

# Comprobar si hay N ausencias consecutivas.
print(repo_presencia.ausencias_consecutivas(
    "062026004444", "Cantabria", 2
))  # True si falta en 2 listados

# Ejemplos de uso: historico-task

## Componente: `historico-task` (`source/api/historico/task.py`)

Tarea programada diaria que orquesta el cierre de ofertas. Arranca un hilo daemon a la hora configurada (por defecto 02:00) y ejecuta el flujo completo: verificar si ya se ejecutó hoy, consultar el estado del buscador, obtener el listado oficial del PDF, validar el recuento con el guardián, obtener las ofertas vigentes, ejecutar el cierre por fecha y el cierre por desaparición, y registrar la ejecución del día. Un disparo no se solapa consigo mismo. No crea ofertas nuevas ni altera ``fecha_alta`` (REQ-001).

## Ejemplo: crear e iniciar la tarea programada

```python
from source.api.historico.config import cargar_configuracion
from source.api.historico.connection import abrir_conexion
from source.api.historico.migrations import migrar
from source.api.historico.presencia_repository import RepositorioPresencia
from source.api.historico.abstenciones_repository import RepositorioAbstenciones
from source.api.historico.ejecucion_repository import RepositorioEjecucion
from source.api.historico.buscador_client import ClienteEstadoBuscador
from source.api.historico.persistencia_client import ClientePersistencia
from source.api.historico.pdf_adapter import AdaptadorListadoPDF
from source.api.historico.task import TareaHistorico

# Cargar configuración y preparar conexión propia.
config = cargar_configuracion()
conexion = abrir_conexion(config.ruta_sqlite_historico)
migrar(conexion)

# Instanciar repositorios y adaptadores.
repo_presencia = RepositorioPresencia(conexion)
repo_abstenciones = RepositorioAbstenciones(conexion)
repo_ejecucion = RepositorioEjecucion(conexion)
cliente_buscador = ClienteEstadoBuscador(config.url_base_buscador)
cliente_persistencia = ClientePersistencia(config.url_base_persistencia)

# Resolver la URL del PDF a partir del identificador de comunidades.yaml.
from source.api.config import cargar_comunidades
comunidades = cargar_comunidades()
url_pdf = next(
    c.url_pdf for c in comunidades if c.identificador == config.pdf_identificador
)
adaptador_pdf = AdaptadorListadoPDF(
    url_pdf=url_pdf,
    comunidad=config.pdf_comunidad,
)

# Crear la tarea programada.
tarea = TareaHistorico(
    config=config,
    cliente_buscador=cliente_buscador,
    cliente_persistencia=cliente_persistencia,
    repositorio_presencia=repo_presencia,
    repositorio_abstenciones=repo_abstenciones,
    repositorio_ejecucion=repo_ejecucion,
    adaptador_pdf=adaptador_pdf,
)

# Arrancar el planificador (hilo daemon).
tarea.iniciar()
# ... la aplicación sigue corriendo ...
# En el apagado:
tarea.detener()
conexion.close()
```

## Ejemplo: ejecutar el cierre manualmente (por ejemplo, desde un endpoint)

```python
from source.api.historico.task import ResultadoEjecucion

# Ejecutar el cierre manualmente (no espera a la hora programada).
resultado: ResultadoEjecucion = tarea.ejecutar_cierre_diario()

print(f"Fecha: {resultado.fecha}")
print(f"Exitoso: {resultado.exitoso}")
print(f"Cerradas por fecha: {resultado.cerradas_por_fecha}")
print(f"Cerradas por desaparición: {resultado.cerradas_por_desaparicion}")
for error in resultado.errores:
    print(f"  Error: {error}")
for motivo in resultado.abstenciones:
    print(f"  Abstención: {motivo}")
```

## Ejemplo: usar un reloj controlado para pruebas

```python
from datetime import datetime
from source.api.historico.task import TareaHistorico

class RelojDePrueba:
    def __init__(self, ahora: datetime) -> None:
        self._ahora = ahora

    def now(self) -> datetime:
        return self._ahora

    def sleep(self, segundos: float) -> None:
        pass  # No duerme en pruebas.

reloj = RelojDePrueba(datetime(2026, 11, 22, 2, 0, 0))
tarea = TareaHistorico(
    config=config,
    cliente_buscador=cliente_buscador,
    cliente_persistencia=cliente_persistencia,
    repositorio_presencia=repo_presencia,
    repositorio_abstenciones=repo_abstenciones,
    repositorio_ejecucion=repo_ejecucion,
    adaptador_pdf=adaptador_pdf,
    reloj=reloj,
)

# La tarea usa la fecha del reloj para calcular "hoy".
resultado = tarea.ejecutar_cierre_diario()
print(resultado.fecha)  # "2026-11-22"
```

## Ejemplo: segunda ejecución el mismo día (ALT-006)

```python
# Primera ejecución: realiza los cierres y registra la fecha.
resultado1 = tarea.ejecutar_cierre_diario()
print(resultado1.exitoso)  # True

# Segunda ejecución el mismo día: no hace nada.
resultado2 = tarea.ejecutar_cierre_diario()
print(resultado2.exitoso)              # True
print(resultado2.cerradas_por_fecha)   # 0 (no reevalúa)
```
```

# Ejemplos de uso: api-service (integración en el lifespan)

## Componente: `api-service` (`source/api/main.py`)

Integración del histórico en el ciclo de vida de la aplicación FastAPI. El `lifespan` carga la configuración del histórico, abre su conexión SQLite con WAL, aplica las migraciones propias, instancia repositorios, adaptadores y la tarea programada, y arranca el hilo daemon. En el apagado, detiene la tarea antes de cerrar su conexión y antes de detener el scheduler del buscador. Si la configuración o la migración fallan, la app continúa sin el histórico (los endpoints de buscador y persistencia siguen respondiendo). El router de consulta se registra con `app.include_router(historico_router)`.

## Ejemplo: arranque y apagado en el lifespan

```python
# source/api/main.py (fragmento del lifespan)

# Startup: tras el bloque de persistencia
config_historico = cargar_configuracion_historico()
conexion_historico = abrir_conexion_historico(config_historico.ruta_sqlite_historico)
migrar_historico(conexion_historico)

repositorio_presencia = RepositorioPresencia(conexion_historico)
repositorio_abstenciones = RepositorioAbstenciones(conexion_historico)
repositorio_ejecucion = RepositorioEjecucion(conexion_historico)

cliente_estado_buscador = ClienteEstadoBuscador(config_historico.url_base_buscador)
cliente_persistencia_historico = ClientePersistencia(config_historico.url_base_persistencia)
adaptador_lectura = AdaptadorLecturaHistorica(config_historico.ruta_sqlite_persistencia)

# Resolver la URL del PDF a partir de config/comunidades.yaml.
from source.api.config import cargar_comunidades
comunidades_pdf = cargar_comunidades()
url_pdf = next(
    c.url_pdf for c in comunidades_pdf
    if c.identificador == config_historico.pdf_identificador
)
adaptador_pdf = AdaptadorListadoPDF(
    url_pdf=url_pdf,
    comunidad=config_historico.pdf_comunidad,
)

tarea_historico = TareaHistorico(
    config=config_historico,
    cliente_buscador=cliente_estado_buscador,
    cliente_persistencia=cliente_persistencia_historico,
    repositorio_presencia=repositorio_presencia,
    repositorio_abstenciones=repositorio_abstenciones,
    repositorio_ejecucion=repositorio_ejecucion,
    adaptador_pdf=adaptador_pdf,
)
tarea_historico.iniciar()

# app_state guarda todas las referencias
app_state["tarea_historico"] = tarea_historico
app_state["conexion_historico"] = conexion_historico

# Shutdown: antes del scheduler y de cerrar conexión de persistencia
tarea_historico.detener()
conexion_historico.close()
```

# Ejemplos de uso: historico-api

## Componente: `historico-api` (`source/api/historico/routes.py`)

Endpoints de consulta del histórico sobre el SQLite de `api-persistencia` en modo solo lectura. Expone cuatro rutas: `GET /historico/altas`, `GET /historico/cierres`, `GET /historico/cierres-por-fin-difusion` y `GET /historico/resumen`. Los parámetros `desde` y `hasta` son fechas ISO (`YYYY-MM-DD`). No exigen autenticación. Si el histórico no está inicializado, devuelven 503.

## Ejemplo: consultar las altas de un rango de fechas

```python
from fastapi.testclient import TestClient
from source.api.main import app

client = TestClient(app)

resp = client.get(
    "/historico/altas",
    params={"desde": "2026-11-01", "hasta": "2026-11-30"},
)
assert resp.status_code == 200
for oferta in resp.json():
    print(f"  {oferta['codigo']} | {oferta['ocupacion']} | alta: {oferta['fecha_alta']}")
```

## Ejemplo: consultar cierres por fecha de cierre

```python
from fastapi.testclient import TestClient
from source.api.main import app

client = TestClient(app)

resp = client.get(
    "/historico/cierres",
    params={"desde": "2026-11-01", "hasta": "2026-11-30"},
)
for oferta in resp.json():
    print(f"  {oferta['codigo']} | cierre: {oferta['fecha_cierre']}")
```

## Ejemplo: consultar cierres por fecha de fin de difusión

```python
from fastapi.testclient import TestClient
from source.api.main import app

client = TestClient(app)

resp = client.get(
    "/historico/cierres-por-fin-difusion",
    params={"desde": "2026-11-01", "hasta": "2026-11-30"},
)
for oferta in resp.json():
    print(f"  {oferta['codigo']} | cierre: {oferta['fecha_cierre']}")
```

## Ejemplo: consultar el resumen diario

```python
from fastapi.testclient import TestClient
from source.api.main import app

client = TestClient(app)

resp = client.get(
    "/historico/resumen",
    params={"desde": "2026-11-01", "hasta": "2026-11-30"},
)
for dia in resp.json():
    print(f"  {dia['fecha']}: {dia['altas']} altas, {dia['cierres']} cierres")
```

## Ejemplo: validación de parámetros

```python
from fastapi.testclient import TestClient
from source.api.main import app

client = TestClient(app)

# Fecha inválida → 400.
resp = client.get(
    "/historico/altas",
    params={"desde": "no-es-fecha", "hasta": "2026-11-30"},
)
assert resp.status_code == 400

# desde > hasta → 400.
resp = client.get(
    "/historico/altas",
    params={"desde": "2026-12-01", "hasta": "2026-11-01"},
)
assert resp.status_code == 400
```

