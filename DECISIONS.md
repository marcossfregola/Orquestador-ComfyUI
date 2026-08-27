# Decisiones F0

Registro conciso. Cada entrada indica fecha, decisión, motivo, estado/reemplazo y documento autoridad.

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
| 2026-08-27 | F0 es documental y no implementa producto | Congelar base antes de F1 | Aprobada en F0; F1 aún no iniciada | [STATUS.md](STATUS.md) |
