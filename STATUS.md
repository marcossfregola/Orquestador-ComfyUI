# Estado del proyecto

**Última actualización:** 2026-08-28
**Fase:** F2 — Dominio + persistencia + reconciliación base
**Estado:** CLOSED — aprobado por la dirección técnica de ChatGPT; se cumplieron los criterios de cierre de F1 con esta corrección exacta

## Fotografía viva

- F1 tiene evidencia controlada de B2–B7 y C1–C3 contra la instalación real de ComfyUI.
- C3 recibió validación humana explícita: la unión Chunk 1 → Chunk 2 fue reportada como perfecta e imperceptible.
- No se implementó código ni infraestructura de producción.
- La consolidación documental de este checkpoint está sin commit; el estado Git posterior debe leerse en la evidencia final.
- F1 no implementa F2/F3/F4. La evidencia de spike está completa y F1 queda formalmente cerrada por aprobación de la dirección técnica de ChatGPT.
- F2: **IMPLEMENTATION COMPLETE — PENDING FINAL CHATGPT AUDIT**.
- F2 incluye modelo ejecutable backend-agnóstico, persistencia SQLite v1, historial append-only, validación de grafo/procedencia y reconciliación pura determinista. No incluye adaptador ComfyUI, FFmpeg productivo, bindings/profile H3, GUI, orquestación productiva ni validación visual.
- F3: NOT STARTED.

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
- F2: implementación técnica completa; pendiente auditoría final de ChatGPT (estado vigente arriba).
- F3: NOT STARTED — adaptador productivo, reconexión, cancelación y errores.
- F4: contrato versionado del Workflow Profile H3 y tests de compatibilidad/bindings.
- F6/F7/F8/F9: recovery, chaining largo, ensamblado productivo y GUI.

## Criterio de cierre

F1 está CLOSED: el trabajo técnico, la documentación de evidencia y esta corrección exacta cumplen todos los criterios de cierre. No autoriza implementación productiva ni adelanta F2–F4.
