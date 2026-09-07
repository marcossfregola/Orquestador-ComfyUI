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
- `prompt`, `length`, FPS y `ref_image_size` se inyectan en sus inputs API reales; el baseline F4 no exponía `steps`, pero F11.0 lo promueve como binding público F11.1 hacia node 146 `steps`; seed, sampler y scheduler permanecen fuera de la superficie pública;
- node 92 `SaveVideo` expone el descriptor `filename/subfolder/type` usado para resolver el output.

Estos IDs y nombres son evidencia del profile H3 instalado; no deben filtrarse al dominio.

Un cambio incompatible del workflow debe fallar durante preflight, antes de iniciar una sesión larga, con un error claro. La decisión de diseño F1 queda registrada: un Workflow Profile/manifest versionado y autocontenido, con bindings declarativos y validación de compatibilidad en preflight; los IDs de nodo y `class_type` quedan aislados detrás del profile/adapter; la correlación determinista de outputs usa `prompt_id`/history y el descriptor de `SaveVideo`. El esquema formal, las pruebas de compatibilidad y la implementación del profile F4 están **CLOSED — APPROVED**; la frontera del adaptador consumidor de ComfyUI permanece en F3.

## Contrato H3 aprobado para F11.1

F11.0 formaliza la superficie mínima que la GUI puede configurar. El contrato de aplicación debe traducir estos conceptos mediante el profile H3, sin exponer IDs de nodos a la UI:

| Concepto | Destino efectivo | Alcance F11.1 |
| --- | --- | --- |
| `prompt` | node 129 `prompt` | Público |
| `first_frame` externo | node 114 `image` | Público; lo materializa el Orquestador |
| `ref_image_0..5` | nodes 130, 131, 132, 150, 151, 152 `image` | Público; exactamente seis |
| `megapixels` | node 119 `megapixels` | Público como única política de resolución |
| `length` | node 129 `length` | Público |
| `steps` | node 146 `steps` | Público desde F11.1 |
| `fps` | node 148 `fps` | Público |
| `ref_image_size` | node 129 `ref_image_size` | Default, sin control hasta F11.3 |
| `also_ref_first_frame` | node 129 `also_ref_first_frame` | Default, sin control hasta F11.3 |

El profile mantiene además la ranura canónica `ref_image_6` sin conexión; no es una entrada de usuario y no amplía la cardinalidad de seis referencias de F11.1.

La tabla fija el contrato de diseño, no afirma que F11.1 ya esté implementada: el código y el manifest H3 actuales no se modifican en F11.0. La incorporación efectiva de `steps` y cualquier corrección del descriptor de `first_frame` quedan para una implementación posterior controlada y sus pruebas.

La resolución no admite dos políticas concurrentes: F11.1 configura `ImageScaleToTotalPixels` node 119 mediante `megapixels`; node 120 deriva width y height para H3. No se agregan controles de width/height manuales en paralelo.

La distinción de `first_frame` es contractual: la entrada externa que recibe la ruta materializada es `LoadImage` node 114 `image`. La conexión `node 119 → node 129.first_frame` es parte de la topología interna canónica y debe mantenerse. El contrato y el manifest no deben presentar `129.first_frame` como el slot externo de escritura. La corrección efectiva de código/manifest queda para una implementación posterior controlada; esta sección fija el significado.

Defaults normales vigentes para F11.1: `megapixels=0.6`, `length=294`, `steps=20`, `fps=24`, `ref_image_size="match"`, `also_ref_first_frame=false` y `orchestration_timeout_seconds=1800`. `fast_e2e` permanece sólo como opción de desarrollo y no es un preset de usuario ni se persiste.

Seed, sampler, scheduler, IA y otros parámetros de backlog no se convierten en bindings públicos por este cambio. Los valores numéricos, tipos, límites, profile/version/hash, rutas y cardinalidad de referencias deben validarse durante preflight y fallar de forma explícita antes del submit.

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

Los bindings mínimos de F11.1 y su semántica de resolución/`first_frame` quedan formalizados en la sección anterior. La exposición de bindings H3 adicionales requiere una decisión posterior de perfil y pertenece a F11.3 o más adelante.

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

F6 cerró el recovery/retry durable de un chunk después de crash/cierre/reinicio mediante el agregado SQLite y una observación backend fresca, sin afirmar una nueva generación E2E contra ComfyUI. Siguen abiertos la recuperación y el chaining multi-chunk, la semántica de cancelación a nivel de pipeline/dominio, la concurrencia segura, el ensamblado productivo, la GUI y la generalización de la continuidad visual; la cancelación backend segura pending-only de F3-4 está cerrada y live validada. La persistencia durable y el completion/artifact persistence de F5 están **CLOSED — APPROVED**. No se adopta ni forkeará automáticamente un proyecto externo.

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

La validación física recibe un `OutputDescriptor` ya correlacionado y un `trusted_root` explícito. F3 genérico está CLOSED/LIVE VALIDATED en ComfyUI 0.33.0 aislado: parser de queue de 5 campos, correlación exacta por `prompt_id`, WS corregido, outputs lógicos deterministas y protección fail-closed contra escapes. H3 profile/bindings F4 están **CLOSED — APPROVED**. Persistencia durable y chunk orchestration de F5 están **CLOSED — APPROVED**; F6 está **CLOSED — APPROVED** para recovery/retry durable de un chunk con evidencia local/mock.

## F5 — Contrato de ejecución de un chunk

Corrección contractual F5: `orchestration_timeout_seconds` se resuelve antes de cada Attempt desde defaults JSON (entero, bool inválido, `>0`, default 1800 s), merge proyecto→ejecución→chunk con override de chunk permitido; Attempt no tiene options. Timeout no-retryable fail-closed. `CANCELLED` nunca auto-retry F5 aunque F2 pueda clasificarlo `RETRY_CURRENT_CHUNK`/`CREATE_NEW_ATTEMPT`; no redefine F2/F6. `prompt_id` usa sólo `Attempt.external_job_ref`/`attempts.external_job_ref`, sin columna nueva: persistir sin ref→submit→validar BackendJobRef no vacío→asignar una vez→persistir inmediatamente. Incertidumbre nunca reenvía; job observado durable es ref persistida más evidencia correlacionada.

F5 consume este adaptador en la secuencia preflight → Attempt durable → submit → monitoring/history → correlación determinista → validación física → extracción N-1 → completion durable. El timeout de orquestación se configura por Attempt en las opciones efectivas de defaults JSON persistidos (proyecto → ejecución → chunk; `WorkflowProfileRef` no es fuente de defaults): **1800 segundos (30 minutos) por defecto**. Es independiente de los timeouts de transporte F3 (HTTP 10 s / WebSocket 5 s). Su expiración es fallo/bloqueo explícito, nunca éxito ni retry/resubmit automático.

La única elegibilidad de retry automático es: estado terminal backend explícito `FAILED` sin output verificado, o fallo pre-submit con evidencia determinista de que el backend no aceptó el trabajo. No son elegibles `RUNNING`, `UNKNOWN`, timeout de orquestación, evidencia ambigua/contradictoria, aceptación incierta del submit, pérdida de evidencia, mismatch de procedencia/path, estado u output corrupto, ni cualquier posibilidad de que ya exista un job. Un retry elegible crea exactamente un nuevo Attempt y conserva toda la evidencia anterior. Las situaciones ambiguas se mapean a decisiones existentes `NEEDS_MANUAL_REVIEW` o `BLOCKED_CORRUPT_STATE`, sin persistir un estado nuevo. La cancelación de trabajos running permanece fuera de F5: sólo se conserva el contrato F3 pending-only. Outputs parciales e intermedios se preservan como evidencia y no se limpian automáticamente.

F5 está **CLOSED — APPROVED** (2026-08-30): Slices 1, 2, 3 y 4A completadas/auditadas. La evidencia es local/mock; no implica ComfyUI vivo ni validación visual.

## F6 — Frontera de recovery/reconciliación durable (2026-08-30)

`ResumeExecutionUseCase` reabre el agregado desde SQLite y usa el `Attempt.external_job_ref` durable para una observación fresca. `QUEUED` y `RUNNING` esperan sin resubmit; `COMPLETED` sólo se acepta con `HistoryResult` cuyo `prompt_id` coincide exactamente y delega el output/evidence, el `Artifact` `OUTPUT` y el `TransitionFrame` N-1 al coordinador de completion existente. Un `FAILED` terminal explícito puede persistir el error y consumir un único retry, creando un segundo Attempt y preservando el primero; un tercer Attempt, un `CANCELLED`, un estado desconocido, un mismatch de procedencia o evidencia incompleta quedan bloqueados para revisión manual. Los resumes de un agregado ya completo son idempotentes.

Esta frontera es backend-agnóstica y reconciliable: las pruebas usan SQLite real y observaciones inyectadas/mocks. F6 no modifica el protocolo de ComfyUI ni declara una nueva ejecución live, chaining multi-chunk, propagación automática de `first_frame` ni ensamblado; esos comportamientos pertenecen a F7/F8.

## F10 — evidencia live de la cadena pública (2026-09-01)

La corrida real usó `facade.prepare` y el camino compuesto `facade.start_chain` contra `http://127.0.0.1:8188` (ComfyUI core `0.33.0`). El runtime de evidencia es `C:\Codex\Orquestador-ComfyUI-F10-runtime\codex-local-final-f10\e2e-20260901T184920Z-8ee4f1e6`; la queue estaba vacía antes de comenzar. Los siete archivos declarados por F10 existían bajo el input root real y se subieron exactamente una vez cada uno, con `overwrite=false`:

| slot | referencia efectiva |
|---|---|
| initial | `orquestador/static/initial-9c5b54673dfd0cf7.png` |
| ref 1 | `orquestador/static/ref-1-3ba7d5a1389d1be4.jpg` |
| ref 2 | `orquestador/static/ref-2-37803ec8fd58b35f.jpg` |
| ref 3 | `orquestador/static/ref-3-0e4d603306e24883.jpg` |
| ref 4 | `orquestador/static/ref-4-fa1dfd29e6f6b6af.jpg` |
| ref 5 | `orquestador/static/ref-5-cfb5642a9a1e4433.jpg` |
| ref 6 | `orquestador/static/ref-6-1c15b866fc10e8b1.jpg` |

El graph capturado antes de cada `/prompt` confirmó para chunk 0 `node 114.image = initial`, las seis referencias en `130/131/132/150/151/152`, `129.first_frame = ["119", 0]`, prompt no vacío y cero placeholders. Para chunk 1 confirmó `node 114.image = orquestador/transitions/transition-52b5ac2a-0d2e-4e54-bc7c-2a79314f87e8-ff3326b0fd903e2f.png`, las mismas seis referencias, el mismo `129.first_frame` canónico y cero placeholders. Los prompt IDs fueron `abea6078-1983-4dc7-80bd-70f25f920ed2` y `a3a2510f-a9ac-45e8-b5e1-e57c58d7a0f8`, un submit aceptado por chunk.

Los histories terminales resolvieron SaveVideo node 92 con `images: [{filename, subfolder: "video", type: "output"}]` y `animated: [true]`; la metadata auxiliar no se interpretó como descriptor. Los MP4 fuente fueron `C:\Users\Marcos Casa\AppData\Local\Comfy-Desktop\ComfyUI-Shared\output\video\MiniMax_H3_00254_.mp4` y `MiniMax_H3_00255_.mp4`, y se importaron sin overwrite bajo el proyecto de evidencia. FFprobe validó en ambos H.264, 800×800, 24 fps, 294 frames y 12.25 s; cada SHA-256 fuente coincidió con el importado.

El frame exacto `N-1` de chunk 0 es `...\transitions\52b5ac2a-0d2e-4e54-bc7c-2a79314f87e8.png`, índice `293/294`, SHA-256 `ff3326b0fd903e2f6680d3985ea5afc17f4199533b20f8843faeeaeb49da0978`; se subió una vez como la referencia efectiva indicada arriba y quedó persistido en `MaterializedInputRef`. Ambos jobs superaron el deadline de orquestación 1800 s, pero el contrato mantuvo sus IDs y la recuperación pública completó los mismos intentos sin tercer submit. Reopen terminó `succeeded`, con dos artefactos y dos transiciones. La validación visual humana posterior aprobó la continuidad (`HUMAN_VISUAL_VALIDATION=APPROVED`, `VISUAL_CONTINUITY=APPROVED`).

### F10 — diagnóstico C/D y validación FAST posterior

El diagnóstico del seam del run anterior es reproducible: el preview de ComfyUI node 127 era exactamente el recorte superior izquierdo 512×512 de la transición 800×800. La implementación de `ImageCropV2` usa `{x:0,y:0,width:512,height:512}` cuando recibe `crop_region={}`; node 119 (`megapixels=0.6`, `nearest-exact`, `resolution_steps=32`) lo reescalaba a 800×800. Eso explica el zoom/reencuadre y confirma causa C de pipeline. El perfil ahora fija sólo node 127 a `{x:0,y:0,width:16384,height:16384}`; el bounding box excedente se recorta a los límites reales de la imagen, por lo que conserva toda la entrada sin introducir una dimensión fija.

La ejecución FAST de control se hizo por `facade.prepare` y `facade.start_chain(..., fast_e2e=True)` en el runtime `C:\Codex\Orquestador-ComfyUI-F10-runtime\seam-fast-e2e\fast-20260901T223000Z`. El flag no se persiste. Los graphs capturados muestran node 127 completo, node 119 `0.09` MP, node 129 `length=56`, node 146 `steps=4`, `node 129.first_frame=["119",0]` y SaveVideo node 92 sin cambios. Se subieron exactamente siete estáticos, más una transición PNG; hubo exactamente dos jobs y no hubo tercero. Ambos resultados son H.264, 352×256, 24 fps, 56 frames y 2,333 s; estado durable `succeeded` tras reopen.

La evidencia `seam-comparison.json` contiene `TRANSITION_INPUT.png`, `CHUNK1_FRAME0.png`, `CHUNK1_FRAME1.png`, frames 2–4, preview node 127, histories, hashes y métricas. `node127_vs_transition` es `pixel_identical=true` (352×256); el frame 55 exacto de chunk 0 coincide byte/pixel a pixel con `TRANSITION_INPUT.png`. `transition_vs_chunk1[0]` mantiene dimensiones pero no identidad pixel: PSNR 29,846985 dB, MSE 67,356863 y diferencia media 6,431763. Con la entrada ya idéntica, la alteración residual es causa D del modelo H3 y queda aceptada como limitación conocida del backend, no como defecto pendiente del Orquestador; la continuidad visual fue aprobada (`VISUAL_CONTINUITY=APPROVED`).

El control local `codec-baseline-frame0.png`, codificando 56 copias de la transición con H.264 y decodificando el primer frame, obtuvo PSNR 40,894518 dB y diferencia media 1,772694. La diferencia adicional del output H3 excede el error esperado del codec y mantiene la clasificación D con una base separada de la compresión.
