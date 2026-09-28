# F14 — Cierre funcional del producto actual

**Estado:** EN CURSO — F14.1 implementada técnicamente, pendiente de validación humana Windows.
**Fecha de decisión:** 2026-09-27.

Este documento es el contrato ejecutable de F14. El estado vivo continúa en `STATUS.md`, el orden decidido en `ROADMAP.md`, las reglas permanentes en `RULES.md` y la semántica implementada debe quedar actualizada en `ARCHITECTURE.md` y `DATA_MODEL.md` dentro de cada slice.

## Objetivo

Terminar y robustecer el funcionamiento ya existente antes de agregar características nuevas o dedicar una etapa al pulido visual.

F14 corrige tres huecos funcionales comprobados en la versión cerrada F13.10:

1. la identidad humana de un proyecto no es durable ni renombrable de forma independiente de su `ProjectId`;
2. el scheduler arranca automáticamente y no existe una política elegible auto/manual de inicio;
3. la ejecución puede considerarse terminada al completar los chunks aunque el MP4 final todavía no haya sido ensamblado y validado.

F11.6, pulido visual/UX, permanece fuera de F14 y se tratará después.

## No-alcance

F14 no incorpora nuevos modelos, IA, cloud, multi-GPU, prioridades inteligentes, búsqueda avanzada, etiquetas/carpetas, timeline, edición de video, integración con Visor ni rediseño visual general.

No se aprovecha F14 para refactors ajenos, cambios de stack ni limpiezas oportunistas.

## Reglas comunes a todas las slices

- Inspeccionar el estado real antes de modificar producción.
- Mantener `UI → aplicación/casos de uso → dominio`.
- La UI no accede directamente a SQLite, ComfyUI ni FFmpeg/FFprobe.
- Toda persistencia nueva debe ser incremental, migrable y compatible con bases existentes.
- No modificar ni reutilizar IDs técnicos ya persistidos.
- No mover, renombrar, sobrescribir ni borrar outputs existentes por cambios administrativos.
- No crear una segunda ruta de submit a ComfyUI.
- Recovery y retry deben fallar cerradamente ante ambigüedad.
- Una slice no avanza a la siguiente hasta pruebas, evidencia, auditoría y aprobación.
- Cada slice debe actualizar los documentos autoridad afectados.
- El commit de una slice debe contener sólo su cambio lógico y su documentación.

---

## F14.1 — Nombre durable y renombrado de proyectos

### Problema verificado

En el baseline F13.10, `Project` contiene `id + defaults` y la tabla `projects` persiste `id + defaults`. La Biblioteca usa `ProjectId` como identidad visible. Un clone puede mostrarse como `Copia de <origen>` sólo durante la sesión que lo crea y, tras recargar, caer en `Proyecto generado` porque no existe nombre ni lineage durable.

### Resultado de producto

La persona trabaja con nombres humanos; los IDs técnicos permanecen internos, opacos e inmutables.

Ejemplo:

```text
Proyecto: Martina - Playa
  Ejecución #1 — succeeded
  Ejecución #2 — draft
```

### Contrato

- `ProjectId` sigue siendo la identidad técnica y nunca cambia al renombrar.
- `Project` obtiene un nombre durable separado del ID.
- El nombre se normaliza con la misma política Unicode NFC + `casefold()` ya usada por presets/plantillas.
- Los nombres de proyecto deben ser no vacíos y únicos bajo esa normalización para evitar selección humana ambigua.
- Crear un proyecto desde la UI recibe un nombre humano y genera internamente un ID opaco nuevo.
- La Biblioteca lista, ordena y selecciona por nombre visible, conservando el ID técnico sólo como identidad interna.
- Renombrar es una operación administrativa atómica y debe poder hacerse aunque existan ejecuciones históricas, queued o running: no cambia configuración, lifecycle, cola, archivos, outputs, artifacts ni recovery.
- `Crear a partir de este` genera un proyecto independiente con ID nuevo y nombre durable derivado `Copia de <nombre>`; si ya existe, asigna un sufijo determinista `(2)`, `(3)`, etc.
- Cola y demás proyecciones que muestran identidad de proyecto deben consumir el nombre durable; nunca deben exigir que la persona copie/escriba UUIDs.
- No persistir lineage ficticio de clones en esta slice. El nombre de copia no implica una relación dinámica con el origen.

### Migración

La migración debe preservar todos los `ProjectId` actuales y toda evidencia asociada.

Para proyectos existentes:

- si el ID no es un UUID válido, usar inicialmente ese ID como nombre humano;
- si el ID es UUID, usar un fallback honesto y determinista `Proyecto generado <short-id>`;
- si una normalización produjera colisión, resolverla de forma determinista con sufijo sin perder ningún proyecto.

La implementación concreta de schema se decide tras inspección, pero un campo durable nuevo exige migración versionada y pruebas desde schema 7.

### Aceptación

- Crear → cerrar app → abrir conserva nombre.
- Renombrar → cerrar → abrir conserva nombre nuevo.
- Rename no cambia `ProjectId`, `ExecutionId`, `execution_number`, QueueItem, attempts, artifacts, transitions ni paths.
- Proyectos históricos siguen abriendo.
- Clone conserva toda la semántica F13.2 y recibe nombre durable independiente.
- Colisiones de nombres fallan claramente o se resuelven sólo donde este contrato define autosufijo.
- La UI normal no solicita ni muestra UUID como identidad primaria.

### Pruebas mínimas

- migración schema 7 desde proyectos con ID legible y UUID;
- round-trip de nombre;
- create/rename y conflictos normalizados;
- rename con draft, queued, active y terminal;
- clone + autosufijo;
- restart/reopen;
- Biblioteca y Cola proyectando nombre;
- regresión F13.1/F13.2/F13.6/F13.7/F13.10;
- `compileall` y `git diff --check`.

### Validación humana

Smoke Windows corto: crear, renombrar, cerrar/reabrir, clonar y volver a seleccionar por nombre. No requiere generación real de video.

### Estado de implementación F14.1

La migración SQLite 7→8, los casos de uso de alta/renombrado, la asignación durable de nombre a clones y las proyecciones de Biblioteca/Cola están implementados y cubiertos por pruebas automáticas. La suite completa no está globalmente verde; la comparación reproducible contra el snapshot del baseline `c14aa524c770b994330a04c55e615bc110313fda` dio `NEW_REGRESSIONS=0`. El cierre de F14.1 queda pendiente hasta completar el smoke Windows indicado arriba. F14.2 no se inició.

---

## F14.2 — Política de inicio de cola automática/manual

### Problema

El scheduler F13.8/F13.10 inicia automáticamente con el runtime. Esto debe seguir disponible, pero el producto necesita un modo manual que permita abrir la aplicación, revisar Biblioteca/Cola y no iniciar nuevos trabajos hasta una acción explícita.

### Contrato

- Configuración durable `auto | manual`; default `auto` para preservar comportamiento existente.
- `auto`: comportamiento actual.
- `manual`: cada arranque de la aplicación comienza con el permiso de despacho cerrado.
- En manual, abrir la app no puede reclamar un nuevo QueueItem ni producir un submit nuevo.
- `Iniciar/Reanudar cola` abre explícitamente el permiso de despacho de esa sesión.
- La política de inicio y la pausa de cola son conceptos distintos. No reutilizar `paused` para simular modo manual.
- Cambiar a manual nunca cancela un trabajo active/running.
- Recovery puede observar y reconciliar evidencia existente de forma segura, pero el modo manual no autoriza nuevos claims ni nuevos submits hasta la acción explícita.
- No se agrega `/interrupt` running.
- El setting debe sobrevivir reinicio; el permiso manual de la sesión no debe sobrevivirlo.

### Aceptación

- Auto conserva la conducta F13.10.
- Manual + restart deja items queued sin claim/submit.
- Pulsar Iniciar/Reanudar permite exactamente un scheduler normal, sin segunda ruta.
- Pausar/reanudar conserva sus invariantes actuales.
- Un active sobreviviente nunca se duplica.
- Cambiar política no altera orden ni contenido de cola.

### Pruebas mínimas

- persistencia/migración del modo;
- auto regression;
- manual cold start;
- manual con queued;
- manual con active sobreviviente;
- interacción con pause/resume;
- no doble claim/submit;
- restart;
- regresión F13.7–F13.10;
- Qt offscreen de controles funcionales mínimos;
- `compileall` y `git diff --check`.

### Validación humana

Windows: abrir en manual con trabajo en cola y comprobar que nada inicia hasta pulsar Iniciar/Reanudar; luego comprobar auto.

---

## F14.3 — Ensamblado como requisito de finalización real

### Problema

El producto ya tiene un adaptador de ensamblado fail-closed y validación FFprobe, pero el ensamblado está expuesto como operación separada. Completar todos los chunks no debe equivaler a completar la ejecución de producto.

### Contrato funcional

El flujo final pasa a ser:

```text
chunks completos
→ finalización pendiente
→ ensamblado del MP4 único
→ validación del MP4 final
→ evidencia durable del final
→ ejecución completada
→ QueueItem liberado
```

- Todos los chunks pueden estar correctos sin que la ejecución esté todavía completada.
- El MP4 final debe generarse automáticamente dentro de una ubicación durable y controlada por el producto. Reutilizar una convención existente si la inspección encuentra una; no depender de un diálogo manual Save As para que el scheduler pueda finalizar.
- El resultado final se valida con la frontera FFmpeg/FFprobe existente o su evolución acotada.
- Chunks y frames intermedios se preservan siempre.
- Un fallo de ensamblado no regenera chunks y no crea submits a ComfyUI.
- Debe existir evidencia durable suficiente para distinguir: pendiente, ensamblando, final válido y fallo de ensamblado.
- Retry de ensamblado actúa exclusivamente sobre la finalización y conserva los chunks ya válidos.
- Recovery después de cierre/crash reconcilia el estado de finalización antes de liberar la cola.
- Nunca se declara éxito por la mera presencia de un archivo: debe validarse procedencia/estado/ruta conforme a las autoridades existentes.
- Un destino ya existente o evidencia ambigua falla cerradamente; no se sobrescribe.
- La implementación debe elegir el modelo durable mínimo correcto después de inspeccionar el estado real. No forzar la semántica de fallo de ensamblado dentro del retry de chunks si eso puede regenerar video.
- La UI sólo debe exponer estado y acción funcional mínima de retry/export; el rediseño visual queda para F11.6.

### Aceptación

- El último chunk exitoso no libera por sí solo el QueueItem como ejecución finalizada.
- Ensamblado + validación exitosos producen un final durable y recién entonces permiten estado final y avance de cola.
- Fallo de FFmpeg/FFprobe conserva todos los chunks y bloquea finalización con causa visible.
- Retry de ensamblado no toca ComfyUI, Attempts de chunks ni TransitionFrames.
- Restart en finalización pendiente/fallida conserva el punto seguro y permite continuar/reintentar sin regeneración.
- Una ejecución histórica ya válida sigue siendo legible tras migración.

### Pruebas mínimas

- happy path chunks→assembly→final;
- fallo FFmpeg;
- fallo FFprobe/validación;
- retry sólo assembly;
- restart antes/durante/después de finalización;
- destino existente y output ambiguo;
- no submit a ComfyUI durante assembly retry;
- queue no avanza antes de final durable;
- regresión F7/F8/F11.5/F13.8/F13.9/F13.10;
- pruebas reales FFmpeg/FFprobe donde corresponda;
- `compileall` y `git diff --check`.

### Validación humana

Una cadena real representativa en Windows: observar chunks, ensamblado automático, MP4 final reproducible y continuidad. Si se prueba un fallo de ensamblado, el retry debe actuar sólo sobre el ensamblado.

---

## F14.4 — Regresión integral y cierre funcional

### Objetivo

Demostrar que F14.1–F14.3 conviven sin regresiones y declarar cerrado el funcionamiento actual antes de F11.6.

### Incluye

- suite completa y focales relevantes;
- migración desde una base representativa anterior;
- restart/recovery;
- Biblioteca por nombre;
- clone;
- cola auto/manual;
- generación secuencial;
- finalización con ensamblado;
- retry de chunk y retry de ensamblado como autoridades separadas;
- evidencia documental final.

### No incluye

Pulido visual F11.6 ni nuevas capacidades.

### Validación humana final

Flujo Windows representativo de punta a punta. No afirmar validación visual de continuidad/calidad si no fue realizada por la persona.

---

## Orden obligatorio

```text
F14.1 → auditoría/aprobación
F14.2 → auditoría/aprobación
F14.3 → auditoría/aprobación
F14.4 → auditoría/aprobación
F11.6 después, en una etapa separada
```

Codex no debe avanzar automáticamente de una slice a la siguiente.
