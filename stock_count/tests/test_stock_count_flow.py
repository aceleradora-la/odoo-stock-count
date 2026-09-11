from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestStockCountFlow(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write(
            {
                "stock_count_lock_mode": "none",
                "stock_count_recount_threshold_pct": 5.0,
                "stock_count_recount_threshold_qty": 3.0,
                "stock_count_auto_approve_pct": 1.0,
            }
        )
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.company.id)], limit=1
        )
        cls.stock = cls.warehouse.lot_stock_id
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
        cls.tape = Product.create(
            {"name": "Cinta 50 mm", "type": "consu", "is_storable": True, "standard_price": 400.0}
        )
        cls.paint = Product.create(
            {
                "name": "Pintura 4 L",
                "type": "consu",
                "is_storable": True,
                "tracking": "lot",
                "standard_price": 12900.0,
            }
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

        cls.manager_group = cls.env.ref("stock_count.group_stock_count_manager")
        cls.counter_group = cls.env.ref("stock_count.group_stock_count_user")
        cls.counter = cls.env["res.users"].create(
            {
                "name": "Luis Paz",
                "login": "luis.paz",
                "group_ids": [(6, 0, [cls.env.ref("base.group_user").id, cls.counter_group.id])],
            }
        )
        cls.other_counter = cls.env["res.users"].create(
            {
                "name": "Marta Gil",
                "login": "marta.gil",
                "group_ids": [(6, 0, [cls.env.ref("base.group_user").id, cls.counter_group.id])],
            }
        )
        cls.Count = cls.env["stock.count"]

    def _create_count(self, **vals):
        base = {
            "warehouse_id": self.warehouse.id,
            "location_ids": [(6, 0, self.shelf.ids)],
            "include_children": False,
            "counter_ids": [(6, 0, [self.counter.id, self.other_counter.id])],
        }
        base.update(vals)
        return self.Count.create(base)

    def _qty(self, product, location, lot=None):
        return self.env["stock.quant"]._get_available_quantity(
            product, location, lot_id=lot, strict=True
        )

    def _line(self, count, product, lot=None):
        return count.line_ids.filtered(
            lambda line: (
                line.product_id == product and line.lot_id == (lot or line.lot_id.browse())
            )
        )

    # ------------------------------------------------------------------
    # Confirmar: snapshot
    # ------------------------------------------------------------------
    def test_confirm_generates_snapshot_lines(self):
        count = self._create_count()
        count.action_confirm()
        self.assertEqual(count.state, "ready")
        self.assertTrue(count.date_start)
        self.assertEqual(len(count.line_ids), 4, "una línea por quant del pasillo A")
        screw = self._line(count, self.screw)
        self.assertEqual(screw.qty_theoretical, 100.0)
        self.assertEqual(screw.state, "pending")
        self.assertEqual(screw.quant_id.count_line_id, screw, "el quant queda tomado")
        paint_b = self._line(count, self.paint, self.lot_b)
        self.assertEqual(paint_b.qty_theoretical, 12.0)
        self.assertEqual(paint_b.lot_id, self.lot_b)
        self.assertEqual(count.line_count, 4)
        self.assertEqual(count.pending_count, 4)
        self.assertEqual(count.progress, 0.0)

    def test_confirm_with_children_covers_sublocations(self):
        count = self._create_count(location_ids=[(6, 0, self.stock.ids)], include_children=True)
        count.action_confirm()
        locations = count.line_ids.mapped("location_id")
        self.assertIn(self.shelf, locations)
        self.assertIn(self.other_shelf, locations)

    def test_confirm_scope_products(self):
        count = self._create_count(scope="products", product_ids=[(6, 0, self.roller.ids)])
        count.action_confirm()
        self.assertEqual(count.line_ids.mapped("product_id"), self.roller)

    def test_confirm_scope_lots(self):
        count = self._create_count(scope="lots", lot_ids=[(6, 0, self.lot_a.ids)])
        count.action_confirm()
        self.assertEqual(len(count.line_ids), 1)
        self.assertEqual(count.line_ids.lot_id, self.lot_a)

    def test_confirm_requires_stock_or_zero_lines(self):
        count = self._create_count(scope="products", product_ids=[(6, 0, self.tape.ids)])
        with self.assertRaises(UserError):
            count.action_confirm()
        count.include_zero_quants = True
        count.action_confirm()
        line = count.line_ids
        self.assertEqual(len(line), 1)
        self.assertEqual(line.qty_theoretical, 0.0)
        self.assertFalse(line.quant_id)

    def test_confirm_rejects_overlapping_active_count(self):
        first = self._create_count()
        first.action_confirm()
        second = self._create_count()
        with self.assertRaises(UserError) as err:
            second.action_confirm()
        self.assertIn(first.name, str(err.exception))
        # Otra ubicación no molesta
        third = self._create_count(location_ids=[(6, 0, self.other_shelf.ids)])
        third.action_confirm()
        self.assertEqual(third.state, "ready")

    # ------------------------------------------------------------------
    # Contar
    # ------------------------------------------------------------------
    def test_counting_records_author_and_state(self):
        count = self._create_count()
        count.action_confirm()
        count.action_start()
        screw = self._line(count, self.screw)
        screw.with_user(self.counter).write({"qty_counted": 100.0})
        self.assertEqual(screw.state, "counted")
        self.assertEqual(screw.counted_by_id, self.counter)
        self.assertTrue(screw.counted_at)
        self.assertEqual(count.counted_count, 1)

    def test_counter_cannot_count_line_assigned_to_someone_else(self):
        count = self._create_count()
        count.action_confirm()
        count.action_start()
        screw = self._line(count, self.screw)
        screw.assigned_user_id = self.other_counter
        with self.assertRaises(UserError):
            screw.with_user(self.counter).write({"qty_counted": 99.0})
        screw.with_user(self.other_counter).write({"qty_counted": 99.0})
        self.assertEqual(screw.counted_by_id, self.other_counter)

    def test_cannot_count_when_not_active(self):
        count = self._create_count()
        count.action_confirm()
        line = count.line_ids[0]
        count.action_cancel()
        with self.assertRaises(UserError):
            line.write({"qty_counted": 1.0})

    # ------------------------------------------------------------------
    # Revisión, reconteo, aplicación
    # ------------------------------------------------------------------
    def _count_all(self, count, values):
        for product, lot, qty in values:
            self._line(count, product, lot).write({"qty_counted": qty})

    def test_full_flow_with_recount_and_apply(self):
        count = self._create_count()
        count.action_confirm()
        count.action_start()
        with self.assertRaises(UserError, msg="no se puede revisar con líneas pendientes"):
            count.action_to_review()
        self._count_all(
            count,
            [
                (self.screw, None, 100.0),  # sin diferencia
                (self.roller, None, 52.0),  # +30 % → reconteo
                (self.paint, self.lot_a, 36.0),  # sin diferencia
                (self.paint, self.lot_b, 9.0),  # −25 % → reconteo
            ],
        )
        self.assertFalse(count.has_recount, "sin reconteos no se muestran sus columnas")
        count.action_to_review()
        self.assertEqual(count.state, "review")
        screw = self._line(count, self.screw)
        roller = self._line(count, self.roller)
        paint_b = self._line(count, self.paint, self.lot_b)
        self.assertEqual(screw.state, "approved")
        self.assertEqual(roller.state, "recount")
        self.assertEqual(paint_b.state, "recount")
        self.assertTrue(count.has_recount, "con reconteos pedidos, aparecen las columnas")

        with self.assertRaises(UserError, msg="no se aplica con reconteos pendientes"):
            count.action_apply()

        roller.with_user(self.other_counter).write({"qty_recount": 41.0})
        self.assertEqual(roller.state, "counted")
        self.assertEqual(roller.recounted_by_id, self.other_counter)
        self.assertEqual(roller.qty_final, 41.0, "el segundo conteo manda")
        self.assertEqual(roller.qty_diff, 1.0)
        paint_b.write({"qty_recount": 9.0})
        paint_b.reason_id = self.env.ref("stock_count.reason_breakage")

        count.action_approve_all()
        self.assertTrue(all(line.state == "approved" for line in count.line_ids))

        count.action_apply()
        self.assertEqual(count.state, "done")
        self.assertTrue(count.date_end)
        self.assertTrue(all(line.state == "applied" for line in count.line_ids))
        self.assertEqual(self._qty(self.roller, self.shelf), 41.0)
        self.assertEqual(self._qty(self.paint, self.shelf, self.lot_b), 9.0)
        self.assertEqual(self._qty(self.screw, self.shelf), 100.0)

        self.assertEqual(len(count.move_ids), 2, "solo las líneas con diferencia generan ajuste")
        self.assertTrue(all(move.is_inventory for move in count.move_ids))
        self.assertTrue(all(move.state == "done" for move in count.move_ids))
        self.assertTrue(all(count.name in move.reference for move in count.move_ids))
        self.assertEqual(roller.move_line_ids.move_id.count_id, count)
        self.assertEqual(roller.move_line_ids.quantity, 1.0)
        self.assertEqual(paint_b.move_line_ids.lot_id, self.lot_b)
        self.assertFalse(screw.move_line_ids)
        self.assertFalse(
            count.line_ids.quant_id.filtered("count_line_id"), "los quants se liberan al aplicar"
        )
        self.assertEqual(count.diff_count, 2)
        self.assertAlmostEqual(count.diff_value, 1 * 800.0 - 3 * 12900.0)
        self.assertAlmostEqual(count.accuracy, 50.0)

    def test_within_tolerance_is_auto_approved(self):
        count = self._create_count(auto_approve_tolerance_pct=1.0)
        count.action_confirm()
        count.action_start()
        self._count_all(
            count,
            [
                (self.screw, None, 99.5),  # −0,5 % → dentro de tolerancia
                (self.roller, None, 40.0),
                (self.paint, self.lot_a, 36.0),
                (self.paint, self.lot_b, 12.0),
            ],
        )
        count.action_to_review()
        self.assertEqual(self._line(count, self.screw).state, "approved")

    def test_tolerance_100_approves_everything_including_zero_theoretical(self):
        count = self._create_count(
            scope="products",
            product_ids=[(6, 0, (self.screw | self.tape).ids)],
            include_zero_quants=True,
            auto_approve_tolerance_pct=100.0,
        )
        count.action_confirm()
        count.action_start()
        self._line(count, self.screw).write({"qty_counted": 60.0})  # −40 %
        self._line(count, self.tape).write({"qty_counted": 7.0})  # teórico cero
        count.action_to_review()
        self.assertTrue(
            all(line.state == "approved" for line in count.line_ids),
            "con 100 % no queda nada esperando aprobación",
        )
        count.action_apply()
        self.assertEqual(count.state, "done")
        self.assertEqual(self._qty(self.tape, self.shelf), 7.0)

    def test_warehouse_change_drops_foreign_locations(self):
        other_wh = self.env["stock.warehouse"].create(
            {"name": "Depósito Sur", "code": "SUR", "company_id": self.company.id}
        )
        count = self._create_count()
        self.assertEqual(count.location_ids, self.shelf)
        count.warehouse_id = other_wh
        count._onchange_warehouse_id()
        self.assertFalse(count.location_ids, "el pasillo A no es del depósito Sur")
        in_scope = self.env["stock.location"].search(
            [("usage", "=", "internal"), ("warehouse_id", "=", other_wh.id)]
        )
        self.assertNotIn(self.shelf, in_scope)

    def test_diff_between_tolerance_and_threshold_waits_for_supervisor(self):
        count = self._create_count(recount_threshold_qty=10.0, recount_threshold_pct=5.0)
        count.action_confirm()
        count.action_start()
        self._count_all(
            count,
            [
                (self.screw, None, 97.0),  # −3 %: ni tolerable ni reconteo
                (self.roller, None, 40.0),
                (self.paint, self.lot_a, 36.0),
                (self.paint, self.lot_b, 12.0),
            ],
        )
        count.action_to_review()
        screw = self._line(count, self.screw)
        self.assertEqual(screw.state, "counted")
        with self.assertRaises(UserError):
            count.action_apply()
        screw.action_approve()
        count.action_apply()
        self.assertEqual(self._qty(self.screw, self.shelf), 97.0)

    def test_skip_line(self):
        count = self._create_count()
        count.action_confirm()
        count.action_start()
        self._line(count, self.roller).action_skip()
        self._count_all(
            count,
            [
                (self.screw, None, 100.0),
                (self.paint, self.lot_a, 36.0),
                (self.paint, self.lot_b, 12.0),
            ],
        )
        count.action_to_review()
        count.action_apply()
        self.assertEqual(count.state, "done")
        self.assertEqual(self._line(count, self.roller).state, "skipped")
        self.assertEqual(self._qty(self.roller, self.shelf), 40.0)
        self.assertFalse(count.move_ids)

    def test_moved_during_count_requires_explicit_decision(self):
        count = self._create_count()
        count.action_confirm()
        count.action_start()
        # Sale stock del pasillo entre el snapshot y la aplicación
        self.env["stock.quant"]._update_available_quantity(self.screw, self.shelf, -10.0)
        self._count_all(
            count,
            [
                (self.screw, None, 100.0),
                (self.roller, None, 40.0),
                (self.paint, self.lot_a, 36.0),
                (self.paint, self.lot_b, 12.0),
            ],
        )
        count.action_to_review()
        screw = self._line(count, self.screw)
        self.assertEqual(screw.qty_current, 90.0)
        result = count.action_apply()
        self.assertEqual(result.get("tag"), "display_notification")
        self.assertIn("se movió", result["params"]["message"])
        self.assertEqual(count.state, "review", "no se aplica hasta decidir")
        self.assertTrue(screw.moved_during_count)
        self.assertEqual(count.moved_count, 1)
        count.action_apply_force()
        self.assertEqual(count.state, "done")
        self.assertEqual(
            self._qty(self.screw, self.shelf), 100.0, "el contado es la cantidad final"
        )
        self.assertEqual(len(count.move_ids), 1)

    def test_zero_line_creates_quant_and_move(self):
        count = self._create_count(
            scope="products", product_ids=[(6, 0, self.tape.ids)], include_zero_quants=True
        )
        count.action_confirm()
        count.action_start()
        line = count.line_ids
        line.write({"qty_counted": 6.0})
        line.reason_id = self.env.ref("stock_count.reason_unexpected")
        count.action_to_review()
        self.assertEqual(line.state, "recount", "6 unidades superan el umbral de 3")
        line.write({"qty_recount": 6.0})
        self.assertEqual(line.state, "counted")
        line.action_approve()
        count.action_apply()
        self.assertEqual(self._qty(self.tape, self.shelf), 6.0)
        self.assertEqual(line.move_line_ids.quantity, 6.0)
        self.assertEqual(line.move_line_ids.location_dest_id, self.shelf)

    def test_reason_with_loss_location_redirects_negative_adjustment(self):
        scrap = self.env["stock.location"].create(
            {"name": "Roturas", "usage": "inventory", "location_id": self.stock.location_id.id}
        )
        reason = self.env["stock.count.reason"].create(
            {"name": "Rotura a scrap", "location_dest_id": scrap.id}
        )
        count = self._create_count(scope="products", product_ids=[(6, 0, self.roller.ids)])
        count.action_confirm()
        count.action_start()
        line = count.line_ids
        line.write({"qty_counted": 38.0})
        line.reason_id = reason
        count.action_to_review()
        line.action_approve()
        count.action_apply()
        move = count.move_ids
        self.assertEqual(move.location_dest_id, scrap)
        self.assertEqual(move.product_uom_qty, 2.0)
        self.assertEqual(self._qty(self.roller, self.shelf), 38.0)

    # ------------------------------------------------------------------
    # Cancelar / borrador
    # ------------------------------------------------------------------
    def test_cancel_releases_quants(self):
        count = self._create_count()
        count.action_confirm()
        quants = count.line_ids.quant_id
        self.assertTrue(all(quants.mapped("count_line_id")))
        count.action_cancel()
        self.assertEqual(count.state, "cancel")
        self.assertFalse(any(quants.mapped("count_line_id")))
        # Y ahora otro recuento sobre el mismo pasillo sí puede confirmarse
        again = self._create_count()
        again.action_confirm()
        self.assertEqual(again.state, "ready")

    def test_back_to_draft_discards_lines(self):
        count = self._create_count()
        count.action_confirm()
        count.action_draft()
        self.assertEqual(count.state, "draft")
        self.assertFalse(count.line_ids)
        self.assertFalse(count.date_start)

    def test_done_count_cannot_be_cancelled(self):
        count = self._create_count(scope="products", product_ids=[(6, 0, self.roller.ids)])
        count.action_confirm()
        count.action_start()
        count.line_ids.write({"qty_counted": 40.0})
        count.action_to_review()
        count.action_apply()
        with self.assertRaises(UserError):
            count.action_cancel()
        with self.assertRaises(UserError):
            count.action_draft()
