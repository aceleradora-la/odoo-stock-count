/** @odoo-module **/

import { Component, onWillStart, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useBus, useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { scanBarcode } from "@web/core/barcode/barcode_dialog";
import { isBarcodeScannerSupported } from "@web/core/barcode/barcode_video_scanner";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

/**
 * Vista móvil del contador.
 *
 * Muestra las líneas a contar del usuario (asignadas a él, o libres de los recuentos
 * donde es contador) agrupadas por ubicación, con un campo de cantidad grande, botón +1
 * y escaneo por tres vías: lector físico (servicio de código de barras de Odoo, sin
 * necesidad de enfocar nada), cámara del dispositivo (lector de vídeo del núcleo web) y
 * campo de texto para tipear. Escanear una ubicación la abre; escanear un producto suma
 * una unidad (o la cantidad embebida en un código GS1) a su línea.
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
        this.barcode = useService("barcode");
        this.dialog = useService("dialog");
        this.scanInput = useRef("scanInput");
        this.cameraSupported = isBarcodeScannerSupported();
        useBus(this.barcode.bus, "barcode_scanned", (ev) => this.handleScan(ev.detail.barcode));
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

    // ------------------------------------------------------------------
    // Terminar
    // ------------------------------------------------------------------
    async finish(locationOnly) {
        if (!this.state.countId) {
            return;
        }
        const locationId = locationOnly ? this.state.locationId : false;
        const args = [this.state.countId, locationId || false];
        const probe = await this.orm.call("stock.count.line", "counter_finish", [...args, false]);
        if (probe.done) {
            return this._afterFinish(probe, locationOnly);
        }
        const body = locationOnly
            ? _t(
                  "Hay %s productos sin cantidad en esta ubicación. Se registrarán como 0 (no hay stock). ¿Terminar la ubicación?",
                  probe.pending
              )
            : _t(
                  "Hay %s productos sin cantidad. Se registrarán como 0 (no hay stock). ¿Terminar el conteo?",
                  probe.pending
              );
        this.dialog.add(ConfirmationDialog, {
            title: locationOnly ? _t("Terminar ubicación") : _t("Terminar conteo"),
            body,
            confirmLabel: _t("Sí, terminar"),
            cancelLabel: _t("Volver"),
            confirm: async () => {
                const result = await this.orm.call("stock.count.line", "counter_finish", [
                    ...args,
                    true,
                ]);
                await this._afterFinish(result, locationOnly);
            },
        });
    }

    async _afterFinish(result, locationOnly) {
        await this.load();
        this.state.locationId = false;
        if (locationOnly && result.remaining) {
            this.notification.add(_t("Ubicación terminada."), { type: "success" });
            return;
        }
        if (result.recount) {
            this.notification.add(
                _t(
                    "Conteo terminado. El recuento está en revisión y tenés %s líneas para recontar.",
                    result.recount
                ),
                { type: "warning", sticky: true }
            );
        } else if (result.state === "review") {
            this.notification.add(_t("Conteo terminado y enviado a revisión."), {
                type: "success",
                sticky: true,
            });
        } else {
            this.notification.add(_t("Tus líneas quedaron contadas."), { type: "success" });
        }
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
    /** Enter en el campo de texto: mismo camino que un lector físico. */
    onScan(ev) {
        if (ev.key !== "Enter") {
            return;
        }
        ev.preventDefault();
        const code = this.state.scan.trim();
        this.state.scan = "";
        return this.handleScan(code);
    }

    /** Cámara del dispositivo (lector de vídeo del núcleo de Odoo). */
    async openCamera() {
        try {
            const code = await scanBarcode(this.env);
            if (code) {
                await this.handleScan(code);
            }
        } catch (error) {
            this.notification.add(
                _t("No se pudo usar la cámara: %s", error.message || error),
                { type: "danger" }
            );
        }
    }

    /** Busca la línea del producto (y lote) primero en la ubicación abierta. */
    _findLine(predicate) {
        let line = this.currentLines.find(predicate);
        if (!line) {
            line = this.state.lines.find(predicate);
            if (line) {
                this.openLocation(line.location_id);
            }
        }
        return line;
    }

    async _countLine(line, quantity) {
        if (this.state.scanAddsOne || quantity !== 1) {
            await this.addOne(line, quantity);
        } else {
            const input = document.querySelector(`[data-line-id="${line.id}"] input`);
            if (input) {
                input.focus();
                input.select();
            }
        }
    }

    async handleScan(code) {
        code = (code || "").trim();
        if (!code || this.state.loading) {
            return;
        }
        const lower = code.toLowerCase();
        // 1) Lo que ya tenemos en pantalla, sin ir al servidor
        const location = this.locations.find(
            (l) => (l.barcode && l.barcode.toLowerCase() === lower) || l.name.toLowerCase() === lower
        );
        if (location) {
            this.openLocation(location.id);
            return;
        }
        const local = this._findLine(
            (line) =>
                (line.product_barcode && line.product_barcode.toLowerCase() === lower) ||
                (line.product_code && line.product_code.toLowerCase() === lower) ||
                (line.lot_name && line.lot_name.toLowerCase() === lower)
        );
        if (local) {
            await this._countLine(local, 1);
            return;
        }
        // 2) El servidor interpreta el código con la nomenclatura (GS1, peso, lote…)
        const resolved = await this.orm.call("stock.count.line", "counter_resolve_barcode", [
            code,
            this.state.countId || false,
        ]);
        if (resolved.type === "location") {
            const known = this.locations.find((l) => l.id === resolved.location_id);
            if (known) {
                this.openLocation(known.id);
            } else {
                this.notification.add(_t("Esa ubicación no está en tu recuento."), { type: "warning" });
            }
            return;
        }
        if (resolved.type === "product") {
            const line = this._findLine(
                (line) =>
                    line.product_id === resolved.product_id &&
                    (!resolved.lot_id || line.lot_id === resolved.lot_id)
            );
            if (line) {
                await this._countLine(line, resolved.quantity || 1);
                return;
            }
            this.notification.add(
                _t("El producto escaneado no está en el recuento. Si está en la estantería, usá 'Producto no esperado'."),
                { type: "warning" }
            );
            return;
        }
        this.notification.add(_t("Código no reconocido: %s", code), { type: "warning" });
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
