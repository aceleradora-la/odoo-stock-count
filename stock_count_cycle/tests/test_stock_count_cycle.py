from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestStockCountCycle(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
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
        cls.customers = cls.env.ref("stock.stock_location_customers")
        cls.shelf = cls.env["stock.location"].create(
            {"name": "Pasillo C1", "location_id": cls.stock.id, "usage": "internal"}
        )
        cls.other_shelf = cls.env["stock.location"].create(
            {"name": "Pasillo C2", "location_id": cls.stock.id, "usage": "internal"}
        )
        Product = cls.env["product.product"]
        cls.screw = Product.create(
            {"name": "Tornillo M8", "type": "consu", "is_storable": True, "standard_price": 35.0}
        )
        cls.roller = Product.create(
            {"name": "Rodillo 22", "type": "consu", "is_storable": True, "standard_price": 800.0}
        )
        Quant = cls.env["stock.quant"]
        Quant._update_available_quantity(cls.screw, cls.shelf, 100.0)
        Quant._update_available_quantity(cls.roller, cls.shelf, 40.0)
        Quant._update_available_quantity(cls.screw, cls.other_shelf, 500.0)
        base_user = cls.env.ref("base.group_user")
        cls.supervisor = cls.env["res.users"].create(
            {
                "name": "Ana Torres",
                "login": "ana.cycle",
                "email": "ana.cycle@example.com",
                "groups_id": [
                    (6, 0, [base_user.id, cls.env.ref("stock_count.group_stock_count_manager").id])
                ],
            }
        )
        cls.counter = cls.env["res.users"].create(
            {
                "name": "Luis Paz",
                "login": "luis.cycle",
                "email": "luis.cycle@example.com",
                "groups_id": [
                    (6, 0, [base_user.id, cls.env.ref("stock_count.group_stock_count_user").id])
                ],
            }
        )
        cls.Rule = cls.env["stock.count.rule"]
        cls.Count = cls.env["stock.count"]

    def _rule(self, **vals):
        base = {
            "name": "Regla de prueba",
            "rule_type": "periodic",
            "warehouse_id": self.warehouse.id,
            "location_ids": [(6, 0, (self.shelf | self.other_shelf).ids)],
            "include_children": False,
            "user_id": self.supervisor.id,
            "counter_ids": [(6, 0, self.counter.ids)],
            "lock_mode": "warn",
        }
        base.update(vals)
        return self.Rule.create(base)

    def _deliver(self, product, qty, src):
        move_vals = {
            "product_id": product.id,
            "product_uom_qty": qty,
            "product_uom": product.uom_id.id,
            "location_id": src.id,
            "location_dest_id": self.customers.id,
        }
        if "name" in self.env["stock.move"]._fields:
            move_vals["name"] = product.display_name
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.warehouse.out_type_id.id,
                "location_id": src.id,
                "location_dest_id": self.customers.id,
                "move_ids": [(0, 0, move_vals)],
            }
        )
        picking.action_confirm()
        picking.action_assign()
        picking.move_ids.picked = True
        picking.button_validate()
        self.assertEqual(picking.state, "done")
        return picking

    def _apply_count(self, locations, counted):
        """Aplica un recuento sobre las ubicaciones con las cantidades indicadas."""
        count = self.Count.create(
            {
                "warehouse_id": self.warehouse.id,
                "location_ids": [(6, 0, locations.ids)],
                "include_children": False,
                "user_id": self.supervisor.id,
            }
        )
        count.action_confirm()
        count.action_start()
        for line in count.line_ids:
            line.write({"qty_counted": counted.get(line.product_id, line.qty_theoretical)})
        count.action_to_review()
        for line in count.line_ids.filtered(lambda line: line.state == "recount"):
            line.write({"qty_recount": line.qty_counted})
        count.action_approve_all()
        count.action_apply()
        self.assertEqual(count.state, "done")
        return count

    # ------------------------------------------------------------------
    # Periódico
    # ------------------------------------------------------------------
    def test_periodic_creates_count_with_activity_once_per_period(self):
        rule = self._rule(period_days=7, planning_days=2)
        counts = rule._run()
        self.assertEqual(len(counts), 1)
        count = counts
        self.assertEqual(count.state, "draft", "sin auto-confirmar queda en borrador")
        self.assertEqual(count.rule_id, rule)
        self.assertEqual(count.location_ids, self.shelf | self.other_shelf)
        self.assertEqual(count.user_id, self.supervisor)
        self.assertEqual(count.counter_ids, self.counter)
        self.assertEqual(count.lock_mode, "warn")
        self.assertIn("periódico", count.origin)
        expected_date = fields.Date.context_today(rule) + timedelta(days=2)
        self.assertEqual(fields.Date.to_date(count.date_planned), expected_date)
        activity = count.activity_ids
        self.assertEqual(len(activity), 1)
        self.assertEqual(activity.user_id, self.supervisor)
        self.assertEqual(activity.date_deadline, expected_date)
        self.assertIn(count.name, activity.summary)
        self.assertEqual(rule.next_date, fields.Date.context_today(rule) + timedelta(days=7))
        self.assertTrue(rule.last_run)

        self.assertFalse(rule._run(), "el mismo día no vuelve a generar")
        rule.next_date = fields.Date.context_today(rule) - timedelta(days=1)
        self.assertEqual(len(rule._run()), 1, "vencida la fecha, genera otro")
        self.assertEqual(rule.count_count, 2)

    def test_periodic_auto_confirm_and_conflict_stays_draft(self):
        rule = self._rule(period_days=30, auto_confirm=True)
        count = rule._run()
        self.assertEqual(count.state, "ready", "confirmado: snapshot tomado")
        self.assertTrue(count.line_ids)
        # Otra regla sobre las mismas ubicaciones no puede confirmar: queda en borrador
        other = self._rule(name="Solapada", period_days=30, auto_confirm=True)
        conflict = other._run()
        self.assertEqual(conflict.state, "draft")
        body = " ".join(conflict.message_ids.mapped("body"))
        self.assertIn("No se pudo confirmar", body)
        self.assertIn(count.name, body)

    def test_run_now_button_and_view_counts(self):
        rule = self._rule(period_days=30)
        action = rule.action_run_now()
        self.assertEqual(action.get("res_model"), "stock.count")
        self.assertEqual(action.get("res_id"), rule.count_ids.id)
        again = rule.action_run_now()
        self.assertEqual(again.get("tag"), "display_notification")
        zero_rule = self._rule(name="Cero", rule_type="zero")
        with self.assertRaises(UserError):
            zero_rule.action_run_now()

    # ------------------------------------------------------------------
    # Rotación de valor
    # ------------------------------------------------------------------
    def test_turnover_rule_triggers_only_locations_over_threshold(self):
        rule = self._rule(name="Rotación", rule_type="turnover", turnover_threshold=1000.0)
        self._deliver(self.screw, 10.0, self.shelf)  # 350 de valor: no alcanza
        self.assertFalse(rule._run())
        self._deliver(self.roller, 2.0, self.shelf)  # +1600: supera
        counts = rule._run()
        self.assertEqual(len(counts), 1)
        self.assertEqual(counts.location_ids, self.shelf, "solo la ubicación que superó el umbral")
        self.assertFalse(counts.include_children)
        self.assertIn("Rotación", counts.origin)
        self.assertFalse(rule._run(), "enfriamiento: no repite")

    def test_turnover_resets_after_applied_count(self):
        rule = self._rule(
            name="Rotación", rule_type="turnover", turnover_threshold=1000.0, cooldown_days=0
        )
        self._deliver(self.roller, 2.0, self.shelf)  # 1600
        self.assertGreater(rule._turnover_value(self.shelf), 1000.0)
        self._apply_count(self.shelf, {})
        self.assertEqual(rule._turnover_value(self.shelf), 0.0, "desde el último recuento: nada")

    # ------------------------------------------------------------------
    # Precisión mínima
    # ------------------------------------------------------------------
    def test_accuracy_rule_triggers_when_location_below_threshold(self):
        rule = self._rule(name="Precisión", rule_type="accuracy", accuracy_threshold_pct=80.0)
        self.assertFalse(rule._run(), "sin historial no hay precisión que evaluar")
        # Pasillo C1: una línea con diferencia de dos → 50 %; Pasillo C2: 100 %
        self._apply_count(self.shelf, {self.screw: 98.0})
        self._apply_count(self.other_shelf, {})
        counts = rule._run()
        self.assertEqual(len(counts), 1)
        self.assertEqual(counts.location_ids, self.shelf)
        self.assertIn("Precisión", counts.origin)
        self.assertFalse(rule._run(), "enfriamiento")

    # ------------------------------------------------------------------
    # Confirmación de cero
    # ------------------------------------------------------------------
    def test_zero_confirmation_created_when_product_reaches_zero(self):
        rule = self._rule(
            name="Cero",
            rule_type="zero",
            location_ids=[(6, 0, self.shelf.ids)],
            auto_confirm=True,
        )
        self._deliver(self.roller, 10.0, self.shelf)
        self.assertFalse(rule.count_ids, "quedan 30: no dispara")
        self._deliver(self.screw, 100.0, self.shelf)
        self.assertEqual(len(rule.count_ids), 1)
        count = rule.count_ids
        self.assertEqual(count.scope, "products")
        self.assertEqual(count.product_ids, self.screw)
        self.assertEqual(count.location_ids, self.shelf)
        self.assertTrue(count.include_zero_quants)
        self.assertEqual(count.state, "ready")
        self.assertEqual(len(count.line_ids), 1)
        self.assertEqual(count.line_ids.qty_theoretical, 0.0)
        self.assertIn("Confirmación de cero", count.origin)
        self.assertTrue(count.activity_ids)
        # Otra ubicación fuera de la regla no dispara
        self._deliver(self.screw, 500.0, self.other_shelf)
        self.assertEqual(len(rule.count_ids), 1)

    def test_zero_confirmation_respects_scope_and_cooldown(self):
        rule = self._rule(
            name="Cero rodillos",
            rule_type="zero",
            location_ids=[(6, 0, self.shelf.ids)],
            scope="products",
            product_ids=[(6, 0, self.roller.ids)],
        )
        self._deliver(self.screw, 100.0, self.shelf)
        self.assertFalse(rule.count_ids, "el tornillo no está en el alcance")
        self._deliver(self.roller, 40.0, self.shelf)
        self.assertEqual(len(rule.count_ids), 1)
        self.assertEqual(rule.count_ids.state, "draft")
        # Vuelve a entrar y a salir: dentro del enfriamiento no repite
        self.env["stock.quant"]._update_available_quantity(self.roller, self.shelf, 5.0)
        self._deliver(self.roller, 5.0, self.shelf)
        self.assertEqual(len(rule.count_ids), 1)

    # ------------------------------------------------------------------
    # Cron
    # ------------------------------------------------------------------
    def test_cron_runs_all_active_rules_and_survives_errors(self):
        periodic = self._rule(name="Periódica", period_days=30)
        archived = self._rule(name="Archivada", period_days=30, active=False)
        turnover = self._rule(name="Rotación", rule_type="turnover", turnover_threshold=1.0)
        created = self.Rule._cron_generate_counts()
        self.assertEqual(len(created), 1, "solo la periódica tenía algo que generar")
        self.assertEqual(created.rule_id, periodic)
        self.assertFalse(archived.count_ids)
        self.assertFalse(turnover.count_ids, "sin movimientos no hay rotación")
        self.assertTrue(self.env.ref("stock_count_cycle.ir_cron_stock_count_cycle").active)
