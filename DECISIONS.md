# Decisiones F0

Registro conciso. Cada entrada indica fecha, decisión, motivo, estado/reemplazo y documento autoridad.

## Decisiones de diseño F1 (sin implementación)

| Fecha | Decisión | Motivo breve | Estado o reemplazo | Autoridad |
|---|---|---|---|---|
| 2026-08-27 | Workflow Profile H3 versionado y autocontenido, con manifest declarativo de conceptos→inputs (tipo, cardinalidad, opcionalidad y compatibilidad); IDs/class_type aislados en profile/adapter; preflight obligatorio | F1 verificó bindings reales sin filtrarlos al dominio | DECIDIDA como diseño; contrato y tests en F4; consumo por adaptador en F3 | [COMFYUI_INTEGRATION.md](COMFYUI_INTEGRATION.md) |
| 2026-08-27 | MAKE/REUSE/ADAPT: REUSE API nativa ComfyUI, FFmpeg/FFprobe detrás de adaptadores; ADAPT/EVALUATE SDK v2 después; reutilizar sólo patrones de FlowDirector, VideoChunkTools y wrappers comunitarios; MAKE dominio, orquestación, persistencia, recovery, UI, estados, intentos, assembly y bindings de producto | Separar evidencia útil de dependencias estructurales | DECIDIDA como diseño F1; no implementación | [COMFYUI_INTEGRATION.md](COMFYUI_INTEGRATION.md) |

| Fecha | Decisión | Motivo breve | Estado o reemplazo | Autoridad |
|---|---|---|---|---|
| 2026-08-27 | Aplicación de escritorio independiente para Windows | Contexto y flujo del primer release | Aprobada en F0; no reemplazada | [PROJECT.md](PROJECT.md) |
| 2026-08-27 | ComfyUI es backend, no UI principal | Separar producto de motor de inferencia | Aprobada en F0; no reemplazada | [PROJECT.md](PROJECT.md) |
| 2026-08-27 | Independencia de Visor y Bridges | Evitar acoplamiento de producto y runtime | Aprobada en F0; no reemplazada | [PROJECT.md](PROJECT.md) |
| 2026-08-27 | Bridge sólo es infraestructura de desarrollo | El runtime debe ser autónomo | Aprobada en F0; no reemplazada | [ARCHITECTURE.md](ARCHITECTURE.md) |
| 2026-08-27 | Último frame real del chunk N → `first_frame` del N+1 | Preservar continuidad validada manualmente | Aprobada en F0; no reemplazada | [DATA_MODEL.md](DATA_MODEL.md) |
| 2026-08-27 | MiniMax H3 es el primer Workflow Profile | Entregar un primer caso sin limitar el dominio | Aprobada en F0; no reemplazada | [COMFYUI_INTEGRATION.md](COMFYUI_INTEGRATION.md) |
| 2026-08-27 | Chunks e intermedios se preservan | Trazabilidad y recuperación | Aprobada en F0; no reemplazada | [DATA_MODEL.md](DATA_MODEL.md) |
| 2026-08-27 | Retry crea un nuevo Intento y preserva anteriores | No perder historia ni evidencia | Aprobada en F0; no reemplazada | [DATA_MODEL.md](DATA_MODEL.md) |
| 2026-08-27 | Recovery es requisito inicial | Los trabajos son largos y pueden interrumpirse | Aprobada en F0; no reemplazada | [DATA_MODEL.md](DATA_MODEL.md) |
| 2026-08-27 | Preferir interfaz programática antes que automatización visual | Robustez, exactitud y auditabilidad | Aprobada en F0; detalles a verificar en F1 | [COMFYUI_INTEGRATION.md](COMFYUI_INTEGRATION.md) |
| 2026-08-27 | FFmpeg/FFprobe tienen responsabilidad separada | Operaciones exactas de video | Aprobada en F0; política concreta abierta | [ARCHITECTURE.md](ARCHITECTURE.md) |
| 2026-08-27 | La UI no realiza trabajo pesado | Mantener respuesta durante ejecuciones largas | Aprobada en F0; no reemplazada | [ARCHITECTURE.md](ARCHITECTURE.md) |
| 2026-08-27 | Progreso basado en hechos reales | Evitar porcentajes o ETA inventados | Aprobada en F0; no reemplazada | [TESTING.md](TESTING.md) |
| 2026-08-27 | No sobrescribir ni destruir outputs silenciosamente | Seguridad y posibilidad de recovery | Aprobada en F0; no reemplazada | [RULES.md](RULES.md) |
| 2026-08-27 | El funcionamiento esencial no requiere IA | Reducir costo y dependencias obligatorias | Aprobada en F0; IA futura opcional | [PROJECT.md](PROJECT.md) |
| 2026-08-27 | Dirección UI → Aplicación/Casos de uso → Dominio | Separación durable de responsabilidades | Aprobada en F0; no reemplazada | [ARCHITECTURE.md](ARCHITECTURE.md) |
| 2026-08-27 | Infraestructura/adaptadores implementan contratos internos | Poder reemplazar detalles externos | Aprobada en F0; no reemplazada | [ARCHITECTURE.md](ARCHITECTURE.md) |
| 2026-08-27 | El dominio es independiente de detalles técnicos externos | Testabilidad y evolución | Aprobada en F0; no reemplazada | [DATA_MODEL.md](DATA_MODEL.md) |
| 2026-08-27 | Primer release: proyecto H3 de N chunks durable, recuperable y ensamblable | Definición comprobable del valor inicial | Aprobada en F0; ampliaciones fuera de alcance | [PROJECT.md](PROJECT.md) |
| 2026-08-27 | F6 valida recovery del pipeline y F7 recovery multi-chunk | Evitar confundir niveles de recuperación | Aprobada en F0; no reemplazada | [ROADMAP.md](ROADMAP.md) |
| 2026-08-27 | F0 es documental y no implementa producto | Congelar base antes de F1 | Aprobada en F0; F1 cerrada | [STATUS.md](STATUS.md) |
| 2026-08-27 | ComfyUI se integra detrás de un adaptador programático | F1 demostró API, WebSocket, history y outputs sin automatizar clicks | Respaldada por F1; implementación productiva pendiente | [COMFYUI_INTEGRATION.md](COMFYUI_INTEGRATION.md) |
| 2026-08-27 | El workflow UI canónico se conserva y el prompt API se deriva en memoria | F1 ejecutó B2–B7 sin modificar `Prueba Orquestador.json` | Respaldada por F1; profile formal pendiente | [COMFYUI_INTEGRATION.md](COMFYUI_INTEGRATION.md) |
| 2026-08-27 | `prompt_id` y descriptor de node 92 son la correlación de output | Evitar heurísticas de archivo reciente o nombre ambiguo | Respaldada por F1; persistencia propia pendiente | [COMFYUI_INTEGRATION.md](COMFYUI_INTEGRATION.md) |
| 2026-08-27 | Assets externos pueden subirse y referenciarse como `subfolder/name` | B5 y C2 conservaron hash idéntico | Respaldada por F1; política durable pendiente | [COMFYUI_INTEGRATION.md](COMFYUI_INTEGRATION.md) |
| 2026-08-27 | El Workflow Profile / binding H3 actual, observado y validado, usa slots densos y ordenados para la configuración externa del Reference Set; esto no define su schema durable definitivo | B7 y C2 conservaron `ref_image_0..5` y sus crops | Respaldada por F1; el schema durable y la persistencia productiva del Reference Set pertenecen a F2 | [DATA_MODEL.md](DATA_MODEL.md) |
| 2026-08-27 | El frame de transición es el último frame decodificado, seleccionado por índice | C1 probó `N-1` con firma pixel a pixel | Respaldada por F1; adaptador productivo pendiente | [DATA_MODEL.md](DATA_MODEL.md) |
| 2026-08-27 | FFmpeg/FFprobe son autoridad para video exacto | C1 y C3 verificaron extracción, firmas y concat compatible | Respaldada por F1; política productiva pendiente | [COMFYUI_INTEGRATION.md](COMFYUI_INTEGRATION.md) |
| 2026-08-27 | Queue/history de ComfyUI no sustituyen persistencia durable | Son memoria observable del backend | Respaldada por F1; schema durable pendiente | [ARCHITECTURE.md](ARCHITECTURE.md) |
| 2026-08-27 | La continuidad visual requiere validación humana | C3 fue reportado perfecto sólo para el seam probado | Respaldada para ese caso; no generalizable | [TESTING.md](TESTING.md) |

## Decisiones de diseño F2

## Decisiones de diseño F3

| Fecha | Decisión | Motivo breve | Estado | Autoridad |
|---|---|---|---|---|
| 2026-08-28 | El adaptador genérico devuelve todos los descriptores lógicamente validados; el workflow profile/binding seleccionará más adelante el artefacto esperado | Evitar selección heurística y acoplamiento H3 | Implementada en F3-3 lógico | [COMFYUI_INTEGRATION.md](COMFYUI_INTEGRATION.md) |

No hay fixture real F1 completo comprometido; la compatibilidad live requiere validación controlada antes del cierre de F3.

| Fecha | Decisión | Motivo breve | Estado | Autoridad |
|---|---|---|---|---|
| 2026-08-28 | No persistir una entidad `Checkpoint`; derivar el punto seguro del agregado durable y artefactos/transiciones verificados | Evitar estado duplicado y permitir recomputación auditable | Implementada en F2 | [DATA_MODEL.md](DATA_MODEL.md) |
| 2026-08-28 | `BackendJobRef` es opaco, opcional en Attempt, assign-once y preservado al reiniciar | Correlación durable sin acoplar el dominio al backend | Implementada en F2 | [DATA_MODEL.md](DATA_MODEL.md) |
| 2026-08-28 | Reconciliación pura, determinista y sin escrituras ocultas | Separar decisión de mutación y hacer recovery testeable | Implementada en F2 | [DATA_MODEL.md](DATA_MODEL.md) |
