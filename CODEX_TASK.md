# CODEX_TASK — próxima tarea del Orquestador

Este archivo es un handoff operativo. Si hay conflicto, prevalecen `RULES.md`, `STATUS.md`, `ROADMAP.md`, `FUNCTIONAL_COMPLETION.md`, `ARCHITECTURE.md`, `DATA_MODEL.md` y `TESTING.md`.

## Próxima tarea

**F14.1 — corregir definitivamente `Crear a partir de esta`: preservar source y crear un proyecto nuevo con nombre elegido antes de persistir.**

Baseline publicado de producción: `54695cd0458e1d385aed7995d8d337bfb6447792`, más el commit documental posterior si `main` avanzó sólo en docs.

F14.2 NO está autorizada.

## Aclaración de producto vinculante

El comportamiento deseado NO es:

```
source → crear copia automática → seleccionar copia → renombrarla
```

El comportamiento correcto es:

```
source
→ Crear a partir de esta
→ pedir "Nombre del nuevo proyecto"
→ la persona escribe/confirma el nombre
→ recién entonces crear un segundo Project independiente
→ source y nuevo proyecto quedan ambos en Biblioteca
→ seleccionar/abrir el nuevo proyecto para empezar a trabajar
```

Ejemplo:

```
Martina - Playa
   ↓ Crear a partir de esta
Nombre del nuevo proyecto: [ Martina - Playa noche ]
   ↓ Confirmar

Biblioteca:
- Martina - Playa
- Martina - Playa noche
```

El source no se renombra, no se reemplaza y no desaparece.

## Contrato obligatorio

- Source: mismo `ProjectId`, nombre, ejecuciones, runtime, cola y evidencia antes/después.
- Clone: `ProjectId`, `ExecutionId` y `ChunkId` nuevos según F13.2.
- La UI solicita el nombre **antes de crear/persistir** el clone.
- Puede aparecer una sugerencia editable `Copia de <source>` o el siguiente nombre disponible.
- Confirmar un nombre válido y único crea el clone atómicamente con ese nombre.
- Cancelar/cerrar el prompt no crea ningún Project/Execution/chunk/archivo/QueueItem.
- Un conflicto normalizado de nombre falla claramente sin clone parcial.
- Tras éxito, source y clone deben coexistir en Biblioteca y el clone nuevo debe quedar seleccionado/abierto para continuar trabajando.
- `Renombrar proyecto` sigue siendo una operación separada para cambiar el nombre de un proyecto ya existente.
- No convertir el flujo en create-then-rename internamente: el nombre pedido debe formar parte de la operación atómica de creación.
- Queue duplicate puede conservar su política automática existente salvo que compartir la firma del caso de uso exija un cambio interno compatible; no agregar diálogos a Cola en esta corrección.
- No mover archivos, tocar outputs, runtime, attempts, artifacts, transitions ni recovery.
- No rediseñar Biblioteca fuera de lo mínimo necesario.

## Diseño esperado

Inspeccionar antes de decidir, pero preferir:

1. una frontera de aplicación de clone que pueda recibir un `target_name` explícito;
2. persistencia atómica del nuevo Project + Execution con ese nombre;
3. ruta automática existente para duplicación de cola preservada mediante nombre sugerido/autogenerado cuando no hay interacción humana;
4. en Biblioteca, un diálogo/modal pequeño o mecanismo equivalente claro de `Nombre del nuevo proyecto`, con sugerencia editable;
5. ningún registro durable antes de aceptar el nombre.

No acceder a SQLite desde el widget.

## Trabajo requerido

1. `git fetch origin`, `git pull --ff-only`, baseline limpio y `git diff --check`.
2. Leer autoridades y revisar flujo F13.2/F14.1 actual.
3. Agregar primero pruebas que demuestren:
   - source permanece intacto;
   - cancelación crea cero proyectos nuevos;
   - nombre explícito se usa al crear el clone;
   - conflicto no deja clone parcial;
   - source + clone quedan ambos listados;
   - clone queda seleccionado/abrible/editable después de confirmar;
   - restart conserva ambos nombres;
   - cola duplicate sigue funcionando.
4. Implementar la corrección mínima y atómica.
5. Eliminar o simplificar la solución específica de foco sólo si queda obsoleta; no conservar complejidad sin necesidad. Si sigue siendo útil tras confirmar el nombre, justificarla con test.
6. Ejecutar focales F14.1, F13.2, F13.6, F13.7/F13.10 afectados, persistencia, `compileall`, `git diff --check` y suite completa diferencial.
7. `NEW_REGRESSIONS` debe ser 0.
8. Actualizar docs según implementación real, dejando F14.1 pendiente de smoke humano final.
9. Si todo queda correcto, queda autorizado un único commit lógico y push normal a `origin/main`; sin force/tag/release.
10. Detenerse. No iniciar F14.2.

## Smoke humano posterior esperado

Sólo después de la implementación:

1. seleccionar un source;
2. pulsar `Crear a partir de esta`;
3. comprobar que se pide `Nombre del nuevo proyecto` antes de crear nada;
4. cancelar una vez y verificar que no apareció copia;
5. repetir, escribir un nombre distinto y confirmar;
6. comprobar que source y nuevo proyecto aparecen simultáneamente;
7. abrir ambos;
8. cerrar/reabrir app y confirmar persistencia de ambos nombres.

## Evidencia requerida

- causa/diseño elegido;
- archivos modificados;
- pruebas de atomicidad/cancelación/source intacto;
- resultados focales;
- diferencial completo con `NEW_REGRESSIONS=0`;
- SHA commit/push;
- confirmación F14.2 no iniciada.
