from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.fields import Domain
from odoo.tools import float_compare, float_is_zero

LINE_STATES = [
    ("pending", "Pendiente"),
    ("counted", "Contada"),
    ("recount", "Reconteo"),
    ("approved", "Aprobada"),
    ("applied", "Aplicada"),
    ("skipped", "Omitida"),
]

# Campos que un contador no puede ver en conteo ciego. Se anulan en el ORM, no solo
# en la vista, así tampoco salen por export, RPC, agrupaciones ni filtros.
BLIND_FIELDS = ("qty_theoretical", "qty_current", "qty_diff", "diff_pct", "diff_value")
# Lo único que un contador puede escribir en una línea.
COUNTER_WRITABLE_FIELDS = {"qty_counted", "qty_recount", "note", "reason_id"}


def _domain_field_names(domain):
    for condition in Domain(domain or []).iter_conditions():
        yield condition.field_expr.split(".")[0]


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
        string="Producto",
        required=True,
        check_company=True,
        domain="[('type', '=', 'consu'), ('is_storable', '=', True)]",
    )
    product_uom_id = fields.Many2one(related="product_id.uom_id", string="UdM")
    location_id = fields.Many2one(
        "stock.location",
        string="Ubicación",
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
    count_date = fields.Datetime(
        related="count_id.date_planned", string="Fecha del recuento", store=True, index=True
    )
    count_user_id = fields.Many2one(related="count_id.user_id", string="Supervisor", store=True)
    warehouse_id = fields.Many2one(related="count_id.warehouse_id", store=True)
    categ_id = fields.Many2one(related="product_id.categ_id", store=True, string="Categoría")

    @api.depends("count_id.name", "product_id.display_name", "location_id.name", "lot_id.name")
    def _compute_display_name(self):
        for line in self:
            parts = [line.count_id.name, line.product_id.display_name, line.location_id.name]
            if line.lot_id:
                parts.append(line.lot_id.name)
            line.display_name = " · ".join(part for part in parts if part)

    # ------------------------------------------------------------------
    # Cómputos
    # ------------------------------------------------------------------
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

    def _rounding(self):
        self.ensure_one()
        return self.product_uom_id.rounding or 0.01

    def _is_diff_zero(self):
        self.ensure_one()
        return float_is_zero(self.qty_diff, precision_rounding=self._rounding())

    def _quant_moved_since_snapshot(self):
        self.ensure_one()
        current = self.quant_id.quantity if self.quant_id else 0.0
        return (
            float_compare(current, self.qty_theoretical, precision_rounding=self._rounding()) != 0
        )

    @api.model
    def _get_active_lock_lines(self, products, locations, companies=None):
        """Líneas de recuentos activos con bloqueo (block o warn) sobre estos productos y
        ubicaciones. Una sola consulta; product_id, location_id y count_state están
        indexados para que validar un picking grande no cueste."""
        domain = [
            ("count_state", "in", ("ready", "counting", "review")),
            ("state", "not in", ("applied", "skipped")),
            ("count_id.lock_mode", "!=", "none"),
            ("product_id", "in", products.ids),
            ("location_id", "in", locations.ids),
        ]
        if companies:
            domain.append(("company_id", "in", companies.ids))
        return self.search(domain)

    # ------------------------------------------------------------------
    # ORM: cargar un conteo registra quién y cuándo, y avanza el estado
    # ------------------------------------------------------------------
    def _check_can_count(self):
        is_manager = self.env.user.has_group("stock_count.group_stock_count_manager")
        for line in self:
            if line.count_state not in ("ready", "counting", "review"):
                raise UserError(
                    self.env._(
                        "El recuento %s no está activo; no se pueden cargar cantidades.",
                        line.count_id.name,
                    )
                )
            if line.state in ("approved", "applied"):
                raise UserError(
                    self.env._(
                        "La línea de %s ya está aprobada. Pedí un reconteo para recontarla.",
                        line.product_id.display_name,
                    )
                )
            if not is_manager and line.assigned_user_id and line.assigned_user_id != self.env.user:
                raise UserError(
                    self.env._(
                        "La línea de %(product)s está asignada a %(user)s.",
                        product=line.product_id.display_name,
                        user=line.assigned_user_id.name,
                    )
                )

    def write(self, vals):
        if self._is_blind_user():
            forbidden = set(vals) - COUNTER_WRITABLE_FIELDS
            if forbidden:
                raise AccessError(
                    self.env._(
                        "Un contador solo puede cargar cantidades, motivo y comentario "
                        "(campos no permitidos: %s).",
                        ", ".join(sorted(forbidden)),
                    )
                )
        counting = "qty_counted" in vals or "qty_recount" in vals
        if counting and not self.env.context.get("stock_count_skip_checks"):
            self._check_can_count()
        res = super().write(vals)
        if counting:
            now = fields.Datetime.now()
            uid = self.env.user.id
            if "qty_counted" in vals:
                first = self.filtered(lambda line: line.state in ("pending", "counted"))
                super(StockCountLine, first).write(
                    {"counted_by_id": uid, "counted_at": now, "state": "counted"}
                )
            if "qty_recount" in vals:
                second = self.filtered(lambda line: line.state == "recount")
                super(StockCountLine, second).write(
                    {"recounted_by_id": uid, "recounted_at": now, "state": "counted"}
                )
                # Tras el segundo conteo, lo que queda dentro de la tolerancia se aprueba
                # solo; el resto espera al supervisor.
                auto = second.filtered(
                    lambda line: (
                        line.count_state == "review" and line.count_id._line_within_tolerance(line)
                    )
                )
                super(StockCountLine, auto).write({"state": "approved"})
            # Contar la primera línea de un recuento confirmado lo pone en conteo.
            self.count_id.filtered(lambda count: count.state == "ready").sudo().action_start()
            # Cuando se carga la última línea, el recuento pasa solo a revisión.
            for count in self.count_id.filtered(lambda count: count.state == "counting"):
                if not count.line_ids.filtered(lambda line: line.state in ("pending", "recount")):
                    count.sudo().action_to_review()
        return res

    # ------------------------------------------------------------------
    # Conteo ciego forzado por el ORM
    # ------------------------------------------------------------------
    def _is_blind_user(self):
        """Usuario que no es supervisor ni superusuario: se le aplican las restricciones."""
        return not self.env.su and not self.env.user.has_group(
            "stock_count.group_stock_count_manager"
        )

    def _blind_company_active(self):
        return self._is_blind_user() and any(
            company.stock_count_blind for company in self.env.companies
        )

    def _read_format(self, fnames, load="_classic_read"):
        result = super()._read_format(fnames, load)
        if self._is_blind_user() and any(name in BLIND_FIELDS for name in fnames):
            blind_ids = set(self.sudo().filtered("blind").ids)
            if blind_ids:
                for vals in result:
                    if vals.get("id") in blind_ids:
                        for name in BLIND_FIELDS:
                            if name in vals:
                                vals[name] = 0.0
        return result

    def _export_rows(self, fields, *, _is_toplevel_call=True):
        if self._is_blind_user() and any(path and path[0] in BLIND_FIELDS for path in fields):
            if self.sudo().filtered("blind"):
                raise AccessError(
                    self.env._("En conteo ciego no se pueden exportar las cantidades teóricas.")
                )
        return super()._export_rows(fields, _is_toplevel_call=_is_toplevel_call)

    def _read_group(self, domain, groupby=(), aggregates=(), having=(), *args, **kwargs):
        if self._blind_company_active():
            used = [spec.split(":")[0] for spec in aggregates] + [
                spec.split(":")[0] for spec in groupby
            ]
            if any(name in BLIND_FIELDS for name in used):
                raise AccessError(
                    self.env._(
                        "En conteo ciego no se puede agrupar ni sumar por teórico o diferencia."
                    )
                )
        return super()._read_group(domain, groupby, aggregates, having, *args, **kwargs)

    def _search(self, domain, *args, **kwargs):
        if self._blind_company_active() and any(
            name in BLIND_FIELDS for name in _domain_field_names(domain)
        ):
            raise AccessError(
                self.env._("En conteo ciego no se puede filtrar por teórico o diferencia.")
            )
        return super()._search(domain, *args, **kwargs)

    # ------------------------------------------------------------------
    # Vista móvil del contador
    # ------------------------------------------------------------------
    @api.model
    def _counter_domain(self, count_id=False):
        user = self.env.user
        domain = [
            ("count_state", "in", ("ready", "counting", "review")),
            ("state", "in", ("pending", "recount", "counted")),
            "|",
            "|",
            ("assigned_user_id", "=", user.id),
            "&",
            ("assigned_user_id", "=", False),
            ("count_id.counter_ids", "in", [user.id]),
            ("count_id.user_id", "=", user.id),
        ]
        if count_id:
            domain.append(("count_id", "=", count_id))
        return domain

    def _counter_line_data(self):
        self.ensure_one()
        return {
            "id": self.id,
            "count_id": self.count_id.id,
            "count_name": self.count_id.name,
            "location_id": self.location_id.id,
            "location_name": self.location_id.complete_name,
            "location_barcode": self.location_id.barcode or "",
            "product_id": self.product_id.id,
            "product_name": self.product_id.display_name,
            "product_code": self.product_id.default_code or "",
            "product_barcode": self.product_id.barcode or "",
            "lot_id": self.lot_id.id,
            "lot_name": self.lot_id.name or "",
            "uom_name": self.product_uom_id.name,
            "state": self.state,
            "is_recount": self.state == "recount",
            "done": self.state == "counted",
            "quantity": self.qty_recount if self.state == "recount" else self.qty_counted,
            "note": self.note or "",
        }

    @api.model
    def counter_get_data(self, count_id=False):
        """Datos para la vista móvil: recuentos activos del usuario y sus líneas a contar."""
        user = self.env.user
        counts = self.env["stock.count"].search(
            [
                ("state", "in", ("ready", "counting", "review")),
                "|",
                ("counter_ids", "in", [user.id]),
                ("user_id", "=", user.id),
            ],
            order="date_planned desc, id desc",
        )
        lines = self.search(self._counter_domain(count_id))
        # La búsqueda respeta las reglas del usuario; los nombres relacionados (lote,
        # ubicación) se leen con sudo porque el contador no tiene acceso a esos modelos.
        return {
            "counts": [
                {"id": count.id, "name": count.name, "state": count.state, "blind": count.blind}
                for count in counts
            ],
            "lines": [line.sudo()._counter_line_data() for line in lines],
        }

    @api.model
    def counter_resolve_barcode(self, barcode, count_id=False):
        """Interpreta un código escaneado en la vista móvil.

        Primero busca coincidencias exactas (ubicación, producto por código de barras o
        referencia interna, lote de los productos en conteo). Si no hay, usa la
        nomenclatura de la compañía: con GS1 entiende producto, lote y cantidad en un
        mismo código; con la nomenclatura clásica, productos con peso o cantidad embebida.
        """
        barcode = (barcode or "").strip()
        result = {
            "barcode": barcode,
            "type": "unknown",
            "location_id": False,
            "product_id": False,
            "lot_id": False,
            "quantity": 1.0,
        }
        if not barcode:
            return result
        Location = self.env["stock.location"].sudo()
        Product = self.env["product.product"].sudo()
        Lot = self.env["stock.lot"].sudo()
        company = self.env.company

        def found_location(location):
            result.update({"type": "location", "location_id": location.id})
            return result

        def found_product(product, lot=None, quantity=1.0):
            result.update(
                {
                    "type": "product",
                    "product_id": product.id,
                    "lot_id": lot.id if lot else False,
                    "quantity": quantity or 1.0,
                }
            )
            return result

        location = Location.search(
            [("barcode", "=", barcode), ("usage", "=", "internal")], limit=1
        )
        if location:
            return found_location(location)
        product = Product.search(
            ["|", ("barcode", "=", barcode), ("default_code", "=", barcode)], limit=1
        )
        if product:
            return found_product(product)
        my_products = self.search(self._counter_domain(count_id)).product_id
        lot = Lot.search([("name", "=", barcode), ("product_id", "in", my_products.ids)], limit=1)
        if lot:
            return found_product(lot.product_id, lot)

        nomenclature = company.nomenclature_id
        if not nomenclature:
            return result
        try:
            parsed = nomenclature.parse_barcode(barcode)
        except Exception:  # noqa: BLE001 - un código raro no debe romper el escaneo
            return result

        if isinstance(parsed, list):  # GS1: varias partes en un mismo código
            gtin = lot_name = location_code = None
            quantity = 1.0
            for part in parsed:
                kind, value = part.get("type"), part.get("value")
                if kind == "product":
                    gtin = str(value)
                elif kind == "lot":
                    lot_name = str(value)
                elif kind == "quantity" and value:
                    quantity = float(value)
                elif kind in ("location", "location_dest"):
                    location_code = str(value)
            if location_code and not gtin:
                location = Location.search(
                    [("barcode", "=", location_code), ("usage", "=", "internal")], limit=1
                )
                if location:
                    return found_location(location)
            if gtin:
                unpadded = gtin.lstrip("0")
                product = Product.search([("barcode", "ilike", unpadded)]).filtered(
                    lambda product: (product.barcode or "").lstrip("0") == unpadded
                )[:1]
                if product:
                    lot = None
                    if lot_name:
                        lot = Lot.search(
                            [("name", "=", lot_name), ("product_id", "=", product.id)], limit=1
                        )
                    return found_product(product, lot, quantity)
            return result

        if isinstance(parsed, dict) and parsed.get("type") not in (None, "error"):
            kind = parsed["type"]
            base_code = parsed.get("base_code") or barcode
            if kind == "location":
                location = Location.search(
                    [("barcode", "=", base_code), ("usage", "=", "internal")], limit=1
                )
                if location:
                    return found_location(location)
            elif kind == "lot":
                lot = Lot.search(
                    [
                        ("name", "=", parsed.get("code") or barcode),
                        ("product_id", "in", my_products.ids),
                    ],
                    limit=1,
                )
                if lot:
                    return found_product(lot.product_id, lot)
            else:
                product = Product.search([("barcode", "=", base_code)], limit=1)
                if product:
                    quantity = parsed.get("value") if kind == "weight" else 1.0
                    return found_product(product, None, quantity or 1.0)
        return result

    def counter_set_quantity(self, quantity):
        """Carga primer o segundo conteo según el estado de la línea."""
        self.ensure_one()
        field = "qty_recount" if self.state == "recount" else "qty_counted"
        self.write({field: quantity})
        return self.sudo()._counter_line_data()

    def counter_add_quantity(self, delta=1.0):
        self.ensure_one()
        current = self.qty_recount if self.state == "recount" else self.qty_counted
        return self.counter_set_quantity(current + delta)

    @api.model
    def counter_finish(self, count_id, location_id=False, zero_pending=False):
        """Terminar el conteo (de una ubicación o del recuento).

        Las líneas que el contador no tocó quedan en 0 cuando confirma: en un conteo
        ciego, "no cargué nada" significa "no hay". Con todo contado, el recuento pasa
        solo a revisión. Los reconteos pendientes no se cierran en cero: hay que
        hacerlos.
        """
        domain = self._counter_domain(count_id) + [("state", "=", "pending")]
        if location_id:
            domain.append(("location_id", "=", location_id))
        pending = self.search(domain)
        if pending and not zero_pending:
            return {"pending": len(pending), "done": False}
        pending.write({"qty_counted": 0.0})
        count = self.env["stock.count"].sudo().browse(count_id)
        recount = self.search(self._counter_domain(count_id) + [("state", "=", "recount")])
        remaining = self.search(self._counter_domain(count_id) + [("state", "=", "pending")])
        return {
            "pending": 0,
            "done": True,
            "zeroed": len(pending),
            "state": count.state,
            "recount": len(recount),
            "remaining": len(remaining),
        }

    # ------------------------------------------------------------------
    # Acciones del supervisor
    # ------------------------------------------------------------------
    def _check_manager(self):
        if not self.env.user.has_group("stock_count.group_stock_count_manager"):
            raise UserError(self.env._("Solo el supervisor puede hacer esta acción."))

    def action_approve(self):
        self._check_manager()
        for line in self:
            if line.state != "counted":
                raise UserError(
                    self.env._(
                        "Solo se aprueban líneas contadas (%(product)s está %(state)s).",
                        product=line.product_id.display_name,
                        state=dict(LINE_STATES)[line.state].lower(),
                    )
                )
        self.write({"state": "approved"})
        return True

    def action_accept_first_count(self):
        """El supervisor da por bueno el primer conteo: la línea pasa a aprobada sin
        segundo conteo. Queda registrado quién lo decidió."""
        self._check_manager()
        for line in self:
            if line.state != "recount":
                raise UserError(
                    self.env._(
                        "Solo se acepta el primer conteo de una línea en reconteo (%s).",
                        line.product_id.display_name,
                    )
                )
        self.write(
            {
                "state": "approved",
                "note": self.env._("1er conteo aceptado sin recontar por %s", self.env.user.name),
            }
        )
        return True

    def action_request_recount(self):
        self._check_manager()
        for line in self:
            if line.state not in ("counted", "approved"):
                raise UserError(
                    self.env._(
                        "Solo se puede pedir reconteo de una línea contada o aprobada (%s).",
                        line.product_id.display_name,
                    )
                )
            if line.count_state not in ("counting", "review"):
                raise UserError(self.env._("El recuento no está en conteo ni en revisión."))
        self.write(
            {
                "state": "recount",
                "qty_recount": 0.0,
                "recounted_by_id": False,
                "recounted_at": False,
                "moved_during_count": False,
            }
        )
        return True

    def action_skip(self):
        self._check_manager()
        if any(line.state == "applied" for line in self):
            raise UserError(self.env._("No se puede omitir una línea ya aplicada."))
        self.write({"state": "skipped"})
        return True

    def action_reset_pending(self):
        self._check_manager()
        self.filtered(lambda line: line.state == "skipped").write({"state": "pending"})
        return True

    # ------------------------------------------------------------------
    # Aplicación del ajuste con el motor nativo de quants
    # ------------------------------------------------------------------
    def _get_or_create_quant(self):
        self.ensure_one()
        if self.quant_id:
            return self.quant_id
        Quant = self.env["stock.quant"].with_company(self.company_id)
        quant = Quant._gather(
            self.product_id,
            self.location_id,
            lot_id=self.lot_id,
            package_id=self.package_id,
            owner_id=self.owner_id,
            strict=True,
        )[:1]
        if not quant:
            quant = Quant.sudo().create(
                {
                    "product_id": self.product_id.id,
                    "location_id": self.location_id.id,
                    "lot_id": self.lot_id.id,
                    "package_id": self.package_id.id,
                    "owner_id": self.owner_id.id,
                    "quantity": 0.0,
                }
            )
        self.quant_id = quant
        return quant

    def _apply(self):
        """Aplica la cantidad final sobre el quant vía stock.quant._apply_inventory."""
        self.ensure_one()
        if self.state != "approved":
            return
        # La cantidad contada es absoluta: se compara con lo que hay HOY en el quant, no
        # con el snapshot. Así, si el stock se movió y el supervisor decidió aplicar
        # igualmente, el ajuste deja el quant en la cantidad contada.
        current = self.quant_id.quantity if self.quant_id else 0.0
        if float_compare(current, self.qty_final, precision_rounding=self._rounding()) == 0:
            self.write({"state": "applied"})
            return
        quant = self._get_or_create_quant()
        ctx = {
            "inventory_name": self.count_id.name,
            "stock_count_id": self.count_id.id,
            "stock_count_line_id": self.id,
            "stock_count_loss_location_id": self.reason_id.location_dest_id.id,
        }
        quant = quant.sudo().with_company(self.company_id).with_context(**ctx)
        quant.write({"inventory_quantity": self.qty_final, "user_id": self.env.user.id})
        quant._apply_inventory()
        self.write({"state": "applied"})
