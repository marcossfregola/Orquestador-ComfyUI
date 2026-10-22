# CODEX_TASK — frontera F11.6A

## Cierre validado anterior

- **F14.4 — CLOSED — APROBADA.**
- **F14 — CLOSED — APROBADO.**
- Baseline de código validado: `ea2d50deeb59f185fddeee142e4feb39e6f2b258`.
- Baterías focales: **303 ejecuciones, 302 OK, 1 skip, 0 FAIL/ERROR**.
- Regresión integrada F14.1–F14.3: **301 tests, 300 OK, 1 skip, 0 FAIL/ERROR**.
- Suite completa canónica: **816 tests, 8 FAIL, 6 ERROR, 2 skips**. Las 14 incidencias son deuda histórica conocida y no hubo regresiones nuevas.
- El smoke integrado real con ComfyUI fue aprobado; el MP4 final se reprodujo completo y la persona confirmó **VIDEO OK**.

La evidencia, el tratamiento de la primera corrida inválida de `git archive` y los detalles del smoke permanecen en `TESTING.md`.

## Tarea explícita actual

La tarea del usuario del 2026-10-21 autoriza **F11.6A — acceso directo a resultados**. El alcance es resolver únicamente outputs acreditados por evidencia durable, presentarlos en Principal y abrirlos mediante el reproductor predeterminado de Windows o el Explorador. Incluye rutas contenidas, evidencia de ensamblado, ejecución parcial e histórica, estado de disponibilidad y pruebas focales.

**Estado: IMPLEMENTADA — AUDITORÍA DIFERENCIAL COMPLETADA (NEW_REGRESSIONS=0) — VALIDACIÓN HUMANA WINDOWS APROBADA — LISTA PARA CIERRE TÉCNICO — NO CERRADA.** La suite F11.6A terminó con 14 OK y 1 skip por privilegio de symlink en Windows; una prueba temporal con junction verificó el rechazo de escapes. Marcos confirmó y aprobó las cuatro comprobaciones visuales Windows. Los resultados diferenciales, la aprobación y sus límites están registrados en TESTING.md.

## Frontera vigente

- La validación humana Windows fue aprobada; F11.6A queda preparada para cierre técnico, pero todavía no está cerrada.
- F11.6A no autoriza otras mejoras de F11.6.
- Esta tarea no autoriza commit, push, PR, merge, tag ni release.
