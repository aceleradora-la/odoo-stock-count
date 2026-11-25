from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from .test_stock_count_phase3 import Phase3Common


@tagged("post_install", "-at_install")
class TestStockCountReviewFixes(Phase3Common, TransactionCase):
    """Arreglos de la revisión de noviembre de 2026."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_phase3()

    def _qty(self, product, location, lot=None):
        quants = self.env["stock.quant"]._gather(product, location, lot_id=lot, strict=True)
        return sum(quants.mapped("quantity"))

    # ------------------------------------------------------------------
    # Terminar
    # ------------------------------------------------------------------
    def test_finish_does_not_zero_locations_of_other_counters(self):
        count = self._create_count(location_ids=[(6, 0, (self.shelf | self.other_shelf).ids)])
        count.action_confirm()
        Line = self.Line.with_user(self.counter)
        screw_here = count.line_ids.filtered(
            lambda line: line.product_id == self.screw and line.location_id == self.shelf
        )
        Line.browse(screw_here.id).counter_set_quantity(100.0)
        probe = Line.counter_finish(count.id, False, False)
        self.assertEqual(probe["pending"], 2, "solo lo del pasillo donde contó")
        result = Line.counter_finish(count.id, False, True)
        self.assertEqual(result["zeroed"], 2)
        self.assertEqual(result["remaining"], 1, "el pasillo B queda para el otro contador")
        other = count.line_ids.filtered(lambda line: line.location_id == self.other_shelf)
        self.assertEqual(other.state, "pending")
        self.assertEqual(count.state, "counting")

    def test_zero_filled_lines_never_auto_approve(self):
        count = self._create_count(
            auto_approve_tolerance_pct=100.0, recount_threshold_pct=0.0, recount_threshold_qty=0.0
        )
        count.action_confirm()
        Line = self.Line.with_user(self.counter)
        Line.browse(self._line(count, self.screw).id).counter_set_quantity(100.0)
        Line.counter_finish(count.id, False, True)
        roller = self._line(count, self.roller)
        paint = self._line(count, self.paint)
        self.assertTrue(roller.zero_filled)
        self.assertEqual(
            roller.state, "counted", "tolerancia 100 % no alcanza a un cierre en cero"
        )
        self.assertEqual(count.state, "review", "no se validó solo")
        self.assertEqual(self._qty(self.roller, self.shelf), 40.0, "el stock sigue intacto")
        # Una cantidad cargada a mano deja de ser un cierre en cero
        count.with_user(self.supervisor).line_ids.filtered(
            lambda line: line.product_id == self.roller
        ).action_request_recount()
        self.assertEqual(roller.state, "recount", "pedir reconteo no lo da por recontado")
        self.assertFalse(roller.recounted_at)
        Line.browse(roller.id).counter_set_quantity(39.0)
        self.assertFalse(roller.zero_filled)
        self.assertEqual(roller.state, "approved", "contada a mano: vale la tolerancia")
        paint.with_user(self.supervisor).action_approve()
        self.assertEqual(count.state, "done")
        self.assertEqual(self._qty(self.roller, self.shelf), 39.0)
        self.assertEqual(self._qty(self.paint, self.shelf, self.lot_a), 0.0)

    # ------------------------------------------------------------------
    # Series
    # ------------------------------------------------------------------
    def test_serial_line_is_zero_or_one(self):
        phone = self.env["product.product"].create(
            {"name": "Lector", "type": "consu", "is_storable": True, "tracking": "serial"}
        )
        serial = self.env["stock.lot"].create(
            {"name": "SN-001", "product_id": phone.id, "company_id": self.company.id}
        )
        self.env["stock.quant"]._update_available_quantity(phone, self.shelf, 1.0, lot_id=serial)
        count = self._create_count(
            scope="products", product_ids=[(6, 0, (phone | self.roller).ids)]
        )
        count.action_confirm()
        count.action_start()
        line = self._line(count, phone)
        self.assertTrue(line.sudo()._counter_line_data()["is_serial"])
        with self.assertRaises(UserError):
            line.write({"qty_counted": 2.0})
        as_counter = self.Line.with_user(self.counter).browse(line.id)
        first = as_counter.counter_add_quantity(1.0)
        self.assertEqual(first["quantity"], 1.0)
        self.assertFalse(first.get("serial_already"))
        second = as_counter.counter_add_quantity(1.0)
        self.assertTrue(second["serial_already"], "escanear dos veces no suma")
        self.assertEqual(line.qty_counted, 1.0)

    # ------------------------------------------------------------------
    # Valor congelado
    # ------------------------------------------------------------------
    def test_unit_cost_is_frozen_at_validation(self):
        count = self._create_count(scope="products", product_ids=[(6, 0, self.roller.ids)])
        count.action_confirm()
        count.action_start()
        line = count.line_ids
        self.assertEqual(line.unit_cost, 800.0)
        line.write({"qty_counted": 38.0})  # −5 %: espera al supervisor
        self.assertEqual(line.state, "counted")
        self.assertAlmostEqual(line.diff_value, -1600.0)
        self.roller.standard_price = 900.0
        line.action_approve()
        self.assertEqual(count.state, "done")
        self.assertAlmostEqual(line.diff_value, -1800.0, msg="al costo del momento de validar")
        self.roller.standard_price = 1000.0
        self.env.flush_all()
        self.assertAlmostEqual(line.diff_value, -1800.0, msg="el historial no cambia")
        self.assertAlmostEqual(count.diff_value, -1800.0)

    # ------------------------------------------------------------------
    # Materialidad
    # ------------------------------------------------------------------
    def test_recount_min_value_skips_cheap_differences(self):
        cheap = self._create_count(
            scope="products", product_ids=[(6, 0, self.screw.ids)], recount_min_value=500.0
        )
        cheap.action_confirm()
        cheap.action_start()
        cheap.line_ids.write({"qty_counted": 90.0})  # −10 % pero solo $ 350
        self.assertEqual(cheap.state, "review")
        self.assertEqual(cheap.line_ids.state, "counted", "no vale un segundo conteo")
        cheap.action_cancel()

        dear = self._create_count(
            scope="products", product_ids=[(6, 0, self.screw.ids)], recount_min_value=500.0
        )
        dear.action_confirm()
        dear.action_start()
        dear.line_ids.write({"qty_counted": 80.0})  # −20 %, $ 700
        self.assertEqual(dear.line_ids.state, "recount")

    # ------------------------------------------------------------------
    # Producto no esperado desde la app
    # ------------------------------------------------------------------
    def test_add_unexpected_from_app(self):
        count = self._create_count(location_ids=[(6, 0, (self.shelf | self.other_shelf).ids)])
        count.action_confirm()
        count.action_start()
        Line = self.Line.with_user(self.counter)
        result = Line.counter_add_unexpected(
            count.id, self.other_shelf.id, self.roller.id, False, 3.0
        )
        data = result["line"]
        self.assertEqual(data["product_id"], self.roller.id)
        self.assertEqual(data["location_id"], self.other_shelf.id)
        self.assertTrue(data["done"])
        self.assertEqual(data["quantity"], 3.0)
        line = self.Line.browse(data["id"])
        self.assertEqual(line.counted_by_id, self.counter)
        self.assertEqual(line.qty_theoretical, 0.0)
        self.assertEqual(line.reason_id, self.env.ref("stock_count.reason_unexpected"))

        self.assertEqual(
            Line.counter_add_unexpected(count.id, self.other_shelf.id, self.paint.id, False, 1.0),
            {"need_lot": True},
            "controlado por lote sin lote: la app abre el formulario",
        )
        with self.assertRaises(UserError, msg="ya está en esa ubicación"):
            Line.counter_add_unexpected(count.id, self.shelf.id, self.roller.id, False, 1.0)

    def test_resolve_barcode_returns_product_name(self):
        count = self._create_count()
        count.action_confirm()
        result = self.Line.with_user(self.counter).counter_resolve_barcode("7790001", count.id)
        self.assertEqual(result["product_name"], self.screw.display_name)

    # ------------------------------------------------------------------
    # Paquetes
    # ------------------------------------------------------------------
    def test_line_data_shows_package(self):
        Package = self.env[self.Line._fields["package_id"].comodel_name]
        pallet = Package.create({"name": "PALLET-7"})
        self.env["stock.quant"]._update_available_quantity(
            self.tape, self.shelf, 5.0, package_id=pallet
        )
        self.env["stock.quant"]._update_available_quantity(self.tape, self.shelf, 2.0)
        count = self._create_count(scope="products", product_ids=[(6, 0, self.tape.ids)])
        count.action_confirm()
        names = sorted(line.sudo()._counter_line_data()["package_name"] for line in count.line_ids)
        self.assertEqual(len(names), 2)
        self.assertEqual(names[0], "")
        self.assertIn("PALLET-7", names[1])

    # ------------------------------------------------------------------
    # Validación en lote
    # ------------------------------------------------------------------
    def test_batch_apply_links_each_move_to_its_line(self):
        count = self._create_count(auto_approve_tolerance_pct=100.0)
        count.action_confirm()
        count.action_start()
        for product, qty in ((self.screw, 97.0), (self.roller, 42.0), (self.paint, 36.0)):
            self._line(count, product).write({"qty_counted": qty})
        self.assertEqual(count.state, "done")
        self.assertEqual(len(count.move_ids), 2)
        screw, roller, paint = (
            self._line(count, product) for product in (self.screw, self.roller, self.paint)
        )
        self.assertEqual(screw.move_line_ids.product_id, self.screw)
        self.assertEqual(screw.move_line_ids.quantity, 3.0)
        self.assertEqual(roller.move_line_ids.product_id, self.roller)
        self.assertEqual(roller.move_line_ids.quantity, 2.0)
        self.assertFalse(paint.move_line_ids)
        self.assertEqual(self._qty(self.screw, self.shelf), 97.0)
        self.assertEqual(self._qty(self.roller, self.shelf), 42.0)
