/** @odoo-module **/

import { onMounted } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { MainMenu } from "@stock_barcode/components/main_menu";

/**
 * Tarjeta "Recuentos" en la pantalla principal de la app Código de barras.
 *
 * Se inserta por DOM al montar el menú, sin heredar la plantilla de Enterprise: si la
 * estructura interna de la app cambia, a lo sumo la tarjeta no aparece, pero la app
 * sigue funcionando y el menú "Recuentos" de la barra superior queda como acceso.
 */
patch(MainMenu.prototype, {
    setup() {
        super.setup(...arguments);
        this.stockCountOrm = useService("orm");
        this.stockCountAction = useService("action");
        onMounted(() => this._stockCountInjectCard());
    },

    _stockCountFindContainer() {
        const selectors = [
            ".o_stock_barcode_main_menu .o_stock_barcode_menu",
            ".o_stock_barcode_main_menu",
            ".o_barcode_main_menu",
            ".o_action_manager .o_action",
        ];
        for (const selector of selectors) {
            const el = document.querySelector(selector);
            if (el) {
                return el;
            }
        }
        return null;
    },

    async _stockCountInjectCard() {
        const container = this._stockCountFindContainer();
        if (!container || container.querySelector(".o_stock_count_barcode_card")) {
            return;
        }
        let pending = 0;
        try {
            const data = await this.stockCountOrm.call("stock.count.line", "counter_get_data", [false]);
            pending = data.lines.filter((line) => !line.done).length;
        } catch {
            pending = 0;
        }
        const card = document.createElement("div");
        card.className = "o_stock_count_barcode_card";
        const button = document.createElement("button");
        button.type = "button";
        button.className = "btn btn-secondary btn-lg o_stock_count_barcode_button";
        button.innerHTML =
            '<i class="fa fa-list-ol me-2"></i>' +
            `<span class="o_stock_count_barcode_label">${_t("Recuentos")}</span>` +
            (pending ? `<span class="badge rounded-pill text-bg-primary ms-2">${pending}</span>` : "");
        button.addEventListener("click", () =>
            this.stockCountAction.doAction("stock_count.action_stock_count_counter")
        );
        card.appendChild(button);
        container.appendChild(card);
    },
});
