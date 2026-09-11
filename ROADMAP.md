# Roadmap

Este documento contiene únicamente trabajo decidido. El orden aprobado de F0–F11 sólo puede modificarse si evidencia posterior lo justifica y mediante una decisión formal aprobada que actualice los documentos autoridad correspondientes. Sin esa decisión, la secuencia y los límites de las etapas se conservan.

## F0 — Fundación

Producto, alcance, no-alcance, arquitectura, dominio, estados, checkpoints, retry, recovery y reconciliación conceptuales; responsabilidades de infraestructura; Workflow Profiles y bindings como contratos; reglas, entorno, testing y documentación autoridad. No incluye funcionalidad de producto.

**Estado:** base documental establecida en el baseline; F0 no incluye funcionalidad de producto.

## F1 — Spike técnico controlado

Inspeccionar la instalación real de ComfyUI/MiniMax H3 y verificar versiones, custom nodes, workflow normal y API JSON, API local, queue/history, WebSocket/eventos, outputs, uploads, cancelación, FFmpeg/FFprobe, bindings, recovery experimental y reutilización tecnológica.

Puede usar experimentos descartables, harnesses o una cáscara técnica mínima para validar threading, cancelación, progreso o integración desktop. Esos experimentos no se convierten automáticamente en producción ni condicionan el diseño sin evidencia.

**Estado:** COMPLETED/CLOSED — trabajo técnico y evidencia completos, con aprobación de la dirección técnica de ChatGPT. F2 está **CLOSED — APPROVED** (cierre 2026-08-28).

F1 demostró derivación del prompt API, endpoints nativos, WebSocket/progreso, upload, correlación determinista prompt_id→history→SaveVideo92→archivo, bindings H3 reales, extracción exacta N-1, chaining de dos chunks y ensamblado técnico. La cancelación básica running→`/interrupt` y pending-delete están demostradas como spike; lo productivo queda asignado a F2/F3/F4/F6/F7/F8/F9.

## F2 — Dominio + persistencia + reconciliación base

Construir el modelo ejecutable, persistencia versionada y recuperación durable base. F2 implementa entidades e invariantes backend-agnósticos, SQLite schema v1, migración preparada, protección contra corrupción/conflictos y reconciliación pura determinista; el punto seguro se deriva de agregado durable + evidencia verificada, sin entidad Checkpoint persistida.

Incluye 135 pruebas verdes (incluidos escenarios recovery E2E y corrupción SQLite). Deferidos: consulta/adaptador ComfyUI, ejecución FFmpeg, profile/bindings H3, GUI, orquestación productiva, assembly y validación visual.

**Estado:** **CLOSED — APPROVED** (cierre 2026-08-28).

## F3 — Adaptador ComfyUI

Implementar health, submit, seguimiento, history, outputs, errores, reconexión y cancelación según los contratos y la evidencia obtenida en F1.

**Estado:** **COMPLETED/CLOSED — LIVE VALIDATED**. Auditoría global independiente 096 no encontró bloqueadores técnicos; sólo requirió sincronización documental.

La integración output→`ArtifactObservation` está implementada, side-effect free y fail-closed; completion/artifact durable quedó cerrada en F5. F3 está **CLOSED / COMPLETED; LIVE VALIDATED**.

## F4 — Workflow Profile / bindings MiniMax H3

Definir y probar el contrato versionado del workflow H3 real, sus bindings y su validación de compatibilidad.

**Estado:** **CLOSED — APPROVED** (cierre técnico de F4); F5 **CLOSED — APPROVED** (2026-08-30).

## F5 — Pipeline robusto de un chunk

Corrección de aceptación F5: probar defaults/validación/precedencia de `orchestration_timeout_seconds`; excluir `CANCELLED` del auto-retry F5 sin redefinir F2/F6; verificar asignación única/reload de `external_job_ref` sin columna prompt_id y submit incierto sin reenvío. Job observado durable es ref persistida más evidencia correlacionada.

Completar un único chunk end-to-end: preflight → preparación → generación → detección inequívoca → validación → extracción exacta del frame de transición N-1 → completado durable.

Decisiones aprobadas para F5: el timeout de orquestación se configura por Attempt en las opciones efectivas de defaults JSON persistidos (proyecto → ejecución → chunk; `WorkflowProfileRef` no es fuente de defaults) y su valor predeterminado es exactamente 1800 segundos (30 minutos), distinto de F3 HTTP 10 s / WebSocket 5 s; su vencimiento es fallo/bloqueo explícito, nunca éxito ni retry/resubmit. La única elegibilidad de retry automático es `FAILED` terminal explícito sin output verificado o fallo pre-submit con evidencia determinista de no aceptación backend. Nunca son elegibles `RUNNING`, `UNKNOWN`, timeout, evidencia ambigua/contradictoria, submit incierto, pérdida de evidencia, mismatch de procedencia/path, estado/output corrupto o cualquier caso donde pueda existir un job. Cada retry elegible crea exactamente un nuevo Intento y preserva la evidencia previa; las ambigüedades se mapean a `NEEDS_MANUAL_REVIEW` o `BLOCKED_CORRUPT_STATE`, sin inventar estados persistidos. La cancelación de una generación running queda fuera de F5 y se conserva el contrato F3 pending-only; todos los outputs parciales/intermedios se conservan como evidencia, sin limpieza automática. Quedan fuera chaining multi-chunk, ensamblado, GUI, F6+ y crash-recovery real más allá de los contratos necesarios para este estado seguro.

Aceptación F5: un chunk exitoso deja durablemente Attempt, job observado, output correlacionado de forma determinista, validación física, frame N-1 y completion; cada fallo elegible consume como máximo el retry único y preserva ambos Attempts; timeout, ambigüedad o `RUNNING` no producen `COMPLETADO` ni resubmit; las decisiones ambiguas son `NEEDS_MANUAL_REVIEW` o `BLOCKED_CORRUPT_STATE`; y ningún artefacto parcial se elimina.

**Estado:** **CLOSED — APPROVED** (2026-08-30). Slices 1, 2, 3 y 4A completadas/auditadas; F6 queda cerrado en la sección siguiente.

## F6 — Recovery/retry durable de un chunk y checkpoints

Cerrar la recuperación/reanudación durable de un único chunk: reapertura desde SQLite, reconciliación con una observación fresca del backend, recuperación de intentos existentes, completion verificable, errores durables y un retry controlado.

El contrato implementado espera estados `QUEUED`/`RUNNING`, completa sólo con `HistoryResult` y output/evidencia verificables, y ante `FAILED` crea como máximo un segundo Attempt preservando el primero. El presupuesto agotado, `CANCELLED`, desconocido, ambiguo o con procedencia inconsistente queda fail-closed para revisión manual. La reapertura y los resumes repetidos son idempotentes; el frame de transición usa la semántica N-1 y el artefacto `OUTPUT` queda durable.

F6 se considera completada únicamente cuando la suite enfocada, la regresión oficial y la auditoría documental/del diff terminan correctamente. La evidencia de cierre es local y con backend simulado/inyectado; no declara una nueva generación E2E contra ComfyUI ni validación visual.

**Estado:** **CLOSED — APPROVED** (2026-08-30). Suite F6 **28/28 OK**; regresión oficial **418/418 OK**. El recovery/chaining multi-chunk permanece explícitamente fuera de F6 y corresponde a F7.

## F7 — Chaining 2–3 chunks + recovery de cadena

Usar último frame → siguiente `first_frame`, avanzar automáticamente, recuperar entre chunks, reintentar dentro de una cadena y continuar tras interrupciones.

Aquí se valida por primera vez el recovery multi-chunk completo.

Implementación F7: `ChainExecutionUseCase` compone el coordinador F5, enlaza cada
`TransitionFrame` al chunk inmediato siguiente y persiste el checkpoint antes de
continuar. Reanudar reutiliza chunks y artefactos ya exitosos; no se elimina evidencia.
El ensamblado final y la UI permanecen fuera de alcance.

**Estado:** **CLOSED — APPROVED** (cierre 2026-08-31). Auditoría independiente final `orquestador-f7-final-audit-017`: F7 19/19, F6 28/28, F5 21/21, corrupción F2 17/17, regresión oficial 437/437 y `git diff --check` PASS.

## F8 — Ensamblado final

Verificar compatibilidad, concat/re-encode y preservación de todos los chunks e intermedios; crear el final como artefacto adicional.

**Estado:** **CLOSED — APPROVED** (cierre 2026-08-31; evidencia `orquestador-f8-evidence-audit-037`). La UI y F9 no forman parte de este cambio.

Contrato F8: requiere >=2 chunks y destino MP4; usa `-c copy` sólo con firmas de stream compatibles, ofrece fallback explícito de reencode, ejecuta FFprobe final antes de publicar sin overwrite y preserva chunks e intermedios.

## F9 — GUI del primer release

Construir la UI de producto sobre el núcleo probado: preparación, preflight, ejecución, estados, progreso, errores, retry, recovery, cancelación y resultados.

Las etapas anteriores pueden haber usado harnesses técnicos descartables o una cáscara mínima para probar threading, cancelación, progreso o integración desktop. Eso no invalida ni reemplaza la UI final.

**Estado:** **CLOSED — APPROVED WITH OBSERVATIONS** (auditoría independiente 056; cierre documental 2026-08-31).

F9 entrega una GUI PySide6 lanzable con raíz de composición/entrypoint, fachada de aplicación, workers en segundo plano y preparación de inputs. La fachada conecta start/resume/recover/retry/cancel/assemble con los casos de uso existentes; expone snapshot durable y capability flags, falla cerradamente ante configuración o selección ambigua y no inventa ETA ni progreso. Retry conserva Attempt 1 fallido, crea como máximo Attempt 2 y respeta presupuesto. Assembly pasa por la frontera F8 y cancelación resuelve un único target durable fallando cerradamente si no es seguro. Widgets no acceden directamente a persistencia, ComfyUI ni FFmpeg; el cableado queda en la raíz de composición.

Invocación verificada: `python -m orquestador --project-root <absolute-directory> [--comfyui-endpoint <url>] [--workflow-template <absolute-file>] [--ffmpeg <command>] [--ffprobe <command>]`; `--project-root` es obligatorio y absoluto. Evidencia de cierre F9 en ese checkpoint: composición 12/12; F9 restante 5/5; frontera histórica 3/3; F6/F7 47/47; F5/F8 51/51; completa 460/460; syntax/diff/temp harness PASS. En ese momento **HUMAN VISUAL VALIDATION NOT PERFORMED** y **REAL COMFYUI E2E NOT PERFORMED**; la evidencia actual de F10 queda registrada abajo.

## F10 — Validación real y cierre

Ejecutar E2E, escenarios de fallo y recovery, continuidad visual, UX, rendimiento, instalación cuando corresponda y cierre formal del primer release.

F5: **CLOSED — APPROVED**. Slices 1–4A completadas/auditadas. F6: **CLOSED — APPROVED**. F7: **CLOSED — APPROVED**. F8: **CLOSED — APPROVED**. F9: **CLOSED — APPROVED WITH OBSERVATIONS**. F10: **CLOSED — APPROVED** (2026-09-01; `HUMAN_VISUAL_VALIDATION=APPROVED`, `VISUAL_CONTINUITY=APPROVED`).

### Evidencia técnica F10 (2026-09-01)

Se ejecutó el camino público/composed `facade.prepare` → `facade.start_chain` con dos chunks contra ComfyUI real `0.33.0` en `127.0.0.1:8188`. La corrida y sus capturas están en `C:\Codex\Orquestador-ComfyUI-F10-runtime\codex-local-final-f10\e2e-20260901T184920Z-8ee4f1e6`. Se materializaron exactamente siete inputs estáticos, todos con `overwrite=false`; el chunk 0 usó el initial efectivo `orquestador/static/initial-9c5b54673dfd0cf7.png`, y el chunk 1 reutilizó las seis referencias y recibió la transición efectiva `orquestador/transitions/transition-52b5ac2a-0d2e-4e54-bc7c-2a79314f87e8-ff3326b0fd903e2f.png`.

Los prompt IDs fueron `abea6078-1983-4dc7-80bd-70f25f920ed2` y `a3a2510f-a9ac-45e8-b5e1-e57c58d7a0f8`, cada uno con un único submit. Ambos histories terminaron `success` y resolvieron el descriptor real de SaveVideo node 92 (`images[{filename,subfolder,type=output}]`). Los MP4 se importaron bajo el proyecto sin escapar de la raíz, conservaron SHA-256 fuente/importado, y FFprobe confirmó H.264 800×800, 24 fps y 294 frames. El frame de transición es exactamente N-1 (`293/294`), se persistió con `MaterializedInputRef` y se reusó tras reopen.

La generación H3 superó el deadline de orquestación configurado de 1800 s en ambos chunks; el contrato fail-closed mantuvo cada `external_job_ref` y no reintentó ni reenvió. La recuperación pública observó esos mismos IDs una vez terminales, completó/importó ambos chunks y el reopen final quedó `succeeded`: exactamente dos jobs aceptados, cero tercero y ningún reupload estático innecesario. El ensamblado no pertenece al alcance decisivo de F10 en las autoridades vigentes: `ASSEMBLY_STATUS=NOT_APPLICABLE_TO_F10`. La validación visual humana posterior aprobó la continuidad; F11 no se inició.

### Corrección de seam y prueba FAST (posterior)

El run anterior mostró causa C: `ImageCropV2` node 127 interpretaba `crop_region={}` como 512×512 desde `(0,0)` antes de reescalar en node 119. El perfil mantiene la topología y usa un bounding box explícito 16384×16384 para conservar el frame completo. El E2E FAST de control (`C:\Codex\Orquestador-ComfyUI-F10-runtime\seam-fast-e2e\fast-20260901T223000Z`) ejecutó el mismo camino público con `fast_e2e=True` sin persistir cambios: 0.09 MP, 56 frames y 4 steps, frente a los defaults normales 0.6 MP, 294 frames y 20 steps. Terminó en 57,0 s, con 7 uploads estáticos + 1 transición, 2 submits exactos y estado durable `succeeded`.

La comparación guardada demuestra node 127 pixel-idéntico a `TRANSITION_INPUT.png` y el frame N-1 de chunk 0 byte/pixel idéntico a esa transición. El frame 0 de chunk 1 conserva 352×256 pero no es pixel-idéntico (PSNR 29,846985 dB; MSE 67,356863; media absoluta 6,431763). La causa C de pipeline quedó corregida; la diferencia D del modelo queda aceptada como limitación conocida del backend H3, no como defecto pendiente del Orquestador. La continuidad visual fue aprobada (`HUMAN_VISUAL_VALIDATION=APPROVED`, `VISUAL_CONTINUITY=APPROVED`) y F11 permanece sin iniciar.

El control de codec separado dio PSNR 40,894518 dB y media absoluta 1,772694, por debajo de la diferencia observada en el frame 0; la clasificación D no depende sólo del round-trip H.264.

## F11 — GUI operativa incremental y configuración de generación

### F11.5 — Operación, recuperación y resultados desde GUI

**Estado:** **CLOSED — APPROVED (2026-09-11)**. La GUI expone reapertura durable, Resume/Recover, Retry, cancelación fail-closed, ensamblado/reensamblado por F8 y visibilidad de chunks, transiciones, intermedios y resultados. La evidencia automatizada y la validación humana Windows combinada constan en `TESTING.md`.

Convertir la GUI técnica ya existente en una interfaz Windows realmente utilizable para preparar, ejecutar, seguir y recuperar generaciones de video sin depender de consola ni de edición manual de archivos de configuración.

F11 se desarrolla por **slices verticales utilizables**. Cada slice cerrado debe dejar una aplicación que siga pudiendo generar videos reales; las capacidades nuevas se agregan sobre contratos ya estabilizados, sin rehacer la lógica anterior. La configuración de generación debe tener una única fuente de verdad compartida por aplicación y GUI: la interfaz no debe duplicar reglas de defaults, validación, herencia o bindings, ni hablar directamente con ComfyUI, FFmpeg o persistencia.

No forman parte de F11 por defecto: IA para prompts o planificación, nuevos modelos/workflows, cloud, multi-GPU, plugin system, timeline/editor avanzado, biblioteca avanzada de personajes ni otras expansiones del backlog.

### F11.0 — Inspección y contrato único de configuración

Antes de modificar funcionalidad de producto:

- inspeccionar la GUI F9 y su cableado real;
- inventariar los bindings públicos soportados por el perfil H3 actual;
- definir qué parámetros son de proyecto y cuáles admiten override por chunk;
- fijar obligatoriedad, defaults, precedencia y validaciones;
- identificar qué controles ya existen y cuáles faltan;
- definir archivos afectados, pruebas y criterios de aceptación antes de implementar.

Decisiones formalizadas para el diseño de F11:

- existe un único contrato conceptual `GenerationConfig`, compartido por GUI, aplicación y profile/bindings; la GUI no mantiene una segunda lógica de defaults o validación;
- se conserva la precedencia `project.defaults → execution.defaults → chunk.defaults`, con prioridad del chunk, y cada ejecución guarda un snapshot durable de su configuración efectiva;
- F11.1 exige imagen inicial, referencias H3 opcionales (0..6), ordenadas y densas para la serialización de producto, N>=2 chunks sin máximo arbitrario y un prompt no vacío por chunk;
- F11.1 expone resolución mediante una única política de megapíxeles, además de `length`, `steps` y FPS; los destinos, defaults y la distinción externa/interna de `first_frame` son autoridad de [COMFYUI_INTEGRATION.md](COMFYUI_INTEGRATION.md);
- width/height siguen siendo derivados por el workflow y no se crea una política manual concurrente; la forma de scopes, snapshot y validación es autoridad de [DATA_MODEL.md](DATA_MODEL.md);
- seed, sampler, scheduler, IA y demás backlog quedan fuera; `ref_image_size` y `also_ref_first_frame` usan defaults sin controles hasta F11.3;
- los overrides por chunk sólo existen para parámetros autorizados explícitamente y no agregan complejidad innecesaria al primer video usable.

**Criterio de cierre:** contrato de configuración explícito y reutilizable, sin segunda lógica paralela en la UI y sin cambios innecesarios del núcleo ya validado.

**Estado:** **CLOSED — APPROVED** como decisión documental/contractual. F11.1A y F11.1B están implementadas, auditadas y cerradas en Git; F11.2A queda cerrada tras su evidencia automatizada y validación humana.

### F11.1 — Primera GUI realmente utilizable para generar

Exponer desde la aplicación Windows el conjunto mínimo que permita producir un video real sin preparación externa:

- seleccionar imagen inicial;
- seleccionar las referencias requeridas por el perfil H3 vigente;
- definir cantidad de chunks;
- editar un prompt para cada chunk;
- configurar resolución, `length`, `steps` y FPS;
- preparar y lanzar la cadena desde la GUI;
- mostrar estado real `chunk X/N` y fase verificable;
- obtener los chunks generados y poder crear el resultado final mediante la frontera F8 existente.

La configuración de resolución usa exclusivamente megapíxeles del node 119; width y height son derivados por el workflow. Los parámetros todavía no expuestos usan defaults conocidos y validados; no se crean controles ficticios para bindings que H3 no soporte. F11.1 no agrega edición avanzada de overrides por chunk.

**Criterio de cierre:** desde Windows, el usuario abre la aplicación, prepara únicamente desde la GUI una generación real de dos chunks, la ejecuta de inicio a fin contra ComfyUI, obtiene los outputs y el resultado final, sin consola ni edición manual de configuración. Requiere pruebas automáticas pertinentes, ejecución real, auditoría y validación humana.

Este es el primer checkpoint de F11 que debe dejar el producto utilizable mientras continúan las slices siguientes.

### F11.2 — Gestión visual de imagen inicial y referencias

**F11.2A — CLOSED / HUMAN-VALIDATED (2026-09-10):** preparación visual validada explícitamente en Windows; el detalle y la separación respecto de las pruebas automatizadas constan en `STATUS.md` y `TESTING.md`.

**Corrección F11.1 vigente:** el contrato de producto admite 0..6 referencias H3 opcionales, serializadas densamente en `ref_image_0..N-1`; F11.1A/F11.1B están implementadas, auditadas y cerradas en Git.

Agregar comodidad de preparación sin cambiar el contrato de generación:

- previews/thumbnails;
- agregar, reemplazar y quitar referencias respetando requisitos del perfil;
- orden/slot visible;
- recorte manual desde la propia aplicación;
- conservar siempre el original y materializar el recorte como derivado controlado;
- no destruir ni sobrescribir silenciosamente archivos fuente.

**Criterio de cierre:** toda la preparación habitual de imagen inicial y referencias puede realizarse dentro de la aplicación y la generación real de F11.1 continúa funcionando sin regresiones.

### F11.3 — Configuración H3 ampliada

Exponer los bindings H3 reales restantes que resulte útil controlar, incluyendo donde corresponda `ref_image_size`, `also_ref_first_frame` y presets/variantes de resolución. Mantener defaults globales y overrides por chunk únicamente donde el dominio y el perfil lo soporten.

Seed, sampler, scheduler u otros parámetros no se exponen mientras no sean bindings públicos reales del perfil vigente.

**Criterio de cierre:** todos los parámetros H3 decididos para uso normal pueden configurarse desde GUI, con validación previa y sin duplicar lógica de bindings.

**Estado:** **CLOSED — APPROVED (2026-09-10)**. La evidencia automatizada F11.3 es satisfactoria y la VALIDACIÓN HUMANA WINDOWS confirmó los controles en una instancia fresca de la GUI. Captura histórica; el cierre combinado F11.4/F11.5 está registrado abajo.

### F11.4 — Editor de secuencia de chunks

Mejorar la preparación de sesiones de más de dos chunks:

- agregar y quitar chunks;
- reordenar;
- duplicar cuando sea útil;
- editar prompt individual;
- visualizar valores heredados y overrides explícitos;
- mantener una secuencia inequívoca antes de iniciar.

**Criterio de cierre:** una sesión multi-chunk puede prepararse y revisarse completamente desde la GUI antes de enviarse a generación.

**Estado:** **CLOSED — APPROVED (2026-09-11)**. La edición durable de chunks, herencia/overrides, duplicación, eliminación, reordenamiento por ID y la invalidación `Prepare → Start` pasaron la regresión automatizada y la validación humana Windows combinada documentada en `STATUS.md` y `TESTING.md`.

### F11.5 — Operación, recuperación y resultados desde GUI

Llevar a la experiencia gráfica las capacidades ya existentes del núcleo:

- abrir/reabrir proyecto durable;
- resume/recover;
- retry según contrato vigente;
- cancelación sólo cuando sea segura;
- ensamblar/reensamblar mediante F8;
- mostrar errores accionables y estados fail-closed;
- acceso claro a chunks, transiciones, intermedios y resultado final.

**Criterio de cierre:** las operaciones normales de continuidad, fallo y recuperación pueden ejecutarse desde Windows sin recurrir a herramientas técnicas externas.

**Estado:** **CLOSED — APPROVED (2026-09-11)**. Resume/Recover/Retry, cancelación fail-closed, chaining automático de dos chunks, ensamblado y resultados visibles quedaron verificados automáticamente y aprobados en la validación humana Windows combinada.

### F11.6 — Pulido de UX y validación Windows

Con las capacidades anteriores ya funcionales:

- consolidar distribución de paneles y navegación;
- mejorar mensajes, estados, previews y accesos frecuentes;
- eliminar fricciones detectadas durante uso real;
- validar sesiones reales más largas y comportamiento de la UI durante generación;
- documentar cualquier limitación conocida que quede aceptada.

**Criterio de cierre F11:** la aplicación Windows permite preparar, configurar, generar, seguir, recuperar y obtener resultados de una sesión H3 real mediante la GUI, manteniendo las garantías de chaining, persistencia y conservación de artefactos demostradas hasta F10.

### Regla de avance de F11

Cada slice sigue el flujo obligatorio: **inspección → diagnóstico/diseño → implementación → pruebas → evidencia → auditoría → validación humana cuando corresponda → aprobación → commit**.

No se inicia automáticamente la slice siguiente. Una slice aprobada debe quedar utilizable por sí misma, de forma que el usuario pueda generar videos con la aplicación mientras continúa el desarrollo posterior.
F11.4 correction3/4/5 evidence above is historical and is superseded by the combined approval below. The exact automated counts, environmental skip and separate human evidence remain in `TESTING.md`.

## Cierre combinado F11.4/F11.5 (2026-09-11)

F11.4 y F11.5: **CLOSED — APPROVED**. La validación humana Windows confirmó crop sin cambios, edición y navegación de chunks, `Prepare → Start`, invalidación/re-Prepare, recovery real `yy/yy` con `MiniMax_H3_00286_.mp4` y `00287_.mp4`, ensamblado perfecto y una generación fresca de dos chunks que continuó automáticamente. La suite automatizada quedó en **614 tests (613 OK, 1 skip ambiental)**; no se ejecutó generación real nueva durante este cierre. La observación no bloqueante sobre rehidratación de miniaturas y el pulido visual restante se trasladan a F11.6.
