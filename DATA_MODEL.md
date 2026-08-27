# Modelo de dominio

Este documento define semántica, relaciones, invariantes y estados conceptuales. No fija todavía campos definitivos, clases concretas, tablas ni schema SQL.

## Conceptos centrales

### Proyecto

Es la definición durable del trabajo: nombre, intención, recursos iniciales, referencias, perfil de workflow, parámetros comunes, orden de chunks, carpeta de trabajo y resultado esperado. Un Proyecto puede tener más de una ejecución a lo largo del tiempo.

### Ejecución

Es una corrida concreta de un Proyecto. Mantiene su propio inicio, estado, decisiones efectivas, historial de intentos, checkpoints y resultado de esa corrida. Proyecto y Ejecución son conceptos distintos: editar la preparación no reescribe una ejecución histórica.

### Chunk

Es una unidad ordenada de generación dentro de una Ejecución. Tiene una intención/prompt, parámetros efectivos, un `first_frame` resuelto cuando corresponde, referencias, estado, outputs y una relación con sus Intentos. El chunk N y el chunk N+1 se vinculan por el frame de transición, no sólo por su índice.

### Intento

Es una ejecución concreta de un Chunk. Un retry crea un nuevo Intento; nunca borra ni transforma silenciosamente los intentos anteriores. Cada intento conserva parámetros efectivos, timestamps, fase, errores, outputs parciales y resultado.

### Artefacto

Es un archivo o evidencia producida, recibida o preservada por el proceso: input, output de ComfyUI, copia controlada del proyecto, frame de transición, metadata, log o ensamblado final. Mantiene trazabilidad hacia su origen (Proyecto, Ejecución, Chunk, Intento y fase cuando exista) y no se considera intercambiable sólo por tener un nombre parecido.

### Workflow Profile

Es una descripción versionada del workflow soportado y de los bindings necesarios para traducir conceptos del proyecto a inputs reales. MiniMax H3 es el primer perfil, no una limitación estructural del dominio.

## Conceptos relacionados

- **Input:** recurso o valor que una fase consume, como imagen inicial, referencia, prompt o parámetro. Su procedencia, legibilidad y uso efectivo deben ser rastreables.
- **Output:** resultado observado de una fase, como un MP4 de chunk o metadata. Un output sólo puede usarse para avanzar cuando está identificado y validado según el contrato vigente.
- **Binding:** mapeo entre un concepto (por ejemplo `first_frame`, `prompt`, `length` o `seed`) y un punto de entrada del Workflow Profile. No obliga a que cada binding sea una entidad independiente.
- **Error:** hecho explícito con fase, contexto, timestamp, causa observable y posibilidad de retry/recovery. Nunca se convierte silenciosamente en éxito.
- **Frame de transición:** artefacto derivado del último fotograma exacto de un output válido; es el candidato a `first_frame` del chunk siguiente y conserva su origen.
- **Ensamblado:** operación que combina chunks compatibles para producir un resultado final adicional, preservando los originales.
- **Estado:** representación del progreso conceptual de Proyecto, Ejecución, Chunk o Intento, sujeta a evidencia y transiciones permitidas.
- **Checkpoint/punto seguro:** registro durable que identifica hasta qué fase se puede continuar sin repetir trabajo válido. No es sólo un porcentaje.
- **Reconciliación:** comparación, después de una interrupción o al iniciar, entre estado durable, artefactos existentes y estado observable del backend para decidir continuar, validar, marcar error o crear un nuevo Intento.

## Relaciones

- Un Proyecto prepara cero o más Ejecuciones.
- Una Ejecución materializa una secuencia ordenada de Chunks.
- Cada Chunk puede tener uno o más Intentos, con a lo sumo un resultado elegido para avanzar según evidencia.
- Un Intento produce o referencia Artefactos y Errores.
- Un Artefacto conserva la trazabilidad de su origen y de las transformaciones posteriores.
- Una Ejecución usa un Workflow Profile versionado; el perfil y sus bindings no redefinen la semántica del dominio.
- El frame de transición elegido de un Chunk puede ser el Input `first_frame` del Chunk siguiente, con relación explícita de procedencia.
- El Ensamblado consume outputs de chunks seleccionados y produce otro Artefacto, sin sustituir los insumos.

## Estados conceptuales

Los nombres siguientes son vocabulario de F0; pueden refinarse sin alterar sus significados.

### Proyecto / Ejecución

`BORRADOR` → `LISTO` → `EJECUTANDO` → `COMPLETADO`  
Desde `EJECUTANDO` puede pasarse a `PAUSADO`, `ERROR` o `CANCELADO`, y una reconciliación puede devolver a un estado reanudable cuando exista un punto seguro.

- `BORRADOR`: preparación incompleta o editable.
- `LISTO`: preflight suficiente para intentar iniciar.
- `EJECUTANDO`: existe trabajo activo o avance coordinado.
- `PAUSADO`: no se solicita nuevo avance, pero el trabajo previo permanece.
- `ERROR`: existe una causa o inconsistencia que requiere decisión, retry o recovery.
- `COMPLETADO`: todos los chunks y el ensamblado requerido tienen evidencia válida.
- `CANCELADO`: la ejecución fue detenida de forma explícita; el trabajo previo se conserva.

### Chunk

`PENDIENTE` → `PREPARANDO` → `ENCOLADO` → `GENERANDO` → `VALIDANDO_OUTPUT` → `OUTPUT_DETECTADO` → `EXTRAYENDO_FRAME` → `COMPLETADO`.

Desde las fases activas puede llegarse a `ERROR` o `CANCELADO` según evidencia. Un `ERROR` puede originar otro Intento; `CANCELADO` no elimina intentos ni artefactos previos.

Un Chunk no se marca `COMPLETADO` si falta output válido, validación requerida, frame de transición cuando el chaining lo necesita, registro durable o evidencia equivalente definida por el perfil.

### Intento

Un Intento nace al comenzar una tentativa concreta, avanza por las fases disponibles y termina con resultado válido, error explícito o cancelación. Un retry siempre crea otro Intento y mantiene el vínculo con el anterior.

## Invariantes

1. Proyecto y Ejecución no se confunden ni comparten silenciosamente el estado mutable.
2. Chunk e Intento son distintos; un retry no reescribe el historial.
3. El chaining usa el último frame real del output válido del chunk anterior como `first_frame` del siguiente.
4. Un Artefacto conserva trazabilidad hacia su origen y no se reemplaza por nombre.
5. Un output válido no se regenera automáticamente sin necesidad demostrada.
6. `COMPLETADO` exige evidencia suficiente de todas las fases críticas.
7. Cancelar preserva el trabajo previo y no equivale a borrar o marcar éxito.
8. Un checkpoint sólo habilita continuar desde una fase segura; no autoriza repetir trabajo válido por defecto.
9. Recovery compara estado durable, artefactos y backend observable antes de elegir la acción.
10. Ninguna transición convierte un error desconocido en éxito.
11. El ensamblado final es adicional y no destruye chunks ni intermedios.
12. Los parámetros heredados y los overrides efectivos de cada chunk quedan distinguibles para poder reproducir el intento.

## Checkpoints y recovery conceptual

Después de cada fase crítica, la aplicación registra durablemente el estado, referencias a artefactos y evidencia suficiente antes de avanzar. Un punto seguro típico es: output inequívoco identificado y validado, frame de transición extraído y validado, y relación con el siguiente input preparada o registrada.

Al volver tras cierre, crash o reinicio:

1. leer el último estado durable;
2. inspeccionar los Artefactos esperados y existentes;
3. consultar el backend si la operación podría seguir viva;
4. comparar esas fuentes y clasificar el resultado como completo, reanudable, incompleto o inconsistente;
5. conservar todo lo encontrado;
6. continuar desde el checkpoint seguro, esperar/validar el output pendiente o crear un nuevo Intento con causa explícita.

La política concreta de almacenamiento, atomicidad, versionado y migraciones queda abierta para F1/F2.

## Límites de F0

No se fijan schema SQL, tablas, clases, nombres definitivos de campos, tecnología de persistencia, serialización ni implementación de estados. Esos detalles sólo se decidirán después de la evidencia técnica y de una revisión del modelo.
