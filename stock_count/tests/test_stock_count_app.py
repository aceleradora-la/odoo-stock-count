from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestStockCountApp(HttpCase):
    def test_installable_app_manifest(self):
        """La app Recuentos se instala en el celular con su nombre y su ícono."""
        response = self.url_open(
            "/web/manifest.scoped_app_manifest?app_id=stock_count&path=/scoped_app/recuentos"
        )
        self.assertEqual(response.status_code, 200)
        manifest = response.json()
        self.assertEqual(manifest["name"], "Recuentos")
        self.assertEqual(manifest["start_url"], "/scoped_app/recuentos")
        self.assertEqual(manifest["scope"], "/scoped_app/recuentos")
        self.assertEqual([icon["sizes"] for icon in manifest["icons"]], ["192x192", "512x512"])
        for icon in manifest["icons"]:
            self.assertEqual(self.url_open(icon["src"]).status_code, 200)

        other = self.url_open(
            "/web/manifest.scoped_app_manifest?app_id=stock_count&path=/scoped_app/otra-cosa"
        ).json()
        self.assertNotEqual(other["name"], "Recuentos", "Solo cambia para la app Recuentos")

        action = self.env.ref("stock_count.action_stock_count_counter")
        self.assertEqual(action.path, "recuentos")
        menu = self.env.ref("stock_count.menu_stock_count_app_root")
        self.assertEqual(menu.action, action)
        self.assertFalse(menu.parent_id, "es una app propia en el inicio de Odoo")
        self.assertEqual(
            self.url_open("/stock_count/static/description/icon.svg").status_code, 200
        )
