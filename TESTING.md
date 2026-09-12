# Estrategia de pruebas

## Evidencia verificada de F2 (task 026)

La suite actual queda en **135 tests, OK**, incluyendo 15 escenarios dedicados save→close→reopen→reconcile de recovery E2E, 15 casos directos de corrupción SQLite, prueba de rollback de migración, auditoría AST/import y imports productivos stdlib/local. `git diff --check` está limpio y no hay SQLite/cache generados bajo el repositorio. Es evidencia backend-agnostic de unidad/integración/E2E: no ejecuta ComfyUI ni FFmpeg reales y no constituye validación visual.

F0 define cómo se probará el producto. No afirma pruebas de producto que todavía no existen ni ejecuciones contra ComfyUI que no se realizaron.

## Niveles

La unidad F3-1 añade pruebas de contrato deterministas contra servidores HTTP locales para health, submit, queue, history y traducción de errores; no implica ejecuciones reales de ComfyUI. La ruta de timeout específico de `websocket-client` se prueba mediante el transporte de producción con el límite websocket-client simulado.

### Unitarias

Cubrir modelo de Proyecto, Ejecución, Chunk e Intento; estados y transiciones; validaciones; herencia y overrides de parámetros; bindings; seeds; rutas; compatibilidad de outputs; checkpoints; retry; y reglas de reconciliación.

### Integración

Cubrir el adaptador ComfyUI contra la instalación real; workflow y bindings; queue/history/eventos; detección inequívoca de output; uploads; cancelación y reconexión según capacidad; FFmpeg/FFprobe; extracción del frame; concat/re-encode; persistencia; escritura atómica; y recovery.

### E2E

Cubrir proyectos de uno, dos y tres chunks; continuidad último frame → siguiente `first_frame`; fallo intermedio; retry; pausa; cancelación; cierre/reinicio; recovery; ensamblado; preservación de intermedios; y errores explícitos.

### Ejecución real

F1 debe documentar experimentos reproducibles con versiones, workflow, inputs, comandos, respuestas, outputs, tiempos y límites. Los harnesses de F1 pueden ser descartables y no se convierten automáticamente en producción.

## Evidencia ejecutada en F1

Contra la instalación real de ComfyUI y el workflow H3 canónico se verificaron:

- B2: ejecución baseline por API, WebSocket, history y correlación exacta con `SaveVideo` node 92;
- B3: override externo únicamente del prompt;
- B4: override externo de una referencia existente;
- B5: upload de un asset externo y uso mediante `subfolder/name`;
- B6: override externo del first frame conservando pipeline y resolución derivada;
- B7: proyecto integrado con Profile, Reference Set, First Frame, Prompt/Chunk, Preset y Output, usando `length=56`, `steps=20`, `fps=24`;
- C1: extracción del último frame decodificado por índice y prueba `framemd5` pixel a pixel;
- C2: chaining real de dos chunks, incluido upload y hash idéntico del frame de continuidad;
- C3: ensamblado técnico de ambos MP4 con concat demuxer y `-c copy`.

La continuidad visual del seam C3 fue validada humanamente por el usuario para ese caso concreto; no es un test automatizado ni una garantía universal.

### Artefactos y correlación del checkpoint

- B7: `prompt_id=96526a14-065d-497d-850b-9c3714ea775e`; MP4 H.264 de 56 frames, SHA-256 `57A66039892267CCCD3BF33B00FFB064D8A857423A09E4F992E414A198EAD449`.
- C1: `N=56`, frame `N-1=55`; PNG `rgb24` `672×928`, SHA-256 `1CE0DE5B9573CE1B3BA2EDE0706068F4325D53B3442B73F029C0AE71CEFB44D5`; `framemd5` MP4 y PNG: `f7bc0b105d1d6b123fa04b394e1c4d76`.
- C2: `prompt_id=e88489a4-464a-4398-a491-a361f4d69427`; MP4 H.264 de 56 frames, SHA-256 `C508979CC1736B6FD2B181FAC03B6F90021EEFD30A468D1082197E1A4ED0431C`.
- C3: concat demuxer `-c copy`; resultado de 112 frames y 4.666667 s, SHA-256 `42D7DED6732846DC37A644A9FB4FB8FFE73886C4171FB01EBBA65B0D29069D90`.

Los paths completos y descriptores de cada artefacto se conservaron en los informes de ejecución; el vínculo durable deberá vivir en la persistencia del Orquestador, no en history de ComfyUI.

### Validación humana

Es obligatoria para continuidad visual, identidad, seam entre chunks, calidad, usabilidad, claridad de UI y facilidad de preparar una sesión. La evidencia visual complementa, pero no reemplaza, las validaciones automáticas.

## Preflight y contratos

Antes de una sesión larga se prueba que ComfyUI, el perfil, bindings, inputs, parámetros, salida, FFmpeg/FFprobe, espacio y estado durable sean coherentes. El objetivo es fallar en segundos cuando la causa ya es detectable.

Los contratos se prueban en sus límites: output parcial o ambiguo, backend reiniciado, evento perdido, binding ausente, frame ilegible, codec incompatible, persistencia interrumpida y cancelación no soportada.

## Benchmark de aceptación del núcleo

El benchmark de aceptación conceptual es un proyecto de tres chunks con workflow H3 conocido, referencias conocidas, `first_frame` manual sólo al inicio y prompts distintos. Debe:

1. ejecutarse sin intervención humana entre chunks;
2. producir tres MP4 válidos;
3. extraer correctamente dos frames intermedios;
4. encadenar automáticamente cada frame;
5. producir un output final;
6. conservar evidencia y artefactos;
7. demostrar continuidad visual mediante validación humana.

Este benchmark demuestra el problema central y no equivale por sí solo al cierre del producto.

## Evidencia requerida

Cada prueba relevante debe conservar, según corresponda:

- versión y configuración del entorno;
- proyecto, ejecución, chunk e intento;
- fase y timestamps;
- inputs y bindings efectivos;
- request/job y eventos relevantes del backend;
- rutas, hashes o metadata de artefactos;
- errores y comandos de FFmpeg/FFprobe;
- resultado esperado y observado;
- decisión de retry/recovery;
- validación humana cuando aplique.

No se debe afirmar “funciona” sin indicar qué se ejecutó, contra qué entorno y con qué evidencia.

## Matriz formal F1

| Área | Clasificación | Asignación |
|---|---|---|
| API/endpoints, prompt derivation, queue/history, WS/progreso, upload, output correlation | DEMONSTRATED | F3 genérico; H3 bindings F4 |
| N-1 PNG + framemd5, chaining real de dos chunks, hash continuity | DEMONSTRATED | F5/F7 amplían cobertura |
| pending-delete B por POST `/queue` 200, history `{}`, sin output; interrupt A; queue vacía; repo intacto | DEMONSTRATED | F3/F6 definen semántica productiva |
| concat `-c copy` y seam visual | DEMONSTRATED sólo para ese caso | F8/F10 validan generalización |
| automatización visual como integración | DISCARDED | — |
| **FUTURE:** cancelación productiva de dominio, recovery/chaining multi-chunk contra backend, concurrencia, GUI | FUTURE / NOT STARTED | F9/F10 |

## Estado de F1

F1 produjo evidencia experimental reproducible, no implementó producto ni convirtió harnesses en dependencias. Su estado histórico no se confunde con F3.

## F3 closure evidence

La suite externa final quedó **322/322 verde** tras la corrección manual sólo de tests. Las auditorías READ_ONLY independientes 095/096 inspeccionaron repositorio y cobertura final; 096 encontró únicamente documentación stale y ningún bloqueador técnico. F3 está cerrada: live validation completó WS/history/output/physical path y cancelación pending-only segura. F4 está **CLOSED — APPROVED** con validación estática, fixture canónico durable y suites de cierre en verde; F5 está **CLOSED — APPROVED** con Slice 4A completada, auditada y aprobada; F6 está **CLOSED — APPROVED** para recovery durable de un chunk. No se afirma E2E H3/chunk no ejecutado. Automated tests, live execution evidence y human visual validation son categorías distintas; la continuidad visual de video no aplica al cierre F3.

## Criterios de avance

- F1 no puede cerrarse sin evidencia del entorno real y de los contratos que se adopten.
- F5 requiere un chunk completo con output, validación, frame y checkpoint durables.
- F6 requiere recovery/retry del pipeline sin declarar recovery multi-chunk.
- F7 requiere por primera vez recovery completo de una cadena de dos o tres chunks.
- F10 reúne E2E, fallos, recovery, continuidad visual, UX y demás criterios del release.

## F5 — Criterios y pruebas de aceptación documental

Pruebas adicionales: defaults/validación/precedencia de `orchestration_timeout_seconds`; timeout no-retryable; `CANCELLED` excluido; Attempt sin ref antes de submit, BackendJobRef no vacío, asignación única y reload durable de `external_job_ref` sin `prompt_id`; y submit/persistencia inciertos sin resubmit.

Las pruebas de contrato de F5 deberán cubrir: flujo feliz de un chunk con Attempt, submit, monitoring/history, correlación determinista, validación física, extracción exacta N-1 y completion durable; retry automático sólo para `FAILED` terminal explícito sin output verificado o fallo pre-submit con evidencia determinista de no aceptación; un único retry como nuevo Attempt preservando el anterior y segundo fallo sin tercer submit; timeout de orquestación por Attempt configurable con valor predeterminado exacto de 1800 s (30 min), separado de HTTP 10 s/WebSocket 5 s, como fallo/bloqueo no exitoso y sin retry; y rechazo de retry para `RUNNING`, `UNKNOWN`, timeout, evidencia ambigua/contradictoria, submit incierto, pérdida de evidencia, mismatch de procedencia/path, estado/output corrupto o posible job existente. Las condiciones ambiguas deben mapearse a `NEEDS_MANUAL_REVIEW` o `BLOCKED_CORRUPT_STATE`, sin estado nuevo persistido. También se verifica cancelación running rechazada conforme a F3 pending-only y conservación de outputs parciales/intermedios. No se incluyen chaining multi-chunk, ensamblado, GUI ni crash-recovery real.
# F3 Unidades 1–4

Focused contract suite: `python -B -m unittest tests.test_f3_adapter -v` — **38 tests**, all green. The suite uses a local mocked HTTP server; live ComfyUI evidence is recorded separately and is not a unit-test result.

F3-2 usa transporte WebSocket falso inyectable y cubre correlación, estados, reconexión y fallback sin requerir ComfyUI vivo. La derivación de URL del transporte de producción está cubierta con `websocket-client` mockeado.

F3-3: `python -B -m unittest tests.test_f3_outputs` cubre una matriz determinista de fixtures sintéticos/document-derived: gating por estado e history, ausencia/vacío/malformación de outputs, recorrido de contenedores, validación estricta de node/filename/subfolder/type, multiplicidad/orden/duplicados/ambigüedad, igualdad semántica de `BackendJobRef` e identidad del ref provisto por el caller, dataclasses congeladas y ausencia de filesystem. No constituye fixture live ni compatibilidad real con F3.
# F3-4 testing

Cancellation tests use mocked HTTP behavior only. They verify exact queue-delete payloads, empty-body acceptance, fail-closed races/errors, identity preservation, and that safe cancellation never calls native interrupt.

F3-4 focused suite: `python -B -m unittest tests.test_f3_cancellation` covers the preflight decision matrix, malformed/unknown evidence, typed issue and phase mapping, exact mutation payloads, definitive rejects, uncertain mutation errors without retry, post-verification races, frozen result contracts, and the F1-backed pending+`NOT_FOUND` policy. It does not contact live ComfyUI or modify domain/persistence state.
F3-6 cubre determinísticamente raíz explícita, contención, escapes/symlink, lectura, archivos vacíos y raíces inválidas; La validación live F3-7 de WS/history/output y ruta física, además de cancelación pending segura, ya ocurrió; la validación visual humana de calidad de video sigue siendo futura y no es sustituida por estas pruebas.

## F4 — Workflow Profile H3

La suite enfocada `python -B -m unittest tests.test_f4_workflow_profile -v` cubre la validación estructural fail-closed del workflow UI, el hash canónico, la integridad del template API, los bindings declarados y la topología width/height contrastada con evidencia canónica independiente versionada en `tests/fixtures/minimax_h3/prompt.sanitized.v2.json`. Es una validación determinista local: no ejecuta una nueva generación contra ComfyUI ni constituye validación visual. F4 está **CLOSED — APPROVED**; snapshot histórico de esa ronda: F5 estaba **NOT STARTED**. En esa ronda: **29 tests, OK**.

La regresión reproducible F3+F4 usa exactamente estos módulos: `tests.test_f3_adapter tests.test_f3_events tests.test_f3_outputs tests.test_f3_physical_outputs tests.test_f3_cancellation tests.test_f3_application_bridge tests.test_f4_workflow_profile`.

Comando:

`python -B -m unittest tests.test_f3_adapter tests.test_f3_events tests.test_f3_outputs tests.test_f3_physical_outputs tests.test_f3_cancellation tests.test_f3_application_bridge tests.test_f4_workflow_profile`

Resultado observado en esta ronda: **209 tests, OK**.

Suite completa:

`python -B -m unittest discover -s tests`

Resultado observado en esta ronda: **351 tests, OK**. Las tres ejecuciones usaron un directorio temporal controlado process-local y no modificaron ComfyUI.

## F5 — cierre de evidencia (2026-08-30)

F5 **CLOSED — APPROVED**. Slice4A 13/13; todos F5 39/39; regresión completa 390/390, dos corridas consecutivas independientes, ambas OK. A–L explícitos; A/B/C/H/I/L usan SQLiteProjectRepository real con close + nueva instancia + reopen; A/B verifican OUTPUT Artifact + TransitionFrame N-1. diff-check limpio salvo warnings de line endings; ResourceWarnings históricos no son failures. No ComfyUI real, ni FFmpeg real donde hubo fakes, ni validación visual/UX. F6 se documenta a continuación.

Las pruebas contractuales cubren submit único, history terminal correlacionado, correlación/validación física, persistencia tardía, TransitionFrame nullable y FFprobe/FFmpeg shell-free con N-1. G está cubierto por `test_final_save_failure_does_not_mutate_in_memory` con SQLite real y reapertura; I por `test_happy_path_durable_sqlite_reopen_preserves_output_and_transition` (artefacto previo + output); J por `test_transition_frame_target_none_and_second_chunk_reload` con la fila durable completa y `first_frame` del target; K por `tests/test_f5_video_adapter.py` (destino existente, args exactos y `shell=False`). A–K explícito se considera sustentado por estos contratos y los focused F2/F3/F5 suites. Verificación local: discovery **377 tests, OK**, dos ejecuciones consecutivas. No hay claim de ComfyUI vivo ni visual.

## F6 — Recovery/retry durable de un chunk (2026-08-30)

La validación enfocada reproducible es:

`python -B -m unittest tests.test_f6_recover_execution -v`

Desde PowerShell, ejecutar en la raíz del repositorio. La convención de imports del repo la aporta `tests/__init__.py`; si el entorno no la hereda, se puede fijar explícitamente `$env:PYTHONPATH = (Resolve-Path .\src).Path`. Las pruebas que requieren filesystem aceptan un directorio temporal fresco mediante `$env:ORQ_TEST_TMP`; no se deben reutilizar bases SQLite de corridas anteriores.

La suite F6 (**28 tests, OK**) comprueba con SQLite real save → close → nueva instancia → reopen, reconciliación y observación fresca de `external_job_ref`, estados `QUEUED`/`RUNNING`/`COMPLETED`/`FAILED`, error durable, retry controlado, Attempt 1 preservado, creación durable de Attempt 2, ausencia de Attempt 3, IDs/referencias, output/evidence, un `Artifact` `OUTPUT`, un `TransitionFrame` N-1, snapshots antes/después de reopen y repeated resume idempotente. Los casos ambiguos, cancelados, desconocidos o con procedencia inválida deben quedar fail-closed. No hay mutaciones directas de producción para fabricar el resultado; las asignaciones directas de fixtures sólo preparan estados de prueba.

La regresión completa oficial conserva el comando:

`python -B -m unittest discover -s tests`

El cierre F6 observado con ese comando fue **418 tests, OK**. En este host hubo `ResourceWarning` de conexiones/archivos sin cerrar provenientes de pruebas existentes; se informan como warnings y no como éxito silencioso. La suite completa requiere que el directorio temporal que usan las pruebas F5 (`C:\Temp\orq-f5-final-tests`) sea escribible en Windows; un `PermissionError` allí es ambiental y debe resolverse en el entorno, no relajando assertions.

F6 no ejecuta una nueva generación contra ComfyUI ni validación visual. La recuperación completa de una cadena, la propagación automática del último frame, el ensamblado y F7 siguen fuera de alcance.

## F7 — chaining y recovery de cadena

`ChainExecutionUseCase` se valida con coordinador y repositorio inyectados:
cadenas de 2–3 chunks, propagación N-1, checkpoint antes de avanzar,
reanudación sin regenerar chunks exitosos y preservación de intentos/artefactos.
La validación es determinista y no implica ComfyUI vivo ni validación visual.

### Cierre oficial F7 (2026-08-31)

Auditoría independiente final `orquestador-f7-final-audit-017` aprobada. Resultados: F7 **19/19 PASS**, F6 **28/28 PASS**, F5 **21/21 PASS**, corrupción F2 **17/17 PASS**, suite oficial completa (`python -B -m unittest discover -s tests`) **437/437 PASS** y `git diff --check` **PASS**. Esta evidencia cubre validación determinista de aplicación/SQLite; no se ejecutó nueva generación E2E contra ComfyUI ni validación visual.
## F8 — ensamblado final

`python -B -m unittest tests.test_f8_assembly -v` cubre concat compatible, incompatibilidad, contención,
destino existente/carrera, validación final fallida sin publicación, sufijo `.mp4` explícito, temporales únicos y
lista concat con escapes de apóstrofes. FFprobe valida el temporal antes de enlazar; la publicación es create-if-absent
sin validación post-publicación falible. La integración FFmpeg real se mantiene como evidencia externa de laboratorio;
Contrato F8: >=2 chunks, MP4, copy sólo con firmas compatibles, fallback explícito de reencode, FFprobe final antes de publicar y preservación de chunks/intermedios.

Auditoría aprobada `orquestador-f8-evidence-audit-037`: FFmpeg y FFprobe reales 8.1.1; copy PASS a `out copy's file.mp4` (2640 bytes, ffprobe válido) y reencode PASS a `out reencode's file.mp4` (1875 bytes, ffprobe válido), con nombres con espacios y apóstrofes. Fuente sin cambios; destino existente y carrera preservados sin overwrite; probe pre-publicación fallido sin destino; destinos unsupported/suffixless rechazados; temporales propios limpiados y sentinel preservado. F8 focused **6/6 PASS**, suite completa **443/443 PASS**, compileall PASS y `git diff --check` PASS. No hubo validación visual humana ni E2E ComfyUI; no eran requeridos para esta slice técnica.

**Histórico del cierre F9:** F8: **CLOSED — APPROVED**. F9: **CLOSED — APPROVED WITH OBSERVATIONS**. En esa captura F10: **NOT STARTED**.

Auditoría independiente 056: composición **12/12**, otras F9 **5/5**, frontera histórica **3/3**, F6/F7 **47/47**, F5/F8 **51/51**, discovery completa **460/460**; syntax check, `git diff --check` y harness temporal externo PASS. En esa captura no se había realizado validación visual humana ni E2E real de ComfyUI; quedaban para F10.

## F10 — E2E real y regresión final (2026-09-01)

La validación real se ejecutó con el camino público/composed `facade.prepare` → `facade.start_chain` contra ComfyUI local `0.33.0`. El runtime y la evidencia están fuera del repositorio, en `C:\Codex\Orquestador-ComfyUI-F10-runtime\codex-local-final-f10\e2e-20260901T184920Z-8ee4f1e6`. Se verificaron dos chunks reales, exactamente siete uploads estáticos con `overwrite=false`, cero placeholders, un submit por chunk, history terminal, SaveVideo node 92, contención/importación, SHA-256, FFprobe, extracción N-1, upload y persistencia de transición, y reopen/recovery sin resubmit.

Comandos y resultados finales:

- `python -B -m unittest tests.test_f10_gui_preparation tests.test_f7_chain_execution -v` → **Ran 32 tests — OK**.
- `python -B -m unittest discover -s tests` → **Ran 478 tests — OK**.

La suite completa sólo emitió `ResourceWarning` históricos de recursos no cerrados y el aviso de fuentes de Qt; no hubo failures, errors ni skips. Ambos jobs H3 superaron el límite de orquestación F5 de 1800 s y quedaron en estado fail-closed sin retry/resubmit; la recuperación posterior consumió los mismos `external_job_ref` una vez terminales. La validación visual humana posterior aprobó la continuidad (`HUMAN_VISUAL_VALIDATION=APPROVED`, `VISUAL_CONTINUITY=APPROVED`), y F10 queda cerrado.

### F10 — corrección del seam y FAST E2E posterior

La prueba de regresión del cambio mantiene el camino público `facade.prepare` → `facade.start_chain`, pero acepta el flag explícito `fast_e2e=True` sólo para desarrollo/prueba. `configure_fast_e2e` trabaja sobre una copia del prompt y aplica node 119 `megapixels=0.09`, node 129 `length=56` y node 146 `steps=4`; no escribe esos valores en `Execution.defaults` ni altera el perfil normal (0.6 MP, 294 frames, 20 steps). El node 127 usa el bounding box completo 16384×16384 para evitar el default implícito 512×512; la topología y la conexión `node 129.first_frame=["119",0]` no cambian.

Resultados automáticos del cambio:

- `python -B -m unittest tests.test_f4_workflow_profile tests.test_f10_gui_preparation` → **46/46 OK**.
- `python -B -m unittest discover -s tests` → **481/481 OK**.
- La suite completa sólo mostró `ResourceWarning` preexistentes; no hubo failures, errors ni skips.

## F11.2A — preparación visual (2026-09-10)

Focused suite: `python -B -m unittest tests.test_f11_2a_visual_preparation -v` — **Ran 5 tests — OK (skipped=1)** (symlink creation unavailable in this Windows environment; lexical root validation remains covered). La suite automatizada cubre preview, cardinalidad/orden y operaciones de referencias, preservación del original y derivación de crops.

Validación humana separada: se confirmó preview inicial; 0, 1 y 6 referencias; Add/Replace/Remove; ratios/movimiento/resize manuales; paths seleccionados y preferencias por defecto; y `Prepare` completado sin crash nativo de Qt. Esto es evidencia de uso humano, no resultado automatizado.

## F11.3 — configuración H3 ampliada (2026-09-10)

Focused changed module: `python -B -m unittest tests.test_f11_1b_gui_preparation -v` — **Ran 33 tests — OK**. Qt font/plugin warnings and historical ResourceWarnings are environmental/pre-existing.

All F11 tests: `python -B -m unittest discover -s tests -p '*f11*'` — **Ran 63 tests — OK (skipped=1)**.

Isolated HTTP recheck: `tests.test_f11_1b_integrated.F111BIntegratedHarnessTests.test_real_http_transport_and_materialization_cardinality` — **Ran 1 test — OK**. Local ephemeral `127.0.0.1` fixture only; the prior HTTP abort was transient and not reproduced.

Full suite: `python -B -m unittest discover -s tests` — **Ran 563 tests — OK (skipped=1)**. A CLI usage line from an expected negative-path test and pre-existing Qt/ResourceWarnings were observed; no failures or errors.

The implementation adds the canonical `ref_image_size=match` selector and `also_ref_first_frame=False` checkbox, wires both through the existing GUI normalization path, invalidates Prepare/Start on edits, and projects exactly six public H3 parameters.

### VALIDACIÓN HUMANA WINDOWS (separada de los tests automáticos)

En una instancia fresca de la GUI F11.3 se verificó:

- `Reference image size` visible, con el valor canónico `match`.
- `Also reference first frame` visible e inicialmente desmarcado.
- `Megapixels`, `Length`, `Steps` y `FPS` siguen visibles; no aparece el control `lens`.
- Con proyecto válido y prompts no vacíos, `Preflight → Prepare` habilitó `Start chain`.
- Después de `Prepare`, marcar `Also reference first frame` deshabilitó inmediatamente `Start chain`.
- `Start chain` no fue pulsado; no se generó ningún video; la GUI fue cerrada después de la validación.

Esta evidencia es VALIDACIÓN HUMANA WINDOWS, separada de los tests automáticos, y no constituye un E2E real de generación.

## F11.1B — evidencia final

F11.1A+F10+F4 H3+F11.1B: **83 PASS**; F11.1B: **27 PASS**; suite completa: **518 PASS**, **0 skipped**; `compileall` y `git diff --check` PASS. Se cubren referencias 0..6 densas, length en frames/FPS dinámico, re-Prepare seguro, invalidación de Start y SQLite/QThread en worker. Runtime `/prompt`: 0, 1, 6 y hueco intencional aceptados; prompts interrumpidos inmediatamente; `REAL_VIDEO_GENERATION=NO`. Auditoría 031: PASS.
F11.4 focused: `python -m unittest -v tests.test_f11_4_sequence_editor` — **15 tests, OK**; regressions F11.1A/F11.1B — **43 tests, OK**. Full suite with `ORQ_TEST_TMP=C:\Codex\Orquestador-Test-Temp\f114-run`: **578 tests, OK (skipped=1)**. Exact skip: `tests.test_f11_2a_visual_preparation.F112AVisualPreparationTests.test_invalid_crop_collision_and_root_escape_rejected` — symlink creation unavailable on this Windows environment; lexical root validation remains covered. `compileall` and `git diff --check` PASS. This is a historical pre-closure snapshot; the combined human approval is recorded below.

F11.4 correction5 acceptance: SQLite integrity **5 tests OK**, MainWindow action surface **1 test OK**, focused editor **15 tests OK**, F11.1A/F11.1B regressions **43 tests OK**, full discovery **583 tests OK (skipped=1)**. Exact skip unchanged: `tests.test_f11_2a_visual_preparation.F112AVisualPreparationTests.test_invalid_crop_collision_and_root_escape_rejected` — symlink creation unavailable on this Windows environment; lexical root validation remains covered. Scratch path was `C:\Codex\Orquestador-Test-Temp\f114-run`; writability probe, compileall and `git diff --check` passed. F11.3 six-public-H3 surface remains unchanged and seed/sampler/scheduler/lens/width/height remain non-public. This is a historical pre-closure snapshot; the combined approval is recorded below.
F11.4 human-validation-corrections: `tests.test_f11_4_human_validation_corrections` **15 tests OK**; required focal set **91 tests OK**; full discovery **611 tests OK (skipped=1)**. Prompt writes are debounced and flushed before structural actions; direct overrides remain draft/snapshot-authoritative. This is a historical pre-closure snapshot; the combined approval is recorded below.
# F11.5 — Operación, recuperación y resultados desde GUI

Matriz automatizada: `tests.test_f11_5_operations` cubre reapertura durable, Resume/Recover y Retry fail-closed, cancelación segura/no segura, visibilidad de chunks/transiciones/artefactos, frontera F8 para Assemble/Reassemble, errores accionables, aislamiento del worker Qt y bloqueo de Start tras ediciones que invalidan Prepare. F11.5 queda **CLOSED — APPROVED** con la aceptación combinada F11.4 en Windows documentada abajo; los tests no se presentan como generación real contra ComfyUI.

## Cierre F11.4/F11.5 (2026-09-11)

### Automated validation

Se ejecutaron todos los módulos `tests/test_*.py` en procesos `unittest` aislados para evitar contaminación entre QApplication/QThread: **614 tests**, **613 OK**, **1 skip**, **0 failures**, **0 errors**. El único skip es `tests.test_f11_2a_visual_preparation.F112AVisualPreparationTests.test_invalid_crop_collision_and_root_escape_rejected`, porque la creación de symlink no está disponible en este Windows; la validación léxica de raíz sigue cubierta. El directorio temporal utilizado fue externo al repositorio y escribible: `C:\Users\Marcos Casa\.codex\visualizations\2026\09\11\01a0905b-2d26-7311-b5b9-564f4d66ff3d\orquestador-test-temp-current`.

Regresiones focales relevantes: F7 chain **26/26**, F6 recovery **29/29**, stale provenance **11/11**, recovery restart **15/15**, F11.4 human corrections **21/21** (casos aislados), MainWindow acceptance **11/11**, sequence editor **15/15**, SQLite acceptance **4/4** y F11.5 operations **13/13**. También quedaron verdes F5, F8, F9 y las regresiones F11.1A/F11.1B. `python -m compileall -q src tests` y `git diff --check` pasan.

### VALIDACIÓN HUMANA WINDOWS (separada de los tests automáticos)

Evidencia aportada por la validación Windows combinada: layout compacto/legible de settings y overrides; valores heredados efectivos; Override ON/OFF y Restore inherited; Duplicate con prompt, configuración y overrides e ID nuevo; Remove bloqueado con dos chunks y habilitado con más de dos; Move Up/Down reordenando por ID y conservando prompt/overrides; `Reference image size` dentro de General configuration; crop sin modificación; y `Prepare → Start` con invalidación al editar y re-Prepare posterior. La recuperación real en `yy/yy` reutilizó `MiniMax_H3_00286_.mp4`, completó `00287_.mp4` y el ensamblado fue aprobado como perfecto. Una generación fresca de dos chunks iniciada con `Start Chain` continuó automáticamente tras completar el chunk 1.

Esta evidencia humana no se presenta como una nueva ejecución real durante este turno. Se acepta como no bloqueante que algunas miniaturas de referencias no se rehidraten tras el ensamblado; se difiere junto con el pulido visual restante (settings horizontales, IDs permanentes, paneles inferiores lado a lado, previews mayores y spinboxes) a F11.6.
