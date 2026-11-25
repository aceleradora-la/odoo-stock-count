from . import controllers
from . import models
from . import wizards


def _post_init_hook(env):
    """Los depósitos que ya existían reciben su tipo de operación Recuento."""
    env["stock.warehouse"].with_context(active_test=False).search(
        []
    )._stock_count_create_missing_types()
