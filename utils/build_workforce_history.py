from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.workforce_history import SimulationConfig, materialize_workforce_history


def main() -> None:
    parser = argparse.ArgumentParser(description="Build simulated monthly workforce history tables.")
    parser.add_argument(
        "--db",
        default=str(Path(__file__).resolve().parents[1] / "hr_data.db"),
        help="Path to hr_data.db",
    )
    parser.add_argument(
        "--seed",
        default=20260415,
        type=int,
        help="Random seed for deterministic workforce simulation",
    )
    args = parser.parse_args()

    metadata = materialize_workforce_history(
        args.db,
        SimulationConfig(random_seed=args.seed),
    )
    validation = metadata.get("validation", {})
    print("Simulated workforce history refreshed.")
    print(f"Latest month: {metadata.get('latest_snapshot_month')}")
    print(f"Months simulated: {metadata.get('months')}")
    print(f"Target latest headcount: {metadata.get('target_latest_headcount')}")
    print(f"Validation passed: {validation.get('passed')}")


if __name__ == "__main__":
    main()
