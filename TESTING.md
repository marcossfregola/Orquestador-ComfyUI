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
| **FUTURE:** cancelación productiva de dominio, crash/orphan recovery contra backend, retry del pipeline, chaining largo, concurrencia, GUI | FUTURE / NOT STARTED | F5/F6/F7/F8/F9 |

## Estado de F1

F1 produjo evidencia experimental reproducible, no implementó producto ni convirtió harnesses en dependencias. Su estado histórico no se confunde con F3.

## F3 closure evidence

La suite externa final quedó **322/322 verde** tras la corrección manual sólo de tests. Las auditorías READ_ONLY independientes 095/096 inspeccionaron repositorio y cobertura final; 096 encontró únicamente documentación stale y ningún bloqueador técnico. F3 está cerrada: live validation completó WS/history/output/physical path y cancelación pending-only segura. F4 está **CLOSED — APPROVED** con validación estática, fixture canónico durable y suites de cierre en verde; F5 permanece **NOT STARTED**. No se afirma E2E H3/chunk no ejecutado. Automated tests, live execution evidence y human visual validation son categorías distintas; la continuidad visual de video no aplica al cierre F3.

## Criterios de avance

- F1 no puede cerrarse sin evidencia del entorno real y de los contratos que se adopten.
- F5 requiere un chunk completo con output, validación, frame y checkpoint durables.
- F6 requiere recovery/retry del pipeline sin declarar recovery multi-chunk.
- F7 requiere por primera vez recovery completo de una cadena de dos o tres chunks.
- F10 reúne E2E, fallos, recovery, continuidad visual, UX y demás criterios del release.
# F3 Unidades 1–4

Focused contract suite: `python -B -m unittest tests.test_f3_adapter -v` — **38 tests**, all green. The suite uses a local mocked HTTP server; live ComfyUI evidence is recorded separately and is not a unit-test result.

F3-2 usa transporte WebSocket falso inyectable y cubre correlación, estados, reconexión y fallback sin requerir ComfyUI vivo. La derivación de URL del transporte de producción está cubierta con `websocket-client` mockeado.

F3-3: `python -B -m unittest tests.test_f3_outputs` cubre una matriz determinista de fixtures sintéticos/document-derived: gating por estado e history, ausencia/vacío/malformación de outputs, recorrido de contenedores, validación estricta de node/filename/subfolder/type, multiplicidad/orden/duplicados/ambigüedad, igualdad semántica de `BackendJobRef` e identidad del ref provisto por el caller, dataclasses congeladas y ausencia de filesystem. No constituye fixture live ni compatibilidad real con F3.
# F3-4 testing

Cancellation tests use mocked HTTP behavior only. They verify exact queue-delete payloads, empty-body acceptance, fail-closed races/errors, identity preservation, and that safe cancellation never calls native interrupt.

F3-4 focused suite: `python -B -m unittest tests.test_f3_cancellation` covers the preflight decision matrix, malformed/unknown evidence, typed issue and phase mapping, exact mutation payloads, definitive rejects, uncertain mutation errors without retry, post-verification races, frozen result contracts, and the F1-backed pending+`NOT_FOUND` policy. It does not contact live ComfyUI or modify domain/persistence state.
F3-6 cubre determinísticamente raíz explícita, contención, escapes/symlink, lectura, archivos vacíos y raíces inválidas; La validación live F3-7 de WS/history/output y ruta física, además de cancelación pending segura, ya ocurrió; la validación visual humana de calidad de video sigue siendo futura y no es sustituida por estas pruebas.

## F4 — Workflow Profile H3

La suite enfocada `python -B -m unittest tests.test_f4_workflow_profile -v` cubre la validación estructural fail-closed del workflow UI, el hash canónico, la integridad del template API, los bindings declarados y la topología width/height contrastada con evidencia canónica independiente versionada en `tests/fixtures/minimax_h3/prompt.sanitized.v2.json`. Es una validación determinista local: no ejecuta una nueva generación contra ComfyUI ni constituye validación visual. F4 está **CLOSED — APPROVED**; F5 está **NOT STARTED**. En esta ronda: **29 tests, OK**.

La regresión reproducible F3+F4 usa exactamente estos módulos: `tests.test_f3_adapter tests.test_f3_events tests.test_f3_outputs tests.test_f3_physical_outputs tests.test_f3_cancellation tests.test_f3_application_bridge tests.test_f4_workflow_profile`.

Comando:

`python -B -m unittest tests.test_f3_adapter tests.test_f3_events tests.test_f3_outputs tests.test_f3_physical_outputs tests.test_f3_cancellation tests.test_f3_application_bridge tests.test_f4_workflow_profile`

Resultado observado en esta ronda: **209 tests, OK**.

Suite completa:

`python -B -m unittest discover -s tests`

Resultado observado en esta ronda: **351 tests, OK**. Las tres ejecuciones usaron un directorio temporal controlado process-local y no modificaron ComfyUI.
