/** @odoo-module **/

import { onMounted } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";

/**
 * Botón "Recuentos" en la pantalla principal de la app Código de barras.
 *
 * No se importa el componente de Enterprise por su ruta (que cambia entre versiones):
 * se lo busca en el registro de acciones al arrancar el cliente web y se lo parchea
 * ahí. Al montarse la pantalla, el botón se inserta debajo del último botón grande
 * ("Contar inventario"); si la estructura no se reconoce, se agrega al final de la
 * pantalla. Si nada de esto es posible, la app sigue funcionando y queda el menú
 * Contar de Inventario.
 */
const CANDIDATE_ACTIONS = ["stock_barcode_main_menu", "stock_barcode.main_menu", "main_menu"];

function findMainMenuComponent() {
    const actions = registry.category("actions");
    for (const name of CANDIDATE_ACTIONS) {
        const component = actions.get(name, null);
        if (component && component.prototype) {
            return component;
        }
    }
    for (const [name, component] of actions.getEntries()) {
        if (name.includes("barcode") && name.includes("menu") && component && component.prototype) {
            return component;
        }
    }
    return null;
}

function findAnchor() {
    const root =
        document.querySelector(".o_stock_barcode_main_menu") ||
        document.querySelector(".o_barcode_main_menu") ||
        document.querySelector(".o_action_manager .o_action") ||
        document.querySelector(".o_action_manager");
    if (!root) {
        return { root: null, last: null };
    }
    const buttons = [...root.querySelectorAll("button.btn, a.btn")].filter(
        (el) => el.offsetParent !== null && !el.closest(".o_control_panel, .o_navbar")
    );
    return { root, last: buttons.length ? buttons[buttons.length - 1] : null };
}

async function injectCard(env) {
    if (document.querySelector(".o_stock_count_barcode_card")) {
        return;
    }
    const { root, last } = findAnchor();
    if (!root) {
        return;
    }
    let pending = 0;
    try {
        const data = await env.services.orm.call("stock.count.line", "counter_get_data", [false]);
        pending = data.lines.filter((line) => !line.done).length;
    } catch {
        pending = 0;
    }
    if (document.querySelector(".o_stock_count_barcode_card")) {
        return;
    }
    const card = document.createElement("div");
    card.className = "o_stock_count_barcode_card";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn-lg o_stock_count_barcode_button";
    button.innerHTML =
        '<i class="fa fa-list-ol me-2"></i>' +
        `<span>${_t("Recuentos")}</span>` +
        (pending ? `<span class="badge rounded-pill ms-2">${pending}</span>` : "");
    button.addEventListener("click", () =>
        env.services.action.doAction("stock_count.action_stock_count_counter")
    );
    card.appendChild(button);
    if (last && last.parentElement) {
        // Mismo contenedor y mismas clases de tamaño que "Contar inventario"
        card.className += " " + (last.className.match(/\b(w-100|col[-\w]*|mb-\d|mt-\d)\b/g) || []).join(" ");
        last.insertAdjacentElement("afterend", card);
    } else {
        root.appendChild(card);
    }
}

const stockCountBarcodeService = {
    dependencies: ["orm", "action"],
    start(env) {
        const MainMenu = findMainMenuComponent();
        if (!MainMenu) {
            console.warn("stock_count_barcode: no se encontró la pantalla principal de la app Código de barras");
            return;
        }
        patch(MainMenu.prototype, {
            setup() {
                super.setup(...arguments);
                onMounted(() => injectCard(env));
            },
        });
    },
};

registry.category("services").add("stock_count_barcode", stockCountBarcodeService);
