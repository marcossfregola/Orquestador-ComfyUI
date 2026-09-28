# CODEX_TASK — próxima tarea del Orquestador

Este archivo es un handoff operativo. Si hay conflicto, prevalecen `RULES.md`, `STATUS.md`, `ROADMAP.md`, `FUNCTIONAL_COMPLETION.md`, `ARCHITECTURE.md`, `DATA_MODEL.md` y `TESTING.md`.

## Próxima tarea

**F14.1 — corrección de validación humana: clone inmediatamente renombrable.**

Baseline publicado: `f7196ac84f3ae5ed49bb37e7495c78d28b1f9db4` más este commit documental si `main` avanzó sólo en docs.

## Hallazgo humano

En Windows se verificó:

1. crear `Prueba F14.1` funciona;
2. renombrarlo a `Prueba F14.1 Renombrado` funciona y el nombre anterior desaparece. **Esto es correcto**: rename cambia el nombre del mismo proyecto y no debe conservar una segunda copia;
3. al usar `Crear a partir de esta`, la copia nueva debe ser independiente, pero la persona no pudo cambiar de forma usable el nombre del nuevo proyecto abierto.

F14.1 queda REQUIERE CORRECCIÓN. F14.2 no está autorizada.

## Objetivo

Reproducir el flujo humano real y corregir el mínimo necesario para que una copia creada con `Crear a partir de esta` pueda renombrarse inmediatamente y persistir el nuevo nombre, sin alterar el proyecto fuente ni ninguna evidencia/runtime.

## Contrato obligatorio

- El proyecto fuente permanece con su `ProjectId`, nombre, ejecuciones y evidencia.
- El clone conserva `ProjectId` y `ExecutionId` nuevos.
- El clone recibe inicialmente el nombre durable automático `Copia de <origen>` / sufijo disponible.
- Después de crear el clone, éste debe quedar inequívocamente seleccionado en Biblioteca.
- El control `Nombre durable seleccionado` debe quedar habilitado para ese clone.
- Editar ese campo a un nombre único debe habilitar `Renombrar proyecto`.
- Renombrar debe actuar sobre el clone, no sobre el source.
- El nombre nuevo debe sobrevivir refresh y reinicio de la aplicación.
- El source debe seguir visible y abrirse con su nombre original.
- No convertir rename en clone: renombrar un proyecto existente sigue reemplazando sólo su nombre.
- No mover archivos, no cambiar IDs, no tocar cola/runtime/attempts/artifacts/transitions.
- No rediseñar Biblioteca ni agregar funciones ajenas. Si el problema es de selección/foco/estado del panel, corregir sólo esa frontera.

## Trabajo requerido

1. `git fetch origin` y `git pull --ff-only`; confirmar árbol limpio.
2. Leer las autoridades y revisar el flujo exacto:
   `clone_selected → GuiFacade.clone_library_execution → PreparationLibraryUseCase.clone → handle_result/render/_current_execution/_update_controls → rename_project`.
3. Reproducir primero con un test Qt/offscreen que modele exactamente:
   - crear/seleccionar source;
   - `Crear a partir de esta`;
   - verificar que source y clone existen;
   - verificar selección del clone;
   - editar `libraryProjectName`;
   - verificar botón de rename habilitado;
   - renombrar;
   - refresh/reopen;
   - verificar source intacto y clone con nombre nuevo.
4. Diagnosticar la causa real antes de editar. No asumir que el problema está en persistencia si la reproducción muestra que es UI/selección.
5. Implementar la corrección mínima.
6. Agregar/ajustar test de regresión específico del hallazgo humano.
7. Ejecutar:
   - `tests.test_f14_1_project_names`;
   - `tests.test_f13_6_library_gui`;
   - regresiones F13.2 clone + F13.10 GUI relevantes;
   - `python -B -m compileall -q src tests`;
   - `git diff --check`;
   - suite completa diferencial contra el baseline publicado, bloqueando cualquier regresión nueva.
8. No corregir deuda histórica fuera de alcance.
9. Actualizar `STATUS.md` y `TESTING.md` con el diagnóstico y la evidencia técnica, pero dejar F14.1 pendiente hasta repetir el smoke humano.
10. Si todo queda correcto, queda autorizado un único commit lógico de corrección F14.1 y push normal a `origin/main`, sin force/tag/release.
11. Detenerse. No iniciar F14.2.

## Evidencia final requerida

- causa raíz concreta;
- archivos modificados;
- test que reproduce el fallo previo y pasa después;
- resultados exactos de focales y regresión;
- `NEW_REGRESSIONS=0` o detalle;
- SHA del commit/push;
- instrucciones humanas mínimas para repetir únicamente el caso source→clone→rename→restart;
- confirmación de que F14.2 no se inició.
