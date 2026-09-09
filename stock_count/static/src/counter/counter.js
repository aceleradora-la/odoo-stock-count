/** @odoo-module **/

import { Component, onWillStart, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

/**
 * Vista móvil del contador.
 *
 * Muestra las líneas a contar del usuario (asignadas a él, o libres de los recuentos
 * donde es contador) agrupadas por ubicación, con un campo de cantidad grande, botón +1
 * y un campo de escaneo que reacciona a lectores físicos o de cámara: escanear una
 * ubicación la abre; escanear un producto suma una unidad a su línea.
 *
 * Nunca pide al servidor la cantidad teórica: el conteo desde acá es siempre "a ciegas"
 * en pantalla, y en conteo ciego el ORM además la devuelve en cero.
 */
export class StockCountCounter extends Component {
    static template = "stock_count.Counter";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.scanInput = useRef("scanInput");
        this.state = useState({
            loading: true,
            counts: [],
            lines: [],
            countId: false,
            locationId: false,
            scan: "",
            scanAddsOne: true,
            saving: {},
        });
        onWillStart(() => this.load());
    }

    // ------------------------------------------------------------------
    // Datos
    // ------------------------------------------------------------------
    async load(countId) {
        this.state.loading = true;
        const data = await this.orm.call("stock.count.line", "counter_get_data", [
            countId || this.state.countId || false,
        ]);
        this.state.counts = data.counts;
        if (!this.state.countId && data.counts.length === 1) {
            this.state.countId = data.counts[0].id;
        }
        this.state.lines = data.lines.filter(
            (line) => !this.state.countId || line.count_id === this.state.countId
        );
        if (this.state.locationId && !this.locations.some((l) => l.id === this.state.locationId)) {
            this.state.locationId = false;
        }
        this.state.loading = false;
    }

    get currentCount() {
        return this.state.counts.find((c) => c.id === this.state.countId);
    }

    /** Ubicaciones con líneas, en orden, con avance. */
    get locations() {
        const byId = new Map();
        for (const line of this.state.lines) {
            if (!byId.has(line.location_id)) {
                byId.set(line.location_id, {
                    id: line.location_id,
                    name: line.location_name,
                    barcode: line.location_barcode,
                    total: 0,
                    done: 0,
                });
            }
            const loc = byId.get(line.location_id);
            loc.total += 1;
            if (line.done) {
                loc.done += 1;
            }
        }
        return [...byId.values()];
    }

    get currentLocation() {
        return this.locations.find((l) => l.id === this.state.locationId);
    }

    get currentLines() {
        return this.state.lines.filter((line) => line.location_id === this.state.locationId);
    }

    get pendingTotal() {
        return this.state.lines.filter((line) => !line.done).length;
    }

    // ------------------------------------------------------------------
    // Navegación
    // ------------------------------------------------------------------
    async selectCount(countId) {
        this.state.countId = countId;
        this.state.locationId = false;
        await this.load(countId);
    }

    openLocation(locationId) {
        this.state.locationId = locationId;
        this.focusScan();
    }

    backToLocations() {
        this.state.locationId = false;
    }

    nextLocation() {
        const locations = this.locations;
        const index = locations.findIndex((l) => l.id === this.state.locationId);
        const next =
            locations.slice(index + 1).find((l) => l.done < l.total) ||
            locations.find((l) => l.done < l.total);
        if (next && next.id !== this.state.locationId) {
            this.openLocation(next.id);
        } else {
            this.state.locationId = false;
            this.notification.add(_t("No quedan ubicaciones pendientes."), { type: "success" });
        }
    }

    focusScan() {
        if (this.scanInput.el) {
            this.scanInput.el.focus();
        }
    }

    // ------------------------------------------------------------------
    // Cantidades
    // ------------------------------------------------------------------
    _replaceLine(updated) {
        const index = this.state.lines.findIndex((line) => line.id === updated.id);
        if (index >= 0) {
            this.state.lines[index] = updated;
        }
    }

    async setQuantity(line, value) {
        const quantity = parseFloat(String(value).replace(",", "."));
        if (Number.isNaN(quantity) || quantity < 0) {
            this.notification.add(_t("Cantidad inválida."), { type: "danger" });
            return;
        }
        this.state.saving[line.id] = true;
        try {
            const updated = await this.orm.call("stock.count.line", "counter_set_quantity", [
                [line.id],
                quantity,
            ]);
            this._replaceLine(updated);
        } finally {
            delete this.state.saving[line.id];
        }
    }

    async addOne(line, delta = 1) {
        this.state.saving[line.id] = true;
        try {
            const updated = await this.orm.call("stock.count.line", "counter_add_quantity", [
                [line.id],
                delta,
            ]);
            this._replaceLine(updated);
        } finally {
            delete this.state.saving[line.id];
        }
    }

    onQuantityChange(line, ev) {
        return this.setQuantity(line, ev.target.value);
    }

    onQuantityKeydown(line, ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            ev.target.blur();
        }
    }

    // ------------------------------------------------------------------
    // Escaneo
    // ------------------------------------------------------------------
    async onScan(ev) {
        if (ev.key !== "Enter") {
            return;
        }
        ev.preventDefault();
        const code = this.state.scan.trim();
        this.state.scan = "";
        if (!code) {
            return;
        }
        const lower = code.toLowerCase();
        const location = this.locations.find(
            (l) => (l.barcode && l.barcode.toLowerCase() === lower) || l.name.toLowerCase() === lower
        );
        if (location) {
            this.openLocation(location.id);
            return;
        }
        const matches = (line) =>
            (line.product_barcode && line.product_barcode.toLowerCase() === lower) ||
            (line.product_code && line.product_code.toLowerCase() === lower) ||
            (line.lot_name && line.lot_name.toLowerCase() === lower);
        let line = this.currentLines.find(matches);
        if (!line) {
            line = this.state.lines.find(matches);
            if (line) {
                this.openLocation(line.location_id);
            }
        }
        if (!line) {
            this.notification.add(
                _t("%s no está en el recuento. Si está en la estantería, usá 'Producto no esperado'.", code),
                { type: "warning" }
            );
            return;
        }
        if (this.state.scanAddsOne) {
            await this.addOne(line, 1);
        } else {
            const input = document.querySelector(`[data-line-id="${line.id}"] input`);
            if (input) {
                input.focus();
                input.select();
            }
        }
    }

    // ------------------------------------------------------------------
    // Producto no esperado
    // ------------------------------------------------------------------
    async openAddProduct() {
        if (!this.state.countId) {
            return;
        }
        await this.action.doAction("stock_count.action_stock_count_add_product", {
            additionalContext: {
                default_count_id: this.state.countId,
                default_location_id: this.state.locationId || false,
            },
            onClose: () => this.load(),
        });
    }
}

registry.category("actions").add("stock_count_counter", StockCountCounter);
