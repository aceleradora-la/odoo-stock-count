/** @odoo-module **/

import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("stock_count_counter_tour", {
    url: "/odoo/recuentos",
    steps: () => [
        {
            content: "Inicio: entrar a Contar",
            trigger: ".o_stock_count_counter .o_sc_home_card_active",
            run: "click",
        },
        {
            content: "Lista: abrir el recuento",
            trigger: ".o_sc_card .o_sc_btn_primary",
            run: "click",
        },
        {
            content: "Recuento: abrir la primera ubicación",
            trigger: ".o_sc_loc_card",
            run: "click",
        },
        {
            content: "Ubicación: sumar una unidad a la primera línea",
            trigger: ".o_sc_line:first-child .o_sc_plus",
            run: "click",
        },
        {
            content: "La línea queda contada",
            trigger: ".o_sc_line:not(.o_sc_line_empty)",
        },
    ],
});
