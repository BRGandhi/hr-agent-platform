"""
Build the HR SQLite database from the original IBM attrition CSV only.

The runtime database contains:
- `employees`: the original CSV rows
- `employees_current`: a compatibility view over the same original rows
- simulated 36-month trend tables derived from the base snapshot

Usage:
    python setup_db.py
    python setup_db.py --csv path/to/custom.csv
    python setup_db.py --db path/to/hr_data.db
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import pandas as pd

from database.workforce_history import materialize_workforce_history

CSV_NAME = "WA_Fn-UseC_-HR-Employee-Attrition.csv"


def resolve_default_csv() -> Path:
    candidates = [
        Path(__file__).parent.parent / CSV_NAME,
        Path(__file__).parent / CSV_NAME,
        Path.home() / "Downloads" / CSV_NAME,
        Path.home() / "Downloads" / "Work Projects" / CSV_NAME,
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


DEFAULT_CSV = resolve_default_csv()
DEFAULT_DB = Path(__file__).parent / "hr_data.db"


def setup_database(csv_path: str, db_path: str) -> None:
    print(f"Reading CSV: {csv_path}")
    df = pd.read_csv(csv_path)
    print(f"  Loaded original data: {len(df)} rows, {len(df.columns)} columns")

    print(f"Writing original dataset to SQLite: {db_path}")
    conn = sqlite3.connect(db_path)
    df.to_sql("employees", conn, if_exists="replace", index=False)
    conn.execute("DROP VIEW IF EXISTS employees_current")
    conn.execute(
        """
        CREATE VIEW employees_current AS
        SELECT *
        FROM employees
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_employees_employee_number ON employees (EmployeeNumber)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_employees_department ON employees (Department)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_employees_attrition ON employees (Attrition)")
    conn.commit()
    conn.close()

    conn = sqlite3.connect(db_path)
    row_count = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
    attrition = conn.execute(
        "SELECT Attrition, COUNT(*) FROM employees GROUP BY Attrition ORDER BY Attrition"
    ).fetchall()
    conn.close()

    print(f"\nDatabase ready: {db_path}")
    print(f"  Original rows: {row_count}")
    for row in attrition:
        print(f"  Attrition={row[0]}: {row[1]} employees")
    print("\nBuilding simulated monthly workforce history...")
    metadata = materialize_workforce_history(db_path)
    validation = metadata.get("validation", {})
    print(
        "  Simulated latest active headcount: "
        f"{metadata.get('target_latest_headcount')} across {metadata.get('months')} months"
    )
    print(
        "  Validation status: "
        f"{'passed' if validation.get('passed') else 'needs review'}"
    )
    print("\nSetup complete! You can now run: python -m uvicorn server:app --host 127.0.0.1 --port 8000")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load the original HR CSV into SQLite")
    parser.add_argument(
        "--csv",
        default=str(DEFAULT_CSV),
        help=f"Path to CSV file (default: {DEFAULT_CSV})",
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB),
        help=f"Path to SQLite DB (default: {DEFAULT_DB})",
    )
    args = parser.parse_args()

    if not Path(args.csv).exists():
        print(f"ERROR: CSV not found: {args.csv}")
        print(
            "Place WA_Fn-UseC_-HR-Employee-Attrition.csv in a known location such as "
            "Downloads or Downloads/Work Projects, or pass --csv /path/to/file.csv"
        )
        sys.exit(1)

    setup_database(args.csv, args.db)
