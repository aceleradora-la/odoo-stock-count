from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import float_compare, float_is_zero, float_round

LINE_STATES = [
    ("pending", "Pendiente"),
    ("counted", "Contada"),
    ("recount", "Reconteo"),
    ("approved", "Aprobada"),
    ("applied", "Validada"),
    ("skipped", "Omitida"),
]

# Campos que un contador no puede ver en conteo ciego. Se anulan en el ORM, no solo
# en la vista, así tampoco salen por export, RPC, agrupaciones ni filtros.
BLIND_FIELDS = (
    "qty_theoretical",
    "qty_current",
    "qty_diff",
    "diff_pct",
    "diff_value",
    "theoretical_breakdown",
)
# Conteo en embalajes: por cada etapa, (embalajes, sueltas, cantidad en la unidad base).
PACK_FIELDS = {
    "counted": ("qty_counted_packs", "qty_counted_loose", "qty_counted"),
    "recount": ("qty_recount_packs", "qty_recount_loose", "qty_recount"),
}
# Lo único que un contador puede escribir en una línea.
COUNTER_WRITABLE_FIELDS = {
    "qty_counted",
    "qty_recount",
    "qty_counted_packs",
    "qty_counted_loose",
    "qty_recount_packs",
    "qty_recount_loose",
    "note",
    "reason_id",
}


def _domain_field_names(domain):
    for leaf in domain or ():
        if isinstance(leaf, list | tuple) and len(leaf) == 3 and isinstance(leaf[0], str):
            yield leaf[0].split(".")[0]


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
    package_id = fields.Many2one("stock.quant.package", string="Paquete")
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
    count_pack_id = fields.Many2one(
        "product.packaging",
        string="Unidad de recuento",
        readonly=True,
        copy=False,
        help="Embalaje en el que se cuenta esta línea. Se toma del producto al confirmar "
        "y el contador puede cambiarlo en la app.",
    )
    count_pack_factor = fields.Float(
        string="Unidades por embalaje",
        digits="Product Unit of Measure",
        readonly=True,
        copy=False,
        help="Congelado en la línea: un cambio posterior del embalaje no altera el recuento.",
    )
    qty_counted_packs = fields.Float(
        string="1er conteo: embalajes", digits="Product Unit of Measure"
    )
    qty_counted_loose = fields.Float(
        string="1er conteo: sueltas", digits="Product Unit of Measure"
    )
    qty_recount_packs = fields.Float(
        string="2do conteo: embalajes", digits="Product Unit of Measure"
    )
    qty_recount_loose = fields.Float(
        string="2do conteo: sueltas", digits="Product Unit of Measure"
    )
    counted_breakdown = fields.Char(string="Contado en embalajes", compute="_compute_breakdown")
    theoretical_breakdown = fields.Char(
        string="Teórico en embalajes", compute="_compute_breakdown"
    )
    unit_cost = fields.Float(
        string="Costo unitario",
        digits="Product Price",
        readonly=True,
        copy=False,
        help="Costo del producto con el que se valoriza la diferencia. Se toma al crear la "
        "línea y se congela al validar, para que el historial no cambie con el costo.",
    )
    zero_filled = fields.Boolean(
        string="Cerrada en cero al terminar",
        readonly=True,
        copy=False,
        help="El contador terminó sin cargar cantidad y la línea quedó en 0. Nunca se "
        "aprueba sola: la confirma un reconteo o el supervisor.",
    )

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
    last_op_uid = fields.Char(
        string="Último pedido de la app",
        copy=False,
        readonly=True,
        help="Identificador del último 'sumar' recibido de la app: si el teléfono lo reenvía "
        "porque se cortó la señal antes de recibir la respuesta, no se suma dos veces.",
    )
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

    @api.depends("qty_final", "qty_theoretical", "state", "unit_cost")
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
            line.diff_value = diff * line.unit_cost

    def _current_unit_cost(self):
        self.ensure_one()
        return self.product_id.sudo().with_company(self.company_id).standard_price

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        for line, vals in zip(lines, vals_list, strict=True):
            extra = {}
            if "unit_cost" not in vals:
                extra["unit_cost"] = line._current_unit_cost()
            if "count_pack_id" not in vals:
                product = line.product_id.sudo()
                pack = product._stock_count_default_pack()
                if pack:
                    extra["count_pack_id"] = pack.id
                    extra["count_pack_factor"] = product._stock_count_pack_factor(pack)
            if extra:
                super(StockCountLine, line).write(extra)
        return lines

    # ------------------------------------------------------------------
    # Conteo en embalajes
    # ------------------------------------------------------------------
    def _count_stage(self):
        """Etapa que se está cargando: el segundo conteo manda una vez pedido."""
        self.ensure_one()
        return "recount" if self.state == "recount" or self.recounted_at else "counted"

    def _split_packs(self, quantity):
        """Cantidad en la unidad base → (embalajes enteros, sueltas)."""
        self.ensure_one()
        factor = self.count_pack_factor
        if not self.count_pack_id or factor <= 0 or quantity <= 0:
            return 0.0, quantity
        rounding = self._rounding()
        packs = float(int((quantity + rounding / 2.0) // factor))
        loose = float_round(quantity - packs * factor, precision_rounding=rounding)
        return packs, max(loose, 0.0)

    def _breakdown(self, quantity):
        self.ensure_one()
        if not self.count_pack_id:
            return False
        packs, loose = self._split_packs(quantity)
        return f"{packs:g} × {self.count_pack_id.display_name} + {loose:g}"

    @api.depends(
        "count_pack_id",
        "count_pack_factor",
        "qty_final",
        "qty_theoretical",
        "state",
        "qty_counted_packs",
        "qty_counted_loose",
        "qty_recount_packs",
        "qty_recount_loose",
    )
    def _compute_breakdown(self):
        for line in self:
            if not line.count_pack_id or line.state == "pending":
                line.counted_breakdown = False
            else:
                packs_f, loose_f, _qty_f = PACK_FIELDS[line._count_stage()]
                line.counted_breakdown = (
                    f"{line[packs_f]:g} × {line.count_pack_id.display_name} + {line[loose_f]:g}"
                )
            line.theoretical_breakdown = line._breakdown(line.qty_theoretical)

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
        # Embalajes + sueltas → cantidad en la unidad base, que es con la que trabaja
        # todo el recuento (diferencias, tolerancias, ajustes).
        derive = []
        for packs_f, loose_f, qty_f in PACK_FIELDS.values():
            if (packs_f in vals or loose_f in vals) and qty_f not in vals:
                if len(self) != 1:
                    for line in self:
                        line.write(vals)
                    return True
                packs = vals.get(packs_f, self[packs_f]) or 0.0
                loose = vals.get(loose_f, self[loose_f]) or 0.0
                if packs and not self.count_pack_id:
                    raise UserError(
                        self.env._(
                            "%s no tiene unidad de recuento: cargá la cantidad en su unidad.",
                            self.product_id.display_name,
                        )
                    )
                vals = dict(vals, **{qty_f: packs * self.count_pack_factor + loose})
            elif qty_f in vals and packs_f not in vals and loose_f not in vals:
                derive.append((packs_f, loose_f, qty_f))
        if any(vals.get(name, 0.0) < 0 for names in PACK_FIELDS.values() for name in names):
            raise UserError(self.env._("La cantidad no puede ser negativa."))
        counting = "qty_counted" in vals or "qty_recount" in vals
        if counting and not self.env.context.get("stock_count_skip_checks"):
            self._check_can_count()
        if counting:
            self._check_serial_quantity(vals)
        res = super().write(vals)
        # Cantidad base cargada directo (escritorio, cierre en cero): se reparte en
        # embalajes enteros y sueltas para que la app y los reportes la muestren igual.
        for packs_f, loose_f, qty_f in derive:
            for line in self.filtered("count_pack_id"):
                packs, loose = line._split_packs(vals[qty_f])
                super(StockCountLine, line).write({packs_f: packs, loose_f: loose})
        if counting:
            # Una cantidad cargada a mano deja de ser un "cierre en cero"
            zero_fill = bool(self.env.context.get("stock_count_zero_fill"))
            flagged = self.filtered(lambda line: line.zero_filled != zero_fill)
            super(StockCountLine, flagged).write({"zero_filled": zero_fill})
            now = fields.Datetime.now()
            uid = self.env.user.id
            if "qty_counted" in vals:
                first = self.filtered(lambda line: line.state in ("pending", "counted"))
                super(StockCountLine, first).write(
                    {"counted_by_id": uid, "counted_at": now, "state": "counted"}
                )
                # Sumando de a uno (escaneo, +1) la cantidad todavía no es la final: se
                # evalúa al terminar la ubicación.
                if not self.env.context.get("stock_count_incremental"):
                    first._immediate_recount()
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
            self.count_id._auto_review()
            # Un reconteo que dejó todo aprobado valida el recuento.
            self.count_id._try_auto_validate()
        return res

    def _immediate_recount(self):
        """Reconteo inmediato: el primer conteo que supera el umbral vuelve a contarse en
        el momento, sin esperar a la revisión. Al contador no se le informa cuánto
        esperaba el sistema, solo que tiene que contar de nuevo."""
        again = self.filtered(
            lambda line: (
                line.state == "counted"
                and line.count_id.immediate_recount
                and line.count_state in ("ready", "counting")
                and not line.recounted_at
                and not line.count_id._line_within_tolerance(line)
                and line.count_id._line_needs_recount(line)
            )
        )
        super(StockCountLine, again).write(
            {
                "state": "recount",
                "qty_recount": 0.0,
                "qty_recount_packs": 0.0,
                "qty_recount_loose": 0.0,
            }
        )
        return again

    def _is_serial(self):
        self.ensure_one()
        return bool(self.lot_id) and self.product_id.sudo().tracking == "serial"

    def _check_serial_quantity(self, vals):
        """Un número de serie está (1) o no está (0): no admite otra cantidad."""
        quantities = [vals[name] for name in ("qty_counted", "qty_recount") if name in vals]
        if all(qty in (0, 1) for qty in quantities):
            return
        for line in self:
            if line._is_serial():
                raise UserError(
                    self.env._(
                        "%(product)s · serie %(lot)s: un número de serie solo puede estar "
                        "(1) o no estar (0).",
                        product=line.product_id.display_name,
                        lot=line.lot_id.name,
                    )
                )

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
                                vals[name] = False if name == "theoretical_breakdown" else 0.0
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
        packs_f, loose_f, qty_f = PACK_FIELDS[self._count_stage()]
        pack = self.count_pack_id
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
            "package_name": self.package_id.display_name or "",
            "owner_name": self.owner_id.display_name or "",
            "is_serial": self._is_serial(),
            "uom_name": self.product_uom_id.name,
            "state": self.state,
            "is_recount": self.state == "recount",
            "done": self.state == "counted",
            "quantity": self[qty_f],
            "pack": {
                "id": pack.id,
                "name": pack.display_name,
                "factor": self.count_pack_factor,
            }
            if pack
            else False,
            "packs": self[packs_f],
            "loose": self[loose_f],
            "pack_options": self._counter_pack_options(),
            "note": self.note or "",
        }

    def _counter_pack_options(self):
        """Unidades entre las que el contador puede elegir para este renglón."""
        self.ensure_one()
        product = self.product_id
        packs = product._stock_count_packs() | self.count_pack_id
        if not packs or self._is_serial():
            return []
        options = [{"id": False, "name": self.product_uom_id.name, "factor": 1.0}]
        for pack in packs:
            factor = (
                self.count_pack_factor
                if pack == self.count_pack_id
                else product._stock_count_pack_factor(pack)
            )
            options.append(
                {"id": pack.id, "name": f"{pack.display_name} · {factor:g}", "factor": factor}
            )
        return options

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
            "is_manager": user.has_group("stock_count.group_stock_count_manager"),
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

        def found_product(product, lot=None, quantity=1.0, pack=None):
            result.update(
                {
                    "type": "product",
                    "product_id": product.id,
                    "product_name": product.display_name,
                    "lot_id": lot.id if lot else False,
                    "quantity": quantity or 1.0,
                    "pack_id": pack.id if pack else False,
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
        # El código de un embalaje: suma un embalaje entero
        product, pack = Product._stock_count_find_pack_barcode(barcode)
        if product and pack:
            return found_product(product, None, product._stock_count_pack_factor(pack), pack)
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

    def counter_set_quantity(self, quantity=None, packs=None, loose=None):
        """Carga primer o segundo conteo según el estado de la línea: una cantidad en la
        unidad del producto, o embalajes + sueltas si la línea tiene unidad de recuento."""
        self.ensure_one()
        packs_f, loose_f, qty_f = PACK_FIELDS[self._count_stage()]
        was_recount = self.state == "recount"
        if packs is not None or loose is not None:
            self.write({packs_f: packs or 0.0, loose_f: loose or 0.0})
        else:
            self.write({qty_f: quantity or 0.0})
        data = self.sudo()._counter_line_data()
        data["recount_requested"] = self.state == "recount" and not was_recount
        return data

    def counter_set_pack(self, pack_id=False):
        """El contador cambia la unidad en la que cuenta este renglón: la unidad del
        producto (sin embalaje) o uno de sus embalajes. Lo ya cargado se conserva."""
        self.ensure_one()
        self.check_access("write")
        self._check_can_count()
        product = self.product_id.sudo()
        pack = (product._stock_count_packs() | self.sudo().count_pack_id).filtered(
            lambda candidate: candidate.id == pack_id
        )
        if pack_id and not pack:
            raise UserError(self.env._("Ese embalaje no es de %s.", product.display_name))
        line = self.sudo()
        vals = {
            "count_pack_id": pack.id,
            "count_pack_factor": (
                line.count_pack_factor
                if pack and pack == line.count_pack_id
                else product._stock_count_pack_factor(pack)
            ),
        }
        super(StockCountLine, line).write(vals)
        for packs_f, loose_f, qty_f in PACK_FIELDS.values():
            packs, loose = line._split_packs(line[qty_f])
            super(StockCountLine, line).write({packs_f: packs, loose_f: loose})
        return line._counter_line_data()

    def counter_add_quantity(self, delta=1.0, pack_id=False, op_uid=False):
        """Suma a la cantidad contada (delta en la unidad del producto). Si el escaneo fue
        del código del embalaje de la línea, suma embalajes enteros. Bloquea la fila para
        que dos escaneos simultáneos (dos contadores, o doble toque) no se pisen.

        `op_uid` identifica el pedido de la app: si llega repetido (el teléfono lo reenvía
        porque perdió la señal antes de recibir la respuesta) no se suma otra vez."""
        self.ensure_one()
        self.check_access("write")
        self.env.cr.execute("SELECT id FROM stock_count_line WHERE id = %s FOR UPDATE", [self.id])
        self.invalidate_recordset()
        if op_uid:
            if self.sudo().last_op_uid == op_uid:
                return self.sudo()._counter_line_data()
            super(StockCountLine, self.sudo()).write({"last_op_uid": op_uid})
        packs_f, loose_f, qty_f = PACK_FIELDS[self._count_stage()]
        current = self[qty_f]
        self = self.with_context(stock_count_incremental=True)
        if self._is_serial():
            if self.state == "counted" and current >= 1:
                data = self.sudo()._counter_line_data()
                data["serial_already"] = True
                return data
            return self.counter_set_quantity(1.0)
        if self.count_pack_id:
            packs, loose = self[packs_f], self[loose_f]
            factor = self.count_pack_factor
            if pack_id and pack_id == self.count_pack_id.id and factor > 0:
                packs += round(delta / factor)
            else:
                loose += delta
            return self.counter_set_quantity(packs=packs, loose=loose)
        return self.counter_set_quantity(current + delta)

    @api.model
    def counter_add_unexpected(
        self, count_id, location_id, product_id, lot_id=False, quantity=1.0
    ):
        """Producto encontrado en una ubicación donde el recuento no lo esperaba,
        agregado desde la app al escanearlo."""
        count = self.env["stock.count"].browse(count_id)
        count.check_access("read")
        product = self.env["product.product"].browse(product_id)
        lot = self.env["stock.lot"].browse(lot_id or [])
        if product.sudo().tracking != "none" and not lot:
            return {"need_lot": True}
        location = self.env["stock.location"].browse(location_id)
        line = count._add_unexpected_line(product, location, lot, quantity)
        return {"line": line.sudo()._counter_line_data()}

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
        if not location_id:
            # Al terminar todo el recuento no se cierran en cero las líneas sin asignar
            # de ubicaciones donde este contador no contó nada: pueden ser de otro.
            count = self.env["stock.count"].sudo().browse(count_id)
            if len(count.counter_ids) > 1:
                mine = self.search(
                    self._counter_domain(count_id)
                    + [("state", "!=", "pending"), ("counted_by_id", "=", self.env.user.id)]
                ).location_id
                pending = pending.filtered(
                    lambda line: line.assigned_user_id == self.env.user or line.location_id in mine
                )
        if pending and not zero_pending:
            return {"pending": len(pending), "done": False}
        pending.with_context(stock_count_zero_fill=True).write({"qty_counted": 0.0})
        # Lo contado sumando de a uno (escaneo, +1) recién acá es una cantidad final.
        counted = self._counter_domain(count_id) + [
            ("state", "=", "counted"),
            ("counted_by_id", "=", self.env.user.id),
        ]
        if location_id:
            counted.append(("location_id", "=", location_id))
        self.search(counted)._immediate_recount()
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
        self.count_id._try_auto_validate()
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
        self.count_id._auto_review()
        self.count_id._try_auto_validate()
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
        # Con el write del ORM, sin pasar por el de esta clase: poner qty_recount en 0 no
        # es "cargar un segundo conteo" y no debe marcar la línea como recontada.
        super(StockCountLine, self).write(
            {
                "state": "recount",
                "qty_recount": 0.0,
                "qty_recount_packs": 0.0,
                "qty_recount_loose": 0.0,
                "recounted_by_id": False,
                "recounted_at": False,
                "moved_during_count": False,
            }
        )
        return True

    def action_skip(self):
        self._check_manager()
        if any(line.state == "applied" for line in self):
            raise UserError(self.env._("No se puede omitir una línea ya validada."))
        self.write({"state": "skipped"})
        self.count_id._auto_review()
        self.count_id._try_auto_validate()
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
        """Aplica la cantidad final sobre los quants vía stock.quant._apply_inventory,
        todas las líneas de un recuento en una sola pasada."""
        lines = self.filtered(lambda line: line.state == "approved")
        for count in lines.count_id:
            count_lines = lines.filtered(lambda line, count=count: line.count_id == count)
            # El valor de la diferencia queda al costo del momento de validar
            for line in count_lines:
                super(StockCountLine, line).write({"unit_cost": line._current_unit_cost()})
            # La cantidad contada es absoluta: se compara con lo que hay HOY en el quant,
            # no con el snapshot. Así, si el stock se movió y el supervisor decidió
            # validar igualmente, el ajuste deja el quant en la cantidad contada.
            line_by_quant = {}
            loss_by_quant = {}
            for line in count_lines:
                current = line.quant_id.quantity if line.quant_id else 0.0
                if (
                    float_compare(current, line.qty_final, precision_rounding=line._rounding())
                    == 0
                ):
                    continue
                quant = line._get_or_create_quant()
                line_by_quant[quant.id] = line
                loss_by_quant[quant.id] = line.reason_id.location_dest_id.id
            if line_by_quant:
                quants = (
                    self.env["stock.quant"]
                    .browse(list(line_by_quant))
                    .sudo()
                    .with_company(count.company_id)
                    .with_context(
                        inventory_name=count.name,
                        stock_count_id=count.id,
                        stock_count_line_by_quant={
                            quant_id: line.id for quant_id, line in line_by_quant.items()
                        },
                        stock_count_loss_by_quant=loss_by_quant,
                    )
                )
                for quant in quants:
                    quant.write(
                        {
                            "inventory_quantity": line_by_quant[quant.id].qty_final,
                            "user_id": self.env.user.id,
                        }
                    )
                quants._apply_inventory()
            count_lines.write({"state": "applied"})
