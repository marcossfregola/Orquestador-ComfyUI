# Roadmap

Este documento contiene únicamente trabajo decidido. El orden aprobado de F0–F10 sólo puede modificarse si evidencia posterior lo justifica y mediante una decisión formal aprobada que actualice los documentos autoridad correspondientes. Sin esa decisión, la secuencia y los límites de las etapas se conservan.

## F0 — Fundación

Producto, alcance, no-alcance, arquitectura, dominio, estados, checkpoints, retry, recovery y reconciliación conceptuales; responsabilidades de infraestructura; Workflow Profiles y bindings como contratos; reglas, entorno, testing y documentación autoridad. No incluye funcionalidad de producto.

**Estado:** base documental establecida en el baseline; F0 no incluye funcionalidad de producto.

## F1 — Spike técnico controlado

Inspeccionar la instalación real de ComfyUI/MiniMax H3 y verificar versiones, custom nodes, workflow normal y API JSON, API local, queue/history, WebSocket/eventos, outputs, uploads, cancelación, FFmpeg/FFprobe, bindings, recovery experimental y reutilización tecnológica.

Puede usar experimentos descartables, harnesses o una cáscara técnica mínima para validar threading, cancelación, progreso o integración desktop. Esos experimentos no se convierten automáticamente en producción ni condicionan el diseño sin evidencia.

**Estado:** checkpoint técnico B2–C3 ejecutado y documentado; F1 permanece abierta.

F1 ya demostró derivación del prompt API, overrides externos, upload de assets, first frame externo, un proyecto integrado, extracción exacta del último frame, chaining real de dos chunks, ensamblado técnico y validación humana del primer seam. Antes del cierre formal todavía faltan recovery/retry/cancelación productivos, persistencia durable, chaining largo, ensamblado productivo, concurrencia segura y validación de los límites restantes.

## F2 — Dominio + persistencia + reconciliación base

Construir el modelo ejecutable, persistencia versionada, checkpoints y recuperación durable base. La tecnología concreta se decide con evidencia de F1.

## F3 — Adaptador ComfyUI

Implementar health, submit, seguimiento, history, outputs, errores, reconexión y cancelación según los contratos y la evidencia obtenida en F1.

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
