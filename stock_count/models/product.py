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

    stock_count_pack_id = fields.Many2one(
        "uom.uom",
        string="Unidad de recuento",
        domain="[('id', 'in', uom_ids)]",
        help="Embalaje en el que se cuenta este producto en los recuentos de inventario: "
        "el contador carga embalajes y unidades sueltas. Vacío = se cuenta en la unidad "
        "de medida del producto. Se elige entre los embalajes del producto.",
    )

    @api.constrains("stock_count_pack_id", "uom_id")
    def _check_stock_count_pack_id(self):
        for template in self:
            pack = template.stock_count_pack_id
            if not pack:
                continue
            if pack == template.uom_id:
                raise ValidationError(
                    self.env._(
                        "La unidad de recuento de %s tiene que ser un embalaje, no su unidad "
                        "de medida. Para contar en la unidad de medida, dejala vacía.",
                        template.display_name,
                    )
                )
            if pack._compute_quantity(1.0, template.uom_id, round=False) <= 0:
                raise ValidationError(
                    self.env._(
                        "%(pack)s no se puede convertir a %(uom)s.",
                        pack=pack.name,
                        uom=template.uom_id.name,
                    )
                )


class ProductProduct(models.Model):
    _inherit = "product.product"

    # --- Embalajes para el recuento. En Odoo 19 son unidades de medida (uom.uom) que el
    # --- producto tiene en "Embalajes"; en 18 son product.packaging. El resto del módulo
    # --- solo usa estos métodos.
    def _stock_count_packs(self):
        """Embalajes en los que se puede contar este producto."""
        self.ensure_one()
        return (self.uom_ids | self.stock_count_pack_id) - self.uom_id

    def _stock_count_default_pack(self):
        self.ensure_one()
        return self.stock_count_pack_id

    def _stock_count_pack_factor(self, pack):
        """Cuántas unidades de medida del producto trae un embalaje."""
        self.ensure_one()
        return pack._compute_quantity(1.0, self.uom_id, round=False) if pack else 0.0

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
        link = self.env["product.uom"].sudo().search([("barcode", "=", barcode)], limit=1)
        return link.product_id, link.uom_id
