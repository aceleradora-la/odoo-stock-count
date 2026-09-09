# stock_count · Recuento de inventario

Recuento físico como transacción. Ver el [README del repositorio](../README.md) para
la descripción funcional completa y el plan de fases.

## Estado: fase 0 (esqueleto)

Lo que ya existe:

- Modelos `stock.count`, `stock.count.line`, `stock.count.reason` con todos los campos
  del diseño, estados y estadísticas calculadas (avance, diferencias, valor, precisión).
- Configuración por compañía en Inventario › Configuración: conteo ciego, modo de
  bloqueo por defecto, umbrales de reconteo y tolerancia de aprobación automática.
- Grupos **Contador** y **Supervisor** con reglas de registro: el contador solo ve los
  recuentos donde está asignado y sus propias líneas.
- Secuencia `RC/AAAA/00001`, motivos de diferencia por defecto, menús y vistas.
- Campos de enlace en `stock.move` (`count_id`), `stock.move.line` (`count_line_id`) y
  `stock.quant` (`count_line_id`).

Lo que viene en la fase 1: botones de transición, generación de líneas por alcance con
snapshot del teórico, aplicación de ajustes vía `stock.quant._apply_inventory`.

## Notas de compatibilidad 19.0

Verificado sobre `odoo/odoo` rama 19.0 (`addons/stock/models/stock_quant.py`):

- `_apply_inventory(self, date=None)` ahora acepta fecha. En 17.0 y 18.0 no lleva
  parámetros.
- El contexto `inventory_name` en 17.0 y 18.0 pone el `name` del movimiento; en 19.0 lo
  guarda en el campo nuevo `inventory_name` del `stock.move`.
- Los grupos ya no llevan `category_id`: se agrupan por `res.groups.privilege`. En
  `res.users`, `groups_id` pasó a `group_ids` / `all_group_ids`.
- El modelo de paquetes pasó de `stock.quant.package` a `stock.package`.
- `action_apply_inventory` abre el asistente `stock.inventory.conflict` si el quant está
  `is_outdated`. Nuestro flujo llama a `_apply_inventory` directamente y resuelve el
  conflicto con la lógica propia de "movido durante el conteo".
