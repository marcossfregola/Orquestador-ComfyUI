# CODEX_TASK — captura dirigida del freeze real de Prepare

## Estado

F14.2 sigue abierta. La fase diagnóstica controlada no reprodujo el freeze humano de >30 s y no demostró regresión F14.2.

No iniciar F14.3. No modificar producción sin evidencia nueva.

## Objetivo

Capturar evidencia del incidente real usando el mismo proyecto/borrador e imagen que lo produjo, con mínima intervención humana.

## Procedimiento

1. Sin modificar producción, preparar un launcher/harness diagnóstico temporal que ejecute la aplicación real desde el repo actual y habilite `faulthandler`, identificación de hilos y timestamps alrededor de Prepare/render.
2. Usar el proyecto/DB reales existentes; no alterar datos salvo las escrituras normales de Prepare.
3. Pedir a la persona sólo que seleccione el mismo borrador de dos chunks y pulse `Prepare` una vez.
4. Registrar ruta, tamaño y dimensiones de la imagen real, y si está en disco local, carpeta sincronizada o red.
5. Si la GUI responde normalmente, registrar tiempo total y no inferir causa.
6. Si queda sin responder >5 s, capturar inmediatamente thread dump/stacks; si no alcanza, indicar el proceso exacto para obtener un Windows dump sin cerrar primero la app.
7. Registrar estado de Cola y confirmar cero submits a ComfyUI.
8. Comparar el stack real con preview/QPixmap, I/O, SQLite, scheduler, Qt/QThread u otra causa.
9. Detenerse tras diagnóstico. No implementar fix sin una causa demostrada y auditoría posterior.

## Evidencia requerida

- incidente reproducido SÍ/NO;
- ruta/tamaño/dimensiones de imagen;
- tiempos;
- thread dump o razón de ausencia;
- hilo/llamada bloqueante si se reproduce;
- estado SQLite y Cola;
- llamadas ComfyUI;
- causa raíz demostrada o hipótesis restantes;
- propuesta mínima de fix sólo si existe causa demostrada;
- confirmación F14.3 no iniciada.
