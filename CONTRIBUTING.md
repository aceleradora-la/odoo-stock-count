# Contribuir

## Ramas

- `main`: documentación. No lleva módulos.
- `17.0`, `18.0`, `19.0`: una rama por versión de Odoo. Los módulos viven en la raíz.
- El desarrollo nuevo entra por `18.0` y se porta a las otras dos ramas en un PR aparte.

## Convenciones

- Mensajes de commit al estilo Odoo: `[ADD]`, `[IMP]`, `[FIX]`, `[REF]`, `[REM]` seguido
  del módulo y una descripción corta en español.
- `pre-commit` antes de cada commit (`pip install pre-commit && pre-commit install`).
- Todo cambio de comportamiento lleva test en `stock_count/tests`.
- La versión del manifest sigue `X.0.a.b.c` donde `X` es la versión de Odoo.

## Correr los tests localmente

```bash
docker compose -f .github/docker-compose.test.yml up --abort-on-container-exit
```

o directamente contra una instancia propia:

```bash
odoo -d test_stock_count -i stock_count --test-enable --stop-after-init
```
