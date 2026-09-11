{
    "name": "Recuento de inventario: app Código de barras (Enterprise)",
    "summary": "Tarjeta 'Recuentos' en la app Código de barras de Odoo Enterprise que abre "
    "la vista de conteo móvil del recuento",
    "version": "18.0.1.0.0",
    "category": "Inventory/Inventory",
    "author": "aceleradora.la",
    "website": "https://github.com/aceleradora-la/odoo-stock-count",
    "license": "AGPL-3",
    "depends": ["stock_count", "stock_barcode"],
    "data": [],
    "assets": {
        "web.assets_backend": [
            "stock_count_barcode/static/src/main_menu/main_menu.js",
            "stock_count_barcode/static/src/main_menu/main_menu.scss",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": True,
}
