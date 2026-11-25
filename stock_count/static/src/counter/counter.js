/** @odoo-module **/

import { Component, onPatched, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useBus, useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { scanBarcode } from "@web/core/barcode/barcode_dialog";
import { isBarcodeScannerSupported } from "@web/core/barcode/barcode_video_scanner";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { formatQty, parseQty, selectOnFocus } from "./number_input";
import { offlineStore } from "./offline_store";

const MODEL = "stock.count.line";
const COUNT_MODEL = "stock.count";
const STATE_LABELS = { ready: "Para contar", counting: "En conteo", review: "Reconteo" };

/** Un pedido falló sin respuesta del servidor (sin señal), no por una regla de negocio. */
function isNetworkError(error) {
    return !(error && (error.data || error.exceptionName));
}

const copy = (value) => JSON.parse(JSON.stringify(value));

// Un lector físico "tipea" el código mucho más rápido que una persona.
const SCAN_GAP_MS = 50;
const SCAN_MIN_LENGTH = 4;

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
 * Sin conexión: cada cantidad se guarda primero en el teléfono (cola en IndexedDB), se
 * ve aplicada en pantalla y viaja al servidor en orden cuando hay señal. Se puede seguir
 * contando en una zona sin wifi; lo que necesita al servidor (terminar, producto no
 * esperado, supervisar) espera a que la cola se vacíe.
 *
 * Nunca pide al servidor la cantidad teórica: el conteo desde acá es siempre "a ciegas"
 * en pantalla, y en conteo ciego el ORM además la devuelve en cero. El tablero del
 * supervisor es otra pantalla, con sus propios datos.
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
        this.flushing = null;
        this.saving = Promise.resolve(); // escrituras de la cola en el teléfono, en orden
        this.needsReload = false;
        this.serverLines = new Map(); // última versión de cada línea según el servidor
        this.pendingSnapshot = new Set();
        this.burst = null; // ráfaga de teclas en un casillero: puede ser un lector
        this.valueBefore = new WeakMap();
        this.formatQty = formatQty;
        this.selectOnFocus = selectOnFocus;
        this.state = useState({
            screen: "home", // home | list | count | location | super | super_count
            counts: [],
            lines: [],
            countId: false,
            locationId: false,
            manualCode: "",
            showManual: false,
            filter: "",
            onlyPending: false,
            busy: false,
            loading: true,
            online: navigator.onLine !== false,
            queue: [], // cantidades todavía no enviadas al servidor
            isManager: false,
            supervision: [],
            superCountId: false,
        });
        useBus(this.barcode.bus, "barcode_scanned", (ev) => this.handleScan(ev.detail.barcode));
        this.onOnline = () => {
            this.state.online = true;
            this.flush();
        };
        this.onOffline = () => {
            this.state.online = false;
        };
        window.addEventListener("online", this.onOnline);
        window.addEventListener("offline", this.onOffline);
        this.retryTimer = setInterval(() => {
            if (this.state.queue.length) {
                this.flush();
            }
        }, 15000);
        onWillUnmount(() => {
            window.removeEventListener("online", this.onOnline);
            window.removeEventListener("offline", this.onOffline);
            clearInterval(this.retryTimer);
        });
        onWillStart(async () => {
            const stored = await offlineStore.queueAll().catch(() => []);
            this.state.queue = stored.map((op) => ({ uid: `stored-${op.id}`, ...op }));
            await this.load();
            this.flush();
        });
        onPatched(() => this.focusFirstEmpty());
    }

    // ------------------------------------------------------------------
    // Servidor
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

    /** Pedido que necesita respuesta ahora. Lanza `offline` si no hay señal. */
    async call(method, args = [], kwargs = {}, model = MODEL) {
        this.state.busy = true;
        try {
            const result = await this.orm.silent.call(model, method, args, kwargs);
            this.state.online = true;
            return result;
        } catch (error) {
            if (isNetworkError(error)) {
                this.state.online = false;
                this.warn(_t("Sin conexión. Probá de nuevo cuando vuelva la señal."));
            } else {
                this.notification.add(this.errorMessage(error), { type: "danger" });
            }
            throw error;
        } finally {
            this.state.busy = false;
        }
    }

    /** Lo que necesita al servidor espera a que no queden cantidades sin enviar. */
    async requireOnline() {
        await this.flush();
        if (this.state.queue.length) {
            this.warn(
                _t(
                    "Sin conexión: hay %s cantidades guardadas en el teléfono sin enviar. Probá de nuevo cuando vuelva la señal.",
                    this.state.queue.length
                )
            );
            return false;
        }
        return true;
    }

    // ------------------------------------------------------------------
    // Datos y cola sin conexión
    // ------------------------------------------------------------------
    async load() {
        this.state.loading = true;
        try {
            let data;
            try {
                data = await this.orm.silent.call(MODEL, "counter_get_data", [false]);
                this.state.online = true;
                offlineStore.cacheSet("data", data);
            } catch (error) {
                if (!isNetworkError(error)) {
                    this.notification.add(this.errorMessage(error), { type: "danger" });
                    throw error;
                }
                this.state.online = false;
                data = (await offlineStore.cacheGet("data")) || {
                    counts: [],
                    lines: [],
                    is_manager: false,
                };
            }
            this.state.counts = data.counts;
            this.state.isManager = Boolean(data.is_manager);
            this.serverLines = new Map(data.lines.map((line) => [line.id, line]));
            this.state.lines = data.lines.map((line) => this.withQueue(copy(line)));
        } finally {
            this.state.loading = false;
        }
        if (this.state.countId && !this.currentCount) {
            // El recuento ya no es mío o se validó: vuelvo a la lista
            this.state.countId = false;
            this.state.locationId = false;
            if (["count", "location"].includes(this.state.screen)) {
                this.state.screen = "list";
            }
        }
    }

    saveCache() {
        offlineStore.cacheSet("data", {
            counts: this.state.counts,
            lines: [...this.serverLines.values()],
            is_manager: this.state.isManager,
        });
    }

    /** Aplica en pantalla una cantidad guardada en el teléfono, como lo hará el servidor. */
    applyOp(line, op) {
        const factor = line.pack ? line.pack.factor : 0;
        const split = (quantity) => {
            const packs = factor > 0 ? Math.floor((quantity + 1e-9) / factor) : 0;
            return [packs, Math.round((quantity - packs * factor) * 1000) / 1000];
        };
        if (op.kind === "set") {
            if (op.values.packs !== undefined) {
                line.packs = op.values.packs;
                line.loose = op.values.loose;
                line.quantity = line.packs * factor + line.loose;
            } else {
                line.quantity = op.values.quantity;
                if (line.pack) {
                    [line.packs, line.loose] = split(line.quantity);
                }
            }
        } else if (line.is_serial) {
            line.quantity = 1;
        } else if (line.pack) {
            if (op.packId && op.packId === line.pack.id && factor > 0) {
                line.packs += Math.round(op.quantity / factor);
            } else {
                line.loose += op.quantity;
            }
            line.quantity = line.packs * factor + line.loose;
        } else {
            line.quantity = (line.quantity || 0) + op.quantity;
        }
        line.done = true;
        return line;
    }

    /** Una línea del servidor más lo que todavía está en la cola para ella. */
    withQueue(line) {
        for (const op of this.state.queue) {
            if (op.lineId === line.id) {
                this.applyOp(line, op);
            }
        }
        return line;
    }

    _replaceLine(line) {
        const index = this.state.lines.findIndex((entry) => entry.id === line.id);
        if (index >= 0) {
            this.state.lines[index] = line;
        } else {
            this.state.lines.push(line);
        }
    }

    /** Llegó la versión del servidor de una línea: reemplaza a la de pantalla. */
    setServerLine(updated) {
        const { serial_already, recount_requested, ...line } = updated;
        this.serverLines.set(line.id, line);
        this._replaceLine(this.withQueue(copy(line)));
    }

    /**
     * Guarda una cantidad en el teléfono, la muestra aplicada y la manda cuando se pueda.
     * Entra a la cola en el acto (sin esperar al disco): así "Terminar", que se toca justo
     * después de escribir la última cantidad, siempre la encuentra en la cola.
     * `uid` identifica el pedido: si se reenvía porque se cortó la señal antes de recibir
     * la respuesta, el servidor no lo suma dos veces.
     */
    pushOp(op) {
        op.uid = `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
        this.state.queue.push(op);
        const line = this.state.lines.find((entry) => entry.id === op.lineId);
        if (line) {
            this.applyOp(line, op);
        }
        this.saving = this.saving
            .then(() => offlineStore.queueAdd(op))
            .then((id) => {
                const queued = this.state.queue.find((entry) => entry.uid === op.uid);
                if (queued) {
                    queued.id = id;
                } else {
                    return offlineStore.queueDelete(id); // ya se envió mientras se guardaba
                }
            })
            .catch(() => {}); // sin disco, la cola sigue en memoria
        this.flush();
    }

    async dropOp(op) {
        await this.saving;
        const queued = this.state.queue.find((entry) => entry.uid === op.uid) || op;
        this.state.queue = this.state.queue.filter((entry) => entry.uid !== op.uid);
        if (queued.id !== undefined) {
            await offlineStore.queueDelete(queued.id).catch(() => {});
        }
    }

    /** Manda al servidor lo guardado, en orden. Corta al primer pedido sin señal. */
    flush() {
        if (!this.flushing) {
            this.flushing = this._flush().finally(() => {
                this.flushing = null;
            });
        }
        return this.flushing;
    }

    async _flush() {
        let changed = false;
        while (this.state.queue.length) {
            const op = this.state.queue[0];
            let updated;
            try {
                if (op.kind === "add") {
                    const kwargs = { op_uid: op.uid };
                    if (op.packId) {
                        kwargs.pack_id = op.packId;
                    }
                    updated = await this.orm.silent.call(
                        MODEL,
                        "counter_add_quantity",
                        [[op.lineId], op.quantity],
                        kwargs
                    );
                } else if (op.values.packs !== undefined) {
                    updated = await this.orm.silent.call(
                        MODEL,
                        "counter_set_quantity",
                        [[op.lineId]],
                        op.values
                    );
                } else {
                    updated = await this.orm.silent.call(MODEL, "counter_set_quantity", [
                        [op.lineId],
                        op.values.quantity,
                    ]);
                }
                this.state.online = true;
            } catch (error) {
                if (isNetworkError(error)) {
                    this.state.online = false;
                    return;
                }
                // El servidor la rechazó (la línea ya se aprobó, el recuento se cerró…): se
                // descarta, se avisa y se vuelve a traer el estado real.
                await this.dropOp(op);
                this.warn(`${op.label}: ${this.errorMessage(error)}`, { sticky: true });
                this.needsReload = true;
                continue;
            }
            await this.dropOp(op);
            this.setServerLine(updated);
            changed = true;
            if (updated.serial_already) {
                this.warn(_t("%s: ese número de serie ya estaba contado.", updated.product_name));
            }
            if (updated.recount_requested) {
                this.warn(
                    _t(
                        "%s: la cantidad no coincide con el sistema. Contalo de nuevo y cargá el segundo conteo.",
                        updated.product_name
                    ),
                    { sticky: true }
                );
            }
        }
        this.saveCache();
        if (this.needsReload) {
            this.needsReload = false;
            await this.load();
        } else if (changed) {
            await this._afterLineChange();
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

    /** Renglones a la vista: los de la ubicación, pasados por el buscador y el filtro. */
    get visibleLines() {
        let lines = this.currentLines;
        const text = this.state.filter.trim().toLowerCase();
        if (text) {
            lines = lines.filter((line) =>
                [line.product_name, line.product_code, line.product_barcode, line.lot_name, line.package_name].some(
                    (value) => value && String(value).toLowerCase().includes(text)
                )
            );
        }
        if (this.state.onlyPending) {
            lines = lines.filter((line) => this.pendingSnapshot.has(line.id));
        }
        return lines;
    }

    /** Enter en el buscador: un código escaneado se cuenta; si quedó un solo renglón,
     *  el foco pasa a su casillero. */
    onSearchKeydown(ev) {
        if (ev.key !== "Enter") {
            return;
        }
        ev.preventDefault();
        const scan = this.takeScan(ev.target);
        if (scan) {
            this.state.filter = "";
            this.handleScan(scan.code);
            return;
        }
        if (this.visibleLines.length === 1) {
            this.focusPending = true;
            this.focusFirstEmpty();
        } else {
            ev.target.blur();
        }
    }

    clearFilter() {
        this.state.filter = "";
        this.focusPending = true;
    }

    /** "Solo pendientes" fija la lista al activarlo: lo que se va contando no desaparece
     *  de abajo de los dedos. */
    togglePending() {
        this.state.onlyPending = !this.state.onlyPending;
        this.pendingSnapshot = new Set(
            this.currentLines.filter((line) => !line.done).map((line) => line.id)
        );
        this.focusPending = this.state.onlyPending;
    }

    get allClosed() {
        const locations = this.currentLocations;
        return locations.length > 0 && locations.every((loc) => loc.status === "closed");
    }

    // ------------------------------------------------------------------
    // Navegación
    // ------------------------------------------------------------------
    async goHome() {
        await this.flush();
        await this.load();
        this.state.screen = "home";
        this.state.countId = false;
        this.state.locationId = false;
    }

    async openList() {
        await this.flush();
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
        this.state.filter = "";
        this.state.onlyPending = false;
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

    isUnsent(line) {
        return this.state.queue.some((op) => op.lineId === line.id);
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

    /** Guarda lo tipeado en el renglón: primero en el teléfono, después viaja solo. */
    async commitRow(line) {
        const values = this.readRow(line);
        if (values === null) {
            return;
        }
        if (values === false) {
            this.warn(_t("Cantidad inválida."));
            this.restoreRow(line);
            return;
        }
        if (line.is_serial && values.quantity !== 0 && values.quantity !== 1) {
            this.warn(_t("Un número de serie solo puede estar (1) o no estar (0)."));
            this.restoreRow(line);
            return;
        }
        const same = line.pack
            ? values.packs === line.packs && values.loose === line.loose
            : values.quantity === line.quantity;
        if (line.done && same) {
            return;
        }
        this.pushOp({ kind: "set", lineId: line.id, values, label: line.product_name });
    }

    // Con el foco en un casillero, el lector físico escribe el código ahí adentro (el
    // servicio de códigos de barras de Odoo no interviene en campos editables). Sin este
    // control, el código quedaría guardado como cantidad. Una ráfaga de teclas seguida
    // de Enter o Tab es un escaneo: se devuelve el casillero a lo que tenía y se procesa
    // como código.
    onFieldFocus(ev) {
        selectOnFocus(ev);
        this.burst = null;
        this.valueBefore.set(ev.target, ev.target.value);
    }

    onTyping(ev) {
        const input = ev.target;
        const now = performance.now();
        const typed = !ev.inputType || ["insertText", "insertCompositionText"].includes(ev.inputType);
        const burst = this.burst;
        if (!typed) {
            this.burst = null;
        } else if (burst && burst.input === input && now - burst.last < SCAN_GAP_MS) {
            burst.text += ev.data || "";
            burst.last = now;
        } else {
            this.burst = {
                input,
                before: this.valueBefore.get(input) || "",
                text: ev.data || "",
                last: now,
            };
        }
        this.valueBefore.set(input, input.value);
    }

    /** Si lo último que entró al casillero lo tipeó un lector, devuelve el código. */
    takeScan(input) {
        const burst = this.burst;
        this.burst = null;
        if (
            !burst ||
            burst.input !== input ||
            burst.text.trim().length < SCAN_MIN_LENGTH ||
            performance.now() - burst.last > 300
        ) {
            return null;
        }
        return { code: burst.text.trim(), before: burst.before };
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
        if (ev.key !== "Enter" && ev.key !== "Tab") {
            return;
        }
        const input = ev.target;
        const scan = this.takeScan(input);
        if (scan) {
            ev.preventDefault();
            input.value = scan.before;
            this.valueBefore.set(input, scan.before);
            this.handleScan(scan.code);
            return;
        }
        if (ev.key !== "Enter") {
            return;
        }
        ev.preventDefault();
        const container = input.closest(".o_sc_location");
        const inputs = container ? [...container.querySelectorAll("input.o_sc_qty")] : [];
        const next = inputs[inputs.indexOf(input) + 1];
        if (next) {
            next.focus(); // si cambia de renglón, el focusout guarda
        } else {
            input.blur();
        }
    }

    /** Suma a la línea (cantidad en la unidad base). Primero guarda lo tipeado.
     *  Devuelve false si no sumó nada (un número de serie ya contado). */
    async addQuantity(line, quantity = 1, packId = false) {
        await this.commitRow(line);
        const current = this.state.lines.find((entry) => entry.id === line.id) || line;
        if (current.is_serial && current.done && current.quantity >= 1) {
            this.warn(_t("%s: ese número de serie ya estaba contado.", current.product_name));
            return false;
        }
        this.pushOp({
            kind: "add",
            lineId: line.id,
            quantity,
            packId,
            label: line.product_name,
        });
        return true;
    }

    /** Si la última cantidad cerró el recuento (pasó a revisión sin reconteos, o se validó),
     *  las líneas desaparecen de mi lista: se recarga y se informa. */
    async _afterLineChange() {
        if (!this.state.countId || this.state.queue.length) {
            return;
        }
        const lines = this.linesOf(this.state.countId);
        if (lines.length && lines.every((line) => line.done)) {
            const name = this.currentCount && this.currentCount.name;
            await this.load();
            if (!this.currentCount && name) {
                this.notification.add(_t("%s: conteo terminado y enviado a revisión.", name), {
                    type: "success",
                    sticky: true,
                });
            }
        }
    }

    /** Cambiar la unidad en la que se cuenta este renglón (unidad base o un embalaje). */
    async changeUnit(line, ev) {
        const select = ev.target;
        const packId = parseInt(select.value) || false;
        const revert = () => {
            select.value = line.pack ? line.pack.id : "";
        };
        await this.commitRow(line);
        if (!(await this.requireOnline())) {
            revert();
            return;
        }
        try {
            this.setServerLine(await this.call("counter_set_pack", [[line.id], packId]));
            this.saveCache();
        } catch {
            revert();
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
            let resolved;
            try {
                resolved = await this.call("counter_resolve_barcode", [code, this.state.countId]);
            } catch {
                return; // sin señal no se puede identificar: ya se avisó
            }
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
            if (await this.addQuantity(line, scanned.quantity, scanned.packId)) {
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
        if (!(await this.requireOnline())) {
            return;
        }
        let result;
        try {
            result = await this.call("counter_add_unexpected", [
                this.state.countId,
                locationId,
                scanned.productId,
                scanned.lotId || false,
                scanned.quantity,
            ]);
        } catch {
            return;
        }
        if (result.need_lot) {
            // Controlado por lote y el código no lo traía: se pide en el formulario
            await this.openAddProduct({ default_product_id: scanned.productId });
            return;
        }
        this.setServerLine(result.line);
        this.saveCache();
        this.notification.add(_t("%s agregado como producto no esperado.", scanned.name), {
            type: "success",
        });
    }

    // ------------------------------------------------------------------
    // Producto no esperado (formulario)
    // ------------------------------------------------------------------
    async openAddProduct(defaults = {}) {
        if (!this.state.countId || !(await this.requireOnline())) {
            return;
        }
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
        // El orden importa: primero se manda lo que quedó en el teléfono; eso puede cerrar
        // el recuento y sacarlo de la pantalla.
        if (!this.state.countId || !(await this.requireOnline()) || !this.currentCount) {
            return;
        }
        const locationId = locationOnly ? this.state.locationId : false;
        const args = [this.state.countId, locationId || false];
        let probe;
        try {
            probe = await this.call("counter_finish", [...args, false]);
        } catch {
            return;
        }
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
                let result;
                try {
                    result = await this.call("counter_finish", [...args, true]);
                } catch {
                    return;
                }
                await this._afterFinish(result, locationOnly);
            },
            cancel: () => {},
        });
    }

    async _afterFinish(result, locationOnly) {
        const name = this.currentCount && this.currentCount.name;
        await this.load();
        if (locationOnly && this.currentCount) {
            // Reconteo inmediato: lo que no coincide se cuenta de nuevo antes de irse
            const again = this.currentLines.filter((line) => line.is_recount && !line.done).length;
            if (again) {
                this.warn(
                    _t(
                        "Hay %s productos que no coinciden con el sistema. Contalos de nuevo y cargá el segundo conteo antes de pasar a otra ubicación.",
                        again
                    ),
                    { sticky: true }
                );
                this.state.onlyPending = false;
                this.state.filter = "";
                this.focusPending = true;
                return;
            }
            if (result.remaining) {
                this.notification.add(_t("Ubicación terminada."), { type: "success" });
                this.backToCount();
                return;
            }
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

    // ------------------------------------------------------------------
    // Tablero del supervisor
    // ------------------------------------------------------------------
    get superCount() {
        return this.state.supervision.find((count) => count.id === this.state.superCountId);
    }

    qty(value) {
        return formatQty(value);
    }

    diffLabel(line) {
        const sign = line.diff > 0 ? "+" : "";
        const pct = line.diff_pct === false ? "" : ` (${sign}${formatQty(Math.round(line.diff_pct * 10) / 10)} %)`;
        return `${sign}${formatQty(line.diff)}${pct}`;
    }

    counterProgress(counter) {
        return counter.total ? Math.round((counter.done / counter.total) * 100) : 0;
    }

    async openSupervision() {
        if (!(await this.requireOnline())) {
            return;
        }
        try {
            const data = await this.call("supervisor_get_data", [], {}, COUNT_MODEL);
            this.state.supervision = data.counts;
        } catch {
            return;
        }
        this.state.superCountId = false;
        this.state.screen = "super";
    }

    async refreshSupervision() {
        try {
            const data = await this.call("supervisor_get_data", [], {}, COUNT_MODEL);
            this.state.supervision = data.counts;
        } catch {
            return;
        }
        if (this.state.screen === "super_count" && !this.superCount) {
            this.state.screen = "super";
        }
    }

    openSuperCount(countId) {
        this.state.superCountId = countId;
        this.state.screen = "super_count";
    }

    backToSupervision() {
        this.state.superCountId = false;
        this.state.screen = "super";
    }

    async superAction(action, lineIds = []) {
        const count = this.superCount;
        if (!count) {
            return;
        }
        let data;
        try {
            data = await this.call("supervisor_action", [count.id, action, lineIds], {}, COUNT_MODEL);
        } catch {
            return;
        }
        this.state.supervision = data.counts;
        if (data.message) {
            this.warn(data.message, { sticky: true });
        }
        if (data.validated) {
            this.notification.add(_t("%s validado: se generaron los ajustes de inventario.", data.validated), {
                type: "success",
                sticky: true,
            });
        }
        if (!this.superCount) {
            this.state.screen = "super";
        }
    }

    confirmSuper(action, title, body, confirmLabel) {
        this.dialog.add(ConfirmationDialog, {
            title,
            body,
            confirmLabel,
            cancelLabel: _t("Cancelar"),
            confirm: () => this.superAction(action),
            cancel: () => {},
        });
    }

    approveAll() {
        const count = this.superCount;
        this.confirmSuper(
            "approve_all",
            _t("Aprobar todas"),
            _t("Se aprueban las %s líneas contadas que esperan aprobación.", count.approve_count),
            _t("Aprobar")
        );
    }

    acceptAllFirst() {
        const count = this.superCount;
        this.confirmSuper(
            "accept_all_first",
            _t("Aceptar 1er conteo"),
            _t(
                "Las %s líneas en reconteo se aprueban con el primer conteo, sin segundo conteo.",
                count.recount_count
            ),
            _t("Aceptar")
        );
    }

    validateCount() {
        const count = this.superCount;
        const force = count.moved_count > 0;
        this.confirmSuper(
            force ? "validate_force" : "validate",
            force ? _t("Validar igualmente") : _t("Validar"),
            force
                ? _t(
                      "Hay %s líneas cuyo stock se movió después del snapshot. Se toma la cantidad contada como cantidad final y se generan los ajustes. No se puede deshacer.",
                      count.moved_count
                  )
                : _t("Se generan los ajustes de inventario con las cantidades contadas. No se puede deshacer."),
            _t("Validar")
        );
    }
}

registry.category("actions").add("stock_count_counter", StockCountCounter);
