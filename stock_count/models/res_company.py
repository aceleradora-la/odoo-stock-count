from odoo import fields, models

LOCK_MODES = [
    ("block", "Bloquear la validación"),
    ("warn", "Avisar y marcar la línea"),
    ("none", "Sin control"),
]


class ResCompany(models.Model):
    _inherit = "res.company"

    stock_count_blind = fields.Boolean(
        string="Conteo ciego",
        default=False,
        help="Los contadores no ven la cantidad teórica ni la diferencia. "
        "Se define por compañía; no lo elige quien crea el recuento.",
    )
    stock_count_lock_mode = fields.Selection(
        LOCK_MODES,
        string="Bloqueo de movimientos por defecto",
        default="block",
        required=True,
        help="Qué pasa al validar un movimiento sobre un producto y ubicación que están "
        "en un recuento confirmado. La reserva nunca se bloquea, solo la validación.",
    )
    stock_count_recount_threshold_pct = fields.Float(
        string="Reconteo si la diferencia supera (%)",
        default=5.0,
        digits=(16, 2),
    )
    stock_count_recount_threshold_qty = fields.Float(
        string="Reconteo si la diferencia supera (unidades)",
        default=3.0,
        digits="Product Unit of Measure",
    )
    stock_count_auto_approve_pct = fields.Float(
        string="Aprobar automáticamente hasta (%)",
        default=1.0,
        digits=(16, 2),
    )
