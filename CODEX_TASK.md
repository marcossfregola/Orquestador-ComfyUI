# CODEX_TASK — frontera F11.6B

## Cierre validado anterior — F14

- **F14.4 — CLOSED — APROBADA.**
- **F14 — CLOSED — APROBADO.**
- Baseline de código validado: `ea2d50deeb59f185fddeee142e4feb39e6f2b258`.
- Baterías focales: **303 ejecuciones, 302 OK, 1 skip, 0 FAIL/ERROR**.
- Regresión integrada F14.1–F14.3: **301 tests, 300 OK, 1 skip, 0 FAIL/ERROR**.
- Suite completa canónica: **816 tests, 8 FAIL, 6 ERROR, 2 skips**. Las 14 incidencias son deuda histórica conocida y no hubo regresiones nuevas.
- El smoke integrado real con ComfyUI fue aprobado; el MP4 final se reprodujo completo y la persona confirmó **VIDEO OK**.

La evidencia, el tratamiento de la primera corrida inválida de `git archive` y los detalles del smoke permanecen en `TESTING.md`.

## Cierre previo — F11.6A

- **F11.6A — acceso directo a resultados: CLOSED — APROBADA** en el commit local aprobado `a69c65cb28a07a15933830763ac40677afa01b5d`, rama `codex/f11-6a-results`.
- Marcos aprobó la validación humana Windows de F11.6A: MP4 final, chunks individuales, mostrar en Explorador y cambio de proyecto sin resultados cruzados.
- La auditoría diferencial registrada para F11.6A concluyó `NEW_REGRESSIONS=0`; la omisión de symlink por WinError 1314 está documentada en `TESTING.md`.

## Tarea explícita actual

El usuario autorizó **F11.6B — corregir scroll y navegación de Biblioteca**, en una rama nueva desde el commit anterior. Alcance:

- La rueda dentro de la lista de proyectos queda consumida por la lista incluso en sus límites; fuera de ella, el scroll vertical de Biblioteca sigue funcionando.
- Biblioteca conserva la posición y la selección al abrir un proyecto, cambiar de pestaña y refrescar.
- No se altera selección, doble clic ni navegación por teclado; el foco Qt automático no debe desplazar la página.
- No tocar generación, resultados, ComfyUI, SQLite, cola ni ensamblado.

**Estado:** implementación y pruebas automáticas realizadas; Marcos aprobó la validación humana Windows el 2026-10-22 (5/5). F11.6B está **READY_FOR_COMMIT**, aún sin commit y **NO CERRADA**. Evidencia actual en `TESTING.md`.

## Frontera vigente

- Rama de trabajo: `codex/f11-6b-library-scroll-navigation`, derivada del commit local F11.6A indicado arriba.
- Detenerse antes del commit. No hacer commit, push, merge, tag ni release.
- La modificación se limita a F11.6B y su documentación/evidencia. No ejecutar nuevas generaciones ComfyUI.
