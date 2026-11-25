/** @odoo-module **/

import { registry } from "@web/core/registry";
import { FloatField, floatField } from "@web/views/fields/float/float_field";

/**
 * Cantidad contada en las listas de escritorio.
 *
 * - Una línea sin contar muestra la celda vacía en lugar de "0,00".
 * - Escribir 0 en una línea sin contar la deja contada en cero. Un campo numérico
 *   común no guarda un valor igual al que ya tenía, y la línea quedaba pendiente.
 */
export class StockCountQtyField extends FloatField {
    static props = {
        ...FloatField.props,
        emptyStates: { type: Array, optional: true },
        emptyUnless: { type: String, optional: true },
    };
    static defaultProps = {
        ...FloatField.defaultProps,
        emptyStates: ["pending"],
    };

    setup() {
        super.setup();
        this.forcing = false;
    }

    /** La cantidad de esta columna todavía no se cargó. */
    get isUncounted() {
        const data = this.props.record.data;
        if (this.props.emptyUnless) {
            return !data[this.props.emptyUnless];
        }
        return this.props.emptyStates.includes(data.state);
    }

    /** El usuario ya escribió una cantidad que todavía no se guardó. */
    get hasPendingChange() {
        const changes = this.props.record._changes || {};
        return this.forcing || this.props.name in changes;
    }

    get formattedValue() {
        if (this.isUncounted && !this.hasPendingChange) {
            return "";
        }
        return super.formattedValue;
    }

    parse(value) {
        const parsed = super.parse(value);
        if (
            value.trim() !== "" &&
            parsed === this.value &&
            !this.props.readonly &&
            this.isUncounted &&
            !this.hasPendingChange
        ) {
            // Mismo valor que el guardado (0): se registra igual como cambio para que
            // el servidor reciba la cantidad y marque la línea como contada.
            this.forcing = true;
            this.props.record.update({ [this.props.name]: parsed }).finally(() => {
                this.forcing = false;
            });
        }
        return parsed;
    }
}

export const stockCountQtyField = {
    ...floatField,
    component: StockCountQtyField,
    extractProps: (fieldInfo, dynamicInfo) => ({
        ...floatField.extractProps(fieldInfo, dynamicInfo),
        emptyStates: fieldInfo.options.empty_states,
        emptyUnless: fieldInfo.options.empty_unless,
    }),
};

registry.category("fields").add("stock_count_qty", stockCountQtyField);
