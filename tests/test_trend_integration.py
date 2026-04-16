import json
import unittest

from agent.tool_executor import ToolExecutor
from database.access_control import AccessControlStore
from database.connector import HRDatabase


class TrendIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = HRDatabase()
        cls.access = AccessControlStore()
        cls.executor = ToolExecutor(cls.db)
        cls.profile = cls.access.get_profile("demo.google@hr-intelligence.local")

    def test_stats_include_trend_summary_and_series(self):
        stats = self.db.get_table_stats(self.profile)

        self.assertIn("trend_summary", stats)
        self.assertIn("trend_series", stats)
        self.assertIn("headcount", stats["trend_series"])
        self.assertEqual(len(stats["trend_series"]["headcount"]), 12)
        self.assertTrue(stats["latest_trend_month"])
        self.assertIn("monthly trend", stats["trend_note"].lower())
        self.assertIn("rolling12_attrition_rate_pct", stats)

    def test_generate_standard_report_supports_period_based_headcount_trends(self):
        payload = json.loads(
            self.executor._generate_standard_report(
                {
                    "report_type": "headcount_trend",
                    "period_months": 6,
                    "explanation": "Validate period-based trend reporting",
                },
                self.profile,
            )
        )

        self.assertEqual(payload["report_type"], "headcount_trend")
        self.assertEqual(payload["report_period_months"], 6)
        self.assertEqual(payload["row_count"], 6)
        self.assertIn("simulated", payload["note"].lower())
        self.assertIn("MoMHeadcountChangePct", payload["results"][-1])
        self.assertIn("YoYHeadcountChangePct", payload["results"][-1])

    def test_generate_standard_report_supports_tenure_distribution_trends(self):
        payload = json.loads(
            self.executor._generate_standard_report(
                {
                    "report_type": "tenure_distribution_trend",
                    "period_months": 12,
                    "explanation": "Validate tenure trend reporting",
                },
                self.profile,
            )
        )

        self.assertEqual(payload["report_type"], "tenure_distribution_trend")
        self.assertEqual(payload["row_count"], 12)
        self.assertIn("TenureBand0To1Pct", payload["results"][0])
        self.assertIn("TenureBand10PlusPct", payload["results"][0])


if __name__ == "__main__":
    unittest.main()
