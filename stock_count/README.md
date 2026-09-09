# stock_count · Recuento de inventario

Recuento físico como transacción. Ver el [README del repositorio](../README.md) para
la descripción funcional completa y el plan de fases.

## Estado: fase 1 (núcleo funcional)

Flujo completo operativo, sin bloqueo de movimientos todavía (fase 2):

- **Confirmar**: genera una línea por quant del alcance (ubicaciones con o sin hijas;
  todos los productos, lista, categoría o lotes; opcionalmente líneas en cero) con la
  cantidad teórica congelada, toma los quants (`count_line_id`) y valida que no haya otro
  recuento activo sobre la misma clave producto / ubicación / lote.
- **Iniciar conteo**: los contadores cargan el primer conteo; el sistema registra quién y
  cuándo. Solo el asignado o el supervisor pueden cargar una línea asignada.
- **Enviar a revisión**: aprueba solas las líneas dentro de la tolerancia y manda a
  reconteo las que superan el umbral (porcentaje o unidades). El segundo conteo manda.
- **Revisión**: aprobar, pedir reconteo, omitir, asignar motivo, línea a línea o en bloque.
- **Aplicar**: detecta líneas cuyo quant ya no coincide con el teórico congelado
  ("movidas durante el conteo") y exige decisión explícita; genera los ajustes con
  `stock.quant._apply_inventory`, con el nombre del recuento como referencia, enlazados
  al recuento (`stock.move.count_id`) y a la línea (`stock.move.line.count_line_id`).
  Si el motivo tiene ubicación de destino, la pérdida va ahí (por ejemplo Scrap).
- **Cancelar / Volver a borrador**: liberan los quants sin generar ajustes.

Base de la fase 0: modelos con todos los campos del diseño, configuración por compañía
(conteo ciego, modo de bloqueo, umbrales), grupos **Contador** y **Supervisor** con reglas
de registro, secuencia `RC/AAAA/00001`, motivos de diferencia, menús y vistas.

Lo que viene en la fase 2: bloqueo de la validación de movimientos según `lock_mode`,
marca automática de "movido durante el conteo" en modo Avisar, bloqueo de "Aplicar" en
la pantalla nativa de Inventario físico sobre quants tomados.

## Notas de compatibilidad 19.0

Verificado sobre `odoo/odoo` rama 19.0 (`addons/stock/models/stock_quant.py`):

- `_apply_inventory(self, date=None)` ahora acepta fecha. En 17.0 y 18.0 no lleva
  parámetros.
- El contexto `inventory_name` en 17.0 y 18.0 pone el `name` del movimiento; en 19.0 lo
  guarda en el campo nuevo `inventory_name` del `stock.move`.
- `action_apply_inventory` abre el asistente `stock.inventory.conflict` si el quant está
  `is_outdated`. Nuestro flujo llama a `_apply_inventory` directamente y resuelve el
  conflicto con la lógica propia de "movido durante el conteo".
