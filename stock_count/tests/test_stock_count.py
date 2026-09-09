from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestStockCount(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.company.id)], limit=1
        )
        cls.location = cls.warehouse.lot_stock_id
        cls.product = cls.env["product.product"].create(
            {
                "name": "Tornillo M8 x 50",
                "detailed_type": "product",
                "standard_price": 35.0,
            }
        )
        cls.Count = cls.env["stock.count"]

    def _create_count(self, **vals):
        base = {
            "warehouse_id": self.warehouse.id,
            "location_ids": [(6, 0, self.location.ids)],
        }
        base.update(vals)
        return self.Count.create(base)

    def test_sequence_and_company_defaults(self):
        self.company.write(
            {
                "stock_count_lock_mode": "warn",
                "stock_count_blind": True,
                "stock_count_recount_threshold_pct": 7.5,
            }
        )
        count = self._create_count()
        self.assertTrue(count.name.startswith("RC/"), count.name)
        self.assertEqual(count.state, "draft")
        self.assertEqual(count.lock_mode, "warn")
        self.assertTrue(count.blind, "El conteo ciego viene de la compañía")
        self.assertEqual(count.recount_threshold_pct, 7.5)
        self.assertEqual(count.user_id, self.env.user)

    def test_blind_is_not_editable_per_count(self):
        count = self._create_count()
        self.assertTrue(
            count._fields["blind"].related,
            "Conteo ciego es un campo relacionado a la compañía, no propio del recuento",
        )

    def test_line_diff_and_stats(self):
        count = self._create_count()
        Line = self.env["stock.count.line"]
        line_ok = Line.create(
            {
                "count_id": count.id,
                "product_id": self.product.id,
                "location_id": self.location.id,
                "qty_theoretical": 100.0,
                "qty_counted": 100.0,
                "state": "counted",
            }
        )
        line_diff = Line.create(
            {
                "count_id": count.id,
                "product_id": self.product.id,
                "location_id": self.location.id,
                "qty_theoretical": 40.0,
                "qty_counted": 52.0,
                "state": "counted",
            }
        )
        line_pending = Line.create(
            {
                "count_id": count.id,
                "product_id": self.product.id,
                "location_id": self.location.id,
                "qty_theoretical": 10.0,
            }
        )
        self.assertEqual(line_ok.qty_diff, 0.0)
        self.assertEqual(line_diff.qty_diff, 12.0)
        self.assertAlmostEqual(line_diff.diff_pct, 30.0)
        self.assertAlmostEqual(line_diff.diff_value, 12.0 * 35.0)
        self.assertEqual(line_pending.qty_diff, 0.0, "Una línea pendiente no tiene diferencia")

        self.assertEqual(count.line_count, 3)
        self.assertEqual(count.counted_count, 2)
        self.assertEqual(count.diff_count, 1)
        self.assertAlmostEqual(count.diff_value, 420.0)
        self.assertAlmostEqual(count.accuracy, 50.0)
        self.assertAlmostEqual(count.progress, 100.0 * 2 / 3)

    def test_recount_overrides_first_count(self):
        count = self._create_count()
        line = self.env["stock.count.line"].create(
            {
                "count_id": count.id,
                "product_id": self.product.id,
                "location_id": self.location.id,
                "qty_theoretical": 40.0,
                "qty_counted": 52.0,
                "state": "counted",
            }
        )
        self.assertEqual(line.qty_final, 52.0)
        line.write({"qty_recount": 41.0, "recounted_at": "2026-09-12 10:00:00"})
        self.assertEqual(line.qty_final, 41.0)
        self.assertEqual(line.qty_diff, 1.0)

    def test_unlink_only_draft_or_cancel(self):
        count = self._create_count()
        count.state = "done"
        with self.assertRaises(UserError):
            count.unlink()
        count.state = "cancel"
        count.unlink()
