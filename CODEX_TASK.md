# CODEX_TASK — validación humana pendiente

## Estado

F14.2 está implementada técnicamente y publicada en `origin/main`, con migración schema 8→9 y `NEW_REGRESSIONS=0`. Sigue **PENDIENTE DE SMOKE HUMANO WINDOWS**; no declararla cerrada sin esa evidencia. No iniciar F14.3.

El contrato, modelo y evidencia automatizada vigentes están en `FUNCTIONAL_COMPLETION.md`, `ARCHITECTURE.md`, `DATA_MODEL.md`, `ROADMAP.md`, `STATUS.md` y `TESTING.md`. Las fallas/errors históricos de la suite completa continúan documentados allí.

## Smoke humano exacto

Usar la aplicación Windows con el proyecto/output root y ComfyUI disponibles. Preparar ejecuciones de prueba seguras y pequeñas para evitar trabajo/costo no deseado.

1. Iniciar con la cola vacía. En la pestaña `Cola`, seleccionar `Manual`.
2. Pulsar `Iniciar/Reanudar cola` sin items y confirmar que la política no cambia y no aparece un activo.
3. Cerrar y volver a abrir la aplicación. Confirmar que el selector sigue en `Manual` y que `Iniciar/Reanudar cola` vuelve a estar habilitado: el permiso de la sesión anterior no persistió.
4. Agregar un snapshot preparado de prueba. Confirmar que queda `En espera`, no aparece QueueItem activo y no se genera ningún submit nuevo en ComfyUI mientras el permiso esté cerrado.
5. Pulsar `Iniciar/Reanudar cola`. Confirmar que el scheduler existente activa ese item una sola vez y que la cadena comienza sin duplicar submit.
6. Dejarlo terminar. Cambiar a `Automático`, agregar otro snapshot seguro y confirmar que se activa automáticamente sin pulsar el botón manual.

Informar qué pasos se completaron, los estados observados de Cola y ComfyUI y cualquier desvío. Mantener F14.2 abierta hasta revisar esa evidencia. F14.3 queda fuera de la tarea.
