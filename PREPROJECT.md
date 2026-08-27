# Orquestador de Generación de Video con ComfyUI — Preproyecto consolidado

**Estado:** preproyecto / documento de arranque  
**Fecha de consolidación:** 2026-08-25  
**Nombre del producto:** provisional; no fijado  
**Origen:** preproyecto base anterior + experiencia real con ComfyUI/MiniMax H3 + decisiones posteriores de arquitectura, metodología y escalabilidad + investigación externa sobre reutilización tecnológica  
**Propósito:** permitir iniciar el proyecto dentro de algunos días desde cero, de forma ordenada, sin depender de reconstruir conversaciones ni decisiones previas.

> Este archivo es una referencia de preproyecto, no la autoridad definitiva del futuro repositorio. Al iniciar formalmente el proyecto, sus decisiones confirmadas deben distribuirse en documentos autoridad (`PROJECT.md`, `ARCHITECTURE.md`, `DATA_MODEL.md`, etc.) y este archivo debe conservarse como antecedente histórico.

---

# 1. Visión

Crear una aplicación de escritorio independiente para Windows que permita preparar y ejecutar secuencias largas de video generativo usando ComfyUI como motor, eliminando la intervención humana repetitiva entre chunks.

Flujo conceptual:

**preparar proyecto → generar chunk 1 → detectar output correcto → extraer último frame exacto → usarlo como first_frame del chunk 2 → repetir → conservar chunks e intermedios → ensamblar resultado final → informar finalización**

El producto debe convertirse en el centro de:

- preparación;
- ejecución;
- seguimiento;
- recuperación;
- organización de chunks;
- validación;
- ensamblado final.

ComfyUI sigue siendo el motor de inferencia.

El producto **no** debe convertirse en otro ComfyUI, en un editor tradicional de video ni en una automatización frágil basada en clicks de escritorio.

---

# 2. Problema real que motiva el producto

El flujo manual actual ya fue probado con resultados aceptables:

1. cargar imagen inicial;
2. mantener imágenes de referencia de identidad;
3. configurar prompt y parámetros;
4. generar;
5. esperar;
6. localizar el MP4;
7. extraer el último fotograma;
8. volver a ComfyUI;
9. usar ese fotograma como nueva imagen inicial;
10. cambiar el prompt;
11. generar el siguiente chunk;
12. repetir;
13. unir los MP4.

El problema no es demostrar que el método puede funcionar, sino eliminar la necesidad de que el usuario vuelva cada 10–30+ minutos para continuar manualmente la cadena.

La aplicación debe reproducir automáticamente ese método, con más exactitud, trazabilidad y recuperación que el procedimiento manual.

---

# 3. Principios fundacionales de producto

1. **ComfyUI es backend, no interfaz principal del producto.**
2. **La continuidad probada se preserva:** último frame real del chunk anterior → first_frame del siguiente.
3. **Los chunks e intermedios se conservan.**
4. **Un fallo tardío no invalida todo el trabajo previo.**
5. **La aplicación debe poder reanudar desde un punto seguro.**
6. **No automatizar clicks si existe una interfaz programática robusta.**
7. **FFmpeg/FFprobe se usan para operaciones exactas de video.**
8. **La UI debe permanecer fluida; todo trabajo pesado va a background.**
9. **No destruir outputs ni sobrescribir silenciosamente.**
10. **Mostrar estados y progreso reales; no inventar porcentajes.**
11. **Primero resolver muy bien el flujo base; IA y expansiones vienen después.**
12. **Arquitectura de producto, alcance de MVP:** preparar desde el inicio fronteras limpias para crecer, sin implementar funciones futuras que todavía no son necesarias.
13. **No diseñar el producto como “un script para MiniMax H3”.** MiniMax H3 será el primer perfil/workflow soportado, no una limitación estructural.
14. **No depender estructuralmente del Visor de Videos.**
15. **No depender en runtime del Bridge de desarrollo.** El Bridge será herramienta de desarrollo, no componente obligatorio del producto distribuido.

---

# 4. Proyecto independiente y nacimiento ordenado

El Orquestador debe nacer como proyecto totalmente independiente:

- carpeta limpia;
- repositorio Git propio;
- GitHub propio;
- documentación propia;
- arquitectura propia;
- roadmap propio;
- backlog propio;
- pruebas propias;
- configuración propia;
- datos propios;
- versionado propio.

No comenzar acumulando scripts o funciones aisladas.

Antes de implementar funcionalidades debe existir una **fase fundacional explícita** dedicada a:

- producto;
- arquitectura;
- modelo de datos;
- máquina de estados;
- documentación;
- entorno;
- estrategia de pruebas;
- contratos con ComfyUI;
- reglas de desarrollo.

Invertir más tiempo al inicio es aceptable si evita reescrituras, reorganizaciones documentales o deuda estructural posterior.

---

# 5. Estado experimental actual que da origen al proyecto

Fotografía de trabajo actual, a revalidar al inicio formal:

- Windows.
- ComfyUI Desktop.
- MiniMax H3.
- Workflow actual basado en MiniMax H3 híbrido con first frame y referencias.
- Varias imágenes de referencia de identidad; uso habitual actual: hasta 6.
- Imagen inicial separada.
- `ref_image_size = match`.
- `also_ref_first_frame = false` observado en workflow previo.
- FFmpeg/FFprobe disponibles.
- GPU local NVIDIA RTX 5070 12 GB.
- RAM de sistema 32 GB.
- Se han realizado pruebas manuales de chaining de varios chunks con continuidad visual suficientemente prometedora.

Estos datos son históricos y deben verificarse otra vez contra la instalación real antes de convertirlos en contratos.

---

# 6. Método de continuidad validado

La continuidad deseada es:

**último fotograma exacto del chunk N → first_frame del chunk N+1**

manteniendo las referencias necesarias para identidad/consistencia.

No se quiere basar el flujo en:

- un frame “parecido”;
- un keyframe aproximado;
- una captura manual de VLC;
- reconocimiento visual de pantalla;
- coordenadas de mouse.

Preferencia inicial:

1. localizar MP4 terminado;
2. validar que terminó de escribirse;
3. usar FFprobe si hace falta;
4. extraer último frame exacto con FFmpeg;
5. guardar PNG;
6. validar que existe y es legible;
7. usarlo como first_frame del siguiente chunk;
8. conservarlo como evidencia/intermedio.

Nombres conceptuales:

```text
chunk_001.mp4
chunk_001_last_frame.png
chunk_002.mp4
chunk_002_last_frame.png
...
```

---

# 7. Hallazgos de investigación externa sobre reutilización tecnológica

Una investigación externa realizada antes del inicio formal concluyó que **no parece existir una aplicación completa equivalente**, pero sí componentes y patrones muy reutilizables.

Estos hallazgos **deben revalidarse al iniciar el proyecto** antes de adoptar dependencias o copiar código.

## 7.1 API local de ComfyUI

La investigación reportó como disponibles y relevantes:

- `POST /prompt`;
- `GET /queue`;
- `GET /history/{prompt_id}`;
- `POST /interrupt`;
- `GET /system_stats`;
- `POST /upload/image`;
- `GET /view`;
- WebSocket `/ws` con eventos de ejecución/progreso.

Decisión provisional:

> Para P0, preferir un adaptador pequeño sobre la API local nativa de ComfyUI antes que introducir capas innecesarias.

No diseñar alrededor de automatización visual.

## 7.2 SDK oficial / API v2

Se identificó un SDK oficial en evolución (`comfy-python-sdk`) y un proxy local asociado.

Decisión provisional:

- evaluarlo durante la investigación técnica;
- no hacerlo dependencia obligatoria del P0 sin comprobar que simplifica realmente el caso local;
- mantener el adaptador ComfyUI detrás de una interfaz propia para permitir cambiar de implementación.

## 7.3 Proyectos de referencia para chaining

Se identificaron como referencias a estudiar:

- `ComfyUI-MiniMaxH3-FlowDirector`;
- `ComfyUI_VideoChunkTools`;
- scripts externos tipo `comfyui-loop-enhanced`;
- wrappers/clientes API comunitarios.

Especial interés:

- chaining de last-frame → first-frame;
- planificación de bloques;
- detección de outputs;
- modificación programática de workflows;
- patrones de retry/queue.

Decisión:

> No forkear automáticamente ninguno como base del producto. Usarlos como referencia técnica y reutilizar únicamente componentes con licencia compatible, mantenimiento razonable y valor demostrado.

## 7.4 Clasificación provisional de reutilización

**B — existen componentes muy reutilizables, pero el núcleo del producto debe ser propio.**

Propio:

- dominio;
- orquestación;
- persistencia;
- recuperación;
- UI;
- gestión de proyectos;
- estados;
- intentos;
- ensamblado;
- bindings de producto.

Reutilizable:

- API/cliente ComfyUI;
- patrones de chaining;
- FFmpeg/FFprobe;
- algunas ideas de workflow bindings.

---

# 8. Arquitectura objetivo desde el inicio

La arquitectura debe estar preparada para crecer, sin sobrearquitectura.

```text
UI
│
▼
Aplicación / Casos de uso
│
├── Proyecto / Sesión
├── Chunks
├── Validación
├── Reintentos
└── Recuperación
│
▼
Orquestador
│
├── selección del siguiente trabajo
├── preparación de inputs
├── ejecución
├── reconciliación
└── avance de cadena
│
├───────────────┬────────────────┬─────────────────┐
▼               ▼                ▼                 ▼
Backend       Workflow         Video           Persistencia
ComfyUI       Bindings         FFmpeg          Proyectos/estado
│
▼
Perfiles de workflow
├── MiniMax H3 (primero)
├── futuros H3
├── Wan (futuro)
├── Hunyuan (futuro)
└── otros (futuro)

IA / Planner
└── opcional y desacoplado
```

Reglas:

- UI no habla directamente con ComfyUI.
- UI no ejecuta FFmpeg/FFprobe directamente.
- UI no conoce detalles de persistencia.
- Orquestador trabaja mediante contratos.
- Bindings de workflow están separados del dominio.
- Backend ComfyUI es reemplazable.
- Proveedor de IA futuro es reemplazable.
- Persistencia tiene esquema versionado y migraciones.
- No cargar videos completos en RAM innecesariamente.
- Una generación activa por GPU local por defecto.

---

# 9. Escalabilidad futura prevista, pero NO implementada de entrada

La arquitectura no debe impedir:

- múltiples perfiles de workflow;
- otros modelos;
- diferentes estrategias de chaining;
- biblioteca de personajes/referencias;
- presets;
- regeneración selectiva;
- branching de variantes;
- comparación A/B;
- IA para expansión de prompts;
- IA para planificación completa;
- IA para revisar continuidad;
- ejecución remota;
- ComfyUI en otra PC;
- cloud;
- múltiples GPUs/backends;
- cola avanzada;
- estimaciones por historial;
- integración con Visor de Videos;
- importación/exportación de proyectos;
- proyectos concurrentes cuando exista infraestructura real para ello;
- métricas de GPU/VRAM/RAM;
- distintos formatos de salida;
- plugins o extensiones si alguna vez se justifican.

Regla inversa:

> No implementar una capacidad futura solamente porque la arquitectura la contempla.

---

# 10. Modelo de dominio que debe definirse formalmente antes de programar el núcleo

Conceptos mínimos:

## Proyecto

Representa la preparación durable del trabajo.

Campos conceptuales:

- id;
- nombre;
- fecha;
- estado;
- imagen inicial;
- set de referencias;
- perfil de workflow;
- parámetros comunes;
- lista ordenada de chunks;
- carpeta de trabajo;
- output final;
- historial;
- timestamps.

## Sesión / Ejecución de proyecto

Distinguir la definición del proyecto de una ejecución concreta cuando sea necesario.

## Chunk

- id;
- índice/orden;
- intención;
- prompt final;
- parámetros efectivos;
- seed;
- first_frame resuelto;
- referencias efectivas;
- estado;
- output;
- último frame;
- duración de procesamiento;
- error;
- intentos.

## Intento

Un reintento no debe destruir el historial anterior.

Guardar:

- número de intento;
- parámetros;
- timestamps;
- errores;
- outputs parciales;
- resultado.

## Perfil de workflow

Describe qué workflow y qué bindings se usan.

## Binding

Mapea conceptos de dominio a inputs reales del workflow.

Ejemplo conceptual:

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

---

# 11. Máquina de estados

Debe diseñarse formalmente antes de que la UI o los servicios dependan de ella.

Estados de proyecto posibles:

- BORRADOR;
- LISTO;
- EJECUTANDO;
- PAUSADO;
- ERROR;
- COMPLETADO;
- CANCELADO.

Estados de chunk posibles:

- PENDIENTE;
- PREPARANDO;
- ENCOLADO;
- GENERANDO;
- VALIDANDO_OUTPUT;
- OUTPUT_DETECTADO;
- EXTRAYENDO_FRAME;
- COMPLETADO;
- ERROR;
- CANCELADO.

No es obligatorio conservar exactamente estos nombres.

Principios:

- una ejecución no puede marcarse completa si falta una fase crítica;
- pause != cancel;
- cancelar preserva trabajo previo;
- error conserva causa/evidencia;
- reintento crea nuevo intento;
- reconciliación después de crash verifica disco + estado persistido;
- no regenerar automáticamente un chunk válido sin necesidad.

---

# 12. Persistencia y recuperación

La recuperación no se agrega después; forma parte del diseño inicial.

Casos que el producto debe terminar soportando:

- cierre de la app;
- reinicio de Windows;
- cierre/reinicio de ComfyUI;
- error de generación;
- output inexistente;
- output incompleto;
- FFmpeg fallido;
- falta de memoria;
- pausa;
- cancelación;
- crash entre final de chunk y registro del siguiente paso.

Al volver:

1. leer estado durable;
2. inspeccionar artefactos existentes;
3. reconciliar;
4. identificar último punto seguro;
5. no destruir outputs;
6. permitir continuar/reintentar.

Tecnología definitiva a decidir en Fundación/Spike:

- SQLite;
- JSON versionado;
- combinación.

Requisitos:

- escritura atómica;
- esquema versionado;
- migraciones;
- backups mínimos;
- integridad ante cierre.

---

# 13. Parámetros y herencia

Parámetros de proyecto editables:

- cantidad de chunks;
- length;
- resolución/MP;
- steps;
- FPS;
- seed/política;
- referencias;
- workflow;
- carpeta de salida.

Cada chunk hereda parámetros del proyecto y puede tener overrides explícitos.

No obligar a repetir manualmente valores comunes.

Datos históricos actuales deben conservarse únicamente como referencia de benchmark y revalidarse si cambia el entorno.

---

# 14. Prompts e IA

Orden de implementación:

## Nivel A — Manual

Prompt completo por chunk.

Debe existir primero y ser completamente usable sin IA.

## Nivel B — Acción breve → prompt detallado

IA opcional:

- genera;
- muestra;
- permite editar;
- permite regenerar;
- permite bloquear.

## Nivel C — Objetivo global → planificación

IA decide dentro de límites:

- número de chunks;
- acción por chunk;
- transiciones;
- prompts;
- continuidad narrativa.

No forma parte del MVP inicial.

Debe existir una abstracción conceptual `Prompt Assistant / Planner`, no dependencia directa de un proveedor.

No decidir todavía:

- OpenAI;
- Ollama;
- otro proveedor;
- modelo;
- costos.

---

# 15. Workflow bindings y compatibilidad

El MVP soportará primero el workflow real de MiniMax H3.

No generalizar prematuramente.

Pero no dispersar IDs de nodos por todo el código.

Se debe investigar y definir un manifest/perfil versionado que pueda mapear:

- first_frame;
- prompt;
- referencias;
- length;
- steps;
- resolución;
- FPS;
- seed;
- output.

Opciones a evaluar:

- node_id + input;
- título;
- class_type;
- alias;
- combinación controlada.

Un cambio de workflow incompatible debe fallar con error claro antes de iniciar una sesión larga.

---

# 16. ComfyUI como backend

Responsabilidades del adaptador:

- health;
- endpoint configurable;
- cargar/preparar workflow;
- enviar prompt;
- identificar prompt/job;
- queue;
- eventos/progreso;
- history;
- outputs;
- cancelación/interrupción;
- errores;
- reconexión.

El núcleo no debe asumir para siempre `127.0.0.1`, aunque el primer release use ComfyUI local.

Backend remoto/cloud queda fuera de alcance inicial.

---

# 17. FFmpeg / FFprobe y ensamblado

Responsabilidades:

- validar outputs;
- obtener metadata;
- extraer último frame;
- comprobar compatibilidad;
- concatenar;
- re-encode solo cuando corresponda.

Preferencia para ensamblado:

- conservar todos los chunks;
- crear un final adicional;
- usar stream-copy solo si es técnicamente seguro;
- re-encode si es necesario.

Validar como mínimo:

- codec;
- resolución;
- FPS;
- timebase;
- pix format;
- audio;
- parámetros de contenedor relevantes.

Punto de UX/calidad a probar:

- conservar o deduplicar el frame idéntico de la unión entre chunks.

No fijarlo sin validación visual.

---

# 18. Observabilidad del producto

Durante una ejecución de horas mostrar:

- proyecto;
- chunk X/N;
- fase;
- tiempo actual;
- tiempo total;
- último evento;
- último output;
- salud de ComfyUI;
- error;
- qué falta.

Si ComfyUI ofrece progreso real del sampler, usarlo.

Si no, mostrar estados verificables.

No inventar ETA ni porcentaje.

A futuro se puede estimar por historial real de combinaciones:

- GPU;
- workflow;
- modelo;
- MP;
- steps;
- length;
- referencias.

---

# 19. Seguridad de archivos

Reglas permanentes previstas:

- no sobrescribir sesiones;
- nombres inequívocos;
- temporales dentro de carpeta controlada;
- validar rutas antes de borrar;
- no borrar chunks automáticamente;
- no borrar frames de transición automáticamente;
- distinguir output ComfyUI / copia del proyecto / output final;
- limpieza solo explícita;
- conservar evidencia útil de fallos.

---

# 20. Manejo de errores

Nunca transformar silenciosamente error en éxito.

Registrar:

- proyecto;
- chunk;
- intento;
- fase;
- timestamp;
- backend;
- mensaje;
- output;
- respuesta de ComfyUI relevante;
- comando FFmpeg si corresponde;
- posibilidad de retry;
- contexto mínimo para diagnóstico.

Ejemplos conceptuales:

- COMFY_NO_DISPONIBLE;
- WORKFLOW_INVALIDO;
- BINDING_ROTO;
- ERROR_COLA;
- ERROR_GENERACION;
- OUTPUT_NO_ENCONTRADO;
- OUTPUT_INCOMPLETO;
- FRAME_NO_EXTRAIDO;
- CONCAT_INCOMPATIBLE;
- ERROR_PERSISTENCIA.

---

# 21. Validación previa

Antes de iniciar una sesión larga:

- ComfyUI disponible;
- workflow compatible;
- bindings válidos;
- imagen inicial accesible;
- referencias accesibles;
- chunks válidos;
- prompts presentes;
- parámetros válidos;
- salida escribible;
- FFmpeg/FFprobe disponibles;
- espacio libre razonable;
- estado del proyecto consistente;
- no existe ejecución incompatible activa.

Objetivo: fallar en segundos, no después del primer render de 30 minutos.

---

# 22. Estrategia de pruebas

## Unitarias

- modelo de proyecto;
- chunks;
- estados;
- transiciones;
- validaciones;
- bindings;
- seeds;
- presets;
- rutas;
- reconciliación;
- compatibilidad de outputs.

## Integración

- API ComfyUI;
- workflow;
- queue/history/eventos;
- detección de output;
- FFmpeg;
- concatenación;
- persistencia;
- recovery.

## E2E

- 1 chunk;
- 2 chunks;
- 3 chunks;
- continuidad último→primero;
- error intermedio;
- retry;
- pausa;
- cancelación;
- cierre/reinicio;
- recuperación;
- ensamblado;
- preservación de intermedios.

## Validación humana

Obligatoria para:

- continuidad;
- identidad;
- seam;
- calidad;
- usabilidad;
- claridad de UI;
- facilidad de preparar sesiones.

---

# 23. Benchmark de aceptación P0

Para declarar demostrado el núcleo:

1. proyecto de 3 chunks;
2. workflow H3 conocido;
3. referencias conocidas;
4. first_frame manual solo al inicio;
5. prompts distintos;
6. ejecución completa sin intervención humana entre chunks;
7. 3 MP4 válidos;
8. 2 frames intermedios extraídos correctamente;
9. chaining automático;
10. output final;
11. evidencia conservada;
12. continuidad validada visualmente.

Ese benchmark demuestra el problema central, no el producto terminado.

---

# 24. Metodología de desarrollo prevista

El desarrollo debe ser ordenado por etapas pequeñas.

Roles previstos:

- **Usuario:** producto, prioridades, validación visual y autorizaciones sensibles.
- **ChatGPT Chat / Sol 5.6:** arquitecto y auditor principal.
- **Codex local / Luna o Terra:** desarrollador principal cuando el Bridge Codex esté disponible.
- **Sol en Codex:** excepcional para problemas muy complejos.
- **OpenCode:** auxiliar para tareas mecánicas, repetitivas, investigación o segunda ejecución cuando convenga.
- **Bridge Codex:** infraestructura de desarrollo, no dependencia runtime del producto.

Regla:

**problema → inspección → diagnóstico → cambio → prueba → auditoría → validación humana si corresponde → commit**

Un solo agente modifica el working tree principal a la vez.

No permitir:

- refactors no solicitados;
- funciones extra;
- cambios de stack injustificados;
- ocultar errores;
- relajar tests para hacerlos pasar;
- commits/push/tag/release sin autorización;
- borrar datos reales;
- introducir dependencias pagas para funciones esenciales.

---

# 25. Restricción económica

Objetivo del producto y del proceso de desarrollo:

**sin costos adicionales obligatorios más allá de las herramientas/suscripciones ya disponibles.**

Para el runtime esencial del Orquestador:

- ComfyUI local;
- modelos locales;
- FFmpeg;
- Python;
- librerías open source compatibles.

No introducir APIs cloud pagas como requisito del MVP.

Las funciones futuras de IA/cloud, si existen, deben ser opcionales y reemplazables.

---

# 26. Documentación fundacional del futuro repositorio

Crear desde el inicio:

- `README.md` — entrada al proyecto.
- `PROJECT.md` — visión, propósito, alcance, no-alcance.
- `ARCHITECTURE.md` — arquitectura, componentes, contratos, decisiones duraderas.
- `STATUS.md` — estado vivo verificable.
- `ROADMAP.md` — trabajo decidido.
- `BACKLOG.md` — ideas futuras no comprometidas.
- `RULES.md` — reglas permanentes de desarrollo y seguridad.
- `ENVIRONMENT.md` — entorno reproducible.
- `DATA_MODEL.md` — proyectos, sesiones, chunks, intentos, estados y persistencia.
- `COMFYUI_INTEGRATION.md` — API, workflow, bindings, compatibilidad.
- `TESTING.md` — estrategia de pruebas.
- `PERFORMANCE.md` — benchmarks reales cuando existan.
- `TROUBLESHOOTING.md` — recuperación y fallos recurrentes.
- `HISTORY.md` — hitos aprobados.
- `PREPROJECT.md` — este documento preservado como origen.

Cada categoría debe tener una sola autoridad.

No duplicar información profunda entre documentos.

---

# 27. Etapas fundacionales propuestas

## F0 — Fundación

Sin funcionalidad de producto.

Objetivos:

- crear repo;
- establecer documentos autoridad;
- congelar visión/MVP/no-alcance;
- definir arquitectura inicial;
- definir modelo de dominio;
- definir estados;
- definir reglas;
- registrar entorno;
- definir estrategia de pruebas;
- convertir investigación previa en hipótesis verificables.

No implementar GUI ni motor todavía.

## F1 — Spike técnico controlado

Investigación/pruebas descartables o aisladas:

- inspeccionar ComfyUI real;
- versión;
- custom nodes;
- workflow normal/API;
- API local;
- bindings;
- queue/history/eventos;
- cancelación;
- outputs;
- FFmpeg/FFprobe;
- estudiar repositorios externos;
- evaluar wrapper/API propia vs librería existente;
- render conocido;
- extracción real de último frame.

El spike no se convierte automáticamente en producción.

## F2 — Modelo de dominio + persistencia

- proyecto;
- chunk;
- intento;
- estados;
- migraciones;
- reconciliación;
- pruebas.

## F3 — Adaptador ComfyUI

- health;
- ejecución;
- progreso/eventos;
- outputs;
- errores;
- cancelación.

## F4 — Perfil/bindings MiniMax H3

Contrato explícito para el workflow real.

## F5 — Ejecución robusta de un chunk

Un chunk completo de punta a punta.

## F6 — Chaining 2–3 chunks

Último frame → siguiente first_frame.

## F7 — Recovery / retries

Fallos y reanudación.

## F8 — Ensamblado final

Concat/re-encode seguro.

## F9 — MVP de interfaz

La UI se apoya en un núcleo ya probado.

## F10 — Validación real del primer release

Uso real, UX, continuidad, instalación si corresponde y cierre.

El orden exacto puede ajustarse después de F0/F1, pero la lógica general debe preservarse.

---

# 28. Alcance inicial vs dirección futura

## Primer release

Debe resolver muy bien:

- proyecto local;
- MiniMax H3 real;
- imagen inicial;
- referencias;
- prompts manuales;
- parámetros comunes;
- N chunks secuenciales;
- API ComfyUI;
- detección de outputs;
- último frame exacto;
- chaining;
- persistencia;
- retry;
- recuperación;
- ensamblado;
- progreso;
- GUI suficiente.

## Fuera del primer release salvo necesidad demostrada

- IA de planificación;
- cloud;
- múltiples GPUs;
- múltiples backends simultáneos;
- plugin system;
- marketplace;
- colaboración;
- edición avanzada;
- timeline tradicional;
- automatización de escritorio;
- integración profunda con Visor;
- telemetría avanzada;
- dashboard web;
- distribución comercial.

---

# 29. Decisiones que NO deben fijarse todavía

No decidir definitivamente antes de F0/F1:

- nombre comercial;
- icono;
- framework UI;
- SQLite vs JSON/combinación;
- cliente ComfyUI exacto;
- SDK v2/proxy;
- formato definitivo de bindings;
- proveedor de IA;
- política final de seed;
- packaging/installer;
- licencia;
- distribución pública;
- soporte cloud;
- Wan/Hunyuan;
- plugin architecture;
- cantidad máxima de chunks;
- límite definitivo de referencias.

---

# 30. Relación futura con Visor de Videos

Posible integración futura:

1. seleccionar un frame en Visor;
2. “Generar continuación”;
3. abrir Orquestador con ese frame.

La frontera debe ser explícita:

- archivo de proyecto;
- comando;
- API local;
- deep link;
- otro protocolo evaluado.

El Visor no debe absorber ComfyUI ni el Orquestador depender internamente del Visor.

---

# 31. Criterio de escalabilidad

El proyecto estará bien preparado para escalar si:

- MiniMax H3 está encapsulado como perfil, no repartido por toda la aplicación;
- ComfyUI está detrás de un adaptador;
- UI depende de casos de uso, no de APIs externas;
- persistencia tiene esquema versionado;
- estados están formalizados;
- errores y reintentos son parte del dominio;
- bindings son versionados;
- IA es opcional;
- backend local/remoto puede evolucionar;
- documentación tiene autoridades claras;
- tests cubren contratos;
- las nuevas funciones pueden añadirse sin reescribir el núcleo.

No medir escalabilidad por cantidad de abstracciones o clases.

---

# 32. Regla de conservación de este preproyecto

Cuando se inicie formalmente:

1. verificar hechos contra PC/ComfyUI/repositorios vigentes;
2. distinguir decisiones de hipótesis;
3. convertir decisiones en documentos autoridad;
4. mover futuro no comprometido a `BACKLOG.md`;
5. mover trabajo aprobado a `ROADMAP.md`;
6. registrar arquitectura real;
7. conservar este archivo sin seguir usándolo como estado vivo.

---

# 33. Resumen ejecutivo para retomar dentro de días o meses

> El proyecto será una aplicación independiente de escritorio para automatizar generaciones largas por chunks usando ComfyUI como backend. El método base ya probado manualmente consiste en usar el último frame exacto de cada chunk como first_frame del siguiente, manteniendo referencias de identidad. El primer release debe automatizar ese flujo con persistencia, recuperación, reintentos, ensamblado y una GUI clara. La arquitectura debe nacer preparada para múltiples workflows/modelos, IA y backends futuros, pero sin implementar esas expansiones ahora. La investigación previa indica que la API de ComfyUI, clientes existentes y proyectos de chaining pueden reducir trabajo técnico, pero el dominio/orquestación/persistencia/UI serán propios. Antes de programar funcionalidades se realizará una Fundación documental/arquitectónica y después un Spike técnico controlado sobre el ComfyUI real. El desarrollo seguirá etapas pequeñas con ChatGPT Sol como arquitecto/auditor y Codex Luna/Terra como desarrollador principal cuando el Bridge Codex esté disponible. El Bridge es herramienta de desarrollo y no dependencia runtime. El objetivo es evitar desde el inicio la acumulación desordenada de scripts y funciones, preservar escalabilidad futura y reducir al mínimo la necesidad de reescrituras posteriores.
