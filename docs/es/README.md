[EN](https://github.com/madgagarin/holarchy/blob/main/README.md) | **ES** | [RU](https://github.com/madgagarin/holarchy/blob/main/docs/ru/README.md)

# Holarchy Orchestrator

[![Licencia: MPL 2.0](https://img.shields.io/badge/License-MPL%202.0-brightgreen.svg)](https://opensource.org/licenses/MPL-2.0)
[![Versión de PyPI](https://img.shields.io/pypi/v/holarchy.svg)](https://pypi.org/project/holarchy/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/release/python-3110/)

**Holarchy** es un orquestador de alto rendimiento basado en máquinas de estados, diseñado para gestionar flujos de trabajo de IA de larga duración y tareas distribuidas. Actúa como el núcleo de una **Red Lógica Holárquica (HLN)**, coordinando **Holones** (workers) a través del protocolo **RXON**.

## 🚀 Características Principales

- **FSM moderno fuertemente tipado**: Decoradores declarativos `@bp.start`, `@bp.step`, `@bp.decide`, `@bp.end`, clases `StatesGroup`, `State` y modelos nativos `@dataclass` / `msgspec.Struct` (con soporte transparente para Pydantic vía duck-typing).
- **5 Zonas limpias de almacenamiento**: Separación estricta de dominios entre `input`, `steps`, `history`, `meta` y `output`.
- **Enrutamiento consultivo de IA y Replay determinista**: Principio Host-Owned Choice, fallback seguro, comprobantes `ExecutionReceipt` y CLI de evaluación de deriva offline (`holarchy replay evaluate`).
- **Autogeneración de OpenAPI 3.1 y documentación interactiva**: Especificación en `/openapi.json` e interfaz UI de pruebas en `/docs`.
- **Caché en memoria de 4 niveles y memoización**: Entrega sub-milisegundo con caché seguro para hilos LRU/FIFO de esquemas en `rxon`, caché de topología espacial DAG en `Blueprint`, y bytes pre-serializados de OpenAPI 3.1 JSON y HTML de documentación en `OrchestratorEngine` con invalidación automática basada en revisiones.
- **Tarjetas de evidencia de incidentes (Zero-Trust Evidence Cards)**: Diagnóstico post-mortem instantáneo en `GET /jobs/{id}/evidence?format=md` con clasificación de causas raíz.
- **Alto Rendimiento**: Indexación de colas vía **ZSET**, mecanismo de **Work Stealing** (robo de tareas) en Lua y transiciones de estado atómicas.
- **Seguridad Zero Trust y Capa de Políticas**: Implementación completa de `SecurityContext`, firma criptográfica de tareas HMAC-SHA256 (`sig`) mediante `ORCHESTRATOR_SECRET_KEY`, verificación de cadenas de identidad (Identity Chains) y políticas granulares para habilidades (`allowed_skills`).
- **Aprobación Scoped Human-in-the-Loop**: Tokens de confirmación seguros de un solo uso (`approval_token`) para webhooks externos (Email, Slack, Telegram) sin exponer tokens maestros de clientes.
- **Atomicidad CAS y Seguridad de Watcher**: Transiciones atómicas basadas en CAS (`update_job_state_atomic`) que protegen contra condiciones de carrera y evitan la sobreescritura de estados terminales por tiempos de espera.
- **Validación Estricta de Configuración en Producción**: Control de inicio seguro (`ENVIRONMENT=production`) que bloquea la ejecución si se detectan tokens predeterminados inseguros o claves secretas faltantes.
- **Protección de Profundidad de Holarquía**: Límite configurable (`MAX_HOLARCHY_DEPTH`) para prevenir la recursión infinita en sub-blueprints con cuarentena automática.
- **Infraestructura de Middleware**: `MiddlewareChain` flexible para interceptar solicitudes, respuestas, resultados de воркеров y tareas salientes.
- **Criptoauditoría D-DNA**: Herramientas CLI de verificación (`holarchy.cli.audit`) que garantizan la integridad de la cadena de historial de eventos.
- **Protección de Datos**: **Envelope Encryption** (cifrado de sobres) para tokens en Redis, aislamiento estricto de clientes y protección contra reenvío (Replay Protection).
- **Gestión de Archivos**: Streaming Async S3 de alto rendimiento mediante la librería `obstore`.
- **Observabilidad**: Seguimiento distribuido **Orquestador ↔ Worker** con **OpenTelemetry**, topología espacial DAG (`/dag`) y métricas en tiempo real.

Este documento sirve como una guía completa para desarrolladores que buscan construir pipelines (blueprints) e integrar el Orquestador en sus aplicaciones.

## Tabla de Contenidos

- [Arquitectura Central: Orquestador, Blueprints y Workers](#arquitectura-central-orquestador-blueprints-y-workers)
- [Instalación](#instalación)
- [Inicio Rápido: Uso como Librería](#inicio-rápido-uso-como-librería)
- [Conceptos Clave: JobContext y Actions](#conceptos-clave-jobcontext-and-actions)
- [Recetario de Blueprints: Características Clave](#recetario-de-blueprints-características-clave)
  - [Transiciones Condicionales](#transiciones-condicionales)
  - [Delegar Tareas a Workers (dispatch_task)](#delegar-tareas-a-workers-dispatch_task)
  - [Ejecución Paralela y Agregación (Fan-out/Fan-in)](#ejecución-paralela-y-agregación-fan-outfan-in)
  - [Inyección de Dependencias (DataStore)](#inyección-de-dependencias-datastore)
  - [Programador Nativo (Scheduler)](#programador-nativo-scheduler)
  - [Descarga de Carga Útil en S3 (S3 Payload Offloading)](#descarga-de-carga-útil-en-s3-s3-payload-offloading)
  - [Notificaciones Webhook](#notificaciones-webhook)
- [Configuración de Producción](#configuración-de-producción)
  - [Tolerancia a Fallos](#tolerancia-a-fallos)
  - [Backend de Almacenamiento](#backend-de-almacenamiento)
  - [Observabilidad](#observability)
- [Guía para Contribuidores](#guía-para-contribuidores)
  - [Configuración del Entorno](#configuración-del-entorno)
  - [Ejecución de Pruebas](#ejecución-de-pruebas)

## Arquitectura Central: Orquestador, Blueprints y Workers

Holarchy desacopla la lógica de orquestación de flujos del procesamiento computacional distribuido a través de tres componentes principales:

- **Orquestador (`OrchestratorEngine`)**: Coordinador central que mantiene el estado persistente de los trabajos, resuelve decisiones de enrutamiento, valida esquemas de datos, gestiona reintentos y despacha tareas mediante flujos de Redis.
- **Blueprints (`Blueprint`)**: Máquinas de estados declarativas que definen grafos de ejecución, políticas de transición, estrategias de agregación de datos y rutinas de manejo para flujos comerciales.
- **Workers (`Worker`)**: Nodos de ejecución autónomos conectados al orquestador mediante sondeo inverso por HTTP. Los workers registran habilidades y capacidades de hardware admitidas, extraen tareas asignadas, ejecutan lógica computacional en directorios aislados y reportan resultados.

Bajo la arquitectura HLN (Holarchical Logic Network), los orquestadores administran el ciclo de vida del estado, mientras que los workers proporcionan capas estandarizadas de ejecución. Mediante composición recursiva, una instancia de orquestador puede ejecutarse dentro de un worker, facilitando clústeres jerárquicos multinivel.

## Ecosistema

Holarchy es parte de un ecosistema más grande:

- **[Protocolo RXON](https://github.com/madgagarin/rxon)**: Paquete compartido de conexión inversa ligera que potencia la comunicación entre nodos en el ecosistema HLN.
- **[SDK de Worker de Holarchy](https://github.com/madgagarin/holonode)**: El SDK oficial de Python para construir workers que se conectan a este motor.
- **[HLN (Holarchical Logic Network)](https://github.com/madgagarin/hln)**: El patrón arquitectónico, manifiesto y especificación de diseño para holarquías autosimilares.
- **[Ejemplo Completo](https://github.com/madgagarin/holarchy-full-example)**: Un proyecto de referencia completo que demuestra el motor y los workers en acción.

## Instalación

- **Instalar solo el núcleo del motor:**

  ```bash
  pip install holarchy
  ```

- **Instalar con soporte para Redis (recomendado para producción):**

  ```bash
  pip install "holarchy[redis]"
  ```

- **Instalar con soporte para almacenamiento de historial (SQLite, PostgreSQL):**

  ```bash
  pip install "holarchy[history]"
  ```

- **Instalar con soporte de telemetría (OpenTelemetry):**

  ```bash
  pip install "holarchy[telemetry]"
  ```

- **Instalar con soporte para S3 (Descarga de Carga Útil):**

  ```bash
  pip install "holarchy[s3]"
  ```

- **Instalar todas las dependencias, incluidas las pruebas:**
  ```bash
  pip install "holarchy[all,test]"
  ```

## Estados del Trabajo (Job Statuses)

Los trabajos en Holarchy pasan por varios estados:

| Estado                 | Tipo         | Descripción                                                |
| :--------------------- | :----------- | :--------------------------------------------------------- |
| `pending`              | Intermedio   | Trabajo creado, esperando a ser encolado.                  |
| `running`              | Intermedio   | Ejecución activa de la lógica o tareas.                    |
| `waiting_for_worker`   | Intermedio   | Tarea enviada, esperando que un worker la recoja.          |
| `waiting_for_human`    | Intermedio   | Pausado, esperando aprobación manual vía webhook.          |
| `waiting_for_parallel` | Intermedio   | Esperando que se completen las subtareas paralelas.        |
| `finished`             | **Terminal** | Completado con éxito. **El resultado es visible.**         |
| `failed`               | **Terminal** | Fallo de lógica o del worker. **El resultado es visible.** |
| `cancelled`            | **Terminal** | Cancelado manualmente por el usuario o el sistema.         |
| `error`                | **Terminal** | Error crítico del sistema o de infraestructura.            |
| `quarantined`          | **Terminal** | Marcado para revisión manual (ej. violación de contrato).  |

### Observabilidad Moderna

Holarchy está construida con una observabilidad profunda en mente utilizando el estándar **OpenTelemetry**. Proporciona:

- **Rastreo Distribuido**: Siga las solicitudes a través de toda la red HLN (Orquestador ↔ Worker).
- **Métricas en Tiempo Real**: Monitoree la longitud de las colas, la salud de los workers y las latencias de los trabajos.
- **OTLP Nativo**: Envíe datos de telemetría directamente a Jaeger, Prometheus o Grafana.

Para habilitar el soporte de telemetría durante la instalación:

```bash
pip install "holarchy[telemetry]"
```

Consulte la [**Guía de Observabilidad**](https://github.com/madgagarin/holarchy/blob/main/docs/es/observability.md) para detalles de configuración.

## Inicio Rápido: Uso como Librería

Puedes integrar y ejecutar fácilmente el motor del orquestador dentro de tu propia aplicación.

```python
# mi_app.py
from asyncio import Event, run
from dataclasses import dataclass

from holarchy import Blueprint, OrchestratorEngine
from holarchy.config import Config
from holarchy.context import ActionFactory
from holarchy.fsm import State, StatesGroup
from holarchy.storage import MemoryStorage


@dataclass
class OrderInput:
    order_id: int
    amount: float


class OrderFlow(StatesGroup):
    start = State()
    finalize = State()


storage = MemoryStorage()
config = Config()
config.CLIENT_TOKEN = "my-secret-client-token"
config.GLOBAL_WORKER_TOKEN = "my-secret-worker-token"

bp = Blueprint(name="order_pipeline", api_version="v1", api_endpoint="/jobs/order")


@bp.start(OrderFlow.start)
async def process_start(data: OrderInput, actions: ActionFactory) -> State:
    """El estado inicial para cada nuevo trabajo."""
    print(f"Pedido #{data.order_id} recibido, importe: {data.amount}")
    return OrderFlow.finalize


@bp.end(OrderFlow.finalize)
async def process_finalize(context) -> dict[str, str]:
    """El estado final. El pipeline termina aquí."""
    print(f"Trabajo {context.job_id} | Completo.")
    return {"status": "completed"}


engine = OrchestratorEngine(storage, config)
engine.register_blueprint(bp)


async def main() -> None:
    await engine.start()
    try:
        await Event().wait()
    finally:
        await engine.stop()


if __name__ == "__main__":
    try:
        run(main())
    except KeyboardInterrupt:
        print("\nDeteniendo servidor.")
```

### Ciclo de Vida del Motor: `run()` vs. `start()`

El `OrchestratorEngine` ofrece dos formas de iniciar el servidor:

- **`engine.run()`**: Este es un método simple y **bloqueante**. Se encarga de iniciar y detener el servidor por ti. No debes usar esto dentro de una función `async def` que sea parte de una aplicación más grande.

- **`await engine.start()`** y **`await engine.stop()`**: Estos son los métodos no bloqueantes para integrar el motor en una aplicación `asyncio` más grande.
  - `start()` configura e inicia el servidor web en segundo plano.
  - `stop()` apaga el servidor con elegancia y limpia los recursos.

## Handler Arguments e Inyección de Dependencias

State handlers son el núcleo de la lógica de tu flujo de trabajo. Holarchy proporciona un potente sistema de inyección de dependencias.

> **Consejo:** En v1.0.0, utiliza los decoradores declarativos `@bp.start(State)`, `@bp.step(State, condition=...)` y `@bp.end(State)`. El decorador `@bp.handler(state_name)` se mantiene para compatibilidad con versiones anteriores.

Los siguientes argumentos se pueden inyectar por nombre:

- **Desde el contexto principal del trabajo:**
  - `job_id` (str): El ID del trabajo actual.
  - `input` (dict): Los datos de entrada iniciales.
  - `steps` (dict): Diccionario de resultados entre pasos.
  - `history` (list): Eventos cronológicos de auditoría.
  - `actions` (ActionFactory): Control de flujo del orquestador.
  - `client` (ClientConfig): Información del cliente API.
  - `data_stores` (SimpleNamespace): Acceso a recursos compartidos.
- **Desde los resultados del worker:**
  - Cualquier clave de un diccionario devuelto por un worker anterior se puede inyectar por nombre.

### Ejemplo: Inyección de Dependencias

```python
@bp.step
async def publish_video(
    job_id: str,
    output_path: str,  # Inyectado desde steps
    duration: int,  # Inyectado desde steps
    actions: ActionFactory,
):
    print(f"Job {job_id}: Publicando video en {output_path} ({duration}s).")
    actions.go_to("complete")
```

### El Objeto `actions`

- `actions.go_to("next_state")`: Mueve el trabajo a un nuevo estado.
- `actions.dispatch_task(...)`: Delega el trabajo a un Worker.
- `actions.dispatch_parallel(...)`: Ejecuta múltiples tareas a la vez.
- `actions.await_human_approval(...)`: Pausa para entrada externa.
- `actions.run_blueprint(...)`: Inicia un flujo secundario.

## Conceptos Clave: JobContext y Actions

### Arquitectura de Alto Rendimiento

Holarchy está diseñada para entornos de alta carga con miles de workers concurrentes.

- **Smart Matching Unificado (RXON)**:
  - **Matching Unificado**: Migración a la lógica de selección formalizada de `rxon`. Todos los recursos (CPU, RAM, GPU, etc.) se rigen estrictamente por el estándar del protocolo HLN.
  - **Comparación Numérica Inteligente**: Realiza automáticamente verificaciones **GE (Mayor o Igual)** para números.
  - **Hot Cache y Skills**: Prioriza workers que ya tienen modelos de IA específicos cargados.
  - **Deep Schema Matching**: Prioriza a los workers cuyos esquemas coinciden con la tarea.
  - **Overflow Strategy**: Desvío automático a workers costosos si los económicos están saturados.
  - **Work Stealing**: Los trabajadores inactivos pueden robar tareas atómicamente a velocidad O(1).
  - **Load Balancing**: Incrementos de carga optimistas entre latidos (heartbeats).
  - **Networking Eficiente**: TCP Keep-Alive y compresión Zstd/Gzip.
  - **Logging Asíncrono**: Procesamiento no bloqueante vía `QueueHandler`.
  - **IO Optimizado**: Serialización pesada en hilos e índices de DB para el historial.
- **Reputación Autoregulada**:
  - **Penalizaciones**: Reducción inmediata por violaciones de contrato (-0.2) o fallos (-0.05).
  - **Trusted Guard**: Parámetro `REPUTATION_MIN_THRESHOLD` para ignorar nodos poco fiables.
- **Arquitectura basada en Contratos**:
  - **Validación de API**: Verificación de datos de entrada (`input`) antes de crear el trabajo.
  - **Validación de Resultados**: Verificación de las respuestas de los workers contra su esquema.
- **Heartbeats Bi-direccionales**: Canal de comunicación robusto con Jitter para evitar tormentas de peticiones.
- **Seguridad de Confianza Cero**:
  - **Verificación de Cadena de Identidad**: Valida la ruta completa ("bubbling path") para eventos en holarquías profundas mediante firmas digitales.
  - **mTLS y STS**: mTLS y STS para rotación de tokens de acceso.
- **E/S No Bloqueante**:
  - **Webhooks**: Enviados vía un pool paralelo de workers de fondo.
  - **Streaming S3**: Uso de memoria constante independientemente del tamaño del archivo.

## Recetario de Blueprints: Características Clave

### 1. Transiciones Condicionales

Pasa condiciones directamente a `@bp.step()` (o `@bp.handler()`) para crear ramas de lógica condicional. Las condiciones se definen como **expresiones `FastF`** de la biblioteca `fast-magic-filter` y se resuelven a través de la cascada de 4 niveles `StepScope` (ámbito actual $\rightarrow$ `input` $\rightarrow$ `steps`).

```python
from holarchy import Blueprint, Context, F, State, StatesGroup


class Flow(StatesGroup):
    decision = State()
    urgent_processing = State()
    priority_lane = State()
    normal_processing = State()


# Coincidencia directa sobre input a través de StepScope
@bp.step(Flow.decision, condition=F.type == "urgent")
async def handle_urgent(ctx: Context):
    ctx.actions.go_to(Flow.urgent_processing)


# Condición compuesta con AND lógico
@bp.step(Flow.decision, condition=(F.priority >= 8) & (F.active == True))
async def handle_priority(ctx: Context):
    ctx.actions.go_to(Flow.priority_lane)


# Paso por defecto si ninguna condición previa coincide
@bp.step(Flow.decision)
async def handle_default(ctx: Context):
    ctx.actions.go_to(Flow.normal_processing)
```

**Sintaxis soportada:** acceso a atributos (`F.status == "done"`), acceso a dict (`F.data["key"]`), lógica AND/OR/NOT (`&`, `|`, `~`), `in_()`, `regexp()`, agregadores de lista (`.any()`, `.all()`).

> **Nota:** Los atributos faltantes devuelven `False` en lugar de lanzar `AttributeError`.

### 2. Delegar Tareas a Workers (`dispatch_task`)

```python
@bp.step
async def transcode_video(input: dict, actions: ActionFactory):
    actions.dispatch_task(
        task_type="video_transcoding",
        params={"input_path": input.get("path")},
        transitions={"success": "publish_video", "failure": "retry"},
    )
```

### 3. Ejecución Paralela y Agregación (Fan-out/Fan-in)

Ejecución de múltiples tareas simultáneamente. **Aislamiento de estado por rama** evita condiciones de carrera.

```python
actions.dispatch_parallel(tasks=tasks_to_dispatch, aggregate_into="aggregate_results")


@bp.aggregator
async def aggregate_results(aggregation_results, steps, actions):
    summary = [res.get("data") for res in aggregation_results.values()]
    steps["summary"] = summary
    actions.go_to("complete")
```

### 4. Inyección de Dependencias (DataStore)

```python
bp = Blueprint("bp", data_stores={"cache": redis_client})


@bp.step
async def get_from_cache(data_stores):
    user_data = await data_stores.cache.get("user:123")
```

### 5. Programador Nativo (Scheduler)

- **Configuración:** `schedules.toml`.
- **Bloqueo Distribuido:** Seguro para múltiples instancias vía Redis.

```toml
[nightly_backup]
blueprint = "backup_flow"
daily_at = "02:00"
dispatch_timeout = 60
```

### 6. Notificaciones Webhook

Notificaciones asíncronas para `job_finished`, `job_failed` o `job_quarantined`.

### 7. Descarga de Carga Útil en S3

- **Streaming**: Uso eficiente de memoria vía `obstore` (Rust).
- **Gestionado**: Limpieza automática de objetos S3.

```python
@bp.step
async def process_data(task_files, actions):
    local_path = await task_files.download("large_dataset.csv")
    await task_files.write_json("results.json", {"status": "done"})
    actions.go_to("finished")
```

## Grupos de API y Versiones

Todos los endpoints externos están prefijados con `/api/v1/`.

**Ejemplo de Solicitud:**

```http
POST /api/v1/jobs/my_flow
{
    "input": { "video_url": "..." },
    "webhook_url": "https://my-app.com/webhooks/holarchy",
    "dispatch_timeout": 30
}

```

## Configuración de Producción

### Archivos de Configuración

- **`clients.toml`**: Clientes API, tokens y cuotas.
- **`workers.toml`**: Tokens individuales para workers. Soporta **patrones fnmatch** (ej. `cpu-worker-*`) para escalado dinámico.
- **`schedules.toml`**: Tareas periódicas.

Para más detalles, consulta la [**Guía de Configuración**](https://github.com/madgagarin/holarchy/blob/main/docs/es/configuration.md).

### Concurrencia y Rendimiento

- **`EXECUTOR_MAX_CONCURRENT_JOBS`**: Límite de manejadores internos (default: `1000`).
- **`WATCHER_LIMIT`**: Reacción ante tiempos de espera por ciclo (default: `500`).
- **`DISPATCHER_MAX_CANDIDATES`**: Límite de chequeos de cumplimiento (default: `50`).

### Observabilidad

- **Structured JSON Logging**: Vía `QueueHandler` no bloqueante.
- **Observabilidad Profunda**: Rastreo y métricas basadas en OpenTelemetry (vía OTLP).

### Seguridad y Protección de Datos

- **Seguridad Zero Trust**: Autenticación mutua (mTLS) y firma obligatoria de mensajes **HMAC SHA256** para la integridad de estados en Redis y verificación de workers.
- **Políticas Granulares para Habilidades (`policy`)**: Restringe las habilidades de workers permitidas para un trabajo mediante `policy: {"allowed_skills": ["skill_a", "skill_b"]}`.
- **Protección de Profundidad de Holarquía (`MAX_HOLARCHY_DEPTH`)**: Límite configurable (default 10) que previene la recursión infinita en sub-blueprints con cuarentena automática.
- **Infraestructura de Middleware (`MiddlewareChain`)**: Intercepta solicitudes/respuestas de manejadores, tareas salientes y eventos de workers.
- **Criptoauditoría D-DNA (`holarchy.cli.audit`)**: Verifica la integridad de la cadena del historial de eventos mediante firmas criptográficas.
- **Protección contra Replay**: Validación estricta de la marca de tiempo (`timestamp`) con una ventana de 60 segundos.
- **Integridad de la Cadena de Identidad**: Verificación matemática de las cadenas de identidad en holarquías (la firma cubre toda la ruta de la señal).
- **Envelope Encryption**: Si se establece `REDIS_ENCRYPTION_KEY`, los tokens de worker se cifran en Redis (AES-GCM).
- **Modos de Autenticación**: Soporte para `WORKER_AUTH_MODE` (`mixed`, `mtls-only`, `token-only`).
- **Aislamiento Estricto de Clientes**: Los trabajos están estrictamente vinculados al `client_token`. Un cliente solo puede acceder, gestionar o descargar archivos de los trabajos que creó.

#### Ejemplo de Políticas de Habilidades (`policy`):

```http
POST /api/v1/jobs/my_flow
{
    "input": {"input_val": 42},
    "policy": {
        "allowed_skills": ["data_extractor", "pdf_generator"]
    },
    "max_transitions": 50
}

```

#### Ejemplo de Middleware Personalizado (`MiddlewareChain`):

```python
from holarchy.middleware import BaseMiddleware


class AuditLogMiddleware(BaseMiddleware):
    async def process_outbound_task(self, context, task_payload):
        task_payload["audit_tag"] = "monitored"
        return task_payload


engine.middleware_chain.add(AuditLogMiddleware())
```

#### Ejemplo de Verificación de Criptoauditoría D-DNA (`holarchy.cli.audit`):

```python
from holarchy.cli.audit import verify_d_dna_integrity

is_valid, error = verify_d_dna_integrity(job_history_events, audit_salt="mi_clave_secreta")
if not is_valid:
    print(f"Alteración del historial detectada: {error}")
```

#### CLI de Replay Determinista (`holarchy replay evaluate`):

Evalúa comprobantes históricos de ejecución offline contra la lógica actualizada del blueprint para detectar la deriva de decisiones antes de pasar a producción:

```bash
# Evaluar decisiones históricas
holarchy replay evaluate --app mi_modulo:bp --cases .holarchy/replay/cases.jsonl

# Modo estricto para CI (código de salida 1 si se detecta alguna deriva)
holarchy replay evaluate --app mi_modulo:bp --cases .holarchy/replay/cases.jsonl --strict
```

### Límite de Tasa

Limitador de tasa granular basado en Redis (Heartbeats: 120/min, Polling: 60/min, General: 100/min).

> **Nota:** Los workers reciben un encabezado estándar **`Retry-After`** al ser bloqueados para gestionar el backoff inteligente.

### Capa de Almacenamiento

- **Redis**: Estados (`msgpack`) y colas (Streams).
- **PostgreSQL/SQLite**: Historial con índices optimizados.

### Modo Holon Puro

Establece `ENABLE_CLIENT_API="false"` para deshabilitar la API pública y solo aceptar tareas vía RXON.

## Guía para Contribuidores

```bash
pip install -e ../rxon
pip install -e ".[all,test]"
pytest tests/
```

### Documentación API Interactiva

Disponible en `/_public/docs`.

## Documentación Detallada

- [**Guía de Arquitectura**](https://github.com/madgagarin/holarchy/blob/main/docs/es/architecture.md)
- [**Referencia de API**](https://github.com/madgagarin/holarchy/blob/main/docs/es/api_reference.md)
- [**Guía de Configuración**](https://github.com/madgagarin/holarchy/blob/main/docs/es/configuration.md)
- [**Guía de Observabilidad**](https://github.com/madgagarin/holarchy/blob/main/docs/es/observability.md)
- [**Protocolo de Rastreo**](https://github.com/madgagarin/holarchy/blob/main/docs/es/observability_protocol.md)
- [**Guía de Despliegue**](https://github.com/madgagarin/holarchy/blob/main/docs/es/deployment.md)
- [**Cookbook**](https://github.com/madgagarin/holarchy/blob/main/docs/es/cookbook/README.md)
