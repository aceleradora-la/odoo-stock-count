from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """El valor de la diferencia pasa a calcularse con un costo guardado en la línea.
    Las líneas que ya existían toman el costo actual del producto."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    lines = env["stock.count.line"].search([("unit_cost", "=", 0)])
    for line in lines:
        cost = line._current_unit_cost()
        if cost:
            line.unit_cost = cost
