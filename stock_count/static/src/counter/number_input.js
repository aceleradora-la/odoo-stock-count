/** @odoo-module **/
/**
 * Cantidades tipeadas en el celular (app Recuentos). Misma receta que Avícola Campo:
 *
 * Las celdas son <input type="text" inputmode="decimal">, no type="number": un campo
 * numérico del navegador devuelve "" mientras se tipea un decimal a medias ("74.") y no
 * acepta la coma decimal del teclado en español.
 *
 * A diferencia de un peso, acá el 0 es una respuesta válida ("conté y no hay"), así que
 * vacío y cero se distinguen.
 */

/** Texto tipeado → número ≥ 0, `null` si está vacío, `NaN` si no es una cantidad. */
export function parseQty(text) {
    if (text === null || text === undefined) {
        return null;
    }
    const clean = String(text).trim().replace(/\s/g, "");
    if (!clean) {
        return null;
    }
    const lastComma = clean.lastIndexOf(",");
    const lastDot = clean.lastIndexOf(".");
    let normalized = clean;
    if (lastComma >= 0 && lastDot >= 0) {
        // Con los dos separadores, el último es el decimal (1.234,5 o 1,234.5).
        normalized =
            lastComma > lastDot ? clean.replace(/\./g, "").replace(",", ".") : clean.replace(/,/g, "");
    } else if (lastComma >= 0) {
        normalized = clean.replace(",", ".");
    }
    if (!/^\d*\.?\d*$/.test(normalized) || normalized === ".") {
        return NaN;
    }
    const value = parseFloat(normalized);
    return Number.isFinite(value) && value >= 0 ? value : NaN;
}

/** Número → texto para la celda: sin separador de miles y con coma decimal. */
export function formatQty(value) {
    if (value === null || value === undefined || value === "") {
        return "";
    }
    const rounded = Math.round(value * 1000) / 1000;
    return String(rounded).replace(".", ",");
}

/**
 * Al tocar una celda con valor, el celular deja el cursor donde se tocó y lo tipeado se
 * intercala con el número anterior: se selecciona todo para reemplazarlo.
 */
export function selectOnFocus(ev) {
    const input = ev.target;
    // En cuanto se tipea algo no se vuelve a seleccionar: se perdería lo ya tipeado.
    let typed = false;
    const onInput = () => {
        typed = true;
    };
    const select = () => {
        if (!typed && document.activeElement === input && input.select) {
            input.select();
        }
    };
    input.addEventListener("input", onInput, { once: true });
    setTimeout(select, 0);
    // El toque que dio el foco termina después (mouseup/click) y ahí el navegador deja el
    // cursor donde se tocó: se vuelve a seleccionar justo después de ese toque.
    const afterTap = () => setTimeout(select, 0);
    input.addEventListener("click", afterTap, { once: true });
    setTimeout(() => {
        input.removeEventListener("click", afterTap);
        input.removeEventListener("input", onInput);
    }, 600);
}
