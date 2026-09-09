{
    "name": "Recuento de inventario: conteo cíclico",
    "summary": "Reglas que crean recuentos automáticamente (periódicas, por rotación de "
    "valor, por precisión mínima y confirmación de cero) y asignan la tarea al responsable",
    "version": "18.0.1.0.0",
    "category": "Inventory/Inventory",
    "author": "aceleradora.la",
    "website": "https://github.com/aceleradora-la/odoo-stock-count",
    "license": "AGPL-3",
    "depends": ["stock_count"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron_data.xml",
        "views/stock_count_rule_views.xml",
        "views/stock_count_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
