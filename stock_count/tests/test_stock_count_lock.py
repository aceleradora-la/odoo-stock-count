from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestStockCountLock(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write(
            {
                "stock_count_lock_mode": "block",
                "stock_count_recount_threshold_pct": 5.0,
                "stock_count_recount_threshold_qty": 3.0,
                "stock_count_auto_approve_pct": 1.0,
            }
        )
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.company.id)], limit=1
        )
        cls.stock = cls.warehouse.lot_stock_id
        cls.customers = cls.env.ref("stock.stock_location_customers")
        cls.suppliers = cls.env.ref("stock.stock_location_suppliers")
        cls.shelf = cls.env["stock.location"].create(
            {"name": "Pasillo A", "location_id": cls.stock.id, "usage": "internal"}
        )
        cls.other_shelf = cls.env["stock.location"].create(
            {"name": "Pasillo B", "location_id": cls.stock.id, "usage": "internal"}
        )
        Product = cls.env["product.product"]
        cls.screw = Product.create(
            {"name": "Tornillo M8", "type": "consu", "is_storable": True, "standard_price": 35.0}
        )
        cls.roller = Product.create(
            {"name": "Rodillo 22", "type": "consu", "is_storable": True, "standard_price": 800.0}
        )
        cls.paint = Product.create(
            {"name": "Pintura 4 L", "type": "consu", "is_storable": True, "tracking": "lot"}
        )
        cls.lot_a = cls.env["stock.lot"].create(
            {"name": "L-240811", "product_id": cls.paint.id, "company_id": cls.company.id}
        )
        cls.lot_b = cls.env["stock.lot"].create(
            {"name": "L-240902", "product_id": cls.paint.id, "company_id": cls.company.id}
        )
        Quant = cls.env["stock.quant"]
        Quant._update_available_quantity(cls.screw, cls.shelf, 100.0)
        Quant._update_available_quantity(cls.roller, cls.shelf, 40.0)
        Quant._update_available_quantity(cls.paint, cls.shelf, 36.0, lot_id=cls.lot_a)
        Quant._update_available_quantity(cls.paint, cls.shelf, 12.0, lot_id=cls.lot_b)
        Quant._update_available_quantity(cls.screw, cls.other_shelf, 500.0)
        cls.Count = cls.env["stock.count"]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _create_count(self, **vals):
        base = {
            "warehouse_id": self.warehouse.id,
            "location_ids": [(6, 0, self.shelf.ids)],
            "include_children": False,
        }
        base.update(vals)
        return self.Count.create(base)

    def _picking(self, product, qty, src, dst, picking_type, lot=None):
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": picking_type.id,
                "location_id": src.id,
                "location_dest_id": dst.id,
                "move_ids": [
                    (
                        0,
                        0,
                        {
                            "name": product.display_name,
                            "product_id": product.id,
                            "product_uom_qty": qty,
                            "product_uom": product.uom_id.id,
                            "location_id": src.id,
                            "location_dest_id": dst.id,
                        },
                    )
                ],
            }
        )
        picking.action_confirm()
        picking.action_assign()
        if not picking.move_line_ids:
            picking.move_ids.move_line_ids = [
                (
                    0,
                    0,
                    {
                        "product_id": product.id,
                        "product_uom_id": product.uom_id.id,
                        "quantity": qty,
                        "location_id": src.id,
                        "location_dest_id": dst.id,
                        "lot_id": lot.id if lot else False,
                    },
                )
            ]
        elif lot:
            picking.move_line_ids.lot_id = lot
        picking.move_ids.picked = True
        return picking

    def _delivery(self, product, qty, src=None, lot=None):
        return self._picking(
            product, qty, src or self.shelf, self.customers, self.warehouse.out_type_id, lot=lot
        )

    def _receipt(self, product, qty, dst=None):
        return self._picking(
            product, qty, self.suppliers, dst or self.shelf, self.warehouse.in_type_id
        )

    def _qty(self, product, location, lot=None):
        return self.env["stock.quant"]._get_available_quantity(
            product, location, lot_id=lot, strict=True
        )

    # ------------------------------------------------------------------
    # Modo Bloquear
    # ------------------------------------------------------------------
    def test_block_delivery_but_allow_reservation(self):
        count = self._create_count()
        count.action_confirm()
        picking = self._delivery(self.screw, 5.0)
        self.assertEqual(picking.state, "assigned", "la reserva no se bloquea")
        with self.assertRaises(UserError) as err:
            picking.button_validate()
        self.assertIn(count.name, str(err.exception))
        self.assertIn("Tornillo M8", str(err.exception))
        self.assertEqual(picking.state, "assigned")
        self.assertEqual(self._qty(self.screw, self.shelf), 100.0)

    def test_block_receipt_into_counted_location(self):
        count = self._create_count()
        count.action_confirm()
        picking = self._receipt(self.screw, 20.0)
        with self.assertRaises(UserError):
            picking.button_validate()
        self.assertEqual(self._qty(self.screw, self.shelf), 100.0)

    def test_block_only_the_counted_key(self):
        count = self._create_count(scope="products", product_ids=[(6, 0, self.screw.ids)])
        count.action_confirm()
        # Otro producto en la misma ubicación: pasa
        other_product = self._delivery(self.roller, 2.0)
        other_product.button_validate()
        self.assertEqual(other_product.state, "done")
        # El mismo producto en otra ubicación: pasa
        other_location = self._delivery(self.screw, 5.0, src=self.other_shelf)
        other_location.button_validate()
        self.assertEqual(other_location.state, "done")
        self.assertEqual(self._qty(self.screw, self.other_shelf), 495.0)

    def test_block_respects_lot(self):
        count = self._create_count(scope="lots", lot_ids=[(6, 0, self.lot_b.ids)])
        count.action_confirm()
        blocked = self._delivery(self.paint, 1.0, lot=self.lot_b)
        with self.assertRaises(UserError):
            blocked.button_validate()
        allowed = self._delivery(self.paint, 1.0, lot=self.lot_a)
        allowed.button_validate()
        self.assertEqual(allowed.state, "done")
        self.assertEqual(self._qty(self.paint, self.shelf, self.lot_a), 35.0)

    def test_lock_released_after_apply_and_cancel(self):
        count = self._create_count(scope="products", product_ids=[(6, 0, self.screw.ids)])
        count.action_confirm()
        picking = self._delivery(self.screw, 5.0)
        with self.assertRaises(UserError):
            picking.button_validate()
        count.action_cancel()
        picking.button_validate()
        self.assertEqual(picking.state, "done")
        self.assertEqual(self._qty(self.screw, self.shelf), 95.0)

        again = self._create_count(scope="products", product_ids=[(6, 0, self.screw.ids)])
        again.action_confirm()
        again.action_start()
        again.line_ids.write({"qty_counted": 95.0})
        again.action_to_review()
        again.action_apply()
        self.assertEqual(again.state, "done")
        later = self._delivery(self.screw, 5.0)
        later.button_validate()
        self.assertEqual(self._qty(self.screw, self.shelf), 90.0)

    def test_own_adjustments_pass_through_the_lock(self):
        count = self._create_count(scope="products", product_ids=[(6, 0, self.roller.ids)])
        count.action_confirm()
        count.action_start()
        count.line_ids.write({"qty_counted": 38.0})
        count.action_to_review()
        count.line_ids.action_approve()
        count.action_apply()
        self.assertEqual(count.state, "done")
        self.assertEqual(self._qty(self.roller, self.shelf), 38.0)
        self.assertEqual(count.move_ids.count_id, count)

    def test_lock_mode_none_does_nothing(self):
        count = self._create_count(lock_mode="none")
        count.action_confirm()
        picking = self._delivery(self.screw, 5.0)
        picking.button_validate()
        self.assertEqual(picking.state, "done")
        self.assertFalse(count.line_ids.filtered("moved_during_count"))

    # ------------------------------------------------------------------
    # Modo Avisar
    # ------------------------------------------------------------------
    def test_warn_mode_flags_line_and_logs(self):
        count = self._create_count(lock_mode="warn")
        count.action_confirm()
        count.action_start()
        picking = self._delivery(self.screw, 10.0)
        picking.button_validate()
        self.assertEqual(picking.state, "done")
        screw = count.line_ids.filtered(lambda line: line.product_id == self.screw)
        self.assertTrue(screw.moved_during_count)
        self.assertEqual(count.moved_count, 1)
        roller = count.line_ids.filtered(lambda line: line.product_id == self.roller)
        self.assertFalse(roller.moved_during_count)
        body = " ".join(count.message_ids.mapped("body"))
        self.assertIn(picking.name, body)
        self.assertIn("Avisar", body)

        # El contador cuenta lo que ve (90), y al aplicar el supervisor decide
        for line, qty in ((screw, 90.0), (roller, 40.0)):
            line.write({"qty_counted": qty})
        for line in count.line_ids.filtered(lambda line: line.product_id == self.paint):
            line.write({"qty_counted": line.qty_theoretical})
        count.action_to_review()
        # 90 contra teórico 100 es −10 %: reconteo
        self.assertEqual(screw.state, "recount")
        screw.write({"qty_recount": 90.0})
        screw.action_approve()
        result = count.action_apply()
        self.assertEqual(result.get("tag"), "display_notification")
        self.assertEqual(count.state, "review")
        count.action_apply_force()
        self.assertEqual(count.state, "done")
        self.assertEqual(self._qty(self.screw, self.shelf), 90.0)
        self.assertFalse(count.move_ids, "el quant ya estaba en 90: no hace falta ajuste")

    # ------------------------------------------------------------------
    # Inventario físico nativo
    # ------------------------------------------------------------------
    def test_native_apply_is_blocked_on_taken_quant(self):
        count = self._create_count(scope="products", product_ids=[(6, 0, self.screw.ids)])
        count.action_confirm()
        quant = count.line_ids.quant_id
        self.assertEqual(quant.count_id, count)
        quant.inventory_quantity = 77.0
        with self.assertRaises(UserError) as err:
            quant.action_apply_inventory()
        self.assertIn(count.name, str(err.exception))
        self.assertEqual(self._qty(self.screw, self.shelf), 100.0)
        count.action_cancel()
        quant.inventory_quantity = 77.0
        quant.action_apply_inventory()
        self.assertEqual(self._qty(self.screw, self.shelf), 77.0)
