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


class AccessCapabilityLLMClient:
    def create_response(self, system_prompt: str, tools: list[dict], messages: list[dict]) -> LLMResponse:
        return LLMResponse(
            text=(
                "You currently have access to headcount and attrition data for the Technology business area. "
                "You can ask for HR questions about headcount, attrition, approved standard reports, and supported visuals."
            ),
            tool_calls=[],
            stop_reason="end_turn",
        )


class CalculationExplanationLLMClient:
    def create_response(self, system_prompt: str, tools: list[dict], messages: list[dict]) -> LLMResponse:
        return LLMResponse(
            text=(
                "The metric is a snapshot calculation.\n\n"
                "- Definition: recently promoted means `YearsSinceLastPromotion < 1`.\n"
                "- Columns used: `Department` and `YearsSinceLastPromotion`.\n"
                "- Formula: promotion rate = recently promoted employees / total headcount in the same department * 100."
            ),
            tool_calls=[],
            stop_reason="end_turn",
        )


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
        self.restricted_profile = AccessProfile(
            email="tech-manager@hr-intelligence.local",
            role="Technology Manager",
            scope_name="Technology",
            allowed_departments=["Research & Development"],
            allowed_metrics=["headcount", "attrition"],
            allowed_doc_tags=["hr", "access", "policy"],
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

    def test_access_envelope_question_is_allowed_even_without_metric_keyword_overlap(self):
        allowed, reason = self.restricted_profile.can_access_question("Tell me about the data that I can access")

        self.assertTrue(allowed, reason)

    def test_access_question_about_restricted_metric_is_still_in_scope(self):
        allowed, reason = self.restricted_profile.can_access_question("Do I have access to compensation data in this platform?")

        self.assertTrue(allowed, reason)

    def test_gender_attrition_question_is_recognized_as_hr(self):
        requested_metrics = self.access_profile.requested_metrics_for_question("Are women attriting more than men?")
        allowed, reason = self.access_profile.can_access_question("Are women attriting more than men?")

        self.assertIn("attrition", requested_metrics)
        self.assertIn("demographics", requested_metrics)
        self.assertTrue(allowed, reason)

    def test_capability_question_routes_to_policy_context(self):
        agent = self._make_agent()

        route = agent._route_request("What metrics can I request in this platform?", None, self.restricted_profile)
        _, _, _, context_documents, prefetched_route = agent._prefetch_context(
            "What metrics can I request in this platform?",
            self.restricted_profile,
            None,
        )

        self.assertEqual(route, "policy")
        self.assertEqual(prefetched_route, "policy")
        self.assertTrue(any(doc["title"] == "Supported HR Insights Questions" for doc in context_documents))

    def test_agent_answers_capability_question_without_out_of_scope_refusal(self):
        agent = self._make_agent(llm_client=AccessCapabilityLLMClient())

        events = list(agent.chat("What metrics can I request in this platform?", self.restricted_profile))

        final_text = events[-1]["text"]
        self.assertIn("headcount and attrition", final_text.lower())
        self.assertIn("### Follow-up questions", final_text)
        self.assertNotIn("This platform only supports HR insights", final_text)
        self.assertNotIn("Out of scope for your role", final_text)

    def test_comparative_attrition_follow_up_uses_prior_hr_context(self):
        agent = self._make_agent()
        agent.conversation_history = [
            {"role": "user", "content": "Show attrition by department for Business Units"},
            {"role": "assistant", "content": "Sales has the highest attrition rate, followed by Human Resources."},
        ]

        access_check_message, _ = agent._build_access_check_message(
            "Which groups have high attrition?",
            table_context=None,
            access_profile=self.access_profile,
        )

        self.assertIn("follow-up to prior hr question", access_check_message.lower())
        self.assertIn("attrition by department", access_check_message.lower())
        allowed, reason = self.access_profile.can_access_question(access_check_message)
        self.assertTrue(allowed, reason)

    def test_ambiguous_comparative_prompt_gets_clarification_before_guardrail(self):
        agent = self._make_agent(llm_client=ExplodingLLMClient())

        events = list(agent.chat("Are women doing worse than men?", self.access_profile))

        self.assertEqual(len(events), 1)
        final_text = events[0]["text"]
        self.assertIn("Which HR measure do you want me to compare", final_text)
        self.assertIn("headcount, attrition, tenure, satisfaction", final_text)
        self.assertNotIn("This platform only supports HR insights", final_text)

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

    def test_simple_trend_chart_request_routes_to_visualization(self):
        agent = self._make_agent()

        route = agent._route_request("show me a mom trend of attrition", None, self.access_profile)

        self.assertEqual(route, "visualization")

    def test_promo_trend_shorthand_with_three_year_and_lab_tech_is_parsed_correctly(self):
        agent = self._make_agent()

        spec = agent._direct_trend_visual_spec(
            "show this 3 year promo trend for only lab tech",
            self.access_profile,
        )

        self.assertIsNotNone(spec)
        self.assertEqual(spec["report_type"], "promotion_trend")
        self.assertEqual(spec["period_months"], 36)
        self.assertEqual(spec["job_role_filter"], "Laboratory Technician")
        self.assertEqual(spec["y_column"], "MonthlyPromotionRatePct")
        self.assertIn("Promotion Trend", spec["title"])
        self.assertIn("Laboratory Technician", spec["title"])

    def test_simple_trend_chart_request_skips_report_workflow_and_returns_chart(self):
        agent = self._make_agent(llm_client=ExplodingLLMClient())

        def execute_stub(tool_name, tool_input, access_profile=None, table_context=None):
            if tool_name == "generate_standard_report":
                return json.dumps(
                    {
                        "report_name": "Attrition Trend Report | Last 12 Months",
                        "report_type": "attrition_trend",
                        "report_period_months": 12,
                        "results": [
                            {"SnapshotMonth": "2025-04-01", "MonthlyAttritionRatePct": 1.1, "Rolling12AttritionRatePct": 14.8},
                            {"SnapshotMonth": "2025-05-01", "MonthlyAttritionRatePct": 1.3, "Rolling12AttritionRatePct": 15.1},
                            {"SnapshotMonth": "2025-06-01", "MonthlyAttritionRatePct": 1.0, "Rolling12AttritionRatePct": 15.0},
                        ],
                    }
                )
            if tool_name == "create_visualization":
                return json.dumps(
                    {
                        "chart_json": "{\"data\": [], \"layout\": {}}",
                        "title": "Attrition Trend | Business Units | Last 12 Months",
                        "chart_type": "line",
                        "x_column": "SnapshotMonth",
                        "y_column": "MonthlyAttritionRatePct",
                        "business_question": "How is attrition moving month over month?",
                        "best_for": "Trend direction and inflection points over time.",
                        "watch_out": "Only use when the x-axis has a real order.",
                    }
                )
            raise AssertionError(f"Unexpected tool call: {tool_name}")

        agent.executor.execute = execute_stub

        events = list(agent.chat("show me a mom trend of attrition", self.access_profile))

        event_types = [event["type"] for event in events]
        self.assertEqual(event_types, ["chart", "final_text"])
        self.assertIn("monthly attrition rate trend", events[-1]["text"].lower())
        self.assertNotIn("Before I build that table", events[-1]["text"])
        self.assertIn("### Follow-up questions", events[-1]["text"])

    def test_filtered_promo_trend_request_uses_filtered_rows_and_returns_chart(self):
        agent = self._make_agent(llm_client=ExplodingLLMClient())
        agent._build_filtered_trend_rows = lambda spec, access_profile: [
            {"SnapshotMonth": "2023-04-01", "MonthlyPromotionRatePct": 0.9},
            {"SnapshotMonth": "2023-05-01", "MonthlyPromotionRatePct": 1.1},
            {"SnapshotMonth": "2023-06-01", "MonthlyPromotionRatePct": 1.4},
        ]

        def execute_stub(tool_name, tool_input, access_profile=None, table_context=None):
            if tool_name == "create_visualization":
                return json.dumps(
                    {
                        "chart_json": "{\"data\": [], \"layout\": {}}",
                        "title": tool_input["title"],
                        "chart_type": "line",
                        "x_column": "SnapshotMonth",
                        "y_column": tool_input["y_column"],
                        "business_question": "How is monthly promotion rate changing over snapshot month?",
                        "best_for": "Trend direction and inflection points over time.",
                        "watch_out": "Only use when the x-axis has a real order.",
                    }
                )
            raise AssertionError(f"Unexpected tool call: {tool_name}")

        agent.executor.execute = execute_stub

        events = list(agent.chat("show this 3 year promo trend for only lab tech", self.access_profile))

        event_types = [event["type"] for event in events]
        self.assertEqual(event_types, ["chart", "final_text"])
        self.assertIn("filtered to Laboratory Technician", events[-1]["text"])
        self.assertIn("36 months", events[-1]["text"])
        self.assertNotIn("Before I build that table", events[-1]["text"])

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

    def test_metric_explanation_follow_up_uses_prior_hr_question_context(self):
        agent = self._make_agent()
        agent.conversation_history = [
            {"role": "user", "content": "How many employees in Business Units were promoted in the last year?"},
            {"role": "assistant", "content": "Total recently promoted: 581."},
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "Promotion rate by department ranges from 38.1% to 39.9%."},
        ]

        access_check_message, follow_up_context = agent._build_access_check_message(
            "give me the details of the calculation, which columns you used and the formula",
            table_context=None,
            access_profile=self.access_profile,
        )

        self.assertIn("follow-up to prior hr question", access_check_message.lower())
        self.assertIn("promoted in the last year", access_check_message.lower())
        self.assertEqual(follow_up_context.get("question"), "How many employees in Business Units were promoted in the last year?")

    def test_metric_explanation_follow_up_skips_report_clarification(self):
        agent = self._make_agent(llm_client=CalculationExplanationLLMClient())
        agent.conversation_history = [
            {"role": "user", "content": "How many employees in Business Units were promoted in the last year?"},
            {"role": "assistant", "content": "Total recently promoted: 581."},
        ]

        events = list(agent.chat("show me how you calculated this metric", self.access_profile))

        final_text = events[-1]["text"]
        self.assertIn("YearsSinceLastPromotion < 1", final_text)
        self.assertIn("Columns used", final_text)
        self.assertNotIn("Before I build that table", final_text)
        self.assertNotIn("This platform only supports HR insights", final_text)

    def test_metric_explanation_without_context_asks_for_clarification(self):
        agent = self._make_agent(llm_client=ExplodingLLMClient())

        events = list(agent.chat("give me the details of the calculation, which columns you used and the formula", self.access_profile))

        self.assertEqual(len(events), 1)
        final_text = events[0]["text"]
        self.assertIn("Which HR metric or prior result do you want me to explain?", final_text)
        self.assertIn("definition, columns used, formula", final_text)
        self.assertNotIn("This platform only supports HR insights", final_text)

    def test_thin_follow_up_memory_uses_prior_question_as_saved_title(self):
        agent = self._make_agent(llm_client=DirectAnswerLLMClient())
        agent.conversation_history = [
            {"role": "user", "content": "Which teams in Business Units have the highest attrition risk?"},
            {"role": "assistant", "content": "I can answer question 1 or question 2 next if you'd like."},
        ]

        events = list(agent.chat("answer question 1", self.access_profile))

        self.assertEqual(events[-1]["type"], "final_text")
        recent_memory = self.store.recent_memory(self.access_profile.email, limit=1)
        self.assertEqual(len(recent_memory), 1)
        self.assertEqual(recent_memory[0]["question"], "Which teams in Business Units have the highest attrition risk?")

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
