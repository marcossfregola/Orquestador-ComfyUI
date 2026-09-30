# Estado del proyecto

**Última actualización:** 2026-09-30
**Implementación F14.2:** `8b7258304eca384d20d4721f35639268a6036e01`; diagnóstico documental posterior `5a17e450982a67360bf08f4740528c0f90500eb9`; cierre humano aprobado el 2026-09-29.
**Baseline F14.3:** `5bb63389ff3af7de1d81581fae15de0b1f5327cb` (igual a `origin/main` al iniciar el trabajo).
**Estado vivo:** F13.0–F13.10 y F14.1–F14.2 están **CLOSED — APROBADAS**. La implementación y el smoke humano de F14.3 fueron **APROBADOS CON OBSERVACIONES**; el cierre documental y la higiene Git están preparados para auditoría final, sin commit/push en esta ronda. F14.3 aún no se declara CLOSED y F14.4 no se inició. F11.6 sigue pospuesta hasta después de F14.

Este documento es la autoridad única de estado vivo. El detalle histórico de evidencia permanece en [TESTING.md](TESTING.md), [COMFYUI_INTEGRATION.md](COMFYUI_INTEGRATION.md) y Git.

## Fotografía viva verificada contra código

- F0–F10 están cerradas en la historia del proyecto. El núcleo incluye dominio y SQLite versionado, adaptador ComfyUI, perfil MiniMax H3, ejecución por chunks, retry/recovery, chaining por último frame real y ensamblado FFmpeg/FFprobe.
- F11.0–F11.5 están cerradas según la evidencia histórica. F11.6, pulido UX final, no está cerrado.
- La GUI PySide6 permite preparar y reabrir una ejecución pendiente, editar imagen inicial, referencias, prompts, chunks y parámetros, iniciar la cadena y operar recovery/retry/cancelación segura/ensamblado mediante casos de uso.
- `ProjectId` es identidad técnica opaca, global e inmutable, separada del nombre humano durable de `Project`. Biblioteca y Cola muestran, ordenan y permiten seleccionar mediante ese nombre; la GUI conserva IDs técnicos internamente. Renombrar no altera ejecuciones ni evidencia.
- La preparación sin `ExecutionId` crea un UUID cuando no existe candidato y reutiliza una única ejecución H3 pendiente, virgen y editable. Si hay más de una candidata, falla cerradamente y exige selección explícita.
- La reapertura rehidrata imagen inicial y preview, referencias, prompts, cantidad/orden de chunks, parámetros globales y overrides. No crea otra ejecución al volver a preparar la candidata seleccionada.
- El código de F14.3 lleva SQLite a schema 10 mediante migración 9→10, que agrega `execution_assembly_attempts` sin inferir registros para ejecuciones históricas. Mantiene las migraciones previas: F13.0 `queue_items`/`queue_control`; F13.3 `global_defaults`; F13.4 `technical_presets`; F13.5 `chunk_templates`; F14.1 nombre durable de proyecto 7→8; F14.2 `queue_start_policy` 8→9 con `auto` predeterminado.
- F13.3 persiste exactamente los ocho parámetros técnicos públicos de Global Defaults y los materializa sólo al crear un borrador nuevo. F13.4 persiste presets técnicos nombrados y normalizados que contienen esos mismos ocho campos: su `default` es sólo metadata y nunca se aplica automáticamente. Aplicar un preset copia sus valores a un borrador realmente editable, sin guardar referencia al preset; cambios o borrado posteriores no son retroactivos. F13.5 persiste plantillas nombradas y normalizadas con una secuencia ordenada de dos o más prompts no vacíos. Aplicarla explícitamente a un borrador realmente editable reemplaza atómicamente `chunk_count`, `prompts`, cantidad/orden de chunks y sus prompts; conserva inputs, profile, valores técnicos, metadata opaca y overrides de chunks ya existentes por posición. No guarda referencia a la plantilla: actualizarla o borrarla no cambia snapshots ya aplicados. F13.2 clone, creación normal, Prepare, Start y recovery no consultan presets ni plantillas. ComfyUI continúa detrás de adaptadores y Workflow Profile/bindings; su queue interna no es la autoridad durable del producto.
- F13.7 expone sólo casos de uso no-UI para seleccionar/listar, encolar, reordenar todos los items `queued`, quitar, saltar, pausar/reanudar y duplicar un item pendiente mediante el clone F13.2. Enqueue exige una `Execution` virgen/editable y sin item vivo; remove/skip sólo terminalizan `queued` y preservan `Project`, `Execution`, chunks y evidencia. Reordenar, cambio de pausa y clone+enqueue son transacciones SQLite; un source que deja de estar `queued` aborta el clone entero. Start y la edición de secuencia fallan cerradamente si existe un item vivo, y la transición pending→running se serializa contra un enqueue para no saltar la cola.
- F13.8 agrega `claim_next_queue_item()` y `finish_claimed_queue_item()` atómicos. F14.3 endurece el cierre exitoso: una ejecución `succeeded` libera la cola sólo con evidencia durable de MP4 ensamblado y validado; el estado `succeeded` heredado de una base antigua se conserva legible, pero no basta para dar por reconciliado un activo.
- F13.9 conserva la recuperación active-first y, en F14.3, reingresa la misma cadena para continuar sólo el ensamblado cuando todos los chunks ya están completos. Si el MP4 y su evidencia no validan, el activo permanece ocupado; no se vuelve a enviar un chunk ni se reclama el siguiente.
- F13.10 expone la cola de producto en una pestaña `Cola` y agrega `Agregar a cola` sólo para un snapshot preparado y durablemente editable. `QueueDashboardUseCase → GuiFacade → worker Qt → QueuePanel` proyecta orden, nombre durable del proyecto, número de ejecución, estado de `QueueItem`, lifecycle de `Execution`, pausa, activo y el último resultado de scheduler sólo para lectura. Sus botones delegan enqueue, selección/consulta, reorder, remove, skip, duplicate y pausa/reanudar a las operaciones F13.7; no reclaman, envían, recuperan ni cancelan por su cuenta. El estado global distingue idle, paused, running, recovery, revisión manual y bloqueo; un activo ambiguo conserva el slot y no habilita el siguiente. El refresco visual periódico sólo relee snapshots durables y el estado runtime, fuera del hilo UI. Multi-GPU, paralelismo, cloud, prioridades inteligentes, auto-skip y `/interrupt` siguen fuera de alcance. La validación humana Windows aprobó la integración Start→Cola, la visibilidad del activo, el recovery tras reinicio y el retry exclusivo del chunk fallido sin doble submit.
- F14.2 conserva el autoarranque y permite elegir `auto | manual` desde Cola. Manual abre cada runtime con el gate cerrado; `Iniciar/Reanudar cola` autoriza nuevos claims sólo durante esa sesión. El claim lee la política durable dentro de su transacción, y el gate se serializa con cambios de modo; pause sigue independiente. La validación humana Windows aprobó el comportamiento Manual y Automático con ComfyUI real: trabajos en espera no arrancaron sin permiso, dos proyectos de dos chunks se ejecutaron secuencialmente al abrir el gate, ambos terminaron sin duplicados y el modo Automático inició un nuevo trabajo sin usar el botón manual. F14.2 queda CLOSED — APROBADA.
- F14.3 conserva `Execution` en `running` después del último chunk y finaliza automáticamente por el scheduler/orquestación existente. `FinalizeExecutionUseCase` valida orden, transiciones N−1, un Artifact inequívoco por Attempt y SHA-256 de cada fuente; `FFmpegAssemblyAdapter` crea `.orquestador-assembly/<execution-id>/attempt-N.mp4`, valida con FFprobe y publica sin sobrescribir `assembled-<execution-id>.mp4`. Schema 10 conserva estado, hashes, firma FFprobe, rutas y procedencia. El smoke Windows de dos chunks confirmó assembly automático, reproducción completa del MP4 y continuidad/orden visual; el QueueItem se finalizó después de persistir la evidencia válida. En assembly no hubo Attempts de chunk nuevos ni submits a ComfyUI. La auditoría dio **APROBADA CON OBSERVACIONES**; el commit/push no se hizo y el cierre formal queda sujeto a la auditoría Git final.
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

F14 — cierre funcional del producto actual — está **EN CURSO**. F14.1 y F14.2 están cerradas/aprobadas. La implementación y el smoke humano Windows de F14.3 están **APROBADOS CON OBSERVACIONES**; resta la auditoría final del conjunto documental/Git antes de un eventual commit autorizado. F14.4 no se inició. El contrato completo está en [FUNCTIONAL_COMPLETION.md](FUNCTIONAL_COMPLETION.md).

Orden aprobado:

0. **Gate pre-F14 — CLOSED — APROBADO**: hotfixes runtime reconstruidos limpiamente e integrados en `c14aa524...`; comparación diferencial contra `80943fae...` dio `NEW_REGRESSIONS=0`.
1. **F14.1 — CLOSED — APROBADA**: nombre durable/rename/clone verificados con pruebas automáticas y smoke humano Windows del 2026-09-28; evidencia en [TESTING.md](TESTING.md).
2. **F14.2 — CLOSED — APROBADA**: política durable auto/manual verificada con pruebas automáticas y smoke humano Windows con ComfyUI real; no se observó doble submit ni paralelismo indebido.
3. **F14.3 — implementación y smoke APROBADOS CON OBSERVACIONES**: chunks completos no equivalen a ejecución final; el MP4 ensamblado y validado es requisito, con retry sólo de ensamblado. Se trabaja sobre el baseline `5bb6338`; la higiene Git está preparada para auditoría final, sin commit/push.
4. **F14.4 — regresión integral y cierre funcional**.

F11.6 permanece **OPEN — NO INICIADA**, expresamente pospuesta por decisión de producto hasta cerrar F14. No se agregan características nuevas ni pulido visual dentro de F14.

F14.2 está **CLOSED — APROBADA**. La implementación y validación humana de F14.3 están **APROBADAS CON OBSERVACIONES**; no se declara cerrada en esta entrega documental previa al commit. F14.4 permanece **PLANNED — NO INICIADA**.

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


### Incidente de smoke F14.2 — Prepare deja la GUI sin responder

**Estado:** NO REPRODUCIDO; REGISTRADO COMO INCIDENTE TRANSITORIO NO BLOQUEANTE PARA EL CIERRE F14.2.

El diagnóstico controlado sobre `main=0f6dd576980f23a7b5750503e0f56cc77377bd5c` no reprodujo el freeze de >30 s. F14.1 y F14.2 mostraron tiempos de Prepare del orden de decenas de milisegundos con imágenes sintéticas de 7 MB y 50 MB; la mayor pausa del event loop medida fue ~124 ms.

Prepare y GUI se observaron en hilos distintos. SQLite quedó íntegro, sin transacciones largas ni rollback; Manual cerrado devolvió `DISPATCH_CLOSED`. No hubo llamadas a ComfyUI. La hipótesis de contención introducida por F14.2 no quedó demostrada.

Se observó que el render de preview carga QPixmap sincrónicamente y puede causar pausas breves con imágenes grandes, comportamiento ya presente en F14.1; no explica por sí solo el freeze humano de >30 s.

El incidente no reapareció en el smoke humano posterior tras reinicio de Windows: `Prepare` volvió a operar normalmente y la prueba real de cola pudo completarse. La causa raíz del freeze aislado sigue sin demostrarse; si reaparece se capturará stack/dump antes de cualquier corrección. No se modifica producción por una hipótesis no reproducida.

F14.2 queda CLOSED — APROBADA. La implementación y el smoke humano de F14.3 fueron aprobados con observaciones; su cierre formal queda pendiente de la auditoría Git final y del commit autorizado. F14.4 permanece NO INICIADA.
