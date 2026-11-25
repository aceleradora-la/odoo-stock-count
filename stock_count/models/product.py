from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = "product.template"

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

    @api.model
    def _stock_count_find_pack_barcode(self, barcode):
        """(producto, embalaje) del código de barras de un embalaje, o vacíos."""
        link = self.env["product.uom"].sudo().search([("barcode", "=", barcode)], limit=1)
        return link.product_id, link.uom_id
