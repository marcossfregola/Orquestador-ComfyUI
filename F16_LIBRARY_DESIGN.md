# F16 — Diseño preliminar de bibliotecas locales

**Estado:** investigación documental preparada dentro de F15 para auditoría. No constituye un contrato aprobado ni inicia la implementación de F16.

## Alcance aprobado

- **F16.0 — Investigación y diseño de bibliotecas.** Contrastar las alternativas de persistencia, integridad, deduplicación, eliminación e incorporación a borradores; resolver las decisiones de producto enumeradas abajo.
- **F16.1 — Biblioteca local de imágenes de referencia.**
- **F16.2 — Biblioteca local de prompts individuales.**
- **F16.3 — Integración GUI y validación.**

El orden está aprobado. F16.1–F16.3 no están iniciadas y requieren una autorización posterior a la auditoría F15.

## Hallazgos del código actual

- Los proyectos y ejecuciones existentes son la autoridad de preparación. `PreparationLibraryUseCase` crea borradores a través de `DraftUseCase`, y la GUI delega por `GuiFacade` y workers. No se encontró una entidad de biblioteca global de imágenes ni de prompts individuales.
- `PrepareGuiUseCase` mantiene `initial_image` y `references` como campos separados del snapshot editable. Importa sus bytes al área `inputs/` del proyecto; ante colisión de nombre usa un prefijo derivado del SHA-256 y comprueba el destino antes de persistir. Esto ofrece una ruta reutilizable para incorporar una imagen seleccionada a un borrador con las rutas que ya consumen Prepare y Start.
- `CloneConfigurationUseCase` valida que las imágenes existentes sean archivos relativos, contenidos en la raíz del proyecto, y copia sus rutas/configuración por valor. No crea una dependencia dinámica con la fuente. No conviene mover ni reinterpretar esas rutas al introducir una biblioteca.
- `CreateReferenceDerivativeUseCase` genera recortes PNG deterministas en `derived/references/`, con control de contención y colisiones. Es una operación de recorte por proyecto, no un catálogo de imágenes ni un generador de miniaturas; sus datos no deben convertirse implícitamente en recursos compartidos.
- `ChunkTemplatesUseCase` y la tabla `chunk_templates` guardan una plantilla con nombre y una secuencia ordenada de al menos dos prompts. Aplicarla reemplaza el plan de chunks de un borrador editable por copia. F16.2 trata un prompt individual para insertar en un campo elegido; no cambia ni reutiliza la plantilla como si fuera una entrada individual.
- `GenerationConfig` persiste rutas para una imagen inicial y de cero a seis referencias de usuario. El profile MiniMax H3 vincula esas rutas y conserva su orden. Si `first_frame_as_primary_reference` está activo, el primer frame ocupa Reference 1 y las referencias del usuario se desplazan; una selección desde la biblioteca debe mantener esta semántica.
- El SQLite actual llega a schema 10 y contiene proyectos, snapshots y `chunk_templates`, pero no un catálogo de imágenes, miniaturas ni entradas de prompt individuales. La eliminación de proyectos conserva los archivos físicos. La búsqueda del código no localizó un servicio actual de miniaturas.

Referencias de implementación: [preparation_library.py](src/orquestador/application/preparation_library.py), [prepare_gui.py](src/orquestador/application/prepare_gui.py), [clone_configuration.py](src/orquestador/application/clone_configuration.py), [create_reference_derivative.py](src/orquestador/application/create_reference_derivative.py), [chunk_templates.py](src/orquestador/application/chunk_templates.py), [config.py](src/orquestador/domain/config.py), [minimax_h3.py](src/orquestador/profiles/minimax_h3.py) y [sqlite.py](src/orquestador/persistence/sqlite.py).

La investigación de F15 usó código y documentos. No abrió la base SQLite de usuario ni leyó archivos de video reales.

## Alternativas concretas para F16.0

| Decisión | Alternativa A | Alternativa B | Consecuencia principal |
|---|---|---|---|
| Alcance del catálogo | Una biblioteca local compartida por los proyectos de la instalación. | Una biblioteca dentro de cada proyecto. | Compartir facilita reutilizar recursos; el catálogo por proyecto mejora su portabilidad y aislamiento. |
| Datos de imagen | Archivos administrados fuera de SQLite y metadatos en tablas versionadas. | Bytes de imagen como BLOB en SQLite. | Archivos reducen el tamaño de la base y reutilizan el patrón actual; BLOB concentra la transacción y complica copias y consultas grandes. |
| Ruta para borradores | Copiar el recurso elegido a `inputs/` del proyecto antes de guardar el snapshot. | Guardar una referencia estable al recurso compartido. | Copiar reutiliza el contrato actual y mantiene autónomos los proyectos; compartir ahorra espacio, pero requiere un nuevo modelo de referencias, manejo de disponibilidad y reglas de eliminación. |
| Miniaturas | Derivadas regenerables en caché, identificadas por hash del original y versión/tamaño del generador. | Archivos derivados durables junto al original. | La caché evita tratar una preview como original y se puede reconstruir; los derivados durables requieren versionado y limpieza propios. |
| Deduplicación | Un objeto por SHA-256 del contenido dentro del ámbito elegido, con entradas de catálogo separadas si se desean nombres/metadata distintos. | Conservar cada archivo importado, aunque sus bytes coincidan. | El hash exacto ahorra espacio y permite verificar integridad; conservar copias evita reglas de referencia compartida. |
| Eliminación | Ocultar/eliminar la entrada de catálogo y conservar el objeto; purgar físicamente sólo en una operación explícita tras probar que no hay referencias. | Papelera recuperable con purga posterior de objetos sin uso. | Ambas reducen el riesgo de borrar recursos usados; la segunda requiere metadatos de referencia y una política de retención. |
| Prompt individual | Entidad `PromptEntry` con texto editable y nombre opcional; selección copia el texto al chunk elegido. | Texto sin nombre, identificado sólo por contenido/hash y búsqueda. | El nombre facilita reconocer variantes; el hash evita entradas idénticas pero no expresa intención ni contexto. |

Como hipótesis de bajo impacto para evaluar en F16.0, se puede prototipar almacenamiento local de imágenes en archivos, metadatos durables separados, miniaturas regenerables y copia por valor al `inputs/` del borrador. Para prompts individuales se puede evaluar texto editable copiado al chunk elegido. Estas son opciones para comparar, no decisiones tomadas.

## Preservación e integridad

- No migrar, escanear, renombrar ni deduplicar automáticamente los proyectos existentes. Sus paths y snapshots se mantienen intactos; los nuevos recursos sólo entran al editar o crear un borrador que la aplicación declare editable.
- Si F16 agrega esquema, diseñar una migración aditiva desde schema 10 y probar bases antiguas hasta la versión nueva. Las filas históricas no deben ganar recursos sintéticos ni asociaciones implícitas.
- Para una imagen administrada: calcular SHA-256 al importar y verificarlo al leer; guardar tamaño y formato detectado; contener y validar toda ruta; publicar con creación atómica que no sobrescriba contenido distinto. Una entrada corrupta o ausente debe fallar cerradamente y no cambiar el borrador.
- Tratar las miniaturas como derivadas no autoritativas: tamaño acotado, formato/versionado definido, regeneración desde el original y ningún uso de una miniatura como input de generación.
- Mantener la política actual de no borrar archivos físicos automáticamente. Si existen referencias compartidas, resolver y bloquear ambigüedades antes de permitir purga.
- Toda selección se incorpora mediante casos de uso. Los widgets no acceden a SQLite ni manipulan directamente la raíz de recursos. La actualización de un borrador conserva su identidad, profile, parámetros y recursos no seleccionados.

## Incorporación a drafts y compatibilidad H3

F16.3 debe ofrecer destinos explícitos para **imagen inicial** y **referencia de usuario**. El borrador recibe una copia editable del valor elegido o una referencia compartida sólo si se aprueba e implementa su contrato. Aplicar un prompt individual copia un único texto al chunk seleccionado; no cambia cantidad/orden de chunks ni guarda un vínculo vivo con la biblioteca.

Para MiniMax H3, la integración debe preservar el orden de referencias, el máximo actual de seis referencias del usuario, la separación entre imagen inicial y referencias, y la opción `first_frame_as_primary_reference`. Los recursos añadidos no cambian los defaults, presets ni Chunk Templates; un draft con evidencia de ejecución o un QueueItem vivo sigue bloqueado por las capacidades existentes.

## Decisiones que requieren al dueño del producto

1. ¿La biblioteca de imágenes y la de prompts son compartidas por toda la instalación o están asociadas a cada proyecto?
2. Al seleccionar una imagen, ¿el draft debe guardar una copia independiente bajo `inputs/` o una referencia al objeto compartido?
3. ¿Cómo deben presentarse duplicados: una sola entrada con varias etiquetas/nombres, o entradas separadas que comparten bytes?
4. Al borrar una entrada, ¿se conserva siempre el archivo, se usa una papelera recuperable o se permite purga explícita cuando no haya referencias?
5. ¿Qué metadata mínima necesita cada recurso? Opciones: nombre, nota, etiquetas, origen, fecha, dimensiones y formato. Búsqueda avanzada y organización por carpetas quedarían fuera del alcance inicial salvo aprobación.
6. ¿Los prompts individuales necesitan nombre/categoría o basta texto; y al elegirlos, qué destino editable debe ofrecer la GUI?
7. ¿Qué formatos de imagen, límites de tamaño/dimensiones y formatos de miniatura se aceptan para la primera versión?

## Evidencia requerida para F16.0

Antes de implementar, cerrar las decisiones anteriores y producir un contrato con ubicación de datos, esquema/migración, importación atómica, deduplicación, referencias en uso, borrado, recuperación, compatibilidad de drafts H3, tratamiento de proyectos existentes y pruebas de preservación. La validación debe incluir duplicados, corrupción/hash cambiado, rutas escapadas, symlink/junction, miniaturas regeneradas, borrado con referencias, cancelación sin cambios parciales y conservación de proyectos anteriores.
