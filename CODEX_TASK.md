# CODEX_TASK — frontera F14.3 / F14.4

## Estado vigente

- **F14.3 — CLOSED — APROBADA.**
- Implementación publicada en `4f1bd9320c005ef9dc0ac89855f10abc3f529681`.
- Las pruebas automáticas y la comparación diferencial están aprobadas; `NEW_REGRESSIONS=0`.
- El smoke humano Windows está aprobado: cadena real de dos chunks secuenciales, assembly automático, MP4 final reproducido completo y orden/continuidad validados visualmente.
- SQLite schema 10 registró `AssemblyAttempt #1 succeeded`. El QueueItem se finalizó sólo después de evidencia durable final válida.
- Durante assembly hubo cero Attempts de chunk nuevos y cero submits a ComfyUI.
- El retry de assembly fallido no se ejercitó humanamente; está cubierto por pruebas automáticas.

El detalle y la procedencia de la evidencia permanecen en `STATUS.md`, `ROADMAP.md`, `FUNCTIONAL_COMPLETION.md` y `TESTING.md`.

## Próxima etapa

**F14.4 — PLANNED — NO INICIADA — NO AUTORIZADA.** Es la próxima etapa del roadmap, pero este archivo no autoriza iniciarla. Esperar una nueva tarea explícita antes de inspeccionar para implementación, modificar archivos, ejecutar pruebas de F14.4 o preparar su publicación.

F11.6 continúa pospuesta hasta después de F14 y requiere su propia autorización.

## Alcance de esta frontera

Este archivo sólo registra el estado de cierre de F14.3 y el límite de autorización siguiente. No contiene una tarea activa de implementación para F14.3 ni una autorización implícita para avanzar a F14.4.
