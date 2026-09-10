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
]


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
