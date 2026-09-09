from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    stock_count_blind = fields.Boolean(related="company_id.stock_count_blind", readonly=False)
    stock_count_lock_mode = fields.Selection(
        related="company_id.stock_count_lock_mode", readonly=False
    )
    stock_count_recount_threshold_pct = fields.Float(
        related="company_id.stock_count_recount_threshold_pct", readonly=False
    )
    stock_count_recount_threshold_qty = fields.Float(
        related="company_id.stock_count_recount_threshold_qty", readonly=False
    )
    stock_count_auto_approve_pct = fields.Float(
        related="company_id.stock_count_auto_approve_pct", readonly=False
    )
