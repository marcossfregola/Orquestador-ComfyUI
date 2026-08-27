# Arquitectura

## Dirección obligatoria

La dependencia conceptual del producto es:

**UI → Aplicación/Casos de uso → Dominio**

Persistencia, ComfyUI, Workflow Profiles/bindings, FFmpeg/FFprobe y background jobs son infraestructura o adaptadores. Implementan contratos requeridos por las capas internas; las capas internas no dependen de sus detalles.

## Fronteras

### UI

Presenta proyectos, ejecuciones, chunks, estados, eventos, errores y acciones disponibles. Solicita casos de uso y recibe resultados o cambios de estado observables. No habla directamente con ComfyUI, FFmpeg/FFprobe ni la persistencia, y no ejecuta trabajo pesado.

### Aplicación y casos de uso

Coordina operaciones como crear o validar un proyecto, iniciar una ejecución, avanzar al siguiente chunk, reintentar, cancelar, reconciliar y ensamblar. Define la secuencia de trabajo y usa contratos internos para solicitar servicios externos. No contiene detalles de Qt, HTTP, WebSocket, comandos concretos o schema de almacenamiento.

### Dominio

Define el significado de Proyecto, Ejecución, Chunk, Intento, Artefacto, Workflow Profile, estados, transiciones, checkpoints, retry, recovery, errores y reglas de continuidad. Debe ser determinista y testeable sin infraestructura.

El dominio no depende de Qt, ComfyUI, FFmpeg, SQLite, JSON, HTTP, WebSocket, frameworks ni otros detalles técnicos externos.

### Puertos y adaptadores

Los contratos de aplicación/dominio expresan lo que se necesita: persistir un estado durable, consultar o enviar trabajo a un backend, observar eventos, validar o transformar video y ejecutar trabajo en background. Los adaptadores proporcionan esas capacidades y traducen errores externos a conceptos explícitos del producto.

No se elige en F0 un framework UI, tecnología de persistencia, SDK/cliente ComfyUI ni formato final de bindings. Esas decisiones son hipótesis de F1.

## Componentes conceptuales

- **Gestión de proyecto y ejecución:** mantiene la preparación durable separada de cada corrida concreta.
- **Orquestador de aplicación:** selecciona el siguiente trabajo, prepara inputs, coordina generación, validación, extracción del frame y avance de la cadena.
- **Dominio:** aplica invariantes, estados y condiciones para marcar una fase como completada.
- **Adaptador ComfyUI:** realiza health, envío, seguimiento, history, outputs, reconexión y cancelación según evidencia real.
- **Workflow Profile y bindings:** describen el workflow soportado y mapean conceptos del proyecto a inputs del workflow sin repartir IDs de nodos por el núcleo.
- **Adaptador de video:** usa FFmpeg/FFprobe para metadata, validación, extracción del último frame y ensamblado.
- **Persistencia:** conserva estado versionado, intentos, checkpoints y referencias a artefactos mediante un contrato durable.
- **Background jobs:** ejecutan generación, inspección y video fuera del hilo de UI, con cancelación y eventos según capacidades reales.

La semántica de los conceptos y sus relaciones es autoridad de [DATA_MODEL.md](DATA_MODEL.md). Las responsabilidades específicas de ComfyUI y los bindings están en [COMFYUI_INTEGRATION.md](COMFYUI_INTEGRATION.md).

## Flujo conceptual de una ejecución

1. La UI solicita validar e iniciar una ejecución.
2. La aplicación consulta el estado durable y ejecuta preflight.
3. El dominio selecciona el primer chunk pendiente o el checkpoint reconciliado.
4. Un adaptador prepara los inputs a través del Workflow Profile y los envía a ComfyUI.
5. La aplicación observa el trabajo, identifica el output inequívoco y pide validación de video.
6. El adaptador de video extrae y valida el frame de transición.
7. La aplicación registra durablemente el intento, el output y el checkpoint antes de avanzar.
8. El siguiente chunk consume ese frame como `first_frame` y conserva el resto de las referencias.
9. Al completar todos los chunks, el adaptador de video crea un ensamblado final adicional.

Un cierre puede ocurrir entre cualquiera de estos pasos. En el siguiente inicio, recovery compara estado durable, artefactos y backend observable antes de continuar; no asume que la última operación terminó sólo porque existió una solicitud.

## Dependencias permitidas

- UI depende de casos de uso, no de adaptadores externos.
- Aplicación depende de contratos y del dominio.
- Dominio depende sólo de conceptos y reglas propias.
- Adaptadores dependen de sus librerías o procesos externos y traducen hacia contratos internos.
- Un Workflow Profile puede depender de la forma de un workflow concreto, pero el dominio no.

## Principios duraderos

- Una generación activa por GPU local por defecto hasta contar con evidencia de concurrencia segura.
- El último frame real del chunk N es el origen del `first_frame` del chunk N+1.
- Los chunks, intermedios, intentos y evidencia útil se conservan.
- Un output válido no se regenera automáticamente sin necesidad demostrada.
- Un estado COMPLETADO requiere evidencia suficiente, no sólo ausencia de error.
- Pause no equivale a cancel; cancelar preserva el trabajo previo.
- Los errores son explícitos y trazables.
- El progreso refleja hechos reales; no se inventan porcentajes ni ETA.
- Las fronteras se preparan para perfiles, backends y asistentes futuros sin implementar esas funciones en F0.

## Qué no decide F0

Persistencia concreta, schema, framework UI, cliente o SDK ComfyUI, endpoints exactos, WebSocket real, política FFmpeg, packaging, límites efectivos, concurrencia segura y librerías externas quedan abiertos para F1. La lista operativa de preguntas está en [COMFYUI_INTEGRATION.md](COMFYUI_INTEGRATION.md) y [ENVIRONMENT.md](ENVIRONMENT.md).
