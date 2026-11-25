from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ProductPackaging(models.Model):
    _inherit = "product.packaging"

    stock_count_default = fields.Boolean(
        string="Recuento",
        help="Embalaje en el que se cuenta este producto en los recuentos de inventario: "
        "el contador carga embalajes y unidades sueltas. Uno solo por producto; si no hay "
        "ninguno marcado, se cuenta en la unidad de medida del producto.",
    )

    @api.constrains("stock_count_default", "product_id", "qty")
    def _check_stock_count_default(self):
        for packaging in self.filtered("stock_count_default"):
            if packaging.qty <= 0:
                raise ValidationError(
                    self.env._(
                        "%s: un embalaje de recuento tiene que traer una cantidad mayor a cero.",
                        packaging.name,
                    )
                )
            others = self.search_count(
                [
                    ("product_id", "=", packaging.product_id.id),
                    ("stock_count_default", "=", True),
                    ("id", "!=", packaging.id),
                ],
                limit=1,
            )
            if others:
                raise ValidationError(
                    self.env._(
                        "%s ya tiene otro embalaje marcado para recuento. Puede haber uno solo.",
                        packaging.product_id.display_name,
                    )
                )


class ProductProduct(models.Model):
    _inherit = "product.product"

    # --- Embalajes para el recuento. En Odoo 18 son product.packaging; en 19 son unidades
    # --- de medida. El resto del módulo solo usa estos métodos.
    def _stock_count_packs(self):
        """Embalajes en los que se puede contar este producto."""
        self.ensure_one()
        return self.packaging_ids.filtered(lambda packaging: packaging.qty > 0)

    def _stock_count_default_pack(self):
        self.ensure_one()
        return self.packaging_ids.filtered("stock_count_default")[:1]

    def _stock_count_pack_factor(self, pack):
        """Cuántas unidades de medida del producto trae un embalaje."""
        self.ensure_one()
        return pack.qty if pack else 0.0

    @api.model
    def _stock_count_find_pack_barcode(self, barcode):
        """(producto, embalaje) del código de barras de un embalaje, o vacíos."""
        pack = self.env["product.packaging"].sudo().search([("barcode", "=", barcode)], limit=1)
        return pack.product_id, pack
