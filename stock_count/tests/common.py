def done_move(env, product, qty, src, dst, lot=None):
    """Movimiento de stock validado, sin transferencia."""
    vals = {
        "product_id": product.id,
        "product_uom_qty": qty,
        "product_uom": product.uom_id.id,
        "location_id": src.id,
        "location_dest_id": dst.id,
    }
    if "name" in env["stock.move"]._fields:  # hasta 18.0 es obligatorio; en 19.0 no existe
        vals["name"] = product.display_name
    move = env["stock.move"].create(vals)
    move._action_confirm()
    move._action_assign()
    if not move.move_line_ids:
        move.move_line_ids = [
            (
                0,
                0,
                {
                    "product_id": product.id,
                    "product_uom_id": product.uom_id.id,
                    "quantity": qty,
                    "location_id": src.id,
                    "location_dest_id": dst.id,
                    "lot_id": lot.id if lot else False,
                },
            )
        ]
    elif lot:
        move.move_line_ids.lot_id = lot
    move.picked = True
    move._action_done()
    return move


def pass_through(env, product, location, qty=5.0, lot=None):
    """El producto entra a la ubicación y vuelve a salir: queda en cero, con movimientos."""
    suppliers = env.ref("stock.stock_location_suppliers")
    customers = env.ref("stock.stock_location_customers")
    done_move(env, product, qty, suppliers, location, lot=lot)
    done_move(env, product, qty, location, customers, lot=lot)
