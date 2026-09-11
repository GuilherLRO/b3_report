"""
Build clean tables from raw_* tables in data/b3.db.

Usage:
    uv run python build_clean.py

Creates / replaces:
  - positions  (holdings by month + classification rules)
  - provents   (income events)

Raw tables are never modified.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from rules import (
    GROUP_RULE_COLUMNS,
    PROVENT_GROUP_COLUMN,
    classify_asset_group,
    classify_provent_group,
    classify_rf_rate_type,
    parse_ticker_from_product,
)

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "b3.db"

# Raw position tables and the asset_class label we assign
RAW_POSITION_SOURCES = {
    "raw_posicao_acoes": "stocks",
    "raw_posicao_etf": "etf",
    "raw_posicao_fundos": "funds",
    "raw_posicao_renda_fixa": "fixed_income",
    "raw_posicao_tesouro": "treasury",
}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def read_table(conn: sqlite3.Connection, name: str) -> pd.DataFrame:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    if not exists:
        return pd.DataFrame()
    return pd.read_sql_query(f'SELECT * FROM "{name}"', conn)


def to_number(series: pd.Series) -> pd.Series:
    """Turn B3 values into numbers. '-' and blanks become NaN."""
    cleaned = (
        series.astype(str)
        .str.strip()
        .replace({"-": pd.NA, "": pd.NA, "None": pd.NA, "nan": pd.NA})
    )
    return pd.to_numeric(cleaned, errors="coerce")


def has_real_product(df: pd.DataFrame) -> pd.Series:
    if "product" not in df.columns:
        return pd.Series([False] * len(df), index=df.index)
    text = df["product"].astype(str).str.strip()
    return df["product"].notna() & text.ne("") & text.str.lower().ne("nan")


# ---------------------------------------------------------------------------
# positions
# ---------------------------------------------------------------------------

def normalize_stocks_like(df: pd.DataFrame, asset_class: str) -> pd.DataFrame:
    """Ações / ETF / Fundos share almost the same columns."""
    out = pd.DataFrame(
        {
            "report_month": df["report_month"],
            "source_file": df["source_file"],
            "asset_class": asset_class,
            "product": df["Produto"],
            "institution": df["Instituição"],
            "account": df.get("Conta"),
            "ticker": df["Código de Negociação"],
            "asset_type": df.get("Tipo"),
            "indexer": pd.NA,
            "quantity": to_number(df["Quantidade"]),
            "price": to_number(df["Preço de Fechamento"]),
            "market_value": to_number(df["Valor Atualizado"]),
        }
    )
    return out.loc[has_real_product(out)].reset_index(drop=True)


def normalize_fixed_income(df: pd.DataFrame) -> pd.DataFrame:
    price_curve = to_number(df["Preço Atualizado CURVA"])
    value_curve = to_number(df["Valor Atualizado CURVA"])
    price_mtm = to_number(df["Preço Atualizado MTM"])
    value_mtm = to_number(df["Valor Atualizado MTM"])

    price = price_curve.fillna(price_mtm)
    market_value = value_curve.fillna(value_mtm)

    out = pd.DataFrame(
        {
            "report_month": df["report_month"],
            "source_file": df["source_file"],
            "asset_class": "fixed_income",
            "product": df["Produto"],
            "institution": df["Instituição"],
            "account": pd.NA,
            "ticker": df["Código"],
            "asset_type": pd.NA,
            "indexer": df["Indexador"],
            "quantity": to_number(df["Quantidade"]),
            "price": price,
            "market_value": market_value,
        }
    )
    return out.loc[has_real_product(out)].reset_index(drop=True)


def normalize_treasury(df: pd.DataFrame) -> pd.DataFrame:
    quantity = to_number(df["Quantidade"])
    market_value = to_number(df["Valor Atualizado"])
    price = market_value / quantity.replace(0, pd.NA)

    out = pd.DataFrame(
        {
            "report_month": df["report_month"],
            "source_file": df["source_file"],
            "asset_class": "treasury",
            "product": df["Produto"],
            "institution": df["Instituição"],
            "account": pd.NA,
            "ticker": df["Produto"],
            "asset_type": pd.NA,
            "indexer": df["Indexador"],
            "quantity": quantity,
            "price": price,
            "market_value": market_value,
        }
    )
    return out.loc[has_real_product(out)].reset_index(drop=True)


def build_positions(conn: sqlite3.Connection) -> pd.DataFrame:
    pieces: list[pd.DataFrame] = []

    for table_name, asset_class in RAW_POSITION_SOURCES.items():
        raw = read_table(conn, table_name)
        if raw.empty:
            print(f"  skip {table_name} (missing or empty)")
            continue

        if asset_class in {"stocks", "etf", "funds"}:
            piece = normalize_stocks_like(raw, asset_class)
        elif asset_class == "fixed_income":
            piece = normalize_fixed_income(raw)
        else:
            piece = normalize_treasury(raw)

        pieces.append(piece)
        print(f"  {table_name} -> {len(piece)} rows")

    if not pieces:
        return pd.DataFrame()

    positions = pd.concat(pieces, ignore_index=True)

    # --- Rules (add more columns here later) ---
    positions["asset_group"] = positions.apply(classify_asset_group, axis=1)
    positions["rf_rate_type"] = positions.apply(classify_rf_rate_type, axis=1)

    # Keep column order stable and include any declared rule columns
    base_cols = [
        "report_month",
        "source_file",
        "asset_class",
        "product",
        "institution",
        "account",
        "ticker",
        "asset_type",
        "indexer",
        "quantity",
        "price",
        "market_value",
    ]
    rule_cols = [c for c in GROUP_RULE_COLUMNS if c in positions.columns]
    return positions[base_cols + rule_cols]


# ---------------------------------------------------------------------------
# provents
# ---------------------------------------------------------------------------

def build_provents(conn: sqlite3.Connection) -> pd.DataFrame:
    raw = read_table(conn, "raw_proventos")
    if raw.empty:
        return pd.DataFrame()

    out = pd.DataFrame(
        {
            "report_month": raw["report_month"],
            "source_file": raw["source_file"],
            "product": raw["Produto"],
            "payment_date": raw["Pagamento"],
            "event_type": raw["Tipo de Evento"],
            "institution": raw["Instituição"],
            "quantity": to_number(raw["Quantidade"]),
            "unit_price": to_number(raw["Preço unitário"]),
            "net_value": to_number(raw["Valor líquido"]),
        }
    )
    out = out.loc[has_real_product(out)].reset_index(drop=True)
    out["ticker"] = out["product"].map(parse_ticker_from_product)
    out[PROVENT_GROUP_COLUMN] = out.apply(classify_provent_group, axis=1)

    cols = [
        "report_month",
        "source_file",
        "product",
        "ticker",
        "payment_date",
        "event_type",
        "institution",
        "quantity",
        "unit_price",
        "net_value",
        PROVENT_GROUP_COLUMN,
    ]
    return out[cols]


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

def save_clean_table(conn: sqlite3.Connection, name: str, df: pd.DataFrame) -> None:
    """Replace the whole clean table (simple and safe)."""
    df.to_sql(name, conn, index=False, if_exists="replace")
    print(f"  wrote {name}: {len(df)} rows")


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(
            f"Database not found at {DB_PATH}.\n"
            "Run first: uv run python ingest.py"
        )

    print(f"Database: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    try:
        print("\nBuilding positions ...")
        positions = build_positions(conn)
        print("\nBuilding provents ...")
        provents = build_provents(conn)

        print("\nSaving clean tables ...")
        save_clean_table(conn, "positions", positions)
        save_clean_table(conn, "provents", provents)
        conn.commit()
    finally:
        conn.close()

    print("\nDone.")


if __name__ == "__main__":
    main()
