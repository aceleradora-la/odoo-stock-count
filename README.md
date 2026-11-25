<p align="center">
  <img src="https://raw.githubusercontent.com/aceleradora-la/odoo-stock-count/19.0/stock_count/static/description/icon.png" width="96" alt="Recuento de inventario">
</p>

# Recuento de inventario para Odoo

Recuentos físicos de inventario como documento: se planifican, se cuentan desde el celular
o el escritorio, se recuentan las diferencias, un supervisor las aprueba y el recuento
genera los ajustes de inventario. Para Odoo Community y Enterprise.

| Módulo | Qué hace | Requiere |
|---|---|---|
| [`stock_count`](https://github.com/aceleradora-la/odoo-stock-count/blob/19.0/stock_count/README.md) | Recuentos, app **Recuentos** para contar y supervisar, bloqueo de movimientos, reconteo, aprobación, validación y reportes | `stock`, `mail`, `barcodes` |
| [`stock_count_cycle`](https://github.com/aceleradora-la/odoo-stock-count/blob/19.0/stock_count_cycle/README.md) | Reglas de conteo cíclico que crean los recuentos y asignan la tarea al responsable | `stock_count` |
| [`stock_count_barcode`](https://github.com/aceleradora-la/odoo-stock-count/blob/19.0/stock_count_barcode/README.md) | Tarjeta **Recuentos** dentro de la app Código de barras de Enterprise. Se instala solo | `stock_count`, `stock_barcode` |

## Versiones

| Rama | Odoo | Versión del módulo | Estado |
|---|---|---|---|
| [`19.0`](https://github.com/aceleradora-la/odoo-stock-count/tree/19.0) | 19.0 Community y Enterprise | 19.0.8.0.0 | Completo |
| [`18.0`](https://github.com/aceleradora-la/odoo-stock-count/tree/18.0) | 18.0 Community y Enterprise | 18.0.8.0.0 | Completo |
| [`17.0`](https://github.com/aceleradora-la/odoo-stock-count/tree/17.0) | 17.0 | 17.0.0.1.0 | En preparación: solo la estructura, sin funcionalidad |
| `main` | — | — | Documentación |

## Cómo funciona

1. **Crear el recuento.** Inventario › Operaciones › Recuentos › Nuevo. Se elige el
   depósito, las ubicaciones (con o sin sub-ubicaciones), qué productos entran (todos, una
   lista, una categoría o lotes), el supervisor, los contadores y el modo de bloqueo. El
   recuento toma un número `RC/AAAA/00001`.
2. **Confirmar.** El recuento genera una línea por cada producto, lote, paquete y
   propietario en stock dentro del alcance, con la cantidad del sistema guardada en ese
   momento. Desde acá los movimientos de esos productos en esas ubicaciones quedan
   controlados según el modo de bloqueo.
3. **Contar.** Cada contador abre la app **Recuentos**, entra a una ubicación y carga las
   cantidades escribiendo o escaneando. También se puede contar desde el escritorio o
   sobre la hoja de conteo impresa.
4. **Recontar.** Las líneas cuya diferencia supera el umbral vuelven al contador para un
   segundo conteo. El segundo conteo es el que vale.
5. **Revisar.** El supervisor ve las diferencias en unidades, porcentaje y valor, y
   aprueba, pide otro conteo, acepta el primer conteo u omite cada línea. Las líneas
   dentro de la tolerancia se aprueban solas.
6. **Validar.** Con todas las líneas resueltas, el recuento se valida y genera los ajustes
   de inventario, enlazados al recuento y a cada línea.

| Estado | Qué significa |
|---|---|
| Borrador | Se está definiendo el alcance |
| Confirmado | Líneas generadas y movimientos controlados; todavía nadie contó |
| En conteo | Los contadores están cargando cantidades |
| En revisión | Todo contado; quedan reconteos o aprobaciones |
| Validado | Ajustes de inventario generados |
| Cancelado | Sin ajustes; los productos quedan liberados |

El recuento avanza solo: pasa a *En conteo* con la primera cantidad, a *En revisión* con
la última y a *Validado* cuando no queda nada por aprobar.

## App Recuentos

Aplicación propia en el menú principal de Odoo, instalable en el celular con su ícono.

- **Contar.** Recuentos del contador → tarjetas por ubicación con su avance → renglones de
  la ubicación. Se escribe la cantidad y Enter pasa al renglón siguiente.
- **Escaneo.** Lector físico, cámara del celular o código escrito. Escanear una ubicación
  la abre; escanear un producto suma una unidad; el código de un embalaje suma un
  embalaje. Reconoce códigos GS1 con producto, lote y cantidad.
- **Embalajes.** Un producto con unidad de recuento (caja, pack) se carga en dos
  casilleros: embalajes y sueltas.
- **Producto no esperado.** Lo que aparece en una ubicación donde el sistema no lo tenía
  se agrega al recuento desde la app.
- **Sin conexión.** Las cantidades se guardan en el teléfono y se envían cuando vuelve la
  señal.
- **Supervisar.** Para supervisores: avance por contador, líneas para resolver, aprobar,
  pedir reconteo y validar.

## Configuración

Inventario › Configuración › Ajustes › **Recuento de inventario**:

| Ajuste | Efecto |
|---|---|
| Conteo ciego | Los contadores no ven la cantidad del sistema, la diferencia ni su valor |
| Bloqueo de movimientos | Modo por defecto de los recuentos nuevos: bloquear la validación, avisar y marcar la línea, o sin control |
| Reconteo inmediato | Si el primer conteo supera el umbral, la app pide contar de nuevo en el momento |
| Umbrales | Reconteo si la diferencia supera un porcentaje o una cantidad de unidades; aprobación automática hasta un porcentaje; no recontar si el valor de la diferencia es menor a un importe |

Otros puntos de configuración:

- **Usuarios.** Grupos *Contador* y *Supervisor* en la ficha del usuario.
- **Motivos de diferencia.** Inventario › Configuración › Motivos de diferencia.
- **Unidad de recuento.** En el producto, para contarlo en cajas o packs.
- **Reglas de conteo cíclico.** Inventario › Configuración › Reglas de conteo cíclico
  (módulo `stock_count_cycle`).

## Instalación

```bash
git clone -b 19.0 https://github.com/aceleradora-la/odoo-stock-count.git
```

Usar la rama de la versión de Odoo (`19.0` o `18.0`). Agregar la carpeta al `addons_path`,
actualizar la lista de aplicaciones e instalar **Recuento de inventario**. Para los
recuentos automáticos, instalar además **Recuento de inventario: conteo cíclico**.

En Odoo.sh, agregar el repositorio como submódulo en la rama de la versión.

Dependencia de Python: `xlsxwriter` (incluida en las instalaciones estándar de Odoo).

## Desarrollo

Ver [CONTRIBUTING.md](CONTRIBUTING.md). Cada rama corre lint y tests en GitHub Actions
sobre la imagen oficial de Odoo.

## Licencia y autor

[AGPL-3](LICENSE) · [aceleradora.la](https://aceleradora.la)
