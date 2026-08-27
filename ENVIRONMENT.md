# Entorno

Este documento separa hechos comprobados en el repositorio, antecedentes históricos de `PREPROJECT.md` y cuestiones que F1 debe revalidar. No convierte una fotografía antigua en contrato actual.

## Situación actual verificada del repositorio

La situación Git actual verificada es:

- repositorio: `C:\Codex\Orquestador-ComfyUI`;
- rama: `main`;
- baseline HEAD: `c7bfff125c03791e78458663519db0d77404e522`;
- `PREPROJECT.md` y los doce documentos autoridad de F0 (`README.md`, `PROJECT.md`, `ARCHITECTURE.md`, `STATUS.md`, `ROADMAP.md`, `BACKLOG.md`, `RULES.md`, `ENVIRONMENT.md`, `DATA_MODEL.md`, `COMFYUI_INTEGRATION.md`, `TESTING.md` y `DECISIONS.md`) figuran actualmente como `untracked` (`??`) y están pendientes de revisión, aprobación y commit;
- todavía no existe un commit de F0; el HEAD continúa en el baseline indicado;
- F1 — Spike técnico controlado todavía no comenzó;
- no existe remote configurado ni tag.

La creación documental de F0 no instaló dependencias, no ejecutó ComfyUI y no ejecutó FFmpeg/FFprobe sobre datos reales. El hash verificado de `PREPROJECT.md` es `4ACD468623C01B8E2D6E53C9839B551CF69344FA7577D2B45E2CDBB95C213A7A`.

## Antecedentes históricos no contractuales

`PREPROJECT.md` registró, para revalidación, Windows, ComfyUI Desktop, MiniMax H3, un workflow híbrido con `first_frame` y referencias, uso habitual de hasta seis referencias, `ref_image_size = match`, `also_ref_first_frame = false`, disponibilidad histórica de FFmpeg/FFprobe, una NVIDIA RTX 5070 de 12 GB y 32 GB de RAM, además de pruebas manuales de chaining.

También registró como investigación previa los endpoints `/prompt`, `/queue`, `/history/{prompt_id}`, `/interrupt`, `/system_stats`, `/upload/image`, `/view` y `/ws`, junto con un SDK en evolución y proyectos comunitarios de referencia. Ninguno de esos datos se afirma aquí como disponible o compatible en la instalación actual.

## Revalidaciones de F1

F1 debe obtener evidencia reproducible sobre:

- versión y variante de ComfyUI, custom nodes y modelos instalados;
- workflow normal y JSON de API del H3 real;
- mecanismo efectivo de queue, history, eventos, progreso y correlación de outputs;
- uploads, rutas y permisos;
- cancelación/interrupción observable y sus límites;
- outputs completos, metadata y detección de fin de escritura;
- FFmpeg/FFprobe, codecs, resolución, FPS, timebase, pix format, audio y concat;
- bindings, manifest/versionado y compatibilidad ante cambios del workflow;
- espacio libre, memoria, GPU y concurrencia segura;
- opciones de SDK, cliente propio o librerías externas con licencia compatible.

F1 debe registrar versiones, comandos, respuestas, artefactos de prueba y límites. Un experimento descartable no se convierte por sí solo en dependencia de producción.

## Principios de reproducibilidad

- Registrar el entorno real antes de convertir un comportamiento en contrato.
- Separar configuración del proyecto de la configuración del equipo.
- Mantener el endpoint configurable aunque el primer release use ComfyUI local.
- No elegir framework UI, persistencia, SDK, bindings definitivos ni packaging durante F0.
- El producto esencial debe poder operar localmente sin IA ni servicios cloud pagos.
