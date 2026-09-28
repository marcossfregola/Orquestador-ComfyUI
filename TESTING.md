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

## Auditoría Work del baseline remoto (diagnóstico reemplazado por F12.1, 2026-09-13)

El diagnóstico previo indicó erróneamente una discrepancia del artifact. F12.1 se ejecutó desde `main` en `ac77bc892f02641eaa6c4db7b6431ce25be98ae7`, con worktree e index limpios. No se modificó producción ni se ejecutó ComfyUI.

El hash alegado `9F6B5785483D8FCC2C2ADBD0F574DD558BE1F605F2A8D64208AB86FC6FF4E508` no pertenece al artifact versionado de este checkout; fue una afirmación falsa sólo en planificación. La lectura canónica del artifact, `H3_API_TEMPLATE_SHA256` y el manifest coincide en `4DCFB2783391FBA0C5090B8A78765E46AA26B9A2215B948664F0D20341EC8F25`, y `load_api_template()` carga correctamente. No hubo cambio semántico de workflow, por lo que no se requiere validación humana.

F12.1 verificó desde checkout limpio:

- hash del artifact, constante y manifest idénticos;
- `load_api_template()` y validación de profile;
- binding/rebind con 0, 1 y 6 referencias, flag OFF/ON y conflicto con `also_ref_first_frame`;
- chaining/recovery que reconstruye prompts;
- pruebas de `execution_number`, reapertura e hidratación;
- suites focales separadas en Windows con `PYTHONPATH=src` y temp root explícito.

Las cinco primeras suites separadas pasaron: F4 workflow profile 32/32, F11 rebind first frame 7/7, F11.1B capabilities 3/3, F7 chain 26/26 y F6 stale provenance 11/11. La rerun autorizada de `python -m unittest tests.test_f10_gui_preparation`, en proceso Python nuevo con `PYTHONPATH=src`, `TEMP`/`TMP`/`TMPDIR`/`ORQ_TEST_TMP=C:\\Temp\\orq-f12-1-20260913` y `QT_QPA_PLATFORM=offscreen`, pasó 19/19 en 3.735 s. El aviso de Qt sobre fuentes no afectó el resultado. Después, `tests.test_persistence` aislada pasó 14/14 en 0.412 s; `python -B -m compileall -q src tests` terminó con código 0 sin cambios generados en el repo; la comprobación SHA-256 de artifact/constante/manifest fue idéntica al valor canónico; `load_api_template()` devolvió correctamente un `dict` de 35 nodos; y `git diff --check` terminó con código 0. F12.1 queda resuelta y lista para auditoría independiente.

No se ejecutó ComfyUI real ni validación humana; ambos permanecen fuera de alcance porque el artifact canónico no cambió semánticamente.

## Matriz de pruebas decidida para F13

## Evidencia de cierre F13.1

La implementación no-UI de create/save/reopen/listado de borradores ejecutó **9 tests F13.1, OK**. La regresión focal ejecutó **16 tests F13.0 + 14 de persistencia + 10 de Prepare/reopen = 40 tests, OK**; total focal **49 tests, OK**. `compileall` y `git diff --check` terminaron con código 0. Esta evidencia no ejecuta ComfyUI, FFmpeg/FFprobe ni validación humana.

## Evidencia de cierre F13.2

F13.2 está **CLOSED — APROBADA**. El caso de uso no-UI de clonación ejecutó **6 tests F13.2, OK y 1 omitido no bloqueante**: copia desde draft/succeeded/failed, exclusión de evidencia runtime, nuevas identidades e independencia posterior, rutas de inputs contenidas y rollback SQL atómico. Las rutas reutilizadas deben existir, resolver bajo el root y ser archivos regulares; inputs inexistentes, directorios y symlinks rotos o que escapan se rechazan antes de persistir el clon. El único omitido corresponde a `WinError 1314` al intentar crear un symlink en Windows por falta de privilegio; no bloquea el cierre. La regresión focal ejecutó **16 tests F13.0 + 9 tests F13.1 + 10 de GenerationConfig/Prepare + 4 de aceptación SQLite + 14 de persistencia = 53 tests**, más los 7 F13.2: **60 tests ejecutados: 59 OK, 1 omitido**. `compileall` y `git diff --check` terminaron con código 0. No se ejecutó ComfyUI real, GUI interactiva, FFmpeg/FFprobe ni validación humana; no hubo cambio de schema.

## Evidencia de cierre F13.3

F13.3 está **CLOSED — APROBADA**. SQLite migra de schema 4 a 5 mediante el singleton versionado `global_defaults`; la fila contiene exactamente los ocho campos técnicos públicos y no contiene `profile_ref`. La migración no reescribe históricos. El caso de uso valida lectura/escritura cerradamente y toda creación válida de borrador materializa los globals en su snapshot, incluso con `defaults={}` o metadata opaca sin claves técnicas. Se preserva metadata opaca válida, `workflow_profile_ref` se persiste, y la precedencia es `base/canónico → globals → explícito → snapshot Execution → Chunk`; cambios posteriores de globals no modifican ejecuciones existentes.

`python -B -m unittest -v tests.test_f13_3_global_defaults tests.test_f13_1_drafts tests.test_f13_2_clone_configuration` ejecutó **30 tests: 29 OK y 1 omitido no bloqueante** por `WinError 1314` al crear el symlink de F13.2. La cobertura F13.3 incluye schema 4→5, singleton, versionado, validación fail-closed, los ocho campos, `defaults={}`, metadata opaca con y sin `profile_ref`, override técnico parcial sin shape completa, metadata opaca junto a configuración completa, no retroactividad, precedencia, rollback atómico y clone desde el snapshot origen sin consulta de globals. La regresión relevante de F13.0, persistencia, GenerationConfig/Prepare/Start, aceptación SQLite, recovery y operaciones F11.5 ejecutó **86 tests, OK**. La auditoría de código confirmó que, fuera de `GlobalDefaultsUseCase`, el único consumo de globals en el flujo de una ejecución está en `DraftUseCase.create`: F13.2 clone, Prepare, Start y recovery no los consultan. `python -m compileall -q src tests` y `git diff --check` terminaron con código 0.

Para diagnosticar los errores ya observados de la suite completa, se ejecutó aparte `tests.test_f11_2a_visual_preparation`: **1 OK, 3 errors y 1 omitido**. Los tres errors son de la fixture histórica: `Mock` no define `execution_id` y PySide6 rechaza ese objeto en `QLineEdit.setText`; ni `tests/test_f11_2a_visual_preparation.py` ni `src/orquestador/ui/main_window.py` cambiaron desde el baseline F13.2. No se corrigieron porque son ajenos a F13.3. No se ejecutó ComfyUI real, GUI interactiva, FFmpeg/FFprobe ni validación humana; F13.4 y F13.5 estaban fuera del alcance de ese cierre histórico.

## Evidencia de cierre F13.4

F13.4 está **CLOSED — APROBADA**. SQLite migra de schema 5 a 6 y crea `technical_presets` sin presets iniciales ni reescritura de `global_defaults` o de ejecuciones históricas. Cada preset durable contiene exactamente los ocho `GLOBAL_DEFAULT_KEYS`, `config_version=1`, nombre NFC/casefold único, timestamps UTC ordenados y como máximo un `default`. Ese `default` es sólo metadata: la creación normal de borradores no lo consulta ni lo aplica.

Aplicar un preset copia sólo los ocho valores técnicos a una `Execution` pendiente, virgen y fuera de una cola viva. Conserva `profile_ref`, `workflow_profile_ref`, inputs, metadata opaca y overrides de chunks; no guarda referencia al preset. Actualizar o borrar el preset después no cambia el snapshot ya aplicado. El loader falla cerradamente ante `id` no textual, vacío o sólo whitespace; nombre vacío/no trimmed/no NFC; `name_key` inconsistente; mapping/configuración inválida; timestamps inválidos, naïve, no UTC o invertidos; defaults corruptos o múltiples.

`python -m unittest tests.test_f13_4_technical_presets tests.test_persistence tests.test_f13_0_queue_contracts` ejecutó **40 tests, OK**. Cubre CRUD y rollback transaccional, schema 5→6, preservación de globals/histórico, ausencia de presets iniciales, unicidad NFC/casefold, mapping exacto, default único, corrupción durable, aplicación por copia/no retroactividad y bloqueo por cola o evidencia runtime.

Las regresiones relacionadas `tests.test_f13_1_drafts`, `tests.test_f13_2_clone_configuration`, `tests.test_f11_1a_generation_config`, `tests.test_f11_4_sqlite_acceptance`, `tests.test_f6_recover_execution` y `tests.test_f11_5_operations` ejecutaron **72 tests: 71 OK y 1 omitido ambiental** por `WinError 1314` al crear un symlink de F13.2. La revisión estática confirmó que los únicos accesos a presets están en su caso de uso y su repositorio: F13.2 clone, creación normal de borrador, Prepare, Start y recovery no los consultan. No hay implementación accidental de F13.5, F13.6 ni UI de presets. `python -m compileall -q src tests` y `git diff --check` terminaron con código 0.

No se ejecutó ComfyUI real, FFmpeg/FFprobe real, GUI interactiva ni validación humana. Al momento de ese cierre histórico, F13.5 y F13.6 no habían sido iniciadas.

## Evidencia de cierre F13.5

F13.5 está **CLOSED — APROBADA**. SQLite migra de schema 6 a 7 y crea `chunk_templates` sin filas iniciales ni reescritura de `global_defaults`, `technical_presets`, proyectos, ejecuciones, chunks o evidencia histórica. Cada plantilla durable contiene un ID textual no vacío sin whitespace periférico, nombre NFC/casefold único, `template_version=1`, timestamps UTC ordenados y una secuencia JSON ordenada de dos o más prompts no vacíos. No guarda parámetros técnicos, imágenes, referencias, runtime ni outputs.

El caso de uso no-UI crea, lista, lee, actualiza, renombra, duplica y elimina plantillas. Aplicar una plantilla seleccionada copia su secuencia a una `Execution` pendiente, virgen y fuera de una cola viva: actualiza atómicamente `chunk_count`, `prompts`, cantidad/orden y prompt de cada chunk. Conserva `workflow_profile_ref`, inputs, defaults técnicos, metadata opaca y overrides de chunks existentes por posición; chunks nuevos nacen sólo con prompt. No persiste `template_id`: editar o eliminar luego la fuente no altera el snapshot aplicado. La carga falla cerradamente ante identidades/nombres/name keys corruptos, JSON o cardinalidad inválida, versión futura y timestamps inválidos.

`python -m unittest -v tests.test_f13_0_queue_contracts tests.test_f13_1_drafts tests.test_f13_2_clone_configuration tests.test_f13_3_global_defaults tests.test_f13_4_technical_presets tests.test_f13_5_chunk_templates tests.test_persistence` ejecutó **79 tests: 78 OK y 1 omitido no bloqueante** por `WinError 1314` al crear el symlink de F13.2. Incluye CRUD, unicidad NFC/casefold, duplicación, cantidad/orden/prompts, expansión/contracción, rollback transaccional, bloqueo por cola/evidencia runtime, reapertura, corrupción durable y schema 6→7 que preserva globals, presets e histórico. `python -m unittest -v tests.test_f11_1a_generation_config tests.test_f11_4_sqlite_acceptance tests.test_f6_recover_execution tests.test_f11_5_operations` ejecutó **56 tests, OK** para GenerationConfig, Prepare, Start y recovery. La revisión estática confirmó que templates sólo se consultan desde su caso de uso: F13.2 clone, creación normal de draft, Prepare, Start y recovery no los consultan. No hay implementación accidental de F13.6 ni UI de plantillas. `python -m compileall -q src tests` y `git diff --check` terminaron con código 0.

No se ejecutó ComfyUI real, FFmpeg/FFprobe real, GUI interactiva ni validación humana. En el cierre histórico de F13.5, F13.6 permanecía no iniciada.

## Evidencia de cierre F13.7

F13.7 está **CLOSED — APROBADA**. La fuente de verdad del repo confirmó que F13.6 aporta biblioteca e integración GUI de preparación, mientras F13.7 requiere las fundaciones backend F13.0/F13.1 y el clone canónico F13.2; la antigua mención de orden lineal no era una dependencia técnica. No se implementó F13.6 ni UI de cola.

El caso de uso no-UI lista/selecciona, encola, reordena el conjunto completo de items `queued`, quita, salta, pausa/reanuda y duplica un item pendiente mediante el clone F13.2. `enqueue` exige una ejecución virgen/editable y sin item vivo. Remove/skip no borran proyecto, ejecución, chunks ni evidencia. El orden, clone+enqueue, revisión de pausa y la transición normal pending→running contra un item vivo se serializan con SQLite; los conflictos, corrupción y source no pendiente fallan cerradamente. `active` queda protegido. F13.7 no contiene claim, scheduler, submit automático, terminalización automática ni recovery de cola. El schema sigue siendo 7: F13.0 ya había creado los datos e índices necesarios.

`python -m unittest -v tests.test_f13_0_queue_contracts tests.test_f13_1_drafts tests.test_f13_2_clone_configuration tests.test_f13_3_global_defaults tests.test_f13_4_technical_presets tests.test_f13_5_chunk_templates tests.test_f13_7_queue_operations tests.test_persistence` ejecutó **90 tests: 89 OK y 1 omitido no bloqueante** por `WinError 1314` al crear el symlink de F13.2. Cubre enqueue/select/reorder/reopen, terminalización sin borrar agregados, protección de active/runtime, pausa/revisión, clone por valor/rollback, dos conexiones SQLite, rollback del orden, corrupción fail-closed, schema 4→7 y preservación de globals/presets/templates/snapshots.

`python -m unittest -v tests.test_f11_1a_generation_config tests.test_f11_4_sqlite_acceptance tests.test_f11_4_sequence_editor tests.test_f6_recover_execution tests.test_f7_chain_execution tests.test_f11_5_operations` ejecutó **97 tests, OK** para configuración, Prepare/Start, edición de secuencia, persistencia, recovery, chaining y operaciones. `python -m compileall -q src tests` y `git diff --check` terminaron con código 0.

`python -m unittest -v tests.test_f10_gui_preparation tests.test_f11_1b_gui_preparation` ejecutó **52 tests, OK** y confirmó que el Start/Prepare normal y la composición GUI existente siguen funcionando. Durante esa batería aparecieron `ResourceWarning` no bloqueantes de conexiones SQLite de fixtures GUI fuera del diff; no hubo fallo ni cambio en esos módulos como parte de F13.7.

No se ejecutó ComfyUI real, FFmpeg/FFprobe real, GUI interactiva ni validación humana: F13.7 no agrega UI ni inicia una ejecución. La suite completa no se repitió; los tres errors históricos de la fixture F11.2A/crop permanecen fuera del diff y fuera de alcance.

## Evidencia de cierre F13.8

F13.8 está **CLOSED — APROBADA**. El cierre fue autorizado sobre la implementación y los controles técnicos registrados en esta sección. No cambia schema: continúa en 7 y opera las fundaciones `queue_items`/`queue_control` de F13.0/F13.7. El scheduler usa un claim y una finalización `BEGIN IMMEDIATE`, lock local de byte del SO y una conexión SQLite propia del worker no-Qt. El runtime se inicia al lanzar la app; si falta el output root confiable, la frontera existente bloquea antes de reclamar.

`python -B -m unittest -v tests.test_f13_8_scheduler` ejecutó **16 tests, OK**. Cubre vacío, pausa, FIFO y reorder; claim/control atómicos; corrupción y activo sobreviviente fail-closed; carrera entre dos conexiones SQLite reales con un único ganador; lock y fallo de adquisición sin tick; manual Start bloqueado y `start_claimed` convergente; éxito/fallo/cancelación con `finished` y control limpio; pausa con activo; error pre-submit y submit ambiguo con un solo llamado/ref durable; background no-Qt; autoarranque/parada de runtime; y smoke compuesto simulado con exactamente dos submits, uno por chunk, sin ComfyUI real.

Con `ORQ_TEST_TMP` dirigido a un directorio nuevo y aislado, la regresión de F13.0/F13.1/F13.7, persistencia, F3/F5, recovery y chaining ejecutó **234 tests: OK, 1 omitido ambiental** (`WinError 1314` al crear un symlink). La regresión de GenerationConfig, Prepare/Start, SQLite, edición de secuencia y operaciones F11.5 ejecutó **75 tests, OK**. Hubo `ResourceWarning` no bloqueantes por conexiones SQLite sin cerrar en fixtures históricas fuera del diff.

`tests.test_f9_composition.CompositionTests.test_snapshot_missing_fails_closed` continúa fallando con `state == "new"` frente a su expectativa histórica `"error"`: el mismo retorno `new` ya existe en `HEAD` de `src/orquestador/ui/app.py` fuera del diff F13.8. No se corrigió ni se reinterpretó como regresión de esta slice. `python -B -m compileall -q src tests` y `git diff --check` terminan con código 0.

No se ejecutó ComfyUI real, FFmpeg/FFprobe real, generación de video ni validación humana adicional. Para aquel cierre formal no se repitieron auditorías, suites ni smoke; en ese momento F13.9 permanecía NOT STARTED.

## Evidencia técnica F13.9

F13.9 está **CLOSED — APROBADA** sobre la implementación y los 82 tests focales registrados. El scheduler reconcilia un `QueueItem active` antes de reclamar otro, mediante la misma cadena de aplicación y el recovery F6. La ruta de cola conserva `allow_submit=False`: observa y completa referencias durables existentes, pero no autoriza retry ni reenvío por incertidumbre. Un Attempt sin `external_job_ref`, un backend `UNKNOWN` o un job `NOT_FOUND` no liberan el activo; la pausa también conserva y difiere su reconciliación. Éxito durable con outputs importados, artefactos y transiciones válidos puede recuperar la terminalización perdida; fallo/cancelación observados se persisten terminales sin retry automático.

`PYTHONPATH=src ORQ_TEST_TMP=C:\Codex\Orquestador-Test-Temp python -B -m unittest tests.test_f13_9_queue_recovery tests.test_f6_recover_execution tests.test_f7_chain_execution tests.test_f13_8_scheduler -v` ejecutó **82 tests, OK**: los 11 de F13.9 cubren restart completo, Execution terminal con QueueItem activo, outputs durables sin transición final, job observable vivo, intento ambiguo sin ref, crash antes de submit en los estados claimed/running, continuidad de un chunk posterior sin Attempt, job desaparecido, staging de retry explícito, fallo/cancelación observados, pausa, no doble submit y bloqueo del siguiente item; 16 conservan scheduler F13.8 y 55 cubren recovery/chaining F6/F7. No se ejecutó ComfyUI real, FFmpeg/FFprobe real, generación de video ni validación humana. Para ese cierre formal no se repitieron tests, auditorías ni smoke; en ese momento F13.10 permanecía NOT STARTED.

## Evidencia técnica F13.10

F13.10 está **CLOSED — APROBADA**. La pestaña `Cola` proyecta QueueItem/Execution y el estado del scheduler sin acceso directo desde Qt a SQLite, ComfyUI o al scheduler. `Agregar a cola` exige el snapshot preparado e inmutable; las operaciones manuales delegan en F13.7; pause/resume conserva el item activo; recovery/manual review/blocked permanecen visibles y no habilitan un submit adicional; y la selección se conserva por identidad durable.

`PYTHONPATH=src python -B -m unittest -v tests.test_f13_10_queue_gui` ejecutó **4 tests, OK**: proyección y persistencia tras reinicio, activo en manual review con siguiente item en espera, Qt offscreen con dos proyectos/encolado/reordenamiento/pausa y guard de arquitectura del panel.

`PYTHONPATH=src python -B -m unittest -v tests.test_f13_7_queue_operations tests.test_f13_8_scheduler tests.test_f13_9_queue_recovery` ejecutó **38 tests, OK**. `PYTHONPATH=src python -B -m unittest -v tests.test_f13_6_library_gui tests.test_f11_1b_gui_preparation tests.test_f11_5_operations` ejecutó **53 tests, OK**; aparecieron sólo `ResourceWarning` no bloqueantes de conexiones SQLite en fixtures históricas. `python -B -m compileall -q src` terminó con código 0.

La validación humana Windows quedó aprobada sobre una cadena real representativa: `Start chain` se integró con la cola, el activo permaneció visible y único, el recovery tras reinicio no reenvió el chunk ya enviado, y el retry quedó habilitado sólo para el chunk fallido, manteniendo el mismo QueueItem y sin doble submit. No se repitieron suites, auditorías ni crashes/restarts para este cierre. El ensamblado final único permanece fuera de F13.10 y se registra como pendiente futuro.

## Evidencia de cierre F13.6

F13.6 — Biblioteca e integración GUI de preparación — está **CLOSED — APROBADA**. La biblioteca proyecta proyectos/ejecuciones por estado derivado, conserva el UUID sólo internamente, abre borradores/históricos, crea un borrador nuevo mediante el caso de uso F13.1, clona mediante F13.2 y delega Global Defaults, presets técnicos y plantillas de chunks a las autoridades F13.3–F13.5. Las ejecuciones `queued`, activas, históricas o inconsistentes son consultables; sólo un borrador durablemente editable puede recibir cambios estructurales. No se implementaron operaciones UI de cola, scheduler, submit ni recovery.

`python -B -m unittest -v tests.test_f13_0_queue_contracts tests.test_f13_1_drafts tests.test_f13_2_clone_configuration tests.test_f13_3_global_defaults tests.test_f13_4_technical_presets tests.test_f13_5_chunk_templates tests.test_f13_6_library_gui tests.test_f13_7_queue_operations tests.test_persistence` ejecutó **95 tests: 94 OK y 1 omitido no bloqueante** por `WinError 1314` al intentar crear el symlink de la prueba F13.2. Cubre proyección/selección, creación mediante Global Defaults por copia, clone sin consulta dinámica a globals, administración y no retroactividad de preset/plantilla, locks de cola, facade y Qt offscreen.

`python -B -m unittest -v tests.test_f11_1b_gui_preparation` ejecutó **33 tests, OK** para Preflight, Prepare/Start y la composición GUI existente. `python -B -m unittest -v tests.test_f11_4_mainwindow_acceptance.MainWindowF114AcceptanceTests.test_references_have_dedicated_tab_grid_and_controls_below tests.test_f11_4_human_validation_corrections.F114HumanValidationCorrections.test_refs_and_tabs_regression` ejecutó **2 tests, OK** para la pestaña Library añadida. La batería de Prepare/Start/recovery `tests.test_f11_1a_generation_config tests.test_f11_4_sqlite_acceptance tests.test_f11_4_sequence_editor tests.test_f6_recover_execution tests.test_f7_chain_execution tests.test_f11_5_operations` ejecutó **97 tests, OK**. El host de `python -m unittest` no termina de forma determinista para `F10GuiMatrixTests.test_reopened_window_loads_project_before_prepare_without_duplicate_execution`; un probe en memoria con `src/orquestador/ui/main_window.py` de `ea106049` reproduce el mismo comportamiento. La ejecución instrumentada del cuerpo con `setUp`, cleanups y `tearDown` sí completó, pero esta prueba no se contabiliza como batería aprobada ni como regresión F13.6.

La ronda correctiva UX posterior verificó la presentación en español de Biblioteca, contexto visible de proyecto/ejecución/estado, UUID de clone oculto tanto en la sesión que conoce el origen como al recargar la proyección (fallback `Proyecto generado` porque no existe nombre/lineage durable), confirmación única por operación, preservación de scroll en refresh, salto predecible al nuevo clone/borrador, layout tabular de sobrescrituras y tabs ordenadas de prompts de plantilla. El test Qt cubre crear, editar, duplicar y aplicar una secuencia de tres prompts por tabs, además de los locks de cola y el aviso explícito de sólo lectura.

La primera política basada sólo en foco Qt resultó insuficiente en Windows real: un spinbox podía recibir o conservar foco sin un click de intención y consumir la rueda. La corrección usa una política Qt reutilizable que arma el control registrado sólo ante `MouseButtonPress` izquierdo y lo desarma ante cualquier click fuera; el foco automático, restaurado o por navegación no habilita wheel. El test focal `F136QtLibraryTests.test_library_wheel_requires_explicit_click_before_mutating_spinbox` pasó **1/1** y cubre foco sin click, click explícito sobre el número y click fuera seguido de nuevo foco sin click: en ambos tramos no armados el valor queda estable y el `QScrollArea` se desplaza. `tests.test_f13_6_library_gui` pasó **7/7** y la regresión GUI de tabs F11.4 pasó **2/2**.

`python -B -m unittest -v tests.test_f13_0_queue_contracts tests.test_f13_1_drafts tests.test_f13_2_clone_configuration tests.test_f13_3_global_defaults tests.test_f13_4_technical_presets tests.test_f13_5_chunk_templates tests.test_f13_6_library_gui tests.test_persistence` ejecutó **85 tests: 84 OK y 1 omitido no bloqueante** por `WinError 1314` al crear el symlink de F13.2. `python -B -m unittest -v tests.test_f11_1a_generation_config tests.test_f11_4_sqlite_acceptance tests.test_f11_4_sequence_editor tests.test_f6_recover_execution tests.test_f7_chain_execution tests.test_f11_5_operations` ejecutó **97 tests, OK** y `tests.test_f11_1b_gui_preparation` **33 tests, OK**. `python -m compileall -q src tests` y `git diff --check` terminaron con código 0.

La validación humana final Windows fue aprobada: Biblioteca rediseñada; preservación de posición de scroll; Global Defaults; Technical Presets; Chunk Templates y tabs por chunk; `Crear a partir de este`; contexto proyecto/ejecución/estado; layout de overrides; bloqueo y explicación de sólo lectura de históricos. La limpieza autorizada de proyectos de prueba se verificó tras reiniciar la aplicación: quedó únicamente `abs`. La corrección de wheel también fue aprobada en la secuencia real: hover sin click desplaza Biblioteca sin cambiar el valor, click explícito permite editarlo y click fuera vuelve a desarmar la edición. Esta validación humana es evidencia distinta de las pruebas automáticas anteriores.

La prueba histórica `tests.test_f11_4_mainwindow_acceptance.MainWindowF114AcceptanceTests.test_render_snapshot_without_reference_authority_preserves_existing_state` falla porque su fake `NoReferenceAuthority` no declara `execution_id`/`execution_number`; el mismo acceso de `ui/main_window.py` y la fixture existen en el baseline `ea106049`, fuera del diff F13.6. No se clasificó como regresión ni se corrigió fuera de alcance. No se ejecutó ComfyUI real, FFmpeg/FFprobe real ni generación de video en esta ronda de cierre.

| Slice | Pruebas focales mínimas | Validación humana |
|---|---|---|
| F13.0 | invariantes QueueItem, migración schema 3, round-trip, corrupción, activo único | no |
| F13.1 | create/save/reopen draft, listado, clasificación, no duplicación, bloqueo runtime | no |
| F13.2 | copia permitida/prohibida, identidades nuevas, independencia, rollback | no |
| F13.3 | schema 4→5, singleton, validación, ocho campos, precedencia, snapshots/no retroactividad y rollback | no propia; UI integrada y validada por F13.6 |
| F13.4 | schema 5→6, CRUD, corrupción durable, default único, aplicación por copia y no retroactividad | no propia; UI integrada y validada por F13.6 |
| F13.5 | CRUD plantilla, cantidad/orden/prompts, rollback, ejecución bloqueada | no propia; UI integrada y validada por F13.6 |
| F13.6 | facade/snapshots, Qt offscreen, navegación, capabilities, locks de cola y delegación por copia F13.3–F13.5 | Windows final aprobada; CLOSED |
| F13.7 | enqueue/select/reorder/remove/skip/pause, clone por valor, restart, rollback, constraints y concurrencia SQLite | no; CLOSED backend, F13.6 sólo proyecta sus estados |
| F13.8 | claim/finalización atómicos, activo único, dos conexiones SQLite, lock local, pausa, no doble submit, runtime no-Qt y smoke compuesto simulado | CLOSED — APROBADA sobre evidencia técnica registrada; sin smoke adicional |
| F13.9 | restart, activo terminal, outputs durable, job vivo/ausente, no-ref ambiguo, pre-submit, no doble submit y active-first recovery | CLOSED — APROBADA sobre implementación y 82 tests focales registrados; sin validación adicional |
| F13.10 | proyección/acciones Qt, persistencia y restart focal, pausa/reanudación, activo único y no doble submit | CLOSED — APROBADA; validación humana Windows completada |
| F14.2 | schema 8→9, auto/manual, gate por sesión, active recovery/no-submit, pause separado, no doble claim/submit y Qt offscreen | implementación técnica verificada; smoke Windows pendiente |

En toda slice, tests automáticos, ejecución real y validación humana se informan por separado. Ninguna prueba con fake acredita una generación real ni una observación visual.


## Gate técnico pre-F14 — evidencia de cierre (2026-09-27)

Commit integrado: `c14aa524c770b994330a04c55e615bc110313fda` — `stabilize F13.10 runtime recovery paths`.

La reconstrucción limpia incorporó cuatro correcciones acotadas:

- correlación del wrapper SaveVideo `images + animated`, excluyendo previews `type=temp` de la identidad durable;
- resolución de nombres bare `ffmpeg`/`ffprobe` a través de PATH en Windows, preservando rutas explícitas;
- retry de chunk con rematerialización de inputs estáticos antes de reconstruir el prompt, fail-closed ante materialización incompleta;
- detalle compacto y accionable de rechazos HTTP 4xx de ComfyUI, sin cambiar presupuesto ni estado del retry.

Evidencia local reportada para el hotfix: suites focales **27/27**, **80/80** y **41/41** OK; `python -B -m compileall -q src tests` exit 0; `git diff --check` exit 0; diff staged sin churn CRLF masivo.

La suite completa se ejecutó diferencialmente con directorios temporales frescos:

- baseline `80943faeee828def5dda54fefa70cad13ba6a0b5`: **769 tests**, 12 failures, 25 errors, 2 skipped;
- hotfix: **778 tests**, 9 failures, 5 errors, 2 skipped;
- comparación por nombre de test: **NEW_REGRESSIONS=0**. Los failures/errors del hotfix fueron un subconjunto de los ya presentes en el baseline.

Por lo tanto, la suite completa no está globalmente verde y esa deuda histórica no se oculta ni se declara resuelta; sí quedó demostrado que el gate no añadió failures/errors nuevos. Los dos skips corresponden a creación de symlink no disponible bajo privilegios Windows.

No se ejecutaron en este cierre una cadena contra ComfyUI real, FFmpeg/FFprobe con binarios reales ni validación visual humana. Esas categorías permanecen separadas de la evidencia automática anterior.


## F14.1 — nombre durable y renombrado de proyectos (2026-09-27)

Migración implementada: schema 7→8 agrega `projects.name` y `projects.name_key` más índice único normalizado. La prueba de migración parte de una base schema 7 con IDs legibles, UUID y nombres que colisionan normalizados; confirma que mantiene los IDs/evidencia y asigna nombres iniciales deterministas con sufijos. Pruebas adicionales verifican creación con ID generado, normalización/conflicto, rename atómico con proyectos draft/queued/active/terminal sin cambio de ejecución/cola/attempts/artifacts/transitions/paths, reopen, clone durable y autosufijo, Biblioteca y Cola mostrando el nombre.

Resultados focales:

- `python -B -m unittest -v tests.test_f14_1_project_names` — **5 tests, OK**.
- Regresión combinada — **147 tests, OK; 1 skip** (Windows no permitió crear el symlink de ese caso; su validación léxica sigue cubierta):

```powershell
$env:ORQ_TEST_TMP='C:\Codex\Orquestador-Test-Temp'; $env:PYTHONPATH='src'
python -B -m unittest -v tests.test_f13_0_queue_contracts tests.test_f13_1_drafts tests.test_f13_2_clone_configuration tests.test_f13_3_global_defaults tests.test_f13_4_technical_presets tests.test_f13_5_chunk_templates tests.test_f13_6_library_gui tests.test_f13_7_queue_operations tests.test_f13_8_scheduler tests.test_f13_9_queue_recovery tests.test_f13_10_queue_gui tests.test_f13_10_retry_hotfix tests.test_f13_10_runtime_regression tests.test_persistence tests.test_f14_1_project_names
```
- `python -B -m compileall -q src tests` — **exit 0**.
- `git diff --check` — **PASS**, sin errores de whitespace. Git mostró avisos informativos de conversión LF→CRLF configurada para Windows.

Suite completa diferencial, ejecutada con `ORQ_TEST_TMP` fresco y `PYTHONPATH=src` mediante `python -B -m unittest discover -s tests -v`:

- Reproducción desde snapshot limpio creado con `git archive` de `c14aa524c770b994330a04c55e615bc110313fda`, `ORQ_TEST_TMP=C:\Codex\Orquestador-Test-Temp\f14-baseline-20260927`: **778 tests en 63.722 s, 12 failures, 26 errors, 2 skipped**.
- Implementación F14.1, `ORQ_TEST_TMP=C:\Codex\Orquestador-Test-Temp\f14-current-20260927`: **785 tests en 62.421 s, 8 failures, 5 errors, 2 skipped**.
- Comparación de los identificadores exactos `FAIL`/`ERROR` del output verbose: **`NEW_REGRESSIONS=0`**; las 13 incidencias actuales ya aparecen en la reproducción del baseline.

El agregado de la reproducción limpia del commit `c14aa...` no coincide con el agregado histórico publicado unas líneas arriba para el hotfix (**778 tests, 9 failures, 5 errors, 2 skipped**). Se conserva esa discrepancia explícita; para esta decisión se usó la repetición controlada del snapshot exacto y la comparación por identificador, sin declarar globalmente verde la suite ni resolver deuda histórica fuera de alcance.

No hubo validación humana interactiva Windows, ejecución real de ComfyUI ni generación de video. Para cerrar F14.1, probar en Windows: crear un proyecto por nombre, renombrarlo, cerrar y reabrir la aplicación y confirmar persistencia, clonar y confirmar el nombre `Copia de <origen>`/autosufijo, y seleccionar ambos proyectos desde la Biblioteca por nombre visible. F14.1 queda pendiente de ese smoke; F14.2 no se inició.


## F14.1 — corrección técnica: clone inmediatamente renombrable (2026-09-28)

La reproducción Qt/offscreen del reporte humano verificó que el clone ya tenía `ProjectId` y `ExecutionId` nuevos, quedaba seleccionado y recibía el nombre durable `Copia de <origen>`. La persistencia no era la causa: al completar la operación, `render()` reconstruía la lista y Qt dejaba `QApplication.focusWidget()` en `None`. El editor `libraryProjectName` estaba habilitado pero no recibía el teclado, así que para una persona la copia no era renombrable de inmediato sin volver a hacer click en el campo.

La corrección mínima en `PreparationLibraryPanel` conserva una intención de foco sólo durante `Crear a partir de esta`. Cuando el worker termina con éxito y ya se renderizó la selección del clone, la transición a idle enfoca el campo de nombre y selecciona su contenido. Si falla la operación o el dispatch no se inicia, se descarta la intención. El rename continúa por el caso de uso durable existente; no se tocan IDs, ejecuciones, queue, runtime, attempts, artifacts, transitions, archivos ni evidencia.

La regresión `tests.test_f13_6_library_gui.F136QtLibraryTests.test_clone_can_be_renamed_immediately_and_survives_refresh_and_reopen` reproduce el flujo Qt: renombra el source, crea el clone, verifica su selección e IDs/nombre independientes, comprueba el foco del editor sin volver a clickearlo, introduce un nombre, lo renombra, refresca Biblioteca y abre una nueva instancia de `SQLiteProjectRepository`. El source conserva su nombre e identidad y el nombre del clone persiste. Antes del fix fallaba en la aserción de foco (`focusWidget()` era `None`); después pasó **1/1**.

Resultados focales posteriores al fix:

- `python -B -m unittest tests.test_f14_1_project_names tests.test_f13_6_library_gui tests.test_f13_2_clone_configuration tests.test_f13_10_queue_gui tests.test_f13_10_retry_hotfix tests.test_f13_10_runtime_regression -v` — **35 tests, OK; 1 skip**. El único skip es el caso de symlink F13.2: Windows devolvió `WinError 1314` porque este usuario no tiene privilegio para crear symlinks.
- `python -B -m compileall -q src tests` — **exit 0**.
- `git diff --check` — **PASS**, sin errores de whitespace; Git sólo informó la conversión configurada LF→CRLF.

Suite completa diferencial con `python -B -m unittest discover -s tests -v`, snapshot limpio generado desde el baseline publicado `f7196ac84f3ae5ed49bb37e7495c78d28b1f9db4` y directorios `ORQ_TEST_TMP` separados y frescos para baseline y árbol corregido:

- Baseline: **785 tests en 67.394 s; 11 failures, 26 errors, 2 skipped**.
- Árbol corregido: **786 tests en 64.131 s; 8 failures, 5 errors, 2 skipped** (el test adicional es la regresión F14.1).
- Comparación por identificador exacto `FAIL`/`ERROR`: las **13 incidencias actuales** ya están en el baseline; **`NEW_REGRESSIONS=0`**. La suite global sigue mostrando deuda histórica y no se declara verde ni se corrigió fuera de alcance.

F14.1 continúa **PENDIENTE DE VALIDACIÓN HUMANA** hasta repetir el smoke de nombre previo a persistencia registrado abajo. F14.2 no se inició.


## F14.1 — nombre solicitado antes de persistir el clone (2026-09-28)

La causa era que el camino de Biblioteca creaba primero el clone con `Copia de <source>` y dependía de renombrarlo después, en contra del contrato humano. La corrección pide un nombre editable antes de despachar el trabajo. Cancelar/cerrar no llama a la fachada ni crea filas o archivos. Al confirmar, el nombre explícito viaja `PreparationLibraryPanel → GuiFacade → PreparationLibraryUseCase → CloneConfigurationUseCase → SQLiteProjectRepository`; SQLite lo normaliza y persiste con el Project, Execution y Chunks nuevos bajo una transacción. El índice NFC/casefold existente rechaza una colisión y el rollback evita clones parciales. No se accede a SQLite desde Qt. La ruta de duplicación desde Cola sigue usando el nombre sugerido y autosufijo existente, sin diálogo. Se eliminó el workaround de foco que quedó obsoleto al recoger el nombre antes de crear.

Las nuevas pruebas cubren nombre explícito con source sin cambios y reopen; colisión normalizada con snapshots idénticos de `projects`, `executions`, `chunks`, `attempts`, `artifacts`, `errors`, `transitions`, `queue_items` y `queue_control`; cancelación sin cambios durable/archivos/selección; prompt antes de persistir; coexistencia visible; selección, apertura y capacidad de edición del clone; y nombres tras reabrir SQLite. `test_clone_names_are_durable_and_autosuffix_for_both_clone_routes` sigue comprobando que el duplicado de cola conserve los nombres automáticos con sufijo. Antes de implementar, las cinco nuevas pruebas de frontera/UI fallaban por falta del argumento `target_name` y del diálogo previo; después quedaron verdes.

Resultados focales con `PYTHONPATH=src`, Qt offscreen y temporales aislados dentro del checkout:

- `python -B -m unittest -v tests.test_f14_1_project_names tests.test_f13_2_clone_configuration tests.test_f13_6_library_gui tests.test_f13_7_queue_operations tests.test_f13_10_queue_gui tests.test_persistence` — **58 tests, OK; 1 omitido ambiental** por `WinError 1314` al crear el symlink F13.2.
- `python -B -m compileall -q src tests` — **exit 0**.
- `git diff --check` — **PASS**.

Suite diferencial completa (`python -B -m unittest discover -s tests -v`), usando `git archive` del baseline de producción `54695cd0458e1d385aed7995d8d337bfb6447792` y carpetas `ORQ_TEST_TMP` separadas:

- Baseline: **786 tests en 69.074 s; 11 failures, 26 errors, 2 skipped**.
- Árbol corregido: **790 tests en 64.330 s; 8 failures, 5 errors, 2 skipped**.
- Comparación exacta de IDs `FAIL`/`ERROR`: baseline **37**, árbol corregido **13**, los 13 ya existen en el baseline y **`NEW_REGRESSIONS=0`**. Se resolvieron 24 IDs del baseline. La suite global no queda verde; no se cambiaron sus fallos históricos ajenos al alcance.

El smoke humano Windows sigue pendiente: (1) seleccionar un source; (2) pulsar `Crear a partir de esta` y comprobar que aparece `Nombre del nuevo proyecto` antes de crear; (3) cancelar y confirmar que no aparece ninguna copia; (4) repetir, ingresar un nombre único distinto y confirmar; (5) comprobar que source y clone aparecen simultáneamente y que ambos pueden abrirse; (6) verificar que el clone está seleccionado y se puede editar; (7) cerrar/reabrir la aplicación y comprobar que ambos nombres siguen presentes. No se ejecutó ComfyUI real ni se generó video. F14.1 permanece pendiente de este smoke; F14.2 no se inició.


## F14.1 — validación humana Windows y cierre (2026-09-28)

Validación humana final **APROBADA** sobre `origin/main` con la implementación publicada en `796d9afba88a1685b163c6bd85064c08de10420c`.

Se comprobó en la aplicación real:

- creación/renombrado de proyecto y persistencia del nombre;
- `Crear a partir de esta` solicita `Nombre del nuevo proyecto` antes de crear;
- cancelar el diálogo no crea una copia;
- confirmar con un nombre distinto crea un Project/Execution independiente;
- source y clone coexisten en Biblioteca y pueden abrirse por separado;
- tras cerrar y reabrir la aplicación persisten ambos nombres y el source original permanece intacto.

Esta evidencia humana complementa, pero no reemplaza, las pruebas automáticas ya registradas. La suite completa conserva failures/errors históricos y no se declara globalmente verde; la comparación diferencial de F14.1 dio `NEW_REGRESSIONS=0`.

**Decisión:** F14.1 CLOSED — APROBADA. F14.2 no había sido iniciada al momento de este cierre.


## F14.2 — política durable auto/manual (2026-09-28)

Se agregó schema 9 con el singleton `queue_start_policy`; la migración 8→9 crea `auto`, conservando el comportamiento publicado. Un `QueueDispatchSession` nuevo por runtime inicia el permiso manual cerrado. Su lock serializa claims, apertura de sesión y cambios de política; el claim SQLite vuelve a leer modo y pausa en `BEGIN IMMEDIATE`. `QueuePanel` expone `Automático / Manual` y `Iniciar/Reanudar cola` por fachada/caso de uso, separados del botón durable de pausa.

En manual cerrado, el scheduler no reclama items nuevos. F13.9 todavía reconcilia jobs ya enlazados por su ruta no-submit, pero espera para llamar a `start_claimed` sobre un activo virgen hasta que la persona abra el permiso de esta sesión. Cambiar a manual no toca QueueItems, el control activo, lifecycle, attempts ni referencias backend. El submit sigue por `StartGuiChainUseCase → ChainExecutionUseCase → SubmitBoundary`; no se agregó `/interrupt` ni una segunda ruta.

Las pruebas F14.2 cubren migración/default/reapertura/corrupción de política, manual cold start con cola vacía y queued, permiso explícito, cierre al crear otra sesión, auto regression, activo bound observado sin submit, activo pending diferido, cambio auto→manual sin cancelación, separación con pausa, Qt offscreen de selector/botón y el fail-closed de un scheduler creado sin sesión inyectada. Resultado focal: **13 tests, OK**. Comandos focal e integrado:

```powershell
$env:PYTHONPATH='src'; $env:QT_QPA_PLATFORM='offscreen'
python -B -m unittest -v tests.test_f14_2_queue_start_policy
python -B -m unittest -v tests.test_f13_3_global_defaults tests.test_f13_4_technical_presets tests.test_f13_5_chunk_templates tests.test_f13_7_queue_operations tests.test_f13_8_scheduler tests.test_f13_9_queue_recovery tests.test_f13_10_queue_gui tests.test_f13_10_retry_hotfix tests.test_f13_10_runtime_regression tests.test_f14_1_project_names tests.test_persistence tests.test_f14_2_queue_start_policy
python -B -m compileall -q src tests
git diff --check
```

La regresión integrada de F13.7–F14.2 ejecutó **122 tests, OK**. `python -B -m compileall -q src tests` y `git diff --check` finalizaron con código **0**.

Suite completa diferencial con temporales separados, `PYTHONPATH=src`, `QT_QPA_PLATFORM=offscreen` y `python -B -m unittest discover -s tests -v`:

- Baseline limpio `a3a9be122a1ce4f41de18725867e0453e95dc471`: **790 tests en 67.647 s, 11 failures, 26 errors, 2 skipped**.
- F14.2 (repetición diferencial final): **803 tests en 69.893 s, 8 failures, 5 errors, 2 skipped**.
- Comparación por identificador exacto `FAIL`/`ERROR`: baseline **37**, actual **13**; todas las incidencias actuales ya estaban en baseline; **`NEW_REGRESSIONS=0`**. Una primera pasada del árbol actual reportó un error adicional transitorio `WinError 10053` en `test_real_http_transport_and_materialization_cardinality`; la prueba pasó aislada y la repetición de la suite completa quedó sin IDs nuevos.

La suite completa conserva fallos históricos y no se declara globalmente verde. No se ejecutó ComfyUI real ni se produjo video. La UI tuvo prueba automatizada Qt offscreen, pero falta el smoke humano interactivo Windows indicado en [FUNCTIONAL_COMPLETION.md](FUNCTIONAL_COMPLETION.md); F14.2 permanece abierta hasta esa validación. F14.3 no se inició.
