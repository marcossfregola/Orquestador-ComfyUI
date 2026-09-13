# Estado del proyecto

**Última actualización:** 2026-09-13
**Baseline auditada:** `main` en `1d5589c8d1e74eabb53338509944bbc14f1d94ba`
**Estado de la evolución:** planificación documental de gestión de trabajos completada; implementación no iniciada.

Este documento es la autoridad única de estado vivo. El detalle histórico de evidencia permanece en [TESTING.md](TESTING.md), [COMFYUI_INTEGRATION.md](COMFYUI_INTEGRATION.md) y Git.

## Fotografía viva verificada contra código

- F0–F10 están cerradas en la historia del proyecto. El núcleo incluye dominio y SQLite versionado, adaptador ComfyUI, perfil MiniMax H3, ejecución por chunks, retry/recovery, chaining por último frame real y ensamblado FFmpeg/FFprobe.
- F11.0–F11.5 están cerradas según la evidencia histórica. F11.6, pulido UX final, no está cerrado.
- La GUI PySide6 permite preparar y reabrir una ejecución pendiente, editar imagen inicial, referencias, prompts, chunks y parámetros, iniciar la cadena y operar recovery/retry/cancelación segura/ensamblado mediante casos de uso.
- `Project ID` es visible. `ExecutionId` es un UUID técnico global y la GUI lo conserva internamente; `execution_number` es visible, correlativo por proyecto y puede repetirse entre proyectos.
- La preparación sin `ExecutionId` crea un UUID cuando no existe candidato y reutiliza una única ejecución H3 pendiente, virgen y editable. Si hay más de una candidata, falla cerradamente y exige selección explícita.
- La reapertura rehidrata imagen inicial y preview, referencias, prompts, cantidad/orden de chunks, parámetros globales y overrides. No crea otra ejecución al volver a preparar la candidata seleccionada.
- SQLite está en schema 3. Persisten `Project`, `Execution`, `Chunk`, `Attempt`, errores, artefactos, transiciones y `execution_number`; todavía no existen tablas ni casos de uso de cola, presets, plantillas o listado de proyectos.
- ComfyUI continúa detrás de adaptadores y Workflow Profile/bindings. La cola propia decidida para la próxima evolución no existe y no debe confundirse con la queue interna de ComfyUI.

## F12 — first frame como referencia primaria

El código actual contiene la opción global durable `first_frame_as_primary_reference`, default `false`, incompatible con `also_ref_first_frame=true`. Cuando está activa, el mismo IMAGE efectivo de `first_frame` ocupa la primera referencia y las referencias del usuario conservan orden denso.

La fase no se considera cerrada documentalmente en este baseline. La auditoría directa de GitHub encontró una inconsistencia de integridad previa a esta planificación:

- el blob remoto `src/orquestador/profiles/artifacts/minimax_h3_api_template.v1.json` tiene SHA-256 `9F6B5785483D8FCC2C2ADBD0F574DD558BE1F605F2A8D64208AB86FC6FF4E508`;
- `H3_API_TEMPLATE_SHA256` y el manifest esperan `4DCFB2783391FBA0C5090B8A78765E46AA26B9A2215B948664F0D20341EC8F25`;
- por lo tanto `load_api_template()` falla cerradamente desde un checkout limpio de `main`.

No se corrigió porque este trabajo es exclusivamente documental. La primera etapa de implementación debe restablecer una baseline limpia y verificable antes de agregar funcionalidad.

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

Ejecutar únicamente **F12.1 — Restablecimiento de baseline verificable**, definida en [ROADMAP.md](ROADMAP.md). No comenzar F13 hasta que el checkout remoto limpio cargue el template canónico y pasen las pruebas focales y la regresión Windows acordada.

## No verificado en esta auditoría

- No se ejecutó ComfyUI real, FFmpeg/FFprobe real ni validación visual.
- La regresión completa no pudo considerarse válida en el runtime Linux de Work: además del hash inválido, faltó PySide6 y varias pruebas son Windows/environment-specific. El resultado no sustituye la validación Windows.
- No se modificó código, schema, workflow ni runtime.
