# Modelo de dominio

Este documento es la autoridad de semántica, relaciones, estados e invariantes. Distingue explícitamente lo implementado de lo decidido para F13.

## Modelo implementado en HEAD auditado

### Project

Implementado como `ProjectId` global + mapping `defaults`. El código actual no posee nombre, timestamps, carpeta por proyecto ni lifecycle propio. Un proyecto agrupa una o más ejecuciones.

### Execution

Corrida concreta de un proyecto. Tiene `ExecutionId` UUID global, `execution_number` visible y correlativo dentro del proyecto, defaults/snapshot, lifecycle, profile, chunks, artifacts y errores.

`execution_number` no es identidad técnica: Proyecto A y Proyecto B pueden tener ambos `Execution 1`.

### Chunk

Unidad ordenada dentro de una ejecución. Tiene identidad, orden contiguo, defaults/overrides, lifecycle, attempts y `first_frame` enlazado cuando corresponde.

### Attempt

Submit concreto de un chunk. Retry agrega otro Attempt; no reemplaza el anterior. Conserva número, lifecycle, output/evidence/error y `BackendJobRef` asignable una sola vez.

### Artifact y TransitionFrame

`Artifact` registra procedencia de output. `TransitionFrame` vincula el output exitoso del chunk anterior con el siguiente y exige índice N-1 cuando se conoce `frame_count`. La referencia materializada conserva tipo, subfolder, nombre y SHA-256.

### WorkflowProfileRef y GenerationConfig

El profile es referencia opaca de ejecución. `GenerationConfig` es el único contrato serializable de configuración H3. En HEAD contiene:

- `profile_ref`;
- imagen inicial;
- 0..6 referencias ordenadas;
- cantidad de chunks y prompts;
- megapixels, length, steps, fps;
- `ref_image_size`;
- `also_ref_first_frame`;
- `first_frame_as_primary_reference`;
- timeout de orquestación.

El contrato exige N >= 2 y un prompt no vacío por chunk. Width/height, seed, sampler y scheduler no son superficie pública.

## Estados implementados

`Lifecycle` se comparte por Execution, Chunk y Attempt:

- `pending`;
- `running`;
- `succeeded`;
- `failed`;
- `cancelled`;
- `unknown` para carga/reconciliación, no como éxito implícito.

Transiciones normales: `pending → running|cancelled` y `running → succeeded|failed|cancelled`. Retry posee reaperturas estrechas y explícitas; no habilita transiciones generales hacia atrás.

## Ejecución editable virgen

F13 formalizará este predicado, ya implícito en código:

```text
editable_virgin(execution) =
    execution.state == pending
    and execution.artifacts está vacío
    and execution.errors está vacío
    and para todo chunk:
        state == pending
        attempts está vacío
        first_frame is None
```

Con F13 se añadirá además `and no existe QueueItem vigente` para distinguir draft de queued.

Una ejecución deja de ser estructuralmente editable al encolarse o al adquirir cualquier evidencia runtime. La comprobación no se duplica en GUI, repositorio y casos de uso: debe existir una regla canónica.

## Draft decidido para F13

`Draft` es una clasificación derivada:

```text
draft = editable_virgin(execution) and not queued(execution.id)
```

No se crea tabla ni clase Draft. Crear un borrador crea una nueva Execution pendiente. Guardar/reabrir conserva la misma identidad. Encolar no crea otra ejecución: crea QueueItem.

## QueueItem decidido para F13

Entidad durable mínima:

- `id: QueueItemId` global;
- `execution_id: ExecutionId` con foreign key;
- `position` u otra clave de orden total estable;
- `state`;
- `created_at` y `updated_at` en UTC para auditoría operativa mínima;
- razón terminal opcional para remove/skip/failure de coordinación.

Estados mínimos propuestos:

- `queued`: pendiente y reordenable;
- `active`: reclamado por la autoridad del scheduler;
- `finished`: ejecución reconciliada terminal;
- `removed`: quitado antes de iniciar;
- `skipped`: omitido explícitamente antes de iniciar.

`paused` pertenece al control singleton de cola, no a cada item. `running`, `failed`, `succeeded` y `cancelled` continúan perteneciendo a Execution; la UI combina ambos modelos para presentar estado.

Invariantes:

1. QueueItem referencia una Execution existente.
2. Sólo una ejecución editable virgen puede encolarse inicialmente.
3. Una Execution no puede tener dos QueueItems vigentes (`queued|active`).
4. Existe como máximo un QueueItem `active`.
5. Sólo `queued` puede reordenarse, quitarse o saltarse.
6. `active` no vuelve automáticamente a `queued` después de crash.
7. `finished` requiere que Execution esté terminal y reconciliada.
8. Borrar/quitar QueueItem nunca borra Project, Execution, chunks ni artifacts.

La migración SQLite debe crear restricciones/índices que refuercen 3 y 4, además de validación de aplicación.

## Control de cola

Registro singleton durable con:

- `paused: bool`;
- `active_queue_item_id` opcional o relación equivalente validada;
- revisión/versión para updates transaccionales si la implementación lo necesita.

Pausar impide iniciar el siguiente item. No cancela ni interrumpe el activo.

## Clasificación de biblioteca

La clasificación visible se deriva en este orden:

1. QueueItem active → `running/recovering` según Execution y evidencia;
2. QueueItem queued → `queued`;
3. editable virgin sin item → `draft`;
4. Execution lifecycle terminal → `succeeded|failed|cancelled`;
5. inconsistencias → `attention_required`, sólo como proyección UI, no nuevo lifecycle persistido.

## Clonación de configuración

La clonación construye agregados nuevos. Copia:

- Workflow Profile;
- imagen inicial y referencias materializadas/reutilizables;
- cantidad, orden y prompts de chunks;
- parámetros globales de GenerationConfig;
- overrides públicos por chunk.

Genera nuevos `ProjectId`, `ExecutionId`, `ChunkId` y numeración local. No copia:

- AttemptId o attempts;
- BackendJobRef/prompt IDs;
- lifecycle runtime;
- artifacts, outputs o transition frames;
- errores;
- queue items;
- información de recovery;
- timestamps de ejecución.

La operación es atómica. Si falla materialización o persistencia, no queda una copia parcial.

## Defaults globales

Registro durable versionado que contiene sólo valores técnicos públicos con los que nace un borrador nuevo. No incluye inputs, referencias, prompts, cantidad de chunks, runtime ni outputs.

Modificarlo nunca reescribe Project.defaults, Execution.defaults ni Chunk.defaults existentes.

## Preset técnico

Entidad con ID, nombre único normalizado, mapping técnico validado y timestamps mínimos. Aplicar un preset copia sus valores al draft. La ejecución no conserva dependencia dinámica con el preset.

No contiene imagen, referencias, prompts, chunks, runtime ni outputs.

## Plantilla de chunks

Entidad con ID, nombre único normalizado, secuencia ordenada N >= 2 de prompts no vacíos y timestamps mínimos. Aplicarla reemplaza atómicamente cantidad/orden/prompts del draft y deja todo editable.

No contiene parámetros técnicos, imágenes, referencias, runtime ni outputs.

## Precedencia de configuración

La precedencia decidida es:

```text
defaults canónicos del código
→ defaults globales al crear
→ preset técnico al aplicar
→ snapshot durable de Execution
→ override de Chunk
```

Defaults globales y preset son mecanismos de autoría. En runtime sólo mandan el snapshot durable de Execution y los overrides de Chunk.

## Recovery de cola

Después de reinicio, un QueueItem active obliga a reconciliar su Execution antes de reclamar otro. La decisión usa estado durable, attempts, BackendJobRef, artifacts, TransitionFrame y observación fresca de ComfyUI.

- Evidencia terminal coherente permite finalizar el item.
- Job queued/running coherente conserva el activo y continúa esperando/recuperando.
- Job no encontrado usa el contrato de stale/retry ya existente.
- Evidencia ambigua o contradictoria bloquea; no inicia el siguiente trabajo.

Nunca se infiere éxito sólo porque ComfyUI no muestre el job.

## Persistencia y compatibilidad

F13.0 elevó el schema a 4 mediante una migración incremental desde 3; no recrea la base. Añade `queue_items`, sus índices parciales de items vigentes/activo, y `queue_control` singleton sin cambiar filas históricas. Defaults globales iniciales deben equivaler a los defaults canónicos vigentes para no alterar comportamiento.

El orden de migración debe permitir que bases schema 1/2 sigan alcanzando el schema nuevo mediante las migraciones existentes 2 y 3.

## Invariantes heredadas

- IDs técnicos son opacos y no se reutilizan.
- Chunks tienen orden contiguo y pertenecen a una sola Execution.
- Retry agrega Attempt y preserva evidencia.
- `external_job_ref` no se reasigna.
- Success requiere output y evidencia.
- TransitionFrame conserva procedencia N-1.
- Rutas persistidas son relativas y contenidas.
- Outputs no se sobrescriben ni se eliminan silenciosamente.
- UI no decide transiciones ni accede a SQLite.
