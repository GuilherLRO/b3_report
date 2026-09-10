# B3 Report

Turn monthly B3 consolidated Excel reports into a small local database and a Streamlit dashboard.

Keep it simple: drop a file in a folder, run one command, open the app.

## What you get

1. **Raw tables** — one SQLite table per Excel sheet (nothing important lost)
2. **Clean tables** — `positions` and `provents`, ready to query
3. **Rules** — e.g. classify holdings as FII, RF, Ações Brasil, Ações Internacional
4. **Streamlit app** — portfolio donut + optional rebalancing targets, and monthly provents

```text
relatorios_mensais/*.xlsx
        │
        ▼
   ingest.py  ──►  raw_* tables
        │
        ▼
 build_clean.py + rules.py  ──►  positions, provents
        │
        ▼
     app.py (Streamlit)
```

## Setup

Install [uv](https://docs.astral.sh/uv/), then:

```bash
git clone https://github.com/GuilherLRO/b3_report.git
cd b3_report
uv sync
```

## Quick start

1. Put monthly B3 reports in `relatorios_mensais/`  
   Expected name pattern: `relatorio-consolidado-mensal-YYYY-mes.xlsx`  
   (`.xlsx` files in that folder are gitignored — keep them only on your machine)

2. Build everything:

```bash
uv run python run_all.py
```

3. Open the dashboard:

```bash
uv run streamlit run app.py
```

Or run steps separately:

```bash
uv run python ingest.py
uv run python build_clean.py
uv run streamlit run app.py
```

The SQLite file is created at `data/b3.db` (gitignored — regenerate anytime).

## Project layout

| File | Role |
|------|------|
| `run_all.py` | Runs ingest + clean build |
| `ingest.py` | Excel → `raw_*` tables |
| `rules.py` | Classification rules (extend here) |
| `build_clean.py` | `raw_*` → `positions` + `provents` |
| `app.py` | Streamlit UI |
| `explore_db.ipynb` | Inspect tables in a notebook |
| `relatorios_mensais/` | Drop monthly Excel files here |
| `pyproject.toml` / `uv.lock` | Dependencies (managed with uv) |

## Database tables

### Raw (`ingest.py`)

| Excel sheet | Table |
|-------------|--------|
| Posição - Ações | `raw_posicao_acoes` |
| Posição - ETF | `raw_posicao_etf` |
| Posição - Fundos | `raw_posicao_fundos` |
| Posição - Renda Fixa | `raw_posicao_renda_fixa` |
| Posição - Tesouro Direto | `raw_posicao_tesouro` |
| Proventos Recebidos | `raw_proventos` |
| Negociações | `raw_negociacoes` |

Every raw table also has `report_month` (e.g. `2026-08`) and `source_file`.

### Clean (`build_clean.py`)

- **`positions`** — unified holdings with `ticker`, `quantity`, `price`, `market_value`, plus rule columns
- **`provents`** — income events with `ticker`, `payment_date`, `net_value`, etc.

## Classification rule: `asset_group`

| Label | Meaning |
|-------|---------|
| `FII` | Real-estate funds |
| `RF` | Fixed income + Tesouro Direto |
| `Ações Brasil` | Brazilian stocks / local ETFs |
| `Ações Internacional` | International ETFs (e.g. IVVB11) |
| `Outros` | Unmatched — check/adjust the rule |

### Add another rule later

1. Write a function in `rules.py`
2. Add the column in `build_clean.py`
3. Append the column name to `GROUP_RULE_COLUMNS`
4. Run `uv run python build_clean.py` again

The app “Group by” dropdown picks up new rule columns automatically.

## Streamlit app

**Portfolio by month**

- Choose month and grouping rule
- Donut chart of portfolio allocation
- Optional rebalancing: edit target % in the UI and see suggested buy/sell amounts

**Provents**

- Monthly net-value chart with clear labels
- Pick a month to see payment details

## Explore in a notebook

```bash
uv run jupyter notebook explore_db.ipynb
```

## Notes

- Re-running `run_all.py` for the same month replaces that month’s raw rows, then rebuilds clean tables.
- `data/b3.db` and `relatorios_mensais/*.xlsx` are gitignored (generated DB + personal reports).
- Designed to stay modular: ingest, rules, clean build, and UI can change independently.
