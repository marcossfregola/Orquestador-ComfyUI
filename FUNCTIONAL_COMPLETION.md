# F14 — Cierre funcional del producto actual

**Estado:** **F14 — CLOSED — APROBADO**; F14.1–F14.4 **CLOSED — APROBADAS**. Baseline validado en F14.4: `ea2d50deeb59f185fddeee142e4feb39e6f2b258`. F11.6 es la próxima etapa planificada, pero permanece **NO INICIADA / NO AUTORIZADA** hasta una nueva tarea explícita.
**Fecha de decisión:** 2026-09-27. **Cierre F14:** 2026-10-01.

Este documento es el contrato ejecutable de F14. El estado vivo continúa en `STATUS.md`, el orden decidido en `ROADMAP.md`, las reglas permanentes en `RULES.md` y la semántica implementada debe quedar actualizada en `ARCHITECTURE.md` y `DATA_MODEL.md` dentro de cada slice.

## Objetivo

Terminar y robustecer el funcionamiento ya existente antes de agregar características nuevas o dedicar una etapa al pulido visual.

F14 corrige tres huecos funcionales comprobados en la versión cerrada F13.10:

1. la identidad humana de un proyecto no es durable ni renombrable de forma independiente de su `ProjectId`;
2. el scheduler arranca automáticamente y no existe una política elegible auto/manual de inicio;
3. la ejecución puede considerarse terminada al completar los chunks aunque el MP4 final todavía no haya sido ensamblado y validado.

F11.6, pulido visual/UX, permaneció fuera de F14. Tras este cierre es la próxima etapa planificada, **NO INICIADA / NO AUTORIZADA** hasta una nueva tarea explícita.

## No-alcance

F14 no incorpora nuevos modelos, IA, cloud, multi-GPU, prioridades inteligentes, búsqueda avanzada, etiquetas/carpetas, timeline, edición de video, integración con Visor ni rediseño visual general.

No se aprovecha F14 para refactors ajenos, cambios de stack ni limpiezas oportunistas.

## Reglas comunes a todas las slices

- Inspeccionar el estado real antes de modificar producción.
- Mantener `UI → aplicación/casos de uso → dominio`.
- La UI no accede directamente a SQLite, ComfyUI ni FFmpeg/FFprobe.
- Toda persistencia nueva debe ser incremental, migrable y compatible con bases existentes.
- No modificar ni reutilizar IDs técnicos ya persistidos.
- No mover, renombrar, sobrescribir ni borrar outputs existentes por cambios administrativos.
- No crear una segunda ruta de submit a ComfyUI.
- Recovery y retry deben fallar cerradamente ante ambigüedad.
- Una slice no avanza a la siguiente hasta pruebas, evidencia, auditoría y aprobación.
- Cada slice debe actualizar los documentos autoridad afectados.
- El commit de una slice debe contener sólo su cambio lógico y su documentación.

---

## F14.1 — Nombre durable y renombrado de proyectos

### Problema verificado

En el baseline F13.10, `Project` contiene `id + defaults` y la tabla `projects` persiste `id + defaults`. La Biblioteca usa `ProjectId` como identidad visible. Un clone puede mostrarse como `Copia de <origen>` sólo durante la sesión que lo crea y, tras recargar, caer en `Proyecto generado` porque no existe nombre ni lineage durable.

### Resultado de producto

La persona trabaja con nombres humanos; los IDs técnicos permanecen internos, opacos e inmutables.

Ejemplo:

```text
Proyecto: Martina - Playa
  Ejecución #1 — succeeded
  Ejecución #2 — draft
```

### Contrato

- `ProjectId` sigue siendo la identidad técnica y nunca cambia al renombrar.
- `Project` obtiene un nombre durable separado del ID.
- El nombre se normaliza con la misma política Unicode NFC + `casefold()` ya usada por presets/plantillas.
- Los nombres de proyecto deben ser no vacíos y únicos bajo esa normalización para evitar selección humana ambigua.
- Crear un proyecto desde la UI recibe un nombre humano y genera internamente un ID opaco nuevo.
- La Biblioteca lista, ordena y selecciona por nombre visible, conservando el ID técnico sólo como identidad interna.
- Renombrar es una operación administrativa atómica y debe poder hacerse aunque existan ejecuciones históricas, queued o running: no cambia configuración, lifecycle, cola, archivos, outputs, artifacts ni recovery.
- `Crear a partir de esta` **no modifica, reemplaza ni renombra el proyecto fuente**. Inicia la creación de un segundo proyecto independiente con IDs nuevos y configuración copiada por valor.
- Antes de persistir la copia, la UI debe pedir `Nombre del nuevo proyecto`. Puede precargar una sugerencia `Copia de <nombre fuente>` (o un sufijo disponible), pero la persona puede reemplazarla por cualquier nombre válido.
- El proyecto nuevo se crea recién al confirmar ese nombre. Cancelar el diálogo/acción no crea Project, Execution, chunks, archivos ni QueueItem.
- El nombre elegido se persiste en la misma operación de creación del clone; no se implementa como “crear con nombre automático y luego renombrar”.
- El proyecto fuente queda visible y reutilizable exactamente como estaba. Source y clone pueden abrirse, editarse y ejecutarse de manera independiente dentro de sus capabilities.
- Si el nombre elegido entra en conflicto por normalización, la creación falla claramente y no deja un clone parcial. La UI debe permitir corregir el nombre e intentar nuevamente.
- Cola y demás proyecciones que muestran identidad de proyecto deben consumir el nombre durable; nunca deben exigir que la persona copie/escriba UUIDs.
- No persistir lineage ficticio de clones en esta slice. El nombre de copia no implica una relación dinámica con el origen.

### Migración

La migración debe preservar todos los `ProjectId` actuales y toda evidencia asociada.

Para proyectos existentes:

- si el ID no es un UUID válido, usar inicialmente ese ID como nombre humano;
- si el ID es UUID, usar un fallback honesto y determinista `Proyecto generado <short-id>`;
- si una normalización produjera colisión, resolverla de forma determinista con sufijo sin perder ningún proyecto.

La implementación concreta de schema se decide tras inspección, pero un campo durable nuevo exige migración versionada y pruebas desde schema 7.

### Aceptación

- Crear → cerrar app → abrir conserva nombre.
- Renombrar → cerrar → abrir conserva nombre nuevo.
- Rename no cambia `ProjectId`, `ExecutionId`, `execution_number`, QueueItem, attempts, artifacts, transitions ni paths.
- Proyectos históricos siguen abriendo.
- Clone conserva toda la semántica F13.2, recibe un nombre durable elegido antes de crearse y deja intacto al proyecto fuente.
- Flujo humano esperado: seleccionar source → `Crear a partir de esta` → introducir/confirmar nombre del nuevo proyecto → aparecen source y clone como dos proyectos distintos → abrir el clone y empezar a trabajar sobre él.
- Cancelar la elección del nombre deja exactamente el estado previo, sin clone persistido.
- Colisiones de nombres fallan claramente o se resuelven sólo donde este contrato define autosufijo.
- La UI normal no solicita ni muestra UUID como identidad primaria.

### Pruebas mínimas

- migración schema 7 desde proyectos con ID legible y UUID;
- round-trip de nombre;
- create/rename y conflictos normalizados;
- rename con draft, queued, active y terminal;
- clone + autosufijo;
- restart/reopen;
- Biblioteca y Cola proyectando nombre;
- regresión F13.1/F13.2/F13.6/F13.7/F13.10;
- `compileall` y `git diff --check`.

### Validación humana

Smoke Windows corto: crear y renombrar un proyecto; cerrar/reabrir; seleccionar un source y pulsar `Crear a partir de esta`; verificar que **antes de crear** se pide el nombre del proyecto nuevo; confirmar un nombre distinto; comprobar que source y clone quedan simultáneamente en Biblioteca, que abrir el clone permite empezar a editarlo independientemente y que ambos nombres sobreviven reinicio. También cancelar una creación y confirmar que no aparece ningún proyecto nuevo. No requiere generación real de video.

### Estado de implementación F14.1

**CLOSED — APROBADA.**

Implementado en schema 8 y en la Biblioteca real:

- nombre durable separado de `ProjectId`;
- create por nombre con ID técnico opaco;
- rename administrativo sin tocar evidencia ni IDs;
- migración 7→8 compatible;
- Biblioteca y Cola proyectando nombre humano;
- `Crear a partir de esta` pide el nombre antes de persistir, cancelar no crea nada y confirmar crea un segundo proyecto independiente;
- duplicación de Cola conserva su política automática.

Las pruebas focales y diferenciales registradas dieron `NEW_REGRESSIONS=0`. La validación humana Windows del 2026-09-28 confirmó create/rename/restart y el flujo source → nombre nuevo → clone independiente, incluida cancelación sin copia y persistencia de source+clone tras reinicio.

F14.2 queda como próxima slice y todavía no fue iniciada.

---

## F14.2 — Política de inicio de cola automática/manual

### Problema

El scheduler F13.8/F13.10 inicia automáticamente con el runtime. Esto debe seguir disponible, pero el producto necesita un modo manual que permita abrir la aplicación, revisar Biblioteca/Cola y no iniciar nuevos trabajos hasta una acción explícita.

### Contrato

- Configuración durable `auto | manual`; default `auto` para preservar comportamiento existente.
- `auto`: comportamiento actual.
- `manual`: cada arranque de la aplicación comienza con el permiso de despacho cerrado.
- En manual, abrir la app no puede reclamar un nuevo QueueItem ni producir un submit nuevo.
- `Iniciar/Reanudar cola` abre explícitamente el permiso de despacho de esa sesión.
- La política de inicio y la pausa de cola son conceptos distintos. No reutilizar `paused` para simular modo manual.
- Cambiar a manual nunca cancela un trabajo active/running.
- Recovery puede observar y reconciliar evidencia existente de forma segura, pero el modo manual no autoriza nuevos claims ni nuevos submits hasta la acción explícita.
- No se agrega `/interrupt` running.
- El setting debe sobrevivir reinicio; el permiso manual de la sesión no debe sobrevivirlo.

### Implementación F14.2

La política se guarda en un singleton SQLite propio (`queue_start_policy`), agregado por migración incremental schema 8→9 y con `auto` como valor inicial. No se reutiliza `queue_control.paused`: pausa durable y política de inicio mantienen autoridades separadas.

El permiso manual vive en un coordinador de aplicación creado nuevo para cada runtime; nace cerrado y no se escribe en SQLite. Ese coordinador serializa la lectura del gate con el claim y con los cambios de política. El claim transaccional vuelve a leer la política durable: en `manual` sólo promueve si el permiso de esta sesión ya fue abierto; en `auto` conserva el flujo actual.

La pestaña Cola expondrá `Automático / Manual` y `Iniciar/Reanudar cola`, delegados por `QueuePanel → GuiFacade → QueueDashboardUseCase`; la UI no recibe repositorios ni autoridad del scheduler. Al cambiar a manual se cierra primero el gate de sesión, sin cambiar ni cancelar el item activo. F13.9 puede observar/reconciliar evidencia existente sin submit; si el activo es una Execution virgen que requeriría `start_claimed`, queda esperando hasta el permiso explícito. Al abrir el gate, el scheduler continúa por las fronteras F13.8/F13.9 existentes.

No cambian la forma/orden/contenido de QueueItems, la semántica de pausa, el motor `StartGuiChainUseCase → ChainExecutionUseCase → SubmitBoundary`, los controles de cancelación ni el alcance visual F11.6.

### Aceptación

- Auto conserva la conducta F13.10.
- Manual + restart deja items queued sin claim/submit.
- Pulsar Iniciar/Reanudar permite exactamente un scheduler normal, sin segunda ruta.
- Pausar/reanudar conserva sus invariantes actuales.
- Un active sobreviviente nunca se duplica.
- Cambiar política no altera orden ni contenido de cola.

### Pruebas mínimas

- persistencia/migración del modo;
- auto regression;
- manual cold start;
- manual con queued;
- manual con active sobreviviente;
- interacción con pause/resume;
- no doble claim/submit;
- restart;
- regresión F13.7–F13.10;
- Qt offscreen de controles funcionales mínimos;
- `compileall` y `git diff --check`.

### Validación humana

Windows:

1. Dejar la cola vacía y cambiar el modo a `Manual`.
2. Agregar un único snapshot preparado de prueba seguro para ejecutar.
3. Cerrar y volver a abrir la aplicación; confirmar que `Manual` persiste, el item sigue `En espera`, no hay QueueItem activo y no se produjo un submit a ComfyUI.
4. Pulsar `Iniciar/Reanudar cola`; confirmar que el scheduler existente activa ese único item y comienza su cadena una sola vez.
5. Dejar que el item termine; cambiar a `Automático`, agregar otro snapshot de prueba seguro y confirmar que se activa sin pulsar `Iniciar/Reanudar cola`.

La implementación técnica F14.2 y su comparación diferencial quedan registradas en [TESTING.md](TESTING.md). La validación humana Windows del 2026-09-29 confirmó ambos modos con ComfyUI real: Manual mantuvo trabajos `En espera` hasta `Iniciar/Reanudar cola`, luego procesó secuencialmente dos proyectos de dos chunks sin duplicados; ambos quedaron `Finalizada`; el ensamblado manual existente produjo los MP4 esperados; y en Automático un nuevo trabajo arrancó sin pulsar el botón manual. Tras reinicio de Windows el gate de sesión volvió a requerir autorización y la política durable se conservó. **F14.2 CLOSED — APROBADA.**

---

## F14.3 — Ensamblado como requisito de finalización real

**Estado:** **CLOSED — APROBADA**. Implementación publicada en `4f1bd9320c005ef9dc0ac89855f10abc3f529681`.

### Problema

El producto ya tiene un adaptador de ensamblado fail-closed y validación FFprobe, pero el ensamblado está expuesto como operación separada. Completar todos los chunks no debe equivaler a completar la ejecución de producto.

### Contrato funcional

El flujo final pasa a ser:

```text
chunks completos
→ finalización pendiente
→ ensamblado del MP4 único
→ validación del MP4 final
→ evidencia durable del final
→ ejecución completada
→ QueueItem liberado
```

- Todos los chunks pueden estar correctos sin que la ejecución esté todavía completada.
- El MP4 final debe generarse automáticamente dentro de una ubicación durable y controlada por el producto. Reutilizar una convención existente si la inspección encuentra una; no depender de un diálogo manual Save As para que el scheduler pueda finalizar.
- El resultado final se valida con la frontera FFmpeg/FFprobe existente o su evolución acotada.
- Chunks y frames intermedios se preservan siempre.
- Un fallo de ensamblado no regenera chunks y no crea submits a ComfyUI.
- Debe existir evidencia durable suficiente para distinguir: pendiente, ensamblando, final válido y fallo de ensamblado.
- Retry de ensamblado actúa exclusivamente sobre la finalización y conserva los chunks ya válidos.
- Recovery después de cierre/crash reconcilia el estado de finalización antes de liberar la cola.
- Nunca se declara éxito por la mera presencia de un archivo: debe validarse procedencia/estado/ruta conforme a las autoridades existentes.
- Un destino ya existente o evidencia ambigua falla cerradamente; no se sobrescribe.
- La implementación debe elegir el modelo durable mínimo correcto después de inspeccionar el estado real. No forzar la semántica de fallo de ensamblado dentro del retry de chunks si eso puede regenerar video.
- La UI sólo debe exponer estado y acción funcional mínima de retry/export; el rediseño visual queda para F11.6.

### Implementación y resultado auditado

La implementación conserva una única autoridad durable por Execution: historial append-only `execution_assembly_attempts` (schema 9→10). El último chunk deja la ejecución `running`; `ChainExecutionUseCase` invoca automáticamente `FinalizeExecutionUseCase`, y F13.9 reingresa esa misma cadena tras recovery. Cada fuente exige Attempt/Artifact únicos, ruta contenida, SHA-256 y checkpoint N−1 exacto hacia el siguiente chunk. FFmpeg/FFprobe validan el staging antes de publicar sin sobrescritura y de persistir `Execution.succeeded`; el QueueItem no se libera sin evidencia final vigente. Los fallos preservan chunks, Attempts y transiciones; retry ejecuta sólo assembly. La UI proyecta estado y delega acciones sin invocar infraestructura.

Las pruebas automáticas focales/integradas y la comparación diferencial fueron aprobadas con `NEW_REGRESSIONS=0`; los resultados están en [TESTING.md](TESTING.md). El smoke humano Windows usó la Execution `31239b42-97c5-4f7d-ad53-70ed80565323` (proyecto `Copia de abs`, dos chunks) y el QueueItem `2bb76b0b-e681-4c8b-848e-da90fa492865`. En schema 10 quedó `AssemblyAttempt #1 succeeded`; el MP4 se reprodujo completo y el orden/continuidad se validaron visualmente. El QueueItem pasó a `finished` sólo después de evidencia final durable válida. Durante assembly hubo cero Attempts de chunk nuevos y cero submits ComfyUI. El retry de assembly fallido no se ejercitó humanamente, pero está cubierto por pruebas automáticas.

### Aceptación

- El último chunk exitoso no libera por sí solo el QueueItem como ejecución finalizada.
- Ensamblado + validación exitosos producen un final durable y recién entonces permiten estado final y avance de cola.
- Fallo de FFmpeg/FFprobe conserva todos los chunks y bloquea finalización con causa visible.
- Retry de ensamblado no toca ComfyUI, Attempts de chunks ni TransitionFrames.
- Restart en finalización pendiente/fallida conserva el punto seguro y permite continuar/reintentar sin regeneración.
- Una ejecución histórica ya válida sigue siendo legible tras migración.

### Pruebas mínimas

- happy path chunks→assembly→final;
- fallo FFmpeg;
- fallo FFprobe/validación;
- retry sólo assembly;
- restart antes/durante/después de finalización;
- destino existente y output ambiguo;
- no submit a ComfyUI durante assembly retry;
- queue no avanza antes de final durable;
- regresión F7/F8/F11.5/F13.8/F13.9/F13.10;
- pruebas reales FFmpeg/FFprobe donde corresponda;
- `compileall` y `git diff --check`.

### Validación humana

Validación humana Windows completada y aprobada con observaciones: se ejecutaron dos chunks secuencialmente; el assembly del MP4 inició automáticamente; el MP4 final abrió y se reprodujo completo; se confirmó visualmente el orden y la continuidad. La verificación técnica posterior confirmó schema 10, `AssemblyAttempt #1 succeeded` y QueueItem finalizado después de la evidencia final válida. No hubo Attempts de chunk nuevos ni submits a ComfyUI durante assembly. El retry de un fallo no se ejercitó en este smoke exitoso.

---

## F14.4 — Regresión integral y cierre funcional

**Estado:** **F14.4 — CLOSED — APROBADA. F14 — CLOSED — APROBADO.** Cierre aprobado el 2026-10-01 sobre el baseline validado `ea2d50deeb59f185fddeee142e4feb39e6f2b258`.

### Objetivo

Se demostró que F14.1–F14.3 conviven sin regresiones nuevas y queda cerrado el funcionamiento F14.

### Incluye

- migraciones hasta schema 10, nombres durables, rename/clone y Biblioteca;
- política Auto/Manual, gate de sesión cerrado tras restart y pausa independiente del modo;
- scheduler de una sola ejecución, cola, recovery/restart y ausencia de doble submit;
- chaining por último frame N−1 y retry de chunk;
- finalización automática con `AssemblyAttempt`, retry exclusivo de assembly y preservación de chunks/transiciones;
- FFmpeg/FFprobe y liberación de QueueItem sólo tras evidencia durable del MP4 final válido;
- regresión focal, regresión integrada y suite completa diferencial sobre snapshot limpio;
- smoke integrado real Windows/ComfyUI y reproducción humana completa del MP4.

### Evidencia automática

- Baterías focales: **303 ejecuciones, 302 OK, 1 skip, 0 FAIL/ERROR**. Incluyeron explícitamente `tests.test_f13_10_runtime_regression` y `tests.test_f13_10_retry_hotfix`.
- Regresión integrada única F14.1–F14.3 y dependencias relevantes: **301 tests, 300 OK, 1 skip, 0 FAIL/ERROR**.
- Suite completa canónica sobre snapshot limpio del baseline exacto, con temporales aislados: **816 tests, 8 FAIL, 6 ERROR, 2 skips**. Las 14 incidencias coinciden con deuda histórica conocida; **`NEW_REGRESSIONS=0`**.
- El primer intento de suite completa desde `git archive` es evidencia inválida: el template H3 quedó alterado byte a byte. Está excluido y no se mezcla con la corrida canónica.
- Los caminos de retry de chunk y retry exclusivo de assembly están cubiertos automáticamente. No se inyectaron fallos artificiales de chunk ni assembly en el smoke real.

### Smoke integrado real Windows/ComfyUI

La persona aprobó el flujo integrado con ComfyUI real. Se creó, renombró y clonó un proyecto y se verificó la persistencia al reabrirlo. En modo Manual se encolaron dos chunks; tras restart el gate de sesión quedó cerrado. Se comprobó que la pausa y el modo Manual son controles independientes. Al abrir el gate se ejecutó una sola cadena activa: dos chunks secuenciales, un Attempt por chunk y dos jobs ComfyUI únicos, sin doble submit. El segundo chunk encadenó desde el frame N−1 del primero.

El assembly automático produjo `AssemblyAttempt #1 succeeded`. FFprobe validó el MP4 final (H.264, 416×224, 24 fps, 112 frames; SHA-256 `bad2386f2c092657f936913ca9a2d257fc831cc6f19d1760a1eb0e8f3b27a68f`). El QueueItem se finalizó sólo después de la evidencia durable final válida. La persona reprodujo el MP4 completo y confirmó **VIDEO OK**.

El borrador nombrado vacío sin imagen inicial presentó el comportamiento histórico detectado de no poder prepararse. Se clasifica como comportamiento histórico, no como regresión F14.4, y no se corrigió en este cierre.

### No incluye

Pulido visual F11.6 ni nuevas capacidades.

### Validación humana final

Completada y aprobada: la persona reprodujo el MP4 final completo y confirmó **VIDEO OK**.

---

## Orden obligatorio

```text
F14.1 → CLOSED — APROBADA
F14.2 → CLOSED — APROBADA
F14.3 → CLOSED — APROBADA
F14.4 → CLOSED — APROBADA
F14 → CLOSED — APROBADO
F11.6 → siguiente etapa planificada; NO INICIADA / NO AUTORIZADA hasta tarea explícita
```

Codex no debe avanzar automáticamente de una slice a la siguiente.
