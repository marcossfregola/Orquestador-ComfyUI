# Backlog

Este documento reúne ideas futuras no comprometidas. No cambia el alcance del primer release ni sustituye el trabajo decidido de [ROADMAP.md](ROADMAP.md).

## Producto y modelos futuros

- Perfiles para Wan, Hunyuan u otros modelos y workflows.
- Varios backends, ComfyUI remoto o cloud.
- Multi-GPU, concurrencia avanzada y planificación de recursos.
- Biblioteca avanzada de personajes y referencias, e importación/exportación de proyectos.
- Regeneración selectiva, branching, variantes y comparación A/B.
- Editor o timeline de video.
- Formatos de salida adicionales y políticas de calidad ampliadas.

## IA opcional

- Asistente que convierta una acción breve en un prompt editable.
- Planificador de una secuencia completa de chunks.
- Revisión asistida de continuidad o identidad.
- Proveedores locales o remotos intercambiables, sin convertirlos en requisito esencial.

## Integraciones y distribución

- Integración futura con Visor mediante archivo de proyecto, comando, API local, deep link u otro protocolo que se evalúe.
- Dashboard web, colaboración y telemetría avanzada.
- Plugin system o extensiones si existe una necesidad demostrada.
- Installer sofisticado, auto-update y distribución comercial.

## Operación y observabilidad

- Estimaciones basadas en historial real de GPU, workflow, modelo, resolución, steps, length y referencias.
- Métricas detalladas de GPU/VRAM/RAM.
- Limpieza asistida y políticas de retención configurables, siempre explícitas y recuperables.

## Trabajo promovido desde el cierre de F13.10

Los dos pendientes funcionales registrados al cierre de F13.10 —modo de inicio de cola configurable y finalización real después del ensamblado— fueron promovidos el 2026-09-27 a trabajo decidido dentro de F14. Su autoridad ya no es este backlog sino [ROADMAP.md](ROADMAP.md) y [FUNCTIONAL_COMPLETION.md](FUNCTIONAL_COMPLETION.md).

El nombre durable/renombrable de proyectos también se incorporó a F14 tras verificar que F13.6 conserva `ProjectId` como identidad y no persiste un nombre humano independiente.
