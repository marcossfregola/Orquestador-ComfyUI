# CODEX_TASK — próxima tarea del Orquestador

Este archivo es un handoff operativo. Si hay conflicto, prevalecen `RULES.md`, `STATUS.md`, `ROADMAP.md`, `FUNCTIONAL_COMPLETION.md`, `ARCHITECTURE.md`, `DATA_MODEL.md` y `TESTING.md`.

## Próxima tarea

**F14.2 — Política durable de inicio de cola automática/manual.**

F14.1 está **CLOSED — APROBADA** y no debe reabrirse salvo regresión demostrada.

Baseline de partida: `origin/main` en `796d9afba88a1685b163c6bd85064c08de10420c` o un commit documental posterior que no cambie producción.

## Objetivo

Conservar el comportamiento actual `auto` y agregar una política durable `manual` para que la aplicación pueda abrirse, inspeccionar Biblioteca/Cola y no reclamar ni enviar nuevos trabajos hasta una acción explícita de la persona.

## Contrato obligatorio

- Política durable: `auto | manual`.
- Default: `auto` para preservar comportamiento existente.
- `auto`: scheduler conserva la conducta actual.
- `manual`: cada arranque de la app inicia con permiso de despacho **cerrado**.
- En manual, abrir la app no puede reclamar un nuevo `QueueItem` ni producir un submit nuevo.
- Acción explícita `Iniciar/Reanudar cola` abre el permiso de despacho de **esa sesión**.
- El permiso de sesión manual NO sobrevive al reinicio.
- La política durable sí sobrevive al reinicio.
- Política manual y `queue_control.paused` son conceptos distintos. No reutilizar `paused`.
- Cambiar a manual nunca cancela un item active/running.
- Recovery puede inspeccionar/reconciliar evidencia existente de forma segura, pero manual no autoriza nuevos claims/submits hasta permiso explícito.
- Un active sobreviviente no puede duplicarse.
- No agregar `/interrupt`.
- No crear una segunda ruta de submit; el scheduler debe seguir entrando por las fronteras existentes.
- UI mínima funcional; F11.6 sigue fuera de alcance.

## Antes de editar

1. Trabajar sólo en `C:\Codex\Orquestador-ComfyUI`.
2. `git fetch origin` + `git pull --ff-only`.
3. Verificar rama, HEAD/origin, status limpio, staging/untracked y `git diff --check`.
4. Leer autoridades completas y luego inspeccionar:
   - scheduler F13.8/F13.9;
   - `queue_control` y persistencia schema 8;
   - composition/runtime startup;
   - `QueueDashboardUseCase` / `QueuePanel`;
   - app startup/shutdown;
   - tests F13.7–F13.10.
5. Diagnosticar dónde debe vivir:
   - política durable;
   - gate de sesión manual;
   - acción UI que abre el gate;
   - comportamiento recovery vs claim nuevo.
6. Documentar qué cambia y qué NO cambia antes de implementar.

## Diseño esperado

Elegir el mínimo modelo correcto tras inspección. Preferencias:

- persistir la política en una autoridad durable explícita y versionada;
- si requiere schema nuevo, migración incremental desde schema 8;
- mantener el permiso de despacho manual como estado **de proceso/sesión**, no durable;
- el scheduler consulta ambas autoridades antes de un claim nuevo;
- recovery de active existente se mantiene separado del permiso para nuevo dispatch;
- UI expone política `Automático / Manual` y una acción clara `Iniciar/Reanudar cola` cuando corresponde.

No almacenar la política en widgets ni acceder SQLite directamente desde UI.

## Pruebas obligatorias

Cubrir como mínimo:

1. migración/persistencia de `auto | manual`;
2. default `auto` conserva F13.10;
3. manual cold start con cola vacía;
4. manual cold start con items queued: cero claim y cero submit;
5. acción explícita en manual habilita scheduler normal;
6. reinicio vuelve a cerrar el permiso de sesión manual;
7. política manual durable persiste;
8. active sobreviviente se reconcilia sin doble submit;
9. cambiar auto→manual con active no cancela ni interrumpe;
10. pausa durable y política manual no se confunden;
11. pause/resume conserva semántica;
12. no doble claim/submit;
13. Qt offscreen de controles mínimos;
14. regresión F13.7/F13.8/F13.9/F13.10;
15. `python -B -m compileall -q src tests`;
16. `git diff --check`;
17. suite completa diferencial contra baseline. Cualquier failure/error nuevo bloquea.

No arreglar deuda histórica fuera de alcance.

## Documentación

Actualizar según implementación real:

- `ARCHITECTURE.md`;
- `DATA_MODEL.md`;
- `FUNCTIONAL_COMPLETION.md`;
- `ROADMAP.md`;
- `STATUS.md`;
- `TESTING.md`;
- `CODEX_TASK.md` sólo al finalizar si corresponde.

## Commit/push

Si la implementación y pruebas quedan correctas con `NEW_REGRESSIONS=0`, queda autorizado:

- un único commit lógico de F14.2;
- push normal a `origin/main`;
- sin force, tag ni release.

Detenerse después del push. **No iniciar F14.3.**

Si requiere validación humana Windows, dejar F14.2 pendiente y entregar instrucciones exactas; no declararla CLOSED.

## Evidencia final requerida

- baseline y SHA final;
- diagnóstico y modelo durable elegido;
- archivos modificados;
- migración si corresponde;
- evidencia exacta de auto/manual, restart, active/recovery y pause interaction;
- comandos/resultados de pruebas;
- comparación completa `NEW_REGRESSIONS=0` o detalle;
- aspectos no verificados;
- commit/push;
- smoke humano requerido;
- confirmación F14.3 no iniciada.
