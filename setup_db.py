"""
Run this once to load the IBM HR Attrition CSV into SQLite.

Usage:
    python setup_db.py
    python setup_db.py --csv path/to/custom.csv  (optional override)
"""

import sqlite3
import sys
import argparse
import pandas as pd
from pathlib import Path

DEFAULT_CSV = Path(__file__).parent.parent / "WA_Fn-UseC_-HR-Employee-Attrition.csv"
DEFAULT_DB = Path(__file__).parent / "hr_data.db"


def setup_database(csv_path: str, db_path: str) -> None:
    print(f"Reading CSV: {csv_path}")
    df = pd.read_csv(csv_path)
    print(f"  Loaded {len(df)} rows, {len(df.columns)} columns")

    print(f"Writing to SQLite: {db_path}")
    conn = sqlite3.connect(db_path)
    df.to_sql("employees", conn, if_exists="replace", index=False)
    conn.close()

    # Verify
    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
    attrition = conn.execute(
        "SELECT Attrition, COUNT(*) FROM employees GROUP BY Attrition"
    ).fetchall()
    conn.close()

    print(f"\nDatabase ready: {db_path}")
    print(f"  Total rows: {count}")
    for row in attrition:
        print(f"  Attrition={row[0]}: {row[1]} employees")
    print("\nSetup complete! You can now run: python -m uvicorn server:app --host 127.0.0.1 --port 8000")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load HR CSV into SQLite")
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
            "Place WA_Fn-UseC_-HR-Employee-Attrition.csv in the Downloads folder "
            "or pass --csv /path/to/file.csv"
        )
        sys.exit(1)

    setup_database(args.csv, args.db)
