from odoo import fields, models


class StockMove(models.Model):
    _inherit = "stock.move"

    count_id = fields.Many2one(
        "stock.count",
        string="Recuento",
        index=True,
        copy=False,
        readonly=True,
        help="Recuento que generó este ajuste de inventario.",
    )


class StockMoveLine(models.Model):
    _inherit = "stock.move.line"

    count_line_id = fields.Many2one(
        "stock.count.line",
        string="Línea de recuento",
        index=True,
        copy=False,
        readonly=True,
    )
