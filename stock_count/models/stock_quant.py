from odoo import fields, models


class StockQuant(models.Model):
    _inherit = "stock.quant"

    count_line_id = fields.Many2one(
        "stock.count.line",
        string="En recuento",
        index=True,
        copy=False,
        help="Línea del recuento activo que tiene tomado este quant.",
    )

    def _get_inventory_fields_write(self):
        return super()._get_inventory_fields_write() + ["count_line_id"]
