# Recuento de inventario: conteo cíclico (`stock_count_cycle`)

Reglas que crean recuentos automáticamente y asignan la tarea al supervisor. Requiere
[`stock_count`](../stock_count/README.md).

Menú: Inventario › Configuración › **Reglas de conteo cíclico**.

## Tipos de regla

| Tipo | Cuándo crea un recuento | Qué incluye |
|---|---|---|
| Periódico | Cada N días, en la fecha *Próximo recuento* | Todas las ubicaciones de la regla |
| Rotación de valor | Cuando el valor a costo de lo que entró y salió de una ubicación desde su último recuento validado supera el importe configurado | Las ubicaciones que lo superaron |
| Precisión mínima | Cuando la precisión promedio de los últimos recuentos de una ubicación baja del mínimo | Las ubicaciones por debajo del mínimo |
| Confirmación de cero | Al validar un movimiento que deja un producto en cero en una ubicación de la regla | Ese producto en esa ubicación, con una línea en cero para confirmar |

## Configurar una regla

- **Depósito y ubicaciones**, con o sin sub-ubicaciones.
- **Productos**: todos, una categoría o una lista.
- **Supervisor, contadores y bloqueo de movimientos** que tendrá el recuento.
- **Planificar a (días)**: la fecha planificada del recuento es hoy más esos días.
- **Confirmar automáticamente**: el recuento se confirma al crearse. Si no se puede
  confirmar (por ejemplo, otro recuento activo cubre la ubicación), queda en borrador con
  el motivo en su historial.
- **No repetir antes de (días)**: en rotación, precisión y cero, tiempo mínimo entre dos
  recuentos de la misma ubicación.

Las reglas de rotación, precisión y cero no crean un recuento si ya tienen uno activo
sobre la misma ubicación.

## Qué recibe el supervisor

Cada recuento creado le genera la actividad **Realizar recuento**, con vencimiento en la
fecha planificada. La regla muestra sus recuentos generados y la última ejecución.

## Ejecución

- La acción planificada diaria *Recuento cíclico: generar recuentos* evalúa las reglas
  periódicas, de rotación y de precisión.
- La confirmación de cero se evalúa al validar cada movimiento.
- El botón **Generar ahora** crea el recuento de una regla periódica en el momento, sin
  esperar a la fecha de *Próximo recuento* (el siguiente se programa desde hoy). Si la
  regla ya tiene un recuento abierto, lo muestra en lugar de crear otro. En rotación y
  precisión, evalúa la condición hoy.
