# CODEX_TASK — diagnóstico bloqueante F14.2

## Estado

F14.2 está publicada en `8b7258304eca384d20d4721f35639268a6036e01` pero NO está cerrada.

Durante el smoke humano Windows, antes de encolar nada, pulsar `Prepare` sobre un borrador de dos chunks dejó la ventana en `Orquestador (No responde)` durante más de 30 segundos.

No iniciar F14.3.

## Objetivo de esta tarea

**Reproducir y diagnosticar el freeze de Prepare con evidencia antes de modificar producción.**

No asumir que F14.2 es la causa. Comparar el comportamiento con y sin scheduler/F14.2 cuando sea posible.

## Observación humana exacta

- app Windows abierta;
- proyecto/borrador editable con imagen inicial visible y dos chunks pending;
- modo de Cola Manual durante el smoke de F14.2;
- al pulsar `Prepare`, controles quedaron deshabilitados como operación busy;
- Windows mostró `Orquestador (No responde)`;
- siguió así >30 s;
- no se llegó a `Agregar a cola`;
- Prepare no debería generar ni hacer submit a ComfyUI.

## Pista técnica a verificar

En el código actual:

- `MainWindow._prepare()` usa `_run(...)` y `OperationWorker` en `QThread`;
- `SchedulerBackgroundRunner` hace polling cada 0,25 s;
- `QueueDispatchSession.claim_next()` llama a `repository.claim_next_queue_item(manual_dispatch_open=...)`;
- `claim_next_queue_item()` usa `_queue_transaction()` → `BEGIN IMMEDIATE` y recién dentro de esa transacción comprueba `manual + permiso cerrado`.

Esto puede producir contención, pero NO declararlo causa sin reproducir y medir.

## Trabajo requerido — fase diagnóstica

1. `git fetch origin` + `git pull --ff-only`; verificar `main`, SHA, árbol limpio y `git diff --check`.
2. Leer autoridades y código relevante:
   - `ui/main_window.py`
   - `ui/workers.py`
   - `application/prepare_gui.py`
   - `application/scheduler.py`
   - `application/queue_dispatch.py`
   - `persistence/sqlite.py`
   - composición en `ui/app.py`.
3. No modificar producción inicialmente.
4. Reproducir de forma controlada el flujo Prepare con:
   - scheduler normal F14.2 en `manual` cerrado;
   - scheduler desactivado/aislado en una prueba diagnóstica equivalente;
   - si es útil, `auto` con cola vacía.
5. Instrumentar temporalmente en test/harness, no en producción salvo necesidad aprobada, tiempos y thread IDs alrededor de:
   - click/dispatch `_prepare`;
   - inicio/fin de `OperationWorker.run`;
   - apertura/cierre de repositorio de Prepare;
   - lectura/import de inputs;
   - `repository.save*()`;
   - ticks del scheduler;
   - `BEGIN IMMEDIATE/COMMIT/ROLLBACK`.
6. Obtener stack traces si la GUI/event loop deja de responder. Preferir `faulthandler.dump_traceback_later`, thread dump o mecanismo equivalente sin OCR/manual speculation.
7. Determinar si:
   - el GUI thread está realmente bloqueado;
   - el worker de Prepare está esperando SQLite;
   - el scheduler está monopolizando/contendiendo SQLite;
   - hay una espera circular Qt/QThread;
   - hay I/O de archivo inesperadamente costoso;
   - o existe otra causa.
8. Confirmar si el comportamiento existía también en baseline F14.1 `a3a9be122a1ce4f41de18725867e0453e95dc471` o fue introducido por F14.2.
9. Entregar diagnóstico con evidencia concreta **antes de implementar fix**.

## Regla de parada

Esta task es diagnóstica. No hacer refactor ni corrección de producción todavía salvo que la causa sea inequívoca, mínima y el informe pueda separar claramente diagnóstico de implementación; preferimos detenerse tras diagnóstico para auditoría.

No commit de código de producción en esta fase. Si se crean harness/tests diagnósticos temporales, no publicarlos salvo que sean pruebas de regresión útiles y se explique por qué.

## Evidencia requerida

- reproducido SÍ/NO;
- baseline F14.1 vs F14.2;
- thread dumps/stacks/timings;
- estado de SQLite/locks;
- si ComfyUI interviene o no;
- causa raíz o hipótesis restantes;
- propuesta mínima de corrección;
- archivos que cambiarían;
- pruebas de regresión propuestas;
- F14.3 no iniciada.
