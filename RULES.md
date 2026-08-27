# Reglas de desarrollo y operación

Estas reglas son permanentes salvo reemplazo explícito en [DECISIONS.md](DECISIONS.md) y el documento autoridad correspondiente.

## Alcance y autoridad

- El repositorio autorizado es `C:\Codex\Orquestador-ComfyUI`.
- No modificar Visor, Bridges, ComfyUI ni carpetas externas desde este proyecto.
- `PREPROJECT.md` es antecedente histórico y no se modifica.
- Cada tema tiene una única autoridad documental; los demás documentos enlazan en lugar de duplicar.
- No convertir hipótesis, antecedentes históricos o backlog en hechos o trabajo decidido.

## Proceso

Seguir la secuencia: **inspección → diagnóstico → cambio acotado → prueba → auditoría → validación humana cuando corresponda → commit autorizado**.

- Un solo agente modifica el working tree principal a la vez.
- No hacer refactors no solicitados, cambios de stack injustificados ni funciones extra.
- No relajar pruebas para hacerlas pasar ni ocultar errores.
- Todo cambio debe poder explicarse por una decisión o por un problema comprobado.

## Protección de datos y archivos

- No sobrescribir sesiones, outputs, chunks ni frames de transición silenciosamente.
- Usar nombres inequívocos y temporales dentro de una carpeta controlada.
- Validar rutas antes de borrar; limpieza sólo por acción explícita.
- No borrar automáticamente chunks, frames de transición ni evidencia de fallos.
- Distinguir output del backend, copia del proyecto y output final.
- Preservar historial de intentos y causa/evidencia de errores.

## Arquitectura y ejecución

- Mantener la dirección **UI → Aplicación/Casos de uso → Dominio**.
- Infraestructura y adaptadores implementan contratos requeridos por capas internas.
- El dominio no depende de Qt, ComfyUI, FFmpeg, SQLite, HTTP, WebSocket ni frameworks.
- La UI no habla directamente con ComfyUI, FFmpeg/FFprobe o persistencia.
- El trabajo pesado corre en background; la UI permanece fluida.
- El progreso se basa en hechos observables; no inventar porcentajes, ETA ni estados de éxito.
- Una generación activa por GPU local es el supuesto inicial hasta validar otra política.

## Git y auditoría

- Antes y después de cambios relevantes registrar ruta, raíz Git, rama, HEAD, status, diff, remote y demás evidencia solicitada.
- No crear remote, commit, push, tag o release sin autorización explícita.
- No declarar F0 cerrada sin auditoría, aprobación y commit autorizado posterior.
- Mantener ausencia de cambios staged no autorizados.
- Informar comandos y resultados reales; nunca simular pruebas o estados.

## Límites de agentes y costos

- Los agentes respetan el alcance de la fase y no avanzan a F1 sin autorización del roadmap.
- Bridge y otras herramientas de desarrollo no son dependencias runtime del producto.
- El núcleo esencial no puede exigir APIs cloud pagas; las expansiones de IA/cloud deben ser opcionales y reemplazables.
