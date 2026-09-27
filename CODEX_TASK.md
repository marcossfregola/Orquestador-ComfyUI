# CODEX_TASK — próxima tarea del Orquestador

Este archivo es un handoff operativo. Si hay conflicto, prevalecen `RULES.md`, `STATUS.md`, `ROADMAP.md`, `FUNCTIONAL_COMPLETION.md`, `ARCHITECTURE.md`, `DATA_MODEL.md` y `TESTING.md`.

## Próxima tarea

**Gate pre-F14 — verificación diferencial final de los hotfixes runtime antes de publicar.**

## Estado

Baseline limpio: `80943faeee828def5dda54fefa70cad13ba6a0b5`.

Sobre ese baseline existen localmente cuatro hotfixes:
1. wrapper SaveVideo `images + animated`, excluyendo previews temporales;
2. resolución robusta de `ffmpeg`/`ffprobe` bare names;
3. retry con rematerialización de inputs estáticos;
4. detalle compacto de rechazo 4xx de ComfyUI.

Las suites focales reportaron 27/27, 80/80 y 41/41; `compileall` y `git diff --check` reportaron OK. La suite completa reportó 778 tests, 9 failures, 5 errors y 2 skipped. Falta demostrar que esos failures/errors son preexistentes.

## Objetivo único

Comparar la suite completa del baseline limpio contra la suite completa con hotfixes. No modificar implementación salvo que aparezca una regresión nueva.

## Instrucciones

1. No perder, resetear ni reformatear el working tree actual.
2. No usar cherry-pick, rebase, force ni merge.
3. Crear un worktree temporal separado desde `80943faeee828def5dda54fefa70cad13ba6a0b5`, fuera del working tree principal.
4. Ejecutar allí la suite completa con un `ORQ_TEST_TMP` fresco.
5. Registrar lista exacta de tests FAILED/ERROR/SKIPPED del baseline.
6. En el working tree con hotfixes, volver a ejecutar la suite completa con otro `ORQ_TEST_TMP` fresco y registrar la lista exacta.
7. Comparar por nombre de test:
   - si hotfix tiene la misma lista o menos failures/errors que baseline: `NEW_REGRESSIONS=0`;
   - si aparece cualquier failure/error nuevo: detenerse, no commit/push y diagnosticar.
8. Confirmar otra vez pruebas focales, `python -B -m compileall -q src tests`, `git diff --check` y ausencia de churn CRLF masivo.
9. Eliminar el worktree temporal sólo con `git worktree remove` después de capturar evidencia.
10. Si `NEW_REGRESSIONS=0` y los focales siguen verdes, queda autorizado:
    - un único commit lógico con sólo los diez paths del hotfix;
    - mensaje: `stabilize F13.10 runtime recovery paths`;
    - push normal a `origin/main`;
    - sin force, tag ni release.
11. Detenerse después del push. No iniciar F14.1.

## Evidencia requerida

- SHA baseline;
- SHA final si se publica;
- lista exacta FAILED/ERROR/SKIPPED baseline;
- lista exacta FAILED/ERROR/SKIPPED hotfix;
- `NEW_REGRESSIONS=0` o detalle;
- focales, compileall y diff-check;
- ausencia de churn CRLF;
- paths del commit;
- confirmación de que F14.1 no se inició.
