import json
import unittest

from agent.tool_executor import ToolExecutor


class VisualizationToolTests(unittest.TestCase):
    def setUp(self):
        self.executor = ToolExecutor(db=object(), context_store=None)

    def test_suggest_visualizations_returns_ranked_options_with_metadata(self):
        rows = [
            {"Department": "Sales", "OverTime": "Yes", "AttritionRate_pct": 37.5},
            {"Department": "Sales", "OverTime": "No", "AttritionRate_pct": 11.2},
            {"Department": "Research & Development", "OverTime": "Yes", "AttritionRate_pct": 24.8},
            {"Department": "Research & Development", "OverTime": "No", "AttritionRate_pct": 8.4},
            {"Department": "Human Resources", "OverTime": "Yes", "AttritionRate_pct": 22.0},
            {"Department": "Human Resources", "OverTime": "No", "AttritionRate_pct": 5.5},
        ]

        payload = json.loads(
            self.executor._suggest_visualizations(
                {
                    "data": json.dumps(rows),
                    "title": "Attrition Hotspots",
                    "question": "Which combinations of department and overtime have the highest attrition rate?",
                    "max_options": 4,
                }
            )
        )

        self.assertIn("options", payload)
        self.assertEqual(payload["recommended_option_id"], "option_1")
        self.assertGreaterEqual(len(payload["options"]), 3)
        self.assertTrue(any(option["chart_type"] == "heatmap" for option in payload["options"]))

        top_option = payload["options"][0]
        self.assertIn("business_question", top_option)
        self.assertIn("best_for", top_option)
        self.assertIn("watch_out", top_option)
        self.assertIn("chart_json", top_option)

    def test_create_visualization_supports_heatmap(self):
        rows = [
            {"Department": "Sales", "OverTime": "Yes", "AttritionRate_pct": 37.5},
            {"Department": "Sales", "OverTime": "No", "AttritionRate_pct": 11.2},
            {"Department": "Research & Development", "OverTime": "Yes", "AttritionRate_pct": 24.8},
            {"Department": "Research & Development", "OverTime": "No", "AttritionRate_pct": 8.4},
        ]

        payload = json.loads(
            self.executor._create_visualization(
                {
                    "chart_type": "heatmap",
                    "data": json.dumps(rows),
                    "x_column": "Department",
                    "y_column": "OverTime",
                    "color_column": "AttritionRate_pct",
                    "title": "Attrition rate heatmap",
                }
            )
        )

        self.assertIn("chart_json", payload)
        figure = json.loads(payload["chart_json"])
        self.assertEqual(figure["data"][0]["type"], "heatmap")
        self.assertIn("colorscale", figure["data"][0])


if __name__ == "__main__":
    unittest.main()
