# Entorno

Este documento separa hechos comprobados en el repositorio, antecedentes históricos de `PREPROJECT.md` y cuestiones que F1 debe revalidar. No convierte una fotografía antigua en contrato actual.

## Situación actual verificada del repositorio

La situación Git actual verificada es:

- repositorio: `C:\Codex\Orquestador-ComfyUI`;
- rama: `main`;
- Git es la autoridad para el HEAD actual; la verificación previa a esta corrección mostró rama `main`, estado limpio y HEAD `4bea00f97b27607bd9dde51adef1910c7b3076ee` (primer checkpoint documental de cierre F1, ya committeado; baseline pre-corrección final);
- workflow UI canónico: `C:\Users\Marcos Casa\AppData\Local\Comfy-Desktop\ComfyUI-Installs\PC casa\ComfyUI\user\default\workflows\Prueba Orquestador.json`;
- SHA-256 del workflow: `3070EB659A0BDB3D8392B0D203F6B4B86409709A20143280473A12C44BA4A7`;
- ComfyUI core verificado: `0.33.0`, endpoint `http://127.0.0.1:8188`;
- raíz de input compartido: `C:\Users\Marcos Casa\AppData\Local\Comfy-Desktop\ComfyUI-Shared\input`;
- raíz de output compartido: `C:\Users\Marcos Casa\AppData\Local\Comfy-Desktop\ComfyUI-Shared\output`;
- FFmpeg/FFprobe usados en F1: `C:\ProjectStorage\VisorVideo\tools\ffmpeg\bin`.

F1 queda CLOSED, sin código productivo. No se modificaron workflow ni assets durante los experimentos.

## Antecedentes históricos no contractuales

`PREPROJECT.md` registró, para revalidación, Windows, ComfyUI Desktop, MiniMax H3, un workflow híbrido con `first_frame` y referencias, uso habitual de hasta seis referencias, `ref_image_size = match`, `also_ref_first_frame = false`, disponibilidad histórica de FFmpeg/FFprobe, una NVIDIA RTX 5070 de 12 GB y 32 GB de RAM, además de pruebas manuales de chaining.

También registró como investigación previa los endpoints `/prompt`, `/queue`, `/history/{prompt_id}`, `/interrupt`, `/system_stats`, `/upload/image`, `/view` y `/ws`, junto con un SDK en evolución y proyectos comunitarios de referencia. Ninguno de esos datos se afirma aquí como disponible o compatible en la instalación actual.

## Revalidaciones de F1 verificadas

F1 confirmó, contra la instalación real:

- endpoints HTTP `/system_stats`, `/queue`, `/prompt`, `/history`, `/history/{prompt_id}`, `/object_info`, `/object_info/{class}`, `/features`, `/api/jobs`, `/api/jobs/{id}`, `/upload/image` y `/view`;
- WebSocket `/ws`, eventos de ejecución y progreso real del sampler;
- derivación del prompt API desde el workflow UI sin editarlo;
- correlación `prompt_id → history → node 92 → filename/subfolder/type → archivo físico`;
- upload de assets externos mediante `subfolder/name` relativo;
- seis referencias H3 densas y ordenadas, con crops, escalados y hashes preservables;
- extracción del último frame decodificado por índice y validación pixel a pixel;
- concat demuxer `-c copy` para dos MP4 H.264 compatibles.

Estos resultados son evidencia de spike, no dependencias productivas. Queue/history/jobs siguen siendo memoria observable del backend.

## Revalidaciones pendientes / no contractuales

F2/F3/F4/F6/F7/F8/F9 deben decidir y probar recovery tras crash/reinicio, retry y cancelación productivos, persistencia durable, contrato formal del profile, chaining largo, ensamblado, concurrencia, packaging, SDK/cliente y GUI. La evidencia F1 no convierte estos hechos en contrato.

## Principios de reproducibilidad

- Registrar el entorno real antes de convertir un comportamiento en contrato.
- Separar configuración del proyecto de la configuración del equipo.
- Mantener el endpoint configurable aunque el primer release use ComfyUI local.
- No elegir framework UI, persistencia, SDK, bindings definitivos ni packaging sólo por el resultado de un spike.
- El producto esencial debe poder operar localmente sin IA ni servicios cloud pagos.
