import base64
import io
import zipfile

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestStockCountReports(TransactionCase):
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
        cls.shelf = cls.env["stock.location"].create(
            {
                "name": "Pasillo R",
                "location_id": cls.stock.id,
                "usage": "internal",
                "barcode": "LOC-R",
            }
        )
        Product = cls.env["product.product"]
        cls.screw = Product.create(
            {
                "name": "Tornillo M8",
                "default_code": "TOR-M8",
                "barcode": "7790001",
                "type": "consu",
                "is_storable": True,
                "standard_price": 35.0,
            }
        )
        cls.roller = Product.create(
            {"name": "Rodillo 22", "type": "consu", "is_storable": True, "standard_price": 800.0}
        )
        Quant = cls.env["stock.quant"]
        Quant._update_available_quantity(cls.screw, cls.shelf, 100.0)
        Quant._update_available_quantity(cls.roller, cls.shelf, 40.0)
        cls.counter = cls.env["res.users"].create(
            {
                "name": "Luis Paz",
                "login": "luis.paz.reports",
                "email": "luis.reports@example.com",
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            cls.env.ref("base.group_user").id,
                            cls.env.ref("stock_count.group_stock_count_user").id,
                        ],
                    )
                ],
            }
        )
        cls.Count = cls.env["stock.count"]

    def _create_count(self, **vals):
        base = {
            "warehouse_id": self.warehouse.id,
            "location_ids": [(6, 0, self.shelf.ids)],
            "include_children": False,
            "counter_ids": [(6, 0, self.counter.ids)],
        }
        base.update(vals)
        return self.Count.create(base)

    def _applied_count(self):
        count = self._create_count()
        count.action_confirm()
        count.action_start()
        count.line_ids.write({"assigned_user_id": self.counter.id})
        for line in count.line_ids:
            qty = 98.0 if line.product_id == self.screw else 40.0
            line.with_user(self.counter).write({"qty_counted": qty})
        count.action_to_review()
        count.action_approve_all()
        count.action_apply()
        return count

    def _render(self, report_ref, count):
        html = self.env["ir.actions.report"]._render_qweb_html(report_ref, count.ids)[0]
        return html.decode() if isinstance(html, bytes) else str(html)

    def test_count_sheet_lists_lines_without_theoretical(self):
        count = self._create_count()
        count.action_confirm()
        count.line_ids.write({"assigned_user_id": self.counter.id})
        html = self._render("stock_count.report_count_sheet", count)
        self.assertIn("Hoja de conteo", html)
        self.assertIn(count.name, html)
        self.assertIn("Luis Paz", html)
        self.assertIn("Pasillo R", html)
        self.assertIn("Tornillo M8", html)
        self.assertIn("TOR-M8", html)
        self.assertIn("barcode_type=Code128", html)
        self.assertIn("LOC-R", html)
        self.assertIn("Cantidad contada", html)
        self.assertNotIn("100.0", html, "la hoja de conteo nunca muestra el teórico")

    def test_diff_report_shows_differences_and_totals(self):
        count = self._applied_count()
        html = self._render("stock_count.report_count_diff", count)
        self.assertIn("Informe de diferencias", html)
        self.assertIn("Tornillo M8", html)
        self.assertIn("-2.00", html)
        self.assertIn("Líneas con diferencia", html)
        self.assertIn("líneas sin diferencia", html)
        self.assertNotIn("No hay diferencias", html)
        self.assertIn("Luis Paz", html)

    def test_xlsx_export_creates_attachment(self):
        count = self._applied_count()
        action = count.action_export_xlsx()
        self.assertEqual(action["type"], "ir.actions.act_url")
        attachment = self.env["ir.attachment"].search(
            [("res_model", "=", "stock.count"), ("res_id", "=", count.id)], limit=1
        )
        self.assertTrue(attachment)
        self.assertTrue(attachment.name.endswith("_diferencias.xlsx"))
        self.assertIn(str(attachment.id), action["url"])
        content = base64.b64decode(attachment.datas)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = archive.namelist()
            self.assertIn("xl/workbook.xml", names)
            shared = archive.read("xl/sharedStrings.xml").decode()
        self.assertIn(count.name, shared)
        self.assertIn("Tornillo M8", shared)
        self.assertIn("Luis Paz", shared)

    def test_location_stats_after_applied_counts(self):
        self.assertEqual(self.shelf.stock_count_count, 0)
        self.assertEqual(self.shelf.stock_count_accuracy, 0.0)
        count = self._applied_count()
        self.shelf.invalidate_recordset()
        self.assertEqual(self.shelf.stock_count_count, 1)
        self.assertEqual(self.shelf.stock_count_last_date, count.date_end)
        self.assertAlmostEqual(self.shelf.stock_count_accuracy, 50.0)
        action = self.shelf.action_view_stock_counts()
        self.assertIn(count, self.Count.search(action["domain"]))

    def test_analysis_fields_and_display_name(self):
        count = self._applied_count()
        line = count.line_ids.filtered(lambda line: line.product_id == self.screw)
        self.assertEqual(line.count_date, count.date_planned)
        self.assertEqual(line.categ_id, self.screw.categ_id)
        self.assertEqual(line.warehouse_id, self.warehouse)
        self.assertIn(count.name, line.display_name)
        self.assertIn("Tornillo M8", line.display_name)
        groups = self.env["stock.count.line"]._read_group(
            [("count_state", "=", "done"), ("count_id", "=", count.id)],
            ["location_id"],
            ["qty_diff:sum", "diff_value:sum"],
        )
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0][0], self.shelf)
        self.assertEqual(groups[0][1], -2.0)
        self.assertEqual(groups[0][2], -70.0)
