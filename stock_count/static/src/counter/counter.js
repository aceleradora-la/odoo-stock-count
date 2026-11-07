/** @odoo-module **/

import { Component, onPatched, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useBus, useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { scanBarcode } from "@web/core/barcode/barcode_dialog";
import { isBarcodeScannerSupported } from "@web/core/barcode/barcode_video_scanner";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

const MODEL = "stock.count.line";
const STATE_LABELS = { ready: "Para contar", counting: "En conteo", review: "Reconteo" };

/**
 * App Recuentos, pensada para el celular y usable en el escritorio:
 * inicio → recuentos a contar → tarjetas por ubicación → cantidades de una ubicación.
 *
 * La ubicación se abre tocando su tarjeta, escaneando su código (lector físico, cámara
 * o escribiéndolo). En la ubicación solo se escribe la cantidad: Enter/Siguiente pasa al
 * producto de abajo. Escanear un producto suma una unidad (o la cantidad del código GS1).
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
        this.dialog = useService("dialog");
        this.barcode = useService("barcode");
        this.pwa = useService("pwa");
        this.scannerSupported = isBarcodeScannerSupported();
        this.focusPending = false;
        this.state = useState({
            screen: "home", // home | list | count | location
            counts: [],
            lines: [],
            countId: false,
            locationId: false,
            manualCode: "",
            showManual: false,
            busy: false,
            loading: true,
        });
        useBus(this.barcode.bus, "barcode_scanned", (ev) => this.handleScan(ev.detail.barcode));
        onWillStart(() => this.load());
        onPatched(() => this.focusFirstEmpty());
    }

    // ------------------------------------------------------------------
    // Datos
    // ------------------------------------------------------------------
    async call(method, args = [], kwargs = {}) {
        this.state.busy = true;
        try {
            return await this.orm.call(MODEL, method, args, kwargs);
        } catch (error) {
            const message = (error.data && error.data.message) || error.message || String(error);
            this.notification.add(message, { type: "danger" });
            throw error;
        } finally {
            this.state.busy = false;
        }
    }

    async load() {
        this.state.loading = true;
        try {
            const data = await this.call("counter_get_data", [false]);
            this.state.counts = data.counts;
            this.state.lines = data.lines;
        } finally {
            this.state.loading = false;
        }
        if (this.state.countId && !this.currentCount) {
            // El recuento ya no es mío o se validó: vuelvo a la lista
            this.state.countId = false;
            this.state.locationId = false;
            this.state.screen = "list";
        }
    }

    get todayLabel() {
        const label = new Date().toLocaleDateString("es-AR", {
            weekday: "long",
            day: "numeric",
            month: "long",
        });
        return label.charAt(0).toUpperCase() + label.slice(1);
    }

    get pendingLabel() {
        const counts = this.state.counts;
        if (!counts.length) {
            return _t("Sin recuentos para contar");
        }
        const pending = this.state.lines.filter((line) => !line.done).length;
        const names = counts.map((c) => c.name).join(", ");
        return `${counts.length} ${counts.length === 1 ? _t("recuento") : _t("recuentos")} · ${pending} ${_t("líneas pendientes")} · ${names}`;
    }

    /** Se ofrece instalar la app mientras no se esté ya dentro de la app instalada. */
    get canInstall() {
        return !this.pwa.isScopedApp && !window.matchMedia("(display-mode: standalone)").matches;
    }

    installApp() {
        const url =
            "/scoped_app?app_id=stock_count&path=" +
            encodeURIComponent("scoped_app/recuentos") +
            "&app_name=" +
            encodeURIComponent("Recuentos");
        window.open(url, "_blank");
    }

    linesOf(countId) {
        return this.state.lines.filter((line) => line.count_id === countId);
    }

    /** Resumen de un recuento para la lista: líneas y ubicaciones hechas / totales. */
    summary(count) {
        const lines = this.linesOf(count.id);
        const locations = this.locationsOf(count.id);
        const done = lines.filter((line) => line.done).length;
        return {
            lines: lines.length,
            done,
            locations: locations.length,
            locationsDone: locations.filter((loc) => loc.status === "closed").length,
            progress: lines.length ? Math.round((done / lines.length) * 100) : 0,
            recount: lines.filter((line) => line.is_recount && !line.done).length,
        };
    }

    stateLabel(count) {
        return STATE_LABELS[count.state] || count.state;
    }

    /** Ubicaciones de un recuento con avance y estado: pending | open | closed. */
    locationsOf(countId) {
        const byId = new Map();
        for (const line of this.linesOf(countId)) {
            if (!byId.has(line.location_id)) {
                byId.set(line.location_id, {
                    id: line.location_id,
                    name: line.location_name,
                    barcode: line.location_barcode,
                    total: 0,
                    done: 0,
                    recount: 0,
                });
            }
            const loc = byId.get(line.location_id);
            loc.total += 1;
            if (line.done) {
                loc.done += 1;
            }
            if (line.is_recount && !line.done) {
                loc.recount += 1;
            }
        }
        for (const loc of byId.values()) {
            loc.status = loc.done === 0 ? "pending" : loc.done === loc.total ? "closed" : "open";
        }
        return [...byId.values()];
    }

    get currentCount() {
        return this.state.counts.find((c) => c.id === this.state.countId);
    }

    get currentSummary() {
        return this.currentCount ? this.summary(this.currentCount) : null;
    }

    get currentLocations() {
        return this.state.countId ? this.locationsOf(this.state.countId) : [];
    }

    get currentLocation() {
        return this.currentLocations.find((loc) => loc.id === this.state.locationId);
    }

    get currentLines() {
        return this.linesOf(this.state.countId).filter(
            (line) => line.location_id === this.state.locationId
        );
    }

    get allClosed() {
        const locations = this.currentLocations;
        return locations.length > 0 && locations.every((loc) => loc.status === "closed");
    }

    // ------------------------------------------------------------------
    // Navegación
    // ------------------------------------------------------------------
    async goHome() {
        await this.load();
        this.state.screen = "home";
        this.state.countId = false;
        this.state.locationId = false;
    }

    async openList() {
        await this.load();
        this.state.screen = "list";
        this.state.countId = false;
        this.state.locationId = false;
    }

    openCount(countId) {
        this.state.countId = countId;
        this.state.locationId = false;
        this.state.showManual = false;
        this.state.screen = "count";
    }

    backToCount() {
        this.state.locationId = false;
        this.state.screen = "count";
    }

    openLocation(locationId) {
        this.state.locationId = locationId;
        this.state.screen = "location";
        this.focusPending = true;
    }

    nextLocation() {
        const locations = this.currentLocations;
        const index = locations.findIndex((loc) => loc.id === this.state.locationId);
        const next =
            locations.slice(index + 1).find((loc) => loc.status !== "closed") ||
            locations.find((loc) => loc.status !== "closed");
        if (next && next.id !== this.state.locationId) {
            this.openLocation(next.id);
        } else {
            this.backToCount();
            this.notification.add(_t("No quedan ubicaciones pendientes."), { type: "success" });
        }
    }

    focusFirstEmpty() {
        if (!this.focusPending) {
            return;
        }
        this.focusPending = false;
        const inputs = [...document.querySelectorAll(".o_sc_location input.o_sc_qty")];
        const target = inputs.find((input) => !input.value) || inputs[inputs.length - 1];
        if (target) {
            target.focus();
            target.select();
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

    async commitQuantity(line, input) {
        const raw = String(input.value).replace(",", ".").trim();
        if (raw === "") {
            return;
        }
        const value = parseFloat(raw);
        if (Number.isNaN(value) || value < 0) {
            this.notification.add(_t("Cantidad inválida."), { type: "danger" });
            input.value = line.done ? line.quantity : "";
            return;
        }
        if (line.done && value === line.quantity) {
            return;
        }
        try {
            const updated = await this.call("counter_set_quantity", [[line.id], value]);
            this._replaceLine(updated);
        } catch {
            input.value = line.done ? line.quantity : "";
        }
        await this._afterLineChange();
    }

    async addOne(line, delta = 1) {
        const updated = await this.call("counter_add_quantity", [[line.id], delta]);
        this._replaceLine(updated);
        await this._afterLineChange();
    }

    /** Si la última cantidad cerró el recuento (pasó a revisión sin reconteos, o se validó),
     *  las líneas desaparecen de mi lista: se recarga y se informa. */
    async _afterLineChange() {
        if (this.linesOf(this.state.countId).every((line) => line.done)) {
            const name = this.currentCount && this.currentCount.name;
            await this.load();
            if (!this.currentCount) {
                this.notification.add(
                    _t("%s: conteo terminado y enviado a revisión.", name),
                    { type: "success", sticky: true }
                );
                this.state.screen = "list";
            }
        }
    }

    onQuantityChange(line, ev) {
        return this.commitQuantity(line, ev.target);
    }

    async onQuantityKeydown(line, ev) {
        if (ev.key !== "Enter") {
            return;
        }
        ev.preventDefault();
        const input = ev.target;
        await this.commitQuantity(line, input);
        const container = input.closest(".o_sc_location");
        if (!container) {
            return;
        }
        const inputs = [...container.querySelectorAll("input.o_sc_qty")];
        const next = inputs[inputs.indexOf(input) + 1];
        if (next) {
            next.focus();
            next.select();
        } else {
            input.blur();
        }
    }

    // ------------------------------------------------------------------
    // Escaneo: lector físico (bus), cámara, o código escrito a mano
    // ------------------------------------------------------------------
    async scan() {
        let code;
        try {
            code = await scanBarcode(this.env);
        } catch (error) {
            this.notification.add(
                _t("No se pudo abrir la cámara: %s. Escribí el código.", error.message || error),
                { type: "warning" }
            );
            this.state.showManual = true;
            return;
        }
        if (code) {
            await this.handleScan(code);
        }
    }

    async submitManual(ev) {
        ev.preventDefault();
        const code = this.state.manualCode.trim();
        if (code) {
            await this.handleScan(code);
        }
    }

    _findLine(predicate) {
        const mine = this.linesOf(this.state.countId);
        let line = mine.find((l) => l.location_id === this.state.locationId && predicate(l));
        if (!line) {
            line = mine.find(predicate);
            if (line) {
                this.openLocation(line.location_id);
            }
        }
        return line;
    }

    async _countScanned(line, quantity) {
        await this.addOne(line, quantity);
        this.notification.add(
            _t("%(product)s: +%(qty)s", { product: line.product_name, qty: quantity }),
            { type: "success" }
        );
    }

    async handleScan(code) {
        code = (code || "").trim();
        if (!code || this.state.loading || !["count", "location"].includes(this.state.screen)) {
            return;
        }
        const lower = code.toLowerCase();
        const location = this.currentLocations.find(
            (loc) =>
                (loc.barcode && loc.barcode.toLowerCase() === lower) ||
                loc.name.toLowerCase() === lower
        );
        if (location) {
            this.state.manualCode = "";
            this.state.showManual = false;
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
            this.state.manualCode = "";
            await this._countScanned(local, 1);
            return;
        }
        const resolved = await this.call("counter_resolve_barcode", [code, this.state.countId]);
        if (resolved.type === "location") {
            const known = this.currentLocations.find((loc) => loc.id === resolved.location_id);
            if (known) {
                this.state.manualCode = "";
                this.state.showManual = false;
                this.openLocation(known.id);
            } else {
                this.notification.add(_t("Esa ubicación no está en este recuento."), {
                    type: "warning",
                });
            }
            return;
        }
        if (resolved.type === "product") {
            const line = this._findLine(
                (l) =>
                    l.product_id === resolved.product_id &&
                    (!resolved.lot_id || l.lot_id === resolved.lot_id)
            );
            if (line) {
                this.state.manualCode = "";
                await this._countScanned(line, resolved.quantity || 1);
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

    // ------------------------------------------------------------------
    // Terminar ubicación / conteo
    // ------------------------------------------------------------------
    async finish(locationOnly) {
        if (!this.state.countId) {
            return;
        }
        const locationId = locationOnly ? this.state.locationId : false;
        const args = [this.state.countId, locationId || false];
        const probe = await this.call("counter_finish", [...args, false]);
        if (probe.done) {
            return this._afterFinish(probe, locationOnly);
        }
        const body = locationOnly
            ? _t(
                  "Hay %s productos sin cantidad en esta ubicación. Se registran como 0 (no hay stock). ¿Terminar la ubicación?",
                  probe.pending
              )
            : _t(
                  "Hay %s productos sin cantidad. Se registran como 0 (no hay stock). ¿Terminar el conteo?",
                  probe.pending
              );
        this.dialog.add(ConfirmationDialog, {
            title: locationOnly ? _t("Terminar ubicación") : _t("Terminar conteo"),
            body,
            confirmLabel: _t("Sí, terminar"),
            cancelLabel: _t("Seguir contando"),
            confirm: async () => {
                const result = await this.call("counter_finish", [...args, true]);
                await this._afterFinish(result, locationOnly);
            },
            cancel: () => {},
        });
    }

    async _afterFinish(result, locationOnly) {
        const name = this.currentCount && this.currentCount.name;
        await this.load();
        if (locationOnly && this.currentCount && result.remaining) {
            this.notification.add(_t("Ubicación terminada."), { type: "success" });
            this.backToCount();
            return;
        }
        if (!this.currentCount || result.state === "done") {
            this.notification.add(
                result.state === "done"
                    ? _t("%s: conteo terminado y validado.", name)
                    : _t("%s: conteo terminado y enviado a revisión.", name),
                { type: "success", sticky: true }
            );
            this.state.countId = false;
            this.state.locationId = false;
            this.state.screen = "list";
            return;
        }
        if (result.recount) {
            this.notification.add(
                _t("Conteo terminado. Quedan %s líneas para recontar.", result.recount),
                { type: "warning", sticky: true }
            );
        }
        this.backToCount();
    }
}

registry.category("actions").add("stock_count_counter", StockCountCounter);
