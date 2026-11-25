from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from .common import done_move, pass_through
from .test_stock_count_phase3 import Phase3Common


@tagged("post_install", "-at_install")
class TestStockCountZero(Phase3Common, TransactionCase):
    """Incluir stock en cero: lo que no tiene stock y se movió desde su último recuento."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_phase3()
        cls.customers = cls.env.ref("stock.stock_location_customers")
        cls.today = fields.Datetime.now().replace(microsecond=0)

    def _day(self, number):
        """Lo que pase adentro ocurre `number` días después de hoy: los movimientos y el
        cierre de los recuentos se comparan por fecha."""
        moment = self.today + timedelta(days=number)
        return patch.object(fields.Datetime, "now", return_value=moment)

    def _zero_count(self, **vals):
        vals.setdefault("include_zero_quants", True)
        return self._create_count(**vals)

    def _validate(self, count):
        """Cuenta todo como dice el sistema y valida."""
        count.action_start()
        for line in count.line_ids:
            line.write({"qty_counted": line.qty_theoretical})
        if count.state != "done":
            count.action_to_review()
        self.assertEqual(count.state, "done")

    def test_zero_without_moves_is_not_included(self):
        count = self._zero_count(scope="products", product_ids=[(6, 0, self.tape.ids)])
        with self.assertRaises(UserError, msg="en cero pero sin movimientos: nada que contar"):
            count.action_confirm()

    def test_zero_with_moves_is_included_in_every_scope(self):
        pass_through(self.env, self.tape, self.shelf)
        by_product = self._zero_count(scope="products", product_ids=[(6, 0, self.tape.ids)])
        by_product.action_confirm()
        self.assertEqual(len(by_product.line_ids), 1)
        self.assertEqual(by_product.line_ids.qty_theoretical, 0.0)
        self.assertFalse(by_product.line_ids.quant_id)
        by_product.action_cancel()

        everything = self._zero_count()
        everything.action_confirm()
        self.assertEqual(self._line(everything, self.tape).qty_theoretical, 0.0)
        self.assertEqual(len(everything.line_ids), 4, "tornillo, rodillo, pintura y la cinta")
        everything.action_cancel()

        without = self._create_count()
        without.action_confirm()
        self.assertNotIn(self.tape, without.line_ids.product_id, "sin la opción no entra")

    def test_only_the_location_where_it_moved(self):
        pass_through(self.env, self.tape, self.other_shelf)
        count = self._zero_count(location_ids=[(6, 0, (self.shelf | self.other_shelf).ids)])
        count.action_confirm()
        self.assertEqual(self._line(count, self.tape).location_id, self.other_shelf)

    def test_product_with_stock_is_not_duplicated(self):
        done_move(self.env, self.screw, 10.0, self.shelf, self.customers)
        count = self._zero_count()
        count.action_confirm()
        self.assertEqual(len(self._line(count, self.screw)), 1)
        self.assertEqual(self._line(count, self.screw).qty_theoretical, 90.0)

    def test_counted_zero_is_not_asked_again_until_it_moves(self):
        with self._day(1):
            pass_through(self.env, self.tape, self.shelf)
        with self._day(2):
            first = self._zero_count(scope="products", product_ids=[(6, 0, self.tape.ids)])
            first.action_confirm()
            self._validate(first)
        self.assertEqual(first.line_ids.state, "applied")

        again = self._zero_count(scope="products", product_ids=[(6, 0, self.tape.ids)])
        with self._day(3), self.assertRaises(UserError, msg="ya se contó y no se movió"):
            again.action_confirm()
        with self._day(4):
            pass_through(self.env, self.tape, self.shelf)
        with self._day(5):
            again.action_confirm()
        self.assertEqual(len(again.line_ids), 1, "se movió de nuevo: vuelve a entrar")

    def test_full_count_is_the_last_count_of_its_locations(self):
        with self._day(1):
            pass_through(self.env, self.tape, self.shelf)
        with self._day(2):
            full = self._create_count()  # todos los productos, sin incluir ceros
            full.action_confirm()
            self._validate(full)

        after = self._zero_count()
        with self._day(3):
            after.action_confirm()
        self.assertNotIn(
            self.tape, after.line_ids.product_id, "la ubicación ya se contó entera después"
        )
        after.action_cancel()
        with self._day(4):
            pass_through(self.env, self.tape, self.shelf)
        after_move = self._zero_count()
        with self._day(5):
            after_move.action_confirm()
        self.assertIn(self.tape, after_move.line_ids.product_id)

    def test_count_adjustments_are_not_moves(self):
        with self._day(1):
            count = self._create_count(scope="products", product_ids=[(6, 0, self.roller.ids)])
            count.action_confirm()
            count.action_start()
            line = count.line_ids
            line.write({"qty_counted": 0.0})
            if count.state == "counting":
                count.action_to_review()
            if line.state == "recount":
                line.write({"qty_recount": 0.0})
            if line.state == "counted":
                line.with_user(self.supervisor).action_approve()
            if count.state != "done":
                count.action_apply()
        self.assertEqual(count.state, "done")
        self.assertTrue(count.move_ids, "el recuento ajustó el rodillo a cero")
        # Otro recuento validado después, que no tocó el rodillo
        with self._day(2):
            pass_through(self.env, self.tape, self.shelf)
            other = self._zero_count(
                scope="products", product_ids=[(6, 0, (self.tape | self.roller).ids)]
            )
            other.action_confirm()
        self.assertEqual(
            other.line_ids.product_id, self.tape, "el ajuste del recuento no es un movimiento"
        )

    def test_lots_get_one_line_each_and_serials_are_skipped(self):
        lot_b = self.env["stock.lot"].create(
            {"name": "L-240902", "product_id": self.paint.id, "company_id": self.company.id}
        )
        pass_through(self.env, self.paint, self.shelf, lot=lot_b)
        reader = self.env["product.product"].create(
            {"name": "Lector", "type": "consu", "is_storable": True, "tracking": "serial"}
        )
        serial = self.env["stock.lot"].create(
            {"name": "SN-001", "product_id": reader.id, "company_id": self.company.id}
        )
        pass_through(self.env, reader, self.shelf, qty=1.0, lot=serial)

        count = self._zero_count()
        count.action_confirm()
        paint = self._line(count, self.paint)
        self.assertEqual(set(paint.mapped("lot_id").ids), {self.lot_a.id, lot_b.id})
        self.assertEqual(self._line(count, self.paint, lot_b).qty_theoretical, 0.0)
        self.assertNotIn(reader, count.line_ids.product_id, "una serie que salió no se confirma")
        count.action_cancel()

        by_lot = self._zero_count(scope="lots", lot_ids=[(6, 0, lot_b.ids)])
        by_lot.action_confirm()
        self.assertEqual(by_lot.line_ids.lot_id, lot_b)

    def test_start_keeps_zero_lines(self):
        pass_through(self.env, self.tape, self.shelf)
        count = self._zero_count()
        count.action_confirm()
        count.action_start()
        self.assertEqual(self._line(count, self.tape).qty_theoretical, 0.0)
        self.assertEqual(len(count.line_ids), 4)
