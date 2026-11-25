import base64
import json

from odoo.tests import TransactionCase, tagged

from .test_stock_count_phase3 import Phase3Common


@tagged("post_install", "-at_install")
class TestStockCountDashboard(Phase3Common, TransactionCase):
    """Tablero "Recuentos" de la app Tableros."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_phase3()

    def _dashboard(self):
        dashboard = self.env.ref("stock_count.dashboard_stock_count")
        return dashboard, json.loads(base64.b64decode(dashboard.spreadsheet_binary_data))

    def _validated_count(self):
        count = self._create_count(
            auto_approve_tolerance_pct=2.0, recount_threshold_qty=0.0, recount_threshold_pct=50.0
        )
        count.action_confirm()
        self._line(count, self.screw).write({"qty_counted": 99.0})  # −1 %: dentro de tolerancia
        self._line(count, self.roller).write({"qty_counted": 45.0})  # +12,5 %: sobrante
        self._line(count, self.paint, self.lot_a).write({"qty_counted": 36.0})
        self._line(count, self.roller).with_user(self.supervisor).action_approve()
        self.assertEqual(count.state, "done")
        return count

    def test_line_fields_for_the_dashboard(self):
        count = self._validated_count()
        screw, roller = self._line(count, self.screw), self._line(count, self.roller)
        paint = self._line(count, self.paint, self.lot_a)
        self.assertEqual(
            (screw.diff_type, roller.diff_type, paint.diff_type), ("shortage", "surplus", "none")
        )
        self.assertEqual(
            (screw.is_accurate, roller.is_accurate, paint.is_accurate), (True, False, True)
        )
        self.assertEqual(screw.diff_value_abs, 35.0)
        self.assertEqual(roller.diff_value_abs, 4000.0)

    def test_dashboard_is_published_for_supervisors(self):
        dashboard, data = self._dashboard()
        self.assertEqual(dashboard.name, "Recuentos")
        self.assertTrue(dashboard.is_published)
        self.assertIn(self.env.ref("stock_count.group_stock_count_manager"), dashboard.group_ids)
        self.assertEqual([sheet["name"] for sheet in data["sheets"]], ["Recuentos", "Datos"])
        self.assertEqual(len(data["sheets"][0]["figures"]), 7)

    def test_every_pivot_reads_fields_that_exist(self):
        """Cada pivote del tablero agrupa, mide y filtra por campos guardados del modelo,
        y la consulta que arma funciona."""
        self._validated_count()
        _dashboard, data = self._dashboard()
        filters = {global_filter["id"] for global_filter in data["globalFilters"]}
        self.assertEqual(len(data["pivots"]), 7)
        for pivot in data["pivots"].values():
            Model = self.env[pivot["model"]]
            groupby, aggregates = [], []
            for group in pivot["rows"] + pivot["columns"]:
                field = Model._fields[group["fieldName"]]
                self.assertTrue(field.store, group["fieldName"])
                granularity = group.get("granularity")
                groupby.append(f"{field.name}:{granularity}" if granularity else field.name)
            for measure in pivot["measures"]:
                if measure["fieldName"] == "__count":
                    aggregates.append("__count")
                    continue
                self.assertTrue(Model._fields[measure["fieldName"]].store, measure["fieldName"])
                aggregates.append(f"{measure['fieldName']}:{measure['aggregator']}")
            for filter_id, match in pivot["fieldMatching"].items():
                self.assertIn(filter_id, filters)
                self.assertTrue(Model._fields[match["chain"]].store, match["chain"])
            groups = Model._read_group(pivot["domain"], groupby, aggregates)
            self.assertTrue(groups, pivot["name"])
