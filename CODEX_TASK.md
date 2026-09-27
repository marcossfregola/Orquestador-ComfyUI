# CODEX_TASK — próxima tarea del Orquestador

Este archivo es un handoff operativo, no una autoridad de arquitectura. Si hay conflicto, prevalecen `RULES.md`, `STATUS.md`, `ROADMAP.md`, `FUNCTIONAL_COMPLETION.md`, `ARCHITECTURE.md`, `DATA_MODEL.md` y `TESTING.md`.

## Próxima tarea

**Gate pre-F14 — reconciliar hotfixes runtime preservados antes de iniciar F14.1.**

Fuente de evidencia preservada:

- rama remota: `origin/recovery/pre-f14-local-changes-2026-09-27`
- commit: `55fb03a8aa8c72e7319be2c00137e4af36062926`
- baseline de esa captura: `2fd5c6961cd007e6accb52ac34bd17a99e8938d0`

La captura está aprobada sólo como resguardo. **No está aprobada para merge directo.** Contiene churn de CRLF/trailing-whitespace en `recover_execution.py` y no tiene CI/test run asociado en GitHub.

## Objetivo

Partiendo del `main` remoto actual, reconstruir únicamente los cambios semánticos útiles de la rama de resguardo, sin cherry-pick ciego y sin arrastrar cambios de fin de línea.

Los cuatro grupos observados a reconciliar son:

1. correlación de outputs de ComfyUI: reconocer el wrapper `images + animated` de SaveVideo y no tratar previews `type=temp` como output durable;
2. resolución robusta de nombres bare `ffmpeg`/`ffprobe` en Windows mediante el ejecutable encontrado en PATH, preservando paths explícitos y dobles de test;
3. retry explícito de chunk fallido: reconstruir el prompt usando la misma autoridad de materialización de inputs estáticos que Start, para que las referencias durables locales se conviertan en rutas visibles por ComfyUI;
4. conservar detalle compacto y accionable de rechazos 4xx de ComfyUI sin alterar la semántica fail-closed.

## Instrucciones

1. Trabajar exclusivamente en `C:\Codex\Orquestador-ComfyUI`.
2. No modificar ni borrar la rama de resguardo.
3. Ejecutar `git fetch origin`.
4. Volver a `main` y sincronizar sólo mediante `git pull --ff-only`. El `main` remoto contiene documentación posterior a `2fd5c696`; debe preservarse.
5. Verificar baseline real: rama, HEAD, `origin/main`, status, staging/untracked y `git diff --check`. El árbol debe quedar limpio antes de editar.
6. Leer `RULES.md`, `STATUS.md`, este archivo y las autoridades relevantes.
7. Comparar `2fd5c696..55fb03a8` usando también una vista que ignore whitespace/EOL para separar semántica de churn.
8. **No hacer cherry-pick directo** de `55fb03a8`. Reaplicar/reconstruir los cambios semánticos mínimos sobre el `main` actual.
9. Preservar las fronteras actuales: sin segunda ruta de submit, sin cambio de budget de retry, sin borrar outputs, sin DB manual.
10. Mantener/ajustar pruebas para los cuatro grupos. Los dos tests nuevos de la rama de resguardo pueden reutilizarse sólo si siguen expresando correctamente el contrato.
11. Ejecutar como mínimo:
   - pruebas focales de outputs;
   - pruebas focales de retry/recovery incluyendo stale-not-found;
   - pruebas focales de composición/runtime F13.10;
   - pruebas de video adapter;
   - `python -B -m compileall -q src tests`;
   - `python -B -m unittest discover -s tests`;
   - `git diff --check`.
12. Si la suite completa falla por un problema ambiental preexistente, aislarlo con evidencia; no relajar tests ni ocultarlo.
13. Revisar el diff final y comprobar que no exista un reemplazo masivo sólo por CRLF.
14. Actualizar documentación únicamente si la semántica durable/autoridad realmente cambia. No iniciar F14.1.
15. Si todo queda verde, te autorizo a crear **un único commit lógico de hotfix pre-F14** y hacer push normal a `origin/main`, sin force, tag ni release.
16. Detenerte después del push. No avanzar a F14.1.

## Evidencia requerida al terminar

Informar:

- baseline y SHA final;
- archivos realmente modificados;
- resumen de cada uno de los cuatro hotfixes recuperados o motivo de exclusión;
- comandos de pruebas y resultados exactos;
- `git diff --check`;
- confirmación de ausencia de churn CRLF masivo;
- cualquier prueba real Windows/ComfyUI que NO se haya ejecutado;
- commit/push realizados o bloqueo encontrado.
