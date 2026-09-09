import logging

from odoo import models

_logger = logging.getLogger(__name__)


class StockMove(models.Model):
    _inherit = "stock.move"

    def _action_done(self, *args, **kwargs):
        res = super()._action_done(*args, **kwargs)
        try:
            self._stock_count_cycle_check_zero()
        except Exception:  # noqa: BLE001 - nunca frenar una validación por el conteo cíclico
            _logger.exception("Conteo cíclico: error al evaluar confirmación de cero")
        return res

    def _stock_count_cycle_check_zero(self):
        """Tras validar, si un producto quedó en cero en una ubicación interna de origen
        cubierta por una regla de confirmación de cero, se genera el recuento."""
        Rule = self.env["stock.count.rule"].sudo()
        if not Rule.search_count([("rule_type", "=", "zero")], limit=1):
            return
        Quant = self.env["stock.quant"].sudo()
        seen = set()
        for move in self.filtered(lambda move: move.state == "done" and not move.is_inventory):
            for line in move.move_line_ids:
                location = line.location_id
                if location.usage != "internal":
                    continue
                key = (line.product_id.id, location.id)
                if key in seen:
                    continue
                seen.add(key)
                quants = Quant._gather(line.product_id, location, strict=True)
                if sum(quants.mapped("quantity")) > 0:
                    continue
                Rule._trigger_zero_confirmation(line.product_id, location, move.company_id)
