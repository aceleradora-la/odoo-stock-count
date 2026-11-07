from odoo import http
from odoo.addons.web.controllers import webmanifest
from odoo.http import request


class StockCountWebManifest(webmanifest.WebManifest):
    """App Recuentos instalable en el celular, con la misma mecánica que Odoo usa para
    Código de Barras: la página /scoped_app ofrece instalarla y el manifiesto queda
    acotado a /scoped_app/recuentos, con su nombre y su ícono propios."""

    APP_MODULE = "stock_count"
    APP_PATH = "recuentos"
    APP_NAME = "Recuentos"

    def _stock_count_is_app(self, app_id):
        return app_id == self.APP_MODULE and self.APP_PATH in (request.params.get("path") or "")

    def _get_scoped_app_name(self, app_id):
        if self._stock_count_is_app(app_id):
            return self.APP_NAME
        return super()._get_scoped_app_name(app_id)

    def _get_scoped_app_icons(self, app_id):
        if self._stock_count_is_app(app_id):
            return [
                {
                    "src": f"/stock_count/static/description/icon_{size}.png",
                    "sizes": f"{size}x{size}",
                    "type": "image/png",
                }
                for size in (192, 512)
            ]
        return super()._get_scoped_app_icons(app_id)

    @http.route()
    def scoped_app_icon_png(self, app_id, add_padding=False):
        # Ícono para iPhone (apple-touch-icon). La página de instalación no manda el
        # path, y la única app de este módulo que se instala es Recuentos.
        if app_id == self.APP_MODULE:
            return request.redirect("/stock_count/static/description/icon_192.png")
        return super().scoped_app_icon_png(app_id, add_padding=add_padding)
