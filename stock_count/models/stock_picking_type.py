from odoo import fields, models


class StockPickingType(models.Model):
    _inherit = "stock.picking.type"

    code = fields.Selection(
        selection_add=[("stock_count", "Recuento de inventario")],
        ondelete={"stock_count": "cascade"},
    )
    count_stock_count_to_count = fields.Integer(compute="_compute_stock_count_counts")
    count_stock_count_review = fields.Integer(compute="_compute_stock_count_counts")
    count_stock_count_draft = fields.Integer(compute="_compute_stock_count_counts")

    def _compute_stock_count_counts(self):
        """Recuentos abiertos por tipo de operación, para la tarjeta del tablero."""
        self.count_stock_count_to_count = 0
        self.count_stock_count_review = 0
        self.count_stock_count_draft = 0
        types = self.filtered(lambda picking_type: picking_type.code == "stock_count")
        if not types:
            return
        groups = (
            self.env["stock.count"]
            .sudo()
            ._read_group(
                [
                    ("picking_type_id", "in", types.ids),
                    ("state", "in", ("draft", "ready", "counting", "review")),
                ],
                ["picking_type_id", "state"],
                ["__count"],
            )
        )
        for picking_type, state, number in groups:
            picking_type = self.browse(picking_type.id)
            if state == "draft":
                picking_type.count_stock_count_draft += number
            elif state == "review":
                picking_type.count_stock_count_review += number
            else:
                picking_type.count_stock_count_to_count += number

    def get_stock_count_action(self):
        """Recuentos del depósito, desde la tarjeta del tablero de Inventario."""
        action = self.env["ir.actions.act_window"]._for_xml_id("stock_count.stock_count_action")
        context = {
            key: value
            for key, value in self.env.context.items()
            if key.startswith("search_default_")
        }
        if self:
            action["display_name"] = self.display_name
            action["domain"] = [("picking_type_id", "in", self.ids)]
            context["default_warehouse_id"] = self[:1].warehouse_id.id
        action["context"] = context
        return action


class StockWarehouse(models.Model):
    _inherit = "stock.warehouse"

    count_type_id = fields.Many2one(
        "stock.picking.type",
        string="Tipo de operación de recuento",
        check_company=True,
        copy=False,
    )

    def _get_sequence_values(self, name=False, code=False):
        values = super()._get_sequence_values(name=name, code=code)
        values["count_type_id"] = {
            "name": self.env._("%(name)s Secuencia de recuento", name=name or self.name),
            "prefix": (code or self.code)
            + "/"
            + (self.count_type_id.sequence_code or "REC")
            + "/",
            "padding": 5,
            "company_id": self.company_id.id,
        }
        return values

    def _get_picking_type_create_values(self, max_sequence):
        data, next_sequence = super()._get_picking_type_create_values(max_sequence)
        data["count_type_id"] = {
            "name": self.env._("Recuentos"),
            "code": "stock_count",
            "default_location_src_id": self.lot_stock_id.id,
            "default_location_dest_id": self.lot_stock_id.id,
            "sequence": next_sequence + 1,
            "sequence_code": "REC",
            "company_id": self.company_id.id,
        }
        return data, next_sequence + 2

    def _get_picking_type_update_values(self):
        data = super()._get_picking_type_update_values()
        data["count_type_id"] = {"active": self.active}
        return data

    def _stock_count_create_missing_types(self):
        """Crea el tipo de operación Recuento en los depósitos que no lo tienen."""
        for warehouse in self.filtered(lambda warehouse: not warehouse.count_type_id):
            values = warehouse._create_or_update_sequences_and_picking_types()
            if values:
                warehouse.write(values)
