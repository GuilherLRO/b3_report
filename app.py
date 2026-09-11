"""
Simple Streamlit dashboard for clean B3 tables.

Run:
    uv run streamlit run app.py

Needs:
    uv run python ingest.py
    uv run python build_clean.py
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from rules import GROUP_RULE_COLUMNS

DB_PATH = Path(__file__).resolve().parent / "data" / "b3.db"

# Default target weights (%) for rebalancing suggestions.
# Change these in the UI; they only need to cover groups you care about.
DEFAULT_TARGET_PCT = {
    "FII": 20.0,
    "RF": 50.0,
    "Ações Brasil": 15.0,
    "Ações Internacional": 15.0,
}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

@st.cache_data
def load_table(table_name: str) -> pd.DataFrame:
    if not DB_PATH.exists():
        return pd.DataFrame()
    conn = sqlite3.connect(DB_PATH)
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        if not exists:
            return pd.DataFrame()
        return pd.read_sql_query(f'SELECT * FROM "{table_name}"', conn)
    finally:
        conn.close()


def money(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

st.set_page_config(page_title="B3 Report", layout="wide")
st.title("B3 Report")

positions = load_table("positions")
provents = load_table("provents")

if positions.empty and provents.empty:
    st.error(
        "Clean tables not found. Run:\n\n"
        "`uv run python ingest.py`\n\n"
        "`uv run python build_clean.py`"
    )
    st.stop()

# Attributes you can filter by in "Inside a category".
# Rule columns + useful built-in fields (extend later as needed).
CATEGORY_FILTER_COLUMNS = list(GROUP_RULE_COLUMNS) + ["asset_class"]

tab_portfolio, tab_inside, tab_provents = st.tabs(
    ["Portfolio by month", "Inside a category", "Provents"]
)


# ---------------------------------------------------------------------------
# Tab 1 — Portfolio by month
# ---------------------------------------------------------------------------

with tab_portfolio:
    st.subheader("Portfolio distribution")

    if positions.empty:
        st.warning("No positions table yet.")
    else:
        months = sorted(positions["report_month"].dropna().unique().tolist())
        rule_cols = [c for c in GROUP_RULE_COLUMNS if c in positions.columns]
        if not rule_cols:
            st.error("No group-rule columns found on positions.")
            st.stop()

        col_a, col_b = st.columns(2)
        with col_a:
            selected_month = st.selectbox("Month", months, index=len(months) - 1)
        with col_b:
            group_col = st.selectbox("Group by (rule)", rule_cols, index=0)

        month_df = positions.loc[positions["report_month"] == selected_month].copy()
        total = float(month_df["market_value"].fillna(0).sum())

        st.metric(f"Total market value ({selected_month})", money(total))

        grouped = (
            month_df.groupby(group_col, dropna=False)["market_value"]
            .sum()
            .fillna(0)
            .sort_values(ascending=False)
            .reset_index()
        )
        grouped.columns = [group_col, "market_value"]
        grouped["pct"] = grouped["market_value"] / total * 100 if total else 0.0

        # Donut chart — parts of the total, with clear labels
        donut = px.pie(
            grouped,
            names=group_col,
            values="market_value",
            hole=0.45,
            title=f"Allocation — {selected_month}",
        )
        donut.update_traces(
            textposition="outside",
            textinfo="label+percent",
            textfont_size=14,
            pull=[0.02] * len(grouped),
        )
        donut.update_layout(
            showlegend=True,
            legend_title_text=group_col,
            margin=dict(t=60, b=40, l=40, r=40),
            font=dict(size=14),
        )
        st.plotly_chart(donut, width="stretch")

        show = grouped.copy()
        show["market_value"] = show["market_value"].map(money)
        show["pct"] = show["pct"].map(lambda x: f"{x:.1f}%")
        st.dataframe(show, width="stretch")

        # ----- Optional rebalancing suggestion -----
        st.markdown("---")
        st.subheader("Rebalancing (optional)")
        st.caption(
            "Set target % for each category. The table suggests how much to "
            "buy (+) or sell (−) to reach those targets for the selected month."
        )

        # Categories = current groups + any defaults (so targets stay editable)
        categories = sorted(
            set(grouped[group_col].astype(str).tolist()) | set(DEFAULT_TARGET_PCT)
        )

        target_inputs: dict[str, float] = {}
        input_cols = st.columns(min(4, max(1, len(categories))))
        for i, category in enumerate(categories):
            default = float(DEFAULT_TARGET_PCT.get(category, 0.0))
            with input_cols[i % len(input_cols)]:
                target_inputs[category] = st.number_input(
                    f"Target % — {category}",
                    min_value=0.0,
                    max_value=100.0,
                    value=default,
                    step=1.0,
                    key=f"target_{group_col}_{category}",
                )

        target_sum = sum(target_inputs.values())
        if abs(target_sum - 100.0) > 0.05:
            st.warning(f"Target percentages currently add up to {target_sum:.1f}% (aim for 100%).")
        else:
            st.success("Targets add up to 100%.")

        current_map = {
            str(row[group_col]): float(row["market_value"])
            for _, row in grouped.iterrows()
        }

        rebalance_rows = []
        for category, target_pct in target_inputs.items():
            current_value = current_map.get(category, 0.0)
            current_pct = (current_value / total * 100) if total else 0.0
            target_value = total * (target_pct / 100.0) if total else 0.0
            delta = target_value - current_value
            rebalance_rows.append(
                {
                    "category": category,
                    "current_pct": current_pct,
                    "target_pct": target_pct,
                    "current_value": current_value,
                    "target_value": target_value,
                    "suggested_trade": delta,
                    "action": (
                        "Buy" if delta > 1 else "Sell" if delta < -1 else "OK"
                    ),
                }
            )

        rebalance_df = pd.DataFrame(rebalance_rows)
        display_rebalance = rebalance_df.copy()
        display_rebalance["current_pct"] = display_rebalance["current_pct"].map(
            lambda x: f"{x:.1f}%"
        )
        display_rebalance["target_pct"] = display_rebalance["target_pct"].map(
            lambda x: f"{x:.1f}%"
        )
        display_rebalance["current_value"] = display_rebalance["current_value"].map(money)
        display_rebalance["target_value"] = display_rebalance["target_value"].map(money)
        display_rebalance["suggested_trade"] = display_rebalance["suggested_trade"].map(
            money
        )
        st.dataframe(display_rebalance, width="stretch")
        st.caption(
            "Suggested trade is relative to the current portfolio total "
            "(no extra cash assumed). Positive = invest more; negative = reduce."
        )

        with st.expander("Positions detail"):
            detail_cols = [
                c
                for c in [
                    "ticker",
                    "product",
                    "institution",
                    group_col,
                    "quantity",
                    "price",
                    "market_value",
                ]
                if c in month_df.columns
            ]
            st.dataframe(
                month_df[detail_cols].sort_values("market_value", ascending=False),
                width="stretch",
            )


# ---------------------------------------------------------------------------
# Tab 2 — Inside a category (drill-down)
# ---------------------------------------------------------------------------

with tab_inside:
    st.subheader("Inside a category")
    st.caption(
        "Pick an attribute (for example asset_group), then one category "
        "(for example Ações Brasil). See how products split inside that slice."
    )

    if positions.empty:
        st.warning("No positions table yet.")
    else:
        filter_cols = [c for c in CATEGORY_FILTER_COLUMNS if c in positions.columns]
        if not filter_cols:
            st.error("No filter columns available on positions.")
        else:
            months = sorted(positions["report_month"].dropna().unique().tolist())
            col_m, col_attr, col_cat = st.columns(3)
            with col_m:
                selected_month = st.selectbox(
                    "Month",
                    months,
                    index=len(months) - 1,
                    key="inside_month",
                )
            with col_attr:
                filter_col = st.selectbox(
                    "Attribute",
                    filter_cols,
                    index=0,
                    key="inside_attribute",
                )

            month_df = positions.loc[positions["report_month"] == selected_month].copy()
            categories = sorted(
                month_df[filter_col].dropna().astype(str).unique().tolist()
            )
            with col_cat:
                if not categories:
                    st.selectbox("Category", ["(none)"], disabled=True, key="inside_cat")
                    selected_category = None
                else:
                    selected_category = st.selectbox(
                        "Category",
                        categories,
                        index=0,
                        key="inside_cat",
                    )

            if selected_category is None:
                st.info("No categories for this month/attribute.")
            else:
                slice_df = month_df.loc[
                    month_df[filter_col].astype(str) == selected_category
                ].copy()
                slice_total = float(slice_df["market_value"].fillna(0).sum())
                portfolio_total = float(month_df["market_value"].fillna(0).sum())

                m1, m2 = st.columns(2)
                with m1:
                    st.metric(
                        f"Total in {selected_category}",
                        money(slice_total),
                    )
                with m2:
                    share = (
                        slice_total / portfolio_total * 100 if portfolio_total else 0.0
                    )
                    st.metric("Share of portfolio", f"{share:.1f}%")

                # Aggregate by ticker (same ticker at multiple brokers = one slice)
                by_ticker = (
                    slice_df.groupby("ticker", dropna=False)["market_value"]
                    .sum()
                    .fillna(0)
                    .sort_values(ascending=False)
                    .reset_index()
                )
                by_ticker.columns = ["ticker", "market_value"]
                by_ticker["pct"] = (
                    by_ticker["market_value"] / slice_total * 100
                    if slice_total
                    else 0.0
                )

                donut = px.pie(
                    by_ticker,
                    names="ticker",
                    values="market_value",
                    hole=0.45,
                    title=f"{selected_category} — products ({selected_month})",
                )
                donut.update_traces(
                    textposition="outside",
                    textinfo="label+percent",
                    textfont_size=14,
                    pull=[0.02] * len(by_ticker),
                )
                donut.update_layout(
                    showlegend=True,
                    legend_title_text="ticker",
                    margin=dict(t=60, b=40, l=40, r=40),
                    font=dict(size=14),
                )
                st.plotly_chart(donut, width="stretch")

                show = by_ticker.copy()
                show["market_value"] = show["market_value"].map(money)
                show["pct"] = show["pct"].map(lambda x: f"{x:.1f}%")
                st.dataframe(show, width="stretch")

                with st.expander("Position rows (brokers / accounts)"):
                    detail_cols = [
                        c
                        for c in [
                            "ticker",
                            "product",
                            "institution",
                            "account",
                            filter_col,
                            "quantity",
                            "price",
                            "market_value",
                        ]
                        if c in slice_df.columns
                    ]
                    st.dataframe(
                        slice_df[detail_cols].sort_values(
                            "market_value", ascending=False
                        ),
                        width="stretch",
                    )


# ---------------------------------------------------------------------------
# Tab 3 — Provents
# ---------------------------------------------------------------------------

with tab_provents:
    st.subheader("Provents over time")

    if provents.empty:
        st.warning("No provents table yet.")
    else:
        monthly = (
            provents.groupby("report_month", dropna=False)["net_value"]
            .sum()
            .fillna(0)
            .sort_index()
            .reset_index()
        )
        monthly.columns = ["report_month", "net_value"]

        # Bar chart with value labels on each bar (easy to spot)
        bars = px.bar(
            monthly,
            x="report_month",
            y="net_value",
            text="net_value",
            title="Monthly provents (net value)",
            labels={
                "report_month": "Month",
                "net_value": "Net value (R$)",
            },
        )
        bars.update_traces(
            texttemplate="R$ %{text:,.2f}",
            textposition="outside",
            textfont_size=14,
            cliponaxis=False,
        )
        bars.update_layout(
            xaxis_title="Month",
            yaxis_title="Net value (R$)",
            margin=dict(t=60, b=40, l=40, r=40),
            font=dict(size=14),
            uniformtext_minsize=12,
            uniformtext_mode="show",
        )
        bars.update_xaxes(type="category", tickfont=dict(size=14))
        bars.update_yaxes(tickfont=dict(size=14))
        st.plotly_chart(bars, width="stretch")

        months = monthly["report_month"].tolist()
        selected_month = st.selectbox(
            "Month details",
            months,
            index=len(months) - 1,
            key="provents_month",
        )

        month_provents = provents.loc[provents["report_month"] == selected_month].copy()
        month_total = float(month_provents["net_value"].fillna(0).sum())
        st.metric(f"Provents total ({selected_month})", money(month_total))

        detail_cols = [
            c
            for c in [
                "payment_date",
                "ticker",
                "product",
                "event_type",
                "institution",
                "quantity",
                "unit_price",
                "net_value",
            ]
            if c in month_provents.columns
        ]
        st.dataframe(month_provents[detail_cols], width="stretch")
