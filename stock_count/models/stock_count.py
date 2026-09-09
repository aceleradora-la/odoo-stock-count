from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_is_zero

from .res_company import LOCK_MODES

STATES = [
    ("draft", "Borrador"),
    ("ready", "Confirmado"),
    ("counting", "En conteo"),
    ("review", "En revisión"),
    ("done", "Aplicado"),
    ("cancel", "Cancelado"),
]


class StockCount(models.Model):
    """Recuento de inventario.

    Documento que agrupa las líneas a contar sobre un conjunto de ubicaciones
    y productos, con la cantidad teórica congelada al confirmar, contadores
    asignados, revisión del supervisor y los ajustes de inventario generados.
    """

    _name = "stock.count"
    _description = "Recuento de inventario"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date_planned desc, id desc"
    _check_company_auto = True

    name = fields.Char(default="/", required=True, copy=False, readonly=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
        readonly=True,
    )
    warehouse_id = fields.Many2one(
        "stock.warehouse",
        string="Depósito",
        check_company=True,
        default=lambda self: self._default_warehouse_id(),
    )
    location_ids = fields.Many2many(
        "stock.location",
        "stock_count_location_rel",
        "count_id",
        "location_id",
        string="Ubicaciones",
        check_company=True,
        domain="[('usage', '=', 'internal'), "
        "'|', ('company_id', '=', company_id), ('company_id', '=', False)]",
    )
    include_children = fields.Boolean(string="Incluir sub-ubicaciones", default=True)
    scope = fields.Selection(
        [
            ("all", "Todos los productos en las ubicaciones"),
            ("products", "Productos seleccionados"),
            ("category", "Categoría de producto"),
            ("lots", "Lotes / números de serie"),
        ],
        string="Alcance",
        default="all",
        required=True,
    )
    product_ids = fields.Many2many(
        "product.product",
        "stock_count_product_rel",
        "count_id",
        "product_id",
        string="Productos",
        check_company=True,
        domain="[('type', '=', 'product')]",
    )
    categ_id = fields.Many2one("product.category", string="Categoría")
    lot_ids = fields.Many2many(
        "stock.lot",
        "stock_count_lot_rel",
        "count_id",
        "lot_id",
        string="Lotes",
        check_company=True,
    )
    include_zero_quants = fields.Boolean(
        string="Incluir stock en cero",
        help="Genera líneas para productos del alcance sin stock en la ubicación, "
        "para confirmar que efectivamente no hay nada.",
    )

    user_id = fields.Many2one(
        "res.users",
        string="Supervisor",
        default=lambda self: self.env.user,
        tracking=True,
        domain=lambda self: [
            ("groups_id", "in", self.env.ref("stock_count.group_stock_count_manager").id)
        ],
    )
    counter_ids = fields.Many2many(
        "res.users",
        "stock_count_counter_rel",
        "count_id",
        "user_id",
        string="Contadores",
        domain=lambda self: [
            ("groups_id", "in", self.env.ref("stock_count.group_stock_count_user").id)
        ],
    )
    date_planned = fields.Datetime(
        string="Fecha planificada", default=fields.Datetime.now, tracking=True
    )
    date_start = fields.Datetime(string="Inicio real", readonly=True, copy=False)
    date_end = fields.Datetime(string="Cierre real", readonly=True, copy=False)
    state = fields.Selection(
        STATES, default="draft", required=True, tracking=True, copy=False, index=True
    )

    lock_mode = fields.Selection(
        LOCK_MODES,
        string="Bloqueo de movimientos",
        required=True,
        default=lambda self: self.env.company.stock_count_lock_mode,
        help="Bloquear: no se pueden validar movimientos sobre el stock en recuento. "
        "Avisar: el movimiento pasa y la línea queda marcada. Sin control: nada.",
    )
    blind = fields.Boolean(
        related="company_id.stock_count_blind",
        string="Conteo ciego",
        help="Se configura en Inventario › Configuración, por compañía.",
    )
    recount_threshold_pct = fields.Float(
        string="Reconteo si la diferencia supera (%)",
        default=lambda self: self.env.company.stock_count_recount_threshold_pct,
        digits=(16, 2),
    )
    recount_threshold_qty = fields.Float(
        string="Reconteo si la diferencia supera (unidades)",
        default=lambda self: self.env.company.stock_count_recount_threshold_qty,
        digits="Product Unit of Measure",
    )
    auto_approve_tolerance_pct = fields.Float(
        string="Aprobar automáticamente hasta (%)",
        default=lambda self: self.env.company.stock_count_auto_approve_pct,
        digits=(16, 2),
    )

    line_ids = fields.One2many("stock.count.line", "count_id", string="Líneas", copy=False)
    move_ids = fields.One2many(
        "stock.move", "count_id", string="Ajustes generados", readonly=True, copy=False
    )
    origin = fields.Char(string="Origen", help="Referencia libre o regla que lo generó.")
    note = fields.Html(string="Notas")

    line_count = fields.Integer(compute="_compute_line_stats", store=True)
    counted_count = fields.Integer(compute="_compute_line_stats", store=True)
    diff_count = fields.Integer(compute="_compute_line_stats", store=True)
    diff_value = fields.Monetary(
        compute="_compute_line_stats", store=True, currency_field="currency_id"
    )
    accuracy = fields.Float(
        string="Precisión (%)", compute="_compute_line_stats", store=True, digits=(16, 2)
    )
    progress = fields.Float(string="Avance (%)", compute="_compute_line_stats", store=True)
    move_count = fields.Integer(compute="_compute_move_count")
    currency_id = fields.Many2one(related="company_id.currency_id")
    is_manager = fields.Boolean(compute="_compute_is_manager")

    # ------------------------------------------------------------------
    # Defaults y cómputos
    # ------------------------------------------------------------------
    @api.model
    def _default_warehouse_id(self):
        return self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1
        )

    @api.depends(
        "line_ids.state",
        "line_ids.qty_diff",
        "line_ids.diff_value",
        "line_ids.qty_final",
    )
    def _compute_line_stats(self):
        for count in self:
            lines = count.line_ids
            counted = lines.filtered(lambda line: line.state != "pending")
            with_diff = counted.filtered(
                lambda line: (
                    line.state != "skipped"
                    and not float_is_zero(
                        line.qty_diff, precision_rounding=line.product_uom_id.rounding or 0.01
                    )
                )
            )
            count.line_count = len(lines)
            count.counted_count = len(counted)
            count.diff_count = len(with_diff)
            count.diff_value = sum(with_diff.mapped("diff_value"))
            count.progress = 100.0 * len(counted) / len(lines) if lines else 0.0
            effective = counted.filtered(lambda line: line.state != "skipped")
            count.accuracy = (
                100.0 * (len(effective) - len(with_diff)) / len(effective) if effective else 0.0
            )

    def _compute_is_manager(self):
        is_manager = self.env.user.has_group("stock_count.group_stock_count_manager")
        for count in self:
            count.is_manager = is_manager

    @api.depends("move_ids")
    def _compute_move_count(self):
        for count in self:
            count.move_count = len(count.move_ids)

    # ------------------------------------------------------------------
    # ORM
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                company_id = vals.get("company_id") or self.env.company.id
                vals["name"] = (
                    self.env["ir.sequence"].with_company(company_id).next_by_code("stock.count")
                    or "/"
                )
        return super().create(vals_list)

    def unlink(self):
        if any(count.state not in ("draft", "cancel") for count in self):
            raise UserError(_("Solo se pueden eliminar recuentos en borrador o cancelados."))
        return super().unlink()

    # ------------------------------------------------------------------
    # Acciones de vista
    # ------------------------------------------------------------------
    def action_view_moves(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("stock.stock_move_action")
        action["domain"] = [("count_id", "=", self.id)]
        action["context"] = {"create": False}
        return action
