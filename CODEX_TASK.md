# CODEX_TASK — frontera F11.6C

## Cierres previos

- **F14.4 — CLOSED — APROBADA**; baseline validado `ea2d50deeb59f185fddeee142e4feb39e6f2b258`.
- **F11.6A — CLOSED — APROBADA** en `a69c65cb28a07a15933830763ac40677afa01b5d`, rama `codex/f11-6a-results`.
- **F11.6B — CLOSED — APROBADA** en `16c91f653f56438bd563a5fc2e88639865bf3518`, rama `codex/f11-6b-library-scroll-navigation`. Marcos aprobó su validación humana Windows 5/5 el 2026-10-22.

## Tarea explícita actual

Completar la auditoría final de **F11.6C — recuperación durable de videos finales históricos** en `codex/f11-6c-historical-final-video`, derivada del commit F11.6B indicado arriba. La implementación está lista y Marcos aprobó tanto la recuperación real del caso como su validación humana Windows el 2026-10-22.

El alcance habilita una acción explícita «Generar video final histórico» para una ejecución durable `succeeded` sin AssemblyAttempt, si y sólo si todos sus chunks exitosos, artifacts, transiciones y archivos son inequívocos y válidos. Reutiliza la finalización F14.3, publica bajo el proyecto sin solicitar destino y mantiene sin cambios el estado `succeeded` de Execution y QueueItem. La apertura desde Biblioteca nunca inicia FFmpeg.

Se bloquea la generación cuando la ejecución está activa, fallida, incompleta, ambigua, carece de procedencia o existe el destino final sin evidencia durable. El video final sólo queda disponible después de guardar AssemblyAttempt exitoso con hash y firma FFprobe. Los fallos e interrupciones deben conservar datos y permitir recuperación segura sólo si la evidencia sigue coincidiendo.

Caso real ya recuperado con autorización de Marcos, no usar como fixture: proyecto `f241170c`, ejecución `77267374-1393-43bd-9c9d-08b8d3d57409`.

## Frontera vigente

- No repetir la recuperación real ni modificar la SQLite, los MP4 o la evidencia del proyecto indicado. La auditoría final puede leer esa ejecución con SQLite `mode=ro`/`PRAGMA query_only=ON`, calcular hashes y ejecutar FFprobe.
- Las pruebas automatizadas F11.6C usan exclusivamente fixtures aisladas.
- No ejecutar generaciones ComfyUI ni FFmpeg de ensamblado; no alterar la generación, la cola, exports manuales o ensamblado F14.3 fuera de la integración ya auditada.
- Detenerse antes del commit; no hacer push, merge, tag ni release.
- No utilizar ChatGPT–Codex Bridge.
