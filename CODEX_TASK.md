# CODEX_TASK — próxima tarea del Orquestador

Este archivo es un handoff operativo, no una autoridad de arquitectura. Si hay conflicto, prevalecen `RULES.md`, `STATUS.md`, `ROADMAP.md`, `FUNCTIONAL_COMPLETION.md`, `ARCHITECTURE.md`, `DATA_MODEL.md` y `TESTING.md`.

## Próxima tarea

**F14.1 — Nombre durable y renombrado de proyectos.**

Baseline de partida: `origin/main` en `c14aa524c770b994330a04c55e615bc110313fda` o un commit documental posterior que no cambie producción. El gate pre-F14 está cerrado y aprobado.

## Instrucciones para Codex local

1. Trabajar exclusivamente en `C:\Codex\Orquestador-ComfyUI`.
2. Ejecutar `git fetch origin` y sincronizar `main` sólo mediante `git pull --ff-only`.
3. Antes de modificar, leer completos: `RULES.md`, `STATUS.md`, `ROADMAP.md`, `FUNCTIONAL_COMPLETION.md`, `ARCHITECTURE.md`, `DATA_MODEL.md` y las secciones relevantes de `TESTING.md`.
4. Verificar baseline real: repo, rama, HEAD, `origin/main`, status, staging/untracked y `git diff --check`. El working tree debe estar limpio.
5. Inspeccionar el código real afectado y confirmar el diagnóstico de F14.1 antes de editar.
6. Implementar **sólo F14.1** conforme al contrato completo de `FUNCTIONAL_COMPLETION.md`. No iniciar F14.2.
7. Mantener `ProjectId` técnico, opaco e inmutable; agregar identidad humana durable separada. Rename no puede mover archivos, alterar IDs, ejecuciones, cola, attempts, artifacts, transitions, outputs ni recovery.
8. Implementar migración incremental desde schema 7 preservando todos los proyectos existentes y probar casos con IDs legibles, UUIDs y colisiones normalizadas.
9. Mantener UI → aplicación/casos de uso → dominio. Ningún widget accede directamente a SQLite.
10. Crear/actualizar pruebas de create, rename, conflictos, restart/reopen, clone con autosufijo, Biblioteca y Cola por nombre, y regresión F13 relevante.
11. Ejecutar como mínimo las pruebas focales de F14.1, las regresiones F13.1/F13.2/F13.6/F13.7/F13.10 afectadas, `python -B -m compileall -q src tests` y `git diff --check`.
12. Ejecutar también la suite completa. Los failures/errors históricos registrados en `TESTING.md` no deben ocultarse ni corregirse fuera de alcance; cualquier failure/error nuevo respecto del baseline debe tratarse como regresión y bloquear el commit.
13. Actualizar `ARCHITECTURE.md`, `DATA_MODEL.md`, `STATUS.md`, `TESTING.md` y demás autoridades sólo según la implementación real.
14. Revisar el diff final y confirmar ausencia de refactors no solicitados, cambios de EOL masivos o paths ajenos.
15. Si todo lo exigido para F14.1 queda correcto, queda autorizado un único commit lógico de F14.1 y push normal a `origin/main`, sin force, tag ni release.
16. Detenerse después del push. **No iniciar F14.2.**
17. Si la implementación requiere validación humana Windows para cerrar F14.1, no declararla CLOSED todavía: indicar exactamente qué debe probar la persona.

## Evidencia final requerida

- baseline y SHA final;
- archivos modificados;
- migración implementada y compatibilidad demostrada;
- criterios de aceptación cubiertos;
- comandos de prueba y resultados exactos;
- comparación de suite completa contra la deuda histórica registrada;
- cualquier aspecto no verificado;
- commit/push realizados;
- confirmación de que F14.2 no se inició.
