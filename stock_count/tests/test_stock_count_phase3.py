from odoo.exceptions import AccessError, UserError
from odoo.tests import HttpCase, TransactionCase, tagged


class Phase3Common:
    @classmethod
    def _setup_phase3(cls):
        cls.company = cls.env.company
        cls.company.write(
            {
                "stock_count_lock_mode": "none",
                "stock_count_blind": False,
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
            {
                "name": "Pasillo A",
                "location_id": cls.stock.id,
                "usage": "internal",
                "barcode": "LOC-A",
            }
        )
        cls.other_shelf = cls.env["stock.location"].create(
            {
                "name": "Pasillo B",
                "location_id": cls.stock.id,
                "usage": "internal",
                "barcode": "LOC-B",
            }
        )
        Product = cls.env["product.product"]
        cls.screw = Product.create(
            {
                "name": "Tornillo M8",
                "type": "consu",
                "is_storable": True,
                "standard_price": 35.0,
                "barcode": "7790001",
            }
        )
        cls.roller = Product.create(
            {"name": "Rodillo 22", "type": "consu", "is_storable": True, "standard_price": 800.0}
        )
        cls.tape = Product.create(
            {"name": "Cinta 50 mm", "type": "consu", "is_storable": True, "standard_price": 400.0}
        )
        cls.paint = Product.create(
            {"name": "Pintura 4 L", "type": "consu", "is_storable": True, "tracking": "lot"}
        )
        cls.lot_a = cls.env["stock.lot"].create(
            {"name": "L-240811", "product_id": cls.paint.id, "company_id": cls.company.id}
        )
        Quant = cls.env["stock.quant"]
        Quant._update_available_quantity(cls.screw, cls.shelf, 100.0)
        Quant._update_available_quantity(cls.roller, cls.shelf, 40.0)
        Quant._update_available_quantity(cls.paint, cls.shelf, 36.0, lot_id=cls.lot_a)
        Quant._update_available_quantity(cls.screw, cls.other_shelf, 500.0)
        cls.counter_group = cls.env.ref("stock_count.group_stock_count_user")
        cls.manager_group = cls.env.ref("stock_count.group_stock_count_manager")
        base_user = cls.env.ref("base.group_user")
        cls.counter = cls.env["res.users"].create(
            {
                "name": "Luis Paz",
                "login": "luis.paz",
                "groups_id": [(6, 0, [base_user.id, cls.counter_group.id])],
            }
        )
        cls.other_counter = cls.env["res.users"].create(
            {
                "name": "Marta Gil",
                "login": "marta.gil",
                "groups_id": [(6, 0, [base_user.id, cls.counter_group.id])],
            }
        )
        cls.supervisor = cls.env["res.users"].create(
            {
                "name": "Ana Torres",
                "login": "ana.torres",
                "groups_id": [(6, 0, [base_user.id, cls.manager_group.id])],
            }
        )
        cls.Count = cls.env["stock.count"]
        cls.Line = cls.env["stock.count.line"]

    def _create_count(self, **vals):
        base = {
            "warehouse_id": self.warehouse.id,
            "location_ids": [(6, 0, self.shelf.ids)],
            "include_children": False,
            "user_id": self.supervisor.id,
            "counter_ids": [(6, 0, [self.counter.id, self.other_counter.id])],
        }
        base.update(vals)
        return self.Count.create(base)

    def _line(self, count, product, lot=None):
        return count.line_ids.filtered(
            lambda line: line.product_id == product and (lot is None or line.lot_id == lot)
        )


@tagged("post_install", "-at_install")
class TestStockCountPhase3(Phase3Common, TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_phase3()

    # ------------------------------------------------------------------
    # Conteo ciego forzado por el ORM
    # ------------------------------------------------------------------
    def test_blind_hides_theoretical_from_counter_but_not_from_manager(self):
        self.company.stock_count_blind = True
        count = self._create_count()
        count.action_confirm()
        count.action_start()
        screw = self._line(count, self.screw)
        screw.write({"qty_counted": 90.0})
        as_counter = screw.with_user(self.counter)

        data = as_counter.read(
            ["qty_theoretical", "qty_diff", "diff_pct", "diff_value", "qty_counted"]
        )[0]
        self.assertEqual(data["qty_theoretical"], 0.0)
        self.assertEqual(data["qty_diff"], 0.0)
        self.assertEqual(data["diff_value"], 0.0)
        self.assertEqual(data["qty_counted"], 90.0, "lo que él contó sí lo ve")
        searched = self.Line.with_user(self.counter).search_read(
            [("id", "=", screw.id)], ["qty_theoretical"]
        )
        self.assertEqual(searched[0]["qty_theoretical"], 0.0)
        count_data = count.with_user(self.counter).read(["diff_value", "accuracy", "line_count"])[
            0
        ]
        self.assertEqual(count_data["diff_value"], 0)
        self.assertEqual(count_data["line_count"], 3, "los totales neutros sí")

        as_manager = screw.with_user(self.supervisor).read(["qty_theoretical", "qty_diff"])[0]
        self.assertEqual(as_manager["qty_theoretical"], 100.0)
        self.assertEqual(as_manager["qty_diff"], -10.0)

        self.company.stock_count_blind = False
        visible = as_counter.read(["qty_theoretical"])[0]
        self.assertEqual(visible["qty_theoretical"], 100.0, "sin ciego, el contador ve el teórico")

    def test_blind_blocks_export_search_and_group_by(self):
        self.company.stock_count_blind = True
        count = self._create_count()
        count.action_confirm()
        count.action_start()
        lines = count.line_ids.with_user(self.counter)
        with self.assertRaises(AccessError):
            lines.export_data(["product_id", "qty_theoretical"])
        with self.assertRaises(AccessError):
            self.Line.with_user(self.counter).search([("qty_theoretical", ">", 50)])
        with self.assertRaises(AccessError):
            self.Line.with_user(self.counter)._read_group(
                [("count_id", "=", count.id)], ["location_id"], ["qty_theoretical:sum"]
            )
        # El supervisor no tiene restricciones
        lines.with_user(self.supervisor).export_data(["product_id", "qty_theoretical"])
        found = self.Line.with_user(self.supervisor).search([("qty_theoretical", ">", 50)])
        self.assertIn(self._line(count, self.screw), found)

    def test_blind_hides_taken_quants_from_counter(self):
        self.company.stock_count_blind = True
        count = self._create_count(scope="products", product_ids=[(6, 0, self.screw.ids)])
        count.action_confirm()
        Quant = self.env["stock.quant"].with_user(self.counter)
        domain = [("product_id", "=", self.screw.id), ("location_id", "=", self.shelf.id)]
        self.assertFalse(Quant.search(domain), "el quant tomado por un recuento ciego no se ve")
        other = [("product_id", "=", self.screw.id), ("location_id", "=", self.other_shelf.id)]
        self.assertTrue(Quant.search(other), "los demás quants sí")
        self.assertTrue(self.env["stock.quant"].with_user(self.supervisor).search(domain))
        count.action_cancel()
        self.assertTrue(Quant.search(domain), "al liberar el quant vuelve a verse")

    def test_counter_can_only_write_counting_fields(self):
        count = self._create_count()
        count.action_confirm()
        count.action_start()
        screw = self._line(count, self.screw).with_user(self.counter)
        screw.write(
            {
                "qty_counted": 99.0,
                "note": "faltan 1",
                "reason_id": self.env.ref("stock_count.reason_missing").id,
            }
        )
        with self.assertRaises(AccessError):
            screw.write({"state": "approved"})
        with self.assertRaises(AccessError):
            screw.write({"qty_theoretical": 5.0})
        with self.assertRaises(AccessError):
            screw.write({"assigned_user_id": self.counter.id})

    # ------------------------------------------------------------------
    # Reparto de líneas
    # ------------------------------------------------------------------
    def _assign(self, count, users, **vals):
        wizard_vals = {
            "count_id": count.id,
            "user_ids": [(6, 0, [user.id for user in users])],
        }
        wizard_vals.update(vals)
        wizard = self.env["stock.count.assign"].with_user(self.supervisor).create(wizard_vals)
        wizard.action_assign()
        return wizard

    def test_assign_by_location_keeps_each_location_with_one_counter(self):
        count = self._create_count(location_ids=[(6, 0, (self.shelf | self.other_shelf).ids)])
        count.action_confirm()
        # Pasillo A: 3 líneas, Pasillo B: 1 línea
        self._assign(count, [self.counter, self.other_counter], mode="location")
        by_location = {}
        for line in count.line_ids:
            by_location.setdefault(line.location_id, set()).add(line.assigned_user_id)
        for location, users in by_location.items():
            self.assertEqual(len(users), 1, f"{location.name} debe tener un solo contador")
        self.assertTrue(all(count.line_ids.mapped("assigned_user_id")))
        assigned_users = set(count.line_ids.mapped("assigned_user_id"))
        self.assertEqual(assigned_users, {self.counter, self.other_counter})
        # El primero de la lista se lleva la ubicación más grande (primera alfabéticamente)
        self.assertEqual(self._line(count, self.roller).assigned_user_id, self.counter)
        body = " ".join(count.message_ids.mapped("body"))
        self.assertIn("Líneas repartidas", body)

    def test_assign_balanced_and_only_unassigned(self):
        count = self._create_count()
        count.action_confirm()
        screw = self._line(count, self.screw)
        screw.assigned_user_id = self.other_counter
        self._assign(count, [self.counter], mode="balanced", only_unassigned=True)
        self.assertEqual(screw.assigned_user_id, self.other_counter, "ya asignada: no se toca")
        others = count.line_ids - screw
        self.assertTrue(all(line.assigned_user_id == self.counter for line in others))
        # Reasignar todo, salvo lo ya contado
        self._line(count, self.roller).write({"qty_counted": 40.0})
        self._assign(count, [self.other_counter], mode="balanced", only_unassigned=False)
        self.assertEqual(
            self._line(count, self.roller).assigned_user_id, self.counter, "contada: no se toca"
        )
        self.assertEqual(self._line(count, self.paint).assigned_user_id, self.other_counter)

    def test_assign_adds_missing_counter_to_count(self):
        count = self._create_count(counter_ids=[(6, 0, self.counter.ids)])
        count.action_confirm()
        self._assign(count, [self.other_counter])
        self.assertIn(self.other_counter, count.counter_ids)

    # ------------------------------------------------------------------
    # Producto no esperado
    # ------------------------------------------------------------------
    def _add_product(self, count, product, qty, user=None, **vals):
        wizard_vals = {
            "count_id": count.id,
            "location_id": self.shelf.id,
            "product_id": product.id,
            "qty_counted": qty,
        }
        wizard_vals.update(vals)
        Wizard = self.env["stock.count.add.product"].with_user(user or self.supervisor)
        wizard = Wizard.create(wizard_vals)
        wizard.action_add()
        return wizard

    def test_add_unexpected_product_without_stock(self):
        count = self._create_count()
        count.action_confirm()
        count.action_start()
        self._add_product(count, self.tape, 6.0, user=self.counter)
        line = self._line(count, self.tape)
        self.assertEqual(len(line), 1)
        self.assertEqual(line.qty_theoretical, 0.0)
        self.assertFalse(line.quant_id)
        self.assertEqual(line.qty_counted, 6.0)
        self.assertEqual(line.state, "counted")
        self.assertEqual(line.counted_by_id, self.counter)
        self.assertEqual(line.assigned_user_id, self.counter)
        self.assertEqual(line.reason_id, self.env.ref("stock_count.reason_unexpected"))
        with self.assertRaises(UserError, msg="no se agrega dos veces"):
            self._add_product(count, self.tape, 1.0, user=self.counter)

        for line_ in count.line_ids - line:
            line_.write({"qty_counted": line_.qty_theoretical})
        count.action_to_review()
        # 6 unidades sobre teórico 0 superan el umbral por unidades → reconteo
        self.assertEqual(line.state, "recount")
        line.write({"qty_recount": 6.0})
        line.action_approve()
        count.action_apply()
        quants = self.env["stock.quant"]._gather(self.tape, self.shelf, strict=True)
        self.assertEqual(sum(quants.mapped("quantity")), 6.0)

    def test_add_product_with_existing_quant_outside_scope(self):
        count = self._create_count(scope="products", product_ids=[(6, 0, self.screw.ids)])
        count.action_confirm()
        count.action_start()
        self._add_product(count, self.roller, 38.0)
        line = self._line(count, self.roller)
        self.assertEqual(line.qty_theoretical, 0.0, "no estaba previsto: teórico cero")
        self.assertTrue(line.quant_id, "pero el quant existente queda enlazado y tomado")
        self.assertEqual(line.quant_id.count_line_id, line)
        line.write({"qty_counted": 38.0})
        self._line(count, self.screw).write({"qty_counted": 100.0})
        count.action_to_review()
        for line_ in count.line_ids.filtered(lambda line: line.state == "recount"):
            line_.write({"qty_recount": line_.qty_counted})
        count.action_approve_all()
        count.action_apply()
        quants = self.env["stock.quant"]._gather(self.roller, self.shelf, strict=True)
        self.assertEqual(sum(quants.mapped("quantity")), 38.0, "el contado es absoluto: 40 → 38")

    def test_add_product_rejects_location_outside_count_and_missing_lot(self):
        count = self._create_count()
        count.action_confirm()
        with self.assertRaises(UserError):
            self._add_product(count, self.tape, 1.0, location_id=self.other_shelf.id)
        with self.assertRaises(UserError):
            self._add_product(count, self.paint, 1.0)

    # ------------------------------------------------------------------
    # Datos para la vista móvil
    # ------------------------------------------------------------------
    def test_counter_get_data_and_set_quantity(self):
        count = self._create_count()
        count.action_confirm()
        count.action_start()
        self._line(count, self.screw).assigned_user_id = self.counter
        self._line(count, self.paint).assigned_user_id = self.other_counter
        Line = self.Line.with_user(self.counter)
        data = Line.counter_get_data()
        self.assertEqual([c["id"] for c in data["counts"]], [count.id])
        products = {line["product_name"] for line in data["lines"]}
        self.assertEqual(products, {self.screw.display_name, self.roller.display_name})
        screw_data = next(line for line in data["lines"] if line["product_id"] == self.screw.id)
        self.assertEqual(screw_data["location_barcode"], "LOC-A")
        self.assertEqual(screw_data["product_barcode"], "7790001")
        self.assertFalse(screw_data["done"])
        self.assertNotIn("qty_theoretical", screw_data)

        updated = Line.browse(screw_data["id"]).counter_set_quantity(98.0)
        self.assertTrue(updated["done"])
        self.assertEqual(updated["quantity"], 98.0)
        updated = Line.browse(screw_data["id"]).counter_add_quantity(1.0)
        self.assertEqual(updated["quantity"], 99.0)
        self.assertEqual(self._line(count, self.screw).counted_by_id, self.counter)

        with self.assertRaises(AccessError, msg="la línea de Marta no es visible para Luis"):
            Line.browse(self._line(count, self.paint).id).counter_set_quantity(1.0)

        # En revisión, solo las líneas en reconteo vuelven a aparecer
        for line in count.line_ids.filtered(lambda line: line.state == "pending"):
            line.write({"qty_counted": line.qty_theoretical})
        self._line(count, self.screw).write({"qty_counted": 80.0})  # −20 % → reconteo
        count.action_to_review()
        data = Line.counter_get_data()
        self.assertEqual(len(data["lines"]), 1)
        self.assertTrue(data["lines"][0]["is_recount"])
        updated = Line.browse(data["lines"][0]["id"]).counter_set_quantity(81.0)
        self.assertEqual(self._line(count, self.screw).qty_recount, 81.0)
        self.assertEqual(self._line(count, self.screw).state, "counted")


@tagged("post_install", "-at_install")
class TestStockCountCounterTour(Phase3Common, HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_phase3()

    def test_counter_tour(self):
        admin = self.env.ref("base.user_admin")
        count = self._create_count(counter_ids=[(6, 0, admin.ids)], user_id=admin.id)
        count.action_confirm()
        count.action_start()
        self.start_tour(
            "/odoo/action-stock_count.action_stock_count_counter",
            "stock_count_counter_tour",
            login="admin",
        )
        self.assertTrue(count.line_ids.filtered(lambda line: line.state == "counted"))
