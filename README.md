# Odoo Stock Count

Recuento de inventario como **transacción** para Odoo. Cada recuento es un documento con
número, estados, supervisor, contadores, cantidad teórica congelada al confirmar, bloqueo
de movimientos mientras se cuenta, reconteo por umbral y trazabilidad completa de los
ajustes que generó.

| | |
|---|---|
| **Módulos** | `stock_count` · `stock_count_cycle` (conteo cíclico) · `stock_count_barcode` (app Código de barras de Enterprise, se instala solo) |
| **Licencia** | AGPL-3 |
| **Versiones** | 17.0, 18.0, 19.0 — Community y Enterprise (ver [Ramas](#ramas)) |

## Por qué existe

Desde Odoo 15 el recuento vive en el quant: un responsable, una fecha y una cantidad
contada por línea de stock. No hay documento de recuento, nada se bloquea mientras se
cuenta, y al aplicar se pierde quién contó, cuánto contó y por qué había diferencia.

`stock_count` agrega la entidad **Recuento** (`stock.count`):

- Alcance por depósito, ubicaciones (con o sin hijas), productos, categoría o lotes.
- Al confirmar se toma un **snapshot**: una línea por quant con la cantidad teórica
  congelada, y se activa el **bloqueo** del par producto + ubicación.
- Modos de bloqueo por recuento: **bloquear** la validación de movimientos, solo
  **avisar** (el movimiento pasa y la línea queda marcada), o **sin control**.
  La reserva nunca se bloquea; solo la validación.
- **Contadores** cargan sus líneas (escritorio o celular). **Conteo ciego** configurable
  a nivel de compañía en Inventario › Configuración.
- **Supervisor** revisa diferencias en unidades, porcentaje y valor, pide **reconteos**
  por encima de un umbral, asigna motivos y aplica.
- La aplicación usa el motor nativo (`stock.quant._apply_inventory`), con el nombre del
  recuento como referencia del ajuste.
- Historial por ubicación, precisión, hoja de conteo PDF, informe de diferencias y
  análisis pivot.

## Ramas

| Rama | Odoo | Estado |
|---|---|---|
| `main` | — | Solo documentación, sin módulos |
| `17.0` | 17.0 CE / EE | Fase 0: esqueleto |
| `18.0` | 18.0 CE / EE | Fase 4: flujo completo, bloqueo, contador móvil, conteo ciego y reportes |
| `19.0` | 19.0 CE / EE | Fase 4: flujo completo, bloqueo, contador móvil, conteo ciego y reportes (rama de desarrollo principal) |

El desarrollo se hace primero sobre `19.0` y se retroporta a `18.0` y `17.0`.

## Instalación

```bash
git clone https://github.com/aceleradora-la/odoo-stock-count.git
cd odoo-stock-count
git checkout 18.0   # o 17.0 / 19.0
```

Agregar la carpeta al `addons_path`, actualizar la lista de aplicaciones e instalar
**Recuento de inventario** (`stock_count`). Depende solo de `stock` y `mail`.

## Plan de trabajo

| Fase | Contenido |
|---|---|
| 0 | Repo, ramas, CI, esqueleto del módulo, verificación del flujo de quants en 19.0 |
| 1 | Núcleo: entidad, líneas, snapshot, aplicación, seguridad, vistas, tests |
| 2 | Bloqueo de movimientos: modos, exclusividad entre recuentos, detección |
| 3 | Roles y revisión: vista de contador móvil, ciego, reconteo, motivos |
| 4 ✅ | Reportes: hoja de conteo, informe de diferencias, Excel, análisis (18.0 y 19.0) |
| 5 | Retroport a 17.0 |
| 6 ⏳ | Escaneo con lector físico, cámara y nomenclatura GS1 en la vista Contar (Community y Enterprise); `stock_count_barcode`: tarjeta y menú en la app Código de barras de Enterprise, pendiente de validar en una base Enterprise |
| 7 ✅ | `stock_count_cycle`: reglas de conteo cíclico que crean recuentos automáticamente y asignan la tarea al responsable (18.0 y 19.0) |

## Autor

[aceleradora.la](https://aceleradora.la)
