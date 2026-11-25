from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import float_compare, float_is_zero
from odoo.tools.misc import formatLang

from .res_company import LOCK_MODES

STATES = [
    ("draft", "Borrador"),
    ("ready", "Confirmado"),
    ("counting", "En conteo"),
    ("review", "En revisión"),
    ("done", "Validado"),
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
    picking_type_id = fields.Many2one(
        "stock.picking.type",
        string="Tipo de operación",
        compute="_compute_picking_type_id",
        store=True,
        index=True,
        help="Tipo de operación Recuento del depósito: agrupa los recuentos en el tablero "
        "de Inventario y etiqueta los ajustes que generan.",
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
        help="Agrega líneas en cero para los productos del alcance que no tienen stock "
        "en la ubicación y tuvieron movimientos ahí desde su último recuento, para "
        "confirmar que efectivamente no hay nada.",
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
    immediate_recount = fields.Boolean(
        string="Reconteo inmediato",
        default=lambda self: self.env.company.stock_count_immediate_recount,
        help="Si el primer conteo supera el umbral de reconteo, se pide el segundo conteo "
        "en el momento, sin esperar a la revisión.",
    )
    recount_min_value = fields.Float(
        string="No recontar si el valor es menor a",
        default=lambda self: self.env.company.stock_count_recount_min_value,
        digits="Product Price",
        help="Materialidad: una diferencia cuyo valor a costo es menor a este monto no "
        "exige segundo conteo aunque supere los umbrales; queda para que la apruebe el "
        "supervisor. 0 = sin mínimo.",
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
        string="Precisión (%)",
        compute="_compute_line_stats",
        store=True,
        digits=(16, 2),
        help="Líneas contadas sin diferencia o con una diferencia dentro de 'Aprobar "
        "automáticamente hasta (%)', sobre el total de líneas contadas.",
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
        "auto_approve_tolerance_pct",
    )
    def _compute_line_stats(self):
        for count in self:
            # Una sola pasada: se recalcula con cada cantidad cargada.
            # Una línea en reconteo ya tiene un primer conteo: cuenta como contada.
            total = counted = recount = effective = with_diff = moved = inexact = 0
            diff_value = 0.0
            has_recount = False
            for line in count.line_ids:
                total += 1
                state = line.state
                if line.moved_during_count:
                    moved += 1
                if state == "recount":
                    recount += 1
                if state == "recount" or line.recounted_at:
                    has_recount = True
                if state == "pending":
                    continue
                counted += 1
                if state == "skipped":
                    continue
                effective += 1
                if not line._is_diff_zero():
                    with_diff += 1
                    diff_value += line.diff_value
                    if not count._line_is_accurate(line):
                        inexact += 1
            count.line_count = total
            count.counted_count = counted
            count.pending_count = total - counted
            count.recount_count = recount
            count.diff_count = with_diff
            count.diff_value = diff_value
            count.progress = 100.0 * counted / total if total else 0.0
            count.moved_count = moved
            count.has_recount = has_recount
            count.accuracy = 100.0 * (effective - inexact) / effective if effective else 0.0

    @api.depends("warehouse_id.count_type_id")
    def _compute_picking_type_id(self):
        for count in self:
            count.picking_type_id = count.warehouse_id.count_type_id

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

    def _zero_last_moves(self, locations):
        """Último movimiento hecho de cada (producto, ubicación, lote) del alcance.

        Los ajustes que generan los recuentos no cuentan como movimiento. Los productos
        con número de serie quedan afuera: una serie que salió no se confirma en cero."""
        self.ensure_one()
        domain = [
            ("state", "=", "done"),
            ("company_id", "=", self.company_id.id),
            ("move_id.count_id", "=", False),
            ("product_id.is_storable", "=", True),
            ("product_id.tracking", "!=", "serial"),
        ]
        if self.scope != "all":
            domain.append(("product_id", "in", self._get_scope_products().ids))
        if self.scope == "lots":
            domain.append(("lot_id", "in", self.lot_ids.ids))
        MoveLine = self.env["stock.move.line"].sudo()
        last_moves = {}
        for field in ("location_id", "location_dest_id"):
            groups = MoveLine._read_group(
                domain + [(field, "in", locations.ids)],
                ["product_id", field, "lot_id"],
                ["date:max"],
            )
            for product, location, lot, date in groups:
                tracked = product.tracking == "lot"
                if tracked and not lot:
                    continue
                key = (product.id, location.id, lot.id if tracked else False)
                if not last_moves.get(key) or date > last_moves[key]:
                    last_moves[key] = date
        return last_moves

    def _zero_last_counts(self, locations, product_ids):
        """Cierre del último recuento validado de cada (producto, ubicación, lote), y de
        cada ubicación contada entera (alcance 'todos los productos')."""
        self.ensure_one()
        by_key = {}
        groups = (
            self.env["stock.count.line"]
            .sudo()
            ._read_group(
                [
                    ("state", "=", "applied"),
                    ("location_id", "in", locations.ids),
                    ("product_id", "in", list(product_ids)),
                ],
                ["product_id", "location_id", "lot_id"],
                ["count_id:recordset"],
            )
        )
        for product, location, lot, counts in groups:
            dates = [date for date in counts.mapped("date_end") if date]
            if dates:
                by_key[(product.id, location.id, lot.id)] = max(dates)
        by_location = {}
        pending = set(locations.ids)
        full_counts = self.sudo().search(
            [
                ("state", "=", "done"),
                ("scope", "=", "all"),
                ("company_id", "=", self.company_id.id),
                ("date_end", "!=", False),
            ],
            order="date_end desc",
        )
        for count in full_counts:
            if not pending:
                break
            for location_id in pending & set(count._get_count_locations().ids):
                by_location[location_id] = count.date_end
                pending.discard(location_id)
        return by_key, by_location

    def _prepare_zero_lines_vals_list(self, quants):
        """Líneas en cero: lo que no tiene stock en la ubicación y se movió ahí desde su
        último recuento. Lo que nunca se contó entra con cualquier movimiento."""
        self.ensure_one()
        existing = {(q.product_id.id, q.location_id.id, q.lot_id.id) for q in quants}
        stocked = {(q.product_id.id, q.location_id.id) for q in quants}
        locations = self._get_count_locations()
        last_moves = {
            key: date
            for key, date in self._zero_last_moves(locations).items()
            if key not in existing and (key[2] or key[:2] not in stocked)
        }
        if not last_moves:
            return []
        by_key, by_location = self._zero_last_counts(locations, {key[0] for key in last_moves})
        vals_list = []
        for key in sorted(last_moves):
            product_id, location_id, lot_id = key
            counted = [date for date in (by_key.get(key), by_location.get(location_id)) if date]
            if counted and last_moves[key] <= max(counted):
                continue
            vals_list.append(
                {
                    "count_id": self.id,
                    "product_id": product_id,
                    "location_id": location_id,
                    "lot_id": lot_id,
                    "qty_theoretical": 0.0,
                }
            )
        return vals_list

    def _prepare_line_vals_list(self):
        """Una línea por quant con stock del alcance más, si corresponde, líneas en cero.

        Odoo conserva los quants que quedaron en cero hasta que se limpian (al abrir el
        informe de existencias): no generan línea por sí solos, valen como 'en cero'."""
        self.ensure_one()
        quants = self._get_quants().filtered(
            lambda quant: (
                not float_is_zero(
                    quant.quantity, precision_rounding=quant.product_uom_id.rounding or 0.01
                )
            )
        )
        vals_list = [self._prepare_line_vals_from_quant(quant) for quant in quants]
        if self.include_zero_quants:
            vals_list += self._prepare_zero_lines_vals_list(quants)
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
        """Borrador → Confirmado: genera las líneas para repartirlas e imprimir la hoja.
        El teórico definitivo y el bloqueo de movimientos llegan al iniciar el conteo."""
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
                        "No hay nada para contar en las ubicaciones elegidas con el alcance "
                        "definido. 'Incluir stock en cero' agrega lo que quedó en cero y se "
                        "movió desde su último recuento."
                    )
                )
            count._check_no_overlapping_count(vals_list)
            count.line_ids.unlink()
            lines = self.env["stock.count.line"].create(vals_list)
            count.write({"state": "ready"})
            count.message_post(
                subtype_xmlid="mail.mt_note",
                body=self.env._(
                    "Recuento confirmado. %(lines)s líneas generadas. El teórico se actualiza "
                    "y el bloqueo de movimientos empieza al iniciar el conteo.",
                    lines=len(lines),
                ),
            )
        return True

    def action_start(self):
        """Confirmado → En conteo: toma el teórico de este momento y empieza el bloqueo."""
        self._check_state(("ready",), self.env._("iniciar"))
        for count in self:
            updated, added, removed = count._refresh_snapshot()
            count.write({"state": "counting", "date_start": fields.Datetime.now()})
            count.message_post(
                subtype_xmlid="mail.mt_note",
                body=self.env._(
                    "Conteo iniciado con el teórico de este momento. Desde la confirmación: "
                    "%(updated)s líneas actualizadas, %(added)s agregadas y %(removed)s "
                    "quitadas. Bloqueo de movimientos: %(lock)s.",
                    updated=updated,
                    added=added,
                    removed=removed,
                    lock=dict(LOCK_MODES)[count.lock_mode],
                ),
            )
        return True

    def _refresh_snapshot(self):
        """Pone las líneas al día con el stock de este momento y toma los quants.

        Entre la confirmación y el inicio el stock se sigue moviendo. Al iniciar, cada
        línea toma la cantidad del sistema de ese momento, el stock nuevo del alcance
        agrega líneas y las líneas pendientes cuyo stock ya no está se quitan. Devuelve
        cuántas líneas se actualizaron, agregaron y quitaron."""
        self.ensure_one()
        Line = self.env["stock.count.line"].sudo()
        keep = set(self.env.context.get("stock_count_keep_line_ids") or [])
        vals_list = self._prepare_line_vals_list()
        self.sudo()._check_no_overlapping_count(vals_list)
        existing = {}
        for line in Line.search([("count_id", "=", self.id)]):
            key = (
                line.product_id.id,
                line.location_id.id,
                line.lot_id.id,
                line.package_id.id,
                line.owner_id.id,
            )
            existing.setdefault(key, line)
        updated = 0
        seen = Line
        to_create = []
        for vals in vals_list:
            key = (
                vals["product_id"],
                vals["location_id"],
                vals.get("lot_id") or False,
                vals.get("package_id") or False,
                vals.get("owner_id") or False,
            )
            line = existing.get(key)
            if not line:
                to_create.append(vals)
                continue
            seen |= line
            updated += line._set_snapshot(vals.get("quant_id") or False, vals["qty_theoretical"])
        to_unlink = Line
        for line in Line.union(*existing.values()) - seen:
            if line.state == "pending" and line.id not in keep:
                to_unlink |= line
                continue
            # Ya contada (producto no esperado, o la línea que se está cargando): se
            # queda, con lo que el sistema tenga ahora para esa clave.
            quant = (
                self.env["stock.quant"]
                .sudo()
                ._gather(
                    line.product_id,
                    line.location_id,
                    lot_id=line.lot_id,
                    package_id=line.package_id,
                    owner_id=line.owner_id,
                    strict=True,
                )[:1]
            )
            updated += line._set_snapshot(quant.id, quant.quantity if quant else 0.0)
        removed = len(to_unlink)
        to_unlink.unlink()
        new_lines = Line.create(to_create)
        lines = Line.search([("count_id", "=", self.id)])
        # Una línea nueva en una ubicación que ya tiene un único contador es de él.
        for line in new_lines:
            siblings = (lines - new_lines).filtered(
                lambda other, line=line: other.location_id == line.location_id
            )
            users = siblings.assigned_user_id
            if len(users) == 1 and all(sibling.assigned_user_id for sibling in siblings):
                line.assigned_user_id = users
        for line in lines.filtered("quant_id"):
            line.quant_id.sudo().count_line_id = line
        return updated, len(new_lines), removed

    # ------------------------------------------------------------------
    # Avisos: quién tiene que actuar
    # ------------------------------------------------------------------
    def _sync_review_activities(self):
        """Deja una actividad a quien tiene que actuar y cierra las que ya no aplican.

        - Al supervisor del recuento, mientras haya líneas contadas para aprobar.
        - A cada contador, mientras tenga líneas para recontar en un recuento en revisión.
        """
        review_type = "stock_count.mail_activity_count_review"
        recount_type = "stock_count.mail_activity_count_recount"
        review = self.env.ref(review_type, raise_if_not_found=False)
        recount = self.env.ref(recount_type, raise_if_not_found=False)
        if not review or not recount:
            return
        for count in self.sudo():
            activities = count.activity_ids
            in_review = count.state == "review"
            to_approve = count.line_ids.filtered(lambda line: line.state == "counted")
            in_recount = count.line_ids.filtered(lambda line: line.state == "recount")
            # --- supervisor
            mine = activities.filtered(lambda act: act.activity_type_id == review)
            own = to_approve.with_user(count.user_id)._self_counted() if count.user_id else []
            open_recount = activities.filtered(lambda act: act.activity_type_id == recount)
            recount_users = open_recount.user_id
            if in_review and to_approve and count.user_id:
                if not mine:
                    count.activity_schedule(
                        review_type,
                        user_id=count.user_id.id,
                        note=self.env._(
                            "%(name)s tiene %(approve)s líneas para aprobar y %(recount)s "
                            "en reconteo.",
                            name=count.name,
                            approve=len(to_approve),
                            recount=len(in_recount),
                        )
                        + (
                            " "
                            + self.env._(
                                "%s las contaste vos: las tiene que aprobar otro supervisor.",
                                len(own),
                            )
                            if own
                            else ""
                        ),
                    )
            elif mine:
                if count.state in ("review", "done"):
                    count.activity_feedback([review_type])
                else:
                    count.activity_unlink([review_type])
            # --- contadores con reconteos
            users = self.env["res.users"]
            if in_review:
                for line in in_recount:
                    users |= line.assigned_user_id or line.counted_by_id
            for user in users - recount_users:
                if not count.with_user(user).has_access("read"):
                    continue
                lines = in_recount.filtered(
                    lambda line, user=user: (line.assigned_user_id or line.counted_by_id) == user
                )
                count.activity_schedule(
                    recount_type,
                    user_id=user.id,
                    note=self.env._(
                        "%(name)s: %(n)s líneas para contar de nuevo. Abrí la app Recuentos.",
                        name=count.name,
                        n=len(lines),
                    ),
                )
            for user in recount_users - users:
                if count.state in ("review", "done"):
                    count.activity_feedback([recount_type], user_id=user.id)
                else:
                    count.activity_unlink([recount_type], user_id=user.id)

    def _auto_review(self):
        """Sin líneas pendientes ni en reconteo, el recuento en conteo pasa solo a
        revisión."""
        Line = self.env["stock.count.line"].sudo()
        for count in self.filtered(lambda count: count.state == "counting"):
            left = Line.search_count(
                [("count_id", "=", count.id), ("state", "in", ("pending", "recount"))],
                limit=1,
            )
            if not left:
                count.sudo().action_to_review()

    def _line_needs_recount(self, line):
        self.ensure_one()
        if line.recounted_at or line._is_diff_zero():
            return False
        params = self._line_params(line)
        diff = abs(line.qty_diff)
        rounding = line._rounding()
        over_qty = params["recount_threshold_qty"] > 0 and (
            float_compare(diff, params["recount_threshold_qty"], precision_rounding=rounding) > 0
        )
        over_pct = (
            params["recount_threshold_pct"] > 0
            and line.qty_theoretical
            and abs(line.diff_pct) > params["recount_threshold_pct"]
        )
        if params["recount_min_value"] > 0 and abs(line.diff_value) < params["recount_min_value"]:
            return False
        return bool(over_qty or over_pct)

    def _line_is_accurate(self, line):
        """Para la precisión: sin diferencia o dentro de la tolerancia de aprobación."""
        self.ensure_one()
        if line._is_diff_zero():
            return True
        if not line.qty_theoretical:
            return False
        return abs(line.diff_pct) <= self._line_params(line)["auto_approve_tolerance_pct"]

    def _line_params(self, line):
        """Umbrales que rigen una línea: los del producto si tiene propios; si no, los de
        su categoría (o la primera categoría superior que los tenga); si no, los del
        recuento."""
        self.ensure_one()
        source = line.product_id.sudo()._stock_count_params_source()
        if source:
            return {
                "recount_threshold_pct": source.stock_count_recount_threshold_pct,
                "recount_threshold_qty": source.stock_count_recount_threshold_qty,
                "auto_approve_tolerance_pct": source.stock_count_auto_approve_pct,
                "recount_min_value": source.stock_count_recount_min_value,
            }
        return {
            "recount_threshold_pct": self.recount_threshold_pct,
            "recount_threshold_qty": self.recount_threshold_qty,
            "auto_approve_tolerance_pct": self.auto_approve_tolerance_pct,
            "recount_min_value": self.recount_min_value,
        }

    def _line_within_tolerance(self, line):
        """Tolerancia de aprobación automática. 100 % o más significa aprobar todo lo
        contado; con teórico cero no hay porcentaje, así que solo aprueba con 100 %."""
        self.ensure_one()
        if line._is_diff_zero():
            return True
        if line.zero_filled:
            return False
        tolerance = self._line_params(line)["auto_approve_tolerance_pct"]
        if tolerance >= 100:
            return True
        if not line.qty_theoretical:
            return False
        return abs(line.diff_pct) <= tolerance

    def action_to_review(self):
        """En conteo → En revisión: aprueba lo tolerable y manda a reconteo lo que se pasa.

        Se dispara sola al cargar la última línea; el botón queda para cuando se quiere
        pasar a revisión omitiendo lo que falta.
        """
        already = self.filtered(lambda count: count.state in ("review", "done"))
        self._check_state(("counting", "review", "done"), self.env._("enviar a revisión"))
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
        (self - already)._try_auto_validate()
        (self - already)._sync_review_activities()
        return True

    def _own_lines_notification(self, done, own):
        """Aviso de una acción en bloque que dejó afuera lo que contó el propio usuario."""
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "message": self.env._(
                    "%(done)s líneas resueltas. Quedan %(own)s que contaste vos: las tiene "
                    "que resolver otro supervisor.",
                    done=done,
                    own=own,
                ),
                "type": "warning",
                "sticky": True,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def action_approve_all(self):
        """Aprueba todas las líneas contadas que no estén en reconteo."""
        self._check_state(("review", "done"), self.env._("aprobar"))
        if all(count.state == "done" for count in self):
            return True
        counted = self.line_ids.filtered(lambda line: line.state == "counted")
        own = counted._self_counted()
        to_approve = counted - own
        if not to_approve and own:
            return self._own_lines_notification(0, len(own))
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
        self._try_auto_validate()
        if own:
            return self._own_lines_notification(len(to_approve), len(own))
        return True

    def action_accept_first_counts(self):
        """Da por bueno el primer conteo de todas las líneas en reconteo."""
        self._check_state(("review", "done"), self.env._("aceptar"))
        skipped = accepted = 0
        for count in self:
            lines = count.line_ids.filtered(lambda line: line.state == "recount")
            own = lines._self_counted(first_count=True)
            skipped += len(own)
            lines -= own
            if not lines:
                continue
            accepted += len(lines)
            lines.action_accept_first_count()
            count.message_post(
                subtype_xmlid="mail.mt_note",
                body=self.env._(
                    "%(user)s aceptó el primer conteo de %(n)s líneas sin recontar.",
                    user=self.env.user.name,
                    n=len(lines),
                ),
            )
        self._try_auto_validate()
        if skipped:
            return self._own_lines_notification(accepted, skipped)
        return True

    def action_approve_within_tolerance(self):
        self._check_state(("review", "done"), self.env._("aprobar"))
        for count in self:
            counted = count.line_ids.filtered(lambda line: line.state == "counted")
            to_approve = self.env["stock.count.line"]
            for line in counted - counted._self_counted():
                if count._line_within_tolerance(line):
                    to_approve |= line
            to_approve.action_approve()
        self._try_auto_validate()
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
                        "No se puede validar: hay líneas sin resolver (%s). Aprobá, omití o "
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

    def _try_auto_validate(self):
        """Con todas las líneas aprobadas u omitidas, el recuento se valida solo.

        Si hay stock movido desde el snapshot, action_apply marca las líneas y deja la
        decisión al supervisor ('Validar igualmente').
        """
        for count in self.filtered(lambda count: count.state == "review"):
            unresolved = count.line_ids.filtered(
                lambda line: line.state in ("pending", "recount", "counted")
            )
            if unresolved or not count.line_ids:
                continue
            count.sudo().action_apply()
        return True

    def action_apply(self):
        """En revisión → Validado: genera los ajustes con el motor nativo y libera el bloqueo."""
        if all(count.state == "done" for count in self):
            return True  # ya validado (por ejemplo, solo al aprobar la última línea)
        self._check_state(("review",), self.env._("validar"))
        self._check_can_apply()
        force = self.env.context.get("stock_count_force_apply")
        for count in self:
            moved = count._detect_moved_lines()
            if moved and not force:
                # No se lanza excepción: la marca en las líneas debe persistir para que el
                # supervisor las vea y decida (reconteo o "Validar igualmente").
                detail = "\n".join(
                    f"- {line.product_id.display_name} · {line.location_id.complete_name}: "
                    f"teórico {line.qty_theoretical}, ahora {line.qty_current}"
                    for line in moved[:10]
                )
                message = self.env._(
                    "El stock de %(n)s líneas se movió después del snapshot:\n%(detail)s\n\n"
                    "Revisá esas líneas (podés pedir reconteo) o usá 'Validar igualmente' "
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
            to_apply._apply()
            count._release_quants()
            count.write({"state": "done", "date_end": fields.Datetime.now()})
            adjusted = to_apply.filtered("move_line_ids")
            count.message_post(
                subtype_xmlid="mail.mt_note",
                body=self.env._(
                    "Recuento validado. %(moves)s ajustes de inventario generados, "
                    "%(ok)s líneas sin diferencia. Bloqueo de movimientos liberado.",
                    moves=len(adjusted),
                    ok=len(to_apply) - len(adjusted),
                ),
            )
            count._sync_review_activities()
        return True

    def action_apply_force(self):
        return self.with_context(stock_count_force_apply=True).action_apply()

    def action_cancel(self):
        self._check_state(("draft",) + ACTIVE_STATES, self.env._("cancelar"))
        for count in self:
            count._release_quants()
        self.write({"state": "cancel"})
        self._sync_review_activities()
        return True

    def action_draft(self):
        """Vuelve a borrador (desde Confirmado o Cancelado) descartando las líneas."""
        self._check_state(("ready", "cancel"), self.env._("volver a borrador"))
        for count in self:
            count._release_quants()
            count.line_ids.unlink()
        self.write({"state": "draft", "date_start": False, "date_end": False})
        self._sync_review_activities()
        return True

    def _add_unexpected_line(self, product, location, lot=None, quantity=0.0, **extra):
        """Agrega al recuento un producto que no estaba previsto en esa ubicación y lo
        deja contado por el usuario actual. Lo usan el asistente y la app."""
        self.ensure_one()
        lot = lot or self.env["stock.lot"]
        if self.state not in ACTIVE_STATES:
            raise UserError(self.env._("El recuento no está activo."))
        if location not in self._get_count_locations():
            raise UserError(self.env._("La ubicación no forma parte del recuento."))
        if product.sudo().tracking != "none" and not lot:
            raise UserError(self.env._("Este producto se controla por lote: indicá el lote."))
        if quantity < 0:
            raise UserError(self.env._("La cantidad no puede ser negativa."))
        Line = self.env["stock.count.line"].sudo()
        existing = Line.search_count(
            [
                ("count_id", "=", self.id),
                ("product_id", "=", product.id),
                ("location_id", "=", location.id),
                ("lot_id", "=", lot.id),
            ],
            limit=1,
        )
        if existing:
            raise UserError(
                self.env._(
                    "%s ya está en el recuento en esa ubicación: cargá la cantidad en su línea.",
                    product.sudo().display_name,
                )
            )
        vals = self._prepare_zero_line_vals(product, location, lot)
        # Con sudo: el contador no ve las líneas de otros recuentos, pero el control de
        # exclusividad tiene que verlas todas.
        self.sudo()._check_no_overlapping_count([vals])
        quant = (
            self.env["stock.quant"].sudo()._gather(product, location, lot_id=lot, strict=True)[:1]
        )
        is_manager = self.env.user.has_group("stock_count.group_stock_count_manager")
        reason = self.env.ref("stock_count.reason_unexpected", raise_if_not_found=False)
        # Si el sistema sí tenía stock (producto fuera del alcance), el teórico es lo que
        # dice el quant: la diferencia se mide contra eso. Si no había quant, es cero.
        vals.update(
            {
                "quant_id": quant.id,
                "qty_theoretical": quant.quantity if quant else 0.0,
                "reason_id": reason.id if reason else False,
                "assigned_user_id": False if is_manager else self.env.user.id,
            }
        )
        vals.update(extra)
        line = Line.create(vals)
        if quant:
            quant.count_line_id = line
        line.with_user(self.env.user).write({"qty_counted": quantity})
        self.sudo().message_post(
            subtype_xmlid="mail.mt_note",
            body=self.env._(
                "Producto no esperado agregado por %(user)s: %(product)s en %(location)s, "
                "%(qty)s %(uom)s.",
                user=self.env.user.name,
                product=product.sudo().display_name,
                location=location.sudo().complete_name,
                qty=quantity,
                uom=product.sudo().uom_id.name,
            ),
        )
        return line

    # ------------------------------------------------------------------
    # Tablero del supervisor (app)
    # ------------------------------------------------------------------
    def _check_supervisor(self):
        if not self.env.user.has_group("stock_count.group_stock_count_manager"):
            raise AccessError(self.env._("Solo un supervisor de recuentos puede ver el tablero."))

    def _supervisor_line_data(self, line):
        money = formatLang(self.env, line.diff_value, currency_obj=self.currency_id)
        return {
            "id": line.id,
            "product": line.product_id.display_name,
            "location": line.location_id.complete_name,
            "lot": line.lot_id.name or "",
            "uom": line.product_uom_id.name,
            "theoretical": line.qty_theoretical,
            "counted": line.qty_final,
            "first_count": line.qty_counted,
            "has_recount": bool(line.recounted_at),
            "diff": line.qty_diff,
            "diff_pct": line.diff_pct if line.qty_theoretical else False,
            "value": line.diff_value,
            "value_label": money,
            "state": line.state,
            "counted_by": (line.recounted_by_id or line.counted_by_id).name or "",
            "breakdown": line.counted_breakdown or "",
            "theoretical_breakdown": line.theoretical_breakdown or "",
            "zero_filled": line.zero_filled,
            "moved": line.moved_during_count,
            # La contó quien mira el tablero y la compañía no deja aprobar lo propio
            "own": bool(line._self_counted(first_count=line.state == "recount")),
        }

    def _supervisor_count_data(self):
        self.ensure_one()
        lines = self.line_ids
        counters = {}
        for line in lines:
            user = line.assigned_user_id or line.counted_by_id
            entry = counters.setdefault(
                user.id, {"name": user.name or self.env._("Sin asignar"), "total": 0, "done": 0}
            )
            entry["total"] += 1
            if line.state != "pending":
                entry["done"] += 1
        to_approve = lines.filtered(
            lambda line: line.state == "counted" and self.state == "review"
        )
        in_recount = lines.filtered(lambda line: line.state == "recount")
        review = (to_approve | in_recount).sorted(
            key=lambda line: (line.state != "counted", -abs(line.diff_value), line.id)
        )
        unresolved = lines.filtered(lambda line: line.state in ("pending", "recount", "counted"))
        return {
            "id": self.id,
            "name": self.name,
            "state": self.state,
            "state_label": dict(STATES)[self.state],
            "locations": ", ".join(self.location_ids.mapped("display_name")),
            "supervisor": self.user_id.name or "",
            "progress": round(self.progress),
            "line_count": self.line_count,
            "counted_count": self.counted_count,
            "pending_count": self.pending_count,
            "recount_count": self.recount_count,
            "approve_count": len(to_approve),
            "diff_count": self.diff_count,
            "diff_value_label": formatLang(
                self.env, self.diff_value, currency_obj=self.currency_id
            ),
            "moved_count": self.moved_count,
            "can_validate": self.state == "review" and not unresolved and bool(lines),
            "counters": sorted(counters.values(), key=lambda entry: entry["name"]),
            "lines": [self._supervisor_line_data(line) for line in review[:200]],
            "more_lines": max(len(review) - 200, 0),
        }

    @api.model
    def supervisor_get_data(self):
        """Recuentos activos con avance por contador y líneas para resolver."""
        self._check_supervisor()
        counts = self.search([("state", "in", ACTIVE_STATES)], order="date_planned desc, id desc")
        return {"counts": [count._supervisor_count_data() for count in counts]}

    @api.model
    def supervisor_action(self, count_id, action, line_ids=None):
        """Una acción del supervisor desde el celular. Devuelve el tablero actualizado."""
        self._check_supervisor()
        count = self.browse(count_id).exists()
        if not count:
            raise UserError(self.env._("El recuento ya no existe."))
        lines = self.env["stock.count.line"].browse(line_ids or []).exists()
        if lines - count.line_ids:
            raise UserError(self.env._("Hay líneas que no son de este recuento."))
        message = False
        if action == "approve":
            lines.action_approve()
        elif action == "recount":
            lines.action_request_recount()
        elif action == "accept_first":
            lines.action_accept_first_count()
        elif action in ("approve_all", "accept_all_first", "validate", "validate_force"):
            method = {
                "approve_all": count.action_approve_all,
                "accept_all_first": count.action_accept_first_counts,
                "validate": count.action_apply,
                "validate_force": count.action_apply_force,
            }[action]
            result = method()
            if isinstance(result, dict):
                message = result.get("params", {}).get("message")
        else:
            raise UserError(self.env._("Acción desconocida: %s", action))
        data = self.supervisor_get_data()
        data["message"] = message
        data["validated"] = count.state == "done" and count.name
        return data

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
            (self.env._("Unidad de recuento"), 18),
            (self.env._("Contado en embalajes"), 24),
            (self.env._("Teórico en embalajes"), 24),
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
                (line.count_unit_names or "", None),
                (line.counted_breakdown or "", None),
                (line.theoretical_breakdown or "", None),
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
