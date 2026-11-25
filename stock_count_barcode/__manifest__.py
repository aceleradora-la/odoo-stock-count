{
    "name": "Recuento de inventario: app Código de barras",
    "summary": "Tarjeta Recuentos en la app Código de barras de Odoo Enterprise",
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
    "images": ["static/description/banner.png"],
    "installable": True,
    "application": False,
    "auto_install": True,
}
