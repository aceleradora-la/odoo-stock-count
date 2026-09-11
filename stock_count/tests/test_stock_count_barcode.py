from odoo.tests import TransactionCase, tagged


def _gtin_check_digit(digits):
    """Dígito verificador GS1 (EAN/GTIN): pesos 3 y 1 desde la derecha."""
    total = 0
    for index, char in enumerate(reversed(digits)):
        total += int(char) * (3 if index % 2 == 0 else 1)
    return str((10 - total % 10) % 10)


@tagged("post_install", "-at_install")
class TestStockCountBarcode(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({"stock_count_lock_mode": "none", "stock_count_blind": False})
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.company.id)], limit=1
        )
        cls.stock = cls.warehouse.lot_stock_id
        cls.shelf = cls.env["stock.location"].create(
            {
                "name": "Pasillo S",
                "location_id": cls.stock.id,
                "usage": "internal",
                "barcode": "LOC-S",
            }
        )
        ean13 = "123456789012"
        cls.ean13 = ean13 + _gtin_check_digit(ean13)
        Product = cls.env["product.product"]
        cls.screw = Product.create(
            {
                "name": "Tornillo M8",
                "default_code": "TOR-M8",
                "barcode": cls.ean13,
                "type": "consu",
                "is_storable": True,
            }
        )
        cls.paint = Product.create(
            {
                "name": "Pintura 4 L",
                "barcode": "7790002",
                "type": "consu",
                "is_storable": True,
                "tracking": "lot",
            }
        )
        cls.lot_a = cls.env["stock.lot"].create(
            {"name": "L240811", "product_id": cls.paint.id, "company_id": cls.company.id}
        )
        Quant = cls.env["stock.quant"]
        Quant._update_available_quantity(cls.screw, cls.shelf, 100.0)
        Quant._update_available_quantity(cls.paint, cls.shelf, 36.0, lot_id=cls.lot_a)
        cls.counter = cls.env["res.users"].create(
            {
                "name": "Luis Paz",
                "login": "luis.barcode",
                "email": "luis.barcode@example.com",
                "group_ids": [
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
        cls.count = cls.env["stock.count"].create(
            {
                "warehouse_id": cls.warehouse.id,
                "location_ids": [(6, 0, cls.shelf.ids)],
                "include_children": False,
                "counter_ids": [(6, 0, cls.counter.ids)],
            }
        )
        cls.count.action_confirm()
        cls.count.action_start()
        cls.Line = cls.env["stock.count.line"].with_user(cls.counter)

    def _resolve(self, code):
        return self.Line.counter_resolve_barcode(code, self.count.id)

    def test_exact_matches(self):
        self.assertEqual(self._resolve("LOC-S")["type"], "location")
        self.assertEqual(self._resolve("LOC-S")["location_id"], self.shelf.id)
        product = self._resolve(self.ean13)
        self.assertEqual(
            (product["type"], product["product_id"], product["quantity"]),
            ("product", self.screw.id, 1.0),
        )
        by_code = self._resolve("TOR-M8")
        self.assertEqual(by_code["product_id"], self.screw.id)
        lot = self._resolve("L240811")
        self.assertEqual(
            (lot["type"], lot["product_id"], lot["lot_id"]),
            ("product", self.paint.id, self.lot_a.id),
        )
        self.assertEqual(self._resolve("NADA-QUE-VER")["type"], "unknown")
        self.assertEqual(self._resolve("")["type"], "unknown")

    def test_gs1_product_with_quantity_and_lot(self):
        gs1 = self.env.ref("barcodes_gs1_nomenclature.default_gs1_nomenclature")
        self.company.nomenclature_id = gs1
        gtin14 = "0" + self.ean13
        with_qty = self._resolve("01" + gtin14 + "3012")
        self.assertEqual(with_qty["type"], "product")
        self.assertEqual(with_qty["product_id"], self.screw.id)
        self.assertEqual(with_qty["quantity"], 12.0)

        paint_gtin = "0000000" + "7790002"  # 14 dígitos, el producto tiene el código sin ceros
        # El dígito verificador del GTIN debe ser válido: recalculamos sobre los 13 primeros
        paint_gtin = paint_gtin[:-1] + _gtin_check_digit(paint_gtin[:-1])
        self.paint.barcode = paint_gtin.lstrip("0")
        with_lot = self._resolve("01" + paint_gtin + "10L240811")
        self.assertEqual(with_lot["type"], "product")
        self.assertEqual(with_lot["product_id"], self.paint.id)
        self.assertEqual(with_lot["lot_id"], self.lot_a.id)
        self.assertEqual(with_lot["quantity"], 1.0)

        self.assertEqual(self._resolve("0199999999999999")["type"], "unknown")
