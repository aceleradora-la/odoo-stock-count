from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .res_company import LOCK_MODES


class StockCountParamsMixin(models.AbstractModel):
    _name = "stock.count.params.mixin"
    _description = "Parámetros de recuento propios (producto o categoría)"

    stock_count_custom = fields.Boolean(
        string="Umbrales de recuento propios",
        help="Los recuentos usan estos umbrales para este producto o categoría, en lugar de "
        "los del recuento. El producto manda sobre la categoría, y una categoría sobre su "
        "categoría superior.",
    )
    stock_count_recount_threshold_pct = fields.Float(
        string="Reconteo si la diferencia supera (%)", digits=(16, 2)
    )
    stock_count_recount_threshold_qty = fields.Float(
        string="Reconteo si la diferencia supera (unidades)", digits="Product Unit of Measure"
    )
    stock_count_auto_approve_pct = fields.Float(
        string="Aprobar automáticamente hasta (%)", digits=(16, 2)
    )
    stock_count_recount_min_value = fields.Float(
        string="No recontar si el valor es menor a", digits="Product Price"
    )
    stock_count_lock_mode = fields.Selection(
        LOCK_MODES,
        string="Bloqueo de movimientos en recuento",
        help="Vacío: el que defina cada recuento.",
    )


class ProductCategory(models.Model):
    _name = "product.category"
    _inherit = ["product.category", "stock.count.params.mixin"]


class ProductTemplate(models.Model):
    _name = "product.template"
    _inherit = ["product.template", "stock.count.params.mixin"]


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

    def _stock_count_params_source(self):
        """Registro (producto o categoría) del que salen los umbrales, o vacío si rigen
        los del recuento."""
        self.ensure_one()
        if self.stock_count_custom:
            return self.product_tmpl_id
        categ = self.categ_id
        while categ:
            if categ.stock_count_custom:
                return categ
            categ = categ.parent_id
        return self.env["product.category"]

    def _stock_count_lock_mode(self):
        self.ensure_one()
        if self.stock_count_lock_mode:
            return self.stock_count_lock_mode
        categ = self.categ_id
        while categ:
            if categ.stock_count_lock_mode:
                return categ.stock_count_lock_mode
            categ = categ.parent_id
        return False

    @api.model
    def _stock_count_find_pack_barcode(self, barcode):
        """(producto, embalaje) del código de barras de un embalaje, o vacíos."""
        pack = self.env["product.packaging"].sudo().search([("barcode", "=", barcode)], limit=1)
        return pack.product_id, pack
