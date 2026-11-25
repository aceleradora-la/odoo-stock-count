# Recuento de inventario: app Código de barras (`stock_count_barcode`)

Agrega la tarjeta **Recuentos** a la pantalla principal de la app Código de barras de Odoo
Enterprise. Requiere [`stock_count`](../stock_count/README.md) y `stock_barcode`.

## Instalación

Se instala solo cuando `stock_count` y Código de barras están instalados.

## Funcionamiento

- La tarjeta **Recuentos** aparece debajo de *Contar inventario* y muestra la cantidad de
  líneas pendientes del usuario.
- Al tocarla abre la pantalla **Contar** de la app Recuentos: ubicaciones con su avance,
  carga de cantidades, escaneo con lector físico o cámara, segundo conteo y producto no
  esperado.

El conteo y el escaneo son los de `stock_count` y funcionan igual en Community.
