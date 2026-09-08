# Modelo de dominio

Este documento define semántica, relaciones, invariantes y estados conceptuales; las secciones de estado F2, F5, F6 y F10 documentan las clases y el schema que ya fueron implementados.

## Conceptos centrales

### Proyecto

Es la definición durable del trabajo: nombre, intención, recursos iniciales, referencias, perfil de workflow, parámetros comunes, orden de chunks, carpeta de trabajo y resultado esperado. Un Proyecto puede tener más de una ejecución a lo largo del tiempo.

### Ejecución

Es una corrida concreta de un Proyecto. Mantiene su propio inicio, estado, decisiones efectivas, historial de intentos, checkpoints y resultado de esa corrida. Proyecto y Ejecución son conceptos distintos: editar la preparación no reescribe una ejecución histórica.

### Chunk

Es una unidad ordenada de generación dentro de una Ejecución. Tiene una intención/prompt, parámetros efectivos, un `first_frame` resuelto cuando corresponde, referencias, estado, outputs y una relación con sus Intentos. El chunk N y el chunk N+1 se vinculan por el frame de transición, no sólo por su índice.

### Intento

Es una ejecución concreta de un Chunk. Un retry crea un nuevo Intento; nunca borra ni transforma silenciosamente los intentos anteriores. Cada intento conserva parámetros efectivos, timestamps, fase, errores, outputs parciales y resultado.

### Artefacto

Es un archivo o evidencia producida, recibida o preservada por el proceso: input, output de ComfyUI, copia controlada del proyecto, frame de transición, metadata, log o ensamblado final. Mantiene trazabilidad hacia su origen (Proyecto, Ejecución, Chunk, Intento y fase cuando exista) y no se considera intercambiable sólo por tener un nombre parecido.

La evidencia de F1 agrega una regla operativa al concepto: el frame de transición debe identificarse como el último frame realmente decodificable del output válido, seleccionado por índice `N-1`, y conservar PNG lossless, metadata y hash. Un path temporal o un nombre por sí solo no constituye identidad.

### Workflow Profile

Es una descripción versionada del workflow soportado y de los bindings necesarios para traducir conceptos del proyecto a inputs reales. MiniMax H3 es el primer perfil, no una limitación estructural del dominio.

## Contrato único de configuración de generación (F11.0)

F11 adopta un único contrato conceptual, `GenerationConfig`, que se serializa y valida antes de iniciar una generación. La forma mínima común es:

```text
profile_ref
inputs.initial_image
inputs.references[0..6] (opcional, ordenadas)
chunk_plan.count (2 | 3)
chunk_plan.chunks[].prompt
parameters.megapixels
parameters.length
parameters.steps
parameters.fps
parameters.ref_image_size
parameters.also_ref_first_frame
orchestration_timeout_seconds
```

El mismo contrato se interpreta por scope, sin crear una segunda semántica en los widgets:

- **Proyecto:** defaults reutilizables y recursos de preparación.
- **Ejecución:** snapshot durable de la configuración elegida, incluyendo inputs, cantidad de chunks, prompts y parámetros efectivos de esa corrida.
- **Chunk:** prompt propio y sólo overrides de parámetros que hayan sido autorizados explícitamente.

La resolución de valores sigue siendo `project.defaults → execution.defaults → chunk.defaults`, con prioridad del chunk. La ejecución y cada intento conservan la configuración efectiva suficiente para reproducir qué se envió; una modificación posterior del proyecto no altera una ejecución histórica.

Para F11.1 el contrato exige una imagen inicial, referencias H3 opcionales (de 0 a 6, ordenadas y densas para la serialización de producto), 2 o 3 chunks y un prompt no vacío por chunk. La resolución usa una única política basada en megapíxeles; width y height efectivos continúan siendo derivados por el workflow. `ref_image_size` y `also_ref_first_frame` conservan sus defaults sin controles gráficos hasta F11.3. Seed, sampler, scheduler, IA y demás parámetros de backlog no forman parte de la superficie pública F11.1.

La validación contractual es fail-closed: `profile_ref` debe identificar una versión/hash compatible; las rutas de inputs deben ser relativas, contenidas, existentes y legibles; las referencias son opcionales (0..6), ordenadas y densas para la serialización de producto, y los prompts no pueden estar vacíos; `chunk_plan.count` sólo admite 2 o 3. `megapixels` debe ser numérico finito y positivo, sujeto al límite del profile; `length`, `steps` y `fps` deben ser enteros positivos (un `bool` no es un entero válido) y respetar los límites declarados por el profile/backend. `ref_image_size` se valida contra los valores admitidos por H3, `also_ref_first_frame` es booleano y `orchestration_timeout_seconds` es un entero positivo con default 1800. Claves desconocidas, combinaciones de resolución con dos políticas simultáneas o cualquier path inseguro rechazan la configuración antes del submit.

## Conceptos relacionados

**Regla F11.1 vigente:** las referencias son opcionales, de 0 a 6, y se serializan densamente en orden (`ref_image_0..N-1`), sin huecos ni imágenes dummy. Este límite de producto prevalece aunque H3 admita más ranuras.

- **Input:** recurso o valor que una fase consume, como imagen inicial, referencia, prompt o parámetro. Su procedencia, legibilidad y uso efectivo deben ser rastreables.
- **Output:** resultado observado de una fase, como un MP4 de chunk o metadata. Un output sólo puede usarse para avanzar cuando está identificado y validado según el contrato vigente.
- **Binding:** mapeo entre un concepto (por ejemplo `first_frame`, `prompt`, `length` o `seed`) y un punto de entrada del Workflow Profile. No obliga a que cada binding sea una entidad independiente.
- **Error:** hecho explícito con fase, contexto, timestamp, causa observable y posibilidad de retry/recovery. Nunca se convierte silenciosamente en éxito.
- **Frame de transición:** artefacto derivado del último fotograma exacto de un output válido; es el candidato a `first_frame` del chunk siguiente y conserva su origen. F1 demostró selección por índice decodificado, firma de píxeles equivalente y upload posterior mediante `subfolder/name`.
- **Ensamblado:** operación que combina chunks compatibles para producir un resultado final adicional, preservando los originales.
- **Estado:** representación del progreso conceptual de Proyecto, Ejecución, Chunk o Intento, sujeta a evidencia y transiciones permitidas.
- **Checkpoint/punto seguro:** registro durable que identifica hasta qué fase se puede continuar sin repetir trabajo válido. No es sólo un porcentaje.
- **Reconciliación:** comparación, después de una interrupción o al iniciar, entre estado durable, artefactos existentes y estado observable del backend para decidir continuar, validar, marcar error o crear un nuevo Intento.

## Relaciones

- Un Proyecto prepara cero o más Ejecuciones.
- Una Ejecución materializa una secuencia ordenada de Chunks.
- Cada Chunk puede tener uno o más Intentos, con a lo sumo un resultado elegido para avanzar según evidencia.
- Un Intento produce o referencia Artefactos y Errores.
- Un Artefacto conserva la trazabilidad de su origen y de las transformaciones posteriores.
- Una Ejecución usa un Workflow Profile versionado; el perfil y sus bindings no redefinen la semántica del dominio.
- El frame de transición elegido de un Chunk puede ser el Input `first_frame` del Chunk siguiente, con relación explícita de procedencia.
- El Ensamblado consume outputs de chunks seleccionados y produce otro Artefacto, sin sustituir los insumos.

## Estados conceptuales

Los nombres siguientes son vocabulario de F0; pueden refinarse sin alterar sus significados.

### Proyecto / Ejecución

`BORRADOR` → `LISTO` → `EJECUTANDO` → `COMPLETADO`  
Desde `EJECUTANDO` puede pasarse a `PAUSADO`, `ERROR` o `CANCELADO`, y una reconciliación puede devolver a un estado reanudable cuando exista un punto seguro.

- `BORRADOR`: preparación incompleta o editable.
- `LISTO`: preflight suficiente para intentar iniciar.
- `EJECUTANDO`: existe trabajo activo o avance coordinado.
- `PAUSADO`: no se solicita nuevo avance, pero el trabajo previo permanece.
- `ERROR`: existe una causa o inconsistencia que requiere decisión, retry o recovery.
- `COMPLETADO`: todos los chunks y el ensamblado requerido tienen evidencia válida.
- `CANCELADO`: la ejecución fue detenida de forma explícita; el trabajo previo se conserva.

### Chunk

`PENDIENTE` → `PREPARANDO` → `ENCOLADO` → `GENERANDO` → `VALIDANDO_OUTPUT` → `OUTPUT_DETECTADO` → `EXTRAYENDO_FRAME` → `COMPLETADO`.

Desde las fases activas puede llegarse a `ERROR` o `CANCELADO` según evidencia. Un `ERROR` puede originar otro Intento; `CANCELADO` no elimina intentos ni artefactos previos.

Un Chunk no se marca `COMPLETADO` si falta output válido, validación requerida, frame de transición cuando el chaining lo necesita, registro durable o evidencia equivalente definida por el perfil.

### Intento

Un Intento nace al comenzar una tentativa concreta, avanza por las fases disponibles y termina con resultado válido, error explícito o cancelación. Un retry siempre crea otro Intento y mantiene el vínculo con el anterior.

En F5 el límite de orquestación se configura por Attempt en las opciones efectivas de la defaults JSON persistidos (proyecto → ejecución → chunk; `WorkflowProfileRef` no es fuente de defaults) y vale exactamente 1800 segundos (30 minutos) por defecto, distinto de los transportes F3 (HTTP 10 s / WebSocket 5 s). Su expiración termina el Intento en fallo/bloqueo explícito y nunca autoriza retry/resubmit. La única elegibilidad automática es `FAILED` terminal explícito sin output verificado o fallo pre-submit con evidencia determinista de no aceptación backend. Nunca son elegibles `RUNNING`, `UNKNOWN`, timeout, evidencia ambigua/contradictoria, submit incierto, pérdida de evidencia, mismatch de procedencia/path, estado/output corrupto o cualquier caso donde pueda existir un job. El retry elegible crea exactamente un segundo Intento append-only y conserva todos los artefactos/evidencias; las condiciones ambiguas usan `NEEDS_MANUAL_REVIEW` o `BLOCKED_CORRUPT_STATE`, sin estado persistido nuevo.

## Invariantes

Corrección F5: `orchestration_timeout_seconds` (defaults JSON) es entero, bool inválido, `>0`, default 1800 s, merge proyecto→ejecución→chunk; se resuelve antes de cada Attempt, que no tiene options. Timeout no-retryable. `CANCELLED` nunca auto-retry F5 aunque F2 lo clasifique retryable; no redefine F2/F6. `prompt_id` sólo en `external_job_ref`, asignación única y persistencia inmediata; incertidumbre no reenvía.

1. Proyecto y Ejecución no se confunden ni comparten silenciosamente el estado mutable.
2. Chunk e Intento son distintos; un retry no reescribe el historial.
3. El chaining usa el último frame real del output válido del chunk anterior como `first_frame` del siguiente.
4. Un Artefacto conserva trazabilidad hacia su origen y no se reemplaza por nombre.
5. Un output válido no se regenera automáticamente sin necesidad demostrada.
6. `COMPLETADO` exige evidencia suficiente de todas las fases críticas.
7. Cancelar preserva el trabajo previo y no equivale a borrar o marcar éxito.
8. Un checkpoint sólo habilita continuar desde una fase segura; no autoriza repetir trabajo válido por defecto.
9. Recovery compara estado durable, artefactos y backend observable antes de elegir la acción.
10. Ninguna transición convierte un error desconocido en éxito.
11. El ensamblado final es adicional y no destruye chunks ni intermedios.
12. Los parámetros heredados y los overrides efectivos de cada chunk quedan distinguibles para poder reproducir el intento.
13. Los outputs parciales e intermedios de cada Intento se conservan como Artefactos de evidencia; F5 no ejecuta limpieza automática.

### Estado F5 (2026-08-30)

F5 **CLOSED — APPROVED**: Slices 1, 2, 3 y 4A completadas/auditadas. F6 **CLOSED — APPROVED** para recovery/retry durable de un chunk; no schema migration nueva.

## Checkpoints y recovery conceptual

Después de cada fase crítica, la aplicación registra durablemente el estado, referencias a artefactos y evidencia suficiente antes de avanzar. Un punto seguro típico es: output inequívoco identificado y validado, frame de transición extraído y validado, y relación con el siguiente input preparada o registrada.

F1 verificó que `prompt_id → history → output node → descriptor → archivo` permite correlación técnica, pero queue/history/jobs del backend son memoria de ComfyUI y no son el registro durable del dominio. La persistencia propia debe conservar la relación entre output, frame, upload y `first_frame`.

Al volver tras cierre, crash o reinicio:

1. leer el último estado durable;
2. inspeccionar los Artefactos esperados y existentes;
3. consultar el backend si la operación podría seguir viva;
4. comparar esas fuentes y clasificar el resultado como completo, reanudable, incompleto o inconsistente;
5. conservar todo lo encontrado;
6. continuar desde el checkpoint seguro, esperar/validar el output pendiente o crear un nuevo Intento con causa explícita.

F6 concreta esta frontera para un chunk individual mediante estado durable y una observación fresca del backend; la recuperación de una cadena multi-chunk, el chaining automático y el ensamblado productivo quedan abiertos para F7/F8.

## Estado implementado de F2

F2 está **CLOSED — APPROVED**. El modelo ejecutable mantiene las entidades Proyecto, Ejecución, Chunk ordenado, Intento append-only (incluido el historial de retry), Artefacto, Error y `TransitionFrame`. `TransitionFrame` conserva procedencia exacta y semántica N-1: es el último frame realmente decodificable del output válido y su origen queda vinculado al artefacto y chunk que lo produjo. `WorkflowProfileRef` es una referencia opaca opcional de Ejecución; `BackendJobRef` es una referencia opaca opcional de Intento, se asigna una sola vez y se preserva al reiniciar. Los parámetros heredados y los overrides efectivos quedan distinguibles.

El punto seguro se deriva del agregado durable y de los artefactos verificados requeridos; no existe una entidad `Checkpoint` persistida separada. No forman parte del dominio F2 los IDs ni bindings de nodos H3.

### Persistencia F2

La implementación usa SQLite versionado en una ruta de base de datos contenida dentro del proyecto (schema actual v2). Activa FK, inicializa y guarda atómicamente, rechaza versiones futuras y dispone de runner de migraciones; v2 añade de forma compatible los campos opcionales de materialización de `TransitionFrame`. Usa JSON canónico donde corresponde, mantiene Attempts/Artifacts/Errors append-only, protege stale/conflict, no reemplaza silenciosamente una DB corrupta o no-SQLite y valida en carga el grafo y la procedencia. Las rutas de artefactos propios son relativas al proyecto. `WorkflowProfileRef` y `BackendJobRef` se persisten con las semánticas opacas indicadas arriba.

La reconciliación implementada es pura y agnóstica del backend: recibe evidencia observada de backend, artefactos y transiciones y devuelve un plan determinista de decisión/acción, sin escrituras ocultas. Gana el primer gap no resuelto; preserva chunks completos; cada retry crea otro Intento. RUNNING con el mismo job ref activo produce WAIT; evidencia desconocida o discordante produce review/block. Una finalización externa verificada dentro de una ventana de crash sólo propone una acción explícita de reconciliación. Un frame de transición ausente o corrupto exige recovery específico de transición. El punto seguro avanza sólo con output durable requerido y evidencia de transición verificada; COMPLETE requiere que toda la cadena sea segura.

## Estado implementado de F6 — recovery durable de un chunk (2026-08-30)

F6 usa el schema SQLite v1 existente; no agrega tablas ni migraciones nuevas. La frontera ejecutable es `ResumeExecutionUseCase` y la frontera de planificación sigue siendo `RecoverExecutionUseCase`.

- **Execution:** se reabre desde SQLite con su `id`, `project_id`, defaults, estado y chunks; sólo se promueve a `SUCCEEDED` cuando el agregado durable y sus outputs cumplen la evidencia requerida.
- **Chunk:** conserva orden, estado, `execution_id`, defaults e historial de intentos. F6 valida una ejecución de un chunk; no encadena ni propaga automáticamente al siguiente.
- **Attempt:** es append-only por retry, con `number`, estado, output, evidence, `error_id` y `external_job_ref`. El primer Attempt permanece intacto cuando se crea el segundo y no se crea un tercero al agotar el presupuesto actual.
- **`external_job_ref`:** referencia opaca durable del job externo, asignada una vez al Attempt y usada para la observación fresca tras reopen; no existe una columna `prompt_id` separada.
- **Error durable:** `Attempt.error` se guarda en `errors` y su `error_id` se actualiza en la fila del Attempt; al reabrir se valida la propiedad `(project, execution, chunk, attempt)` y se recuperan código, mensaje e ID.
- **Output/evidence:** el output correlacionado y la evidencia de backend/validación se guardan en el Attempt; el completion exige referencia exacta, output único, validación física y frame decodificable.
- **Artifact:** el completion de un chunk exitoso persiste el `Artifact` de fase `OUTPUT` con la procedencia de proyecto, ejecución, chunk y Attempt y un path relativo seguro. El caso F6 validado conserva exactamente un artefacto de salida.
- **TransitionFrame:** se persiste con `source_output`, `source_attempt_id`, `source_frame_index` y `frame_count`; el índice debe ser `frame_count - 1` con `frame_count > 0`. Para el chunk único `target_chunk_id` es `NULL`; los enlaces futuros mantienen procedencia explícita.
- **Recovery:** `QUEUED`/`RUNNING` espera sin mutar; `COMPLETED` sólo completa mediante `HistoryResult` y el coordinador existente; `FAILED` terminal puede consumir el retry único. Desconocido, cancelado, ambiguo, mismatch de procedencia o evidencia incompleta termina en revisión/bloqueo fail-closed. Un agregado ya completo se reabre y resumes repetidos sin duplicar intentos, artefactos ni transiciones.

## Límites posteriores a F2

ComfyUI querying pertenece al adaptador F3; F6 consume una observación backend inyectada/reconciliable sin afirmar una nueva ejecución real. Las operaciones FFmpeg/FFprobe y el ensamblado permanecen en fronteras posteriores. F7 cubre recovery/chaining multi-chunk; GUI y validación visual universal siguen fuera de alcance.

`TransitionFrame.target_chunk_id` es nullable para el checkpoint del chunk único; los enlaces con target mantienen validación de procedencia y schema v2 (compatible con filas sin materialización).

## Estado implementado de F10 — materialización de transición (2026-09-01)

`MaterializedInputRef` es la referencia efectiva que ComfyUI devuelve para un input subido: `type="input"`, `subfolder`, `name` y `source_sha256`. `TransitionFrame.materialized_ref` es opcional para conservar esa referencia junto con el frame N-1 y su procedencia; se valida que el nombre/subcarpeta no permitan escapes y que el hash sea SHA-256 hexadecimal. La persistencia schema v2 guarda esos cuatro campos sin convertir el path absoluto del backend en autoridad durable.

En el E2E real de dos chunks, el frame `293/294` de chunk 0 se persistió con hash `ff3326b0fd903e2f6680d3985ea5afc17f4199533b20f8843faeeaeb49da0978` y referencia `orquestador/transitions/transition-52b5ac2a-0d2e-4e54-bc7c-2a79314f87e8-ff3326b0fd903e2f.png`. Tras cerrar/reabrir, esa referencia se reutilizó para bindear chunk 1 sin reupload; los dos chunks, dos artefactos y dos transiciones quedaron durables y la ejecución terminó `succeeded`.
