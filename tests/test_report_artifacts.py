import unittest

from utils.report_artifacts import (
    attach_story_chart,
    build_configured_excel,
    build_pdf_report,
    build_ppt_report,
    build_report_story,
    configure_export_rows,
)


class ReportArtifactTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {"Department": "Sales", "AttritionRate_pct": 16.1, "EmployeeCount": 420},
            {"Department": "Research & Development", "AttritionRate_pct": 9.4, "EmployeeCount": 680},
            {"Department": "Human Resources", "AttritionRate_pct": 12.8, "EmployeeCount": 95},
        ]
        self.trend_rows = [
            {"SnapshotMonth": "2025-10-01", "Headcount": 1198, "MoMHeadcountChangePct": 0.8, "YoYHeadcountChangePct": 3.1},
            {"SnapshotMonth": "2025-11-01", "Headcount": 1207, "MoMHeadcountChangePct": 0.8, "YoYHeadcountChangePct": 3.4},
            {"SnapshotMonth": "2025-12-01", "Headcount": 1218, "MoMHeadcountChangePct": 0.9, "YoYHeadcountChangePct": 3.7},
            {"SnapshotMonth": "2026-01-01", "Headcount": 1235, "MoMHeadcountChangePct": 1.4, "YoYHeadcountChangePct": 5.2},
            {"SnapshotMonth": "2026-02-01", "Headcount": 1236, "MoMHeadcountChangePct": 0.1, "YoYHeadcountChangePct": 4.7},
            {"SnapshotMonth": "2026-03-01", "Headcount": 1233, "MoMHeadcountChangePct": -0.2, "YoYHeadcountChangePct": 3.8},
        ]

    def test_configure_export_rows_applies_filter_sort_and_columns(self):
        rows = configure_export_rows(
            self.rows,
            columns=["Department", "EmployeeCount"],
            sort_by="EmployeeCount",
            sort_direction="desc",
            filter_column="Department",
            filter_value="Sales",
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Department"], "Sales")
        self.assertEqual(list(rows[0].keys()), ["Department", "EmployeeCount"])

    def test_artifact_builders_return_binary_outputs(self):
        story = build_report_story(
            "Attrition Brief",
            self.rows,
            role="HR Business Partner",
            scope_name="Business Units",
        )
        story = attach_story_chart(story, self.rows)

        pdf_bytes = build_pdf_report(story)
        ppt_bytes = build_ppt_report(story)
        excel_bytes = build_configured_excel("Attrition Brief", self.rows)

        self.assertGreater(len(pdf_bytes), 1000)
        self.assertGreater(len(ppt_bytes), 1000)
        self.assertGreater(len(excel_bytes), 1000)
        self.assertTrue(story.chart_image)

    def test_trend_story_mentions_simulated_monthly_source(self):
        story = build_report_story(
            "Headcount Trend Brief",
            self.trend_rows,
            role="HR Business Partner",
            scope_name="Business Units",
        )

        self.assertIn("simulated workforce trend layer", story.source_note.lower())
        self.assertIn("2026", story.headline)
        self.assertTrue(any(metric.label.startswith("Latest") or metric.label.endswith("change") for metric in story.key_metrics))


if __name__ == "__main__":
    unittest.main()
