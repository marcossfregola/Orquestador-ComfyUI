# Roadmap

Este documento contiene trabajo decidido. Las ideas no comprometidas pertenecen a [BACKLOG.md](BACKLOG.md). El estado vivo está sólo en [STATUS.md](STATUS.md).

## F0–F10 — Fundación y primer release técnico

**CLOSED.** Quedaron implementados y verificados progresivamente: fundación, spike real, dominio y persistencia, adaptador ComfyUI, Workflow Profile H3, pipeline robusto, recovery/retry, chaining, ensamblado, GUI y E2E real. La evidencia detallada se conserva en Git y [TESTING.md](TESTING.md).

## F11 — GUI operativa incremental

- F11.0 contrato único de configuración: **CLOSED**.
- F11.1 preparación y generación desde GUI: **CLOSED**.
- F11.2 gestión visual de imagen inicial y referencias: **CLOSED / HUMAN-VALIDATED**.
- F11.3 configuración H3 ampliada: **CLOSED**.
- F11.4 editor de chunks: **CLOSED**.
- F11.5 operación, recovery y resultados: **CLOSED**.
- F11.6 pulido UX: **OPEN**, pospuesto hasta integrar la gestión de trabajos para evitar rehacer la navegación.

## F12 — first frame como referencia primaria

**IMPLEMENTED, F12.1 RESUELTA — LISTA PARA AUDITORÍA.** El código expone `first_frame_as_primary_reference` y F12.1 verificó, desde `main` en `ac77bc892f02641eaa6c4db7b6431ce25be98ae7`, que el template API versionado, la constante y el manifest coinciden en el SHA-256 canónico `4DCFB2783391FBA0C5090B8A78765E46AA26B9A2215B948664F0D20341EC8F25`. `load_api_template()` funciona; F10 pasó 19/19 en rerun aislada y persistencia 14/14. No se requirió cambio de workflow, topología ni bindings.

### F12.1 — Cierre documental de baseline verificable

**Objetivo:** corregir la afirmación documental falsa de una inconsistencia de hash y dejar registrada una baseline reproducible antes de sumar nuevas entidades o migraciones.

**Incluye:** verificar cuál artefacto es canónico, constante y manifest; ejecutar pruebas focales F4/F6/F7/F11/F12 y persistencia con entorno Windows; actualizar exclusivamente la evidencia documental de cierre.

**No incluye:** cola, borradores nuevos, clonación, defaults, presets, plantillas, biblioteca de proyectos, cambios UX ni cambios funcionales al workflow.

**Áreas modificadas:** sólo documentación de evidencia. La verificación confirmó que `src/orquestador/profiles/artifacts/`, `src/orquestador/profiles/minimax_h3.py` y el manifest no requieren modificación.

**Aceptación:** `load_api_template()` funciona desde checkout limpio; los tres valores de integridad coinciden; no cambia la topología/binding aprobado; pruebas focales y regresión Windows pasan; cualquier prueba omitida queda identificada.

**Validación humana:** no requerida salvo que la investigación demuestre un cambio funcional del workflow.
**Dependencias:** ninguna.
**Cierre:** resuelto documentalmente y listo para auditoría independiente; sin commit, push ni avance automático a F13.0.

## F13 — Gestión durable de trabajos

F13 incorpora borradores, reutilización, configuración guardada, biblioteca y cola de ejecución sobre el motor existente. Las slices son acumulativas y cada una debe poder cerrarse en un hilo independiente.

### F13.0 — Contratos de gestión y migración base

**Objetivo:** introducir los contratos mínimos que usarán las slices siguientes sin cambiar todavía la experiencia de producto.

**Incluye:** predicado único de `editable virgin execution`; puertos de listado/consulta; modelo durable `QueueItem` y control singleton de cola; diseño ejecutable de migración desde schema 3; invariantes de unicidad y compatibilidad de lectura.

**No incluye:** UI, scheduler, autoarranque, clonación, presets o plantillas.

**Áreas probables:** dominio, puertos/casos de uso, `persistence/sqlite.py`, tests de dominio/persistencia.

**Aceptación:** una base schema 3 migra sin pérdida; datos actuales reabren iguales; un `QueueItem` sólo referencia una ejecución existente y elegible; existe como máximo un item activo; estados y transiciones ilegales fallan cerradamente.

**Tests:** unidad de invariantes; migración 3→4; round-trip; corrupción/foreign keys; compatibilidad con bases actuales.
**Validación humana:** no.
**Dependencias:** F12.1 cerrada.
**Cierre:** pruebas focales + regresión, auditoría y aprobación.

### F13.1 — Borradores y listado de proyectos/ejecuciones

**Objetivo:** formalizar operaciones de crear, guardar, cerrar, listar y reabrir borradores usando la ejecución pendiente virgen existente.

**Incluye:** casos de uso explícitos; listado resumido de proyectos y ejecuciones; clasificación derivada `draft/queued/running/succeeded/failed/cancelled`; selección sin ambigüedad.

**No incluye:** UI completa de biblioteca, clonación ni scheduler.

**Áreas probables:** aplicación, repositorio SQLite, facade/snapshots y tests.

**Aceptación:** cerrar la app no pierde un borrador; reabrirlo restaura toda la configuración; guardar no crea otra ejecución; una ejecución con runtime no puede volver a ser borrador editable.

**Tests:** create/save/reopen; múltiples borradores; clasificación; protección de históricos; regresión de Prepare.
**Validación humana:** no, salvo smoke GUI mínimo si se expone una acción temporal.
**Dependencias:** F13.0.
**Cierre:** pruebas focales + regresión, auditoría y aprobación.

### F13.2 — Crear a partir de este

**Objetivo:** crear un proyecto y una ejecución borrador nuevos e independientes desde configuración reutilizable anterior.

**Incluye:** copiar profile, inputs, referencias, prompts, chunks, parámetros globales y overrides editables reales; nueva identidad técnica y `execution_number` propio.

**No incluye:** attempts, prompt IDs, outputs, artifacts, errores, transiciones, timestamps/runtime, queue item ni recovery heredado.

**Áreas probables:** caso de uso de clonación, dominio, persistencia/listado y tests.

**Aceptación:** origen queda byte/lógicamente inalterado; copia es editable; no comparte IDs ni evidencia runtime; funciona desde draft, completado y fallido cuando la configuración fuente es válida.

**Tests:** matriz de copia/inhibición; independencia posterior; rutas de inputs contenidas; rollback atómico.
**Validación humana:** no.
**Dependencias:** F13.1.
**Cierre:** pruebas focales + regresión, auditoría y aprobación.

### F13.3 — Defaults globales

**Objetivo:** persistir los valores con los que nace un proyecto nuevo.

**Incluye:** parámetros técnicos públicos reales de `GenerationConfig`; lectura/escritura validada; aplicación sólo al crear un borrador nuevo; precedencia `global defaults → configuración de ejecución → override de chunk`.

**No incluye:** mutar proyectos existentes, presets con nombre ni parámetros no soportados.

**Áreas probables:** configuración, persistencia, casos de uso, composición y tests.

**Aceptación:** cambiar defaults afecta sólo creaciones posteriores; snapshots existentes no cambian; valores inválidos fallan cerradamente.

**Tests:** precedencia, persistencia/reopen, no retroactividad, migración/default inicial.
**Validación humana:** mínima cuando se agregue UI en una slice posterior.
**Dependencias:** F13.1; puede ejecutarse después de F13.2 para mantener el orden lineal.
**Cierre:** pruebas focales + regresión, auditoría y aprobación.

### F13.4 — Presets técnicos con nombre

**Objetivo:** CRUD durable de conjuntos técnicos reutilizables.

**Incluye:** crear, aplicar, renombrar, actualizar, eliminar y opcionalmente marcar uno por defecto; sólo parámetros técnicos soportados.

**No incluye:** imágenes, referencias, prompts, chunks, runtime u outputs.

**Áreas probables:** dominio/configuración, persistencia, casos de uso y tests.

**Aceptación:** aplicar copia valores al borrador y luego queda editable; actualizar/eliminar un preset no altera ejecuciones existentes; nombres e identidad son inequívocos.

**Tests:** CRUD, default único, snapshot por copia, conflictos y validación.
**Validación humana:** no hasta su integración GUI.
**Dependencias:** F13.3.
**Cierre:** pruebas focales + regresión, auditoría y aprobación.

### F13.5 — Plantillas de prompts/chunks

**Objetivo:** CRUD durable de plantillas con nombre, cantidad/orden de chunks y prompt por chunk.

**Incluye:** crear, aplicar, actualizar, renombrar, duplicar y eliminar; adaptar atómicamente la secuencia editable del borrador.

**No incluye:** parámetros técnicos, imágenes, referencias, runtime u outputs.

**Áreas probables:** dominio, caso de uso de edición de secuencia, persistencia y tests.

**Aceptación:** aplicar ajusta cantidad, orden y prompts y deja la ejecución editable; no puede aplicarse a una ejecución bloqueada; fallo revierte toda la operación.

**Tests:** cardinalidad, orden, prompts, duplicación, rollback y bloqueo runtime.
**Validación humana:** no hasta GUI.
**Dependencias:** F13.1; se ejecuta después de F13.4 para conservar el orden lineal.
**Cierre:** pruebas focales + regresión, auditoría y aprobación.

### F13.6 — Biblioteca e integración GUI de preparación

**Objetivo:** permitir localizar trabajos, abrir borradores/históricos, clonar y administrar defaults/presets/plantillas desde una UI simple.

**Incluye:** vista de proyectos/ejecuciones con estados derivados; abrir; `Crear a partir de este`; controles mínimos para F13.3–F13.5; ocultar UUID técnico salvo diagnóstico.

**No incluye:** etiquetas, carpetas sofisticadas, búsqueda avanzada, cloud o colaboración.

**Áreas probables:** facade/snapshots, `ui/main_window.py` o componentes dedicados, workers y pruebas Qt.

**Aceptación:** el usuario puede crear/reabrir/editar un borrador, consultar un finalizado y crear una copia sin escribir IDs técnicos manualmente.

**Tests:** facade y Qt offscreen; selección estable; acciones/capabilities; no acceso directo UI→SQLite.
**Validación humana:** sí, Windows.
**Dependencias:** F13.2–F13.5.
**Cierre:** pruebas focales + regresión, validación humana, auditoría y aprobación.

### F13.7 — Operaciones de cola durable

**Estado:** CLOSED — 2026-09-13.

**Objetivo:** permitir encolar y administrar ejecuciones sin iniciar automáticamente todavía.

**Incluye:** enqueue, selección, reordenamiento, quitar, duplicar mediante clonación, saltar pendiente y pausa/reanudación del control; orden transaccional durable.

**No incluye:** scheduler ni submit automático.

**Áreas:** contratos `QueueItem` ya fundados en F13.0, casos de uso, SQLite y tests; esta slice backend no agrega facade ni UI.

**Aceptación:** orden sobrevive reinicio; sólo ejecuciones elegibles entran; no hay duplicado activo de la misma ejecución; running queda protegido; quitar/saltar no destruye proyecto ni outputs.

**Tests:** CRUD/orden/concurrencia SQLite, conflictos, reinicio, integridad referencial.
**Validación humana:** no antes de la UI de cola.
**Dependencias:** F13.0 y F13.1 para la cola/draft, y F13.2 para la duplicación por el clone canónico. F13.6 no es una dependencia técnica: su referencia anterior era sólo orden lineal y F13.7 se cerró como slice backend independiente, sin implementar UI.
**Cierre:** pruebas focales + regresión, auditoría y aprobación — completados.

### F13.8 — Scheduler de una sola ejecución

**Objetivo:** hacer que una única autoridad promueva el próximo item y reutilice el motor actual.

**Incluye:** selección FIFO reordenable; claim transaccional; una ejecución activa; llamada al caso de uso existente; promoción del siguiente sólo tras estado terminal/reconciliado; pausa sin cancelar running.

**No incluye:** multi-GPU, prioridades automáticas, paralelismo ni `/interrupt` running.

**Áreas probables:** aplicación/scheduler, composición/background worker, persistencia y tests.

**Aceptación:** nunca hay dos ejecuciones activas; finalizar una habilita exactamente la siguiente; pausa impide nuevos claims; errores no producen doble submit.

**Tests:** unidad con fakes; carreras de claim; éxito/fallo; pausa; idempotencia y ausencia de doble submit.
**Validación humana:** smoke Windows con backend simulado.
**Dependencias:** F13.7 y motor de ejecución/recovery existente.
**Cierre:** pruebas focales + regresión, smoke humano, auditoría y aprobación.

### F13.9 — Recovery y reconciliación de cola

**Objetivo:** sobrevivir cierre/crash/reinicio sin abandonar ni duplicar trabajos.

**Incluye:** reconciliar primero el item activo con ejecución durable, artifacts y ComfyUI observable; continuar/retry/manual review conforme a contratos existentes; recién después considerar el siguiente item.

**No incluye:** limpiar outputs, retry ilimitado, asumir éxito por ausencia de error ni auto-saltar ambigüedades.

**Áreas probables:** scheduler, recovery, adaptador ComfyUI, persistencia y tests E2E controlados.

**Aceptación:** activo sobreviviente se reconcilia antes de otro claim; job existente reutiliza `external_job_ref`; un estado ambiguo bloquea sin submit; un pending nunca iniciado permanece en cola.

**Tests:** crash antes/después de claim, submit y terminalización; ComfyUI reiniciado; UI ausente; discrepancias durable/artefactos; exactamente un submit.
**Validación humana:** sí, Windows + ComfyUI real en escenario acotado.
**Dependencias:** F13.8.
**Cierre:** matriz de recovery, evidencia real acotada, regresión, auditoría y aprobación.

### F13.10 — UX de cola y cierre integrado

**Objetivo:** completar la operación cotidiana y absorber el pulido pendiente de F11.6 sin rehacer dos veces la navegación.

**Incluye:** panel de cola, estados reales, selección/edición permitida, reordenar/quitar/saltar, pausa/reanudar, accesos a biblioteca/resultados, mensajes accionables y pulido visual pendiente.

**No incluye:** estimaciones inventadas, multi-GPU, etiquetas avanzadas, cloud o automatización inteligente.

**Áreas probables:** UI, facade, workers, snapshots y documentación.

**Aceptación:** preparar varios trabajos, encolarlos, cerrar/reabrir, procesarlos uno por uno y consultar resultados desde Windows; controles reflejan capabilities reales.

**Tests:** regresión completa, Qt offscreen, E2E controlado de cola/restart y evidencia de no doble submit.
**Validación humana:** sí, Windows y una cadena real representativa.
**Dependencias:** F13.6–F13.9.
**Cierre:** pruebas, evidencia real, validación humana, auditoría y aprobación formal de F13.

## Regla de avance

Cada slice sigue: **inspección → diagnóstico/diseño → implementación → pruebas → evidencia → auditoría → validación humana cuando corresponda → aprobación → commit**. No se inicia automáticamente la siguiente slice.
