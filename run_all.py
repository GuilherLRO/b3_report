"""
Run the full data pipeline:

  1. ingest.py      — Excel → raw_* tables
  2. build_clean.py  — raw_* → positions + provents

Usage:
    uv run python run_all.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def run_step(script_name: str) -> None:
    print("\n" + "=" * 60)
    print(f"Running {script_name}")
    print("=" * 60)
    result = subprocess.run(
        [sys.executable, str(ROOT / script_name)],
        cwd=ROOT,
    )
    if result.returncode != 0:
        raise SystemExit(f"{script_name} failed with exit code {result.returncode}")


def main() -> None:
    run_step("ingest.py")
    run_step("build_clean.py")
    print("\nAll steps finished.")
    print("Next (optional): uv run streamlit run app.py")


if __name__ == "__main__":
    main()
