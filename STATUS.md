# Estado del proyecto

**Última actualización:** 2026-09-10
**Fase:** F10 **CLOSED — APPROVED** (`HUMAN_VISUAL_VALIDATION=APPROVED`, `VISUAL_CONTINUITY=APPROVED`); F11.0 **CLOSED — APPROVED**; F11.1A **CLOSED — APPROVED**; F11.1B **CLOSED — APPROVED**; F11.2A **CLOSED — HUMAN-VALIDATED**.
**Estado:** F0–F8 cerradas; F9 **CLOSED — APPROVED WITH OBSERVATIONS**; F10 **CLOSED — APPROVED**; F11.0 **CLOSED — APPROVED**; F11.1A **CLOSED — APPROVED**, commit `b642af94a1091f1f4e1d71912f61d3b9c756ce86`; F11.1B **CLOSED — APPROVED**, commits `dc2c0e9fc17c4fa9cf0b1809342d3fd10d1ae997` y `97b1f6acb7fd8d558712d8e873f62f03eabf40c4`; F11.2A **CLOSED — HUMAN-VALIDATED**, con evidencia automatizada fresca registrada abajo.

## Fotografía viva

- El núcleo ya dispone de dominio/persistencia, integración ComfyUI, perfil MiniMax H3, orquestación durable, recovery/retry, chaining multi-chunk y ensamblado final cerrados en sus fases correspondientes.
- F9 dejó una GUI PySide6 lanzable y conectada al núcleo, pero no constituye todavía la experiencia de preparación/configuración completa que se busca para uso cotidiano.
- F10 validó el camino público real de dos chunks contra ComfyUI, incluyendo materialización del último frame N-1 como siguiente `first_frame`, persistencia/reopen y continuidad visual humana aprobada.
- La corrección posterior del seam eliminó el recorte implícito 512×512 de `ImageCropV2`; el E2E FAST confirmó que la transición llega pixel-idéntica al pipeline del chunk siguiente. La modificación residual del frame 0 queda clasificada como comportamiento del modelo H3, no como defecto pendiente del Orquestador.
- No es necesario esperar al cierre completo de F11 para usar la aplicación: el roadmap exige slices verticales utilizables y F11.1 es el primer checkpoint destinado a permitir generar un video real completamente desde la GUI Windows.

## F11 — GUI operativa incremental

La autoridad del plan detallado es [ROADMAP.md](ROADMAP.md), sección **F11 — GUI operativa incremental y configuración de generación**.

Objetivo de F11: convertir la GUI técnica existente en una interfaz Windows utilizable para preparar, configurar, ejecutar, seguir, recuperar y obtener resultados de generaciones H3 sin depender de consola ni de edición manual de archivos de configuración.

Orden aprobado:

1. **F11.0 — Inspección y contrato único de configuración — CLOSED / APPROVED (documental).**
2. **F11.1 — Primera GUI realmente utilizable para generar.**
3. **F11.2 — Gestión visual de imagen inicial y referencias.**
4. **F11.3 — Configuración H3 ampliada.**
5. **F11.4 — Editor de secuencia de chunks.**
6. **F11.5 — Operación, recuperación y resultados desde GUI.**
7. **F11.6 — Pulido de UX y validación Windows.**

Regla operativa: cada slice debe cerrarse con implementación, pruebas, evidencia, auditoría y validación humana cuando corresponda, dejando una aplicación utilizable antes de avanzar a la siguiente. No se implementan de entrada expansiones del backlog como IA, otros modelos, cloud, multi-GPU, timeline avanzado o plugin system.

**Checkpoint:** F11.1B quedó implementada y cerrada en la historia Git (`dc2c0e9fc17c4fa9cf0b1809342d3fd10d1ae997`, `97b1f6acb7fd8d558712d8e873f62f03eabf40c4`); F11.2A quedó cerrada tras verificación automatizada y validación humana explícita. `REAL_VIDEO_GENERATION=NO`.

### F11.2A — preparación visual (2026-09-10)

**CLOSED — HUMAN-VALIDATED.** La validación humana explícita confirmó preview inicial; 0, 1 y 6 referencias; agregar/reemplazar/quitar; recortes manuales con ratios, movimiento y resize; paths seleccionados y preferencias por defecto; y `Prepare` completado sin el crash nativo de Qt. Esta evidencia humana no sustituye ni amplía la evidencia automatizada.


## Histórico F1–F10

- (Histórico F1) F1 tiene evidencia controlada de B2–B7 y C1–C3 contra la instalación real de ComfyUI.
- (Histórico F1) C3 recibió validación humana explícita: la unión Chunk 1 → Chunk 2 fue reportada como perfecta e imperceptible.
- (Histórico de F1) No se implementó código ni infraestructura de producción en ese checkpoint.
- (Histórico de F1) F1 no implementaba F2/F3/F4; la evidencia de spike quedó formalmente cerrada en ese checkpoint.
- F2: **CLOSED — APPROVED** (cierre 2026-08-28).
- F3: **CLOSED / COMPLETED — LIVE VALIDATED**. Auditoría global independiente 096: cero bloqueadores técnicos; sólo sincronización documental.
- F4: **CLOSED — APPROVED**.
- F5: **CLOSED — APPROVED**.
- F6: **CLOSED — APPROVED** (2026-08-30).
- F7: **CLOSED — APPROVED** (2026-08-31).
- F8: **CLOSED — APPROVED** (2026-08-31).
- F9: **CLOSED — APPROVED WITH OBSERVATIONS**.
- F10: **CLOSED — APPROVED** (2026-09-01).

## Baseline técnico y evidencia consolidada

- raíz de trabajo y raíz Git histórica: `C:\Codex\Orquestador-ComfyUI`;
- rama: `main`;
- workflow UI canónico histórico: `Prueba Orquestador.json`;
- SHA-256 del workflow: `3070EB659A0BDBEB3D8392B0D203F6B4B86409709A20143280473A12C44BA4A7`;
- ComfyUI core validado: `0.33.0` en `127.0.0.1:8188`;
- correlación determinista validada: `prompt_id → history → SaveVideo node 92 → archivo físico`;
- H3 observado: `LoadImage114→ImageCropV2 127→ImageScaleToTotalPixels119→GetImageSize120→H3 129 first_frame`;
- El profile H3 soporta prompt, first_frame externo, length, `ref_image_size`, `also_ref_first_frame` y FPS; F11.0 formaliza `steps` de `BasicScheduler` node 146 como binding público de F11.1. Seed, sampler y scheduler permanecen fuera de la superficie pública vigente.

La evidencia profunda se conserva en [COMFYUI_INTEGRATION.md](COMFYUI_INTEGRATION.md), [TESTING.md](TESTING.md), [DATA_MODEL.md](DATA_MODEL.md) y el historial Git. Este `STATUS.md` mantiene sólo la fotografía viva necesaria para retomar el proyecto sin reconstruir conversaciones.

## Cierre F5 (2026-08-30)

F5 **CLOSED — APPROVED**; Slices 1, 2, 3 y 4A completadas/auditadas. Slice4A 13/13; todos F5 39/39; regresión 390/390 en dos corridas consecutivas independientes, ambas OK. A–L explícitos; A/B/C/H/I/L usan SQLiteProjectRepository real con close + nueva instancia + reopen; A/B verifican OUTPUT Artifact + TransitionFrame N-1. No hubo ComfyUI real, FFmpeg real donde hubo fakes, ni validación visual/UX. ResourceWarnings históricos no son failures.

## Cierre F6 (2026-08-30)

F6 **CLOSED — APPROVED** después de pasar la suite enfocada `python -B -m unittest tests.test_f6_recover_execution -v` (**28/28 OK**) y la regresión oficial `python -B -m unittest discover -s tests` (**418/418 OK**). La regresión emitió `ResourceWarning` de conexiones/archivos sin cerrar en pruebas existentes, pero no tuvo failures, errors ni skips; se conservan como warnings y no se ocultan.

Implementado: reapertura SQLite y reconciliación; recuperación de `Attempt` y `external_job_ref`; estados backend `QUEUED`, `RUNNING`, `COMPLETED` y `FAILED`; persistencia durable del error; retry único con segundo Attempt y sin Attempt 3; preservación de IDs/referencias; output/evidence, `Artifact` `OUTPUT`, `TransitionFrame` N-1; y resumes repetidos idempotentes con comportamiento fail-closed ante inconsistencias.

## F7 — implementación técnica (2026-08-31)

`ChainExecutionUseCase` implementa chaining durable de dos o tres chunks, propagando el frame N-1 como `first_frame` y persistiendo cada checkpoint antes del siguiente submit. Los chunks exitosos y sus artefactos se preservan al reanudar. Estado: **CLOSED — APPROVED**. Auditoría independiente `orquestador-f7-final-audit-017`: F7 19/19, F6 28/28, F5 21/21, corrupción F2 17/17 y regresión oficial 437/437; `git diff --check` PASS.

## F8 — ensamblado final

Implementados `FFmpegAssemblyAdapter` y `AssembleExecutionUseCase`. Contrato: >=2 chunks, destino MP4, `-c copy` sólo para firmas compatibles, fallback explícito `reencode`, FFprobe final antes de publicación create-if-absent sin overwrite, y preservación de chunks/intermedios.

Auditoría aprobada `orquestador-f8-evidence-audit-037`: FFmpeg/FFprobe reales 8.1.1; concat copy PASS y reencode PASS; focused F8 **6/6 PASS**, suite completa **443/443 PASS**, compileall PASS y `git diff --check` PASS.

## F9 — GUI del primer release

F9 **CLOSED — APPROVED WITH OBSERVATIONS**. Entrega una GUI PySide6 lanzable con raíz de composición/entrypoint, fachada, workers en segundo plano y preparación de inputs. La fachada conecta start/resume/recover/retry/cancel/assemble con los casos de uso existentes; widgets no acceden directamente a persistencia, ComfyUI ni FFmpeg.

Invocación verificada: `python -m orquestador --project-root <absolute-directory> [--comfyui-endpoint <url>] [--workflow-template <absolute-file>] [--ffmpeg <command>] [--ffprobe <command>]`.

## F10 — validación real y cierre técnico (2026-09-01)

F10 queda **CLOSED — APPROVED**. Se completó un E2E real de dos chunks por `facade.prepare` y `facade.start_chain` compuesto, contra ComfyUI `0.33.0`, con siete uploads estáticos `overwrite=false`, bindings H3 sin placeholders, dos submits únicos, SaveVideo node 92, importación segura, hashes conservados, FFprobe válido, frame N-1 y materialización/reutilización durable de la transición.

Los prompt IDs fueron `abea6078-1983-4dc7-80bd-70f25f920ed2` y `a3a2510f-a9ac-45e8-b5e1-e57c58d7a0f8`; el informe completo está en `C:\Codex\Orquestador-ComfyUI-F10-runtime\codex-local-final-f10\e2e-20260901T184920Z-8ee4f1e6\e2e-report-final.json`. Los dos jobs excedieron el deadline fail-closed de 1800 s, permanecieron vinculados a sus `external_job_ref` y no fueron reintentados; la recuperación pública los completó con los mismos IDs. La validación visual humana aprobó la continuidad.

### F10 — corrección del seam y FAST E2E

La revisión del run previo demostró que `ImageCropV2` node 127 interpretaba `crop_region={}` como un recorte 512×512 desde `(0,0)`. El cambio mínimo mantiene la topología `114 → 127 → 119 → 120 → 129` y fija node 127 a `{x:0,y:0,width:16384,height:16384}`, conservando la entrada completa.

El E2E FAST real usó `facade.prepare` → `facade.start_chain(..., fast_e2e=True)`, exactamente siete uploads estáticos, un upload de transición, dos submits y ningún tercero. Duró 57,0 s; ambos MP4 quedaron H.264 352×256, 24 fps, 56 frames, 2,333 s; reopen y estado durable terminaron `succeeded`.

La evidencia `seam-comparison.json` demostró que node 127 es pixel-idéntico a `TRANSITION_INPUT.png` y que esa transición coincide byte/pixel a pixel con el frame 55 exacto de chunk 0. El frame 0 de chunk 1 conserva dimensiones pero no identidad pixel; la diferencia residual queda clasificada como causa D del modelo H3. El control local H.264 mostró una degradación menor que la observada en H3, reforzando esa clasificación.

Evaluación vigente de F10: **CLOSED — APPROVED**. `HUMAN_VISUAL_VALIDATION=APPROVED`; `VISUAL_CONTINUITY=APPROVED`.
