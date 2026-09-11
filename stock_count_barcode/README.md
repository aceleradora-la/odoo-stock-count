# stock_count_barcode · App Código de barras (Enterprise)

Puente entre `stock_count` y la app **Código de barras** de Odoo Enterprise
(`stock_barcode`). Se instala solo cuando ambos están presentes.

## Qué agrega

- **Tarjeta "Recuentos"** en la pantalla principal de la app, con la cantidad de líneas
  pendientes del usuario. Abre la vista **Contar** de `stock_count`: ubicaciones con
  avance, cantidad grande y +1, escaneo por lector físico, cámara o texto, reconteo,
  producto no esperado.
- **Menú "Recuentos"** en la barra superior de la app, como acceso alternativo.

El escaneo lo provee el módulo base: usa el servicio de código de barras de Odoo (lector
físico), el lector de vídeo del núcleo web (cámara) y la nomenclatura de la compañía
(GS1 con producto, lote y cantidad en un mismo código; nomenclatura clásica con peso).
Por eso el recuento se cuenta igual en Community y en Enterprise; este módulo solo lo
integra a la app.

## Decisión de diseño

No se modela el recuento como una operación (transferencia) de la app: una transferencia
mueve stock de origen a destino con cantidades hechas, y un recuento congela un teórico,
compara, reconta y recién al final genera ajustes. La tarjeta se inserta por DOM al
montar el menú, sin heredar la plantilla de Enterprise: si la estructura interna cambia,
la tarjeta puede no aparecer pero la app sigue funcionando y queda el menú superior.

## Estado

Escrito sin acceso al código fuente de `stock_barcode`; pendiente de validar en una base
Enterprise 19.0 (ids `stock_barcode.stock_barcode_menu` y ruta
`@stock_barcode/components/main_menu`). No se prueba en la CI del repositorio.
