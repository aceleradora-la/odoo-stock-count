/** @odoo-module **/

import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("stock_count_counter_tour", {
    url: "/odoo/action-stock_count.action_stock_count_counter",
    steps: () => [
        {
            content: "Aparece la lista de ubicaciones",
            trigger: ".o_stock_count_counter .o_stock_count_counter_location",
            run: "click",
        },
        {
            content: "Se ven las líneas de la ubicación",
            trigger: ".o_stock_count_counter_line",
        },
        {
            content: "Sumar una unidad a la primera línea",
            trigger: ".o_stock_count_counter_line:first-child button",
            run: "click",
        },
        {
            content: "La línea queda contada",
            trigger: ".o_stock_count_counter_line.o_done",
        },
    ],
});
