from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged

from .test_stock_count_phase3 import Phase3Common


@tagged("post_install", "-at_install")
class TestStockCountSupervisor(Phase3Common, TransactionCase):
    """Reconteo inmediato y tablero del supervisor de la app.

    Umbrales del escenario: reconteo sobre 5 % o 3 unidades, aprobación sola hasta 1 %.
    Pasillo A: 100 tornillos, 40 rodillos, 36 pinturas (lote).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_phase3()

    def _count(self, **vals):
        count = self._create_count(**vals)
        count.action_confirm()
        return count

    def _as_counter(self, line):
        return self.Line.with_user(self.counter).browse(line.id)

    def _qty(self, product, location, lot=None):
        quants = self.env["stock.quant"]._gather(product, location, lot_id=lot, strict=True)
        return sum(quants.mapped("quantity"))

    def _board(self, count):
        data = self.Count.with_user(self.supervisor).supervisor_get_data()
        return next(entry for entry in data["counts"] if entry["id"] == count.id)

    # ------------------------------------------------------------------
    # Reconteo inmediato
    # ------------------------------------------------------------------
    def test_immediate_recount_is_off_by_default(self):
        count = self._count()
        self.assertFalse(count.immediate_recount)
        screw = self._line(count, self.screw)
        data = self._as_counter(screw).counter_set_quantity(80.0)
        self.assertFalse(data["recount_requested"])
        self.assertEqual(screw.state, "counted", "el reconteo espera a la revisión")

    def test_company_setting_is_the_default_of_new_counts(self):
        self.company.stock_count_immediate_recount = True
        self.assertTrue(self._create_count().immediate_recount)

    def test_typed_quantity_over_threshold_asks_for_recount_right_away(self):
        count = self._count(immediate_recount=True)
        screw = self._line(count, self.screw)
        line = self._as_counter(screw)

        first = line.counter_set_quantity(80.0)
        self.assertTrue(first["recount_requested"])
        self.assertTrue(first["is_recount"])
        self.assertFalse(first["done"], "el segundo conteo arranca vacío")
        self.assertEqual(first["quantity"], 0)
        self.assertEqual(screw.state, "recount")
        self.assertEqual(screw.qty_counted, 80.0, "el primer conteo queda registrado")
        self.assertEqual(count.state, "counting")

        second = line.counter_set_quantity(99.0)
        self.assertFalse(second["recount_requested"], "se pide una sola vez")
        self.assertTrue(second["done"])
        self.assertEqual(screw.state, "counted")
        self.assertEqual(screw.qty_final, 99.0)
        self.assertEqual(screw.recounted_by_id, self.counter)

        exact = self._as_counter(self._line(count, self.roller)).counter_set_quantity(40.0)
        self.assertFalse(exact["recount_requested"])
        self._as_counter(self._line(count, self.paint)).counter_set_quantity(36.0)
        # Todo contado: 99 de 100 entra en la tolerancia y el recuento se valida solo
        self.assertEqual(count.state, "done")
        self.assertEqual(self._qty(self.screw, self.shelf), 99.0)

    def test_small_difference_does_not_ask_for_recount(self):
        count = self._count(immediate_recount=True)
        screw = self._line(count, self.screw)
        data = self._as_counter(screw).counter_set_quantity(98.0)
        self.assertFalse(data["recount_requested"])
        self.assertEqual(screw.state, "counted")

    def test_scanning_unit_by_unit_waits_for_the_end_of_the_location(self):
        count = self._count(immediate_recount=True)
        screw = self._line(count, self.screw)
        line = self._as_counter(screw)
        one = line.counter_add_quantity(1.0)
        self.assertNotIn("recount_requested", [key for key, value in one.items() if value])
        two = line.counter_add_quantity(1.0)
        self.assertEqual(two["quantity"], 2)
        self.assertEqual(
            screw.state, "counted", "sumando de a uno todavía no es la cantidad final"
        )

        result = self.Line.with_user(self.counter).counter_finish(count.id, self.shelf.id, True)
        self.assertEqual(result["zeroed"], 2)
        self.assertEqual(result["recount"], 3, "los 2 tornillos y los dos cierres en cero")
        self.assertEqual(screw.state, "recount")
        self.assertEqual(self._line(count, self.roller).state, "recount")
        self.assertEqual(count.state, "counting", "falta el segundo conteo")

    def test_a_resent_scan_is_not_counted_twice(self):
        """Sin señal, la app reenvía el pedido que quedó sin respuesta."""
        count = self._count()
        screw = self._line(count, self.screw)
        line = self._as_counter(screw)
        line.counter_add_quantity(1.0, op_uid="tel-1")
        again = line.counter_add_quantity(1.0, op_uid="tel-1")
        self.assertEqual(again["quantity"], 1, "el mismo pedido no suma otra vez")
        other = line.counter_add_quantity(1.0, op_uid="tel-2")
        self.assertEqual(other["quantity"], 2)
        self.assertEqual(screw.qty_counted, 2.0)

    # ------------------------------------------------------------------
    # Tablero del supervisor
    # ------------------------------------------------------------------
    def test_board_is_only_for_supervisors(self):
        count = self._count()
        with self.assertRaises(AccessError):
            self.Count.with_user(self.counter).supervisor_get_data()
        with self.assertRaises(AccessError):
            self.Count.with_user(self.counter).supervisor_action(count.id, "approve_all")
        self.assertFalse(self.Line.with_user(self.counter).counter_get_data()["is_manager"])
        self.assertTrue(self.Line.with_user(self.supervisor).counter_get_data()["is_manager"])

    def test_board_shows_progress_and_accepts_first_count(self):
        count = self._count()
        screw = self._line(count, self.screw)
        self._as_counter(screw).counter_set_quantity(80.0)

        board = self._board(count)
        self.assertEqual(board["state"], "counting")
        self.assertEqual(board["approve_count"], 0, "en conteo nada espera aprobación todavía")
        self.assertEqual(board["lines"], [])
        self.assertEqual(
            board["counters"],
            [
                {"name": "Luis Paz", "total": 1, "done": 1},
                {"name": "Sin asignar", "total": 2, "done": 0},
            ],
        )
        self.assertFalse(board["can_validate"])

        self._as_counter(self._line(count, self.roller)).counter_set_quantity(40.0)
        self._as_counter(self._line(count, self.paint)).counter_set_quantity(36.0)
        self.assertEqual(count.state, "review")
        board = self._board(count)
        self.assertEqual(board["recount_count"], 1)
        self.assertEqual(len(board["lines"]), 1)
        line = board["lines"][0]
        self.assertEqual(line["id"], screw.id)
        self.assertEqual(line["state"], "recount")
        self.assertEqual(
            (line["theoretical"], line["first_count"], line["diff"]), (100.0, 80.0, -20.0)
        )
        self.assertEqual(line["counted_by"], "Luis Paz")

        result = self.Count.with_user(self.supervisor).supervisor_action(
            count.id, "accept_first", [screw.id]
        )
        self.assertEqual(result["validated"], count.name)
        self.assertNotIn(count.id, [entry["id"] for entry in result["counts"]])
        self.assertEqual(count.state, "done")
        self.assertEqual(self._qty(self.screw, self.shelf), 80.0)

    def test_board_recount_and_approve(self):
        count = self._count()
        screw = self._line(count, self.screw)
        self._as_counter(screw).counter_set_quantity(97.0)  # −3 %: ni se aprueba ni se recuenta
        self._as_counter(self._line(count, self.roller)).counter_set_quantity(40.0)
        self._as_counter(self._line(count, self.paint)).counter_set_quantity(36.0)
        self.assertEqual(count.state, "review")
        board = self._board(count)
        self.assertEqual(board["approve_count"], 1)
        self.assertEqual(board["lines"][0]["state"], "counted")

        Board = self.Count.with_user(self.supervisor)
        result = Board.supervisor_action(count.id, "recount", [screw.id])
        self.assertEqual(screw.state, "recount")
        self.assertFalse(result["validated"])
        self._as_counter(screw).counter_set_quantity(98.0)
        self.assertEqual(screw.state, "counted", "−2 % sigue fuera de la tolerancia")

        result = Board.supervisor_action(count.id, "approve", [screw.id])
        self.assertEqual(result["validated"], count.name)
        self.assertEqual(self._qty(self.screw, self.shelf), 98.0)

    def test_board_approve_all(self):
        count = self._count()
        self._as_counter(self._line(count, self.screw)).counter_set_quantity(97.0)
        self._as_counter(self._line(count, self.roller)).counter_set_quantity(39.0)  # −2,5 %
        self._as_counter(self._line(count, self.paint)).counter_set_quantity(36.0)
        self.assertEqual(self._board(count)["approve_count"], 2)
        result = self.Count.with_user(self.supervisor).supervisor_action(count.id, "approve_all")
        self.assertEqual(result["validated"], count.name)
        self.assertEqual(self._qty(self.roller, self.shelf), 39.0)

    def test_board_rejects_foreign_lines_and_unknown_actions(self):
        count = self._count()
        other = self._count(location_ids=[(6, 0, self.other_shelf.ids)])
        Board = self.Count.with_user(self.supervisor)
        with self.assertRaises(UserError):
            Board.supervisor_action(count.id, "approve", other.line_ids.ids)
        with self.assertRaises(UserError):
            Board.supervisor_action(count.id, "borrar_todo")

    def test_accepting_the_last_recount_while_counting_closes_the_count(self):
        count = self._count(immediate_recount=True)
        screw = self._line(count, self.screw)
        self._as_counter(screw).counter_set_quantity(80.0)
        self._as_counter(self._line(count, self.roller)).counter_set_quantity(40.0)
        self._as_counter(self._line(count, self.paint)).counter_set_quantity(36.0)
        self.assertEqual(count.state, "counting", "queda el segundo conteo del tornillo")
        board = self._board(count)
        self.assertEqual([line["id"] for line in board["lines"]], [screw.id])
        self.assertEqual(board["approve_count"], 0)

        result = self.Count.with_user(self.supervisor).supervisor_action(
            count.id, "accept_first", [screw.id]
        )
        self.assertEqual(result["validated"], count.name)
        self.assertEqual(count.state, "done")
        self.assertEqual(self._qty(self.screw, self.shelf), 80.0)
