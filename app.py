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

from allocation.config import (
    VALENCIAS_SHEETS,
    FIXED_SHEETS,
    MISSIONARIOS_SHEETS,
    OUTPUT_SHEET,
)
from allocation.main_optimization import run_allocation


# =====================================================================
# 0. UI TOKENS (Missao Pais styling)
# =====================================================================

# Styling lives in assets/missao_pais.css for Dash versions without html.Style.


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
        if valencia_options and _normalize_key(col) == _normalize_key("Valencia"):
            col_def["cellEditor"] = "agSelectCellEditor"
            col_def["cellEditorParams"] = {"values": valencia_options}
        if _normalize_key(col) in numeric_keys:
            col_def["type"] = "numericColumn"
            col_def["valueParser"] = {"function": "Number(params.newValue)"}
        defs.append(col_def)
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

app = Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    suppress_callback_exceptions=True,
)
server = app.server


# =====================================================================
# 3. LAYOUT
# =====================================================================

app.layout = html.Div(
    className="mp-app",
    children=[
        dcc.Store(id="meta-store"),
        dcc.Store(id="valencias-options-store"),
        dcc.Store(id="output-store"),
        dcc.Download(id="download-output"),
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
                            "Carregue o Excel, ajuste as tabelas e execute a alocação com o objetivo de rankings.",
                            className="mp-subtitle",
                        ),
                    ],
                ),
                html.Div(
                    className="mp-hero-card",
                    children=[
                        html.Div(
                            className="mp-hero-card-row",
                            children=[
                                html.Div(
                                    className="mp-hero-upload",
                                    children=[
                                        dcc.Upload(
                                            id="upload-data",
                                            className="mp-upload",
                                            children=html.Div(
                                                [
                                                    html.Div("Arraste o ficheiro Excel aqui"),
                                                    html.Div("ou clique para selecionar"),
                                                ]
                                            ),
                                            multiple=False,
                                        ),
                                        html.Div(id="upload-alert", className="mt-3"),
                                    ],
                                ),
                                html.Div(
                                    className="mp-hero-actions",
                                    children=[
                                        html.Div(
                                            className="mp-actions",
                                            children=[
                                                dbc.Button(
                                                    "Alocar Missionários",
                                                    id="run-button",
                                                    className="mp-btn-primary",
                                                    disabled=True,
                                                ),
                                                dbc.Button(
                                                    "Descarregar Excel",
                                                    id="download-button",
                                                    className="mp-btn-secondary",
                                                    disabled=True,
                                                ),
                                            ],
                                        ),
                                        html.P(
                                            "Limite de tempo: 10 minutos. Objetivo: rankings.",
                                            className="mp-muted mt-3",
                                        ),
                                    ],
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        ),
        html.Div(
            className="mp-section-row",
            children=[
                html.Div(
                    className="mp-section",
                    id="missionarios-section",
                    children=[
                        html.H3("Missionários"),
                        html.P("Tabela apenas de leitura.", className="mp-muted"),
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
                                        "suppressClickEdit": True,
                                        "rowHeight": 38,
                                        "headerHeight": 42,
                                    },
                                    style={"height": "420px", "width": "100%"},
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
                    className="mp-section",
                    id="valencias-section",
                    children=[
                        html.H3("Nº Missionários / Valências"),
                        html.P(
                            "Edite o nº de missionários por valência.",
                            className="mp-muted",
                        ),
                        html.Div(
                            className="mp-grid mt-3",
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
                                    style={"height": "420px", "width": "100%"},
                                    defaultColDef={
                                        "flex": 1,
                                        "minWidth": 120,
                                    },
                                )
                            ],
                        ),
                    ],
                ),
                html.Div(
                    className="mp-section",
                    id="fixas-section",
                    children=[
                        html.H3("Alocações Fixas"),
                        html.P(
                            "Edite ou adicione alocações fixas.",
                            className="mp-muted",
                        ),
                        html.Div(
                            className="mp-grid mt-3",
                            children=[
                                dag.AgGrid(
                                    id="fixas-grid",
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
                                    style={"height": "420px", "width": "100%"},
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
        ),
        html.Div(
            className="mp-section mp-results",
            children=[
                html.H3("Resultados"),
                dbc.Spinner(
                    color="primary",
                    children=html.Div(
                        [
                            html.Div(id="results-alert"),
                            html.Div(
                                className="mp-grid mt-3",
                                children=[
                                    dag.AgGrid(
                                        id="results-grid",
                                        className="ag-theme-alpine",
                                        rowData=[],
                                        columnDefs=[],
                                        columnSize="sizeToFit",
                                        dashGridOptions={
                                            "animateRows": True,
                                            "domLayout": "autoHeight",
                                            "rowSelection": "single",
                                            "suppressClickEdit": True,
                                        },
                                        defaultColDef={
                                            "flex": 1,
                                            "minWidth": 120,
                                        },
                                    )
                                ],
                            ),
                        ]
                    ),
                ),
            ],
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
    Output("fixas-grid", "rowData"),
    Output("fixas-grid", "columnDefs"),
    Output("missionarios-section", "style"),
    Output("valencias-section", "style"),
    Output("fixas-section", "style"),
    Output("meta-store", "data"),
    Output("valencias-options-store", "data"),
    Output("upload-alert", "children"),
    Output("run-button", "disabled"),
    Output("download-button", "disabled"),
    Output("results-grid", "rowData"),
    Output("results-grid", "columnDefs"),
    Output("results-alert", "children"),
    Output("output-store", "data"),
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
            [],
            [],
            _section_style([]),
            _section_style([]),
            _section_style([]),
            None,
            [],
            dbc.Alert("Nenhum ficheiro carregado.", color="warning"),
            True,
            True,
            [],
            [],
            None,
            None,
        )

    try:
        header, b64 = contents.split(",", 1)
        decoded = base64.b64decode(b64)
        book = pd.ExcelFile(io.BytesIO(decoded))
        sheet_names = book.sheet_names

        mission_sheet = _find_sheet(sheet_names, MISSIONARIOS_SHEETS)
        cap_sheet = _find_sheet(sheet_names, VALENCIAS_SHEETS)
        fixed_sheet = _find_sheet_optional(sheet_names, FIXED_SHEETS)

        mission_df = pd.read_excel(book, sheet_name=mission_sheet)
        cap_df = pd.read_excel(book, sheet_name=cap_sheet)
        fix_df = (
            pd.read_excel(book, sheet_name=fixed_sheet)
            if fixed_sheet
            else pd.DataFrame(columns=["Nome", "Valencia"])
        )

        mission_records, mission_cols = _records_from_df(mission_df.dropna(how="all"))
        cap_records, cap_cols = _records_from_df(cap_df.dropna(how="all"))
        fix_records, fix_cols = _records_from_df(fix_df.dropna(how="all"))

        valencias = _derive_valencias(cap_records, cap_cols)

        mission_defs = _make_column_defs(mission_cols, editable=False)
        cap_defs = _make_column_defs(
            cap_cols,
            editable=True,
            numeric_candidates=["Nº Missionários", "Nº Missionarios"],
        )
        fix_defs = _make_column_defs(
            fix_cols,
            editable=True,
            valencia_options=valencias,
        )
        mission_style = _section_style(mission_cols)
        valencias_style = _section_style(cap_cols)
        fixas_style = _section_style(fix_cols or ["Nome", "Valencia"])

        meta = {
            "missionarios": {"sheet": mission_sheet, "columns": mission_cols},
            "valencias": {"sheet": cap_sheet, "columns": cap_cols},
            "fixas": {
                "sheet": fixed_sheet or FIXED_SHEETS[0],
                "columns": fix_cols or ["Nome", "Valencia"],
            },
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
            fix_records,
            fix_defs,
            mission_style,
            valencias_style,
            fixas_style,
            meta,
            valencias,
            alert,
            False,
            True,
            [],
            [],
            None,
            None,
        )

    except Exception as exc:
        alert = dbc.Alert(f"Erro ao ler o ficheiro: {exc}", color="danger")
        return (
            [],
            [],
            [],
            [],
            [],
            [],
            _section_style([]),
            _section_style([]),
            _section_style([]),
            None,
            [],
            alert,
            True,
            True,
            [],
            [],
            None,
            None,
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
    Output("fixas-grid", "columnDefs", allow_duplicate=True),
    Input("valencias-options-store", "data"),
    State("meta-store", "data"),
    State("fixas-grid", "columnDefs"),
    prevent_initial_call=True,
)
def refresh_fixas_columns(valencias: List[str] | None, meta: Dict[str, Any] | None, current_defs: List[Dict[str, Any]]):
    if meta is None:
        return no_update
    columns = meta.get("fixas", {}).get("columns", []) or ["Nome", "Valencia"]
    return _make_column_defs(columns, editable=True, valencia_options=valencias or [])


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
    State("fixas-grid", "rowData"),
    prevent_initial_call=True,
)
def run_optimization(
    n_clicks: int | None,
    meta: Dict[str, Any] | None,
    missionarios_rows: List[Dict[str, Any]] | None,
    valencias_rows: List[Dict[str, Any]] | None,
    fixas_rows: List[Dict[str, Any]] | None,
):
    if not n_clicks:
        return no_update, no_update, no_update, no_update, no_update
    if not meta:
        alert = dbc.Alert("Carregue um ficheiro antes de executar.", color="warning")
        return [], [], alert, None, True

    try:
        mission_cols = meta["missionarios"]["columns"]
        val_cols = meta["valencias"]["columns"]
        fix_cols = meta["fixas"]["columns"] or ["Nome", "Valencia"]

        mission_df = _build_df(missionarios_rows or [], mission_cols)
        val_df = _build_df(valencias_rows or [], val_cols)
        fix_df = _build_df(fixas_rows or [], fix_cols)

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "input.xlsx")
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
                fix_df.to_excel(
                    writer,
                    sheet_name=meta["fixas"]["sheet"],
                    index=False,
                )
            buffer.seek(0)
            with open(input_path, "wb") as handle:
                handle.write(buffer.read())

            for attempt in range(5):
                try:
                    run_allocation(
                        input_path=input_path,
                        output_path=output_path,
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


if __name__ == "__main__":
    # port 8000
    app.run(debug=True, port=8000)
