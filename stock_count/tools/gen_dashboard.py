"""Genera data/files/stock_count_dashboard.json: el tablero "Recuentos" de la app Tableros.

Lee solo stock.count.line, así sirve para cualquier empresa. El formato del archivo cambia
con la versión de Odoo, por eso se indica al generarlo:

    python stock_count/tools/gen_dashboard.py 19
    python stock_count/tools/gen_dashboard.py 18
"""

import json
import os
import sys

ODOO = sys.argv[1] if len(sys.argv) > 1 else "19"
SHEET = "Recuentos"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "data", "files", "stock_count_dashboard.json")
MODEL = "stock.count.line"
DONE = [["count_state", "=", "done"], ["state", "=", "applied"]]
MONTH = "count_date:month"
MONTHS = 12
COLS = "ABCDEFG"


def t(text):
    return '=_t("{}")'.format(text.replace('"', '\\"'))


def measure(name, aggregator="sum"):
    key = name if aggregator == "sum" else f"{name}:{aggregator}"
    return {"id": key, "fieldName": name, "aggregator": aggregator}


def matching(offset=0):
    return {
        "filter_periodo": {"chain": "count_date", "type": "datetime", "offset": offset},
        "filter_deposito": {"chain": "warehouse_id", "type": "many2one"},
        "filter_categ": {"chain": "categ_id", "type": "many2one"},
        "filter_prod": {"chain": "product_id", "type": "many2one"},
    }


def sorted_by(name):
    if ODOO == "18":
        return {"groupId": [[], []], "measure": name, "order": "desc", "originIndexes": [0]}
    return {"measure": name, "order": "desc", "domain": []}


def pivot(pid, name, measures, rows, columns, offset=0, sort=None, domain=None):
    return {
        "type": "ODOO",
        "id": pid,
        "formulaId": pid,
        "name": name,
        "model": MODEL,
        "domain": DONE + (domain or []),
        "context": {},
        "measures": measures,
        "columns": [{"fieldName": column} for column in columns],
        "rows": rows,
        "sortedColumn": sorted_by(sort) if sort else None,
        "fieldMatching": matching(offset),
    }


BY_MONTH = [{"fieldName": "count_date", "granularity": "month"}]
VALUE = [measure("__count"), measure("count_id", "count_distinct"), measure("diff_value_abs")]
pivots = {
    "1": pivot(
        "1", "Por mes y tipo de diferencia (período elegido)", VALUE, BY_MONTH, ["diff_type"]
    ),
    "2": pivot(
        "2", "Por mes y tipo de diferencia (período anterior)", VALUE, BY_MONTH, ["diff_type"], -1
    ),
    "3": pivot(
        "3",
        "Por mes y precisión (período elegido)",
        [measure("__count")],
        BY_MONTH,
        ["is_accurate"],
    ),
    "4": pivot(
        "4",
        "Por mes y precisión (período anterior)",
        [measure("__count")],
        BY_MONTH,
        ["is_accurate"],
        -1,
    ),
    "5": pivot(
        "5",
        "Productos con mayor diferencia en valor",
        [measure("__count"), measure("qty_diff"), measure("diff_value_abs")],
        [{"fieldName": "product_id"}],
        ["diff_type"],
        sort="diff_value_abs",
    ),
    "6": pivot(
        "6",
        "Diferencias por motivo",
        [measure("__count"), measure("diff_value_abs")],
        [{"fieldName": "reason_id"}],
        ["diff_type"],
        sort="diff_value_abs",
        domain=[["diff_type", "!=", "none"]],
    ),
    "7": pivot(
        "7",
        "Ubicaciones con mayor diferencia en valor",
        [measure("__count"), measure("diff_value_abs")],
        [{"fieldName": "location_id"}],
        ["is_accurate"],
        sort="diff_value_abs",
    ),
}

global_filters = [
    {"id": "filter_periodo", "type": "date", "label": "Período", "defaultValue": "this_year"},
    {
        "id": "filter_deposito",
        "type": "relation",
        "label": "Depósito",
        "modelName": "stock.warehouse",
    },
    {
        "id": "filter_categ",
        "type": "relation",
        "label": "Categoría de producto",
        "modelName": "product.category",
    },
    {"id": "filter_prod", "type": "relation", "label": "Producto", "modelName": "product.product"},
]
if ODOO == "18":
    global_filters[0]["rangeType"] = "fixedPeriod"
    for relation in global_filters[1:]:
        relation.update(
            {"defaultValue": [], "defaultValueDisplayNames": [], "includeChildren": False}
        )


def value(pid, name, *position):
    """Valor de un pivote, 0 si no hay datos para esa posición."""
    args = "".join(f",{arg}" for arg in position)
    return f'IFERROR(PIVOT.VALUE({pid},"{name}"{args})+0,0)'


def col(field, key):
    return f'"{field}",{key}'


SURPLUS, SHORTAGE = col("diff_type", '"surplus"'), col("diff_type", '"shortage"')
ACCURATE = col("is_accurate", "TRUE")
COUNTS = "count_id:count_distinct"

# ---------------------------------------------------------------- hoja de datos
data = {
    "A1": t("KPIs (según filtros)"),
    "B1": t("Período elegido"),
    "C1": t("Período anterior"),
    "A2": t("Recuentos validados"),
    "A3": t("Líneas contadas"),
    "A4": t("Líneas dentro de la tolerancia"),
    "A5": t("Precisión"),
    "A6": t("Sobrantes $"),
    "A7": t("Faltantes $ (en positivo)"),
    "A8": t("Neto $ (sobrantes - faltantes)"),
    "A10": t("Notas del cálculo:"),
    "A11": t(
        "Fuente: líneas de recuento validadas (recuento en estado Validado). Período = fecha "
        "planificada del recuento."
    ),
    "A12": t(
        "Precisión = líneas sin diferencia o dentro de 'Aprobar automáticamente hasta (%)' sobre "
        "líneas contadas. Los importes usan el costo guardado en la línea al validar."
    ),
    "A13": t(
        "Pivotes 1 y 3: período elegido. Pivotes 2 y 4: el mismo filtro corrido un período hacia "
        "atrás, para las tarjetas. Pivotes 5 a 7: productos, motivos y ubicaciones ordenados por "
        "valor absoluto de la diferencia."
    ),
}
for column, value_pivot, accuracy_pivot in (("B", 1, 3), ("C", 2, 4)):
    data[f"{column}2"] = "=" + value(value_pivot, COUNTS)
    data[f"{column}3"] = "=" + value(value_pivot, "__count")
    data[f"{column}4"] = "=" + value(accuracy_pivot, "__count", ACCURATE)
    data[f"{column}5"] = f"=IFERROR({column}4/{column}3,0)"
    data[f"{column}6"] = "=" + value(value_pivot, "diff_value_abs", SURPLUS)
    data[f"{column}7"] = "=" + value(value_pivot, "diff_value_abs", SHORTAGE)
    data[f"{column}8"] = f"={column}6-{column}7"

# ---------------------------------------------------------------- hoja principal
cells = {"A1": t("Recuentos de inventario")}
blocks = []  # (fila del título, fila del encabezado, primera fila, última fila, última columna)
row = 18


def block(title, headers, count, fill, total=None):
    """Un bloque: título, encabezado, fila de total opcional y `count` filas."""
    global row  # noqa: PLW0603 - el generador avanza de arriba hacia abajo
    title_row, header_row = row, row + 1
    cells[f"A{title_row}"] = t(title)
    for index, header in enumerate(headers):
        cells[f"{COLS[index]}{header_row}"] = t(header)
    first = header_row + 1
    if total:
        total(first)
        first += 1
    for position in range(1, count + 1):
        fill(first + position - 1, position)
    last = first + count - 1
    blocks.append((title_row, header_row, first, last, COLS[len(headers) - 1]))
    row = last + 2
    return first, last


def blank(line, formula):
    """La fórmula solo se muestra si el renglón tiene encabezado."""
    return f'=IF($A{line}="","",{formula})'


def month_row(line, position):
    at = f'"#{MONTH}",{position}'
    cells[f"A{line}"] = f'=IFERROR(PIVOT.HEADER(1,{at}),"")'
    cells[f"B{line}"] = blank(line, value(1, COUNTS, at))
    cells[f"C{line}"] = blank(line, value(1, "__count", at))
    cells[f"D{line}"] = blank(line, f'IFERROR({value(3, "__count", at, ACCURATE)}/C{line},"")')
    cells[f"E{line}"] = blank(line, value(1, "diff_value_abs", at, SURPLUS))
    cells[f"F{line}"] = blank(line, value(1, "diff_value_abs", at, SHORTAGE))
    cells[f"G{line}"] = blank(line, f"E{line}-F{line}")


def month_total(line):
    first, last = line + 1, line + MONTHS
    cells[f"A{line}"] = t("Total del período")
    cells[f"B{line}"] = "=Datos!B2"
    cells[f"C{line}"] = f"=SUM($C${first}:$C${last})"
    cells[f"D{line}"] = "=Datos!B5"
    for column in "EFG":
        cells[f"{column}{line}"] = f"=SUM(${column}${first}:${column}${last})"


M_FIRST, M_LAST = block(
    "Recuentos por mes",
    ["Mes", "Recuentos", "Líneas", "Precisión", "Sobrantes $", "Faltantes $", "Neto $"],
    MONTHS,
    month_row,
    total=month_total,
)
M_TOTAL = M_FIRST - 1
GROSS = "(Datos!$B$6+Datos!$B$7)"


def product_row(line, position):
    at = f'"#product_id",{position}'
    cells[f"A{line}"] = f'=IFERROR(PIVOT.HEADER(5,{at}),"")'
    cells[f"B{line}"] = blank(line, value(5, "__count", at))
    cells[f"C{line}"] = blank(line, value(5, "qty_diff", at))
    cells[f"D{line}"] = blank(line, value(5, "diff_value_abs", at, SURPLUS))
    cells[f"E{line}"] = blank(line, value(5, "diff_value_abs", at, SHORTAGE))
    cells[f"F{line}"] = blank(line, f"D{line}-E{line}")
    cells[f"G{line}"] = blank(line, f'IFERROR((D{line}+E{line})/{GROSS},"")')


P_FIRST, P_LAST = block(
    "Los 10 productos con mayor diferencia en valor",
    [
        "Producto",
        "Líneas",
        "Dif. en cantidad",
        "Sobrantes $",
        "Faltantes $",
        "Neto $",
        "% del total",
    ],
    10,
    product_row,
)


def reason_row(line, position):
    at = f'"#reason_id",{position}'
    cells[f"A{line}"] = f'=IFERROR(PIVOT.HEADER(6,{at}),"")'
    cells[f"B{line}"] = blank(line, value(6, "__count", at))
    cells[f"C{line}"] = blank(line, value(6, "diff_value_abs", at, SURPLUS))
    cells[f"D{line}"] = blank(line, value(6, "diff_value_abs", at, SHORTAGE))
    cells[f"E{line}"] = blank(line, f"C{line}-D{line}")
    cells[f"F{line}"] = blank(line, f'IFERROR((C{line}+D{line})/{GROSS},"")')


R_FIRST, R_LAST = block(
    "Diferencias por motivo",
    ["Motivo", "Líneas", "Sobrantes $", "Faltantes $", "Neto $", "% del total"],
    8,
    reason_row,
)


def location_row(line, position):
    at = f'"#location_id",{position}'
    cells[f"A{line}"] = f'=IFERROR(PIVOT.HEADER(7,{at}),"")'
    cells[f"B{line}"] = blank(line, value(7, "__count", at))
    cells[f"C{line}"] = blank(line, f"B{line}-{value(7, '__count', at, ACCURATE)}")
    cells[f"D{line}"] = blank(line, f'IFERROR(1-C{line}/B{line},"")')
    cells[f"E{line}"] = blank(line, value(7, "diff_value_abs", at))


L_FIRST, L_LAST = block(
    "Las 10 ubicaciones con mayor diferencia en valor",
    ["Ubicación", "Líneas", "Fuera de tolerancia", "Precisión", "Diferencia absoluta $"],
    10,
    location_row,
)

NOTES = [
    "Cómo usar: elegí el Período (año, trimestre o mes) y, si querés, un Depósito, una Categoría "
    "de producto o un Producto. Toma las líneas de los recuentos validados, por la fecha "
    "planificada del recuento.",
    "Precisión: líneas contadas sin diferencia o con una diferencia dentro de la tolerancia de "
    "aprobación del recuento, sobre el total de líneas contadas.",
    "Sobrantes: el conteo dio más que el sistema. Faltantes: dio menos. Los importes son la "
    "diferencia valorizada al costo del producto al validar el recuento.",
    "Las tarjetas comparan contra el período anterior (mes, trimestre o año anterior, según lo "
    "elegido). La grilla muestra hasta 12 meses.",
]
NOTE_FIRST = row
for index, note in enumerate(NOTES):
    cells[f"A{NOTE_FIRST + index}"] = t(note)
NOTE_LAST = NOTE_FIRST + len(NOTES) - 1

# ---------------------------------------------------------------- tarjetas y gráficos
GREEN, RED = "#00A04A", "#DC6965"
CARDS = [
    ("kpi_recuentos", "Recuentos validados", 2, "#F1F5F4", "percentage", GREEN, RED),
    ("kpi_precision", "Precisión", 5, "#EFF6FF", "difference", GREEN, RED),
    ("kpi_sobrantes", "Sobrantes $", 6, "#EDF7F1", "percentage", RED, GREEN),
    ("kpi_faltantes", "Faltantes $", 7, "#FCEBEB", "percentage", RED, GREEN),
    ("kpi_neto", "Neto $", 8, "#FFF7ED", "difference", GREEN, RED),
]
figures = []
for index, (figure_id, title, line, background, mode, up, down) in enumerate(CARDS):
    descr = "vs anterior"
    figures.append(
        {
            "id": figure_id,
            "x": index * 223,
            "y": 48,
            "width": 213,
            "height": 101,
            "tag": "chart",
            "data": {
                "type": "scorecard",
                "title": {"text": title, "bold": True, "color": "#434343"},
                "keyValue": f"Datos!B{line}",
                "baseline": f"Datos!C{line}",
                "baselineDescr": descr if ODOO == "18" else {"text": descr},
                "background": background,
                "humanize": True,
                "baselineMode": mode,
                "baselineColorUp": up,
                "baselineColorDown": down,
            },
        }
    )
LABELS = f"{SHEET}!A{M_FIRST}:A{M_LAST}"


def series(column, label, color):
    return {
        "dataRange": f"{SHEET}!{column}{M_FIRST}:{column}{M_LAST}",
        "label": label,
        "backgroundColor": color,
    }


def chart(figure_id, x, kind, title, datasets, **extra):
    definition = {
        "type": kind,
        "title": {"text": title, "bold": True, "color": "#434343"},
        "dataSets": datasets,
        "labelRange": LABELS,
        "dataSetsHaveTitle": False,
        "stacked": False,
        "background": "#FFFFFF",
    }
    definition.update(extra)
    return {
        "id": figure_id,
        "x": x,
        "y": 160,
        "width": 547,
        "height": 240,
        "tag": "chart",
        "data": definition,
    }


figures.append(
    chart(
        "chart_valor",
        0,
        "bar",
        "Sobrantes y faltantes $ por mes",
        [series("E", "Sobrantes $", "#1D9E75"), series("F", "Faltantes $", "#D85A30")],
        legendPosition="bottom",
    )
)
figures.append(
    chart(
        "chart_precision",
        557,
        "line",
        "Precisión por mes",
        [series("D", "Precisión", "#01666B")],
        legendPosition="none",
        labelsAsText=True,
        cumulative=False,
    )
)

# ---------------------------------------------------------------- estilos y formatos
rows_cfg = {"0": {"size": 40}}
styles = {"A1": 1, f"A{NOTE_FIRST}:A{NOTE_LAST}": 2}
borders = {}
tables = []
TABLE = {
    "hasFilters": False,
    "totalRow": False,
    "firstColumn": False,
    "lastColumn": False,
    "numberOfHeaders": 1,
    "bandedRows": True,
    "bandedColumns": False,
    "automaticAutofill": True,
    "styleId": "None",
}
for title_row, header_row, first, last, last_col in blocks:
    rows_cfg[str(title_row - 1)] = {"size": 36}
    styles[f"A{title_row}"] = 6
    styles[f"A{header_row}:{last_col}{header_row}"] = 7
    styles[f"A{first}:A{last}"] = 8
    styles[f"B{first}:{last_col}{last}"] = 9
    borders[f"A{title_row}:{last_col}{title_row}"] = 1
    tables.append(
        {"range": f"A{header_row}:{last_col}{last}", "type": "static", "config": dict(TABLE)}
    )
styles[f"A{M_TOTAL}:G{M_TOTAL}"] = 10
MONEY, MONTH_FMT, PERCENT, INTEGER = 1, 2, 3, 4
formats = {
    f"A{M_FIRST}:A{M_LAST}": MONTH_FMT,
    f"B{M_TOTAL}:C{M_LAST}": INTEGER,
    f"D{M_TOTAL}:D{M_LAST}": PERCENT,
    f"E{M_TOTAL}:G{M_LAST}": MONEY,
    f"B{P_FIRST}:B{P_LAST}": INTEGER,
    f"C{P_FIRST}:F{P_LAST}": MONEY,
    f"G{P_FIRST}:G{P_LAST}": PERCENT,
    f"B{R_FIRST}:B{R_LAST}": INTEGER,
    f"C{R_FIRST}:E{R_LAST}": MONEY,
    f"F{R_FIRST}:F{R_LAST}": PERCENT,
    f"B{L_FIRST}:C{L_LAST}": INTEGER,
    f"D{L_FIRST}:D{L_LAST}": PERCENT,
    f"E{L_FIRST}:E{L_LAST}": MONEY,
}


def bar(rule_id, first, last, column, color):
    return {
        "id": rule_id,
        "ranges": [f"A{first}:A{last}"],
        "rule": {
            "type": "DataBarRule",
            "color": color,
            "rangeValues": f"{column}{first}:{column}{last}",
        },
    }


def colored(rule_id, ranges, operator, color):
    return {
        "id": rule_id,
        "ranges": ranges,
        "rule": {
            "type": "CellIsRule",
            "operator": operator,
            "values": ["0"],
            "style": {"textColor": color},
        },
    }


NET = [
    f"G{M_TOTAL}:G{M_LAST}",
    f"F{P_FIRST}:F{P_LAST}",
    f"E{R_FIRST}:E{R_LAST}",
    f"C{P_FIRST}:C{P_LAST}",
]
conditional = [
    bar("db_prod", P_FIRST, P_LAST, "G", 16775149),
    bar("db_reason", R_FIRST, R_LAST, "F", 16775149),
    bar("db_loc", L_FIRST, L_LAST, "E", 15726335),
    colored("cf_neg", NET, "isLessThan", "#C0392B"),
    colored("cf_pos", NET, "isGreaterThan", "#1E7F4F"),
]

EMPTY = {
    "conditionalFormats": [],
    "dataValidationRules": [],
    "figures": [],
    "tables": [],
    "isVisible": True,
    "headerGroups": {"ROW": [], "COL": []},
    "comments": {},
}
sheet1 = dict(
    EMPTY,
    id="sheet1",
    name=SHEET,
    colNumber=8,
    rowNumber=NOTE_LAST + 10,
    rows=rows_cfg,
    cols={
        "0": {"size": 300},
        "1": {"size": 110},
        "2": {"size": 140},
        "3": {"size": 140},
        "4": {"size": 150},
        "5": {"size": 150},
        "6": {"size": 120},
    },
    merges=["A1:G1"] + [f"A{NOTE_FIRST + i}:G{NOTE_FIRST + i}" for i in range(len(NOTES))],
    cells=cells,
    styles=styles,
    formats=formats,
    borders=borders,
    conditionalFormats=conditional,
    figures=figures,
    tables=tables if ODOO != "18" else [],
    areGridLinesVisible=False,
)
sheet2 = dict(
    EMPTY,
    id="sheet2",
    name="Datos",
    colNumber=10,
    rowNumber=30,
    rows={},
    cols={"0": {"size": 260}, "1": {"size": 150}, "2": {"size": 150}},
    merges=[],
    cells=data,
    styles={"A1:C1": 4, "A10": 4, "A11:A13": 5},
    formats={"B2:C4": INTEGER, "B5:C5": PERCENT, "B6:C8": MONEY},
    borders={},
    areGridLinesVisible=True,
)
doc = {
    "version": 21 if ODOO == "18" else "18.5.10",
    "sheets": [sheet1, sheet2],
    "styles": {
        "1": {"textColor": "#01666B", "fontSize": 14, "bold": True},
        "2": {"textColor": "#666666", "italic": True, "wrapping": "wrap"},
        "4": {"textColor": "#434343", "bold": True},
        "5": {"textColor": "#B3B3B3", "fontSize": 9, "wrapping": "wrap"},
        "6": {"textColor": "#01666B", "bold": True, "fontSize": 16, "verticalAlign": "middle"},
        "7": {"textColor": "#434343", "bold": True, "fontSize": 11, "verticalAlign": "middle"},
        "8": {"textColor": "#01666B", "verticalAlign": "middle"},
        "9": {"textColor": "#434343", "verticalAlign": "middle"},
        "10": {"textColor": "#434343", "bold": True, "verticalAlign": "middle"},
    },
    "formats": {"1": "#,##0.00", "2": "mmmm yyyy", "3": "0.0%", "4": "#,##0"},
    "borders": {"1": {"bottom": {"style": "thin", "color": "#CCCCCC"}}},
    "revisionId": "START_REVISION",
    "uniqueFigureIds": True,
    "settings": {
        "locale": {
            "name": "English (US)",
            "code": "en_US",
            "thousandsSeparator": ",",
            "decimalSeparator": ".",
            "dateFormat": "mm/dd/yyyy",
            "timeFormat": "hh:mm:ss",
            "formulaArgSeparator": ",",
            "weekStart": 1,
        }
    },
    "pivots": pivots,
    "pivotNextId": len(pivots) + 1,
    "customTableStyles": {},
    "odooVersion": 12 if ODOO == "18" else 13,
    "globalFilters": global_filters,
    "lists": {},
    "listNextId": 1,
    "chartOdooMenusReferences": {},
}

# El formato de celdas y figuras cambió entre versiones
for sheet in doc["sheets"]:
    if ODOO == "18":
        sheet["cells"] = {xc: {"content": content} for xc, content in sheet["cells"].items()}
        continue
    for figure in sheet["figures"]:
        figure["offset"] = {"x": figure.pop("x"), "y": figure.pop("y")}
        figure["col"] = 0
        figure["row"] = 0
        figure["data"]["chartId"] = figure["id"]

with open(OUT, "w", encoding="utf-8", newline="\n") as output:
    json.dump(doc, output, ensure_ascii=False, indent=1)
    output.write("\n")
print("written", os.path.normpath(OUT), "for Odoo", ODOO)
