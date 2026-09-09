from odoo import api, fields, models
from odoo.exceptions import UserError


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
        count = self.count_id
        if count.state not in ("ready", "counting", "review"):
            raise UserError(self.env._("El recuento no está activo."))
        if self.location_id not in self.allowed_location_ids:
            raise UserError(self.env._("La ubicación no forma parte del recuento."))
        if self.tracking != "none" and not self.lot_id:
            raise UserError(self.env._("Este producto se controla por lote: indicá el lote."))
        if self.qty_counted < 0:
            raise UserError(self.env._("La cantidad no puede ser negativa."))

        existing = count.line_ids.filtered(
            lambda line: (
                line.product_id == self.product_id
                and line.location_id == self.location_id
                and line.lot_id == self.lot_id
            )
        )
        if existing:
            raise UserError(
                self.env._(
                    "%s ya está en el recuento en esa ubicación: cargá la cantidad en su línea.",
                    self.product_id.display_name,
                )
            )
        vals = count._prepare_zero_line_vals(self.product_id, self.location_id, self.lot_id)
        # Con sudo: el contador no ve las líneas de otros recuentos, pero el control de
        # exclusividad tiene que verlas todas.
        count.sudo()._check_no_overlapping_count([vals])

        quant = (
            self.env["stock.quant"]
            .sudo()
            ._gather(self.product_id, self.location_id, lot_id=self.lot_id, strict=True)[:1]
        )
        # Si el sistema sí tenía stock (producto fuera del alcance), el teórico es lo que
        # dice el quant: la diferencia se mide contra eso. Si no había quant, es cero.
        vals.update(
            {
                "quant_id": quant.id,
                "qty_theoretical": quant.quantity if quant else 0.0,
                "reason_id": self.reason_id.id,
                "note": self.note,
                "assigned_user_id": self.env.user.id
                if not self.env.user.has_group("stock_count.group_stock_count_manager")
                else False,
            }
        )
        line = self.env["stock.count.line"].sudo().create(vals)
        if quant:
            quant.count_line_id = line
        line.with_user(self.env.user).write({"qty_counted": self.qty_counted})
        count.sudo().message_post(
            subtype_xmlid="mail.mt_note",
            body=self.env._(
                "Producto no esperado agregado por %(user)s: %(product)s en %(location)s, "
                "%(qty)s %(uom)s.",
                user=self.env.user.name,
                product=self.product_id.display_name,
                location=self.location_id.complete_name,
                qty=self.qty_counted,
                uom=self.product_uom_id.name,
            ),
        )
        return {"type": "ir.actions.act_window_close"}
