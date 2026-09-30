# Arquitectura

## Dirección obligatoria

La dependencia conceptual es:

**UI → aplicación/casos de uso → dominio**

Persistencia, ComfyUI, Workflow Profiles/bindings, FFmpeg/FFprobe y background jobs son adaptadores. Implementan puertos internos; el dominio no depende de Qt, SQLite, HTTP, WebSocket, JSON ni procesos externos.

## Fronteras vigentes

### UI

Presenta proyectos, ejecuciones, chunks, estados, errores, cola y acciones disponibles. Sólo solicita casos de uso y renderiza snapshots/capabilities. No accede directamente a SQLite, ComfyUI o FFmpeg y no ejecuta trabajo pesado.

### Aplicación

Coordina preparación, edición, validación, ejecución, retry, recovery, cancelación segura, ensamblado y, en F13, gestión de biblioteca y scheduler. Define transacciones de aplicación y usa puertos de repositorio/backend/video.

### Dominio

Define identidades, invariantes, estados y transiciones de `Project`, `Execution`, `Chunk`, `Attempt`, `Artifact`, `TransitionFrame` y `QueueItem`. Debe permanecer determinista y testeable sin infraestructura.

### Persistencia

SQLite conserva agregados y evidencia durable con schema versionado y migraciones ordenadas. La implementación local F14.3 avanza schema 9→10 con `execution_assembly_attempts`; la migración sólo crea la tabla y conserva las filas históricas sin fabricar evidencia de finalización. La autoridad durable enlaza estado de ensamblado, rutas contenidas, hashes/probe y procedencia de Attempts/Artifacts. Las versiones anteriores siguen su ruta incremental hasta schema 10 y la carga falla cerradamente ante evidencia nueva inválida.

### ComfyUI y perfiles

ComfyUI permanece detrás del adaptador programático. Queue/history del backend son observables, no autoridad durable. MiniMax H3 vive detrás de un profile/binding que concentra nodos y entradas; los IDs no se dispersan por UI o dominio.

### Video y artifacts

FFmpeg/FFprobe permanecen detrás del adaptador de video. Chunks, outputs, transiciones N-1 y ensamblado son adicionales y no se sobrescriben silenciosamente.

#### Finalización automática F14.3

`ChainExecutionUseCase` conserva `Execution.running` luego del último chunk y delega el finalizado a `FinalizeExecutionUseCase`. Éste valida procedencia por orden de chunk, SHA-256 de cada output y transitions N−1; usa `FFmpegAssemblyAdapter.stage/inspect/publish`, persiste el identity del staging antes de publicar y comprueba de nuevo el destino antes de cambiar a `succeeded`. El nombre final `assembled-<execution-id>.mp4` es determinista; el staging queda bajo `.orquestador-assembly/<execution-id>/`. La publicación usa hard link no destructivo y bloquea un destino existente sin evidencia coincidente. F13.9 llama la cadena existente para continuar sólo el ensamblado si todos los chunks ya están completos; un retry manual no vuelve a llamar al runner/SubmitBoundary. El QueueItem sólo se libera al conciliar la evidencia final. La proyección Qt muestra estado/error y ofrece retry/export por fachada, sin acceso a FFmpeg/SQLite/ComfyUI.

### Background jobs

La UI no se bloquea. Workers ejecutan casos de uso; no se convierten en dueños de reglas de dominio ni de decisiones de scheduler.

## Flujo de ejecución existente

1. Preparación crea o reutiliza una `Execution` H3 pendiente, virgen y editable.
2. Preflight valida configuración, rutas y profile.
3. Start usa la identidad preparada inmutable y bloquea configuración stale.
4. El motor envía un chunk, correlaciona su `external_job_ref`, valida el output y persiste artifacts/checkpoint.
5. Extrae el último frame real N-1, lo materializa y lo usa como `first_frame` del siguiente chunk.
6. Retry/recovery reutiliza evidencia durable y falla cerradamente ante ambigüedad.
7. El ensamblado crea un resultado adicional mediante FFmpeg/FFprobe.

## Evolución F13: gestión de trabajos

### Borrador sin entidad nueva

El código actual ya usa `Execution` como snapshot editable antes del runtime. Por eso `Draft` será una clasificación de producto, no una entidad paralela:

```text
draft := Execution.state == pending
         y sin attempts, artifacts, errors ni TransitionFrame
         y sin QueueItem vigente
```

La regla debe implementarse una sola vez y reutilizarse en dominio, casos de uso, capabilities y persistencia. No se infiere por la ausencia de un botón ni por estado transitorio de la GUI.

Un borrador no “se transforma” en otra Execution. Encolar crea un `QueueItem` que referencia la misma `ExecutionId`; el snapshot se bloquea para edición estructural mientras esté en cola. El primer claim inicia la ejecución existente.

### Frontera de cola

La cola del producto contiene `ExecutionId`, no `ProjectId`: una ejecución identifica exactamente la configuración y secuencia que se va a correr. Un proyecto puede conservar varias ejecuciones y `execution_number` sigue siendo local a cada proyecto.

`QueueItem` es necesario porque orden, encolado, quitar/saltar y estado de despacho no pertenecen al lifecycle de una ejecución ni a ComfyUI. Debe tener identidad propia, referencia a ejecución, posición/orden durable, estado de cola y metadata mínima de creación/actualización.

No debe copiar configuración ni runtime. Es una referencia coordinadora.

F13.7 implementa la administración manual detrás de un caso de uso no-UI: selección/listado, enqueue al final, reordenamiento completo de `queued`, remove/skip terminales, pausa/reanudación y duplicación por el clone F13.2. Las mutaciones de orden y el clone+enqueue son transacciones del repositorio SQLite; ningún widget accede a tablas de cola. La duplicación crea una `Execution`/`Project` nueva por valor y no deja una referencia dinámica a la fuente.

F13.7 no reclama, inicia, envía ni terminaliza trabajo. El camino normal de Start rechaza una `Execution` con item vivo y serializa el paso `pending`→`running` contra enqueue; así no convierte una operación manual de cola en un scheduler encubierto. La edición estructural de la secuencia usa el mismo gate durable.

### Autoridad de scheduler

Un único scheduler de aplicación decide qué item se promueve. Ningún widget, callback de ComfyUI ni worker aislado puede arrancar el siguiente trabajo por su cuenta.

Reglas:

- una sola ejecución activa por GPU local;
- claim de item y registro de activo en una transacción SQLite;
- restricción durable de como máximo un item activo;
- pausa impide claims nuevos, pero no equivale a cancelar el activo;
- reordenar, quitar o saltar sólo opera sobre items todavía pendientes;
- una ejecución active/running no admite cambios estructurales;
- sólo un terminal reconciliado permite liberar el activo y elegir el siguiente.

F13.8 implementa el claim y la liberación terminal, ambos en una transacción `BEGIN IMMEDIATE`: valida control/activo, pausa, orden durable y eligibilidad antes de `queued → active` + `active_queue_item_id`; al finalizar exige el mismo item/control y una `Execution` terminal antes de `active → finished` + limpieza del control. El resultado de claim es transitorio, no otra entidad durable.

La autorización de start separa las entradas: el Start manual sólo llama la frontera que rechaza items vivos; `start_claimed` valida de nuevo el claim activo exacto y converge inmediatamente en `ChainExecutionUseCase` y el motor existente. No hay un segundo submitter, chain ni lifecycle.

Para impedir dos schedulers simultáneos, la raíz de composición adquiere un lock de un byte del SO sobre `.orquestador-scheduler.lock`; el archivo puede permanecer, pero el lock se libera al cerrar el descriptor/proceso. SQLite conserva la autoridad durable frente a conexiones o procesos competidores.

### Scheduler y recovery

En F13.8, el runtime inicia automáticamente, adquiere la autoridad única local, abre una conexión propia de worker y hace ticks fuera de Qt. La ausencia del output root confiable bloquea la frontera de readiness antes de un claim. Un tick con activo previo devuelve explícitamente `recovery_required` y no toca backend, attempts ni la cola; un tick con pausa no reclama. Sólo un claim nuevo entra mediante `start_claimed`; después del retorno se relee la `Execution` durable y sólo un lifecycle terminal permite finalizar el item. El siguiente tick puede evaluar el orden recién entonces.

F13.9 agrega la reconciliación de un activo sobreviviente con `Execution`, attempts, artifacts y backend observable. La evidencia ambigua o un activo previo bloquean y requieren revisión; nunca reclaman otro item. F13.10 sólo proyecta ese resultado y no sustituye la autoridad de recovery.

Un item activo no se devuelve automáticamente a pendiente por timeout o reinicio. `external_job_ref` durable y los contratos existentes determinan si corresponde esperar, completar, retry explícito o revisión manual.

### Clonación

`Crear a partir de este` es un caso de uso, no una copia de filas. Lee configuración reutilizable de una ejecución fuente y crea `ProjectId`, `ExecutionId`, `ChunkId` y `execution_number` nuevos. F14.1 asigna al proyecto el nombre durable `Copia de <nombre fuente>` y el primer sufijo disponible `(2)`, `(3)`, etc.; no persiste lineage.

Copia por valor: profile, imagen inicial materializada, referencias, prompts, orden/cantidad de chunks, parámetros globales y overrides públicos. Puede reutilizar paths de inputs inmutables ya contenidos bajo la raíz; cualquier materialización nueva debe ser create-if-absent y transaccional.

Nunca copia: attempts, `external_job_ref`, prompt IDs, outputs, artifacts, transiciones, errores, estados runtime, datos de recovery ni timestamps de ejecución.

### Configuración guardada

Son tres conceptos separados:

- **defaults globales:** valores técnicos aplicados sólo al crear un borrador nuevo;
- **preset técnico:** conjunto con nombre de parámetros técnicos públicos; aplicar copia valores al borrador;
- **plantilla de chunks:** nombre + secuencia de prompts; aplicar adapta cantidad/orden/prompts.

Ni presets ni plantillas quedan referenciados dinámicamente por ejecuciones. La ejecución guarda su snapshot; cambios posteriores a la fuente no son retroactivos.

Al aplicar una plantilla a un draft, la operación atómica sólo reemplaza el plan textual de la `Execution` (`chunk_count`, `prompts` y prompt por chunk). Mantiene profile, inputs, parámetros técnicos, metadata opaca y overrides de chunks que ya existían en las posiciones retenidas; los nuevos chunks nacen sólo con su prompt.

Precedencia prevista:

```text
defaults canónicos del código
→ defaults globales persistidos
→ preset técnico aplicado opcionalmente
→ snapshot de Execution
→ override explícito de Chunk
```

El preset se materializa al aplicarse; no agrega un scope runtime permanente entre Execution y Chunk.

### Biblioteca de proyectos

La biblioteca es una proyección de lectura y un conjunto de casos de uso. No accede a SQLite desde widgets. Lista proyectos/ejecuciones y deriva la presentación `draft`, `queued`, `running`, `succeeded`, `failed` o `cancelled` desde lifecycle + QueueItem, sin inventar un segundo estado persistido de ejecución.

F13.6 expone esa proyección por `PreparationLibraryUseCase` → `GuiFacade` → worker Qt → panel Biblioteca. Desde F14.1 cada `Project` tiene un nombre durable normalizado, único y separado del `ProjectId`; la Biblioteca lista y ordena por nombre, crea por nombre y ofrece renombrado administrativo. Las identidades técnicas permanecen internas para las llamadas de aplicación. En Biblioteca, `Crear a partir de esta` pide primero un nombre editable y sólo después despacha F13.2; el nombre explícito y el agregado clone se guardan dentro de una transacción SQLite, y una colisión normalizada revierte la operación. La sugerencia `Copia de <origen>` no sustituye el nombre elegido. Duplicar desde Cola conserva el nombre base automático con sufijo único; ninguno de los clones guarda lineage. Crear borrador delega en `DraftUseCase` —por eso captura los Global Defaults vigentes sólo en el nuevo snapshot—, clonar delega en F13.2 y los controles de defaults, presets y plantillas delegan respectivamente en F13.3, F13.4 y F13.5. Cada operación abre su repositorio local al worker y lo cierra allí; no cruza una conexión SQLite ligada a la UI.

Una selección no editable sigue siendo consultable, pero el panel y el formulario principal reflejan el gate durable para impedir cambios estructurales si hay cola viva, runtime o evidencia. El gate definitivo continúa en los casos de uso y la persistencia; la Biblioteca no implementa operaciones manuales de cola, scheduler ni recovery, que se exponen exclusivamente en el panel `Cola` de F13.10 mediante la fachada.

La primera versión no incluye etiquetas, carpetas sofisticadas, búsqueda avanzada, cloud ni colaboración.

### UX de cola F13.10

F13.10 expone la cola durable como una proyección de aplicación: `QueueDashboardUseCase → GuiFacade → worker Qt → QueuePanel`. `QueuePanel` no accede a SQLite, ComfyUI ni al scheduler; el worker abre y cierra el repositorio por operación y la fachada devuelve snapshots/capabilities autoritativos. `Agregar a cola` acepta únicamente la identidad preparada e inmutable que ya pasó por el flujo normal de Prepare, por lo que no crea una segunda ruta de submit.

Las operaciones de ordenar, quitar, saltar, duplicar, pausar y reanudar delegan en F13.7. Las filas consumen el nombre durable del proyecto y mantienen `ProjectId` como dato técnico interno. El scheduler F13.8/F13.9 permanece fuera del hilo UI y sólo publica `SchedulerRuntimeStatus` de lectura; un `QTimer` refresca la proyección sin bloquear. Los estados globales y por fila se derivan de QueueItem, Execution, recovery y capabilities reales; no se inventan progreso, ETA ni éxito.

#### Política F14.2 implementada

La política durable `auto | manual` está en un singleton SQLite versionado independiente de `queue_control.paused`, con default `auto` en la migración 8→9. El runtime crea un gate de despacho manual en memoria, inicialmente cerrado en cada launch; sólo `Iniciar/Reanudar cola` lo abre durante esa sesión. El coordinador de aplicación comparte un lock entre el cambio de política, el permiso y el claim, mientras SQLite valida de nuevo la política dentro de la transacción de claim.

En `manual` cerrado no hay nuevos claims. La reconciliación F13.9 puede seguir observando jobs y completando evidencia durable, pero posterga un activo virgen que necesitaría `start_claimed`; al abrir el gate continúa por la frontera existente. La proyección Qt recibe modo y gate en snapshots mediante la fachada y no accede a SQLite ni controla el scheduler.

F14.2 no cambia el shape/orden de QueueItem, el singleton de pausa, la política de cancelación, el motor de submit ni los contratos de recovery de jobs enlazados; tampoco agrega `/interrupt` o alcance de F11.6.

## Propiedad de los datos

| Información | Autoridad |
|---|---|
| Identidad y defaults reutilizables del proyecto | `Project` |
| Snapshot, profile, chunks y lifecycle de una corrida | `Execution` |
| Prompt y overrides por posición | `Chunk` |
| Submit concreto y job backend | `Attempt` |
| Output/checkpoint verificable | `Artifact` / `TransitionFrame` |
| Orden y despacho de trabajos | `QueueItem` + control de cola |
| Valores de nacimiento | defaults globales |
| Conjunto técnico reutilizable | preset técnico |
| Secuencia textual reutilizable | plantilla de chunks |
| Estado observable de ComfyUI | adaptador; nunca reemplaza SQLite |

## Exclusiones arquitectónicas

F13 no introduce multi-GPU, cloud, múltiples backends, colaboración, IA, plugin system general, prioridades inteligentes, limpieza automática ni abstracciones distribuidas. Tampoco cambia la política de cancelación running: el adaptador productivo continúa siendo pending-only y fail-closed.

## Autoridades relacionadas

- Semántica exacta e invariantes: [DATA_MODEL.md](DATA_MODEL.md).
- Orden de implementación y aceptación: [ROADMAP.md](ROADMAP.md).
- Integración backend: [COMFYUI_INTEGRATION.md](COMFYUI_INTEGRATION.md).
- Evidencia y matriz de pruebas: [TESTING.md](TESTING.md).
- Estado vivo: [STATUS.md](STATUS.md).
