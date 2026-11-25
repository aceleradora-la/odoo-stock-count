# Recuento de inventario (`stock_count`)

Recuentos físicos de inventario como documento, con app para contar y supervisar desde el
celular. Vista general e instalación en el [README del repositorio](../README.md).

## Menús

| Menú | Para qué |
|---|---|
| App **Recuentos** (menú principal) | Contar y supervisar desde el celular o el escritorio |
| Inventario › Operaciones › Recuentos › **Recuentos** | Crear, confirmar, revisar y validar recuentos |
| Inventario › Operaciones › Recuentos › **Contar** | La misma app, desde Inventario |
| Inventario › Operaciones › Recuentos › **Mis líneas de conteo** | Lista de las líneas del usuario, para cargar desde el escritorio |
| Inventario › Informes › **Análisis de recuentos** | Diferencias de los recuentos validados |
| Inventario › Configuración › **Motivos de diferencia** | Motivos que se asignan a las diferencias |

## Usuarios

- **Contador.** Ve los recuentos donde figura como contador y carga cantidades, motivo y
  comentario en sus líneas.
- **Supervisor.** Crea, confirma, reparte, revisa, aprueba y valida recuentos. Incluye
  Inventario / Usuario. Inventario / Administrador incluye Supervisor.

## Crear y confirmar

En el recuento se define:

- **Depósito y ubicaciones**, con o sin sub-ubicaciones.
- **Alcance**: todos los productos, productos seleccionados, una categoría o lotes /
  números de serie. *Incluir stock en cero* agrega líneas para productos del alcance que
  no tienen stock en la ubicación.
- **Supervisor y contadores.**
- **Bloqueo de movimientos**, umbrales de reconteo, tolerancia de aprobación y *Reconteo
  inmediato*. Toman por defecto los valores de los ajustes de Inventario.

**Confirmar** genera una línea por producto, ubicación, lote, paquete y propietario con la
cantidad del sistema de ese momento. No se puede confirmar si otro recuento activo ya
cubre el mismo producto en la misma ubicación.

**Repartir líneas** asigna las líneas a los contadores: por ubicación (cada ubicación
entera a un contador, balanceando la carga) o línea por línea. Una línea asignada solo la
carga su contador o el supervisor; una sin asignar, cualquier contador del recuento.

## Bloqueo de movimientos

Desde la confirmación hasta la validación o cancelación, cada producto en su ubicación
(y lote) queda controlado según el modo del recuento:

| Modo | Al validar un movimiento del producto en esa ubicación |
|---|---|
| Bloquear la validación | Se rechaza, con un mensaje que indica producto, ubicación, recuento y supervisor. Aplica a transferencias, fabricación, punto de venta, desechos y ajustes manuales. La reserva sigue permitida |
| Avisar y marcar la línea | El movimiento pasa, la línea queda marcada como *Movido durante el conteo* y el recuento lo registra en su historial |
| Sin control | El movimiento pasa. Al validar el recuento se detecta igual si el stock cambió |

Los productos en recuento no se pueden ajustar desde Inventario físico: el ajuste sale del
recuento. La lista de Inventario físico muestra la columna *En recuento*.

## Contar con la app

1. **Contar** muestra los recuentos del usuario con su avance.
2. Al abrir un recuento aparece una tarjeta por ubicación: pendiente, en curso o terminada.
3. La ubicación se abre tocando su tarjeta o escaneando su código.
4. En cada renglón se escribe la cantidad. Enter pasa al siguiente. **+1** suma una unidad.
5. **Terminar** cierra la ubicación; **Terminar conteo**, el recuento. Si quedan productos
   sin cantidad, la app avisa y, al confirmar, los registra en 0.

Funciones de la pantalla de conteo:

- **Escaneo** con lector físico, cámara o código escrito. Un producto escaneado suma una
  unidad en la ubicación abierta; el código de un embalaje suma un embalaje. Lee códigos
  GS1 con producto, lote y cantidad, y los códigos con peso de la nomenclatura clásica.
- **Producto no esperado.** Si el producto escaneado no figura en la ubicación abierta, la
  app ofrece agregarlo. También se agrega con el botón *Producto*.
- **Buscador y filtro Pendientes** en ubicaciones con más de seis productos: por nombre,
  código, código de barras, lote o paquete.
- **Números de serie.** Valen 0 o 1; escanear dos veces el mismo no suma.
- **Segundo conteo.** Los renglones a recontar aparecen marcados *2° conteo* y vacíos.
- **Sin conexión.** Cada cantidad se guarda en el teléfono y se envía en orden cuando hay
  señal. Una franja indica cuántas faltan enviar. Terminar, agregar productos, cambiar la
  unidad y supervisar necesitan conexión. La app debe abrirse con señal al menos una vez
  antes de entrar a una zona sin cobertura.
- **Instalar en el celular.** Botón en la pantalla de inicio de la app: queda con su ícono
  y abre directo en Recuentos.

También se puede contar desde *Mis líneas de conteo*, desde las líneas del recuento o
sobre la **hoja de conteo** impresa.

## Conteo en embalajes

Un producto se puede contar en un embalaje (caja, pack, bobina). El contador carga
**embalajes + sueltas** y el recuento calcula el total en la unidad del producto.

- **Odoo 19:** campo *Unidad de recuento* en la pestaña Inventario del producto, entre sus
  embalajes.
- **Odoo 18:** columna *Recuento* en los embalajes del producto, uno por producto.
- En la app, el contador puede cambiar la unidad de cada renglón entre la unidad del
  producto y sus embalajes. Lo ya cargado se conserva.
- La hoja de conteo, el informe de diferencias y el Excel muestran el desglose.

## Reconteo y aprobación

Cuando se carga la última línea, el recuento pasa a **En revisión** y clasifica cada línea:

| Diferencia | Resultado |
|---|---|
| Sin diferencia o dentro de *Aprobar automáticamente hasta (%)* | Aprobada |
| Supera *Reconteo si la diferencia supera* (% o unidades) | Reconteo: vuelve al contador |
| Entre ambos valores | Contada: espera al supervisor |

- Una diferencia cuyo valor es menor a *No recontar si el valor de la diferencia es menor
  a* no va a reconteo.
- Las líneas cerradas en 0 por *Terminar* nunca se aprueban solas.
- Tras el segundo conteo, la línea se aprueba si quedó dentro de la tolerancia; si no,
  espera al supervisor.
- Con **Reconteo inmediato**, el reconteo se pide en el momento de cargar la cantidad, sin
  esperar a que termine el conteo. Lo contado de a una unidad (escaneo, +1) se evalúa al
  terminar la ubicación.

Acciones del supervisor, por línea o en bloque: **Aprobar**, **Pedir reconteo**, **Aceptar
1er conteo**, **Omitir**, asignar **motivo**. Desde la app, la tarjeta **Supervisar**
muestra el avance por contador y las líneas para resolver, ordenadas por valor.

## Validar

Con todas las líneas aprobadas u omitidas el recuento se valida solo; también con el botón
**Validar**.

- Genera los ajustes de inventario con el nombre del recuento como referencia. Los
  movimientos quedan enlazados al recuento y a la línea.
- Si el motivo de la diferencia tiene *Ubicación de destino*, el faltante va a esa
  ubicación (por ejemplo, Desechos).
- Si el stock de una línea cambió después de la confirmación, el recuento no se valida:
  marca la línea y el supervisor decide con **Validar igualmente**.
- El valor de la diferencia usa el costo del producto al momento de validar.

**Cancelar** y **Volver a borrador** liberan los productos sin generar ajustes.

## Conteo ciego

Con *Conteo ciego* activo en los ajustes de Inventario, el contador no ve la cantidad del
sistema, la diferencia ni su valor en ninguna pantalla, exportación, filtro o agrupación,
ni el stock de los productos en recuento. El supervisor ve todo.

## Reportes

| Reporte | Contenido |
|---|---|
| Hoja de conteo (PDF) | Por contador y ubicación, con códigos de barras y columna para anotar. No muestra la cantidad del sistema |
| Informe de diferencias (PDF) | Líneas con diferencia ordenadas por valor: sistema, primer y segundo conteo, porcentaje, valor, motivo y contador |
| Exportar Excel | Todas las líneas del recuento |
| Análisis de recuentos | Tabla dinámica y gráfico por ubicación, depósito, producto, categoría, motivo, contador y mes |
| Ubicación | Recuentos validados, fecha del último y precisión de los últimos cinco |

## Datos técnicos

- Modelos: `stock.count`, `stock.count.line`, `stock.count.reason`.
- Dependencias: `stock`, `mail`, `barcodes`. Python: `xlsxwriter`.
- Tests: `odoo -d <base> -i stock_count --test-enable --test-tags /stock_count --stop-after-init`.
