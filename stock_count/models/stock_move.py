from odoo import fields, models
from odoo.exceptions import UserError


class StockMove(models.Model):
    _inherit = "stock.move"

    count_id = fields.Many2one(
        "stock.count",
        string="Recuento",
        index=True,
        copy=False,
        readonly=True,
        help="Recuento que generó este ajuste de inventario.",
    )

    def _action_done(self, *args, **kwargs):
        """Bloqueo de movimientos sobre stock en recuento.

        Es el único punto por el que pasa toda validación (transferencias, fabricación,
        punto de venta, desecho, ajustes). Solo se controla la validación: la reserva
        sigue permitida. Los ajustes generados por el propio recuento llevan count_id
        y se dejan pasar.
        """
        candidates = self.filtered(lambda move: not move.count_id)
        if self.env.context.get("stock_count_skip_lock"):
            candidates = self.env["stock.move"]
        blocked, warned = candidates.move_line_ids._get_stock_count_conflicts()
        if blocked:
            raise UserError(self._stock_count_blocked_message(blocked))
        res = super()._action_done(*args, **kwargs)
        if warned:
            self._stock_count_flag_moved(warned)
        return res

    def _stock_count_blocked_message(self, conflicts):
        lines = []
        for move_line, count_line in conflicts[:10]:
            count = count_line.count_id
            lines.append(
                self.env._(
                    "- %(product)s en %(location)s: recuento %(count)s a cargo de %(user)s",
                    product=move_line.product_id.display_name,
                    location=count_line.location_id.complete_name,
                    count=count.name,
                    user=count.user_id.name or "-",
                )
            )
        more = ""
        if len(conflicts) > 10:
            more = self.env._("\n… y %s más", len(conflicts) - 10)
        return self.env._(
            "Stock en recuento. No se pueden validar movimientos sobre:\n%(detail)s%(more)s\n\n"
            "Podés reservar desde otra ubicación o esperar a que se cierre el recuento.",
            detail="\n".join(lines),
            more=more,
        )

    def _stock_count_flag_moved(self, conflicts):
        by_count = {}
        for move_line, count_line in conflicts:
            by_count.setdefault(count_line.count_id, []).append((move_line, count_line))
        for count, pairs in by_count.items():
            count_lines = self.env["stock.count.line"].union(*[cl for _ml, cl in pairs])
            count_lines.sudo().write({"moved_during_count": True})
            detail = "\n".join(
                self.env._(
                    "- %(ref)s: %(product)s en %(location)s (%(qty)s %(uom)s, %(src)s → %(dst)s)",
                    ref=ml.reference or ml.move_id.name,
                    product=ml.product_id.display_name,
                    location=cl.location_id.complete_name,
                    qty=ml.quantity,
                    uom=ml.product_uom_id.name,
                    src=ml.location_id.name,
                    dst=ml.location_dest_id.name,
                )
                for ml, cl in pairs
            )
            count.sudo().message_post(
                subtype_xmlid="mail.mt_note",
                body=self.env._(
                    "Se validaron movimientos sobre stock en recuento (modo Avisar). "
                    "Las líneas quedaron marcadas como movidas durante el conteo:\n%s",
                    detail,
                ),
            )


class StockMoveLine(models.Model):
    _inherit = "stock.move.line"

    count_line_id = fields.Many2one(
        "stock.count.line",
        string="Línea de recuento",
        index=True,
        copy=False,
        readonly=True,
    )

    def _get_stock_count_conflicts(self):
        """Devuelve (bloqueadas, avisadas): pares (move line, línea de recuento) cuya
        validación toca un producto y ubicación tomados por un recuento activo."""
        blocked, warned = [], []
        move_lines = self.filtered(lambda ml: ml.quantity > 0)
        if not move_lines:
            return blocked, warned
        locations = move_lines.location_id | move_lines.location_dest_id
        active = (
            self.env["stock.count.line"]
            .sudo()
            ._get_active_lock_lines(move_lines.product_id, locations, move_lines.company_id)
        )
        if not active:
            return blocked, warned
        by_key = {}
        for count_line in active:
            by_key.setdefault((count_line.product_id.id, count_line.location_id.id), []).append(
                count_line
            )
        for ml in move_lines:
            for location in (ml.location_id, ml.location_dest_id):
                for count_line in by_key.get((ml.product_id.id, location.id), []):
                    if count_line.lot_id and count_line.lot_id != ml.lot_id:
                        continue
                    if count_line.company_id and ml.company_id != count_line.company_id:
                        continue
                    mode = count_line.count_id.lock_mode
                    if mode == "block":
                        blocked.append((ml, count_line))
                    elif mode == "warn":
                        warned.append((ml, count_line))
        return blocked, warned
