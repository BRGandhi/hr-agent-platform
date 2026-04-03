import os
import tempfile
import unittest
from unittest.mock import patch

from agent.llm_client import LLMConfig, LLMResponse
from agent.orchestrator import HRAgent
from database.access_control import AccessProfile
from database.context_store import ContextStore


class FakeLLMClient:
    def create_response(self, system_prompt: str, tools: list[dict], messages: list[dict]) -> LLMResponse:
        return LLMResponse(
            text="Which breakdown would you like next: job role, job level, or demographics?",
            tool_calls=[],
            stop_reason="end_turn",
        )


class ChatContextTests(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        self.store = ContextStore(db_path=self.db_path)
        self.access_profile = AccessProfile(
            email="tester@hr-intelligence.local",
            role="HR Business Partner",
            scope_name="Business Units",
            allowed_departments=["Research & Development", "Sales", "Human Resources"],
            allowed_metrics=["headcount", "attrition", "tenure", "demographics"],
            allowed_doc_tags=["policy"],
        )

    def tearDown(self):
        del self.store
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except PermissionError:
                pass

    def _make_agent(self) -> HRAgent:
        with patch("agent.orchestrator.create_llm_client", return_value=FakeLLMClient()):
            return HRAgent(
                llm_config=LLMConfig(provider="anthropic", model="fake-model", api_key="fake-key"),
                db=object(),
                context_store=self.store,
            )

    def test_affirmative_follow_up_uses_prior_hr_question_for_access(self):
        agent = self._make_agent()
        agent.conversation_history = [
            {"role": "user", "content": "What is the headcount for Business Units?"},
            {
                "role": "assistant",
                "content": (
                    "The scoped headcount is 1,470 employees. "
                    "Would you like a deeper breakdown, a visualization, or a roster?"
                ),
            },
        ]

        events = list(agent.chat("yes", self.access_profile))

        self.assertTrue(events)
        final_event = events[-1]
        self.assertEqual(final_event["type"], "final_text")
        self.assertNotIn("This platform only supports HR insights", final_event["text"])
        self.assertIn("breakdown", final_event["text"].lower())

    def test_short_dimension_follow_up_inherits_prior_question_context(self):
        agent = self._make_agent()
        agent.conversation_history = [
            {"role": "user", "content": "What is the headcount for Business Units?"},
            {"role": "assistant", "content": "I can break that down further if you'd like."},
        ]

        access_check_message = agent._build_access_check_message("job level", table_context=None)

        self.assertIn("follow-up to prior hr question", access_check_message.lower())
        self.assertIn("headcount", access_check_message.lower())
        allowed, reason = self.access_profile.can_access_question(access_check_message)
        self.assertTrue(allowed, reason)

    def test_context_anchor_skips_prior_generic_follow_up(self):
        agent = self._make_agent()
        agent.conversation_history = [
            {"role": "user", "content": "What is the headcount for Business Units?"},
            {"role": "assistant", "content": "Would you like a deeper breakdown?"},
            {"role": "user", "content": "yes"},
            {"role": "assistant", "content": "Which breakdown would you like next?"},
        ]

        access_check_message = agent._build_access_check_message("job level", table_context=None)

        self.assertIn("headcount for business units", access_check_message.lower())
        self.assertNotIn("follow-up to prior hr question: yes", access_check_message.lower())


if __name__ == "__main__":
    unittest.main()
