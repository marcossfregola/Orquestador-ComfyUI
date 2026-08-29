# Estado del proyecto

**Última actualización:** 2026-08-28
**Fase:** F3 — Adaptador ComfyUI y observación (IN PROGRESS)
**Estado:** F3-1 checkpointed (`14f8b025...`); F3-2 checkpointed (`bba0e191...`); F3-3 implementado/corregido; F3-4 **CLOSED — APROBADA CON OBSERVACIONES** (baseline `bb58d6b...`); F3-5 corregido e implementado, pendiente de esta auditoría/checkpoint; F3 no está cerrada

## Fotografía viva

- (Histórico F1) F1 tiene evidencia controlada de B2–B7 y C1–C3 contra la instalación real de ComfyUI.
- (Histórico F1) C3 recibió validación humana explícita: la unión Chunk 1 → Chunk 2 fue reportada como perfecta e imperceptible.
- (Histórico de F1) No se implementó código ni infraestructura de producción en ese checkpoint.
- La consolidación documental de este checkpoint está sin commit; el estado Git posterior debe leerse en la evidencia final.
- (Histórico de F1) F1 no implementaba F2/F3/F4; la evidencia de spike quedó formalmente cerrada en ese checkpoint.
- F2: **CLOSED — APPROVED** (cierre 2026-08-28).
- F3-3 implementa correlación lógica genérica sobre `HistoryResult`; no incluye output_root, validación física, fixture F1 completo ni validación live.
- F2 incluye modelo ejecutable backend-agnóstico, persistencia SQLite v1, historial append-only, validación de grafo/procedencia y reconciliación pura determinista. No incluye adaptador ComfyUI, FFmpeg productivo, bindings/profile H3, GUI, orquestación productiva ni validación visual.
- F3: IN PROGRESS — F3-1 y F3-2 checkpointed; F3-3 implementado/corregido, pendiente de aprobación/checkpoint; no está cerrada.

F3 Unidad 1 (corrección R3): adaptador HTTP y contrato fail-closed implementados; focused suite 38/38 verde. Evidencia live separada en COMFYUI_INTEGRATION.md.

## Baseline conocido

La base documental vigente antes de esta consolidación fue:

- raíz de trabajo y raíz Git: `C:\Codex\Orquestador-ComfyUI`;
- rama: `main`;
- HEAD verificado: `ecb33835b3378573b192c7fa094c2c5dfe6d953a`;
- workflow UI canónico: `Prueba Orquestador.json`;
- SHA-256 del workflow: `3070EB659A0BDBEB3D8392B0D203F6B4B86409709A20143280473A12C44BA4A7`.

La evidencia operativa de F1 y el estado Git posterior a esta consolidación se detallan en [COMFYUI_INTEGRATION.md](COMFYUI_INTEGRATION.md), [TESTING.md](TESTING.md) y la auditoría final de este cambio.

## Completado en F0

- Visión, problema, primer release, alcance y no-alcance.
- Dirección arquitectónica y fronteras núcleo/infraestructura.
- Semántica del dominio, estados, checkpoints, retry, recovery y reconciliación conceptuales.
- Responsabilidades de ComfyUI, Workflow Profiles, bindings e hipótesis F1.
- Responsabilidades conceptuales de FFmpeg/FFprobe y background jobs.
- Estrategia de pruebas, reglas de desarrollo, entorno y roadmap F0–F10.

## Completado en F1 hasta este checkpoint

- Derivación del prompt API desde el workflow UI sin modificarlo.
- Ejecuciones controladas B2–B7: override de prompt, referencia, upload, first frame y proyecto integrado.
- Extracción del último frame decodificado por índice con prueba pixel a pixel.
- Un chaining real Chunk 1 → Chunk 2 y ensamblado de validación con `-c copy`.
- Validación humana del primer seam.

## Evidencia adicional y límites explícitos

- ComfyUI core `0.33.0` en `127.0.0.1:8188`; endpoints nativos, prompt API derivada, POST `/prompt`, queue/history, WebSocket de ejecución/progreso, upload y FFmpeg/FFprobe fueron verificados.
- Correlación determinista: `prompt_id → history → SaveVideo node 92 (filename/subfolder/type) → archivo físico`.
- H3 observado: `LoadImage114→ImageCropV2 127→ImageScaleToTotalPixels119→GetImageSize120→H3 129 first_frame`; width/height desde 120; seis `ref_image_0..5` densas; parámetros prompt/length/steps/seed/sampler/scheduler/FPS/ref_image_size; salida node 92.
- C1 probó frame exacto `N-1` y equivalencia pixel a pixel mediante `framemd5`; C2 probó chaining real de dos chunks con upload y continuidad hash; C3 sólo permite concat técnico `-c copy` y validación humana del seam de ese caso.
- Tarea `orquestador-f1-e1-pending-delete-003`: A `f66c16d3-a699-47d8-a8ed-99085fa96cc9` running; B `99632fb4-7c20-4cba-8947-feebed5054ef` pending; B eliminado por `POST /queue` HTTP 200, history `{}`, sin output; A interrumpido por `/interrupt`; queue final vacía; repositorio sin cambios.

Cancelación básica de un job running mediante `/interrupt` queda DEMONSTRATED como spike. Cancelación productiva por job, reconexión, crash recovery, reconciliación de huérfanos, retry y seguridad de producción quedan DEFERRED.

## Pendiente para fases posteriores

- Recovery/retry ante crash, cierre, reinicio y jobs huérfanos.
- Recovery contra backend, cancelación productiva y reconciliación de jobs huérfanos.
- Cancelación productiva, concurrencia segura y comportamiento de reconexión.
- Chaining de mayor longitud, ensamblado productivo y pruebas de fallo.
- F2: **CLOSED — APPROVED** (cierre 2026-08-28).
- F4: contrato versionado del Workflow Profile H3 y tests de compatibilidad/bindings.
- F6/F7/F8/F9: recovery, chaining largo, ensamblado productivo y GUI.

## Criterio de cierre

(Histórico F1) El trabajo técnico y la documentación del spike cumplieron su criterio de cierre. No autoriza implementación productiva ni adelanta F2–F4.
# F3-4 status

F3-1/F3-2/F3-3 remain checkpointed. F3-4 is CLOSED / APROBADA CON OBSERVACIONES at baseline `bb58d6b...`; F3-5 is corrected and implemented pending this audit/checkpoint. Global F3 remains IN PROGRESS. Pending deletion is locally tested only; controlled live validation is still required. The F1 `/interrupt` result remains historical spike evidence, not a production capability.
### F3-5 application bridge

Implemented the generic ComfyUI backend-job application/reconciliation bridge. It durably binds the existing `BackendJobRef`, maps queue/history/observation evidence conservatively, invokes pure F2 reconciliation, and applies only explicit actions. Backend cancellation evidence never directly changes domain lifecycle. Correlated output descriptors remain logical evidence only; physical artifact validation/output-root policy are out of scope. F3 remains IN PROGRESS pending controlled live validation and global closure.
