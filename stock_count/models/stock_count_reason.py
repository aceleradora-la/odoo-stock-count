from odoo import fields, models


class StockCountReason(models.Model):
    _name = "stock.count.reason"
    _description = "Motivo de diferencia en recuento"
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True)
    code = fields.Char()
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    location_dest_id = fields.Many2one(
        "stock.location",
        string="Ubicación de destino",
        domain="[('usage', 'in', ('inventory', 'internal'))]",
        help="Si se define, los ajustes negativos con este motivo van a esta ubicación "
        "(por ejemplo Scrap) en lugar de la ubicación de ajuste de inventario.",
    )
    note = fields.Text()
