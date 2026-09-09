import logging
from datetime import timedelta

from odoo import api, fields, models
from odoo.addons.stock_count.models.res_company import LOCK_MODES
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

RULE_TYPES = [
    ("periodic", "Periódico"),
    ("turnover", "Rotación de valor"),
    ("accuracy", "Precisión mínima"),
    ("zero", "Confirmación de cero"),
]


class StockCountRule(models.Model):
    """Regla de conteo cíclico.

    Decide cuándo hay que contar qué, crea el recuento en borrador (o lo confirma
    si así se configuró) y le deja al supervisor una actividad con la fecha
    planificada, así la tarea le llega sola.
    """

    _name = "stock.count.rule"
    _description = "Regla de conteo cíclico"
    _inherit = ["mail.thread"]
    _order = "sequence, id"
    _check_company_auto = True

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    currency_id = fields.Many2one(related="company_id.currency_id")
    rule_type = fields.Selection(RULE_TYPES, string="Tipo", required=True, default="periodic")
    rule_description = fields.Char(compute="_compute_rule_description")

    # Alcance
    warehouse_id = fields.Many2one(
        "stock.warehouse",
        string="Depósito",
        check_company=True,
        default=lambda self: self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1
        ),
    )
    location_ids = fields.Many2many(
        "stock.location",
        "stock_count_rule_location_rel",
        "rule_id",
        "location_id",
        string="Ubicaciones",
        required=True,
        check_company=True,
        domain="[('usage', '=', 'internal'), ('warehouse_id', '=?', warehouse_id), "
        "'|', ('company_id', '=', company_id), ('company_id', '=', False)]",
    )
    include_children = fields.Boolean(string="Incluir sub-ubicaciones", default=True)
    scope = fields.Selection(
        [
            ("all", "Todos los productos"),
            ("category", "Categoría de producto"),
            ("products", "Productos seleccionados"),
        ],
        default="all",
        required=True,
    )
    categ_id = fields.Many2one("product.category", string="Categoría")
    product_ids = fields.Many2many(
        "product.product",
        "stock_count_rule_product_rel",
        "rule_id",
        "product_id",
        string="Productos",
        check_company=True,
        domain="[('type', '=', 'consu'), ('is_storable', '=', True)]",
    )

    # Parámetros por tipo
    period_days = fields.Integer(string="Cada (días)", default=30)
    next_date = fields.Date(
        string="Próximo recuento",
        default=fields.Date.context_today,
        help="Periódico: fecha en la que el cron genera el próximo recuento. Se puede "
        "adelantar o atrasar a mano.",
    )
    turnover_threshold = fields.Monetary(
        string="Valor movido desde el último recuento",
        currency_field="currency_id",
        help="Se genera un recuento de la ubicación cuando el valor a costo de lo que "
        "entró y salió desde el último recuento aplicado supera este monto.",
    )
    accuracy_threshold_pct = fields.Float(
        string="Precisión mínima (%)",
        default=95.0,
        digits=(16, 2),
        help="Se genera un recuento cuando la precisión promedio de los últimos recuentos "
        "de la ubicación queda por debajo de este valor.",
    )
    cooldown_days = fields.Integer(
        string="No repetir antes de (días)",
        default=7,
        help="Rotación, precisión y confirmación de cero: no vuelve a generar un recuento "
        "para la misma ubicación (y producto) hasta que pasen estos días.",
    )

    # Recuento generado
    user_id = fields.Many2one(
        "res.users",
        string="Supervisor",
        required=True,
        default=lambda self: self.env.user,
        domain=lambda self: [
            ("all_group_ids", "in", self.env.ref("stock_count.group_stock_count_manager").id)
        ],
        help="Recibe la actividad 'Realizar recuento' y queda como supervisor del recuento.",
    )
    counter_ids = fields.Many2many(
        "res.users",
        "stock_count_rule_counter_rel",
        "rule_id",
        "user_id",
        string="Contadores",
        domain=lambda self: [
            ("all_group_ids", "in", self.env.ref("stock_count.group_stock_count_user").id)
        ],
    )
    lock_mode = fields.Selection(
        LOCK_MODES,
        string="Bloqueo de movimientos",
        required=True,
        default=lambda self: self.env.company.stock_count_lock_mode,
    )
    planning_days = fields.Integer(
        string="Planificar a (días)",
        default=0,
        help="Fecha planificada del recuento: hoy más estos días. Es también el "
        "vencimiento de la actividad.",
    )
    auto_confirm = fields.Boolean(
        string="Confirmar automáticamente",
        help="Confirma el recuento al crearlo: congela el teórico y activa el bloqueo. "
        "Si no, queda en borrador hasta que el supervisor lo confirme.",
    )

    count_ids = fields.One2many("stock.count", "rule_id", string="Recuentos generados")
    count_count = fields.Integer(compute="_compute_count_count")
    last_run = fields.Datetime(string="Última ejecución", readonly=True)

    # ------------------------------------------------------------------
    # Cómputos y validaciones
    # ------------------------------------------------------------------
    @api.onchange("warehouse_id")
    def _onchange_warehouse_id(self):
        if self.warehouse_id and self.location_ids:
            self.location_ids = self.location_ids.filtered(
                lambda location: location.warehouse_id == self.warehouse_id
            )

    @api.depends("rule_type")
    def _compute_rule_description(self):
        descriptions = {
            "periodic": self.env._(
                "Genera un recuento de las ubicaciones cada N días, en la fecha indicada."
            ),
            "turnover": self.env._(
                "Genera un recuento de una ubicación cuando el valor movido desde su "
                "último recuento supera el umbral."
            ),
            "accuracy": self.env._(
                "Genera un recuento de una ubicación cuando su precisión histórica cae por "
                "debajo del mínimo."
            ),
            "zero": self.env._(
                "Cuando un producto llega a cero en una ubicación, genera un recuento para "
                "confirmar que efectivamente no queda nada."
            ),
        }
        for rule in self:
            rule.rule_description = descriptions.get(rule.rule_type, "")

    @api.depends("count_ids")
    def _compute_count_count(self):
        for rule in self:
            rule.count_count = len(rule.count_ids)

    @api.constrains("rule_type", "period_days", "turnover_threshold", "accuracy_threshold_pct")
    def _check_parameters(self):
        for rule in self:
            if rule.rule_type == "periodic" and rule.period_days <= 0:
                raise UserError(self.env._("El período tiene que ser mayor a cero días."))
            if rule.rule_type == "turnover" and rule.turnover_threshold <= 0:
                raise UserError(self.env._("El umbral de valor movido tiene que ser positivo."))
            if rule.rule_type == "accuracy" and not (0 < rule.accuracy_threshold_pct <= 100):
                raise UserError(self.env._("La precisión mínima tiene que estar entre 0 y 100."))

    # ------------------------------------------------------------------
    # Alcance
    # ------------------------------------------------------------------
    def _get_rule_locations(self):
        self.ensure_one()
        if self.include_children:
            return self.env["stock.location"].search(
                [("id", "child_of", self.location_ids.ids), ("usage", "=", "internal")]
            )
        return self.location_ids

    def _product_in_scope(self, product):
        self.ensure_one()
        if self.scope == "category":
            return bool(self.categ_id) and (
                product.categ_id == self.categ_id
                or product.categ_id.parent_path.startswith(self.categ_id.parent_path)
            )
        if self.scope == "products":
            return product in self.product_ids
        return True

    def _scope_vals(self):
        self.ensure_one()
        vals = {"scope": self.scope}
        if self.scope == "category":
            vals["categ_id"] = self.categ_id.id
        elif self.scope == "products":
            vals["product_ids"] = [(6, 0, self.product_ids.ids)]
        return vals

    # ------------------------------------------------------------------
    # Creación del recuento
    # ------------------------------------------------------------------
    def _prepare_count_vals(self, locations, include_children, origin, **extra):
        self.ensure_one()
        date_planned = fields.Datetime.now() + timedelta(days=self.planning_days)
        vals = {
            "company_id": self.company_id.id,
            "warehouse_id": self.warehouse_id.id,
            "location_ids": [(6, 0, locations.ids)],
            "include_children": include_children,
            "user_id": self.user_id.id,
            "counter_ids": [(6, 0, self.counter_ids.ids)],
            "lock_mode": self.lock_mode,
            "date_planned": date_planned,
            "origin": origin,
            "rule_id": self.id,
        }
        vals.update(self._scope_vals())
        vals.update(extra)
        return vals

    def _create_count(self, locations, include_children, origin, **extra):
        self.ensure_one()
        Count = self.env["stock.count"].with_company(self.company_id)
        count = Count.create(
            self._prepare_count_vals(locations, include_children, origin, **extra)
        )
        count.message_post(
            subtype_xmlid="mail.mt_note",
            body=self.env._(
                "Recuento generado por la regla de conteo cíclico %(rule)s (%(type)s). %(origin)s",
                rule=self.name,
                type=dict(RULE_TYPES)[self.rule_type],
                origin=origin,
            ),
        )
        count.activity_schedule(
            "mail.mail_activity_data_todo",
            date_deadline=fields.Date.to_date(count.date_planned),
            summary=self.env._("Realizar recuento %s", count.name),
            note=self.env._(
                "Recuento generado por la regla %(rule)s. Ubicaciones: %(locations)s.",
                rule=self.name,
                locations=", ".join(locations.mapped("complete_name")),
            ),
            user_id=self.user_id.id,
        )
        if self.auto_confirm:
            try:
                with self.env.cr.savepoint():
                    count.action_confirm()
            except UserError as error:
                count.message_post(
                    subtype_xmlid="mail.mt_note",
                    body=self.env._(
                        "No se pudo confirmar automáticamente; queda en borrador. Motivo: %s",
                        error.args[0] if error.args else error,
                    ),
                )
        self.last_run = fields.Datetime.now()
        return count

    def _recently_generated(self, location, product=None):
        """Ya hay un recuento de esta regla para la ubicación (y producto) dentro del
        período de enfriamiento, o uno activo que la cubre."""
        self.ensure_one()
        cutoff = fields.Datetime.now() - timedelta(days=max(self.cooldown_days, 0))
        domain = [
            ("rule_id", "=", self.id),
            ("location_ids", "in", location.id),
            "|",
            ("create_date", ">=", cutoff),
            ("state", "in", ("draft", "ready", "counting", "review")),
        ]
        if product is not None:
            domain.append(("product_ids", "in", product.id))
        return bool(self.env["stock.count"].search_count(domain, limit=1))

    def _last_applied_count_date(self, location):
        self.ensure_one()
        line = self.env["stock.count.line"].search(
            [("location_id", "=", location.id), ("count_state", "=", "done")],
            order="count_date desc, id desc",
            limit=1,
        )
        return line.count_id.date_end if line else False

    # ------------------------------------------------------------------
    # Tipos de regla
    # ------------------------------------------------------------------
    def _run_periodic(self):
        self.ensure_one()
        today = fields.Date.context_today(self)
        if self.next_date and self.next_date > today:
            return self.env["stock.count"]
        count = self._create_count(
            self.location_ids,
            self.include_children,
            self.env._("Recuento periódico cada %s días.", self.period_days),
        )
        self.next_date = today + timedelta(days=self.period_days)
        return count

    def _turnover_value(self, location):
        """Valor a costo de lo que entró y salió de la ubicación desde el último recuento
        aplicado. Ignora los ajustes de inventario."""
        self.ensure_one()
        domain = [
            ("state", "=", "done"),
            ("move_id.is_inventory", "=", False),
            ("company_id", "=", self.company_id.id),
            "|",
            ("location_id", "=", location.id),
            ("location_dest_id", "=", location.id),
        ]
        since = self._last_applied_count_date(location)
        if since:
            domain.append(("date", ">", since))
        if self.scope == "category" and self.categ_id:
            domain.append(("product_id.categ_id", "child_of", self.categ_id.id))
        elif self.scope == "products":
            domain.append(("product_id", "in", self.product_ids.ids))
        groups = self.env["stock.move.line"]._read_group(domain, ["product_id"], ["quantity:sum"])
        total = 0.0
        for product, quantity in groups:
            total += quantity * product.with_company(self.company_id).standard_price
        return total

    def _run_turnover(self):
        self.ensure_one()
        due = self.env["stock.location"]
        for location in self._get_rule_locations():
            if self._recently_generated(location):
                continue
            if self._turnover_value(location) > self.turnover_threshold:
                due |= location
        if not due:
            return self.env["stock.count"]
        return self._create_count(
            due,
            False,
            self.env._(
                "Rotación de valor: %(locations)s superaron %(threshold)s desde el último "
                "recuento.",
                locations=", ".join(due.mapped("name")),
                threshold=self.turnover_threshold,
            ),
        )

    def _run_accuracy(self):
        self.ensure_one()
        due = self.env["stock.location"]
        locations = self._get_rule_locations()
        # Indicadores no almacenados: se recalculan para no leer un valor viejo de la caché
        locations.invalidate_recordset(
            ["stock_count_count", "stock_count_accuracy", "stock_count_last_date"]
        )
        for location in locations:
            if self._recently_generated(location):
                continue
            if location.stock_count_count and (
                location.stock_count_accuracy < self.accuracy_threshold_pct
            ):
                due |= location
        if not due:
            return self.env["stock.count"]
        return self._create_count(
            due,
            False,
            self.env._(
                "Precisión por debajo de %(threshold)s %%: %(locations)s.",
                threshold=self.accuracy_threshold_pct,
                locations=", ".join(
                    f"{loc.name} ({loc.stock_count_accuracy:.1f} %)" for loc in due
                ),
            ),
        )

    def _run_zero(self, product, location):
        """Confirmación de cero: un producto llegó a cero en una ubicación de la regla."""
        self.ensure_one()
        if self._recently_generated(location, product):
            return self.env["stock.count"]
        active_line = self.env["stock.count.line"].search_count(
            [
                ("product_id", "=", product.id),
                ("location_id", "=", location.id),
                ("count_state", "in", ("ready", "counting", "review")),
            ],
            limit=1,
        )
        if active_line:
            return self.env["stock.count"]
        return self._create_count(
            location,
            False,
            self.env._(
                "Confirmación de cero: %(product)s quedó en cero en %(location)s.",
                product=product.display_name,
                location=location.complete_name,
            ),
            scope="products",
            product_ids=[(6, 0, product.ids)],
            include_zero_quants=True,
        )

    def _run(self):
        """Ejecuta la regla y devuelve los recuentos creados."""
        counts = self.env["stock.count"]
        for rule in self.filtered("active"):
            rule = rule.with_company(rule.company_id)
            if rule.rule_type == "periodic":
                counts |= rule._run_periodic()
            elif rule.rule_type == "turnover":
                counts |= rule._run_turnover()
            elif rule.rule_type == "accuracy":
                counts |= rule._run_accuracy()
        return counts

    @api.model
    def _cron_generate_counts(self):
        rules = self.search([("rule_type", "!=", "zero")])
        created = self.env["stock.count"]
        for rule in rules:
            try:
                with self.env.cr.savepoint():
                    created |= rule._run()
            except Exception:  # noqa: BLE001 - una regla rota no frena a las demás
                _logger.exception("Regla de conteo cíclico %s: error al generar", rule.name)
        if created:
            _logger.info("Conteo cíclico: %s recuentos generados", len(created))
        return created

    @api.model
    def _trigger_zero_confirmation(self, product, location, company):
        """Llamado al validar movimientos: busca reglas de cero que cubran la ubicación."""
        rules = self.search(
            [("rule_type", "=", "zero"), ("company_id", "=", company.id)]
        ).filtered(
            lambda rule: location in rule._get_rule_locations() and rule._product_in_scope(product)
        )
        counts = self.env["stock.count"]
        for rule in rules:
            counts |= rule._run_zero(product, location)
        return counts

    # ------------------------------------------------------------------
    # Botones
    # ------------------------------------------------------------------
    def action_run_now(self):
        self.ensure_one()
        if self.rule_type == "zero":
            raise UserError(
                self.env._(
                    "Las reglas de confirmación de cero se disparan solas cuando un producto "
                    "llega a cero al validar un movimiento."
                )
            )
        counts = self._run()
        if not counts:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": self.env._("Nada que contar"),
                    "message": self.env._(
                        "La regla no encontró ubicaciones que cumplan la condición hoy."
                    ),
                    "type": "info",
                },
            }
        return self.action_view_counts(counts)

    def action_view_counts(self, counts=None):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("stock_count.stock_count_action")
        counts = counts if counts is not None else self.count_ids
        if len(counts) == 1:
            action.update({"view_mode": "form", "res_id": counts.id, "views": [(False, "form")]})
        else:
            action["domain"] = [("id", "in", counts.ids)]
        action["context"] = {"create": False}
        return action
