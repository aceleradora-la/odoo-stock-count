{
    "name": "Recuento de inventario",
    "summary": "Recuento físico como transacción: snapshot, bloqueo de movimientos, "
    "contadores, reconteo y trazabilidad de los ajustes",
    "version": "19.0.3.0.0",
    "category": "Inventory/Inventory",
    "author": "aceleradora.la",
    "website": "https://github.com/aceleradora-la/odoo-stock-count",
    "license": "AGPL-3",
    "depends": ["stock", "mail"],
    "data": [
        "security/stock_count_security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence_data.xml",
        "data/stock_count_reason_data.xml",
        "wizards/stock_count_assign_views.xml",
        "wizards/stock_count_add_product_views.xml",
        "views/stock_count_reason_views.xml",
        "views/stock_count_line_views.xml",
        "views/stock_count_views.xml",
        "views/res_config_settings_views.xml",
        "views/stock_quant_views.xml",
        "views/stock_count_menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "stock_count/static/src/counter/counter.scss",
            "stock_count/static/src/counter/counter.xml",
            "stock_count/static/src/counter/counter.js",
        ],
        "web.assets_tests": [
            "stock_count/static/tests/tours/**/*",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
