# CODEX_TASK — próxima tarea del Orquestador

Este archivo es un handoff operativo, no una autoridad de arquitectura. Si hay conflicto, prevalecen `RULES.md`, `STATUS.md`, `ROADMAP.md`, `FUNCTIONAL_COMPLETION.md`, `ARCHITECTURE.md`, `DATA_MODEL.md` y `TESTING.md`.

## Próxima tarea

**F14.1 — Nombre durable y renombrado de proyectos.**

## Instrucciones para Codex local

1. Trabajar exclusivamente en `C:\Codex\Orquestador-ComfyUI`.
2. Antes de modificar, leer completos: `RULES.md`, `STATUS.md`, `ROADMAP.md`, `FUNCTIONAL_COMPLETION.md`, `ARCHITECTURE.md`, `DATA_MODEL.md` y las secciones relevantes de `TESTING.md`.
3. Verificar y reportar baseline real: repo, rama, HEAD, `origin/main`, status, staging/untracked y `git diff --check`.
4. Inspeccionar el código real afectado y confirmar el diagnóstico de F14.1 antes de editar.
5. Implementar **sólo F14.1**. No iniciar F14.2.
6. Mantener compatibilidad/migración de datos y las fronteras arquitectónicas.
7. Crear/actualizar pruebas focales y ejecutar las regresiones exigidas por F14.1.
8. Actualizar en la misma slice los documentos autoridad que hayan cambiado por la implementación real.
9. Revisar diff y dejar un informe final con archivos, pruebas, resultados, riesgos y validación humana pendiente.
10. No relajar tests, no borrar datos, no tocar otros proyectos.
11. Commit y push sólo si la invocación del usuario los autoriza explícitamente. Si están autorizados: un único commit lógico de F14.1, push normal a `origin/main`, sin force, tag ni release.
12. Detenerse al completar F14.1. No marcarla cerrada si falta la validación/auditoría requerida.

## Criterio de salida

La entrega debe permitir una auditoría independiente sin confiar en frases como “funciona”: incluir comandos y salidas reales, SHA, diff, pruebas y cualquier aspecto no verificado.
