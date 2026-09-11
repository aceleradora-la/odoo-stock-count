from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare

from .res_company import LOCK_MODES

STATES = [
    ("draft", "Borrador"),
    ("ready", "Confirmado"),
    ("counting", "En conteo"),
    ("review", "En revisión"),
    ("done", "Aplicado"),
    ("cancel", "Cancelado"),
]
ACTIVE_STATES = ("ready", "counting", "review")


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
        domain="[('usage', '=', 'internal'), ('warehouse_id', '=?', warehouse_id), "
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
        domain="[('type', '=', 'consu'), ('is_storable', '=', True)]",
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
            ("all_group_ids", "in", self.env.ref("stock_count.group_stock_count_manager").id)
        ],
    )
    counter_ids = fields.Many2many(
        "res.users",
        "stock_count_counter_rel",
        "count_id",
        "user_id",
        string="Contadores",
        domain=lambda self: [
            ("all_group_ids", "in", self.env.ref("stock_count.group_stock_count_user").id)
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
    pending_count = fields.Integer(compute="_compute_line_stats", store=True)
    diff_count = fields.Integer(compute="_compute_line_stats", store=True)
    diff_value = fields.Monetary(
        string="Valor de las diferencias",
        compute="_compute_line_stats",
        store=True,
        currency_field="currency_id",
    )
    accuracy = fields.Float(
        string="Precisión (%)", compute="_compute_line_stats", store=True, digits=(16, 2)
    )
    progress = fields.Float(string="Avance (%)", compute="_compute_line_stats", store=True)
    moved_count = fields.Integer(compute="_compute_line_stats", store=True)
    recount_count = fields.Integer(
        string="Por recontar", compute="_compute_line_stats", store=True
    )
    has_recount = fields.Boolean(
        compute="_compute_line_stats",
        store=True,
        help="Alguna línea pidió o tuvo un segundo conteo: se muestran las columnas del reconteo.",
    )
    move_count = fields.Integer(compute="_compute_move_count")
    currency_id = fields.Many2one(related="company_id.currency_id")
    is_manager = fields.Boolean(compute="_compute_is_manager")

    # ------------------------------------------------------------------
    # Defaults y cómputos
    # ------------------------------------------------------------------
    @api.onchange("warehouse_id")
    def _onchange_warehouse_id(self):
        """Al cambiar de depósito se descartan las ubicaciones que no le pertenecen."""
        if self.warehouse_id and self.location_ids:
            self.location_ids = self.location_ids.filtered(
                lambda location: location.warehouse_id == self.warehouse_id
            )

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
        "line_ids.moved_during_count",
        "line_ids.recounted_at",
    )
    def _compute_line_stats(self):
        for count in self:
            lines = count.line_ids
            # Una línea en reconteo ya tiene un primer conteo: cuenta como contada.
            counted = lines.filtered(lambda line: line.state != "pending")
            with_diff = counted.filtered(
                lambda line: line.state != "skipped" and not line._is_diff_zero()
            )
            count.line_count = len(lines)
            count.counted_count = len(counted)
            count.pending_count = len(lines) - len(counted)
            count.recount_count = len(lines.filtered(lambda line: line.state == "recount"))
            count.diff_count = len(with_diff)
            count.diff_value = sum(with_diff.mapped("diff_value"))
            count.progress = 100.0 * len(counted) / len(lines) if lines else 0.0
            count.moved_count = len(lines.filtered("moved_during_count"))
            count.has_recount = any(line.state == "recount" or line.recounted_at for line in lines)
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
    # Conteo ciego: los totales de diferencia tampoco se ven
    # ------------------------------------------------------------------
    def _read_format(self, fnames, load="_classic_read"):
        result = super()._read_format(fnames, load)
        blind_fields = ("diff_count", "diff_value", "accuracy")
        if (
            not self.env.su
            and any(name in blind_fields for name in fnames)
            and not self.env.user.has_group("stock_count.group_stock_count_manager")
        ):
            blind_ids = set(self.sudo().filtered("blind").ids)
            for vals in result:
                if vals.get("id") in blind_ids:
                    for name in blind_fields:
                        if name in vals:
                            vals[name] = 0
        return result

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
            raise UserError(
                self.env._("Solo se pueden eliminar recuentos en borrador o cancelados.")
            )
        return super().unlink()

    # ------------------------------------------------------------------
    # Selección de quants (alcance)
    # ------------------------------------------------------------------
    def _get_count_locations(self):
        self.ensure_one()
        if self.include_children:
            return self.env["stock.location"].search(
                [("id", "child_of", self.location_ids.ids), ("usage", "=", "internal")]
            )
        return self.location_ids

    def _get_scope_products(self):
        """Productos del alcance cuando está acotado; vacío significa 'todos'."""
        self.ensure_one()
        if self.scope == "products":
            return self.product_ids
        if self.scope == "category":
            return self.env["product.product"].search(
                [
                    ("categ_id", "child_of", self.categ_id.id),
                    ("type", "=", "consu"),
                    ("is_storable", "=", True),
                ]
            )
        if self.scope == "lots":
            return self.lot_ids.product_id
        return self.env["product.product"]

    def _get_quant_domain(self):
        self.ensure_one()
        domain = [
            ("location_id", "in", self._get_count_locations().ids),
            ("company_id", "=", self.company_id.id),
        ]
        if self.scope != "all":
            domain.append(("product_id", "in", self._get_scope_products().ids))
        if self.scope == "lots":
            domain.append(("lot_id", "in", self.lot_ids.ids))
        return domain

    def _get_quants(self):
        self.ensure_one()
        return self.env["stock.quant"].search(self._get_quant_domain())

    def _prepare_line_vals_from_quant(self, quant):
        self.ensure_one()
        return {
            "count_id": self.id,
            "quant_id": quant.id,
            "product_id": quant.product_id.id,
            "location_id": quant.location_id.id,
            "lot_id": quant.lot_id.id,
            "package_id": quant.package_id.id,
            "owner_id": quant.owner_id.id,
            "qty_theoretical": quant.quantity,
        }

    def _prepare_zero_line_vals(self, product, location, lot=None):
        self.ensure_one()
        return {
            "count_id": self.id,
            "product_id": product.id,
            "location_id": location.id,
            "lot_id": lot.id if lot else False,
            "qty_theoretical": 0.0,
        }

    def _prepare_line_vals_list(self):
        """Una línea por quant del alcance más, si corresponde, líneas en cero."""
        self.ensure_one()
        quants = self._get_quants()
        vals_list = [self._prepare_line_vals_from_quant(quant) for quant in quants]
        if self.include_zero_quants and self.scope != "all":
            existing = {(q.product_id.id, q.location_id.id, q.lot_id.id) for q in quants}
            locations = self._get_count_locations()
            if self.scope == "lots":
                keys = [(lot.product_id, lot) for lot in self.lot_ids]
            else:
                keys = [(product, None) for product in self._get_scope_products()]
            for product, lot in keys:
                for location in locations:
                    key = (product.id, location.id, lot.id if lot else False)
                    if key not in existing:
                        vals_list.append(self._prepare_zero_line_vals(product, location, lot))
        return vals_list

    # ------------------------------------------------------------------
    # Validaciones
    # ------------------------------------------------------------------
    def _check_no_overlapping_count(self, vals_list):
        """No puede haber dos recuentos activos sobre la misma clave producto/ubicación/lote."""
        self.ensure_one()
        if not vals_list:
            return
        candidates = self.env["stock.count.line"].search(
            [
                ("count_id", "!=", self.id),
                ("count_state", "in", ACTIVE_STATES),
                ("state", "not in", ("applied", "skipped")),
                ("product_id", "in", list({vals["product_id"] for vals in vals_list})),
                ("location_id", "in", list({vals["location_id"] for vals in vals_list})),
            ]
        )
        keys = {(v["product_id"], v["location_id"], v.get("lot_id") or False) for v in vals_list}
        blocking = candidates.filtered(
            lambda line: (line.product_id.id, line.location_id.id, line.lot_id.id or False) in keys
        )
        if not blocking:
            return
        sample = blocking[:5]
        detail = "\n".join(
            f"- {line.product_id.display_name} · {line.location_id.complete_name}"
            + (f" · {line.lot_id.name}" if line.lot_id else "")
            for line in sample
        )
        more = ""
        if len(blocking) > len(sample):
            more = self.env._("\n… y %s más", len(blocking) - len(sample))
        raise UserError(
            self.env._(
                "Ya hay un recuento activo sobre parte de este alcance: %(counts)s.\n"
                "Producto y ubicación en conflicto:\n%(detail)s%(more)s",
                counts=", ".join(blocking.count_id.mapped("name")),
                detail=detail,
                more=more,
            )
        )

    def _check_state(self, allowed, action):
        for count in self:
            if count.state not in allowed:
                raise UserError(
                    self.env._(
                        "No se puede %(action)s el recuento %(name)s en estado %(state)s.",
                        action=action,
                        name=count.name,
                        state=dict(STATES)[count.state],
                    )
                )

    # ------------------------------------------------------------------
    # Transiciones
    # ------------------------------------------------------------------
    def action_confirm(self):
        """Borrador → Confirmado: snapshot del teórico y toma de los quants."""
        self._check_state(("draft",), self.env._("confirmar"))
        for count in self:
            if not count.location_ids:
                raise UserError(self.env._("Elegí al menos una ubicación a contar."))
            if count.scope == "products" and not count.product_ids:
                raise UserError(self.env._("Elegí los productos a contar."))
            if count.scope == "category" and not count.categ_id:
                raise UserError(self.env._("Elegí la categoría a contar."))
            if count.scope == "lots" and not count.lot_ids:
                raise UserError(self.env._("Elegí los lotes a contar."))
            vals_list = count._prepare_line_vals_list()
            if not vals_list:
                raise UserError(
                    self.env._(
                        "No hay stock en las ubicaciones elegidas para el alcance definido. "
                        "Si querés confirmar que están vacías, activá 'Incluir stock en cero'."
                    )
                )
            count._check_no_overlapping_count(vals_list)
            count.line_ids.unlink()
            lines = self.env["stock.count.line"].create(vals_list)
            for line in lines.filtered("quant_id"):
                line.quant_id.sudo().count_line_id = line
            count.write({"state": "ready", "date_start": fields.Datetime.now()})
            count.message_post(
                subtype_xmlid="mail.mt_note",
                body=self.env._(
                    "Recuento confirmado. %(lines)s líneas generadas con la cantidad teórica "
                    "congelada. Bloqueo de movimientos: %(lock)s.",
                    lines=len(lines),
                    lock=dict(LOCK_MODES)[count.lock_mode],
                ),
            )
        return True

    def action_start(self):
        """Confirmado → En conteo."""
        self._check_state(("ready",), self.env._("iniciar"))
        self.write({"state": "counting"})
        return True

    def _line_needs_recount(self, line):
        self.ensure_one()
        if line.recounted_at or line._is_diff_zero():
            return False
        diff = abs(line.qty_diff)
        rounding = line._rounding()
        over_qty = self.recount_threshold_qty > 0 and (
            float_compare(diff, self.recount_threshold_qty, precision_rounding=rounding) > 0
        )
        over_pct = (
            self.recount_threshold_pct > 0
            and line.qty_theoretical
            and abs(line.diff_pct) > self.recount_threshold_pct
        )
        return bool(over_qty or over_pct)

    def _line_within_tolerance(self, line):
        """Tolerancia de aprobación automática. 100 % o más significa aprobar todo lo
        contado; con teórico cero no hay porcentaje, así que solo aprueba con 100 %."""
        self.ensure_one()
        if line._is_diff_zero():
            return True
        if self.auto_approve_tolerance_pct >= 100:
            return True
        if not line.qty_theoretical:
            return False
        return abs(line.diff_pct) <= self.auto_approve_tolerance_pct

    def action_to_review(self):
        """En conteo → En revisión: aprueba lo tolerable y manda a reconteo lo que se pasa.

        Se dispara sola al cargar la última línea; el botón queda para cuando se quiere
        pasar a revisión omitiendo lo que falta.
        """
        already = self.filtered(lambda count: count.state == "review")
        self._check_state(("counting", "review"), self.env._("enviar a revisión"))
        for count in self - already:
            pending = count.line_ids.filtered(lambda line: line.state in ("pending", "recount"))
            if pending:
                raise UserError(
                    self.env._(
                        "Faltan %s líneas por contar. Cargá la cantidad u omitilas antes de "
                        "enviar a revisión.",
                        len(pending),
                    )
                )
            approved = recount = self.env["stock.count.line"]
            for line in count.line_ids.filtered(lambda line: line.state == "counted"):
                if count._line_within_tolerance(line):
                    approved |= line
                elif count._line_needs_recount(line):
                    recount |= line
            approved.write({"state": "approved"})
            recount.write({"state": "recount"})
            count.write({"state": "review"})
            count.message_post(
                subtype_xmlid="mail.mt_note",
                body=self.env._(
                    "Enviado a revisión. %(approved)s líneas aprobadas automáticamente "
                    "(tolerancia %(tol)s %%). %(recount)s líneas superan el umbral de reconteo "
                    "(%(pct)s %% / %(qty)s unidades).",
                    approved=len(approved),
                    tol=count.auto_approve_tolerance_pct,
                    recount=len(recount),
                    pct=count.recount_threshold_pct,
                    qty=count.recount_threshold_qty,
                ),
            )
        return True

    def action_approve_all(self):
        """Aprueba todas las líneas contadas que no estén en reconteo."""
        self._check_state(("review",), self.env._("aprobar"))
        to_approve = self.line_ids.filtered(lambda line: line.state == "counted")
        if not to_approve:
            recount = len(self.line_ids.filtered(lambda line: line.state == "recount"))
            message = (
                self.env._(
                    "No hay líneas contadas sin aprobar. Hay %s líneas en reconteo: esperá el "
                    "segundo conteo o usá 'Aceptar 1er conteo'.",
                    recount,
                )
                if recount
                else self.env._("No hay líneas contadas sin aprobar.")
            )
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {"message": message, "type": "info"},
            }
        to_approve.action_approve()
        return True

    def action_accept_first_counts(self):
        """Da por bueno el primer conteo de todas las líneas en reconteo."""
        self._check_state(("review",), self.env._("aceptar"))
        for count in self:
            lines = count.line_ids.filtered(lambda line: line.state == "recount")
            if not lines:
                continue
            lines.action_accept_first_count()
            count.message_post(
                subtype_xmlid="mail.mt_note",
                body=self.env._(
                    "%(user)s aceptó el primer conteo de %(n)s líneas sin recontar.",
                    user=self.env.user.name,
                    n=len(lines),
                ),
            )
        return True

    def action_approve_within_tolerance(self):
        self._check_state(("review",), self.env._("aprobar"))
        for count in self:
            counted = count.line_ids.filtered(lambda line: line.state == "counted")
            to_approve = self.env["stock.count.line"]
            for line in counted:
                if count._line_within_tolerance(line):
                    to_approve |= line
            to_approve.action_approve()
        return True

    def _check_can_apply(self):
        labels = dict(self.env["stock.count.line"]._fields["state"].selection)
        for count in self:
            not_ready = count.line_ids.filtered(
                lambda line: line.state in ("pending", "recount", "counted")
            )
            if not_ready:
                by_state = {}
                for line in not_ready:
                    by_state[line.state] = by_state.get(line.state, 0) + 1
                raise UserError(
                    self.env._(
                        "No se puede aplicar: hay líneas sin resolver (%s). Aprobá, omití o "
                        "esperá los reconteos pendientes.",
                        ", ".join(f"{n} {labels[s].lower()}" for s, n in by_state.items()),
                    )
                )

    def _detect_moved_lines(self):
        """Marca las líneas cuyo quant ya no tiene la cantidad teórica congelada."""
        self.ensure_one()
        moved = self.line_ids.filtered(
            lambda line: line.state == "approved" and line._quant_moved_since_snapshot()
        )
        moved.write({"moved_during_count": True})
        return moved

    def action_apply(self):
        """En revisión → Aplicado: genera los ajustes con el motor nativo y libera el bloqueo."""
        self._check_state(("review",), self.env._("aplicar"))
        self._check_can_apply()
        force = self.env.context.get("stock_count_force_apply")
        for count in self:
            moved = count._detect_moved_lines()
            if moved and not force:
                # No se lanza excepción: la marca en las líneas debe persistir para que el
                # supervisor las vea y decida (reconteo o "Aplicar igualmente").
                detail = "\n".join(
                    f"- {line.product_id.display_name} · {line.location_id.complete_name}: "
                    f"teórico {line.qty_theoretical}, ahora {line.qty_current}"
                    for line in moved[:10]
                )
                message = self.env._(
                    "El stock de %(n)s líneas se movió después del snapshot:\n%(detail)s\n\n"
                    "Revisá esas líneas (podés pedir reconteo) o usá 'Aplicar igualmente' "
                    "para tomar la cantidad contada como cantidad final.",
                    n=len(moved),
                    detail=detail,
                )
                count.message_post(body=message, subtype_xmlid="mail.mt_note")
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": self.env._("Stock movido durante el conteo"),
                        "message": message,
                        "type": "warning",
                        "sticky": True,
                        "next": {"type": "ir.actions.act_window_close"},
                    },
                }
            to_apply = count.line_ids.filtered(lambda line: line.state == "approved")
            for line in to_apply:
                line._apply()
            count._release_quants()
            count.write({"state": "done", "date_end": fields.Datetime.now()})
            adjusted = to_apply.filtered("move_line_ids")
            count.message_post(
                subtype_xmlid="mail.mt_note",
                body=self.env._(
                    "Recuento aplicado. %(moves)s ajustes de inventario generados, "
                    "%(ok)s líneas sin diferencia. Bloqueo de movimientos liberado.",
                    moves=len(adjusted),
                    ok=len(to_apply) - len(adjusted),
                ),
            )
        return True

    def action_apply_force(self):
        return self.with_context(stock_count_force_apply=True).action_apply()

    def action_cancel(self):
        self._check_state(("draft",) + ACTIVE_STATES, self.env._("cancelar"))
        for count in self:
            count._release_quants()
        self.write({"state": "cancel"})
        return True

    def action_draft(self):
        """Vuelve a borrador (desde Confirmado o Cancelado) descartando las líneas."""
        self._check_state(("ready", "cancel"), self.env._("volver a borrador"))
        for count in self:
            count._release_quants()
            count.line_ids.unlink()
        self.write({"state": "draft", "date_start": False, "date_end": False})
        return True

    def _release_quants(self):
        self.ensure_one()
        self.line_ids.quant_id.filtered(
            lambda quant: quant.count_line_id.count_id == self
        ).sudo().write({"count_line_id": False})

    # ------------------------------------------------------------------
    # Acciones de vista
    # ------------------------------------------------------------------
    def action_view_moves(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("stock.stock_move_action")
        action["domain"] = [("count_id", "=", self.id)]
        action["context"] = {"create": False}
        return action

    # ------------------------------------------------------------------
    # Reportes
    # ------------------------------------------------------------------
    def _get_sheet_groups(self):
        """Líneas para la hoja de conteo, agrupadas por contador y ubicación.

        Nunca incluye el teórico: la hoja es para contar, no para comparar.
        """
        self.ensure_one()
        groups = []
        lines = self.line_ids.filtered(lambda line: line.state != "skipped").sorted(
            key=lambda line: (
                line.assigned_user_id.name or "",
                line.location_id.complete_name,
                line.product_id.display_name,
                line.lot_id.name or "",
            )
        )
        # Un grupo por contador y, al final, uno para las líneas sin asignar
        for user in [*lines.assigned_user_id, self.env["res.users"]]:
            user_lines = lines.filtered(lambda line, user=user: line.assigned_user_id == user)
            if not user_lines:
                continue
            locations = []
            for location in user_lines.location_id.sorted("complete_name"):
                locations.append(
                    {
                        "location": location,
                        "lines": user_lines.filtered(
                            lambda line, location=location: line.location_id == location
                        ),
                    }
                )
            groups.append({"user": user, "locations": locations})
        return groups

    def _get_diff_report_data(self):
        """Líneas con y sin diferencia para el informe, con totales."""
        self.ensure_one()
        lines = self.line_ids.filtered(lambda line: line.state not in ("pending", "skipped"))
        with_diff = lines.filtered(lambda line: not line._is_diff_zero()).sorted(
            key=lambda line: (abs(line.diff_value), abs(line.qty_diff)), reverse=True
        )
        without_diff = lines - with_diff
        return {
            "with_diff": with_diff,
            "without_diff": without_diff,
            "skipped": self.line_ids.filtered(lambda line: line.state == "skipped"),
            "total_value": sum(with_diff.mapped("diff_value")),
            "total_positive": sum(line.diff_value for line in with_diff if line.diff_value > 0),
            "total_negative": sum(line.diff_value for line in with_diff if line.diff_value < 0),
        }

    def action_export_xlsx(self):
        """Informe de diferencias en Excel, descargado como adjunto del recuento."""
        self.ensure_one()
        import base64
        import io

        import xlsxwriter

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        bold = workbook.add_format({"bold": True})
        header = workbook.add_format(
            {"bold": True, "bg_color": "#E9E4EA", "border": 1, "text_wrap": True}
        )
        number = workbook.add_format({"num_format": "#,##0.00"})
        money = workbook.add_format({"num_format": "#,##0.00"})
        pct = workbook.add_format({"num_format": "0.00"})
        negative = workbook.add_format({"num_format": "#,##0.00", "font_color": "#A02532"})
        positive = workbook.add_format({"num_format": "#,##0.00", "font_color": "#146C43"})

        sheet = workbook.add_worksheet("Diferencias")
        sheet.write(0, 0, self.env._("Recuento"), bold)
        sheet.write(0, 1, self.name)
        sheet.write(1, 0, self.env._("Supervisor"), bold)
        sheet.write(1, 1, self.user_id.name or "")
        sheet.write(2, 0, self.env._("Ubicaciones"), bold)
        sheet.write(2, 1, ", ".join(self.location_ids.mapped("complete_name")))
        sheet.write(3, 0, self.env._("Inicio"), bold)
        sheet.write(3, 1, str(self.date_start or ""))
        sheet.write(4, 0, self.env._("Cierre"), bold)
        sheet.write(4, 1, str(self.date_end or ""))
        sheet.write(5, 0, self.env._("Precisión (%)"), bold)
        sheet.write(5, 1, self.accuracy, pct)
        sheet.write(6, 0, self.env._("Valor de las diferencias"), bold)
        sheet.write(6, 1, self.diff_value, money)

        columns = [
            (self.env._("Ubicación"), 28),
            (self.env._("Código"), 14),
            (self.env._("Producto"), 36),
            (self.env._("Lote"), 14),
            (self.env._("UdM"), 10),
            (self.env._("Teórico"), 12),
            (self.env._("1er conteo"), 12),
            (self.env._("Contó"), 18),
            (self.env._("2do conteo"), 12),
            (self.env._("Recontó"), 18),
            (self.env._("Final"), 12),
            (self.env._("Diferencia"), 12),
            (self.env._("Dif. %"), 10),
            (self.env._("Valor"), 14),
            (self.env._("Motivo"), 18),
            (self.env._("Comentario"), 30),
            (self.env._("Movido durante el conteo"), 12),
            (self.env._("Estado"), 12),
        ]
        row = 8
        for col, (title, width) in enumerate(columns):
            sheet.write(row, col, title, header)
            sheet.set_column(col, col, width)
        states = dict(self.line_ids._fields["state"]._description_selection(self.env))
        data = self._get_diff_report_data()
        for line in data["with_diff"] + data["without_diff"] + data["skipped"]:
            row += 1
            diff_fmt = negative if line.qty_diff < 0 else positive if line.qty_diff > 0 else number
            values = [
                (line.location_id.complete_name, None),
                (line.product_id.default_code or "", None),
                (line.product_id.name, None),
                (line.lot_id.name or "", None),
                (line.product_uom_id.name, None),
                (line.qty_theoretical, number),
                (line.qty_counted, number),
                (line.counted_by_id.name or "", None),
                (line.qty_recount if line.recounted_at else "", number),
                (line.recounted_by_id.name or "", None),
                (line.qty_final, number),
                (line.qty_diff, diff_fmt),
                (line.diff_pct, pct),
                (line.diff_value, diff_fmt),
                (line.reason_id.name or "", None),
                (line.note or "", None),
                (self.env._("Sí") if line.moved_during_count else "", None),
                (states.get(line.state, line.state), None),
            ]
            for col, (value, fmt) in enumerate(values):
                if fmt is not None and value != "":
                    sheet.write_number(row, col, float(value), fmt)
                else:
                    sheet.write(row, col, value)
        row += 2
        sheet.write(row, 10, self.env._("Total"), bold)
        sheet.write_number(row, 11, sum(data["with_diff"].mapped("qty_diff")), number)
        sheet.write_number(row, 13, data["total_value"], money)
        sheet.freeze_panes(9, 0)
        workbook.close()

        attachment = self.env["ir.attachment"].create(
            {
                "name": f"{self.name.replace('/', '_')}_diferencias.xlsx",
                "type": "binary",
                "datas": base64.b64encode(output.getvalue()),
                "res_model": self._name,
                "res_id": self.id,
                "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            }
        )
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }
