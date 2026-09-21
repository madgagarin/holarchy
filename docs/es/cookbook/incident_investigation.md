[EN](https://github.com/madgagarin/holarchy/blob/main/docs/cookbook/incident_investigation.md) | **ES** | [RU](https://github.com/madgagarin/holarchy/blob/main/docs/ru/cookbook/incident_investigation.md)

# Libro de recetas: Investigación de incidentes y tarjetas de evidencia (Evidence Cards)

Cuando se producen fallos en pipelines distribuidos críticos, es fundamental determinar con rapidez la causa raíz sin exponer datos confidenciales de los usuarios.

Holarchy proporciona auditoría criptográfica con **Deterministic DNA (D-DNA)** y tarjetas de diagnóstico bajo el paradigma **Zero-Trust (Incident Evidence Cards)** para análisis post-mortem instantáneo.

---

## 1. D-DNA y cadena de custodia criptográfica

Cada trabajo en Holarchy mantiene una cadena de hashes para cada transición de estado:
- En cada paso se calcula un hash a partir del hash del estado anterior, el nombre del paso actual, las entradas y los resultados (`d_dna`).
- Si se alteran los datos históricos retroactivamente, el hash de verificación divergerá de `d_dna_hash`, marcando el trabajo como manipulado o corrupto.

---

## 2. Consulta de tarjetas de evidencia vía API

Cuando un trabajo entra en estado `failed` o `quarantined`, Holarchy genera automáticamente una **Incident Evidence Card**.

### Formato Markdown para humanos

```bash
curl -H "X-Client-Token: SU_TOKEN" \
     "http://localhost:8080/api/v1/jobs/550e8400-e29b-41d4-a716-446655440000/evidence?format=md"
```

**Ejemplo de salida:**
```markdown
# 🚨 INCIDENT EVIDENCE CARD

**Job ID:** `550e8400-e29b-41d4-a716-446655440000`
**Blueprint:** `ecommerce_orders`
**Failed Step:** `FlowStates:payment`
**D-DNA Hash:** `genesis:7f83b165...`
**Timestamp:** `2026-09-27T14:30:00Z`

---

### Causa raíz (Root Cause)
> Connection timeout: Failed to connect to payment gateway provider within 5.0s

### Recomendaciones automáticas de resolución
- [ ] **Fallo de red transitorio**: Reintentar la ejecución con retardo exponencial.
- [ ] Verificar la conectividad de red con `api.payment.internal`.

### Instantánea del estado (Sanitizada)
- **Input:** `{"order_id": 9921, "amount": 150.0}`
- **Pasos completados:**
  - `init`: `{"validated": true}`
```

### Formato estructurado JSON

```bash
curl -H "X-Client-Token: SU_TOKEN" \
     "http://localhost:8080/api/v1/jobs/550e8400-e29b-41d4-a716-446655440000/evidence"
```

Devuelve el objeto JSON completo para su integración con sistemas de alerta como PagerDuty, Slack o Datadog.

---

## 3. Sanitización Zero-Trust

Las tarjetas eliminan de manera estricta credenciales sensibles:
- Las cabeceras de autorización (`X-Client-Token`, `Authorization`) y `ORCHESTRATOR_SECRET_KEY` se eliminan.
- Secretos, contraseñas y claves privadas se reemplazan por `[REDACTED]`.

---

## 4. Clasificación automática de causas raíz

| Categoría | Causa típica | Acción recomendada |
|---|---|---|
| **Red / Transitorio** | Tiempos de espera agotados, errores 502/503/504 | Reintentar la ejecución (`retry`) o revisar la red del worker. |
| **Esquema / Contrato** | Campos obligatorios faltantes, `ValidationError` | Comprobar compatibilidad de versión del skill con el contrato. |
| **Cuotas de recursos** | Memoria insuficiente (OOM), límites de peticiones | Escalar réplicas de workers o ampliar la cuota de concurrencia. |
| **Lógica de negocio** | Candidato no válido en decider o excepción no capturada | Inspeccionar la lógica del paso o el estado de fallback. |

---

## 5. Visualización del grafo de estados con DAG

```bash
curl -H "X-Client-Token: SU_TOKEN" \
     "http://localhost:8080/api/v1/blueprints/ecommerce_orders/dag"
```

En la interfaz web interactiva (`/docs`) puede visualizar y recorrer el grafo completo de estados hasta el paso en fallo.
