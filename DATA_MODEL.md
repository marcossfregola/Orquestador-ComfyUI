# Modelo de dominio

Este documento es la autoridad de semántica, relaciones, estados e invariantes. La sección F14.3 describe el modelo implementado y publicado en schema 10. F14.3 y F14.4 están **CLOSED — APROBADAS**; el baseline de código validado para el cierre F14 es `ea2d50deeb59f185fddeee142e4feb39e6f2b258`.

## Modelo implementado en HEAD auditado

### Project

Implementado como `ProjectId` global e inmutable, mapping `defaults` y nombre humano durable `name`. `name_key` guarda la forma NFC + `casefold()` usada para unicidad; el nombre mostrado conserva NFC luego de quitar espacios externos. Un proyecto no tiene timestamps, carpeta ni lifecycle propio y agrupa una o más ejecuciones. Renombrar sólo actualiza `name`/`name_key`: no modifica IDs, ejecuciones, numeración, cola ni evidencia.

### Execution

Corrida concreta de un proyecto. Tiene `ExecutionId` UUID global, `execution_number` visible y correlativo dentro del proyecto, defaults/snapshot, lifecycle, profile, chunks, artifacts, errores e historial de ensamblado final.

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

F14.3 agrega `AssemblyState` para finalización, separado del lifecycle de Execution/Chunk/Attempt: `pending → assembling → failed|succeeded`. Para ejecuciones de producto multichunk, `Execution.succeeded` requiere un ensamblado exitoso con procedencia completa. El último chunk deja la ejecución en `running`; no completa ni libera la cola. El componente F6 de un chunk conserva su contrato aislado y no participa del flujo de producto multichunk.

## Ejecución editable virgen

F13.0 formalizó este predicado, antes implícito en código:

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

La clasificación implementada añade `and no existe QueueItem vigente` para distinguir `draft` de `queued`.

Una ejecución deja de ser estructuralmente editable al encolarse o al adquirir cualquier evidencia runtime. La comprobación no se duplica en GUI, repositorio y casos de uso: debe existir una regla canónica.

## Draft durable de F13

`Draft` es una clasificación derivada:

```text
draft = editable_virgin(execution) and not queued(execution.id)
```

No se crea tabla ni clase Draft. Crear un borrador crea una nueva Execution pendiente. Guardar/reabrir conserva la misma identidad. Encolar no crea otra ejecución: crea QueueItem.

## QueueItem durable de F13

Entidad durable mínima:

- `id: QueueItemId` global;
- `execution_id: ExecutionId` con foreign key;
- `position` u otra clave de orden total estable;
- `state`;
- `created_at` y `updated_at` en UTC para auditoría operativa mínima;
- razón terminal opcional para remove/skip/failure de coordinación.

Estados durables:

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

El schema 4 ya contiene restricciones/índices que refuerzan 3 y 4, además de validación de aplicación. F13.7 y F13.8 no crean otra tabla ni otro lifecycle: operacionalizan estos registros sin reescribir filas históricas.

## Control de cola

Registro singleton durable con:

- `paused: bool`;
- `active_queue_item_id` opcional o relación equivalente validada;
- revisión/versión para updates transaccionales si la implementación lo necesita.

Pausar impide iniciar el siguiente item. No cancela ni interrumpe el activo.

### Finalización de ejecución F14.3

`AssemblyAttempt` queda asociado a una sola `Execution`. El historial append-only es la autoridad durable de finalización y reside en `execution_assembly_attempts` (schema 10). Cada registro contiene número, estado, ruta final, ruta de staging, fuentes ordenadas, SHA-256 y firma FFprobe del resultado, error y timestamps.

Cada `AssemblySourceEvidence` enlaza orden, `ChunkId`, `AttemptId`, `ArtifactId`, output relativo y SHA-256 de los bytes importados. Antes de aceptar una fuente, el caso de uso exige un único Attempt exitoso con evidencia, un único Artifact OUTPUT coincidente y, para cada enlace intermedio, exactamente un `TransitionFrame` N−1 al siguiente chunk. Las rutas final, staging y fuentes deben quedar bajo el project root.

La ruta final determinista es `assembled-<execution-id>.mp4`. El staging por tentativa es `.orquestador-assembly/<execution-id>/attempt-N.mp4`. FFmpeg crea y FFprobe valida el staging; su hash/firma se persisten antes de publicarlo. La publicación por hard link no reemplaza un destino existente. Después de publicar, se inspeccionan otra vez hash, firma FFprobe y procedencia antes de guardar `AssemblyState.succeeded` y `Execution.succeeded` en una transacción.

Un fallo mantiene `Execution.running` y conserva chunks, Attempts, outputs y transiciones. Retry agrega una tentativa de ensamblado y sólo se permite si las fuentes no cambiaron, la procedencia sigue inequívoca y la ruta final no existe. No llama al runner de chunks ni a ComfyUI. Un destino previo o evidencia contradictoria bloquea; la mera presencia del archivo no constituye éxito.

La migración schema 9→10 crea la tabla vacía y deja las ejecuciones terminales históricas legibles sin inventar evidencia final. El scheduler sólo libera un QueueItem exitoso si la aplicación verificó el final actual; SQLite también rechaza el cierre sin estado/hash/probe/procedencia durables.

### Política de inicio F14.2 implementada

`QueueStartMode` es configuración durable global del producto (`auto | manual`), independiente de `QueueControl.paused`, guardada en un singleton `queue_start_policy`. La migración schema 8→9 crea la fila como `auto`, por lo que una base existente mantiene su comportamiento. Una fila ausente, duplicada, inválida o con modo desconocido es corrupción y falla cerradamente.

El permiso de despacho manual es una autorización de proceso/sesión, no un atributo durable ni parte de `QueueItem` o `QueueControl`. Cada runtime lo crea cerrado. `Iniciar/Reanudar cola` lo abre sólo para esa sesión; reiniciar lo vuelve a cerrar aunque `manual` permanezca guardado. Cambiar el modo a `manual` cierra el permiso bajo el mismo coordinador que serializa claims y no altera el activo.

El claim lee `QueueStartMode`, `QueueControl` y el único activo dentro de una transacción. En modo `manual` sin permiso retorna un resultado transitorio de despacho cerrado sin promover filas; `auto` sigue con las reglas F13.8. La pausa sigue bloqueando claims bajo su semántica existente en ambos modos.

Con permiso cerrado, recovery puede completar evidencia terminal y observar referencias backend ya enlazadas por la ruta no-submit existente. No puede llamar a `start_claimed` para una ejecución pending virgen, porque eso generaría un submit nuevo; ese activo permanece exclusivo y espera permiso. El recovery de una ejecución running sin intento conserva el flag no-submit de F13.9 y sólo inspecciona/reconcilia evidencia.

## Claim y finalización F13.8

`claim_next_queue_item()` es una transacción SQLite única. Lee y valida `queue_control` y el único `active`; si existe activo devuelve un resultado transitorio de bloqueo/recovery, si está pausada devuelve pausa, y si no hay `queued` devuelve vacío. Sólo entonces selecciona el primer `queued` por `position,id`, revalida su `Execution` virgen/pending y su propiedad viva única, y persiste juntos `queued → active`, `active_queue_item_id` y una revisión incrementada.

El resultado del claim no se persiste como entidad o lifecycle adicional. Contiene la identidad del item sólo para la frontera de scheduler que debe arrancar exactamente esa `Execution`.

`finish_claimed_queue_item()` también es una transacción única: exige que item/control/execution coincidan, que no exista otro activo y que la `Execution` ya sea `succeeded`, `failed` o `cancelled`. Para `succeeded` exige además un ensamblado final durable con destino, hash, firma FFprobe y fuentes; la aplicación comprueba los bytes/procedencia actuales antes de llegar a esta frontera. Sólo entonces persiste `active → finished`, limpia `active_queue_item_id` e incrementa la revisión. No borra evidencia ni QueueItems históricos.

## Operaciones manuales F13.7

F13.7 opera sólo el conjunto `queued`; no reclama ni inicia trabajo. `enqueue` agrega al final una `Execution` editable virgen y sin item vivo. `reorder` recibe exactamente todos los IDs `queued` una vez y persiste el nuevo orden completo en una transacción SQLite. `remove` y `skip` sólo terminalizan un item `queued` con una razón explícita; nunca borran el agregado que referencia.

La pausa/reanudación cambia el singleton `queue_control` de forma idempotente y admite una revisión esperada para detectar actualizaciones competidoras. Un `active` no se reordena, quita, salta ni duplica. La duplicación parte de un item `queued`, construye el clon de configuración F13.2 y agrega su nuevo item en la misma transacción; si la fuente deja de estar `queued` o el enqueue falla, no queda un proyecto/clon parcial. No se guarda una referencia dinámica entre el clone y la fuente.

La cola bloquea cambios estructurales del snapshot: save/reapertura de draft, presets y plantillas ya exigen que no exista item vivo; F13.7 también bloquea la edición de secuencia y Start. La transición normal de Start de `pending` a `running` se serializa con el enqueue: un item vivo (`queued` o `active`) impide esa transición y una ejecución ya `running` deja de ser elegible para enqueue.

## Clasificación de biblioteca

La clasificación visible se deriva en este orden:

1. QueueItem active → `running/recovering` según Execution y evidencia;
2. QueueItem queued → `queued`;
3. editable virgin sin item → `draft`;
4. Execution lifecycle terminal → `succeeded|failed|cancelled`;
5. inconsistencias → `attention_required`, sólo como proyección UI, no nuevo lifecycle persistido.

F13.6 no añade columnas, tablas ni una relación nueva. Su snapshot de UI transporta solamente la clasificación derivada y la capability `can_edit`; crear desde la biblioteca usa el mismo `DraftUseCase` y materializa por copia los ocho Global Defaults y `workflow_profile_ref` en la nueva `Execution`. Presets, plantillas y clones siguen siendo copias sin IDs o referencias dinámicas en la ejecución creada.

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

La operación es atómica. Si falla materialización o persistencia, no queda una copia parcial. El clone de Biblioteca recibe el nombre explícito antes de invocar el caso de uso; SQLite lo normaliza con NFC/strip y exige que su clave casefold siga libre en el índice único al persistir, dentro de la misma transacción que Project, Execution y Chunks. Un conflicto no deja agregados parciales. Cancelar el diálogo no invoca la aplicación ni crea Project, Execution, Chunk, QueueItem o archivo. El duplicado de cola continúa usando el nombre base automático y el primer sufijo libre dentro de su transacción clone+enqueue.

## Defaults globales

Registro durable versionado que contiene sólo valores técnicos públicos con los que nace un borrador nuevo. No incluye inputs, referencias, prompts, cantidad de chunks, runtime ni outputs.

Modificarlo nunca reescribe Project.defaults, Execution.defaults ni Chunk.defaults existentes.

## Preset técnico

Entidad con ID, nombre único normalizado, mapping técnico validado y timestamps mínimos. Aplicar un preset copia sus valores al draft. La ejecución no conserva dependencia dinámica con el preset.

No contiene imagen, referencias, prompts, chunks, runtime ni outputs.

## Plantilla de chunks

Entidad durable global con ID, nombre único normalizado, `template_version=1`, secuencia ordenada N >= 2 de prompts no vacíos y timestamps mínimos. Aplicarla reemplaza atómicamente cantidad/orden/prompts del draft y deja todo editable. Actualizar o borrar la plantilla no altera snapshots ya aplicados.

No contiene parámetros técnicos, imágenes, referencias, runtime ni outputs. La aplicación conserva profile, inputs, parámetros técnicos, metadata opaca y los overrides existentes de los chunks retenidos por posición; los nuevos chunks contienen sólo el prompt de la plantilla.

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

Después de reinicio, un QueueItem active obliga a reconciliar su Execution antes de reclamar otro. F13.8 lo detecta y bloquea explícitamente sin mutar o reenviar; la decisión completa usa estado durable, attempts, BackendJobRef, artifacts, TransitionFrame y observación fresca de ComfyUI, y F13.9 la resuelve. F13.10 sólo presenta el resultado de esa autoridad y conserva el bloqueo cuando la evidencia es ambigua.

- Evidencia terminal coherente permite finalizar el item.
- Job queued/running coherente conserva el activo y continúa esperando/recuperando.
- Job no encontrado usa el contrato de stale/retry ya existente.
- Evidencia ambigua o contradictoria bloquea; no inicia el siguiente trabajo.

Nunca se infiere éxito sólo porque ComfyUI no muestre el job.

## Proyección UI de cola F13.10

La UI no agrega una tabla ni un lifecycle paralelo: `QueueDashboardUseCase` lee QueueItem, Execution y el estado de runtime para construir filas y un estado global derivado. La selección conserva el `execution_id` opaco y las capabilities de la autoridad de aplicación; los widgets no abren repositorios ni llaman ComfyUI.

`Agregar a cola` requiere el snapshot preparado e inmutable del flujo normal. Reordenar, quitar, saltar, duplicar, pausar y reanudar siguen siendo mutaciones de los casos de uso F13.7 y respetan sus invariantes: el item active no se elimina ni se salta y pausar no cancela. Recovery, manual review y blocked se muestran como estados de espera/bloqueo, nunca como permiso para liberar o reenviar automáticamente.

## Persistencia y compatibilidad

SQLite se mantiene en schema 10 en el baseline validado para el cierre F14 (`ea2d50deeb59f185fddeee142e4feb39e6f2b258`). F13.0 elevó el schema a 4; F13.3 añadió `global_defaults` en schema 5; F13.4 añadió `technical_presets` en schema 6; F13.5 añadió `chunk_templates` en schema 7; F14.1 añadió nombres de proyecto mediante 7→8; F14.2 añadió `queue_start_policy` mediante 8→9; F14.3 añade `execution_assembly_attempts` mediante 9→10. Esta última migración no cambia las ejecuciones/chunks/attempts/artifacts existentes ni infiere resultados assembly. Las migraciones ordenadas mantienen el camino desde schema 1/2 hasta la versión actual; los valores iniciales de defaults y política preservan el comportamiento vigente.

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
