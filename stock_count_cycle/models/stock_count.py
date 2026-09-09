from odoo import fields, models


class StockCount(models.Model):
    _inherit = "stock.count"

    rule_id = fields.Many2one(
        "stock.count.rule",
        string="Regla de conteo cíclico",
        readonly=True,
        index=True,
        copy=False,
        help="Regla que generó este recuento automáticamente.",
    )
