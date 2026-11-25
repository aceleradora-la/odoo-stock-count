from psycopg2.extras import Json

from odoo import SUPERUSER_ID, api
from odoo.tools.sql import column_exists


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
    _migrate_count_units(cr, env)


def _migrate_count_units(cr, env):
    """El producto pasa de una unidad de recuento a varias, y la línea guarda la
    cantidad de cada una. Lo que había (una sola) se pasa al formato nuevo."""
    if column_exists(cr, "product_template", "stock_count_pack_id"):
        cr.execute(
            """
            INSERT INTO product_template_stock_count_uom_rel (product_tmpl_id, uom_id)
            SELECT id, stock_count_pack_id
              FROM product_template
             WHERE stock_count_pack_id IS NOT NULL
            ON CONFLICT DO NOTHING
            """
        )
    if not column_exists(cr, "stock_count_line", "count_pack_id"):
        return
    cr.execute(
        """
        SELECT id, count_pack_id, count_pack_factor, qty_counted_packs, qty_recount_packs
          FROM stock_count_line
         WHERE count_pack_id IS NOT NULL
        """
    )
    rows = cr.fetchall()
    packs = env["uom.uom"].browse({row[1] for row in rows}).exists()
    names = {pack.id: pack.display_name for pack in packs}
    for line_id, pack_id, factor, counted, recount in rows:
        key = str(pack_id)
        cr.execute(
            """
            UPDATE stock_count_line
               SET count_units = %s, qty_counted_units = %s, qty_recount_units = %s
             WHERE id = %s
            """,
            [
                Json([{"id": pack_id, "name": names.get(pack_id, ""), "factor": factor or 0.0}]),
                Json({key: counted}) if counted else None,
                Json({key: recount}) if recount else None,
                line_id,
            ],
        )
    env.invalidate_all()
