# Integración conceptual con ComfyUI

ComfyUI es el backend de inferencia del primer release. La aplicación lo usa mediante un adaptador detrás de contratos propios; no es la UI principal ni una dependencia del dominio.

## Evidencia actual de F1

La instalación real usada en el spike expone ComfyUI core `0.33.0` en `http://127.0.0.1:8188`. El workflow UI canónico `Prueba Orquestador.json` conserva SHA-256 `3070EB659A0BDB3D8392B0D203F6B4B86409709A20143280473A12C44BA4A7`; no es un prompt API JSON y no fue modificado.

Se verificaron, mediante consultas o ejecuciones controladas, `/system_stats`, `/queue`, `/prompt`, `/history`, `/history/{prompt_id}`, `/object_info`, `/object_info/{class}`, `/features`, `/api/jobs`, `/api/jobs/{id}`, `/upload/image`, `/view` y WebSocket `/ws`.

`queue` y `history` son memoria observable de ComfyUI. No sustituyen la persistencia durable del Orquestador.

## Responsabilidad del adaptador

La unidad F3-1 implementa un cliente HTTP local configurable para `/system_stats`, `/prompt`, `/queue` y `/history/{prompt_id}`. Sus modelos son internos y reutilizan `BackendJobRef`; las respuestas malformadas no se convierten en éxito y los estados no determinables quedan explícitamente `unknown`. F3-2 añade observación WebSocket genérica con transporte inyectable, correlación estricta y reconciliación acotada; outputs y bindings H3 permanecen fuera de alcance.

El adaptador debe encapsular, según evidencia de la instalación real:

- health y endpoint configurable;
- carga o preparación de un workflow;
- aplicación de bindings y envío del trabajo;
- identificación inequívoca de la solicitud/job;
- queue, seguimiento, history y eventos/progreso;
- detección y recuperación de reconexiones;
- localización o consulta de outputs;
- traducción de respuestas y fallos a errores explícitos;
- cancelación/interrupción sólo con las capacidades realmente comprobadas.

La aplicación no debe depender de IDs de nodos, rutas de salida, HTTP, WebSocket o nombres propios del backend. Esos detalles pertenecen al adaptador y al perfil.

## Workflow Profiles

Un Workflow Profile es un contrato versionado que describe un workflow concreto, sus requisitos, compatibilidad y bindings. El primer perfil es MiniMax H3. H3 no se reparte por todo el núcleo ni limita la semántica del dominio.

Como mínimo, el perfil debe poder expresar conceptualmente:

- imagen inicial y `first_frame`;
- prompt;
- referencias y su orden;
- length/duración;
- steps;
- resolución/MP;
- FPS;
- seed o política de seed;
- output y su identificación.

El contrato observado del primer perfil H3 incluye, dentro del adaptador/profile:

- `LoadImage` node 114 → `ImageCropV2` 127 → `ImageScaleToTotalPixels` 119 → `GetImageSize` 120 → `MiniMaxH3HybridRefAndKeyframe` 129 `first_frame`;
- `width` y `height` de H3 permanecen enlazados a las salidas 0 y 1 de node 120;
- `ref_images.ref_image_0..5` son seis slots densos, ordenados y conectados a los escalados correspondientes;
- `prompt`, `length`, FPS y `ref_image_size` se inyectan en sus inputs API reales; steps, seed, sampler y scheduler permanecen en nodos separados y no son bindings H3 del perfil F4;
- node 92 `SaveVideo` expone el descriptor `filename/subfolder/type` usado para resolver el output.

Estos IDs y nombres son evidencia del profile H3 instalado; no deben filtrarse al dominio.

Un cambio incompatible del workflow debe fallar durante preflight, antes de iniciar una sesión larga, con un error claro. La decisión de diseño F1 queda registrada: un Workflow Profile/manifest versionado y autocontenido, con bindings declarativos y validación de compatibilidad en preflight; los IDs de nodo y `class_type` quedan aislados detrás del profile/adapter; la correlación determinista de outputs usa `prompt_id`/history y el descriptor de `SaveVideo`. El esquema formal, las pruebas de compatibilidad y la implementación del profile F4 están **CLOSED — APPROVED**; la frontera del adaptador consumidor de ComfyUI permanece en F3.

## Bindings conceptuales

Un binding traduce un concepto del proyecto a un input real del workflow. Debe declarar suficiente información para validar que el objetivo existe, es del tipo esperado y no está ocupado por otra semántica. No se asume que cada binding sea una clase o tabla.

Ejemplos conceptuales:

```text
first_frame  -> node/input
prompt       -> node/input
length       -> node/input
steps        -> node/input
resolution   -> node/input
fps          -> node/input
seed         -> node/input
reference_1  -> node/input
...
```

Los bindings definitivos y su validación productiva todavía requieren formalización; F1 verificó los nombres y enlaces del primer profile H3, seis referencias, uploads e inyección externa de imágenes.

## Preflight de integración

Antes de iniciar una ejecución larga se debe comprobar:

- ComfyUI disponible y endpoint accesible;
- workflow y versión compatibles;
- bindings resolubles y tipos válidos;
- imagen inicial y referencias legibles;
- prompts y parámetros dentro de límites;
- carpeta de salida escribible;
- correlación posible entre job, history y output;
- cancelación y reconexión conocidas o declaradas como no disponibles;
- FFmpeg/FFprobe disponibles para las fases que los requieren.

Fallos de preflight deben ocurrir en segundos y no después de un render largo.

F1 demostró este preflight con el workflow canónico, los assets baseline y los presets corto y largo. Las variantes B3–B7 se construyeron en memoria y se compararon por fingerprint antes del POST.

## Outputs y progreso

El adaptador debe identificar el output correcto sin depender de una captura de pantalla o de un nombre ambiguo. La aplicación validará que el archivo terminó de escribirse y que es legible antes de extraer el frame de transición.

Si el backend ofrece progreso real del sampler, se puede exponer como evidencia. Si no, sólo se muestran fases y eventos verificables; no se inventan porcentajes ni ETA.

La correlación inequívoca observada es:

`prompt_id` → `history` → output node 92 → `filename/subfolder/type` → archivo físico.

No se usa `mtime`, “archivo más reciente” ni heurística de nombre. `api/jobs/{id}` aporta estado y conteo, pero no reemplaza esta correlación ni una persistencia propia.

## Cancelación y recuperación

**HISTORICAL/INTERIM SPIKE:** la interrupción running mediante `/interrupt` y el caso pending-delete fueron experimentales, no semántica productiva. La cancelación final F3-4 es pending-only mediante un único `POST /queue` dirigido, sin `/interrupt` ni clear, con verificación fresca.

## FFmpeg/FFprobe

El adaptador ComfyUI no absorbe las operaciones exactas de video. Un adaptador separado valida outputs, obtiene metadata y extrae el último frame realmente decodificado por índice `N-1` a PNG lossless. F1 probó la firma `framemd5` con formato de píxel equivalente.

F1 también probó concat demuxer con `-c copy` para dos MP4 H.264 compatibles, preservando los originales. La política general de re-encode, deduplicación y ensamblado productivo sigue abierta.

## Resultado F1 y límites abiertos

B2–B7 demostraron, en ejecuciones controladas, derivación del prompt API, overrides externos de prompt/referencia/first frame, upload de assets y separación conceptual entre Workflow Profile, Reference Set, First Frame, Prompt/Chunk, Preset y Output.

C1 demostró extracción exacta del último frame decodificado. C2 demostró un chaining real de dos chunks: output → frame → upload → `first_frame`. C3 demostró un ensamblado técnico y recibió validación humana positiva de ese seam concreto.

Continúan abiertos el recovery/orquestación después de crash/reinicio, el retry productivo, la semántica de cancelación a nivel de pipeline/dominio y la política para trabajos running; la cancelación backend segura pending-only de F3-4 está cerrada y live validada. También siguen abiertos persistencia durable, chaining largo, ensamblado productivo, concurrencia segura, GUI y generalización de la continuidad visual. No se adopta ni forkeará automáticamente un proyecto externo.

### MAKE / REUSE / ADAPT (decisión F1)

- REUSE: API nativa ComfyUI y FFmpeg/FFprobe, siempre detrás de adaptadores propios.
- ADAPT/EVALUATE después: `comfy-python-sdk`/API v2; FlowDirector sólo patrones; VideoChunkTools sólo ideas/utilidades selectivas; wrappers o loop scripts comunitarios sólo patrones.
- MAKE: dominio, orquestación, persistencia, recovery, UI, estados, intentos, assembly y bindings de producto. No se establece dependencia estructural externa.

## Límites

El primer release usa ComfyUI local como backend. Backend remoto/cloud, múltiples backends y otros modelos/workflows están fuera de alcance; su posible incorporación queda en [BACKLOG.md](BACKLOG.md).
# F3-2 URL contract

El adaptador HTTP recibe sólo endpoints `http(s)`; F3-2 deriva `ws(s)` exactamente una vez y el transporte WebSocket consume la URL final sin re-normalizarla. Los timeouts específicos de `websocket-client` se normalizan en el límite del transporte a evidencia interna de timeout; la capa de observación permanece independiente de la dependencia.

# F3 live evidence (2026-08-28)

Read-only GETs to `127.0.0.1:8188` returned HTTP 200: `/system_stats` reported ComfyUI `0.33.0` with non-empty `system` fields (`os`, RAM and version metadata); `/queue` returned empty `queue_running` and `queue_pending`; `/history` returned a mapping of prompt IDs to history records. No prompt was enqueued and no ComfyUI files were modified.

F3-3 añade correlación lógica genérica, sin filesystem ni selección H3. La validación live real aislada de WS/history, descriptor lógico y ruta física se completó; H3 sigue reservado a F4.
# F3-4 cancellation contract

La evidencia histórica/spike de F1 sobre “interrupción básica” no es una capacidad de producción. En ComfyUI 0.33.0, el handler HTTP nativo `/interrupt` es no atómico; el adaptador seguro F3-4 no lo usa y rechaza fail-closed la cancelación de trabajos running. La eliminación `/queue` acepta `{"delete": [prompt_id, ...]}` y sólo remueve pendientes, con verificación posterior obligatoria.

| Evidencia de preflight | Clasificación | Acción segura |
|---|---|---|
| target en pending + history `queued` o `NOT_FOUND` (política respaldada por F1) | `TARGET_PENDING` | `POST /queue` con el ID exacto |
| target en running | `TARGET_RUNNING` o `RUNNING_INTERRUPT_UNSAFE` | ninguna; no `/interrupt` |
| target ausente + history `SUCCEEDED`/`FAILED` | `ALREADY_TERMINAL` | ninguna |
| target ausente + history `NOT_FOUND` | `NOT_FOUND` | ninguna |
| queue/history `UNKNOWN`, malformada, contradictoria o ambigua | `UNKNOWN`/`CONTRADICTORY`/`AMBIGUOUS` | ninguna |

Tras un `2xx` de `/queue`, sólo la lectura fresca de queue/history puede producir `CONFIRMED`; una terminalización concurrente se informa como `RACED_TERMINAL`. Los errores de lectura devuelven `UNKNOWN` sin mutar; timeout/transport/protocol/server durante el delete son inciertos y no se reintentan. La validación live F3-4 de eliminación segura está completada y aprobada independientemente con observaciones. `Lifecycle.CANCELLED` es un estado genérico previo: la confirmación backend F3-4 no se mapea automáticamente; la transición de dominio pertenece a una unidad posterior. ComfyUI installation was not modified.
### F3-6 validación física mínima (completada)

La validación física recibe un `OutputDescriptor` ya correlacionado y un `trusted_root` explícito. F3 genérico está CLOSED/LIVE VALIDATED en ComfyUI 0.33.0 aislado: parser de queue de 5 campos, correlación exacta por `prompt_id`, WS corregido, outputs lógicos deterministas y protección fail-closed contra escapes. H3 profile/bindings F4 están **CLOSED — APPROVED**. Persistencia durable y chunk orchestration son F5 (**IN PROGRESS — Slice 3 implemented/locally tested**).

## F5 — Contrato de ejecución de un chunk

Corrección contractual F5: `orchestration_timeout_seconds` se resuelve antes de cada Attempt desde defaults JSON (entero, bool inválido, `>0`, default 1800 s), merge proyecto→ejecución→chunk con override de chunk permitido; Attempt no tiene options. Timeout no-retryable fail-closed. `CANCELLED` nunca auto-retry F5 aunque F2 pueda clasificarlo `RETRY_CURRENT_CHUNK`/`CREATE_NEW_ATTEMPT`; no redefine F2/F6. `prompt_id` usa sólo `Attempt.external_job_ref`/`attempts.external_job_ref`, sin columna nueva: persistir sin ref→submit→validar BackendJobRef no vacío→asignar una vez→persistir inmediatamente. Incertidumbre nunca reenvía; job observado durable es ref persistida más evidencia correlacionada.

F5 consume este adaptador en la secuencia preflight → Attempt durable → submit → monitoring/history → correlación determinista → validación física → extracción N-1 → completion durable. El timeout de orquestación se configura por Attempt en las opciones efectivas de defaults JSON persistidos (proyecto → ejecución → chunk; `WorkflowProfileRef` no es fuente de defaults): **1800 segundos (30 minutos) por defecto**. Es independiente de los timeouts de transporte F3 (HTTP 10 s / WebSocket 5 s). Su expiración es fallo/bloqueo explícito, nunca éxito ni retry/resubmit automático.

La única elegibilidad de retry automático es: estado terminal backend explícito `FAILED` sin output verificado, o fallo pre-submit con evidencia determinista de que el backend no aceptó el trabajo. No son elegibles `RUNNING`, `UNKNOWN`, timeout de orquestación, evidencia ambigua/contradictoria, aceptación incierta del submit, pérdida de evidencia, mismatch de procedencia/path, estado u output corrupto, ni cualquier posibilidad de que ya exista un job. Un retry elegible crea exactamente un nuevo Attempt y conserva toda la evidencia anterior. Las situaciones ambiguas se mapean a decisiones existentes `NEEDS_MANUAL_REVIEW` o `BLOCKED_CORRUPT_STATE`, sin persistir un estado nuevo. La cancelación de trabajos running permanece fuera de F5: sólo se conserva el contrato F3 pending-only. Outputs parciales e intermedios se preservan como evidencia y no se limpian automáticamente.

F5 Slice 3 implementa completion de un solo chunk y extracción N-1. La evidencia es local/mock; no implica ComfyUI vivo ni validación visual.
