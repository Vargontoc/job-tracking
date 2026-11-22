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
