from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """La precisión pasa a contar como acertadas las líneas dentro de la tolerancia de
    aprobación: se recalcula en los recuentos que ya existían."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    env["stock.count"].search([])._compute_line_stats()
