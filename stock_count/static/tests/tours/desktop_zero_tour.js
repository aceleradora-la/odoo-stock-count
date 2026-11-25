/** @odoo-module **/

import { registry } from "@web/core/registry";

// Escritorio: escribir 0 en una línea pendiente la deja contada en cero.

registry.category("web_tour.tours").add("stock_count_desktop_zero_list", {
    steps: () => [
        {
            content: "Mis líneas de conteo: abrir la ubicación",
            trigger: ".o_list_view .o_group_header",
            run: "click",
        },
        {
            content: "La línea pendiente muestra la cantidad vacía",
            trigger: ".o_data_row:first .o_data_cell[name=qty_counted]:not(:contains(0))",
            run: "click",
        },
        {
            content: "Escribir 0",
            trigger: ".o_selected_row [name=qty_counted] input",
            run: "edit 0",
        },
        {
            content: "Guardar la fila",
            trigger: ".o_list_button_save",
            run: "click",
        },
        {
            content: "La fila quedó guardada",
            trigger: ".o_list_view:not(:has(.o_selected_row))",
        },
    ],
});

registry.category("web_tour.tours").add("stock_count_desktop_zero_form", {
    steps: () => [
        {
            content: "Recuento: la línea pendiente muestra la cantidad vacía",
            trigger:
                ".o_field_widget[name=line_ids] .o_data_row:first .o_data_cell[name=qty_counted]:not(:contains(0))",
            run: "click",
        },
        {
            content: "Escribir 0",
            trigger: ".o_field_widget[name=line_ids] .o_selected_row [name=qty_counted] input",
            run: "edit 0",
        },
        {
            content: "Guardar el recuento",
            trigger: ".o_form_button_save",
            run: "click",
        },
        {
            content: "La línea quedó contada en cero",
            trigger:
                ".o_field_widget[name=line_ids] .o_data_row:first .o_data_cell[name=state]:contains(Contada)",
        },
        {
            content: "La cantidad contada muestra el cero",
            trigger:
                ".o_field_widget[name=line_ids] .o_data_row:first .o_data_cell[name=qty_counted]:contains(0)",
        },
    ],
});
