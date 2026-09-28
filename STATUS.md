# Estado del proyecto

**Última actualización:** 2026-09-28
**Baseline publicado vigente:** `origin/main` en `796d9afba88a1685b163c6bd85064c08de10420c`; Git es la autoridad del SHA vigente.
**Estado de la evolución:** F13.0–F13.10 están implementadas, aprobadas y cerradas. El gate técnico pre-F14 está **CLOSED — APROBADO**. **F14.1 queda CLOSED — APROBADA**, incluida validación humana Windows del flujo create/rename/restart y `Crear a partir de esta` con nombre previo, cancelación sin escrituras, coexistencia source+clone y persistencia tras reinicio. **F14.2 es la próxima slice, todavía NO INICIADA.** F11.6 (pulido visual/UX) sigue pospuesta hasta después de F14.

Este documento es la autoridad única de estado vivo. El detalle histórico de evidencia permanece en [TESTING.md](TESTING.md), [COMFYUI_INTEGRATION.md](COMFYUI_INTEGRATION.md) y Git.

## Fotografía viva verificada contra código

- F0–F10 están cerradas en la historia del proyecto. El núcleo incluye dominio y SQLite versionado, adaptador ComfyUI, perfil MiniMax H3, ejecución por chunks, retry/recovery, chaining por último frame real y ensamblado FFmpeg/FFprobe.
- F11.0–F11.5 están cerradas según la evidencia histórica. F11.6, pulido UX final, no está cerrado.
- La GUI PySide6 permite preparar y reabrir una ejecución pendiente, editar imagen inicial, referencias, prompts, chunks y parámetros, iniciar la cadena y operar recovery/retry/cancelación segura/ensamblado mediante casos de uso.
- `ProjectId` es identidad técnica opaca, global e inmutable, separada del nombre humano durable de `Project`. Biblioteca y Cola muestran, ordenan y permiten seleccionar mediante ese nombre; la GUI conserva IDs técnicos internamente. Renombrar no altera ejecuciones ni evidencia.
- La preparación sin `ExecutionId` crea un UUID cuando no existe candidato y reutiliza una única ejecución H3 pendiente, virgen y editable. Si hay más de una candidata, falla cerradamente y exige selección explícita.
- La reapertura rehidrata imagen inicial y preview, referencias, prompts, cantidad/orden de chunks, parámetros globales y overrides. No crea otra ejecución al volver a preparar la candidata seleccionada.
- SQLite está en schema 8. F13.0 añadió por migración incremental `queue_items` y el singleton `queue_control`; F13.3 añadió `global_defaults`; F13.4 añadió `technical_presets`; F13.5 añadió `chunk_templates`; F14.1 añadió `projects.name` y `name_key` por migración 7→8, preservando IDs y evidencia histórica. F13.7 no necesitó schema nuevo: operacionaliza la fundación durable de F13.0.
- F13.3 persiste exactamente los ocho parámetros técnicos públicos de Global Defaults y los materializa sólo al crear un borrador nuevo. F13.4 persiste presets técnicos nombrados y normalizados que contienen esos mismos ocho campos: su `default` es sólo metadata y nunca se aplica automáticamente. Aplicar un preset copia sus valores a un borrador realmente editable, sin guardar referencia al preset; cambios o borrado posteriores no son retroactivos. F13.5 persiste plantillas nombradas y normalizadas con una secuencia ordenada de dos o más prompts no vacíos. Aplicarla explícitamente a un borrador realmente editable reemplaza atómicamente `chunk_count`, `prompts`, cantidad/orden de chunks y sus prompts; conserva inputs, profile, valores técnicos, metadata opaca y overrides de chunks ya existentes por posición. No guarda referencia a la plantilla: actualizarla o borrarla no cambia snapshots ya aplicados. F13.2 clone, creación normal, Prepare, Start y recovery no consultan presets ni plantillas. ComfyUI continúa detrás de adaptadores y Workflow Profile/bindings; su queue interna no es la autoridad durable del producto.
- F13.7 expone sólo casos de uso no-UI para seleccionar/listar, encolar, reordenar todos los items `queued`, quitar, saltar, pausar/reanudar y duplicar un item pendiente mediante el clone F13.2. Enqueue exige una `Execution` virgen/editable y sin item vivo; remove/skip sólo terminalizan `queued` y preservan `Project`, `Execution`, chunks y evidencia. Reordenar, cambio de pausa y clone+enqueue son transacciones SQLite; un source que deja de estar `queued` aborta el clone entero. Start y la edición de secuencia fallan cerradamente si existe un item vivo, y la transición pending→running se serializa contra un enqueue para no saltar la cola.
- F13.8 agrega `claim_next_queue_item()` y `finish_claimed_queue_item()` atómicos sobre el schema 7 existente. El claim valida `queue_control`, el único `active`, eligibilidad de la `Execution` y el primer `queued` por orden durable antes de promoverlo y registrar `active_queue_item_id`; la finalización exige la misma relación activa y una `Execution` terminal. El runtime inicia automáticamente un scheduler de aplicación con lock local de archivo/OS, fuera de Qt, y llega al mismo `StartGuiChainUseCase → ChainExecutionUseCase → SubmitBoundary` mediante `start_claimed`, sin abrir una ruta de submit paralela. Si falta el output root confiable, la frontera de readiness bloquea antes de reclamar la cola. Invocaciones repetidas con un activo, errores o submit ambiguo conservan el activo y no reenvían; esa reconciliación posterior pertenece exclusivamente a F13.9. Pausar conserva el activo y bloquea el siguiente claim. No se introdujo migración, UI de cola, multi-GPU ni cancelación running.
- F13.9 reconcilia el `QueueItem active` antes de cualquier claim nuevo. `ActiveQueueRecoveryUseCase` valida la relación activa exacta, carga la `Execution` durable y sus chunks/intentos, verifica outputs importados, artefactos y transiciones de un éxito, y usa el mismo `StartGuiChainUseCase → ChainExecutionUseCase → ResumeExecutionUseCase` para continuar u observar un job con `external_job_ref`. La recuperación de cola no habilita submit/retry automático: un intento durable sin referencia queda en manual review; un job desconocido o desaparecido conserva el activo; un job observable vivo espera; fallo o cancelación observados se persisten terminales y dejan el retry explícito como autoridad separada. Un activo virgen o `RUNNING` sin intento puede continuar porque `SubmitBoundary` persiste Attempt 1 antes del transporte. Un éxito con evidencia completa puede recuperar la transición final perdida. Pausa difiere la reconciliación del activo, conserva la relación durable y no inicia el siguiente. El cierre formal fue aprobado sobre esta implementación y los 82 tests focales registrados, sin repetir tests, auditorías ni smoke. Schema 7, UI de cola, multi-GPU, paralelismo e `/interrupt` siguen fuera de esta etapa.
- F13.10 expone la cola de producto en una pestaña `Cola` y agrega `Agregar a cola` sólo para un snapshot preparado y durablemente editable. `QueueDashboardUseCase → GuiFacade → worker Qt → QueuePanel` proyecta orden, nombre durable del proyecto, número de ejecución, estado de `QueueItem`, lifecycle de `Execution`, pausa, activo y el último resultado de scheduler sólo para lectura. Sus botones delegan enqueue, selección/consulta, reorder, remove, skip, duplicate y pausa/reanudar a las operaciones F13.7; no reclaman, envían, recuperan ni cancelan por su cuenta. El estado global distingue idle, paused, running, recovery, revisión manual y bloqueo; un activo ambiguo conserva el slot y no habilita el siguiente. El refresco visual periódico sólo relee snapshots durables y el estado runtime, fuera del hilo UI. Multi-GPU, paralelismo, cloud, prioridades inteligentes, auto-skip y `/interrupt` siguen fuera de alcance. La validación humana Windows aprobó la integración Start→Cola, la visibilidad del activo, el recovery tras reinicio y el retry exclusivo del chunk fallido sin doble submit.
- F13.6 agrega la biblioteca de preparación como una proyección de los casos de uso existentes: lista y ordena por nombre durable de proyecto y `execution_number` local con estado derivado, abre borradores/históricos, crea proyectos por nombre con `ProjectId` generado internamente, renombra sin alterar identidad/evidencia, clona mediante F13.2 y administra Global Defaults, presets técnicos y plantillas de chunks mediante sus autoridades F13.3–F13.5. La UI no solicita IDs técnicos, no accede a SQLite, ComfyUI ni FFmpeg, y ejecuta sus operaciones en el worker GUI. El clone de Biblioteca persiste el nombre elegido antes de la creación, y la duplicación de Cola conserva el autosufijo determinista; no se guarda lineage. Crear un borrador captura por copia los Global Defaults vigentes; aplicar preset o plantilla también es por copia. Una fila `queued`, activa, histórica o inconsistente se puede consultar, pero no habilita cambios estructurales. Las acciones de cola pertenecen exclusivamente al panel F13.10 y siguen delegando a sus casos de uso.
- Para evitar cambios accidentales al recorrer Biblioteca, sus controles técnicos sensibles a la rueda derivan el wheel al scroll de la página hasta recibir un click explícito. El foco Qt, incluso automático, restaurado o por navegación, no arma la edición por rueda; un click fuera del control vuelve a desarmarla. Con click explícito, se conserva la edición normal por rueda, teclado y controles propios.

## F12 — first frame como referencia primaria

El código actual contiene la opción global durable `first_frame_as_primary_reference`, default `false`, incompatible con `also_ref_first_frame=true`. Cuando está activa, el mismo IMAGE efectivo de `first_frame` ocupa la primera referencia y las referencias del usuario conservan orden denso.

**RESUELTO — listo para auditoría independiente.** F12.1 comprobó desde `main` en `ac77bc892f02641eaa6c4db7b6431ce25be98ae7` que el artifact versionado `src/orquestador/profiles/artifacts/minimax_h3_api_template.v1.json`, `H3_API_TEMPLATE_SHA256` y el manifest coinciden en SHA-256 `4DCFB2783391FBA0C5090B8A78765E46AA26B9A2215B948664F0D20341EC8F25`; `load_api_template()` carga correctamente. El supuesto hash `9F6B5785483D8FCC2C2ADBD0F574DD558BE1F605F2A8D64208AB86FC6FF4E508` fue una afirmación falsa limitada a documentación de planificación, no un estado del artifact, profile ni workflow. La repetición aislada de F10 pasó 19/19; persistencia pasó 14/14, `compileall` y `git diff --check` terminaron con código 0.

No hubo cambio de topología, bindings, producción, manifest, constantes, DB/schema, UX ni datos del proyecto. La evidencia automatizada de cierre queda en [TESTING.md](TESTING.md).

## Próxima evolución decidida

La arquitectura y el orden detallado son autoridad de [ARCHITECTURE.md](ARCHITECTURE.md), [DATA_MODEL.md](DATA_MODEL.md) y [ROADMAP.md](ROADMAP.md).

Decisiones centrales:

- un borrador no requiere una entidad `Draft`: es una `Execution` pendiente, virgen, editable y no vinculada a un elemento de cola;
- enviar un borrador a cola crea un `QueueItem` durable que referencia su `ExecutionId`;
- la cola contiene ejecuciones, no proyectos;
- una ejecución con evidencia runtime queda protegida contra edición estructural;
- defaults globales, presets técnicos y plantillas de prompts son conceptos separados;
- el scheduler propio es la única autoridad para promover el siguiente `QueueItem` y debe reconciliar el activo antes de iniciar otro;
- una sola ejecución activa por GPU local por defecto.

## Próximo paso

F14 — cierre funcional del producto actual — está **EN CURSO**. F14.1 está implementada técnicamente pero espera el smoke humano Windows antes del cierre formal; el contrato completo está en [FUNCTIONAL_COMPLETION.md](FUNCTIONAL_COMPLETION.md).

Orden aprobado:

0. **Gate pre-F14 — CLOSED — APROBADO**: hotfixes runtime reconstruidos limpiamente e integrados en `c14aa524...`; comparación diferencial contra `80943fae...` dio `NEW_REGRESSIONS=0`.
1. **F14.1 — IMPLEMENTADA, PENDIENTE VALIDACIÓN HUMANA**: en Windows crear/renombrar un proyecto, cerrar y reabrir, pedir el nombre al clonar antes de persistir, cancelar y confirmar que no hay copia, confirmar con un nombre distinto, abrir source y clone y volver a comprobar los nombres tras reiniciar. La evidencia automática está en [TESTING.md](TESTING.md).
2. **F14.2 — política de inicio de cola auto/manual**: conservar auto y agregar manual sin confundirlo con pausa ni habilitar doble submit.
3. **F14.3 — ensamblado como requisito de finalización real**: chunks completos no equivalen a ejecución final; el MP4 ensamblado y validado es requisito, con retry sólo de ensamblado.
4. **F14.4 — regresión integral y cierre funcional**.

F11.6 permanece **OPEN — NO INICIADA**, expresamente pospuesta por decisión de producto hasta cerrar F14. No se agregan características nuevas ni pulido visual dentro de F14.

F14.2 continúa **NEXT — NO INICIADA**. Su contrato está definido en `FUNCTIONAL_COMPLETION.md`; no existe todavía implementación de política auto/manual.

## Alcance y evidencia no ejercitada en el cierre F13.6

- La validación humana final Windows fue aprobada para Biblioteca, preservación del scroll, Global Defaults, Technical Presets, Chunk Templates y sus tabs, `Crear a partir de este`, contexto proyecto/ejecución/estado, layout de overrides, bloqueo y explicación de sólo lectura de históricos. La limpieza autorizada de proyectos de prueba fue comprobada tras reiniciar la aplicación: quedó únicamente `abs`.
- La corrección final de wheel fue validada en Windows: hover sin click desplaza Biblioteca sin cambiar el valor; click explícito permite la edición por wheel; click fuera desarma el control y devuelve wheel al scroll sin modificarlo. Esta evidencia humana se conserva separada de los tests Qt focales de `TESTING.md`.
- No se ejecutó ComfyUI real, FFmpeg/FFprobe real ni una ejecución de video; F13.6 no cambia workflow, submit ni runtime.
- No se repitió la suite completa ni se revalidó el runtime Linux histórico; la evidencia nueva es la batería focal documentada en `TESTING.md`, no la sustituye.
- El host PySide6 de `F10GuiMatrixTests.test_reopened_window_loads_project_before_prepare_without_duplicate_execution` no termina de forma determinista bajo `python -m unittest`; un probe en memoria con `ea106049` reproduce el mismo comportamiento. No se contabiliza como prueba aprobada ni se corrigió fuera de F13.6.
- La prueba histórica `test_render_snapshot_without_reference_authority_preserves_existing_state` de F11.4 sigue teniendo una fixture sin `execution_id`/`execution_number`; fuente y fixture ya estaban así en `ea106049`. No se corrigió fuera de alcance. Los dos asserts de tabs actualizados por la nueva pestaña Library sí pasaron.
- No se ejecutaron UI de operaciones de cola, scheduler, submit de cola ni recovery/reconciliación de cola; pertenecen a F13.7 backend y F13.8/F13.9, no a F13.6.


### Incidencia humana F14.1 — historial del flujo de renombrado

La observación humana Windows del 2026-09-28 comprobó que crear y renombrar un proyecto conserva la identidad del `ProjectId`, pero el flujo de clone no permitía elegir el nombre antes de la creación. Una reproducción Qt/offscreen también había localizado pérdida de foco al refrescar Biblioteca. El ajuste de foco publicado en `54695cd...` resolvió sólo la escritura inmediata posterior a una copia automática y no satisfizo el contrato de producto aclarado a continuación; esa complejidad se eliminó al pasar el nombre al prompt previo.


### Aclaración de producto F14.1 — source + proyecto nuevo

**Estado:** CORRECCIÓN TÉCNICA IMPLEMENTADA; PENDIENTE SMOKE HUMANO WINDOWS.

La validación humana aclaró el contrato definitivo de `Crear a partir de esta`:

1. el proyecto source debe mantenerse intacto y seguir existiendo;
2. al pulsar `Crear a partir de esta`, antes de persistir nada se solicita `Nombre del nuevo proyecto`;
3. la UI puede sugerir `Copia de <source>`, pero la persona puede escribir cualquier nombre válido;
4. sólo al confirmar se crea un Project nuevo con ProjectId/ExecutionId nuevos y configuración copiada por valor;
5. al finalizar deben coexistir source y clone como dos proyectos independientes;
6. cancelar no crea ninguna copia;
7. el nuevo proyecto debe quedar seleccionado/abierto para poder empezar a trabajar inmediatamente sobre él;
8. `Renombrar proyecto` conserva su función administrativa separada para proyectos ya existentes.

La UI ahora solicita el nombre antes del dispatch; la frontera de aplicación lo entrega al clone canónico y SQLite normaliza, verifica unicidad mediante el índice durable y persiste el proyecto con ejecución/chunks en una transacción. Cancelar retorna antes de llamar al caso de uso. La ruta de duplicación de cola mantiene el nombre automático con sufijo. Las pruebas y la comparación diferencial están registradas en [TESTING.md](TESTING.md). No se acepta “crear copia automática → renombrarla después”. F14.1 sigue pendiente del smoke humano indicado allí; F14.2 permanece NO INICIADA.


### Cierre F14.1 — validación humana aprobada

**Estado:** CLOSED — APROBADA.

Validación humana Windows completada el 2026-09-28 sobre el commit de implementación `796d9afba88a1685b163c6bd85064c08de10420c`:

- el proyecto existente conserva su nombre al renombrar y tras reiniciar;
- `Crear a partir de esta` solicita `Nombre del nuevo proyecto` **antes** de persistir;
- cancelar no crea ninguna copia;
- confirmar un nombre nuevo crea un segundo proyecto independiente;
- source y clone quedan simultáneamente visibles y seleccionables;
- ambos pueden abrirse por separado;
- cerrar y reabrir la aplicación conserva ambos nombres;
- el source permanece intacto y el clone es un proyecto independiente.

Con la evidencia automática previa (`NEW_REGRESSIONS=0`) y esta validación humana, F14.1 queda cerrada. F14.2 pasa a ser la próxima slice, todavía no iniciada.
