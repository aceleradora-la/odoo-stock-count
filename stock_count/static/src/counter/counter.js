/** @odoo-module **/

import { Component, onPatched, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useBus, useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { scanBarcode } from "@web/core/barcode/barcode_dialog";
import { isBarcodeScannerSupported } from "@web/core/barcode/barcode_video_scanner";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { formatQty, parseQty, selectOnFocus } from "./number_input";

const MODEL = "stock.count.line";
const STATE_LABELS = { ready: "Para contar", counting: "En conteo", review: "Reconteo" };

/**
 * App Recuentos, pensada para el celular y usable en el escritorio:
 * inicio → recuentos a contar → tarjetas por ubicación → cantidades de una ubicación.
 *
 * La ubicación se abre tocando su tarjeta o escaneando su código (lector físico, cámara
 * o escribiéndolo). En la ubicación solo se escribe la cantidad: Enter pasa al casillero
 * siguiente. Un producto con unidad de recuento (caja, pack…) se carga en dos
 * casilleros: embalajes y sueltas. Escanear un producto suma una unidad; escanear el
 * código de un embalaje suma un embalaje.
 *
 * Las cantidades se guardan en cola, sin bloquear los casilleros: se puede seguir
 * tipeando mientras la anterior viaja al servidor.
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
        this.saveChain = Promise.resolve();
        this.lastSent = new Map();
        this.formatQty = formatQty;
        this.selectOnFocus = selectOnFocus;
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
            saving: 0,
        });
        useBus(this.barcode.bus, "barcode_scanned", (ev) => this.handleScan(ev.detail.barcode));
        onWillStart(() => this.load());
        onPatched(() => this.focusFirstEmpty());
    }

    // ------------------------------------------------------------------
    // Datos
    // ------------------------------------------------------------------
    errorMessage(error) {
        return (error && error.data && error.data.message) || (error && error.message) || String(error);
    }

    warn(message, options = {}) {
        if (navigator.vibrate) {
            navigator.vibrate([200, 100, 200]);
        }
        this.notification.add(message, { type: "warning", ...options });
    }

    async call(method, args = [], kwargs = {}) {
        this.state.busy = true;
        try {
            return await this.orm.call(MODEL, method, args, kwargs);
        } catch (error) {
            this.notification.add(this.errorMessage(error), { type: "danger" });
            throw error;
        } finally {
            this.state.busy = false;
        }
    }

    /** Encola un guardado: salen de a uno y en orden, sin bloquear los casilleros. */
    enqueue(work) {
        this.state.saving += 1;
        const run = this.saveChain.then(work);
        this.saveChain = run
            .catch(() => {})
            .finally(() => {
                this.state.saving -= 1;
            });
        return run;
    }

    async load() {
        this.state.loading = true;
        try {
            const data = await this.call("counter_get_data", [false]);
            this.state.counts = data.counts;
            this.state.lines = data.lines;
            this.lastSent.clear();
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
        await this.saveChain;
        await this.load();
        this.state.screen = "home";
        this.state.countId = false;
        this.state.locationId = false;
    }

    async openList() {
        await this.saveChain;
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
        }
    }

    // ------------------------------------------------------------------
    // Cantidades
    // ------------------------------------------------------------------
    _replaceLine(updated) {
        const index = this.state.lines.findIndex((line) => line.id === updated.id);
        if (index >= 0) {
            this.state.lines[index] = updated;
        } else {
            this.state.lines.push(updated);
        }
    }

    rowOf(line) {
        return document.querySelector(`.o_sc_line[data-line-id="${line.id}"]`);
    }

    /** Valor a mostrar en un casillero: vacío hasta que la línea esté contada. */
    cell(line, kind) {
        if (!line.done) {
            return "";
        }
        return formatQty(kind === "packs" ? line.packs : kind === "loose" ? line.loose : line.quantity);
    }

    totalLabel(line) {
        return `= ${formatQty(line.quantity)} ${line.uom_name}`;
    }

    /** Lee los casilleros del renglón. `null` si no hay nada tipeado; `false` si es inválido. */
    readRow(line) {
        const row = this.rowOf(line);
        if (!row) {
            return null;
        }
        const read = (kind) => {
            const input = row.querySelector(`input[data-kind="${kind}"]`);
            return input ? parseQty(input.value) : null;
        };
        if (line.pack) {
            const packs = read("packs");
            const loose = read("loose");
            if (Number.isNaN(packs) || Number.isNaN(loose)) {
                return false;
            }
            if (packs === null && loose === null) {
                return null;
            }
            return { packs: packs || 0, loose: loose || 0 };
        }
        const quantity = read("qty");
        if (Number.isNaN(quantity)) {
            return false;
        }
        return quantity === null ? null : { quantity };
    }

    restoreRow(line) {
        const row = this.rowOf(line);
        if (!row) {
            return;
        }
        for (const input of row.querySelectorAll("input.o_sc_qty")) {
            input.value = this.cell(line, input.dataset.kind);
        }
    }

    /** Guarda lo tipeado en el renglón. No espera al servidor para devolver el control. */
    commitRow(line) {
        const values = this.readRow(line);
        if (values === null) {
            return Promise.resolve();
        }
        if (values === false) {
            this.warn(_t("Cantidad inválida."));
            this.restoreRow(line);
            return Promise.resolve();
        }
        const key = JSON.stringify(values);
        const current = line.pack
            ? JSON.stringify({ packs: line.packs, loose: line.loose })
            : JSON.stringify({ quantity: line.quantity });
        if (this.lastSent.get(line.id) === key || (line.done && key === current)) {
            return Promise.resolve();
        }
        this.lastSent.set(line.id, key);
        const lineId = line.id;
        return this.enqueue(async () => {
            try {
                const updated = line.pack
                    ? await this.orm.call(MODEL, "counter_set_quantity", [[lineId]], values)
                    : await this.orm.call(MODEL, "counter_set_quantity", [[lineId], values.quantity]);
                this._replaceLine(updated);
            } catch (error) {
                this.lastSent.delete(lineId);
                this.notification.add(this.errorMessage(error), { type: "danger" });
                const fresh = this.state.lines.find((l) => l.id === lineId);
                if (fresh) {
                    this.restoreRow(fresh);
                }
                return;
            }
            await this._afterLineChange();
        });
    }

    /** Se guarda al salir del renglón, no al pasar de embalajes a sueltas. */
    onRowFocusOut(line, ev) {
        const row = ev.currentTarget;
        if (ev.relatedTarget && row.contains(ev.relatedTarget)) {
            return;
        }
        this.commitRow(line);
    }

    onQtyKeydown(line, ev) {
        if (ev.key !== "Enter") {
            return;
        }
        ev.preventDefault();
        const input = ev.target;
        const container = input.closest(".o_sc_location");
        const inputs = container ? [...container.querySelectorAll("input.o_sc_qty")] : [];
        const next = inputs[inputs.indexOf(input) + 1];
        if (next) {
            next.focus(); // si cambia de renglón, el focusout guarda
        } else {
            input.blur();
        }
    }

    /** Suma a la línea (cantidad en la unidad base). Primero guarda lo tipeado. */
    async addQuantity(line, quantity = 1, packId = false) {
        await this.commitRow(line);
        const lineId = line.id;
        return this.enqueue(async () => {
            let updated;
            try {
                const kwargs = packId ? { pack_id: packId } : {};
                updated = await this.orm.call(MODEL, "counter_add_quantity", [[lineId], quantity], kwargs);
            } catch (error) {
                this.notification.add(this.errorMessage(error), { type: "danger" });
                return null;
            }
            this.lastSent.delete(lineId);
            this._replaceLine(updated);
            if (updated.serial_already) {
                this.warn(_t("%s: ese número de serie ya estaba contado.", updated.product_name));
            }
            await this._afterLineChange();
            return updated;
        });
    }

    /** Si la última cantidad cerró el recuento (pasó a revisión sin reconteos, o se validó),
     *  las líneas desaparecen de mi lista: se recarga y se informa. */
    async _afterLineChange() {
        if (!this.state.countId) {
            return;
        }
        const lines = this.linesOf(this.state.countId);
        if (lines.length && lines.every((line) => line.done)) {
            const name = this.currentCount && this.currentCount.name;
            await this.load();
            if (!this.currentCount) {
                this.notification.add(_t("%s: conteo terminado y enviado a revisión.", name), {
                    type: "success",
                    sticky: true,
                });
                this.state.screen = "list";
            }
        }
    }

    /** Cambiar la unidad en la que se cuenta este renglón (unidad base o un embalaje). */
    async changeUnit(line, ev) {
        const packId = parseInt(ev.target.value) || false;
        await this.commitRow(line);
        await this.saveChain;
        try {
            const updated = await this.call("counter_set_pack", [[line.id], packId]);
            this.lastSent.delete(line.id);
            this._replaceLine(updated);
        } catch {
            ev.target.value = line.pack ? line.pack.id : "";
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
            this.warn(
                _t("No se pudo abrir la cámara: %s. Escribí el código.", error.message || error)
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

    async handleScan(code) {
        code = (code || "").trim();
        if (!code || this.state.loading || !["count", "location"].includes(this.state.screen)) {
            return;
        }
        const lower = code.toLowerCase();
        const same = (value) => Boolean(value) && String(value).toLowerCase() === lower;

        // 1) Una ubicación del recuento: se abre
        const location = this.currentLocations.find((loc) => same(loc.barcode) || same(loc.name));
        if (location) {
            this.state.manualCode = "";
            this.state.showManual = false;
            this.openLocation(location.id);
            return;
        }

        // 2) Un producto: primero lo que ya está en pantalla, si no lo resuelve el servidor
        //    con la nomenclatura (GS1, peso, lote, código de embalaje)
        const mine = this.linesOf(this.state.countId);
        let candidates = mine.filter(
            (line) => same(line.product_barcode) || same(line.product_code) || same(line.lot_name)
        );
        const scanned = { quantity: 1, packId: false, productId: false, lotId: false, name: code };
        if (candidates.length) {
            scanned.productId = candidates[0].product_id;
            scanned.name = candidates[0].product_name;
            scanned.lotId = same(candidates[0].lot_name) ? candidates[0].lot_id : false;
        } else {
            const resolved = await this.call("counter_resolve_barcode", [code, this.state.countId]);
            if (resolved.type === "location") {
                const known = this.currentLocations.find((loc) => loc.id === resolved.location_id);
                if (known) {
                    this.state.manualCode = "";
                    this.state.showManual = false;
                    this.openLocation(known.id);
                } else {
                    this.warn(_t("Esa ubicación no está en este recuento."));
                }
                return;
            }
            if (resolved.type !== "product") {
                this.warn(_t("Código no reconocido: %s", code));
                return;
            }
            scanned.productId = resolved.product_id;
            scanned.lotId = resolved.lot_id || false;
            scanned.quantity = resolved.quantity || 1;
            scanned.packId = resolved.pack_id || false;
            scanned.name = resolved.product_name || code;
            candidates = mine.filter(
                (line) =>
                    line.product_id === scanned.productId &&
                    (!scanned.lotId || line.lot_id === scanned.lotId)
            );
        }
        this.state.manualCode = "";
        await this._countScanned(candidates, scanned);
    }

    /**
     * Un producto escaneado se cuenta en la ubicación abierta y en ninguna otra: si ahí no
     * se lo esperaba, se ofrece agregarlo como producto no esperado en vez de contarlo en
     * la ubicación donde el sistema dice que está.
     */
    async _countScanned(candidates, scanned) {
        const count = async (line) => {
            const updated = await this.addQuantity(line, scanned.quantity, scanned.packId);
            if (updated && !updated.serial_already) {
                this.notification.add(`${line.product_name}: +${formatQty(scanned.quantity)}`, {
                    type: "success",
                });
            }
        };
        if (this.state.screen === "location") {
            const here = candidates.filter((line) => line.location_id === this.state.locationId);
            if (here.length === 1) {
                await count(here[0]);
            } else if (here.length > 1) {
                this.warn(
                    _t(
                        "%s tiene varios renglones en esta ubicación (lotes o paquetes). Cargá la cantidad en el que corresponda.",
                        scanned.name
                    )
                );
            } else {
                this._offerUnexpected(candidates, scanned);
            }
            return;
        }
        if (candidates.length === 1) {
            this.openLocation(candidates[0].location_id);
            await count(candidates[0]);
        } else if (candidates.length) {
            this.warn(
                _t("%s está en varias ubicaciones o lotes. Abrí primero la ubicación donde estás.", scanned.name)
            );
        } else {
            this.warn(
                _t(
                    "%s no está en este recuento. Abrí la ubicación donde lo encontraste y escanealo ahí para agregarlo.",
                    scanned.name
                )
            );
        }
    }

    _offerUnexpected(candidates, scanned) {
        const location = this.currentLocation;
        const elsewhere = [...new Set(candidates.map((line) => line.location_name))];
        let body = _t("%(product)s no figura en %(location)s.", {
            product: scanned.name,
            location: location.name,
        });
        if (elsewhere.length) {
            body += " " + _t("El sistema lo espera en %s.", elsewhere.join(", "));
        }
        body += " " + _t("¿Agregarlo acá con cantidad %s?", formatQty(scanned.quantity));
        if (navigator.vibrate) {
            navigator.vibrate([200, 100, 200]);
        }
        this.dialog.add(ConfirmationDialog, {
            title: _t("Producto no esperado"),
            body,
            confirmLabel: _t("Agregar acá"),
            cancelLabel: _t("Cancelar"),
            confirm: () => this._addUnexpected(location.id, scanned),
            cancel: () => {},
        });
    }

    async _addUnexpected(locationId, scanned) {
        const result = await this.call("counter_add_unexpected", [
            this.state.countId,
            locationId,
            scanned.productId,
            scanned.lotId || false,
            scanned.quantity,
        ]);
        if (result.need_lot) {
            // Controlado por lote y el código no lo traía: se pide en el formulario
            await this.openAddProduct({ default_product_id: scanned.productId });
            return;
        }
        this._replaceLine(result.line);
        this.notification.add(_t("%s agregado como producto no esperado.", scanned.name), {
            type: "success",
        });
    }

    // ------------------------------------------------------------------
    // Producto no esperado (formulario)
    // ------------------------------------------------------------------
    async openAddProduct(defaults = {}) {
        if (!this.state.countId) {
            return;
        }
        await this.saveChain;
        await this.action.doAction("stock_count.action_stock_count_add_product", {
            additionalContext: {
                default_count_id: this.state.countId,
                default_location_id: this.state.locationId || false,
                ...defaults,
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
        await this.saveChain;
        const locationId = locationOnly ? this.state.locationId : false;
        const args = [this.state.countId, locationId || false];
        const probe = await this.call("counter_finish", [...args, false]);
        if (probe.done) {
            return this._afterFinish(probe, locationOnly);
        }
        const body = locationOnly
            ? _t(
                  "Hay %s productos sin cantidad en esta ubicación. Se registran como 0 (no hay stock) y los confirma un reconteo o el supervisor. ¿Terminar la ubicación?",
                  probe.pending
              )
            : _t(
                  "Hay %s productos sin cantidad. Se registran como 0 (no hay stock) y los confirma un reconteo o el supervisor. ¿Terminar el conteo?",
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
            this.warn(_t("Conteo terminado. Quedan %s líneas para recontar.", result.recount), {
                sticky: true,
            });
        } else if (!locationOnly && result.remaining) {
            this.notification.add(
                _t(
                    "Lo tuyo quedó terminado. Quedan %s productos en ubicaciones que no contaste: son de otro contador.",
                    result.remaining
                ),
                { type: "info", sticky: true }
            );
        }
        this.backToCount();
    }
}

registry.category("actions").add("stock_count_counter", StockCountCounter);
