# stock_count_cycle · Conteo cíclico

Extiende `stock_count` con **reglas que crean recuentos solas** y le dejan la tarea al
responsable como actividad. Inventario › Configuración › Reglas de conteo cíclico.

## Tipos de regla

| Tipo | Cuándo genera | Qué genera |
|---|---|---|
| **Periódico** | Cada N días, en la fecha "Próximo recuento" (editable) | Un recuento con todas las ubicaciones de la regla |
| **Rotación de valor** | Cuando el valor a costo de lo que entró y salió de una ubicación desde su último recuento aplicado supera el umbral | Un recuento con las ubicaciones que superaron el umbral |
| **Precisión mínima** | Cuando la precisión promedio de los últimos recuentos de la ubicación cae por debajo del mínimo | Un recuento con las ubicaciones por debajo |
| **Confirmación de cero** | Al validar un movimiento que deja un producto en cero en una ubicación de la regla | Un recuento del producto en esa ubicación, con línea en cero para confirmar que no queda nada |

Rotación, precisión y cero respetan un **enfriamiento** (días) para no repetir el mismo
recuento, y nunca generan uno si ya hay un recuento activo de la regla sobre la ubicación.

## Recuento generado

Toma de la regla el supervisor, los contadores, el modo de bloqueo y el alcance de
productos (todos, categoría o lista). La fecha planificada es hoy más "Planificar a (días)"
y es también el vencimiento de la **actividad "Realizar recuento"** que recibe el supervisor.

Con "Confirmar automáticamente" el recuento se confirma al crearse (snapshot y bloqueo).
Si no se puede confirmar (por ejemplo, otro recuento activo cubre la misma ubicación),
queda en borrador con el motivo en el chatter.

## Ejecución

- Cron diario "Recuento cíclico: generar recuentos" para periódico, rotación y precisión.
  Un error en una regla no frena a las demás.
- Confirmación de cero se evalúa al validar movimientos, sin cron.
- Botón "Generar ahora" en la regla para evaluarla en el momento.
