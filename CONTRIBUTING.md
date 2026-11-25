# Contribuir

## Ramas

- `19.0`, `18.0`, `17.0`: una rama por versión de Odoo. Los módulos viven en la raíz.
- `main`: documentación. No lleva módulos.
- El desarrollo nuevo entra por `19.0` y se porta a `18.0`.

## Convenciones

- Mensajes de commit al estilo Odoo: `[ADD]`, `[IMP]`, `[FIX]`, `[REF]`, `[REM]` seguido
  del módulo y una descripción corta en español.
- `pre-commit` antes de cada commit (`pip install pre-commit && pre-commit install`).
- Todo cambio de comportamiento lleva test en la carpeta `tests` del módulo.
- La versión del manifest sigue `X.0.a.b.c`, donde `X.0` es la versión de Odoo.

## Tests

```bash
docker compose -f .github/docker-compose.test.yml up --abort-on-container-exit
```

o contra una instancia propia:

```bash
odoo -d test_stock_count -i stock_count,stock_count_cycle --test-enable \
  --test-tags /stock_count,/stock_count_cycle --stop-after-init
```

GitHub Actions corre lint y tests en cada push a `19.0` y `18.0`, sobre la imagen oficial
de Odoo. La app (JavaScript) y `stock_count_barcode` no se prueban en la CI.

## Diferencias entre versiones de Odoo

El código de `18.0` y `19.0` es el mismo salvo estos puntos:

| Tema | 18.0 | 19.0 |
|---|---|---|
| Embalajes | `product.packaging` (`qty`, `barcode`) | `uom.uom` en `product.template.uom_ids`; códigos en `product.uom` |
| Paquetes | `stock.quant.package` | `stock.package` |
| Grupos | `category_id`; `res.users.groups_id` | `res.groups.privilege`; `group_ids` / `all_group_ids` |
| `stock.quant._apply_inventory` | Sin parámetros; `inventory_name` pone el `name` del movimiento | Acepta `date`; `inventory_name` es un campo de `stock.move` |
| `stock.move.name` | Obligatorio | No existe |
| Vistas de búsqueda | `<group expand="0" string="...">` | `<group>` sin atributos |
| Dominios | Listas | Pueden llegar como `Domain`; se recorren con `iter_conditions()` |
| Reportes | `ir.actions.report.groups_id` | `group_ids` |

La adaptación de embalajes está en `stock_count/models/product.py`; el resto del código
usa los mismos métodos en las dos ramas.

## Íconos y portada de la tienda

Cada módulo tiene en `static/description`:

- `icon.png` (256 × 256): ícono del módulo en Aplicaciones y en la tienda de Odoo.
- `banner.png` (560 × 280): portada de la tienda, declarada en `images` del manifest.
- `index.html`: descripción que muestra la tienda de Odoo.

`stock_count` tiene además `icon.svg` (ícono del menú de la app) e `icon_192.png` /
`icon_512.png` (app instalable en el celular).
