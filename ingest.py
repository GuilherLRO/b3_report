"""
Load monthly B3 Excel reports into SQLite — one raw table per sheet.

Usage:
    python ingest.py

Drop new files into relatorios_mensais/, then re-run.
Each month is replaced safely if you run the script again.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent
REPORTS_DIR = ROOT / "relatorios_mensais"
DB_PATH = ROOT / "data" / "b3.db"

# Excel sheet name -> SQLite table name
SHEET_TO_TABLE = {
    "Posição - Ações": "raw_posicao_acoes",
    "Posição - ETF": "raw_posicao_etf",
    "Posição - Fundos": "raw_posicao_fundos",
    "Posição - Renda Fixa": "raw_posicao_renda_fixa",
    "Posição - Tesouro Direto": "raw_posicao_tesouro",
    "Proventos Recebidos": "raw_proventos",
    "Negociações": "raw_negociacoes",
}

MONTH_NAMES_PT = {
    "janeiro": "01",
    "fevereiro": "02",
    "marco": "03",
    "março": "03",
    "abril": "04",
    "maio": "05",
    "junho": "06",
    "julho": "07",
    "agosto": "08",
    "setembro": "09",
    "outubro": "10",
    "novembro": "11",
    "dezembro": "12",
}


# ---------------------------------------------------------------------------
# 1) Filename helpers
# ---------------------------------------------------------------------------

def report_month_from_filename(filename: str) -> str:
    """
    Turn 'relatorio-consolidado-mensal-2026-agosto.xlsx' into '2026-08'.
    """
    stem = Path(filename).stem.lower()
    match = re.search(r"(20\d{2})[-_]([a-zç]+)", stem)
    if not match:
        raise ValueError(
            f"Could not find year/month in filename: {filename}\n"
            "Expected something like: ...-2026-agosto.xlsx"
        )
    year, month_name = match.group(1), match.group(2)
    month_num = MONTH_NAMES_PT.get(month_name)
    if not month_num:
        raise ValueError(f"Unknown month name '{month_name}' in {filename}")
    return f"{year}-{month_num}"


# ---------------------------------------------------------------------------
# 2) Cleaning helpers
# ---------------------------------------------------------------------------

def is_empty_value(value) -> bool:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return True
    text = str(value).strip()
    return text == "" or text == "-"


def drop_total_and_empty_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Remove footer 'Total' rows and rows with no real data."""
    if df.empty:
        return df

    cleaned = df.copy()

    # Drop rows where any cell is exactly 'Total' (B3 footer)
    total_mask = cleaned.apply(
        lambda row: any(
            isinstance(v, str) and v.strip().lower() == "total" for v in row
        ),
        axis=1,
    )
    cleaned = cleaned.loc[~total_mask]

    # Drop fully empty / dash-only rows
    empty_mask = cleaned.apply(lambda row: all(is_empty_value(v) for v in row), axis=1)
    cleaned = cleaned.loc[~empty_mask]

    return cleaned.reset_index(drop=True)


def read_sheet(path: Path, sheet_name: str) -> pd.DataFrame:
    """Read one Excel sheet and clean empty/total rows."""
    df = pd.read_excel(path, sheet_name=sheet_name, engine="openpyxl")
    # Drop unnamed leftover columns from Excel formatting
    df = df.loc[:, ~df.columns.astype(str).str.startswith("Unnamed")]
    return drop_total_and_empty_rows(df)


# ---------------------------------------------------------------------------
# 3) Build raw tables for one file
# ---------------------------------------------------------------------------

def load_file(path: Path) -> dict[str, pd.DataFrame]:
    """
    Read all known sheets from one monthly report.
    Returns {table_name: DataFrame} with report_month and source_file added.
    """
    report_month = report_month_from_filename(path.name)
    source_file = path.name
    tables: dict[str, pd.DataFrame] = {}

    for sheet_name, table_name in SHEET_TO_TABLE.items():
        df = read_sheet(path, sheet_name)
        df = df.copy()
        df.insert(0, "report_month", report_month)
        df.insert(1, "source_file", source_file)
        tables[table_name] = df
        print(f"  {table_name}: {len(df)} rows")

    return tables


# ---------------------------------------------------------------------------
# 4) Custom columns (add your own rules here later)
# ---------------------------------------------------------------------------

def add_custom_columns(tables: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """
    Place to add extra columns before saving.

    Example:
        tables["raw_posicao_acoes"]["my_group"] = "equity"

    For now this does nothing — kept as a clear hook for later.
    """
    return tables


# ---------------------------------------------------------------------------
# 5) Save to SQLite (replace that month's data)
# ---------------------------------------------------------------------------

def save_tables(tables: dict[str, pd.DataFrame], report_month: str) -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)

    try:
        for table_name, df in tables.items():
            # Create table on first run by appending an empty frame with columns
            # then delete this month and insert fresh rows.
            if_exists = "append"
            # Ensure table exists with correct columns (replace schema only if new)
            has_table = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,),
            ).fetchone()

            if not has_table:
                df.head(0).to_sql(table_name, conn, index=False)
            else:
                # If columns changed, rebuild table keeping other months
                existing_cols = [
                    row[1]
                    for row in conn.execute(f'PRAGMA table_info("{table_name}")')
                ]
                new_cols = list(df.columns)
                if existing_cols != new_cols:
                    other = pd.read_sql_query(
                        f'SELECT * FROM "{table_name}" WHERE report_month != ?',
                        conn,
                        params=(report_month,),
                    )
                    combined = pd.concat([other, df], ignore_index=True)
                    combined.to_sql(table_name, conn, index=False, if_exists="replace")
                    print(f"  updated schema for {table_name}")
                    continue

            conn.execute(
                f'DELETE FROM "{table_name}" WHERE report_month = ?',
                (report_month,),
            )
            df.to_sql(table_name, conn, index=False, if_exists=if_exists)
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    files = sorted(REPORTS_DIR.glob("*.xlsx"))
    if not files:
        print(f"No .xlsx files found in {REPORTS_DIR}")
        return

    print(f"Database: {DB_PATH}")
    for path in files:
        print(f"\nIngesting {path.name} ...")
        tables = load_file(path)
        tables = add_custom_columns(tables)
        report_month = report_month_from_filename(path.name)
        save_tables(tables, report_month)
        print(f"Done: report_month={report_month}")

    print("\nAll files ingested.")


if __name__ == "__main__":
    main()
