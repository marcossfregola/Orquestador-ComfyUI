# Estado del proyecto

**Última actualización:** 2026-08-27
**Fase:** F1 — Spike técnico controlado
**Estado:** checkpoint técnico B2–C3 consolidado, sin commit de este checkpoint

## Fotografía viva

- F1 tiene evidencia controlada de B2–B7 y C1–C3 contra la instalación real de ComfyUI.
- C3 recibió validación humana explícita: la unión Chunk 1 → Chunk 2 fue reportada como perfecta e imperceptible.
- No se implementó código ni infraestructura de producción.
- La consolidación documental de este checkpoint está sin commit; el estado Git posterior debe leerse en la evidencia final.
- F1 permanece abierta: la evidencia actual no demuestra todavía recovery/retry productivo, persistencia durable, cancelación productiva, chaining largo ni GUI.

## Baseline conocido

La base documental vigente antes de esta consolidación fue:

- raíz de trabajo y raíz Git: `C:\Codex\Orquestador-ComfyUI`;
- rama: `main`;
- HEAD base: `de79777fdef6bd232f78611b021a16e4a8f2a81d`;
- workflow UI canónico: `Prueba Orquestador.json`;
- SHA-256 del workflow: `3070EB659A0BDBEB3D8392B0D203F6B4B86409709A20143280473A12C44BA4A7`.

La evidencia operativa de F1 y el estado Git posterior a esta consolidación se detallan en [COMFYUI_INTEGRATION.md](COMFYUI_INTEGRATION.md), [TESTING.md](TESTING.md) y la auditoría final de este cambio.

## Completado en F0

- Visión, problema, primer release, alcance y no-alcance.
- Dirección arquitectónica y fronteras núcleo/infraestructura.
- Semántica del dominio, estados, checkpoints, retry, recovery y reconciliación conceptuales.
- Responsabilidades de ComfyUI, Workflow Profiles, bindings e hipótesis F1.
- Responsabilidades conceptuales de FFmpeg/FFprobe y background jobs.
- Estrategia de pruebas, reglas de desarrollo, entorno y roadmap F0–F10.

## Completado en F1 hasta este checkpoint

- Derivación del prompt API desde el workflow UI sin modificarlo.
- Ejecuciones controladas B2–B7: override de prompt, referencia, upload, first frame y proyecto integrado.
- Extracción del último frame decodificado por índice con prueba pixel a pixel.
- Un chaining real Chunk 1 → Chunk 2 y ensamblado de validación con `-c copy`.
- Validación humana del primer seam.

## Pendiente para cerrar F1

- Recovery/retry ante crash, cierre, reinicio y jobs huérfanos.
- Persistencia durable, checkpoints y reconciliación implementables.
- Cancelación productiva, concurrencia segura y comportamiento de reconexión.
- Chaining de mayor longitud, ensamblado productivo y pruebas de fallo.
- Decisión y validación del primer Workflow Profile implementable.

## Criterio de cierre

F1 sólo podrá declararse cerrada cuando los pendientes técnicos estén resueltos con evidencia reproducible y una decisión formal actualice las autoridades correspondientes. Este checkpoint no autoriza todavía F2 ni implementación productiva.
