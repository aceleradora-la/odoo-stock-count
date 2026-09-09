from odoo import api, fields, models

LINE_STATES = [
    ("pending", "Pendiente"),
    ("counted", "Contada"),
    ("recount", "Reconteo"),
    ("approved", "Aprobada"),
    ("applied", "Aplicada"),
    ("skipped", "Omitida"),
]


class StockCountLine(models.Model):
    """Una línea por quant del alcance del recuento.

    Guarda la cantidad teórica congelada al confirmar, el primer y el segundo
    conteo con autor y momento, el motivo de la diferencia y el ajuste generado.
    """

    _name = "stock.count.line"
    _description = "Línea de recuento"
    _order = "location_id, product_id, lot_id, id"
    _check_company_auto = True

    count_id = fields.Many2one(
        "stock.count", required=True, ondelete="cascade", index=True, readonly=True
    )
    company_id = fields.Many2one(related="count_id.company_id", store=True, index=True)
    count_state = fields.Selection(related="count_id.state", store=True)
    blind = fields.Boolean(related="count_id.blind")
    is_manager = fields.Boolean(compute="_compute_is_manager")

    product_id = fields.Many2one(
        "product.product",
        required=True,
        check_company=True,
        domain="[('type', '=', 'consu'), ('is_storable', '=', True)]",
    )
    product_uom_id = fields.Many2one(related="product_id.uom_id", string="UdM")
    location_id = fields.Many2one(
        "stock.location",
        required=True,
        check_company=True,
        domain="[('usage', '=', 'internal')]",
        index=True,
    )
    lot_id = fields.Many2one("stock.lot", string="Lote", check_company=True, index=True)
    package_id = fields.Many2one("stock.package", string="Paquete")
    owner_id = fields.Many2one("res.partner", string="Propietario")
    quant_id = fields.Many2one("stock.quant", string="Quant", readonly=True, copy=False)

    qty_theoretical = fields.Float(
        string="Teórico",
        digits="Product Unit of Measure",
        readonly=True,
        help="Cantidad del quant al confirmar el recuento. No se recalcula.",
    )
    qty_current = fields.Float(
        string="Actual",
        digits="Product Unit of Measure",
        compute="_compute_qty_current",
        help="Cantidad del quant ahora mismo. Si difiere del teórico, el stock se movió "
        "durante el recuento.",
    )
    qty_counted = fields.Float(string="1er conteo", digits="Product Unit of Measure")
    counted_by_id = fields.Many2one("res.users", string="Contó", readonly=True)
    counted_at = fields.Datetime(string="Contado el", readonly=True)
    qty_recount = fields.Float(string="2do conteo", digits="Product Unit of Measure")
    recounted_by_id = fields.Many2one("res.users", string="Recontó", readonly=True)
    recounted_at = fields.Datetime(string="Recontado el", readonly=True)
    qty_final = fields.Float(
        string="Contado final",
        digits="Product Unit of Measure",
        compute="_compute_qty_final",
        store=True,
    )
    qty_diff = fields.Float(
        string="Diferencia",
        digits="Product Unit of Measure",
        compute="_compute_diff",
        store=True,
    )
    diff_pct = fields.Float(string="Diferencia (%)", compute="_compute_diff", store=True)
    diff_value = fields.Monetary(
        string="Valor diferencia",
        compute="_compute_diff",
        store=True,
        currency_field="currency_id",
        help="Diferencia valorizada al costo del producto.",
    )
    currency_id = fields.Many2one(related="company_id.currency_id")

    assigned_user_id = fields.Many2one("res.users", string="Asignado a", index=True)
    state = fields.Selection(LINE_STATES, default="pending", required=True, index=True, copy=False)
    moved_during_count = fields.Boolean(
        string="Movido durante el conteo",
        readonly=True,
        copy=False,
        help="Se detectó un movimiento sobre este producto y ubicación mientras el "
        "recuento estaba activo.",
    )
    reason_id = fields.Many2one("stock.count.reason", string="Motivo")
    note = fields.Char(string="Comentario")
    move_line_ids = fields.One2many(
        "stock.move.line", "count_line_id", string="Ajuste generado", readonly=True
    )

    def _compute_is_manager(self):
        is_manager = self.env.user.has_group("stock_count.group_stock_count_manager")
        for line in self:
            line.is_manager = is_manager

    @api.depends("quant_id.quantity")
    def _compute_qty_current(self):
        for line in self:
            line.qty_current = line.quant_id.quantity if line.quant_id else 0.0

    @api.depends("qty_counted", "qty_recount", "recounted_at")
    def _compute_qty_final(self):
        for line in self:
            line.qty_final = line.qty_recount if line.recounted_at else line.qty_counted

    @api.depends("qty_final", "qty_theoretical", "state", "product_id.standard_price")
    def _compute_diff(self):
        for line in self:
            if line.state in ("pending", "skipped"):
                line.qty_diff = 0.0
                line.diff_pct = 0.0
                line.diff_value = 0.0
                continue
            diff = line.qty_final - line.qty_theoretical
            line.qty_diff = diff
            line.diff_pct = 100.0 * diff / line.qty_theoretical if line.qty_theoretical else 0.0
            line.diff_value = diff * line.product_id.with_company(line.company_id).standard_price
