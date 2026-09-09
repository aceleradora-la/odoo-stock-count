from odoo import fields, models


class StockLocation(models.Model):
    _inherit = "stock.location"

    stock_count_count = fields.Integer(
        string="Recuentos aplicados", compute="_compute_stock_count_stats"
    )
    stock_count_last_date = fields.Datetime(
        string="Último recuento", compute="_compute_stock_count_stats"
    )
    stock_count_accuracy = fields.Float(
        string="Precisión de recuentos (%)",
        compute="_compute_stock_count_stats",
        digits=(16, 2),
        help="Promedio de precisión (líneas sin diferencia sobre líneas contadas) de los "
        "últimos cinco recuentos aplicados que incluyeron esta ubicación.",
    )

    def _compute_stock_count_stats(self):
        Line = self.env["stock.count.line"].sudo()
        for location in self:
            lines = Line.search(
                [("location_id", "=", location.id), ("count_state", "=", "done")],
                order="count_date desc, id desc",
            )
            counts = lines.count_id.sorted(key=lambda count: count.date_end or count.date_planned)
            counts = counts[::-1]
            location.stock_count_count = len(counts)
            location.stock_count_last_date = counts[:1].date_end if counts else False
            accuracies = []
            for count in counts[:5]:
                count_lines = lines.filtered(
                    lambda line, count=count: line.count_id == count and line.state == "applied"
                )
                if count_lines:
                    ok = len(count_lines.filtered(lambda line: line._is_diff_zero()))
                    accuracies.append(100.0 * ok / len(count_lines))
            location.stock_count_accuracy = (
                sum(accuracies) / len(accuracies) if accuracies else 0.0
            )

    def action_view_stock_counts(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("stock_count.stock_count_action")
        action["domain"] = [("line_ids.location_id", "=", self.id)]
        action["context"] = {"search_default_done": 1}
        return action
