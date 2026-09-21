[EN](https://github.com/madgagarin/holarchy/blob/main/docs/api_reference.md) | [RU](https://github.com/madgagarin/holarchy/blob/main/docs/ru/api_reference.md) | **ES**

# Referencia de la API del Orquestador

Este documento describe todos los puntos finales HTTP proporcionados por el servidor del Orquestador. La API se divide en tres grupos lógicos: Pública, Cliente e Interna (para Workers).

## Autenticación

- **Cliente -> Orquestador:** Todas las solicitudes a los puntos finales de cliente (prefijo predeterminado `/api/v1/*`) deben contener el encabezado `X-Client-Token`. La parte `/api` es configurable mediante `CLIENT_API_PREFIX`.
- **Worker -> Orquestador:** Todas las solicitudes a los puntos finales `/_worker/*` deben contener el encabezado `X-Worker-Token` con un token de worker válido (individual o global).

---

## 1. Puntos Finales Públicos (`/_public`)

Estos puntos finales no requieren autenticación y siempre utilizan el prefijo fijo `/_public`.

### Verificación del Estado del Servicio

- **Punto final:** `GET /_public/status`
- **Descripción:** Confirma que el servicio se está ejecutando.
- **Respuesta (`200 OK`):** `{"status": "ok"}`

### Webhook para "Aprobación Humana"

- **Punto final:** `POST /_public/webhooks/approval/{job_id}`
- **Descripción:** Permite que un sistema externo u operador apruebe, rechace o decida la bifurcación siguiente para un paso del pipeline en estado `waiting_for_human`.
- **Autenticación y Seguridad:**
  - **Token de Aprobación de Ámbito Limitado (Scoped Approval Token):** Un token criptográfico de un solo uso y con límite de tiempo generado al entrar en `waiting_for_human`. Puede enviarse como parámetro de consulta en la URL (`?token=<approval_token>`) o dentro del cuerpo JSON (`{"token": "<approval_token>", ...}`). Una vez consumido con éxito, el token queda permanentemente invalidado para evitar ataques de repetición (replay attacks).
  - **Autenticación Alternativa con Token de Cliente:** Si no se proporciona un token de aprobación, la solicitud debe incluir la cabecera `X-Client-Token` válida del propietario del trabajo. Las solicitudes no autorizadas devuelven `401 Unauthorized`.
- **Cuerpo de la Solicitud:**
  ```json
  {
    "decision": "approved",
    "token": "token_opcional_si_no_se_pasa_en_la_url"
  }
  ```
  - `decision` (cadena, obligatorio): Decisión que coincide con una de las ramas configuradas para el paso (ej. `"approved"`, `"rejected"`).
  - `token` (cadena, opcional): Token de aprobación de un solo uso (si no se proporciona mediante el parámetro de consulta en la URL).
- **Códigos de Respuesta:**
  - `200 OK`: `{"status": "approval_received", "job_id": "..."}`
  - `400 Bad Request`: Solicitud vacía, JSON no válido o falta de campo `decision`.
  - `401 Unauthorized`: Falta o es inválido el `approval_token` y falta el encabezado `X-Client-Token` válido.
### Documentación Interactiva de la API

- **Punto final:** `GET /docs` (o `GET /_public/docs`)
- **Descripción:** Devuelve una página HTML interactiva y personalizada con documentación de la API, consola de pruebas en vivo, inspector de 5 zonas de almacenamiento e indicadores de riesgo y permisos.
- **Respuesta (`200 OK`):** Página HTML (`text/html`).

### Especificación Dinámica OpenAPI 3.1.0

- **Punto final:** `GET /openapi.json` (o `GET /_public/openapi.json`)
- **Descripción:** Genera dinámicamente la especificación OpenAPI 3.1.0 completa, incluyendo todos los blueprints registrados, DAG espaciales, catálogo de habilidades y encabezados del orquestador.
- **Respuesta (`200 OK`):** Objeto JSON (`application/json`) según el estándar OpenAPI 3.1.0.

---

## 2. Puntos Finales de Cliente (`/{CLIENT_API_PREFIX}/v1`)

Diseñados para sistemas externos que inician y supervisan flujos de trabajo. Requieren el encabezado `X-Client-Token`.
La ruta base para estos puntos finales es configurable a través de la variable de entorno `CLIENT_API_PREFIX` (por defecto `api`). Si se establece como una cadena vacía, estos puntos finales estarán disponibles en la raíz (ej. `/v1/...`).

### Encabezados de Solicitud del Orquestador

Al crear trabajos, los parámetros de control de la orquestación se transmiten a través de encabezados HTTP estándar, manteniendo el cuerpo JSON limpio para los datos del dominio:

- `X-Client-Token` (cadena, obligatorio): Token de autenticación del cliente.
- `X-Job-Priority` (cadena, opcional): Prioridad del trabajo (`critical`, `high`, `normal` [por defecto], `low`, `background`).
- `X-Job-Timeout` (entero, opcional): Tiempo límite máximo de ejecución en segundos.
- `X-Correlation-ID` (cadena, opcional): Identificador de trazabilidad distribuida propagado a lo largo de pasos y workers.
- `Idempotency-Key` (cadena, opcional): Clave de idempotencia para evitar la duplicación de trabajos ante reintentos de red.
- `X-Webhook-URL` (cadena, opcional): URL de webhook notificada asíncronamente cuando el trabajo alcanza un estado terminal.

### Crear Nuevo Trabajo (Punto Final Personalizado del Blueprint)

- **Punto final:** `POST /{CLIENT_API_PREFIX}/v1/{blueprint_api_endpoint}`
- **Ejemplo:** `POST /api/v1/jobs/orders`
- **Descripción:** Inicia una nueva instancia (Job) a través de la ruta personalizada configurada en el blueprint.
- **Encabezados:** Ver «Encabezados de Solicitud del Orquestador» arriba.
- **Cuerpo de la Solicitud:** Carga útil del dominio que coincide con el esquema del paso inicial:
  ```json
  {
    "order_id": 42,
    "amount": 150.0,
    "is_vip": true
  }
  ```
- **Respuesta (`202 Accepted`):**
  ```json
  {
    "status": "accepted",
    "job_id": "123e4567-e89b-12d3-a456-426614174000"
  }
  ```

### Crear Nuevo Trabajo (Iniciador Genérico de Blueprints)

- **Punto final:** `POST /{CLIENT_API_PREFIX}/v1/jobs/start/{blueprint_name}`
- **Ejemplo:** `POST /api/v1/jobs/start/ecommerce_orders`
- **Descripción:** Punto final genérico para iniciar cualquier blueprint registrado por su nombre (incluso sin ruta personalizada).
- **Encabezados:** Ver «Encabezados de Solicitud del Orquestador» arriba.
- **Cuerpo de la Solicitud:** Carga útil del dominio para el blueprint.
- **Respuesta (`202 Accepted`):**
  ```json
  {
    "status": "accepted",
    "job_id": "123e4567-e89b-12d3-a456-426614174000"
  }
  ```
- **Respuesta (`404 Not Found`):** El blueprint especificado no está registrado en el orquestador.

### Obtener Estado del Trabajo

- **Punto final:** `GET /api/v1/jobs/{job_id}`
- **Descripción:** Devuelve el estado actual del trabajo estructurado en 5 zonas de almacenamiento limpias (`input`, `output`, `meta`, `artifacts`, `receipts`).

#### Estados del Trabajo (Job Statuses)

El sistema utiliza los siguientes estados para gestionar el ciclo de vida del trabajo:

**Estados Intermedios:**

- `pending`: Trabajo creado y esperando a ser encolado.
- `running`: El trabajo se está procesando activamente.
- `waiting_for_worker`: Esperando a que un worker adecuado recoja la tarea.
- `waiting_for_human`: Esperando aprobación o acción manual (Human-in-the-loop).
- `waiting_for_parallel`: Esperando a que se completen todas las subtareas en una rama paralela.

**Estados Terminales:**

- `finished`: Trabajo completado con éxito. El resultado final está disponible en la zona `output`.
- `failed`: Error de lógica o del worker. Los detalles del error están disponibles en la respuesta.
- `cancelled`: El trabajo fue cancelado por un usuario o por el sistema.
- `error`: Error crítico del sistema durante la ejecución.
- `quarantined`: Trabajo puesto en cuarentena para revisión manual (por ejemplo, debido a una violación de contrato o falla no recuperable).

* **Parámetros:** `?fields=status,output` — filtrado de campos devueltos.

**Nota de seguridad:** El campo `output` solo se completa y es visible cuando el trabajo alcanza el estado terminal exitoso (`finished`). Para trabajos en estados intermedios, la salida se oculta para proteger datos confidenciales en proceso.

**Aislamiento de datos:** El acceso está estrictamente limitado al cliente que creó el trabajo. Debe proporcionar el mismo `X-Client-Token` que se utilizó para iniciar el trabajo. Cualquier intento de acceder a un ID de trabajo perteneciente a otro cliente devolverá un `404 Not Found` por razones de seguridad (para evitar la enumeración de ID de trabajo).

**Respuesta Compacta (Por defecto):**

```json
{
  "id": "123e4567-e89b-12d3-a456-426614174000",
  "status": "finished",
  "blueprint_name": "ecommerce_orders",
  "current_state": "FlowStates:finalize"
}
```

**Respuesta Detallada (Estructura de 5 Zonas de Almacenamiento):**

```json
{
  "id": "123e4567-e89b-12d3-a456-426614174000",
  "status": "finished",
  "blueprint_name": "ecommerce_orders",
  "current_state": "FlowStates:finalize",
  "input": {
    "order_id": 42,
    "amount": 150.0,
    "is_vip": true
  },
  "output": {
    "receipt_id": "rcpt_42",
    "status": "paid",
    "amount": 150.0
  },
  "meta": {
    "priority": "normal",
    "timeout": 300,
    "correlation_id": "corr-order-42",
    "created_at": 1715280000.0,
    "finished_at": 1715280004.2
  },
  "artifacts": {
    "invoice_pdf": "s3://bucket/invoices/inv_42.pdf"
  },
  "receipts": [
    {
      "step": "FlowStates:init",
      "timestamp": 1715280001.0,
      "status": "success",
      "chosen": "FlowStates:decide_step"
    },
    {
      "step": "FlowStates:decide_step",
      "timestamp": 1715280002.0,
      "status": "success",
      "chosen": "FlowStates:vip_process"
    }
  ]
}
```

### Tarjeta de Evidencia de Incidentes (Evidence Card)

- **Punto final:** `GET /api/v1/jobs/{job_id}/evidence`
- **Descripción:** Genera una tarjeta de diagnóstico forense para trabajos en estado `failed` o `quarantined`. Esencial para análisis post-mortem y remediación automatizada.
- **Parámetros:**
  - `format` (cadena, opcional): Formato de respuesta, `json` (por defecto) o `md` (Markdown).
- **Respuesta JSON (`200 OK`):**
  ```json
  {
    "job_id": "123e4567-e89b-12d3-a456-426614174000",
    "blueprint_name": "ecommerce_orders",
    "status": "quarantined",
    "failed_step": "FlowStates:charge_card",
    "error_message": "Payment gateway timeout after 3 retries",
    "remediation": "Check gateway API availability or replay job via /jobs/start/ecommerce_orders.",
    "receipts": [...]
  }
  ```
- **Respuesta Markdown (`200 OK` con `?format=md`):** Documento formateado (`text/markdown; charset=utf-8`) listo para compartir en Slack, Jira o GitHub Issues.

### Operaciones con S3

- `GET /api/v1/jobs/{job_id}/files/upload` — obtener URL presigned de subida.
- `PUT /api/v1/jobs/{job_id}/files/content/{filename}` — streaming directo de archivos mediante proxy del orquestador.
- `GET /api/v1/jobs/{job_id}/files/download/{filename}` — enlace estable de descarga.

### Gestión, Visualización y Diagnóstico

- `POST /api/v1/jobs/{job_id}/cancel` — cancela una tarea activa.
- `GET /api/v1/jobs/{job_id}/history` — historial completo de eventos del trabajo. En modo compacto, los campos `context_snapshot` en los eventos se filtran.
- `GET /api/v1/blueprints/{blueprint_name}/graph` — estructura del blueprint en formato Graphviz DOT.
- `GET /api/v1/blueprints/{blueprint_name}/dag` — topología 2D espacial del DAG con coordenadas de nodos, tipos de pasos (`start`, `step`, `decide`, `parallel`, `human`, `end`), ramas de transición, niveles de riesgo y permisos.
- `GET /api/v1/workers` — lista de todos los workers activos conectados.
- `GET /api/v1/dashboard` — estadísticas agregadas del sistema y colas.
- `GET /api/v1/skills` — catálogo de habilidades de workers en el clúster (caché 10s).
- `GET /api/v1/skills/{skill_name}` — especificación y contrato detallado de una habilidad (`input_schema`, `output_schema`, `risk`, `permissions`).
- `GET /api/v1/jobs` — lista de todos los trabajos. En modo compacto, los snapshots se filtran.
- `GET /api/v1/jobs/quarantined` — lista de identificadores de trabajos en cuarentena para revisión manual.

---

## 3. Puntos Finales Internos para Workers (`/_worker`)

Requieren encabezado `X-Worker-Token`.

### Registro y Latido (Heartbeat)

- **POST /\_worker/workers/register** — registro del worker y sus capacidades.
- **PATCH /\_worker/workers/{worker_id}** — confirmación de actividad. Devuelve `next_heartbeat_jitter_ms`.

### Tareas y Resultados

- **GET /\_worker/workers/{worker_id}/tasks/next** — solicitud de nueva tarea (Long-Polling + Work Stealing).
- **POST /\_worker/tasks/result** — envío del resultado de la tarea.
- **POST /\_worker/events** — envío de evento intermedio (progreso, logs).

### WebSocket

- **GET /\_worker/ws/{worker_id}** — canal para comandos en tiempo real (ej. `cancel_task`).
