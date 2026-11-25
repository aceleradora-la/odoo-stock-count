from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from .test_stock_count_phase3 import Phase3Common


@tagged("post_install", "-at_install")
class TestStockCountPacks(Phase3Common, TransactionCase):
    """Conteo en embalajes: dos casilleros (embalajes + sueltas) sobre la unidad base."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_phase3()
        cls.egg = cls.env["product.product"].create(
            {"name": "Maple", "type": "consu", "is_storable": True, "standard_price": 10.0}
        )
        cls.env["stock.quant"]._update_available_quantity(cls.egg, cls.shelf, 400.0)
        cls.box = cls._make_pack(cls.egg, "Caja x30", 30.0, barcode="PK30", default=True)
        cls.sixpack = cls._make_pack(cls.egg, "Pack x6", 6.0)

    @classmethod
    def _make_pack(cls, product, name, qty, barcode=None, default=False):
        """Embalaje de un producto. Odoo 18: un product.packaging marcado para recuento."""
        return cls.env["product.packaging"].create(
            {
                "name": name,
                "product_id": product.id,
                "qty": qty,
                "barcode": barcode or False,
                "stock_count_default": default,
            }
        )

    def _count(self, products=None, **vals):
        products = products or self.egg
        count = self._create_count(scope="products", product_ids=[(6, 0, products.ids)], **vals)
        count.action_confirm()
        count.action_start()
        return count

    def _as_counter(self, line):
        return self.Line.with_user(self.counter).browse(line.id)

    def _qty(self, product, location):
        quants = self.env["stock.quant"]._gather(product, location, strict=True)
        return sum(quants.mapped("quantity"))

    def test_snapshot_and_two_boxes(self):
        count = self._count(self.egg | self.roller)
        egg, roller = self._line(count, self.egg), self._line(count, self.roller)
        self.assertEqual(egg.count_pack_id, self.box)
        self.assertEqual(egg.count_pack_factor, 30.0)
        self.assertFalse(roller.count_pack_id, "sin unidad de recuento: se cuenta en su unidad")

        data = egg.sudo()._counter_line_data()
        self.assertEqual(data["pack"]["id"], self.box.id)
        self.assertEqual(data["pack"]["factor"], 30.0)
        self.assertEqual(
            {option["id"] for option in data["pack_options"]},
            {False, self.box.id, self.sixpack.id},
        )
        self.assertEqual(roller.sudo()._counter_line_data()["pack_options"], [])

        updated = self._as_counter(egg).counter_set_quantity(packs=12, loose=7)
        self.assertEqual((updated["packs"], updated["loose"], updated["quantity"]), (12, 7, 367))
        self.assertTrue(updated["done"])
        self.assertEqual(egg.qty_counted, 367.0, "el recuento trabaja en la unidad base")
        self.assertEqual(egg.counted_by_id, self.counter)
        self.assertIn("12", egg.counted_breakdown)
        self.assertIn("Caja x30", egg.counted_breakdown)
        self.assertTrue(egg.theoretical_breakdown.startswith("13 "), egg.theoretical_breakdown)
        self.assertTrue(egg.theoretical_breakdown.endswith("+ 10"), egg.theoretical_breakdown)

        with self.assertRaises(UserError, msg="el rodillo no tiene embalaje"):
            self._as_counter(roller).counter_set_quantity(packs=2, loose=0)
        with self.assertRaises(UserError):
            self._as_counter(roller).counter_set_quantity(-1.0)

    def test_base_quantity_is_split_into_packs(self):
        count = self._count(self.egg | self.roller)
        egg = self._line(count, self.egg)
        egg.write({"qty_counted": 95.0})
        self.assertEqual((egg.qty_counted_packs, egg.qty_counted_loose), (3.0, 5.0))

    def test_scanning_a_pack_barcode_adds_one_pack(self):
        count = self._count(self.egg | self.roller)
        egg = self._line(count, self.egg)
        resolved = self.Line.with_user(self.counter).counter_resolve_barcode("PK30", count.id)
        self.assertEqual(resolved["type"], "product")
        self.assertEqual(resolved["product_id"], self.egg.id)
        self.assertEqual(resolved["pack_id"], self.box.id)
        self.assertEqual(resolved["quantity"], 30.0)

        line = self._as_counter(egg)
        first = line.counter_add_quantity(30.0, pack_id=self.box.id)
        self.assertEqual((first["packs"], first["loose"], first["quantity"]), (1, 0, 30))
        unit = line.counter_add_quantity(1.0)
        self.assertEqual((unit["packs"], unit["loose"], unit["quantity"]), (1, 1, 31))
        again = line.counter_add_quantity(30.0, pack_id=self.box.id)
        self.assertEqual((again["packs"], again["loose"], again["quantity"]), (2, 1, 61))
        other = line.counter_add_quantity(6.0, pack_id=self.sixpack.id)
        self.assertEqual(
            (other["packs"], other["loose"], other["quantity"]),
            (2, 7, 67),
            "otro embalaje del producto suma sus unidades como sueltas",
        )

    def test_counter_changes_the_unit_of_a_line(self):
        count = self._count(self.egg | self.roller)
        egg = self._line(count, self.egg)
        line = self._as_counter(egg)
        line.counter_set_quantity(packs=2, loose=5)
        plain = line.counter_set_pack(False)
        self.assertFalse(plain["pack"])
        self.assertEqual(plain["quantity"], 65, "lo ya cargado se conserva")
        self.assertFalse(egg.count_pack_id)
        line.counter_set_quantity(70.0)
        six = line.counter_set_pack(self.sixpack.id)
        self.assertEqual(six["pack"]["id"], self.sixpack.id)
        self.assertEqual((six["packs"], six["loose"], six["quantity"]), (11, 4, 70))
        self.assertEqual(egg.count_pack_factor, 6.0)

        foreign = self._make_pack(self.roller, "Bulto x4", 4.0)
        with self.assertRaises(UserError, msg="un embalaje de otro producto"):
            line.counter_set_pack(foreign.id)

    def test_recount_has_its_own_boxes_and_validates_in_base_unit(self):
        count = self._count()
        egg = count.line_ids
        line = self._as_counter(egg)
        line.counter_set_quantity(packs=10, loose=0)  # 300 de 400: −25 %
        self.assertEqual(count.state, "review")
        self.assertEqual(egg.state, "recount")
        data = egg.sudo()._counter_line_data()
        self.assertTrue(data["is_recount"])
        self.assertEqual((data["packs"], data["loose"]), (0, 0), "el reconteo arranca vacío")

        second = line.counter_set_quantity(packs=13, loose=5)  # 395: −1,25 %
        self.assertEqual(second["quantity"], 395)
        self.assertEqual((egg.qty_counted_packs, egg.qty_recount_packs), (10.0, 13.0))
        self.assertEqual(egg.qty_final, 395.0)
        self.assertEqual(egg.state, "counted", "fuera de tolerancia: espera al supervisor")
        egg.with_user(self.supervisor).action_approve()
        self.assertEqual(count.state, "done")
        self.assertEqual(self._qty(self.egg, self.shelf), 395.0)
        self.assertEqual(count.move_ids.product_uom_qty, 5.0)

    def test_blind_hides_theoretical_breakdown(self):
        self.company.stock_count_blind = True
        count = self._count(self.egg | self.roller)
        egg = self._line(count, self.egg)
        self._as_counter(egg).counter_set_quantity(packs=12, loose=7)
        data = self._as_counter(egg).read(["theoretical_breakdown", "counted_breakdown"])[0]
        self.assertFalse(data["theoretical_breakdown"])
        self.assertTrue(data["counted_breakdown"])
        manager = egg.with_user(self.supervisor).read(["theoretical_breakdown"])[0]
        self.assertTrue(manager["theoretical_breakdown"])

    def test_count_sheet_prints_the_pack(self):
        count = self._count(self.egg | self.roller)
        html = self.env["ir.actions.report"]._render_qweb_html(
            "stock_count.report_count_sheet", count.ids
        )[0]
        html = html.decode() if isinstance(html, bytes) else str(html)
        self.assertIn("Caja x30", html)
        self.assertIn("sueltas", html)
