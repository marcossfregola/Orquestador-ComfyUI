# Modelo de dominio

Este documento define semántica, relaciones, invariantes y estados conceptuales; la sección de estado F2 documenta las clases y el schema que ya fueron implementados.

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

## Conceptos relacionados

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

La política concreta de integración con ComfyUI, ensamblado productivo y recuperación contra backend queda abierta para fases posteriores.

## Estado implementado de F2

F2 está **CLOSED — APPROVED**. El modelo ejecutable mantiene las entidades Proyecto, Ejecución, Chunk ordenado, Intento append-only (incluido el historial de retry), Artefacto, Error y `TransitionFrame`. `TransitionFrame` conserva procedencia exacta y semántica N-1: es el último frame realmente decodificable del output válido y su origen queda vinculado al artefacto y chunk que lo produjo. `WorkflowProfileRef` es una referencia opaca opcional de Ejecución; `BackendJobRef` es una referencia opaca opcional de Intento, se asigna una sola vez y se preserva al reiniciar. Los parámetros heredados y los overrides efectivos quedan distinguibles.

El punto seguro se deriva del agregado durable y de los artefactos verificados requeridos; no existe una entidad `Checkpoint` persistida separada. No forman parte del dominio F2 los IDs ni bindings de nodos H3.

### Persistencia F2

La implementación usa SQLite schema v1 en una ruta de base de datos contenida dentro del proyecto. Activa FK, inicializa y guarda atómicamente, rechaza versiones futuras y dispone de runner de migraciones; el rollback está probado mediante una migración sintética sólo de test (no se declara migración productiva v2). Usa JSON canónico donde corresponde, mantiene Attempts/Artifacts/Errors append-only, protege stale/conflict, no reemplaza silenciosamente una DB corrupta o no-SQLite y valida en carga el grafo y la procedencia. Las rutas de artefactos propios son relativas al proyecto. `WorkflowProfileRef` y `BackendJobRef` se persisten con las semánticas opacas indicadas arriba.

La reconciliación implementada es pura y agnóstica del backend: recibe evidencia observada de backend, artefactos y transiciones y devuelve un plan determinista de decisión/acción, sin escrituras ocultas. Gana el primer gap no resuelto; preserva chunks completos; cada retry crea otro Intento. RUNNING con el mismo job ref activo produce WAIT; evidencia desconocida o discordante produce review/block. Una finalización externa verificada dentro de una ventana de crash sólo propone una acción explícita de reconciliación. Un frame de transición ausente o corrupto exige recovery específico de transición. El punto seguro avanza sólo con output durable requerido y evidencia de transición verificada; COMPLETE requiere que toda la cadena sea segura.

## Límites posteriores a F2

ComfyUI querying pertenece al adaptador F3; las operaciones FFmpeg/FFprobe y el ensamblado permanecen en fronteras posteriores. F2 no implementa recovery real contra ComfyUI, bindings/profile H3, GUI, orquestación productiva, chaining largo, ensamblado productivo ni validación visual universal.

`TransitionFrame.target_chunk_id` es nullable para el checkpoint del chunk único; los enlaces con target mantienen validación de procedencia y schema v1.
