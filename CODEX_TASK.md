# CODEX_TASK — F14.3 ensamblado como requisito de finalización real

## Estado autorizado

F14.1 y F14.2 están CLOSED — APROBADAS.

F14.3 es la próxima slice. F11.6 permanece fuera de alcance hasta cerrar F14.

Trabajar exclusivamente en el repo existente `C:\Codex\Orquestador-ComfyUI`. No crear proyecto nuevo ni duplicar repo.

## Objetivo de producto

Cambiar la semántica actual:

`chunks completos → ejecución/QueueItem finalizados`

por:

`chunks completos → finalización pendiente → ensamblado automático MP4 → validación → evidencia durable del final → ejecución completada → QueueItem liberado`.

El MP4 final validado pasa a ser requisito de éxito real de la ejecución.

## Antes de modificar producción

1. Sincronizar `main` por fast-forward y verificar HEAD/origin, árbol, índice y `git diff --check`.
2. Leer como autoridades:
   - `RULES.md`
   - `STATUS.md`
   - `ROADMAP.md`
   - `FUNCTIONAL_COMPLETION.md`
   - `ARCHITECTURE.md`
   - `DATA_MODEL.md`
   - `TESTING.md`
   - este `CODEX_TASK.md`.
3. Inspeccionar estado real de:
   - dominio Execution/Chunk/Attempt;
   - persistencia SQLite schema 9 y migraciones;
   - `application/assembly.py`;
   - `adapters/assembly.py`;
   - scheduler F13.8;
   - recovery F13.9;
   - cierre de QueueItem;
   - snapshot/capabilities/UI actual;
   - rutas de outputs y convenciones de proyecto.
4. Definir explícitamente:
   - modelo durable mínimo para finalización;
   - estados/transiciones;
   - ubicación determinista del MP4 final;
   - cómo registrar procedencia/validación;
   - cómo distinguir fallo de chunk de fallo de ensamblado;
   - cómo funciona retry exclusivo de ensamblado;
   - recuperación tras crash en cada fase.
5. Si la inspección revela una ambigüedad arquitectónica que pueda comprometer datos o recovery, detenerse con diagnóstico antes de implementar.

## Contrato obligatorio

- El último chunk exitoso NO libera el QueueItem.
- Ensamblado ocurre automáticamente por el scheduler/orquestación existente, no mediante un diálogo Save As.
- Reutilizar `AssembleExecutionUseCase` / `FFmpegAssemblyAdapter` o evolucionarlos de forma acotada; no crear una segunda implementación FFmpeg.
- Validar el final con FFprobe antes de persistir éxito.
- Chunks, outputs y transition frames se preservan.
- Fallo de ensamblado no genera ni reintenta chunks y no llama ComfyUI.
- Retry de ensamblado actúa sólo sobre finalización.
- Recovery tras cierre/crash reconcilia finalización antes de liberar la cola.
- Nunca considerar éxito sólo por presencia de un archivo.
- Destino existente/ambiguo falla cerrado; no sobrescribir.
- UI no llama FFmpeg, SQLite ni ComfyUI.
- No tocar F11.6, nuevos workflows, IA, cloud, multi-GPU ni features ajenas.
- No usar ChatGPT–Codex Bridge como dependencia runtime.

## Diseño esperado, sujeto a inspección

Preferir una única autoridad durable de finalización asociada a la Execution, con estados suficientes para representar como mínimo:

- pendiente;
- ensamblando/iniciada con evidencia recuperable;
- final válido;
- fallo de ensamblado.

No introducir más estados/entidades de los necesarios.

La ruta final debe ser determinista y contenida bajo el project root, con nombre no ambiguo y publicación no destructiva. Si el archivo ya existe sin evidencia durable compatible, bloquear.

## Recovery

Cubrir explícitamente crash:

- después del último chunk y antes de iniciar ensamblado;
- durante FFmpeg antes de publicación;
- después de publicar pero antes de persistir evidencia;
- después de persistir evidencia pero antes de liberar QueueItem;
- con evidencia contradictoria/ambigua.

La reconciliación debe preservar el último punto seguro y jamás regenerar chunks por un fallo de finalización.

## Pruebas mínimas

Agregar tests focales F14.3 que cubran:

1. happy path chunks completos → assembly → validación → final durable → QueueItem finalizado;
2. QueueItem no avanza sólo porque terminaron los chunks;
3. fallo FFmpeg;
4. fallo FFprobe/final validation;
5. destino ya existente/ambigüedad;
6. retry sólo assembly con cero submits ComfyUI y cero Attempts de chunk nuevos;
7. restart antes/durante/después de finalización;
8. archivo final publicado pero evidencia durable incompleta;
9. evidencia durable final coherente tras restart;
10. regresión F7/F8/F11.5/F13.8/F13.9/F13.10/F14.2;
11. `compileall`;
12. `git diff --check`.

Ejecutar pruebas reales FFmpeg/FFprobe donde el entorno lo permita y separar claramente mocks de ejecución real.

Hacer comparación diferencial contra el baseline previo a F14.3; no esconder fallos históricos y reportar `NEW_REGRESSIONS`.

## Documentación a actualizar dentro de F14.3

Como mínimo:

- `STATUS.md`
- `ROADMAP.md`
- `FUNCTIONAL_COMPLETION.md`
- `ARCHITECTURE.md`
- `DATA_MODEL.md`
- `TESTING.md`

Sólo después de que código y pruebas reflejen el contrato real.

## Validación humana requerida antes de cierre

Una cadena real representativa en Windows:

- observar generación secuencial de chunks;
- comprobar que al terminar el último chunk la ejecución todavía pasa por finalización;
- observar ensamblado automático;
- abrir/reproducir el MP4 final;
- comprobar continuidad y orden de chunks;
- confirmar que el QueueItem se libera/finaliza sólo después del MP4 válido.

Si se ejerce un fallo de ensamblado, el retry debe actuar únicamente sobre assembly y no volver a generar videos.

## Git

- No force.
- No tags/releases.
- No push hasta tener la etapa técnica auditada y autorización de cierre, salvo autorización explícita posterior.
- Un commit lógico para F14.3 cuando corresponda.
- Revisar diff completo antes de proponer commit.

## Entrega obligatoria

Entregar:

- baseline exacto;
- inspección y diseño elegido;
- archivos modificados;
- migración/modelo durable;
- invariantes;
- pruebas y resultados;
- comparación diferencial;
- evidencia FFmpeg/FFprobe real si se ejecutó;
- riesgos/no verificado;
- diff/estado Git;
- confirmación de que F14.4 no fue iniciada;
- pasos exactos del smoke humano Windows.

Detenerse para auditoría antes de declarar F14.3 cerrada.
