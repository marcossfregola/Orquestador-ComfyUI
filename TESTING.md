# Estrategia de pruebas

F0 define cómo se probará el producto. No afirma pruebas de producto que todavía no existen ni ejecuciones contra ComfyUI que no se realizaron.

## Niveles

### Unitarias

Cubrir modelo de Proyecto, Ejecución, Chunk e Intento; estados y transiciones; validaciones; herencia y overrides de parámetros; bindings; seeds; rutas; compatibilidad de outputs; checkpoints; retry; y reglas de reconciliación.

### Integración

Cubrir el adaptador ComfyUI contra la instalación real; workflow y bindings; queue/history/eventos; detección inequívoca de output; uploads; cancelación y reconexión según capacidad; FFmpeg/FFprobe; extracción del frame; concat/re-encode; persistencia; escritura atómica; y recovery.

### E2E

Cubrir proyectos de uno, dos y tres chunks; continuidad último frame → siguiente `first_frame`; fallo intermedio; retry; pausa; cancelación; cierre/reinicio; recovery; ensamblado; preservación de intermedios; y errores explícitos.

### Ejecución real

F1 debe documentar experimentos reproducibles con versiones, workflow, inputs, comandos, respuestas, outputs, tiempos y límites. Los harnesses de F1 pueden ser descartables y no se convierten automáticamente en producción.

### Validación humana

Es obligatoria para continuidad visual, identidad, seam entre chunks, calidad, usabilidad, claridad de UI y facilidad de preparar una sesión. La evidencia visual complementa, pero no reemplaza, las validaciones automáticas.

## Preflight y contratos

Antes de una sesión larga se prueba que ComfyUI, el perfil, bindings, inputs, parámetros, salida, FFmpeg/FFprobe, espacio y estado durable sean coherentes. El objetivo es fallar en segundos cuando la causa ya es detectable.

Los contratos se prueban en sus límites: output parcial o ambiguo, backend reiniciado, evento perdido, binding ausente, frame ilegible, codec incompatible, persistencia interrumpida y cancelación no soportada.

## Benchmark de aceptación del núcleo

El benchmark de aceptación conceptual es un proyecto de tres chunks con workflow H3 conocido, referencias conocidas, `first_frame` manual sólo al inicio y prompts distintos. Debe:

1. ejecutarse sin intervención humana entre chunks;
2. producir tres MP4 válidos;
3. extraer correctamente dos frames intermedios;
4. encadenar automáticamente cada frame;
5. producir un output final;
6. conservar evidencia y artefactos;
7. demostrar continuidad visual mediante validación humana.

Este benchmark demuestra el problema central y no equivale por sí solo al cierre del producto.

## Evidencia requerida

Cada prueba relevante debe conservar, según corresponda:

- versión y configuración del entorno;
- proyecto, ejecución, chunk e intento;
- fase y timestamps;
- inputs y bindings efectivos;
- request/job y eventos relevantes del backend;
- rutas, hashes o metadata de artefactos;
- errores y comandos de FFmpeg/FFprobe;
- resultado esperado y observado;
- decisión de retry/recovery;
- validación humana cuando aplique.

No se debe afirmar “funciona” sin indicar qué se ejecutó, contra qué entorno y con qué evidencia.

## Estado de F0

Durante F0 no se implementó código de producto ni se ejecutaron pruebas contra ComfyUI, FFmpeg/FFprobe o una GUI. Se verificaron las precondiciones Git, se leyó `PREPROJECT.md` y se generaron documentos; la auditoría documental y las verificaciones finales son parte del cierre solicitado, no evidencia de funcionalidad del producto.

## Criterios de avance

- F1 no puede cerrarse sin evidencia del entorno real y de los contratos que se adopten.
- F5 requiere un chunk completo con output, validación, frame y checkpoint durables.
- F6 requiere recovery/retry del pipeline sin declarar recovery multi-chunk.
- F7 requiere por primera vez recovery completo de una cadena de dos o tres chunks.
- F10 reúne E2E, fallos, recovery, continuidad visual, UX y demás criterios del release.
