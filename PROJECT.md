# Proyecto

## Visión

Orquestador ComfyUI será una aplicación de escritorio independiente para Windows que prepare, ejecute, siga y recupere secuencias largas de video generativo por chunks. ComfyUI será el backend de inferencia; no será la interfaz principal del producto.

El flujo central es preparar un proyecto, generar chunks en orden, usar el último frame real de cada chunk como `first_frame` del siguiente, conservar los artefactos y producir un video final. El objetivo es eliminar la intervención humana repetitiva del flujo manual sin perder exactitud, trazabilidad ni capacidad de recuperación.

El producto es independiente de Visor de Videos, de cualquier Bridge de desarrollo y de las carpetas internas de ComfyUI. Un Bridge puede dirigir el desarrollo externamente, pero no es parte del runtime ni de la arquitectura del producto.

## Problema

El procedimiento manual actual exige volver periódicamente a ComfyUI para localizar un MP4 terminado, extraer su último fotograma, preparar el siguiente chunk y repetir la operación. Ese ciclo es largo, propenso a errores y difícil de reanudar después de un cierre, un fallo del backend o un output incompleto.

El problema a resolver no es demostrar que una generación aislada funciona, sino automatizar la cadena conservando evidencia suficiente para saber qué ocurrió y desde qué punto seguro continuar.

## Objetivos

- Automatizar el flujo secuencial de chunks sin intervención humana entre ellos.
- Preservar chunks, frames de transición, intentos y demás artefactos.
- Permitir retry y recovery sin destruir trabajo válido.
- Mostrar estados y progreso basados en hechos observables.
- Producir un video final además de conservar los intermedios.
- Mantener el funcionamiento esencial sin depender de IA o servicios cloud pagos.
- Nacer con fronteras que permitan crecer sin implementar ahora las expansiones futuras.

La arquitectura y los contratos que permiten estos objetivos están definidos en [ARCHITECTURE.md](ARCHITECTURE.md) y [DATA_MODEL.md](DATA_MODEL.md).

## Primer release

El primer release se define de forma breve y comprobable como:

> Una aplicación Windows capaz de ejecutar de forma durable y recuperable un proyecto MiniMax H3 de N chunks secuenciales, sin intervención humana entre chunks, utilizando el último frame exacto del chunk anterior como `first_frame` del siguiente, preservando artefactos y generando un video final.

Para demostrarlo, el release debe cubrir conceptualmente un proyecto local con imagen inicial, referencias, prompts manuales, parámetros comunes y N chunks; validación previa; ComfyUI local mediante interfaz programática; identificación inequívoca y validación de outputs; extracción y chaining del frame de transición; persistencia durable; historial de intentos; retry; recovery; preservación de artefactos; ensamblado final; errores explícitos; estado/progreso verificable; cancelación según capacidades comprobadas; y una GUI suficiente.

La estrategia de pruebas y el benchmark de aceptación están en [TESTING.md](TESTING.md).

## Alcance de F0

F0 fija producto, límites, arquitectura conceptual, semántica del dominio, estados, puntos seguros, retry, recovery y reconciliación conceptuales, responsabilidades de infraestructura, Workflow Profiles, hipótesis de integración, FFmpeg/FFprobe, background jobs, reglas y estrategia de pruebas. Es una fundación documental: no implementa funcionalidad del producto.

## No-alcance del primer release

Quedan fuera del primer release la IA de planificación, cloud o backend remoto, multi-GPU, múltiples backends, otros modelos o workflows, plugin system, integración con Visor, editor/timeline, branching o A/B, dashboard web, distribución comercial, installer sofisticado y auto-update.

Estas exclusiones no impiden que la arquitectura pueda evolucionar hacia ellas. Las ideas no comprometidas se registran en [BACKLOG.md](BACKLOG.md); la secuencia decidida está en [ROADMAP.md](ROADMAP.md).

## Restricciones de producto

- Windows y ejecución local son el contexto del primer release.
- ComfyUI es backend reemplazable, no la UI del producto.
- El chaining conserva la continuidad `último frame real del chunk N → first_frame del chunk N+1`.
- No se sobrescriben ni destruyen outputs silenciosamente.
- La UI no realiza trabajo pesado.
- El núcleo esencial no requiere IA ni APIs cloud pagas.
- Las decisiones técnicas aún abiertas se verifican en F1 y no se presentan como hechos.
