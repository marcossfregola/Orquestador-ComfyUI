# Estado del proyecto

**Última actualización:** 2026-08-31
**Fase:** F9 — GUI del primer release **CLOSED — APPROVED WITH OBSERVATIONS** (auditoría independiente 056); F10 **NOT STARTED**
**Estado:** F3 overall **CLOSED / COMPLETED; LIVE VALIDATED**; F4 **CLOSED — APPROVED**; F5 **CLOSED — APPROVED**; F6 **CLOSED — APPROVED** (2026-08-30); F7 **CLOSED — APPROVED** (2026-08-31).

## Fotografía viva

- (Histórico F1) F1 tiene evidencia controlada de B2–B7 y C1–C3 contra la instalación real de ComfyUI.
- (Histórico F1) C3 recibió validación humana explícita: la unión Chunk 1 → Chunk 2 fue reportada como perfecta e imperceptible.
- (Histórico de F1) No se implementó código ni infraestructura de producción en ese checkpoint.
- La consolidación documental de este checkpoint está sin commit; el estado Git posterior debe leerse en la evidencia final.
- (Histórico de F1) F1 no implementaba F2/F3/F4; la evidencia de spike quedó formalmente cerrada en ese checkpoint.
- F2: **CLOSED — APPROVED** (cierre 2026-08-28).
- F3-3 implementa correlación lógica genérica sobre `HistoryResult`; el mapper F3 integra validación física explícita y observación de artefacto.
- F2 incluye modelo ejecutable backend-agnóstico, persistencia SQLite v1, historial append-only, validación de grafo/procedencia y reconciliación pura determinista. No incluye adaptador ComfyUI, FFmpeg productivo, bindings/profile H3, GUI, orquestación productiva ni validación visual.
- F3: **CLOSED / COMPLETED — LIVE VALIDATED**. Auditoría global independiente 096: cero bloqueadores técnicos; sólo sincronización documental.
- F6: recovery/reanudación durable de un chunk implementado con `ResumeExecutionUseCase`, persistencia SQLite v1, observación fresca por `Attempt.external_job_ref`, retry único y completion durable. El cierre de esta fase se documenta abajo; no implica E2E nuevo contra ComfyUI.

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
- H3 observado: `LoadImage114→ImageCropV2 127→ImageScaleToTotalPixels119→GetImageSize120→H3 129 first_frame`; width/height desde 120; seis `ref_image_0..5` densas; API F4 soporta prompt, first_frame, width, height, length, ref_image_size, also_ref_first_frame y FPS en node 148; steps/seed/sampler/scheduler no están expuestos por la evidencia canónica; salida node 92.
- C1 probó frame exacto `N-1` y equivalencia pixel a pixel mediante `framemd5`; C2 probó chaining real de dos chunks con upload y continuidad hash; C3 sólo permite concat técnico `-c copy` y validación humana del seam de ese caso.
- Tarea `orquestador-f1-e1-pending-delete-003`: A `f66c16d3-a699-47d8-a8ed-99085fa96cc9` running; B `99632fb4-7c20-4cba-8947-feebed5054ef` pending; B eliminado por `POST /queue` HTTP 200, history `{}`, sin output; A interrumpido por `/interrupt`; queue final vacía; repositorio sin cambios.

**HISTORICAL SPIKE:** la interrupción running mediante `/interrupt` es sólo evidencia histórica. F3-4 final es pending-only LIVE VALIDATED en ComfyUI 0.33.0 aislado: un único `POST /queue` dirigido, sin `/interrupt` ni clear; confirmación backend sola no equivale a `Lifecycle.CANCELLED`.

## Cierre F5 (2026-08-30)

F5 **CLOSED — APPROVED**; Slices 1, 2, 3 y 4A completadas/auditadas. Slice4A 13/13; todos F5 39/39; regresión 390/390 en dos corridas consecutivas independientes, ambas OK. A–L explícitos; A/B/C/H/I/L usan SQLiteProjectRepository real con close + nueva instancia + reopen; A/B verifican OUTPUT Artifact + TransitionFrame N-1. No hubo ComfyUI real, FFmpeg real donde hubo fakes, ni validación visual/UX. ResourceWarnings históricos no son failures. F6 se valida y cierra en la sección siguiente.

## Cierre F6 (2026-08-30)

F6 **CLOSED — APPROVED** después de pasar la suite enfocada `python -B -m unittest tests.test_f6_recover_execution -v` (**28/28 OK**) y la regresión oficial `python -B -m unittest discover -s tests` (**418/418 OK**). La regresión emitió `ResourceWarning` de conexiones/archivos sin cerrar en pruebas existentes, pero no tuvo failures, errors ni skips; se conservan como warnings y no se ocultan.

Implementado: reapertura SQLite y reconciliación; recuperación de `Attempt` y `external_job_ref`; estados backend `QUEUED`, `RUNNING`, `COMPLETED` y `FAILED`; persistencia durable del error; retry único con segundo Attempt y sin Attempt 3; preservación de IDs/referencias; output/evidence, `Artifact` `OUTPUT`, `TransitionFrame` N-1; y resumes repetidos idempotentes con comportamiento fail-closed ante inconsistencias.

Probado automáticamente con SQLite real (save → close → nueva instancia → reopen), mocks de backend y la frontera de completion F5. No se ejecutó una nueva generación ni un E2E real contra ComfyUI, y no hubo validación visual. El ensamblado y la recuperación/orquestación E2E contra ComfyUI real quedan fuera del cierre F7; F8 se cerró posteriormente y F9 se cerró documentalmente el 2026-08-31.

## Pendiente para fases posteriores

- Recovery/retry multi-chunk, recuperación de cadena y propagación entre chunks: **F7 CLOSED — APPROVED** (2026-08-31).
- Recovery/orquestación E2E contra ComfyUI real y jobs huérfanos más allá del contrato durable de un chunk.
- Semántica de cancelación a nivel de pipeline/dominio, concurrencia segura y comportamiento de reconexión; la cancelación backend pending-only de F3-4 está cerrada y live validada.
- Chaining de mayor longitud, ensamblado productivo y pruebas de fallo.
- F2: **CLOSED — APPROVED** (cierre 2026-08-28).
- F4: implementación del perfil H3, bindings centralizados, artefactos canónicos sanitizados y fixture durable versionado completados; **CLOSED — APPROVED**. La validación estática contra bytes canónicos y las suites de cierre quedaron en verde; no se afirma una nueva ejecución de generación ni validación visual.
- F9: **CLOSED — APPROVED WITH OBSERVATIONS**. GUI PySide6 lanzable, composición/entrypoint, fachada, workers, snapshot durable/capabilities y acciones conectadas; retry conserva Attempt 1 y limita a Attempt 2; assembly cruza la frontera F8; cancelación fail-closed. Evidencia: composición 12/12, F9 restante 5/5, histórica 3/3, F6/F7 47/47, F5/F8 51/51, completa 460/460; syntax/diff/temp harness PASS. No se realizó validación visual humana ni E2E real de ComfyUI; F10 sigue NOT STARTED.

## F8 — ensamblado final

Implementados `FFmpegAssemblyAdapter` y `AssembleExecutionUseCase`. Contrato: >=2 chunks, destino MP4, `-c copy` sólo para firmas compatibles, fallback explícito `reencode`, FFprobe final antes de publicación create-if-absent sin overwrite, y preservación de chunks/intermedios.

Auditoría aprobada `orquestador-f8-evidence-audit-037`: FFmpeg/FFprobe reales 8.1.1; concat copy PASS a `out copy's file.mp4` (2640 bytes, ffprobe válido) y reencode PASS a `out reencode's file.mp4` (1875 bytes, ffprobe válido), incluyendo nombres con espacios y apóstrofes. Se verificaron hashes fuente sin cambios, destino existente preservado, carrera de destino sin overwrite, fallo de probe pre-publicación sin destino, rechazo de destinos unsupported/suffixless, limpieza de temporales propios con sentinel preservado; focused F8 **6/6 PASS**, suite completa **443/443 PASS**, compileall PASS y `git diff --check` PASS. No se realizó validación visual humana ni E2E de ComfyUI; no eran requeridos para esta slice técnica.

## Criterio de cierre

(Histórico F1) El trabajo técnico y la documentación del spike cumplieron su criterio de cierre. No autoriza implementación productiva ni adelanta F2–F4.
# F3 closure status

F3-1/F3-2/F3-3 remain checkpointed. F3-4 is CLOSED and LIVE VALIDATED with pending-only targeted delete. F3-6 validates caller-supplied trusted root with containment/path-escape protections. F3-7 live validation completed health, submit, production WS, execution_success, exact history, deterministic logical descriptor and physical file. Final `ArtifactObservation` seam is fail-closed; durable completion/artifact persistence was closed in F5. F4/H3 bindings are **CLOSED — APPROVED** after durable canonical-fixture and suite validation; F5 is **CLOSED — APPROVED** (Slice4A completada, auditada y aprobada).
### F3-5 application bridge

Implemented the generic ComfyUI backend-job application/reconciliation bridge. It durably binds the existing `BackendJobRef`, maps queue/history/observation evidence conservatively, invokes pure F2 reconciliation, and applies only explicit actions. Backend cancellation evidence never directly changes domain lifecycle. Correlated output descriptors are mapped only when physical validation succeeds; no persistence or lifecycle mutation occurs. F3 is CLOSED; durable completion/artifact persistence was closed in F5.
F3-6: implementación completa y live validada; F3-7 real WS/history/output physical path validation completada. F3 global está CLOSED; F4/H3 bindings están **CLOSED — APPROVED**; F5 está **CLOSED — APPROVED** (Slice4A completada, auditada y aprobada); F6 está **CLOSED — APPROVED** para recovery durable de un chunk.

Mapper output→`ArtifactObservation` implementado, probado y fail-closed. La persistencia durable de completion/artifact quedó cerrada en F5.

## F7 — implementación técnica (2026-08-31)

`ChainExecutionUseCase` implementa chaining durable de dos o tres chunks,
propagando el frame N-1 como `first_frame` y persistiendo cada checkpoint antes
del siguiente submit. Los chunks exitosos y sus artefactos se preservan al
reanudar. Estado: **CLOSED — APPROVED** (2026-08-31). Auditoría independiente `orquestador-f7-final-audit-017`: F7 19/19, F6 28/28, F5 21/21, corrupción F2 17/17 y regresión oficial 437/437; `git diff --check` PASS. No se ejecutó nueva generación E2E contra ComfyUI ni validación visual.
