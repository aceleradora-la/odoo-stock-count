from odoo import api, fields, models


class StockCountAddProduct(models.TransientModel):
    """Producto encontrado en la estantería que no estaba en el recuento."""

    _name = "stock.count.add.product"
    _description = "Producto no esperado en recuento"

    count_id = fields.Many2one("stock.count", required=True, readonly=True)
    company_id = fields.Many2one(related="count_id.company_id")
    allowed_location_ids = fields.Many2many(
        "stock.location", compute="_compute_allowed_location_ids"
    )
    location_id = fields.Many2one(
        "stock.location",
        string="Ubicación",
        required=True,
        domain="[('id', 'in', allowed_location_ids)]",
    )
    product_id = fields.Many2one(
        "product.product",
        string="Producto",
        required=True,
        domain="[('type', '=', 'consu'), ('is_storable', '=', True)]",
    )
    tracking = fields.Selection(related="product_id.tracking")
    lot_id = fields.Many2one(
        "stock.lot",
        string="Lote",
        domain="[('product_id', '=', product_id)]",
    )
    qty_counted = fields.Float(string="Cantidad contada", digits="Product Unit of Measure")
    product_uom_id = fields.Many2one(related="product_id.uom_id")
    reason_id = fields.Many2one(
        "stock.count.reason",
        string="Motivo",
        default=lambda self: (
            (
                self.env.ref("stock_count.reason_unexpected", raise_if_not_found=False)
                or self.env["stock.count.reason"]
            ).id
        ),
    )
    note = fields.Char(string="Comentario")

    @api.depends("count_id")
    def _compute_allowed_location_ids(self):
        for wizard in self:
            wizard.allowed_location_ids = (
                wizard.count_id._get_count_locations() if wizard.count_id else False
            )

    def action_add(self):
        self.ensure_one()
        self.count_id._add_unexpected_line(
            self.product_id,
            self.location_id,
            self.lot_id,
            self.qty_counted,
            reason_id=self.reason_id.id,
            note=self.note,
        )
        return {"type": "ir.actions.act_window_close"}
