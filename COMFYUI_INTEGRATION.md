# Integración conceptual con ComfyUI

ComfyUI es el backend de inferencia del primer release. La aplicación lo usa mediante un adaptador detrás de contratos propios; no es la UI principal ni una dependencia del dominio.

## Responsabilidad del adaptador

El adaptador debe encapsular, según evidencia de la instalación real:

- health y endpoint configurable;
- carga o preparación de un workflow;
- aplicación de bindings y envío del trabajo;
- identificación inequívoca de la solicitud/job;
- queue, seguimiento, history y eventos/progreso;
- detección y recuperación de reconexiones;
- localización o consulta de outputs;
- traducción de respuestas y fallos a errores explícitos;
- cancelación/interrupción sólo con las capacidades realmente comprobadas.

La aplicación no debe depender de IDs de nodos, rutas de salida, HTTP, WebSocket o nombres propios del backend. Esos detalles pertenecen al adaptador y al perfil.

## Workflow Profiles

Un Workflow Profile es un contrato versionado que describe un workflow concreto, sus requisitos, compatibilidad y bindings. El primer perfil es MiniMax H3. H3 no se reparte por todo el núcleo ni limita la semántica del dominio.

Como mínimo, el perfil debe poder expresar conceptualmente:

- imagen inicial y `first_frame`;
- prompt;
- referencias y su orden;
- length/duración;
- steps;
- resolución/MP;
- FPS;
- seed o política de seed;
- output y su identificación.

Un cambio incompatible del workflow debe fallar durante preflight, antes de iniciar una sesión larga, con un error claro. El formato final del manifest y la estrategia de identificación (node id + input, título, `class_type`, alias o combinación controlada) quedan abiertos para F1.

## Bindings conceptuales

Un binding traduce un concepto del proyecto a un input real del workflow. Debe declarar suficiente información para validar que el objetivo existe, es del tipo esperado y no está ocupado por otra semántica. No se asume que cada binding sea una clase o tabla.

Ejemplos conceptuales:

```text
first_frame  -> node/input
prompt       -> node/input
length       -> node/input
steps        -> node/input
resolution   -> node/input
fps          -> node/input
seed         -> node/input
reference_1  -> node/input
...
```

Los bindings definitivos, límites efectivos de referencias/chunks, uploads e inyección de imágenes se verifican en F1.

## Preflight de integración

Antes de iniciar una ejecución larga se debe comprobar, con operaciones reales cuando F1 lo permita:

- ComfyUI disponible y endpoint accesible;
- workflow y versión compatibles;
- bindings resolubles y tipos válidos;
- imagen inicial y referencias legibles;
- prompts y parámetros dentro de límites;
- carpeta de salida escribible;
- correlación posible entre job, history y output;
- cancelación y reconexión conocidas o declaradas como no disponibles;
- FFmpeg/FFprobe disponibles para las fases que los requieren.

Fallos de preflight deben ocurrir en segundos y no después de un render largo.

## Outputs y progreso

El adaptador debe identificar el output correcto sin depender de una captura de pantalla o de un nombre ambiguo. La aplicación validará que el archivo terminó de escribirse y que es legible antes de extraer el frame de transición.

Si el backend ofrece progreso real del sampler, se puede exponer como evidencia. Si no, sólo se muestran fases y eventos verificables; no se inventan porcentajes ni ETA.

## Cancelación y recuperación

La semántica de cancelación, interrupción, jobs huérfanos y reconexión se mantiene abierta hasta observarla en F1. Un cierre o pérdida de conexión no se interpreta automáticamente como éxito o como permiso para regenerar. Recovery compara el estado durable, los artefactos y el backend observable; si no puede decidir, conserva la evidencia y emite un error explícito.

## FFmpeg/FFprobe

El adaptador ComfyUI no absorbe las operaciones exactas de video. Un adaptador separado valida outputs, obtiene metadata, extrae el último frame y ensambla chunks. La política de concat/re-encode, deduplicación del frame de unión y compatibilidad efectiva quedan para F1/F8.

## Hipótesis y preguntas de F1

Lo siguiente proviene de la investigación histórica de `PREPROJECT.md` y es hipótesis, no hecho actual:

- podrían existir endpoints locales equivalentes a `POST /prompt`, `GET /queue`, `GET /history/{prompt_id}`, `POST /interrupt`, `GET /system_stats`, `POST /upload/image` y `GET /view`;
- podría existir un WebSocket `/ws` con eventos de ejecución/progreso;
- `comfy-python-sdk` y un proxy local podrían ser útiles, pero no son dependencia aprobada;
- proyectos comunitarios como `ComfyUI-MiniMaxH3-FlowDirector`, `ComfyUI_VideoChunkTools` o wrappers de API podrían aportar patrones, sujetos a licencia, mantenimiento y valor demostrado.

F1 debe responder con evidencia: API y schema reales, queue/history/eventos, correlación prompt→output, uploads, cancelación, comportamiento tras reinicio, workflow JSON, límites de bindings, estrategia de cliente/SDK, y reutilización segura. No se adopta ni forkeará automáticamente un proyecto externo.

## Límites

El primer release usa ComfyUI local como backend. Backend remoto/cloud, múltiples backends y otros modelos/workflows están fuera de alcance; su posible incorporación queda en [BACKLOG.md](BACKLOG.md).
