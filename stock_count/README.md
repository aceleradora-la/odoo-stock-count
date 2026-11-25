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
| Inventario › **Información general** | Tarjeta *Recuentos* de cada depósito: por contar, en revisión y en borrador |
| **Tableros** › Logística › **Recuentos** | Tablero de los recuentos validados |

## Usuarios

- **Contador.** Ve los recuentos donde figura como contador y carga cantidades, motivo y
  comentario en sus líneas.
- **Supervisor.** Crea, confirma, reparte, revisa, aprueba y valida recuentos. Incluye
  Inventario / Usuario. Inventario / Administrador incluye Supervisor.

## Crear y confirmar

En el recuento se define:

- **Depósito y ubicaciones**, con o sin sub-ubicaciones.
- **Alcance**: todos los productos, productos seleccionados, una categoría o lotes /
  números de serie.
- **Incluir stock en cero**: agrega una línea en cero por cada producto del alcance que
  no tiene stock en la ubicación y tuvo movimientos ahí desde su último recuento
  validado. Vale para cualquier alcance. Un producto que nunca se contó en esa ubicación
  entra con cualquier movimiento. Un recuento de *todos los productos* cuenta como
  último recuento de todo lo que hay en sus ubicaciones. Los productos por lote llevan
  una línea por lote; los de número de serie no se incluyen. Los ajustes de los
  recuentos no cuentan como movimiento.
- **Supervisor y contadores.**
- **Bloqueo de movimientos**, umbrales de reconteo, tolerancia de aprobación y *Reconteo
  inmediato*. Toman por defecto los valores de los ajustes de Inventario.

**Confirmar** genera una línea por producto, ubicación, lote, paquete y propietario. No se
puede confirmar si otro recuento activo ya cubre el mismo producto en la misma ubicación.
Un recuento confirmado todavía no bloquea movimientos: se puede repartir e imprimir la
hoja de conteo con el depósito trabajando.

**Iniciar conteo** toma la cantidad del sistema de ese momento como teórico y empieza el
bloqueo de movimientos. Si el stock cambió desde la confirmación, las líneas se ponen al
día: se actualiza la cantidad, se agregan los productos o lotes que aparecieron y se
quitan las líneas pendientes que ya no tienen stock. El conteo también se inicia solo
cuando un contador carga la primera cantidad.

**Repartir líneas** asigna las líneas a los contadores: por ubicación (cada ubicación
entera a un contador, balanceando la carga) o línea por línea. Una línea asignada solo la
carga su contador o el supervisor; una sin asignar, cualquier contador del recuento.

## Bloqueo de movimientos

Desde el inicio del conteo hasta la validación o cancelación, cada producto en su
ubicación (y lote) queda controlado según el modo de bloqueo:

| Modo | Al validar un movimiento del producto en esa ubicación |
|---|---|
| Bloquear la validación | Se rechaza, con un mensaje que indica producto, ubicación, recuento y supervisor. Aplica a transferencias, fabricación, punto de venta, desechos y ajustes manuales. La reserva sigue permitida |
| Avisar y marcar la línea | El movimiento pasa, la línea queda marcada como *Movido durante el conteo* y el recuento lo registra en su historial |
| Sin control | El movimiento pasa. Al validar el recuento se detecta igual si el stock cambió |

El modo se define en el recuento. Una categoría de producto o un producto pueden tener
el suyo (campo *Bloqueo de movimientos en recuento*): manda el del producto, después el
de su categoría y por último el del recuento.

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
sobre la **hoja de conteo** impresa. En esas listas, una línea sin contar muestra la
cantidad vacía; escribir 0 la deja contada en cero.

## Conteo en embalajes

Un producto se puede contar en uno o varios embalajes (pallet, caja, pack, bobina). El
contador carga un casillero por embalaje y otro para las **sueltas**, y el recuento calcula
el total en la unidad del producto.

- **Odoo 19:** campo *Unidades de recuento* en la pestaña Inventario del producto: uno o
  varios de sus embalajes.
- **Odoo 18:** columna *Recuento* en los embalajes del producto: uno o varios.
- En la app, el contador puede cambiar cada renglón entre la unidad del producto, uno
  solo de sus embalajes o todas las unidades de recuento. Lo ya cargado se conserva.
- Una cantidad cargada en la unidad del producto se reparte llenando primero el embalaje
  más grande. Escanear el código de un embalaje suma uno en su casillero.
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

**Umbrales por categoría o producto.** Una categoría de producto o un producto pueden
tener *Umbrales de recuento propios* (reconteo por % y por unidades, aprobación automática
y valor mínimo). Manda el producto, después su categoría o la primera categoría superior
que los tenga, y por último los del recuento.

**Avisos.** Cuando el recuento queda con líneas para aprobar, el supervisor del recuento
recibe la actividad *Aprobar recuento*. Cada contador con líneas en reconteo recibe la
actividad *Segundo conteo*. Las actividades se cierran solas cuando ya no hay nada que
hacer. Aprueba cualquier usuario del grupo Supervisor; el aviso va al supervisor del
recuento.

**El supervisor no aprueba lo que contó.** Con este ajuste de Inventario activo, un
supervisor no puede aprobar ni aceptar el primer conteo de las líneas que contó él mismo:
las resuelve otro supervisor. Vale el conteo vigente (el segundo, si lo hubo). Las acciones
en bloque dejan esas líneas sin tocar y avisan cuántas quedaron. La aprobación automática
por tolerancia no cambia.

Acciones del supervisor, por línea o en bloque: **Aprobar**, **Pedir reconteo**, **Aceptar
1er conteo**, **Omitir**, asignar **motivo**. Desde la app, la tarjeta **Supervisar**
muestra el avance por contador y las líneas para resolver, ordenadas por valor.

## Validar

Con todas las líneas aprobadas u omitidas el recuento se valida solo; también con el botón
**Validar**.

- Genera los ajustes de inventario con el nombre del recuento como referencia. Los
  movimientos quedan enlazados al recuento y a la línea, y llevan el tipo de operación
  *Recuentos* del depósito. En el historial de movimientos se encuentran con el filtro
  *Ajustes de recuentos* o buscando por ese tipo de operación.
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
| Informe de diferencias (PDF) | A4 apaisado. Líneas con diferencia ordenadas por valor: sistema, primer y segundo conteo, porcentaje, valor, motivo y contador |
| Exportar Excel | Todas las líneas del recuento |
| Análisis de recuentos | Tabla dinámica y gráfico por ubicación, depósito, producto, categoría, motivo, contador y mes |
| Ubicación | Recuentos validados, fecha del último y precisión de los últimos cinco |

**Precisión** es el porcentaje de líneas contadas sin diferencia o con una diferencia
dentro de *Aprobar automáticamente hasta (%)*.

## Tablero Recuentos

La app Tableros trae el tablero **Recuentos** (sección Logística), visible para el grupo
Supervisor. Lee las líneas de los recuentos validados.

- **Filtros:** período (fecha planificada del recuento), depósito, categoría de producto y
  producto.
- **Tarjetas:** recuentos validados, precisión, sobrantes, faltantes y neto en pesos, cada
  una comparada con el período anterior.
- **Gráficos:** sobrantes y faltantes por mes, y precisión por mes.
- **Tablas:** recuentos por mes, los 10 productos y las 10 ubicaciones con mayor
  diferencia en valor, y diferencias por motivo.

El archivo del tablero se genera con `tools/gen_dashboard.py`.

## Datos técnicos

- Modelos: `stock.count`, `stock.count.line`, `stock.count.reason`.
- Dependencias: `stock`, `mail`, `barcodes`, `spreadsheet_dashboard`. Python: `xlsxwriter`.
- Tests: `odoo -d <base> -i stock_count --test-enable --test-tags /stock_count --stop-after-init`.
