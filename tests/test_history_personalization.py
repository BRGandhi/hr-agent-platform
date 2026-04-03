import os
import tempfile
import unittest

from database.context_store import ContextStore


class ContextStorePersonalizationTests(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        self.store = ContextStore(db_path=self.db_path)
        self.user_email = "tester@hr-intelligence.local"

    def tearDown(self):
        del self.store
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except PermissionError:
                pass

    def test_relevant_questions_prefers_matching_metric_domain(self):
        self.store.remember(
            self.user_email,
            "What is the headcount for Research & Development?",
            "The current headcount is 430 employees.",
        )
        self.store.remember(
            self.user_email,
            "Which teams have the highest attrition risk in Sales?",
            "Sales leadership and field teams have the highest attrition risk.",
        )

        results = self.store.relevant_questions(
            self.user_email,
            "Show attrition risk by team for my scope",
            allowed_metrics=["headcount", "attrition"],
        )

        self.assertGreaterEqual(len(results), 1)
        self.assertIn("attrition", results[0]["question"].lower())
        self.assertIn("Attrition rate", results[0]["topics"])

    def test_history_summary_filters_disallowed_topics(self):
        self.store.remember(
            self.user_email,
            "What is the attrition rate for my scope?",
            "The attrition rate is 16.1%.",
        )
        self.store.remember(
            self.user_email,
            "Which HR access policy applies to my role?",
            "Your role follows the HR analytics access policy.",
        )
        self.store.remember(
            self.user_email,
            "What is the headcount for my scope?",
            "Your scoped headcount is 1,470 employees.",
        )

        summary = self.store.history_summary(
            self.user_email,
            allowed_metrics=["headcount", "attrition"],
        )

        favorite_topics = [item["topic"] for item in summary["favorite_topics"]]
        favorite_questions = [item["question"] for item in summary["favorite_questions"]]

        self.assertIn("Headcount", favorite_topics)
        self.assertIn("Attrition rate", favorite_topics)
        self.assertNotIn("Access policy guidance", favorite_topics)
        self.assertTrue(any("headcount" in question.lower() for question in favorite_questions))
        self.assertTrue(any("attrition" in question.lower() for question in favorite_questions))
        self.assertFalse(any("policy" in question.lower() for question in favorite_questions))


if __name__ == "__main__":
    unittest.main()
