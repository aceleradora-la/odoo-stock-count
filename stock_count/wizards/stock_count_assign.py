from odoo import api, fields, models
from odoo.exceptions import UserError


class StockCountAssign(models.TransientModel):
    """Reparte las líneas de un recuento entre contadores."""

    _name = "stock.count.assign"
    _description = "Repartir líneas de recuento"

    count_id = fields.Many2one("stock.count", required=True, readonly=True)
    user_ids = fields.Many2many(
        "res.users",
        string="Contadores",
        required=True,
        domain=lambda self: [
            ("groups_id", "in", self.env.ref("stock_count.group_stock_count_user").id)
        ],
    )
    mode = fields.Selection(
        [
            ("location", "Por ubicación (cada ubicación a un solo contador)"),
            ("balanced", "Equilibrado línea a línea"),
        ],
        default="location",
        required=True,
    )
    only_unassigned = fields.Boolean(
        string="Solo líneas sin asignar",
        default=True,
        help="Desactivado, también reasigna las líneas asignadas que todavía no se contaron.",
    )
    line_count = fields.Integer(compute="_compute_line_count")

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        count = self.env["stock.count"].browse(self.env.context.get("default_count_id"))
        if count and "user_ids" in fields_list and not vals.get("user_ids"):
            vals["user_ids"] = [(6, 0, count.counter_ids.ids)]
        return vals

    @api.depends("count_id", "only_unassigned")
    def _compute_line_count(self):
        for wizard in self:
            wizard.line_count = len(wizard._get_lines())

    def _get_lines(self):
        self.ensure_one()
        lines = self.count_id.line_ids.filtered(lambda line: line.state in ("pending", "recount"))
        if self.only_unassigned:
            lines = lines.filtered(lambda line: not line.assigned_user_id)
        return lines

    def action_assign(self):
        self.ensure_one()
        count = self.count_id
        if count.state not in ("ready", "counting", "review"):
            raise UserError(self.env._("El recuento no está activo."))
        users = list(self.user_ids)
        if not users:
            raise UserError(self.env._("Elegí al menos un contador."))
        lines = self._get_lines().sorted(
            key=lambda line: (
                line.location_id.complete_name,
                line.product_id.display_name,
                line.id,
            )
        )
        if not lines:
            raise UserError(self.env._("No hay líneas para repartir."))

        missing = self.user_ids - count.counter_ids
        if missing:
            count.write({"counter_ids": [(4, user.id) for user in missing]})

        load = {user: 0 for user in users}
        assignment = {user: self.env["stock.count.line"] for user in users}
        if self.mode == "location":
            groups = {}
            for line in lines:
                groups.setdefault(line.location_id, self.env["stock.count.line"])
                groups[line.location_id] |= line
            # Cada ubicación completa al contador con menos carga en ese momento
            for _location, group in sorted(groups.items(), key=lambda item: item[0].complete_name):
                user = min(users, key=lambda user: (load[user], users.index(user)))
                assignment[user] |= group
                load[user] += len(group)
        else:
            for index, line in enumerate(lines):
                user = users[index % len(users)]
                assignment[user] |= line
                load[user] += 1

        summary = []
        for user in users:
            if assignment[user]:
                assignment[user].write({"assigned_user_id": user.id})
                locations = assignment[user].mapped("location_id.name")
                summary.append(
                    f"{user.name}: {len(assignment[user])} líneas "
                    f"({', '.join(sorted(set(locations)))})"
                )
        count.message_post(
            subtype_xmlid="mail.mt_note",
            body=self.env._("Líneas repartidas:\n%s", "\n".join(f"- {item}" for item in summary)),
        )
        return {"type": "ir.actions.act_window_close"}
