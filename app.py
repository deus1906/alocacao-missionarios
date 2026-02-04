"""Dash frontend for Missao Pais allocation."""

from __future__ import annotations

import base64
import io
import os
import re
import tempfile
import unicodedata
import time
from typing import Any, Dict, List, Tuple

import pandas as pd

from dash import Dash, Input, Output, State, callback, dcc, html, no_update
import dash_ag_grid as dag
import dash_bootstrap_components as dbc

from allocation.config import MISSIONARIOS_SHEETS, OUTPUT_SHEET, VALENCIAS_SHEETS
from allocation.main_optimization import run_allocation


# =====================================================================
# 0. UI TOKENS (Missao Pais styling)
# =====================================================================

# Styling lives in assets/missao_pais.css for Dash versions without html.Style.

# Toggle all table edits in the UI.
ALLOW_EDITS = False


# =====================================================================
# 1. HELPERS (data handling)
# =====================================================================


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _normalize_key(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    text = _strip_accents(text)
    text = text.lower().strip()
    return re.sub(r"\s+", "", text)


def _normalize_label(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return " ".join(text.split())


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, float):
        return pd.isna(value)
    return False


def _select_column(columns: List[Any], candidates: List[str]) -> str | None:
    mapping = {_normalize_key(col): col for col in columns if col is not None}
    for candidate in candidates:
        key = _normalize_key(candidate)
        if key in mapping:
            return mapping[key]
    return None


def _find_sheet(sheet_names: List[str], candidates: List[str]) -> str:
    normalized = {_normalize_key(name): name for name in sheet_names}
    for candidate in candidates:
        key = _normalize_key(candidate)
        if key in normalized:
            return normalized[key]
    if len(sheet_names) == 1:
        return sheet_names[0]
    available = ", ".join(sheet_names)
    raise ValueError(
        f"Could not find a matching sheet name. Available sheets: {available}"
    )


def _find_sheet_optional(sheet_names: List[str], candidates: List[str]) -> str | None:
    normalized = {_normalize_key(name): name for name in sheet_names}
    for candidate in candidates:
        key = _normalize_key(candidate)
        if key in normalized:
            return normalized[key]
    return None


def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    cols = [c for c in df.columns if c is not None and str(c).strip() != ""]
    df = df[cols]
    df.columns = [str(c).strip() for c in df.columns]
    df = df.where(pd.notnull(df), None)
    return df


def _strip_blank_rows(records: List[Dict[str, Any]], columns: List[str]) -> List[Dict[str, Any]]:
    cleaned = []
    for row in records:
        if all(_is_blank(row.get(col)) for col in columns):
            continue
        cleaned.append(row)
    return cleaned


def _records_from_df(df: pd.DataFrame) -> Tuple[List[Dict[str, Any]], List[str]]:
    df = _normalize_df(df)
    records = df.to_dict(orient="records")
    return records, list(df.columns)


def _make_column_defs(
    columns: List[str],
    *,
    editable: bool,
    valencia_options: List[str] | None = None,
    numeric_candidates: List[str] | None = None,
) -> List[Dict[str, Any]]:
    numeric_candidates = numeric_candidates or []
    numeric_keys = {_normalize_key(c) for c in numeric_candidates}
    defs: List[Dict[str, Any]] = []
    for col in columns:
        col_def: Dict[str, Any] = {
            "headerName": str(col),
            "field": col,
            "resizable": True,
            "sortable": True,
            "filter": True,
            "editable": editable,
        }
        if editable and valencia_options and _normalize_key(col) == _normalize_key("Valencia"):
            col_def["cellEditor"] = "agSelectCellEditor"
            col_def["cellEditorParams"] = {"values": valencia_options}
            col_def["cellStyle"] = {"backgroundColor": "#F1F5F9"}
        if _normalize_key(col) in numeric_keys:
            col_def["type"] = "numericColumn"
            col_def["valueParser"] = {"function": "Number(params.newValue)"}
        defs.append(col_def)
    return defs


def _make_missionarios_defs(
    columns: List[str], valencia_options: List[str] | None
) -> List[Dict[str, Any]]:
    defs = _make_column_defs(columns, editable=False)
    fixed_key = _normalize_key("Valência Fixa")
    for col_def in defs:
        if _normalize_key(col_def["field"]) == fixed_key:
            col_def["editable"] = ALLOW_EDITS
            if not ALLOW_EDITS:
                continue
            clean_options: List[str] = []
            for option in (valencia_options or []):
                normalized = _normalize_label(option)
                if not normalized or normalized == "Nenhum":
                    continue
                clean_options.append(option)
            col_def["cellEditor"] = "agSelectCellEditor"
            col_def["cellEditorParams"] = {"values": ["Nenhum", *clean_options]}
            col_def["valueParser"] = {
                "function": (
                    "return params.newValue === 'Nenhum' || params.newValue === '' "
                    "? null : params.newValue;"
                )
            }
            col_def["valueSetter"] = {
                "function": (
                    "params.data[params.colDef.field] = "
                    "(params.newValue === 'Nenhum' || params.newValue === '') "
                    "? null : params.newValue; "
                    "return true;"
                )
            }
            col_def["valueFormatter"] = {
                "function": (
                    "return params.value === null || params.value === undefined || "
                    "params.value === 'Nenhum' ? '' : params.value;"
                )
            }
            col_def["cellClass"] = "mp-select-cell"
            col_def["cellStyle"] = {"backgroundColor": "#F1F5F9"}
    return defs


def _derive_valencias(records: List[Dict[str, Any]], columns: List[str]) -> List[str]:
    val_col = _select_column(columns, ["Valencia"])
    if not val_col:
        return []
    values = []
    seen = set()
    for row in records:
        raw = row.get(val_col)
        val = _normalize_label(raw)
        if not val:
            continue
        if val in seen:
            continue
        seen.add(val)
        values.append(val)
    return values


def _build_df(records: List[Dict[str, Any]], columns: List[str]) -> pd.DataFrame:
    records = _strip_blank_rows(records, columns)
    df = pd.DataFrame(records)
    for col in columns:
        if col not in df.columns:
            df[col] = None
    df = df[columns]
    return df


def _section_style(columns: List[str] | None) -> Dict[str, Any]:
    count = len(columns or [])
    if count <= 0:
        count = 2
    basis = min(max(count * 140, 320), 760)
    grow = max(1, count)
    return {"flex": f"{grow} 1 {basis}px"}


# =====================================================================
# 2. APP SETUP
# =====================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_readme() -> str:
    readme_path = os.path.join(BASE_DIR, "README.md")
    try:
        with open(readme_path, "r", encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return "README.md nao encontrado."


README_TEXT = _load_readme()

app = Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
    suppress_callback_exceptions=True,
)
server = app.server
app.title = "Alocação de Missionários"
app.index_string = """<!DOCTYPE html>
<html>
  <head>
    {%metas%}
    <title>{%title%}</title>
    {%favicon%}
    <link rel="icon" type="image/svg+xml" href="/assets/favicon.svg">
    {%css%}
  </head>
  <body>
    {%app_entry%}
    <footer>
      {%config%}
      {%scripts%}
      {%renderer%}
    </footer>
  </body>
</html>"""


# =====================================================================
# 3. LAYOUT
# =====================================================================

app.layout = html.Div(
    className="mp-app",
    children=[
        dcc.Store(id="meta-store"),
        dcc.Store(id="valencias-options-store"),
        dcc.Store(id="output-store"),
        dcc.Store(id="upload-store"),
        dcc.Store(id="run-trigger-store"),
        dcc.Download(id="download-output"),
        dcc.Download(id="download-example"),
        html.Div(
            className="mp-hero",
            children=[
                html.Div(
                    className="mp-hero-text",
                    children=[
                        html.H1(
                            "Alocação de Missionários",
                            className="mp-title",
                        ),
                        html.P(
                            "Esta aplicação foi criada para automatizar o processo de alocação de missionários a valências através de um algoritmo de otimização. Disclaimer: não associado com a Missão País.",
                            className="mp-subtitle",
                        ),
                    ],
                ),
            ],
        ),
        html.Div(
            className="mp-section mp-readme",
            children=[
                html.Div(
                    className="mp-card-header",
                    children=[
                        html.H3("Instruções"),
                        dbc.Button(
                            "▼",
                            id="readme-toggle",
                            className="mp-btn-icon",
                            n_clicks=0,
                        ),
                    ],
                ),
                dbc.Collapse(
                    id="readme-collapse",
                    is_open=False,
                    children=[
                        dcc.Markdown(
                            README_TEXT,
                            className="mp-readme-markdown",
                        ),
                        html.Div(
                            className="mp-readme-actions",
                            children=[
                                dbc.Button(
                                    "Descarregar Excel Exemplo",
                                    id="download-example-button",
                                    className="mp-btn-secondary mp-readme-download",
                                )
                            ],
                        ),
                    ],
                ),
            ],
        ),
        html.Div(
            className="mp-section mp-upload-card",
            children=[
                html.H3("Carregar ficheiro"),
                html.Div(
                    className="mp-upload-row",
                    children=[
                        html.Div(
                            className="mp-upload-area",
                            children=[
                                dcc.Upload(
                                    id="upload-data",
                                    className="mp-upload",
                                    children=html.Div(
                                        "Arraste o ficheiro Excel aqui ou clique para selecionar",
                                        className="mp-upload-text",
                                    ),
                                    multiple=False,
                                ),
                            ],
                        ),
                    ],
                ),
                html.Div(
                    className="mp-upload-footer",
                    children=[
                        html.Div(id="upload-alert", className="mp-upload-alert"),
                        html.Div(
                            className="mp-actions",
                            children=[
                                dbc.Button(
                                    "Alocar Missionários",
                                    id="run-button",
                                    className="mp-btn-primary",
                                    disabled=True,
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        ),
        html.Div(
            className="mp-section mp-tables-card",
            id="tables-card",
            style={"display": "none"},
            children=[
                html.Div(
                    className="mp-card-header",
                    children=[
                        html.H3("Tabelas"),
                        dbc.Button(
                            "▲",
                            id="tables-toggle",
                            className="mp-btn-icon",
                            n_clicks=0,
                        ),
                    ],
                ),
                dbc.Collapse(
                    id="tables-collapse",
                    is_open=True,
                    children=[
                        html.Div(
                            className="mp-section-row",
                            children=[
                                html.Div(
                                    className="mp-subsection",
                                    id="missionarios-section",
                                    children=[
                                        html.H4("Missionários"),
                                        # html.P(
                                        #     "Esta tabela mostra os missionários e as valências ",
                                        #     className="mp-muted",
                                        # ),
                                        html.Div(
                                            className="mp-grid",
                                            children=[
                                                dag.AgGrid(
                                                    id="missionarios-grid",
                                                    className="ag-theme-alpine",
                                                    rowData=[],
                                                    columnDefs=[],
                                                    columnSize="sizeToFit",
                                                    dashGridOptions={
                                                        "animateRows": True,
                                                        "domLayout": "normal",
                                                        "rowSelection": "single",
                                                        "singleClickEdit": True,
                                                        "rowHeight": 38,
                                                        "headerHeight": 42,
                                                    },
                                                    style={
                                                        "height": "420px",
                                                        "width": "100%",
                                                    },
                                                    defaultColDef={
                                                        "flex": 1,
                                                        "minWidth": 120,
                                                        "wrapText": True,
                                                        "autoHeight": True,
                                                    },
                                                )
                                            ],
                                        ),
                                    ],
                                ),
                                html.Div(
                                    className="mp-subsection",
                                    id="valencias-section",
                                    children=[
                                        html.H4("Nº Missionários / Valências"),
                                        # html.P(
                                        #     "Edita o nº de missionários por valência, se for necessário.",
                                        #     className="mp-muted",
                                        # ),
                                        html.Div(
                                            className="mp-grid",
                                            children=[
                                                dag.AgGrid(
                                                    id="valencias-grid",
                                                    className="ag-theme-alpine",
                                                    rowData=[],
                                                    columnDefs=[],
                                                    columnSize="sizeToFit",
                                                    dashGridOptions={
                                                        "animateRows": True,
                                                        "domLayout": "normal",
                                                        "rowSelection": "single",
                                                        "singleClickEdit": True,
                                                        "rowHeight": 38,
                                                        "headerHeight": 42,
                                                    },
                                                    style={
                                                        "height": "420px",
                                                        "width": "100%",
                                                    },
                                                    defaultColDef={
                                                        "flex": 1,
                                                        "minWidth": 120,
                                                    },
                                                )
                                            ],
                                        ),
                                    ],
                                ),
                            ],
                        )
                    ],
                ),
            ],
        ),
        html.Div(
            className="mp-section mp-results",
            id="results-card",
            style={"display": "none"},
            children=[
                html.H3("Resultados"),
                dbc.Spinner(
                    color="primary",
                    children=html.Div(
                        [
                            html.Div(id="results-status"),
                            html.Div(id="results-alert"),
                            html.Div(
                                className="mp-grid mt-3",
                                id="results-grid-container",
                                children=[
                                    dag.AgGrid(
                                        id="results-grid",
                                        className="ag-theme-alpine",
                                        rowData=[],
                                        columnDefs=[],
                                        columnSize="sizeToFit",
                                        dashGridOptions={
                                            "animateRows": True,
                                            "domLayout": "normal",
                                            "rowSelection": "single",
                                            "suppressClickEdit": True,
                                            "rowHeight": 38,
                                            "headerHeight": 42,
                                        },
                                        style={"height": "420px", "width": "100%"},
                                        defaultColDef={
                                            "flex": 1,
                                            "minWidth": 120,
                                        },
                                    )
                                ],
                            ),
                            html.Div(
                                className="mp-actions mp-actions-right mt-3",
                                children=[
                                    dbc.Button(
                                        "Descarregar Excel",
                                        id="download-button",
                                        className="mp-btn-secondary",
                                        disabled=True,
                                    ),
                                ],
                            ),
                        ]
                    ),
                ),
            ],
        ),
        html.Footer(
            className="mp-footer",
            children="© João de Deus 2026",
        ),
    ],
)


# =====================================================================
# 4. CALLBACKS
# =====================================================================


@callback(
    Output("missionarios-grid", "rowData"),
    Output("missionarios-grid", "columnDefs"),
    Output("valencias-grid", "rowData"),
    Output("valencias-grid", "columnDefs"),
    Output("missionarios-section", "style"),
    Output("valencias-section", "style"),
    Output("tables-card", "style"),
    Output("meta-store", "data"),
    Output("valencias-options-store", "data"),
    Output("upload-alert", "children"),
    Output("run-button", "disabled"),
    Output("download-button", "disabled"),
    Output("results-grid", "rowData"),
    Output("results-grid", "columnDefs"),
    Output("results-alert", "children"),
    Output("output-store", "data"),
    Output("upload-store", "data"),
    Input("upload-data", "contents"),
    State("upload-data", "filename"),
    prevent_initial_call=True,
)
def handle_upload(contents: str | None, filename: str | None):
    if not contents:
        return (
            [],
            [],
            [],
            [],
            _section_style([]),
            _section_style([]),
            {"display": "none"},
            None,
            [],
            dbc.Alert("Nenhum ficheiro carregado.", color="warning"),
            True,
            True,
            [],
            [],
            None,
            None,
            {"at": time.time()},
        )

    try:
        header, b64 = contents.split(",", 1)
        decoded = base64.b64decode(b64)
        book = pd.ExcelFile(io.BytesIO(decoded))
        sheet_names = book.sheet_names

        mission_sheet = _find_sheet(sheet_names, MISSIONARIOS_SHEETS)
        cap_sheet = _find_sheet(sheet_names, VALENCIAS_SHEETS)

        mission_df = pd.read_excel(book, sheet_name=mission_sheet)
        cap_df = pd.read_excel(book, sheet_name=cap_sheet)
        fixed_col = _select_column(
            list(mission_df.columns), ["Valência Fixa", "Valencia Fixa"]
        )
        if not fixed_col:
            fixed_col = "Valência Fixa"
            mission_df[fixed_col] = None

        mission_records, mission_cols = _records_from_df(mission_df.dropna(how="all"))
        cap_records, cap_cols = _records_from_df(cap_df.dropna(how="all"))

        valencias = _derive_valencias(cap_records, cap_cols)

        mission_defs = _make_missionarios_defs(mission_cols, valencias)
        cap_defs = _make_column_defs(
            cap_cols,
            editable=ALLOW_EDITS,
            numeric_candidates=["Nº Missionários", "Nº Missionarios"],
        )
        mission_style = _section_style(mission_cols)
        valencias_style = _section_style(cap_cols)

        meta = {
            "missionarios": {"sheet": mission_sheet, "columns": mission_cols},
            "valencias": {"sheet": cap_sheet, "columns": cap_cols},
            "filename": filename or "input.xlsx",
        }

        alert = dbc.Alert(
            f"Ficheiro carregado: {filename}",
            color="success",
        )

        return (
            mission_records,
            mission_defs,
            cap_records,
            cap_defs,
            mission_style,
            valencias_style,
            {"display": "block"},
            meta,
            valencias,
            alert,
            False,
            True,
            [],
            [],
            None,
            None,
            {"at": time.time()},
        )

    except Exception as exc:
        alert = dbc.Alert(f"Erro ao ler o ficheiro: {exc}", color="danger")
        return (
            [],
            [],
            [],
            [],
            _section_style([]),
            _section_style([]),
            {"display": "none"},
            None,
            [],
            alert,
            True,
            True,
            [],
            [],
            None,
            None,
            {"at": time.time()},
        )


@callback(
    Output("valencias-options-store", "data", allow_duplicate=True),
    Input("valencias-grid", "rowData"),
    State("meta-store", "data"),
    prevent_initial_call=True,
)
def update_valencia_options(rows: List[Dict[str, Any]] | None, meta: Dict[str, Any] | None):
    if meta is None:
        return no_update
    columns = meta.get("valencias", {}).get("columns", [])
    valencias = _derive_valencias(rows or [], columns)
    return valencias


@callback(
    Output("missionarios-grid", "columnDefs", allow_duplicate=True),
    Input("valencias-options-store", "data"),
    State("meta-store", "data"),
    prevent_initial_call=True,
)
def refresh_missionarios_columns(valencias: List[str] | None, meta: Dict[str, Any] | None):
    if meta is None:
        return no_update
    columns = meta.get("missionarios", {}).get("columns", [])
    return _make_missionarios_defs(columns, valencias or [])


@callback(
    Output("run-trigger-store", "data"),
    Input("run-button", "n_clicks"),
    prevent_initial_call=True,
)
def mark_run_trigger(n_clicks: int | None):
    if not n_clicks:
        return no_update
    return {"at": time.time()}


@callback(
    Output("readme-collapse", "is_open"),
    Output("readme-toggle", "children"),
    Input("readme-toggle", "n_clicks"),
    State("readme-collapse", "is_open"),
)
def toggle_readme(n_clicks: int | None, is_open: bool) -> bool:
    if not n_clicks:
        return is_open, "▲" if is_open else "▼"
    next_open = not is_open
    return next_open, "▲" if next_open else "▼"


@callback(
    Output("tables-collapse", "is_open"),
    Output("tables-toggle", "children"),
    Input("tables-toggle", "n_clicks"),
    State("tables-collapse", "is_open"),
)
def toggle_tables(n_clicks: int | None, is_open: bool) -> bool:
    if not n_clicks:
        return is_open, "▲" if is_open else "▼"
    next_open = not is_open
    return next_open, "▲" if next_open else "▼"


@callback(
    Output("results-card", "style"),
    Output("results-status", "children"),
    Output("results-grid-container", "style"),
    Input("run-trigger-store", "data"),
    Input("upload-store", "data"),
    Input("output-store", "data"),
    Input("results-alert", "children"),
)
def update_results_visibility(
    run_trigger: Dict[str, Any] | None,
    upload_trigger: Dict[str, Any] | None,
    output_data: Dict[str, Any] | None,
    results_alert: Any,
):
    run_at = (run_trigger or {}).get("at")
    upload_at = (upload_trigger or {}).get("at")
    if not run_at or (upload_at and run_at < upload_at):
        return {"display": "none"}, None, {"display": "none"}
    if output_data:
        return {"display": "block"}, None, {"display": "block"}
    if results_alert:
        return {"display": "block"}, None, {"display": "none"}
    message = "Estamos a alocar os missionários, reza uma Avé Maria entretanto..."
    return {"display": "block"}, message, {"display": "none"}


@callback(
    Output("results-grid", "rowData", allow_duplicate=True),
    Output("results-grid", "columnDefs", allow_duplicate=True),
    Output("results-alert", "children", allow_duplicate=True),
    Output("output-store", "data", allow_duplicate=True),
    Output("download-button", "disabled", allow_duplicate=True),
    Input("run-button", "n_clicks"),
    State("meta-store", "data"),
    State("missionarios-grid", "rowData"),
    State("valencias-grid", "rowData"),
    prevent_initial_call=True,
)
def run_optimization(
    n_clicks: int | None,
    meta: Dict[str, Any] | None,
    missionarios_rows: List[Dict[str, Any]] | None,
    valencias_rows: List[Dict[str, Any]] | None,
):
    if not n_clicks:
        return no_update, no_update, no_update, no_update, no_update
    if not meta:
        alert = dbc.Alert("Carregue um ficheiro antes de executar.", color="warning")
        return [], [], alert, None, True

    try:
        mission_cols = meta["missionarios"]["columns"]
        val_cols = meta["valencias"]["columns"]
        mission_df = _build_df(missionarios_rows or [], mission_cols)
        val_df = _build_df(valencias_rows or [], val_cols)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "output.xlsx")

            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                mission_df.to_excel(
                    writer,
                    sheet_name=meta["missionarios"]["sheet"],
                    index=False,
                )
                val_df.to_excel(
                    writer,
                    sheet_name=meta["valencias"]["sheet"],
                    index=False,
                )
            buffer.seek(0)
            input_bytes = buffer.read()

            for attempt in range(5):
                try:
                    run_allocation(
                        input_path="memory.xlsx",
                        output_path=output_path,
                        input_bytes=input_bytes,
                        time_limit=600,
                        fairness_mode=None,
                    )
                    break
                except OSError as exc:
                    if getattr(exc, "winerror", None) != 32 and exc.errno != 32:
                        raise
                    if attempt >= 4:
                        raise
                    time.sleep(0.25)

            output_df = pd.read_excel(output_path, sheet_name=OUTPUT_SHEET)
            output_df = _normalize_df(output_df)
            output_records = output_df.to_dict(orient="records")
            output_cols = list(output_df.columns)
            output_defs = _make_column_defs(output_cols, editable=False)

            with open(output_path, "rb") as handle:
                output_bytes = handle.read()

        output_name = (meta.get("filename") or "output.xlsx").replace(
            ".xlsx", ""
        ) + "_output.xlsx"

        alert = dbc.Alert("Alocação concluída com sucesso.", color="success")

        return (
            output_records,
            output_defs,
            alert,
            {
                "content": base64.b64encode(output_bytes).decode("utf-8"),
                "filename": output_name,
            },
            False,
        )

    except SystemExit as exc:
        alert = dbc.Alert(f"Erro na alocação: {exc}", color="danger")
        return [], [], alert, None, True
    except Exception as exc:
        alert = dbc.Alert(f"Erro na alocação: {exc}", color="danger")
        return [], [], alert, None, True


@callback(
    Output("download-output", "data"),
    Input("download-button", "n_clicks"),
    State("output-store", "data"),
    prevent_initial_call=True,
)
def download_output(n_clicks: int | None, data: Dict[str, Any] | None):
    if not n_clicks or not data:
        return no_update
    content = base64.b64decode(data["content"])
    filename = data.get("filename", "output.xlsx")
    return dcc.send_bytes(content, filename)


@callback(
    Output("download-example", "data"),
    Input("download-example-button", "n_clicks"),
    prevent_initial_call=True,
)
def download_example(n_clicks: int | None):
    if not n_clicks:
        return no_update
    example_path = os.path.join(BASE_DIR, "input.xlsx")
    return dcc.send_file(example_path, filename="input.xlsx")


if __name__ == "__main__":
    app.run(debug=True, port=8030, dev_tools_ui=False, dev_tools_props_check=False)
