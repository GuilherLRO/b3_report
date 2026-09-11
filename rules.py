"""
Classification rules for clean tables.

Add a new rule later:
  1. Write a function like classify_asset_group
  2. Call it from build_clean.py to create a new column
  3. Add the column name to GROUP_RULE_COLUMNS so Streamlit can use it
"""

from __future__ import annotations

import re

import pandas as pd

# Columns the Streamlit app can use in the "Group by" dropdown.
# Add new rule column names here when you create them.
GROUP_RULE_COLUMNS = [
    "asset_group",
    "rf_rate_type",  # Prefixado / Pós-fixado / Misto (mainly for RF)
]

# Column used to stack provents in Monthly evolution
PROVENT_GROUP_COLUMN = "provent_group"


def _text(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def classify_asset_group(row: pd.Series) -> str:
    """
    First aggregation rule.

    Labels:
      - FII
      - RF
      - Ações Brasil
      - Ações Internacional
      - Outros  (fallback so gaps are visible)
    """
    asset_class = _text(row.get("asset_class"))
    asset_type = _text(row.get("asset_type")).lower()
    product = _text(row.get("product")).lower()
    ticker = _text(row.get("ticker")).upper()

    if asset_class in {"fixed_income", "treasury"}:
        return "RF"

    if asset_class == "funds":
        return "FII"

    if asset_class == "etf":
        if "internacional" in asset_type:
            return "Ações Internacional"
        return "Ações Brasil"

    if asset_class == "stocks":
        return "Ações Brasil"

    # Extra safety if asset_class is missing later
    if "fii" in product or "imob" in product:
        return "FII"
    if ticker.endswith("11") and "ishares" in product:
        return "Ações Internacional"

    return "Outros"


def classify_rf_rate_type(row: pd.Series) -> str:
    """
    Renda fixa rate style (also used for Tesouro, since it is RF).

    Uses B3 Indexador (+ product name as fallback).

    Labels:
      - Prefixado
      - Pós-fixado
      - Misto              (e.g. IPCA+)
      - Não classificado   (RF but indexer unclear)
      - Não se aplica      (not RF)
    """
    asset_class = _text(row.get("asset_class"))
    if asset_class not in {"fixed_income", "treasury"}:
        return "Não se aplica"

    indexer = _text(row.get("indexer")).lower()
    product = _text(row.get("product")).lower()

    if indexer in {"di", "cdi", "selic"} or "selic" in product:
        return "Pós-fixado"

    if indexer in {"prefixado", "pre"} or "prefixado" in product:
        return "Prefixado"

    if indexer in {"ipca", "igpm", "igp-m"} or "ipca" in product or "igp" in product:
        return "Misto"

    # Some B3 months leave Indexador as "-" for CDBs/LCAs that are DI elsewhere
    if indexer in {"", "-"} and (
        product.startswith("cdb") or product.startswith("lca") or product.startswith("lci")
    ):
        return "Pós-fixado"

    return "Não classificado"


def _looks_like_fii(ticker: str, product: str) -> bool:
    product_l = product.lower()
    if "fii" in product_l or "imob" in product_l or "fundo de investimento imobili" in product_l:
        return True
    # Typical FII ticker: ABCD11 (not ETF names we already know as international)
    if re.fullmatch(r"[A-Z]{4}11", ticker):
        return True
    return False


def _looks_like_br_stock(ticker: str) -> bool:
    # Common B3 equity suffixes: 3 ON, 4 PN, 5/6/7/8 units/receipts, etc.
    return bool(re.fullmatch(r"[A-Z]{4}\d{1,2}", ticker)) and not ticker.endswith("11")


def classify_provent_group(row: pd.Series) -> str:
    """
    Clear buckets for the provents stacked chart.

    Separates:
      - Juros Sobre Capital Próprio
      - Dividendos (when B3 uses that event type)
      - Rendimento FII
      - Rendimento Ações Brasil
      - Outros
    """
    event = _text(row.get("event_type")).lower()
    ticker = _text(row.get("ticker")).upper()
    product = _text(row.get("product"))

    if "juros" in event and "capital" in event:
        return "Juros Sobre Capital Próprio"

    if "dividendo" in event:
        if _looks_like_fii(ticker, product):
            return "Dividendos FII"
        return "Dividendos Ações Brasil"

    if "rendimento" in event:
        if _looks_like_fii(ticker, product):
            return "Rendimento FII"
        if _looks_like_br_stock(ticker):
            return "Rendimento Ações Brasil"
        return "Rendimento (outros)"

    return "Outros"


def parse_ticker_from_product(product: str) -> str | None:
    """
    From 'BTLG11 - SOME FUND NAME' return 'BTLG11'.
    Returns None when it does not look like a ticker.
    """
    text = _text(product)
    if not text:
        return None
    match = re.match(r"^([A-Z0-9]{4,12})\s*-", text, flags=re.IGNORECASE)
    if match:
        return match.group(1).upper()
    return None
