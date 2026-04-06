import json
import os
import tempfile
import unittest
from unittest.mock import patch

from agent.llm_client import LLMClientError, LLMConfig, LLMResponse, ToolCall
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


class DirectAnswerLLMClient:
    def create_response(self, system_prompt: str, tools: list[dict], messages: list[dict]) -> LLMResponse:
        return LLMResponse(
            text="The current headcount for Business Units is 1,470 employees.",
            tool_calls=[],
            stop_reason="end_turn",
        )


class AnswerWithFollowUpsLLMClient:
    def create_response(self, system_prompt: str, tools: list[dict], messages: list[dict]) -> LLMResponse:
        return LLMResponse(
            text=(
                "The current headcount for Business Units is 1,470 employees.\n\n"
                "### Follow-up questions\n"
                "- Can you break headcount down by department in Business Units?\n"
                "- Which employee job roles have the highest headcount in Business Units?"
            ),
            tool_calls=[],
            stop_reason="end_turn",
        )


class ExplodingLLMClient:
    def create_response(self, system_prompt: str, tools: list[dict], messages: list[dict]) -> LLMResponse:
        raise AssertionError("LLM should not be called when the runtime asks a clarifying question first.")


class ToolThenRateLimitLLMClient:
    def __init__(self):
        self.call_count = 0

    def create_response(self, system_prompt: str, tools: list[dict], messages: list[dict]) -> LLMResponse:
        self.call_count += 1
        if self.call_count == 1:
            return LLMResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="call_query",
                        name="query_hr_database",
                        input={
                            "sql_query": (
                                "SELECT Department, AVG(JobSatisfaction) AS AvgSatisfaction, "
                                "AVG(CASE WHEN Attrition = 'Yes' THEN 100.0 ELSE 0 END) AS AttritionRate, "
                                "COUNT(*) AS Headcount FROM employees GROUP BY Department"
                            ),
                            "explanation": "Get average satisfaction and attrition rate by department.",
                        },
                    )
                ],
                stop_reason="tool_use",
            )
        raise LLMClientError("Anthropic rate limit reached. Please try again shortly.")


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
            allowed_metrics=["headcount", "attrition", "tenure", "demographics", "satisfaction"],
            allowed_doc_tags=["policy"],
        )

    def tearDown(self):
        del self.store
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except PermissionError:
                pass

    def _make_agent(self, llm_client=None) -> HRAgent:
        with patch("agent.orchestrator.create_llm_client", return_value=llm_client or FakeLLMClient()):
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

        access_check_message, _ = agent._build_access_check_message(
            "job level",
            table_context=None,
            access_profile=self.access_profile,
        )

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

        access_check_message, _ = agent._build_access_check_message(
            "job level",
            table_context=None,
            access_profile=self.access_profile,
        )

        self.assertIn("headcount for business units", access_check_message.lower())
        self.assertNotIn("follow-up to prior hr question: yes", access_check_message.lower())

    def test_follow_up_uses_recent_memory_when_session_context_is_missing(self):
        agent = self._make_agent()
        self.store.remember(
            self.access_profile.email,
            "What is the headcount for Business Units?",
            "The scoped headcount is 1,470 employees. Would you like a deeper breakdown by job role, demographics, or attrition?",
        )

        access_check_message, follow_up_context = agent._build_access_check_message(
            "yes",
            table_context=None,
            access_profile=self.access_profile,
        )

        self.assertIn("headcount for business units", access_check_message.lower())
        self.assertIn("prior assistant context", access_check_message.lower())
        self.assertIn("headcount", str(follow_up_context.get("question", "")).lower())
        allowed, reason = self.access_profile.can_access_question(access_check_message)
        self.assertTrue(allowed, reason)

    def test_recalled_memory_primes_follow_up_context(self):
        agent = self._make_agent()
        agent.prime_recalled_memory(
            "What is the headcount for Business Units?",
            "The scoped headcount is 1,470 employees. Would you like a deeper breakdown by job level or department?",
        )

        access_check_message, follow_up_context = agent._build_access_check_message(
            "yes",
            table_context=None,
            access_profile=self.access_profile,
        )

        self.assertIn("headcount for business units", access_check_message.lower())
        self.assertIn("headcount", str(follow_up_context.get("question", "")).lower())
        allowed, reason = self.access_profile.can_access_question(access_check_message)
        self.assertTrue(allowed, reason)

    def test_agent_skips_helpful_memories_when_match_is_not_close_enough(self):
        agent = self._make_agent()
        memory_id = self.store.remember(
            self.access_profile.email,
            "Show headcount by department for Business Units",
            "Research & Development has the largest department headcount.",
        )
        self.store.record_feedback(self.access_profile.email, memory_id, "yes")

        events = list(agent.chat("Which job roles have the highest headcount in Business Units?", self.access_profile))

        event_types = [event["type"] for event in events]
        self.assertNotIn("helpful_memories", event_types)
        self.assertEqual(event_types[-1], "final_text")

    def test_agent_appends_follow_up_questions_when_model_omits_them(self):
        agent = self._make_agent(llm_client=DirectAnswerLLMClient())

        events = list(agent.chat("What is the headcount for Business Units?", self.access_profile))

        final_text = events[-1]["text"]
        self.assertIn("The current headcount for Business Units is 1,470 employees.", final_text)
        self.assertIn("### Follow-up questions", final_text)
        bullet_questions = [
            line for line in final_text.splitlines()
            if line.strip().startswith("- ") and line.strip().endswith("?")
        ]
        self.assertGreaterEqual(len(bullet_questions), 2)
        self.assertLessEqual(len(bullet_questions), 3)

    def test_agent_keeps_existing_follow_up_section_without_duplication(self):
        agent = self._make_agent(llm_client=AnswerWithFollowUpsLLMClient())

        events = list(agent.chat("What is the headcount for Business Units?", self.access_profile))

        final_text = events[-1]["text"]
        self.assertEqual(final_text.count("### Follow-up questions"), 1)
        bullet_questions = [
            line for line in final_text.splitlines()
            if line.strip().startswith("- ") and line.strip().endswith("?")
        ]
        self.assertEqual(len(bullet_questions), 2)

    def test_underspecified_report_request_triggers_clarifying_question_before_generation(self):
        agent = self._make_agent(llm_client=ExplodingLLMClient())

        events = list(agent.chat("Generate an active headcount report for Business Units", self.access_profile))

        self.assertEqual(len(events), 1)
        final_text = events[0]["text"]
        self.assertIn("Before I generate that report", final_text)
        self.assertIn("Which columns should I include", final_text)
        self.assertIn("How should I cut the data", final_text)
        self.assertNotIn("### Follow-up questions", final_text)

    def test_fully_specified_report_request_skips_clarifying_gate(self):
        agent = self._make_agent()

        clarification = agent._clarification_prompt_for_request(
            (
                "Generate an active headcount report for Business Units with "
                "EmployeeNumber, Department, JobRole, JobLevel, and OverTime, cut by department"
            ),
            "report",
            self.access_profile,
        )

        self.assertEqual(clarification, "")

    def test_underspecified_employee_listing_request_also_triggers_clarification(self):
        agent = self._make_agent(llm_client=ExplodingLLMClient())

        events = list(agent.chat("Show employees who attrited in Business Units", self.access_profile))

        final_text = events[0]["text"]
        self.assertIn("Before I build that table", final_text)
        self.assertIn("Which columns should I include", final_text)
        self.assertIn("How should I cut the data", final_text)

    def test_short_answer_to_report_clarification_inherits_original_request(self):
        agent = self._make_agent()
        agent.conversation_history = [
            {"role": "user", "content": "Generate an active headcount report for Business Units"},
            {
                "role": "assistant",
                "content": (
                    "Before I generate that report, please confirm these details:\n"
                    "- Which columns should I include?\n"
                    "- How should I cut the data?"
                ),
            },
        ]

        access_check_message, _ = agent._build_access_check_message(
            "default columns",
            table_context=None,
            access_profile=self.access_profile,
        )

        self.assertIn("follow-up to prior hr question", access_check_message.lower())
        self.assertIn("active headcount report", access_check_message.lower())

    def test_visual_request_recovers_with_chart_when_rate_limit_hits_after_table(self):
        agent = self._make_agent(llm_client=ToolThenRateLimitLLMClient())
        original_execute = agent.executor.execute

        table_rows = [
            {"Department": "Sales", "AvgSatisfaction": 2.75, "AttritionRate": 20.6, "Headcount": 446},
            {"Department": "Human Resources", "AvgSatisfaction": 2.60, "AttritionRate": 19.0, "Headcount": 63},
            {"Department": "Research & Development", "AvgSatisfaction": 2.73, "AttritionRate": 13.8, "Headcount": 961},
        ]

        def execute_with_query_stub(tool_name, tool_input, access_profile=None, table_context=None):
            if tool_name == "query_hr_database":
                return json.dumps(table_rows)
            return original_execute(tool_name, tool_input, access_profile=access_profile, table_context=table_context)

        agent.executor.execute = execute_with_query_stub

        events = list(
            agent.chat(
                "Build me a chart of department and avg satisfaction score against attrition rate.",
                self.access_profile,
            )
        )

        event_types = [event["type"] for event in events]
        self.assertIn("tool_result", event_types)
        self.assertIn("visual_options", event_types)
        self.assertIn("chart", event_types)
        self.assertEqual(event_types[-1], "final_text")
        self.assertNotIn("error", event_types)
        self.assertIn("temporarily rate-limited", events[-1]["text"])
        self.assertIn("### Follow-up questions", events[-1]["text"])


if __name__ == "__main__":
    unittest.main()
