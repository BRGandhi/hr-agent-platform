import json
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from database.workforce_history import SimulationConfig, materialize_workforce_history


class WorkforceHistorySimulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.temp_dir.name) / "hr_data.db"
        shutil.copyfile(Path(__file__).resolve().parents[1] / "hr_data.db", cls.db_path)
        cls.metadata = materialize_workforce_history(
            cls.db_path,
            SimulationConfig(),
        )

    @classmethod
    def tearDownClass(cls):
        try:
            cls.temp_dir.cleanup()
        except PermissionError:
            pass

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def test_materialize_creates_history_tables_and_views(self):
        with self._connect() as conn:
            self.assertGreater(conn.execute("SELECT COUNT(*) FROM employees_monthly_history").fetchone()[0], 40000)
            self.assertGreater(conn.execute("SELECT COUNT(*) FROM workforce_monthly_events").fetchone()[0], 2000)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM workforce_monthly_summary").fetchone()[0],
                36 * 4,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(DISTINCT SnapshotMonth) FROM employees_monthly_history").fetchone()[0],
                36,
            )
            self.assertGreater(
                conn.execute("SELECT COUNT(*) FROM employees_trend_current").fetchone()[0],
                1000,
            )

    def test_latest_month_aligns_with_core_metric_targets(self):
        self.assertTrue(self.metadata["validation"]["passed"])
        with self._connect() as conn:
            latest = conn.execute(
                """
                SELECT *
                FROM workforce_monthly_summary
                WHERE SnapshotMonth = ? AND Department = 'All'
                """,
                (self.metadata["latest_snapshot_month"],),
            ).fetchone()
            self.assertEqual(int(latest["Headcount"]), int(self.metadata["target_latest_headcount"]))
            self.assertAlmostEqual(float(latest["Rolling12HiringRatePct"]), 20.0, delta=2.5)
            self.assertAlmostEqual(
                float(latest["Rolling12AttritionRatePct"]),
                float(self.metadata["annual_attrition_rate"]) * 100,
                delta=3.5,
            )
            self.assertAlmostEqual(
                float(latest["Rolling12PromotionRatePct"]),
                float(self.metadata["annual_promotion_rate"]) * 100,
                delta=4.0,
            )

            departments = conn.execute(
                """
                SELECT Department
                FROM workforce_monthly_summary
                WHERE SnapshotMonth = ? AND Department != 'All'
                ORDER BY Headcount DESC
                """,
                (self.metadata["latest_snapshot_month"],),
            ).fetchall()
            self.assertEqual(
                [row["Department"] for row in departments],
                ["Research & Development", "Sales", "Human Resources"],
            )

            validation_summary = json.loads(
                conn.execute(
                    "SELECT value FROM workforce_simulation_metadata WHERE key = 'validation_summary'"
                ).fetchone()[0]
            )
            self.assertTrue(validation_summary["passed"])

    def test_monthly_history_preserves_logical_constraints(self):
        with self._connect() as conn:
            violations = conn.execute(
                """
                SELECT COUNT(*)
                FROM employees_monthly_history
                WHERE YearsInCurrentRole > YearsAtCompany
                   OR YearsSinceLastPromotion > YearsAtCompany
                   OR YearsWithCurrManager > YearsAtCompany
                   OR TotalWorkingYears < YearsAtCompany
                   OR Age < 18
                   OR JobLevel < 1
                   OR JobLevel > 5
                """
            ).fetchone()[0]
            self.assertEqual(violations, 0)


if __name__ == "__main__":
    unittest.main()
