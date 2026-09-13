# Estado del proyecto

**Última actualización:** 2026-09-13
**Baseline publicada anterior a este cierre:** `origin/main` en `b629f097a9cde6a6f03b69ae75720b0e367df271`; Git es la autoridad del SHA vigente.
**Estado de la evolución:** F13.0, F13.1, F13.2, F13.3 y F13.4 están implementadas, aprobadas y cerradas. F13.5 — plantillas de prompts/chunks — es la próxima etapa planificada y no está iniciada; F13.6 tampoco está iniciada.

Este documento es la autoridad única de estado vivo. El detalle histórico de evidencia permanece en [TESTING.md](TESTING.md), [COMFYUI_INTEGRATION.md](COMFYUI_INTEGRATION.md) y Git.

## Fotografía viva verificada contra código

- F0–F10 están cerradas en la historia del proyecto. El núcleo incluye dominio y SQLite versionado, adaptador ComfyUI, perfil MiniMax H3, ejecución por chunks, retry/recovery, chaining por último frame real y ensamblado FFmpeg/FFprobe.
- F11.0–F11.5 están cerradas según la evidencia histórica. F11.6, pulido UX final, no está cerrado.
- La GUI PySide6 permite preparar y reabrir una ejecución pendiente, editar imagen inicial, referencias, prompts, chunks y parámetros, iniciar la cadena y operar recovery/retry/cancelación segura/ensamblado mediante casos de uso.
- `Project ID` es visible. `ExecutionId` es un UUID técnico global y la GUI lo conserva internamente; `execution_number` es visible, correlativo por proyecto y puede repetirse entre proyectos.
- La preparación sin `ExecutionId` crea un UUID cuando no existe candidato y reutiliza una única ejecución H3 pendiente, virgen y editable. Si hay más de una candidata, falla cerradamente y exige selección explícita.
- La reapertura rehidrata imagen inicial y preview, referencias, prompts, cantidad/orden de chunks, parámetros globales y overrides. No crea otra ejecución al volver a preparar la candidata seleccionada.
- SQLite está en schema 6. F13.0 añadió por migración incremental las fundaciones durables `queue_items` y el singleton `queue_control`; F13.3 añadió el singleton versionado `global_defaults`; F13.4 añadió `technical_presets`, sin reescribir las filas históricas de `Project`, `Execution`, `Chunk`, `Attempt`, errores, artefactos, transiciones ni `execution_number`.
- F13.3 persiste exactamente los ocho parámetros técnicos públicos de Global Defaults y los materializa sólo al crear un borrador nuevo. F13.4 persiste presets técnicos nombrados y normalizados que contienen esos mismos ocho campos: su `default` es sólo metadata y nunca se aplica automáticamente. Aplicar un preset copia sus valores a un borrador realmente editable, sin guardar referencia al preset; cambios o borrado posteriores no son retroactivos. F13.2 clone, creación normal, Prepare, Start y recovery no consultan presets. F13.5 y F13.6 continúan planificadas. ComfyUI continúa detrás de adaptadores y Workflow Profile/bindings; su queue interna no es la autoridad durable del producto.

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

F13.5 — plantillas de prompts/chunks — es la próxima etapa planificada y no está iniciada. F13.6 y las slices posteriores tampoco fueron iniciadas como parte del cierre F13.4.

## No verificado en el cierre F13.4

- No se ejecutó ComfyUI real, FFmpeg/FFprobe real ni validación visual.
- No se repitió una regresión completa ni se revalidó el runtime Linux histórico; la evidencia nueva es la batería focal documentada en `TESTING.md`, no la sustituye.
- La suite focal de F11.2A/crop conserva tres errores de fixture: el `Mock` no define `execution_id` y PySide6 rechaza ese `Mock` en `QLineEdit.setText`. `ui/main_window.py` y ese test no cambiaron desde el baseline F13.2; no es un defecto de F13.4 ni se corrigió fuera de alcance.
- No se ejecutó F13.5, F13.6, UI de presets, ni cambios de workflow/runtime.
