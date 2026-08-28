# Roadmap

Este documento contiene únicamente trabajo decidido. El orden aprobado de F0–F10 sólo puede modificarse si evidencia posterior lo justifica y mediante una decisión formal aprobada que actualice los documentos autoridad correspondientes. Sin esa decisión, la secuencia y los límites de las etapas se conservan.

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

**Estado:** NOT STARTED.

## F4 — Workflow Profile / bindings MiniMax H3

Definir y probar el contrato versionado del workflow H3 real, sus bindings y su validación de compatibilidad.

## F5 — Pipeline robusto de un chunk

Completar el flujo preflight → preparación → generación → detección inequívoca → validación → extracción del frame de transición → completado durable.

## F6 — Recovery/retry real del pipeline y checkpoints

Probar crash, cierre, reinicio, errores, outputs incompletos, reconciliación y nuevos intentos del pipeline existente.

F6 valida recovery de un pipeline/chunk. No declara validado el recovery multi-chunk de una cadena.

## F7 — Chaining 2–3 chunks + recovery de cadena

Usar último frame → siguiente `first_frame`, avanzar automáticamente, recuperar entre chunks, reintentar dentro de una cadena y continuar tras interrupciones.

Aquí se valida por primera vez el recovery multi-chunk completo.

## F8 — Ensamblado final

Verificar compatibilidad, concat/re-encode y preservación de todos los chunks e intermedios; crear el final como artefacto adicional.

## F9 — GUI del primer release

Construir la UI de producto sobre el núcleo probado: preparación, preflight, ejecución, estados, progreso, errores, retry, recovery, cancelación y resultados.

Las etapas anteriores pueden haber usado harnesses técnicos descartables o una cáscara mínima para probar threading, cancelación, progreso o integración desktop. Eso no invalida ni reemplaza la UI final.

## F10 — Validación real y cierre

Ejecutar E2E, escenarios de fallo y recovery, continuidad visual, UX, rendimiento, instalación cuando corresponda y cierre formal del primer release.
