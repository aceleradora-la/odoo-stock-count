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
        "en un recuento iniciado. La reserva nunca se bloquea, solo la validación.",
    )
    stock_count_no_self_approval = fields.Boolean(
        string="El supervisor no aprueba lo que contó",
        default=False,
        help="Un supervisor no puede aprobar ni aceptar el primer conteo de las líneas que "
        "contó él mismo: las tiene que resolver otro supervisor. La aprobación automática "
        "por tolerancia no cambia.",
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
    stock_count_immediate_recount = fields.Boolean(
        string="Reconteo inmediato",
        default=False,
        help="Si el primer conteo supera el umbral de reconteo, se pide el segundo conteo "
        "en el momento, sin esperar a la revisión. El contador solo ve que tiene que "
        "contar de nuevo, nunca la cantidad del sistema.",
    )
    stock_count_recount_min_value = fields.Float(
        string="No recontar si el valor de la diferencia es menor a",
        default=0.0,
        digits="Product Price",
    )
