from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    # Cada depósito recibe su tipo de operación Recuento; los recuentos y los ajustes
    # que ya existían quedan con ese tipo.
    env["stock.warehouse"].with_context(active_test=False).search(
        []
    )._stock_count_create_missing_types()
    counts = env["stock.count"].search([])
    counts._compute_picking_type_id()
    counts.flush_recordset()
    cr.execute(
        """
        UPDATE stock_move move
           SET picking_type_id = count.picking_type_id
          FROM stock_count count
         WHERE move.count_id = count.id
           AND move.picking_id IS NULL
           AND move.picking_type_id IS NULL
           AND count.picking_type_id IS NOT NULL
        """
    )
    # La precisión pasa a contar como acertadas las líneas dentro de la tolerancia de
    # aprobación: se recalcula en los recuentos que ya existían.
    counts._compute_line_stats()
