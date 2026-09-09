# stock_count · Recuento de inventario

Recuento físico como transacción. Ver el [README del repositorio](../README.md) para
la descripción funcional completa y el plan de fases.

## Estado: fase 4 (núcleo, bloqueo, contador móvil, conteo ciego y reportes)

Flujo completo operativo:

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

### Bloqueo de movimientos (fase 2)

Desde que el recuento se confirma hasta que se aplica o cancela, el par producto +
ubicación (+ lote) de cada línea queda protegido según el modo del recuento:

- **Bloquear**: `stock.move._action_done` rechaza la validación con un mensaje que dice
  producto, ubicación, recuento y supervisor. Cubre transferencias, fabricación, punto de
  venta, desecho y ajustes manuales. La **reserva sigue permitida**.
- **Avisar**: el movimiento pasa, la línea queda marcada como "movida durante el conteo"
  y el chatter del recuento registra qué movimiento fue. Al aplicar, el supervisor decide.
- **Sin control**: nada en tiempo real; al aplicar se detecta igual si el quant cambió.

Además, el botón Aplicar de Inventario físico nativo (y el borrado de quants) se rechaza
sobre quants tomados por un recuento: el ajuste sale del recuento, no de la pantalla de
quants. La lista de quants muestra la columna "En recuento".

Los ajustes generados por el propio recuento llevan `count_id` y pasan el bloqueo.

### Roles y vista móvil (fase 3)

- **Contar** (Inventario › Operaciones › Recuentos › Contar): vista móvil OWL con las
  ubicaciones del contador y su avance, líneas con cantidad grande y +1, escaneo de
  ubicación o producto (lector físico o cámara: escanear un producto suma una unidad),
  "Siguiente ubicación" y "Producto no esperado". Funciona en Community.
- **Conteo ciego forzado por el ORM**: para el grupo Contador, teórico, actual,
  diferencia y valor se devuelven en cero en toda lectura; export, filtro y agrupación por
  esos campos se rechazan; una regla oculta los quants tomados por un recuento ciego. El
  contador solo puede escribir cantidades, motivo y comentario.
- **Repartir líneas**: por ubicación (cada ubicación entera a un solo contador,
  balanceando carga) o línea a línea; por defecto no toca lo asignado ni lo contado.
- **Producto no esperado**: desde el formulario o el móvil. Si el sistema tenía stock del
  producto (fuera del alcance), el teórico toma la cantidad del quant.

### Reportes (fase 4)

- **Hoja de conteo (PDF)**: por contador y ubicación, con código de barras de recuento,
  ubicación y producto, columna en blanco para anotar y firmas. Nunca muestra el teórico.
- **Informe de diferencias (PDF)**: solo supervisores. Líneas con diferencia ordenadas por
  valor, teórico / primer / segundo conteo, porcentaje, valor, motivo, quién contó,
  totales de sobrantes y faltantes, firmas.
- **Exportar Excel**: el mismo informe con todas las líneas, como adjunto descargable del
  recuento (requiere `xlsxwriter`, que Odoo ya trae).
- **Análisis de recuentos** (Inventario › Informes): pivot y gráfico sobre las líneas de
  recuentos aplicados, por ubicación, depósito, producto, categoría, motivo, contador y
  mes. Medidas: diferencia en unidades y en valor.
- **Ubicación**: recuentos aplicados, fecha del último y precisión promedio de los
  últimos cinco, con acceso a la lista de recuentos.

Lo que viene: retroport a 18.0 y 17.0, puente con Código de barras de Enterprise (fase 6)
y reglas de conteo cíclico que crean recuentos solos y asignan la tarea (fase 7).

## Notas de compatibilidad 19.0

Verificado sobre `odoo/odoo` rama 19.0 (`addons/stock/models/stock_quant.py`):

- `_apply_inventory(self, date=None)` ahora acepta fecha. En 17.0 y 18.0 no lleva
  parámetros.
- El contexto `inventory_name` en 17.0 y 18.0 pone el `name` del movimiento; en 19.0 lo
  guarda en el campo nuevo `inventory_name` del `stock.move`.
- Los grupos ya no llevan `category_id`: se agrupan por `res.groups.privilege`. En
  `res.users`, `groups_id` pasó a `group_ids` / `all_group_ids`.
- En las vistas de búsqueda, el `<group>` de "Agrupar por" ya no acepta `expand` ni `string`.
- El modelo de paquetes pasó de `stock.quant.package` a `stock.package`.
- Los dominios pueden llegar como objetos `Domain`; se recorren con `iter_conditions()`.
- `action_apply_inventory` abre el asistente `stock.inventory.conflict` si el quant está
  `is_outdated`. Nuestro flujo llama a `_apply_inventory` directamente y resuelve el
  conflicto con la lógica propia de "movido durante el conteo".
