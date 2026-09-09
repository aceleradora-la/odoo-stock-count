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

    def _get_inventory_move_values(
        self, qty, location_id, location_dest_id, package_id=False, package_dest_id=False
    ):
        """Enlaza el ajuste al recuento y redirige la pérdida al destino del motivo."""
        ctx = self.env.context
        loss_location_id = ctx.get("stock_count_loss_location_id")
        if loss_location_id and location_dest_id.usage == "inventory":
            location_dest_id = self.env["stock.location"].browse(loss_location_id)
        vals = super()._get_inventory_move_values(
            qty,
            location_id,
            location_dest_id,
            package_id=package_id,
            package_dest_id=package_dest_id,
        )
        if ctx.get("stock_count_id"):
            vals["count_id"] = ctx["stock_count_id"]
        if ctx.get("stock_count_line_id"):
            for command in vals.get("move_line_ids", []):
                if len(command) == 3 and isinstance(command[2], dict):
                    command[2]["count_line_id"] = ctx["stock_count_line_id"]
        return vals
