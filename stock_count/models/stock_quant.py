from odoo import fields, models
from odoo.exceptions import UserError


class StockQuant(models.Model):
    _inherit = "stock.quant"

    count_line_id = fields.Many2one(
        "stock.count.line",
        string="Línea de recuento",
        index=True,
        copy=False,
        help="Línea del recuento activo que tiene tomado este quant.",
    )
    count_id = fields.Many2one(related="count_line_id.count_id", string="En recuento", store=False)

    def _get_inventory_fields_write(self):
        return super()._get_inventory_fields_write() + ["count_line_id"]

    def _apply_inventory(self, *args, **kwargs):
        """Mientras un quant está tomado por un recuento, solo ese recuento lo ajusta.

        Cubre el botón Aplicar de Inventario físico, la aplicación automática y el
        borrado manual de quants (que también pasa por acá).
        """
        if not self.env.context.get("stock_count_line_id"):
            taken = self.filtered("count_line_id")
            if taken:
                detail = "\n".join(
                    f"- {quant.product_id.display_name} en {quant.location_id.complete_name}: "
                    f"{quant.count_line_id.count_id.name}"
                    for quant in taken[:10]
                )
                raise UserError(
                    self.env._(
                        "Estos quants están tomados por un recuento en curso; el ajuste se "
                        "aplica desde el recuento, no desde acá:\n%s",
                        detail,
                    )
                )
        return super()._apply_inventory(*args, **kwargs)

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
