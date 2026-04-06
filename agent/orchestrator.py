"""
Provider-agnostic Think -> Act -> Observe loop with scope, access, and context enforcement.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Generator

from agent.llm_client import LLMClientError, LLMConfig, create_llm_client
from agent.prompts import build_system_prompt
from agent.tool_executor import ToolExecutor
from agent.tools import TOOLS
from config import MAX_AGENT_ITERATIONS, MAX_CONVERSATION_HISTORY
from database.access_control import AccessProfile, HR_SCOPE_KEYWORDS
from database.connector import HRDatabase
from database.context_store import ContextStore

logger = logging.getLogger("hr_platform.agent")

# Display constants
MAX_TABLE_ROWS = 50
MAX_RESULT_CHARS = 2000
MAX_RECENT_MEMORY = 2
MAX_RELATED_MEMORY = 3
MAX_HELPFUL_MEMORY = 2
MAX_CONTEXT_DOCUMENTS = 2
VISUAL_FOLLOW_UP_KEYWORDS = ("visual", "visualize", "visualization", "chart", "graph", "plot", "dashboard")
PRIOR_RESULT_REFERENCES = ("this", "that", "it", "above", "previous", "latest", "table", "result")
HISTORY_LOOKUP_KEYWORDS = ("before", "earlier", "again", "last time", "previous", "prior", "past chat", "dive back")
DOCUMENT_LOOKUP_KEYWORDS = ("policy", "policies", "access", "rule", "rules", "definition", "schema", "tag", "document")
REPORT_OUTPUT_NOUNS = (
    "report",
    "roster",
    "table",
    "spreadsheet",
    "employee-level",
    "employee level",
    "name-by-name",
    "name by name",
    "employee list",
    "listing",
)
REPORT_OUTPUT_VERBS = ("generate", "create", "build", "produce", "show", "list", "give", "provide", "open", "export", "download", "need", "want", "send")
REPORT_COLUMN_TERMS = (
    "column",
    "columns",
    "field",
    "fields",
    "employeenumber",
    "employee number",
    "employee label",
    "department",
    "job role",
    "jobrole",
    "job level",
    "joblevel",
    "overtime",
    "business travel",
    "businesstravel",
    "attrition",
    "gender",
    "age",
    "marital status",
    "maritalstatus",
    "monthly income",
    "monthlyincome",
    "performance rating",
    "performancerating",
    "job satisfaction",
    "jobsatisfaction",
    "environment satisfaction",
    "environmentsatisfaction",
    "years at company",
    "yearsatcompany",
)
REPORT_CUT_PHRASES = (
    "by department",
    "by job role",
    "by joblevel",
    "by job level",
    "by overtime",
    "by gender",
    "by age",
    "by marital status",
    "by business travel",
    "by education field",
    "employee-level",
    "employee level",
    "name-by-name",
    "name by name",
    "break down",
    "breakdown",
    "split by",
    "group by",
    "grouped by",
    "cut by",
    "slice by",
    "segment by",
)
GENERIC_FOLLOW_UP_REPLIES = {
    "yes",
    "yes please",
    "yeah",
    "yep",
    "sure",
    "sure thing",
    "ok",
    "okay",
    "please",
    "go ahead",
    "do it",
    "sounds good",
    "no",
    "no thanks",
    "not now",
}
CONTEXTUAL_REPLY_PHRASES = (
    "show me",
    "show that",
    "show it",
    "show those",
    "break it down",
    "drill down",
    "go deeper",
    "dig deeper",
    "more detail",
    "more details",
    "visualize it",
    "chart it",
    "plot it",
    "turn it into",
    "same for",
    "that one",
    "those ones",
)
FOLLOW_UP_REFERENCE_WORDS = {"this", "that", "it", "those", "them", "same"}
FOLLOW_UP_SECTION_MARKERS = (
    "follow-up questions",
    "follow up questions",
    "next questions",
    "questions to ask next",
    "you could also ask",
)
FINAL_RESPONSE_REFUSAL_MARKERS = (
    "this platform only supports hr insights",
    "out of scope for your role",
    "no access profile provisioned",
    "agent reached max iterations",
    "the model returned no final text",
)
CLARIFICATION_RESPONSE_MARKERS = (
    "before i generate that report",
    "before i build that table",
    "which hr report or measure do you want",
    "which columns should i include",
    "how should i cut the data",
)
RATE_LIMIT_MESSAGE_MARKERS = (
    "rate limit",
    "too many requests",
    "try again shortly",
)
FOLLOW_UP_METRIC_ORDER = (
    "headcount",
    "attrition",
    "compensation",
    "performance",
    "satisfaction",
    "tenure",
    "demographics",
    "policy",
)


class HRAgent:
    def __init__(self, llm_config: LLMConfig, db: HRDatabase, context_store: ContextStore):
        self.llm_config = llm_config.normalized()
        self.client = create_llm_client(self.llm_config)
        self.executor = ToolExecutor(db, context_store=context_store)
        self.context_store = context_store
        self.conversation_history: list[dict] = []
        self.last_table_context: dict | None = None

    def reset(self):
        self.conversation_history = []
        self.last_table_context = None

    def update_llm_config(self, llm_config: LLMConfig):
        normalized = llm_config.normalized()
        if normalized != self.llm_config:
            self.llm_config = normalized
            self.client = create_llm_client(normalized)

    def prime_recalled_memory(self, question: str, response: str):
        question_text = str(question or "").strip()
        response_text = str(response or "").strip()
        if not question_text or not response_text:
            return

        if len(self.conversation_history) >= 2:
            prior_user = self.conversation_history[-2]
            prior_assistant = self.conversation_history[-1]
            if (
                prior_user.get("role") == "user"
                and prior_assistant.get("role") == "assistant"
                and self._normalized_message(str(prior_user.get("content") or "")) == self._normalized_message(question_text)
                and self._normalized_message(str(prior_assistant.get("content") or "")) == self._normalized_message(response_text)
            ):
                return

        self.conversation_history.append({"role": "user", "content": question_text})
        self.conversation_history.append({"role": "assistant", "content": response_text})
        self._trim_history()

    def _trim_history(self):
        """Keep conversation history within bounds to control token usage."""
        if len(self.conversation_history) > MAX_CONVERSATION_HISTORY:
            self.conversation_history = self.conversation_history[-MAX_CONVERSATION_HISTORY:]

    def _normalized_message(self, text: str) -> str:
        return " ".join((text or "").strip().lower().split())

    def _latest_message_content(self, role: str) -> str:
        for item in reversed(self.conversation_history):
            if item.get("role") != role:
                continue
            content = str(item.get("content") or "").strip()
            if content:
                return content
        return ""

    def _latest_assistant_requested_clarification(self) -> bool:
        latest_assistant = self._latest_message_content("assistant").lower()
        return any(marker in latest_assistant for marker in CLARIFICATION_RESPONSE_MARKERS)

    def _latest_user_context_anchor(self) -> str:
        fallback = ""
        for item in reversed(self.conversation_history):
            if item.get("role") != "user":
                continue
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            if not fallback:
                fallback = content

            normalized = self._normalized_message(content)
            if any(keyword in normalized for keyword in HR_SCOPE_KEYWORDS):
                return content
            if len(normalized.split()) > 4 or "?" in content:
                return content
        return fallback

    def _recent_memory_context_anchor(self, access_profile: AccessProfile | None) -> dict[str, str]:
        if access_profile is None:
            return {}

        recent_items = self.context_store.recent_memory(access_profile.email, limit=3)
        fallback_question = ""
        fallback_response = ""

        for item in recent_items:
            question = str(item.get("question") or "").strip()
            response = str(item.get("response") or "").strip()
            if not question:
                continue
            if not fallback_question:
                fallback_question = question
                fallback_response = response

            normalized = self._normalized_message(question)
            if any(keyword in normalized for keyword in HR_SCOPE_KEYWORDS):
                return {"question": question, "response": response}
            if len(normalized.split()) > 4 or "?" in question:
                return {"question": question, "response": response}

        if fallback_question:
            return {"question": fallback_question, "response": fallback_response}
        return {}

    def _resolve_follow_up_context(self, access_profile: AccessProfile | None = None) -> dict[str, str]:
        history_question = self._latest_user_context_anchor()
        history_response = self._latest_message_content("assistant")
        if history_question:
            return {"question": history_question, "response": history_response}
        return self._recent_memory_context_anchor(access_profile)

    def _dedupe_memories(self, memories: list[dict]) -> list[dict]:
        deduped: list[dict] = []
        seen_ids: set[int] = set()
        for item in memories:
            memory_id = int(item.get("memory_id") or 0)
            if memory_id and memory_id in seen_ids:
                continue
            if memory_id:
                seen_ids.add(memory_id)
            deduped.append(item)
        return deduped

    def _is_visualization_follow_up(self, user_message: str, table_context: dict | None) -> bool:
        if not table_context or not table_context.get("rows"):
            return False

        lowered = self._normalized_message(user_message)
        asks_for_visual = any(keyword in lowered for keyword in VISUAL_FOLLOW_UP_KEYWORDS)
        references_prior_result = (
            any(keyword in lowered for keyword in PRIOR_RESULT_REFERENCES)
            or ("turn" in lowered and "into" in lowered)
            or ("convert" in lowered)
            or ("show me options" in lowered)
        )
        return asks_for_visual and references_prior_result

    def _is_contextual_follow_up(self, user_message: str, access_profile: AccessProfile | None = None) -> bool:
        if not self._resolve_follow_up_context(access_profile):
            return False

        normalized = self._normalized_message(user_message)
        if not normalized:
            return False

        words = normalized.split()
        if len(words) > 8:
            return False

        if self._latest_assistant_requested_clarification() and not str(user_message or "").strip().endswith("?"):
            return True

        if normalized in GENERIC_FOLLOW_UP_REPLIES:
            return True
        if any(phrase in normalized for phrase in CONTEXTUAL_REPLY_PHRASES):
            return True
        if any(word in FOLLOW_UP_REFERENCE_WORDS for word in words):
            return True

        mentions_hr_scope = any(keyword in normalized for keyword in HR_SCOPE_KEYWORDS)
        return not mentions_hr_scope

    def _build_contextual_message(
        self,
        user_message: str,
        access_profile: AccessProfile | None = None,
    ) -> tuple[str, dict[str, str]]:
        follow_up_context = self._resolve_follow_up_context(access_profile)
        prior_user_message = str(follow_up_context.get("question") or "").strip()
        if not prior_user_message:
            return user_message, {}

        prior_response = str(follow_up_context.get("response") or "").strip()
        contextual_message = f"{user_message} Follow-up to prior HR question: {prior_user_message}."
        if prior_response:
            contextual_message += f" Prior assistant context: {prior_response[:260]}."
        return contextual_message, follow_up_context

    def _build_access_check_message(
        self,
        user_message: str,
        table_context: dict | None,
        access_profile: AccessProfile | None = None,
    ) -> tuple[str, dict[str, str]]:
        message_for_checks = user_message
        follow_up_context: dict[str, str] = {}
        if self._is_contextual_follow_up(user_message, access_profile):
            message_for_checks, follow_up_context = self._build_contextual_message(message_for_checks, access_profile)

        if not self._is_visualization_follow_up(user_message, table_context):
            return message_for_checks, follow_up_context

        rows = table_context.get("rows") or []
        columns = list(rows[0].keys()) if rows else []
        title = str(table_context.get("title", "Latest Table") or "Latest Table")
        context_summary = f" HR table context: {title}. Columns: {', '.join(columns[:12])}."
        return f"{message_for_checks}{context_summary}", follow_up_context

    def _route_request(self, user_message: str, table_context: dict | None) -> str:
        lowered = user_message.lower()
        if self._is_visualization_follow_up(user_message, table_context):
            return "visual_follow_up"
        if any(keyword in lowered for keyword in HISTORY_LOOKUP_KEYWORDS):
            return "history_lookup"
        if any(keyword in lowered for keyword in DOCUMENT_LOOKUP_KEYWORDS):
            return "policy"
        if "report" in lowered or "roster" in lowered:
            return "report"
        return "data_query"

    def _looks_like_output_request(self, user_message: str, route: str) -> bool:
        lowered = self._normalized_message(user_message)
        has_output_noun = any(noun in lowered for noun in REPORT_OUTPUT_NOUNS)
        has_output_verb = any(re.search(rf"\b{re.escape(verb)}\b", lowered) for verb in REPORT_OUTPUT_VERBS)
        employee_listing_request = bool(re.search(r"\b(show|list|export|download|give|provide)\b.*\bemployees?\b", lowered))
        analytic_question = bool(re.match(r"^(which|what|how|why|where|who)\b", lowered)) and str(user_message or "").strip().endswith("?")

        if analytic_question and not has_output_verb and not employee_listing_request:
            return False
        if employee_listing_request:
            return True
        if route == "report" and has_output_noun and not analytic_question:
            return True
        return has_output_noun and has_output_verb

    def _report_request_has_columns(self, user_message: str) -> bool:
        lowered = self._normalized_message(user_message)
        if re.search(r"\b(columns?|fields?)\b", lowered):
            return True
        explicit_fields = sum(1 for term in REPORT_COLUMN_TERMS if term in lowered)
        return explicit_fields >= 2

    def _report_request_has_cut(self, user_message: str) -> bool:
        lowered = self._normalized_message(user_message)
        return any(phrase in lowered for phrase in REPORT_CUT_PHRASES)

    def _report_request_has_subject(self, user_message: str, access_profile: AccessProfile) -> bool:
        lowered = self._normalized_message(user_message)
        requested_metrics = access_profile.requested_metrics_for_question(user_message)
        if requested_metrics:
            return True
        return any(term in lowered for term in ("headcount", "attrition", "turnover", "employees", "workforce", "promotion", "tenure"))

    def _clarification_prompt_for_request(
        self,
        user_message: str,
        route: str,
        access_profile: AccessProfile,
    ) -> str:
        if not self._looks_like_output_request(user_message, route):
            return ""

        has_subject = self._report_request_has_subject(user_message, access_profile)
        has_columns = self._report_request_has_columns(user_message)
        has_cut = self._report_request_has_cut(user_message)

        if has_subject and has_columns and has_cut:
            return ""

        opener = "Before I generate that report, please confirm these details:"
        if route != "report":
            opener = "Before I build that table, please confirm these details:"

        prompts = []
        if not has_subject:
            prompts.append("- Which HR report or measure do you want? For example: active headcount, attrition, or an employee roster.")
        if not has_columns:
            prompts.append("- Which columns should I include? For example: EmployeeNumber, Department, JobRole, JobLevel, and OverTime.")
        if not has_cut:
            prompts.append("- How should I cut the data? For example: employee-level, by department, by job role, or by job level.")

        return f"{opener}\n" + "\n".join(prompts)

    def _prefetch_context(
        self,
        user_message: str,
        access_profile: AccessProfile,
        table_context: dict | None,
    ) -> tuple[list[dict], list[dict], list[dict], list[dict], str]:
        route = self._route_request(user_message, table_context)
        recent_memory = self.context_store.recent_memory(access_profile.email, limit=MAX_RECENT_MEMORY)
        recent_memory_ids = {
            int(item["memory_id"])
            for item in recent_memory
            if item.get("memory_id")
        }

        helpful_memory = self.context_store.search_memories(
            access_profile.email,
            user_message,
            limit=MAX_HELPFUL_MEMORY,
            min_feedback=1,
            exclude_memory_ids=recent_memory_ids,
            require_strong_match=True,
        )
        helpful_memory = self._dedupe_memories(helpful_memory)

        related_memory: list[dict] = []
        if route in {"history_lookup", "report", "visual_follow_up"}:
            related_memory = self.context_store.search_memories(
                access_profile.email,
                user_message,
                limit=MAX_RELATED_MEMORY,
                exclude_memory_ids=recent_memory_ids,
                require_strong_match=True,
            )
            related_memory = self._dedupe_memories(
                related_memory + [item for item in helpful_memory if item.get("memory_id") not in recent_memory_ids]
            )[:MAX_RELATED_MEMORY]

        context_documents: list[dict] = []
        if route == "policy":
            context_documents = self.context_store.search_documents(
                user_message,
                access_profile.allowed_doc_tags,
                limit=MAX_CONTEXT_DOCUMENTS,
            )

        return recent_memory, related_memory, helpful_memory, context_documents, route

    def chat(
        self,
        user_message: str,
        access_profile: AccessProfile,
        table_context: dict | None = None,
    ) -> Generator[dict, None, None]:
        if table_context and table_context.get("rows"):
            self.last_table_context = {
                "title": table_context.get("title", "Latest Table"),
                "rows": table_context["rows"],
            }

        active_table_context = self.last_table_context
        access_check_message, follow_up_context = self._build_access_check_message(
            user_message,
            active_table_context,
            access_profile,
        )
        allowed, reason = access_profile.can_access_question(access_check_message)
        if not allowed:
            yield {"type": "final_text", "text": reason}
            return

        route = self._route_request(access_check_message, active_table_context)
        clarification_text = self._clarification_prompt_for_request(access_check_message, route, access_profile)
        if clarification_text:
            self.conversation_history.append({"role": "user", "content": user_message})
            self._trim_history()
            self.conversation_history.append({"role": "assistant", "content": clarification_text})
            self._trim_history()
            yield {"type": "final_text", "text": clarification_text}
            return

        recent_memory, related_memory, helpful_memory, context_documents, route = self._prefetch_context(
            access_check_message,
            access_profile,
            active_table_context,
        )
        if helpful_memory:
            yield {
                "type": "helpful_memories",
                "items": [
                    {
                        "memory_id": item.get("memory_id"),
                        "question": item.get("question", ""),
                        "response": item.get("response", "")[:260],
                    }
                    for item in helpful_memory
                ],
            }
        system_prompt = build_system_prompt(
            access_profile=access_profile.summary(),
            recent_memory=recent_memory,
            related_memory=related_memory,
            helpful_memory=helpful_memory,
            context_documents=context_documents,
            latest_table_context=active_table_context,
            route=route,
            current_follow_up_context=follow_up_context,
        )

        self.conversation_history.append({"role": "user", "content": user_message})
        self._trim_history()
        iteration = 0
        last_text = ""

        while iteration < MAX_AGENT_ITERATIONS:
            iteration += 1

            try:
                response = self.client.create_response(
                    system_prompt=system_prompt,
                    tools=TOOLS,
                    messages=self.conversation_history,
                )
            except LLMClientError as exc:
                error_message = str(exc)
                if self._is_rate_limit_error(error_message):
                    fallback_events = self._recover_from_rate_limit(
                        user_message,
                        route,
                        access_profile,
                        active_table_context,
                        error_message,
                    )
                    if fallback_events:
                        for event in fallback_events:
                            yield event
                        return
                yield {"type": "error", "message": error_message}
                return

            if response.text:
                last_text = response.text.strip()

            self.conversation_history.append(
                {
                    "role": "assistant",
                    "content": response.text,
                    "tool_calls": [
                        {"id": call.id, "name": call.name, "input": call.input}
                        for call in response.tool_calls
                    ],
                }
            )

            if response.tool_calls:
                for tool_call in response.tool_calls:
                    tool_input = tool_call.input

                    logger.info(
                        "Tool call: %s user=%s",
                        tool_call.name,
                        access_profile.email,
                    )

                    yield {
                        "type": "tool_call",
                        "name": tool_call.name,
                        "explanation": tool_input.get("explanation", ""),
                        "sql": tool_input.get("sql_query", ""),
                        "inputs": tool_input,
                    }

                    result = self.executor.execute(
                        tool_call.name,
                        tool_input,
                        access_profile=access_profile,
                        table_context=active_table_context,
                    )
                    parsed_result = self._safe_parse_json(result)

                    if isinstance(parsed_result, dict) and "chart_json" in parsed_result:
                        yield {
                            "type": "chart",
                            "chart_json": parsed_result["chart_json"],
                            "title": parsed_result.get("title", "Chart"),
                        }

                    if isinstance(parsed_result, dict) and isinstance(parsed_result.get("options"), list):
                        yield {
                            "type": "visual_options",
                            "title": parsed_result.get("title", "Visualization options"),
                            "recommended_option_id": parsed_result.get("recommended_option_id"),
                            "options": parsed_result["options"],
                        }

                    table_data = None
                    full_table_data = None
                    table_title = tool_call.name
                    report_type = None
                    table_total_rows = None
                    if isinstance(parsed_result, list):
                        full_table_data = parsed_result
                        table_data = parsed_result[:MAX_TABLE_ROWS]
                        table_total_rows = len(parsed_result)
                    elif isinstance(parsed_result, dict) and "results" in parsed_result and isinstance(parsed_result["results"], list):
                        full_table_data = parsed_result["results"]
                        table_data = parsed_result["results"][:MAX_TABLE_ROWS]
                        table_title = parsed_result.get("report_name") or parsed_result.get("focus_area") or tool_call.name
                        report_type = parsed_result.get("report_type")
                        table_total_rows = int(parsed_result.get("row_count") or len(parsed_result["results"]))

                    if full_table_data:
                        self.last_table_context = {"title": table_title, "rows": full_table_data}
                        active_table_context = self.last_table_context

                    yield {
                        "type": "tool_result",
                        "name": tool_call.name,
                        "result": result[:MAX_RESULT_CHARS],
                        "table_data": table_data,
                        "title": table_title,
                        "report_type": report_type,
                        "table_total_rows": table_total_rows,
                    }

                    self.conversation_history.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_call.name,
                            "content": result,
                        }
                    )

                continue

            final_text = self._finalize_response_text(
                response.text,
                access_check_message,
                route,
                access_profile,
            )
            self.conversation_history[-1]["content"] = final_text
            memory_id = self.context_store.remember(access_profile.email, user_message, final_text)
            yield {"type": "final_text", "text": final_text, "memory_id": memory_id, "feedback_score": 0}
            return

        # Max iterations reached — return best-effort answer if available
        if last_text:
            final_text = self._finalize_response_text(
                last_text,
                access_check_message,
                route,
                access_profile,
            )
            if self.conversation_history and self.conversation_history[-1].get("role") == "assistant":
                self.conversation_history[-1]["content"] = final_text
            memory_id = self.context_store.remember(access_profile.email, user_message, final_text)
            yield {"type": "final_text", "text": final_text, "memory_id": memory_id, "feedback_score": 0}
        else:
            fallback = f"Agent reached max iterations ({MAX_AGENT_ITERATIONS}). Try a more specific HR question."
            self.context_store.remember(access_profile.email, user_message, fallback)
            yield {"type": "error", "message": fallback}

    def _safe_parse_json(self, value: str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.debug("JSON parse failed for tool result: %s", exc)
            return {"error": f"Failed to parse tool result", "raw": value[:500]}

    def _has_structured_follow_up_questions(self, text: str) -> bool:
        lowered = str(text or "").lower()
        if not any(marker in lowered for marker in FOLLOW_UP_SECTION_MARKERS):
            return False

        bullet_questions = [
            line.strip()
            for line in str(text or "").splitlines()
            if re.match(r"^(?:[-*+]|\d+[.)])\s+.+\?$", line.strip())
        ]
        return len(bullet_questions) >= 2

    def _is_refusal_or_empty_response(self, text: str) -> bool:
        normalized = self._normalized_message(text)
        if not normalized:
            return True
        return any(marker in normalized for marker in FINAL_RESPONSE_REFUSAL_MARKERS)

    def _is_clarification_response(self, text: str) -> bool:
        normalized = self._normalized_message(text)
        return any(marker in normalized for marker in CLARIFICATION_RESPONSE_MARKERS)

    def _is_rate_limit_error(self, text: str) -> bool:
        normalized = self._normalized_message(text)
        return any(marker in normalized for marker in RATE_LIMIT_MESSAGE_MARKERS)

    def _requests_visualization(self, user_message: str, route: str) -> bool:
        if route == "visual_follow_up":
            return True
        normalized = self._normalized_message(user_message)
        return any(keyword in normalized for keyword in VISUAL_FOLLOW_UP_KEYWORDS)

    def _recover_from_rate_limit(
        self,
        user_message: str,
        route: str,
        access_profile: AccessProfile,
        table_context: dict | None,
        error_message: str,
    ) -> list[dict]:
        rows = list((table_context or {}).get("rows") or [])
        title = str((table_context or {}).get("title") or "Latest Table").strip() or "Latest Table"

        if rows and self._requests_visualization(user_message, route):
            raw_options = self.executor.execute(
                "suggest_visualizations",
                {
                    "title": title,
                    "question": user_message,
                    "max_options": 3,
                },
                access_profile=access_profile,
                table_context=table_context,
            )
            parsed_options = self._safe_parse_json(raw_options)
            if isinstance(parsed_options, dict) and isinstance(parsed_options.get("options"), list) and parsed_options["options"]:
                recommended_option_id = parsed_options.get("recommended_option_id")
                recommended_option = next(
                    (
                        option
                        for option in parsed_options["options"]
                        if str(option.get("id") or "") == str(recommended_option_id or "")
                    ),
                    parsed_options["options"][0],
                )
                fallback_text = (
                    "I retrieved the workforce data successfully and generated the strongest chart option directly "
                    "from the latest table while the model provider was temporarily rate-limited. "
                    "The recommended visual is shown above, and you can compare alternatives in Visual options."
                )
                final_text = self._finalize_response_text(fallback_text, user_message, route, access_profile)
                self.conversation_history.append({"role": "assistant", "content": final_text})
                self._trim_history()
                memory_id = self.context_store.remember(access_profile.email, user_message, final_text)

                events = [
                    {
                        "type": "visual_options",
                        "title": parsed_options.get("title", f"Visualization options for {title}"),
                        "recommended_option_id": recommended_option_id or recommended_option.get("id"),
                        "options": parsed_options["options"],
                    }
                ]
                if recommended_option.get("chart_json"):
                    events.append(
                        {
                            "type": "chart",
                            "chart_json": recommended_option["chart_json"],
                            "title": recommended_option.get("title", f"Visualization for {title}"),
                        }
                    )
                events.append({"type": "final_text", "text": final_text, "memory_id": memory_id, "feedback_score": 0})
                return events

        if rows:
            fallback_text = (
                "I retrieved the workforce data successfully, and the table above is ready to use. "
                f"The model provider then hit a temporary rate limit before I could finish the narrative summary ({error_message}). "
                "You can keep working from this result now or retry the written summary in a moment."
            )
            final_text = self._finalize_response_text(fallback_text, user_message, route, access_profile)
            self.conversation_history.append({"role": "assistant", "content": final_text})
            self._trim_history()
            memory_id = self.context_store.remember(access_profile.email, user_message, final_text)
            return [{"type": "final_text", "text": final_text, "memory_id": memory_id, "feedback_score": 0}]

        return []

    def _follow_up_candidates_for_metric(self, metric: str, scope_name: str) -> list[str]:
        scope_suffix = f" in {scope_name}" if scope_name else ""
        banks = {
            "headcount": [
                f"Can you break headcount down by department{scope_suffix}?",
                f"Which employee job roles have the highest headcount{scope_suffix}?",
                f"Can you show the active headcount roster for {scope_name}?" if scope_name else "Can you show the active headcount roster for this workforce?",
            ],
            "attrition": [
                f"Which departments or employee groups are driving the highest attrition{scope_suffix}?",
                f"How does attrition vary by overtime{scope_suffix}?",
                f"Can you show the highest-risk attrition hotspots by department{scope_suffix}?",
            ],
            "compensation": [
                f"How does employee compensation vary by department{scope_suffix}?",
                f"Which employee groups sit above or below the average income range{scope_suffix}?",
                f"Is attrition higher in lower-paid employee groups{scope_suffix}?",
            ],
            "performance": [
                f"How do employee performance ratings vary by department{scope_suffix}?",
                f"Which employee groups have the highest performance ratings{scope_suffix}?",
                f"Is attrition higher among lower-rated employee groups{scope_suffix}?",
            ],
            "satisfaction": [
                f"Which departments have the lowest employee satisfaction{scope_suffix}?",
                f"How does employee satisfaction differ by job level{scope_suffix}?",
                f"Is lower employee satisfaction linked to higher attrition{scope_suffix}?",
            ],
            "tenure": [
                f"How does employee tenure vary by department{scope_suffix}?",
                "Which employee groups have the longest average time to promotion?",
                f"Is attrition concentrated among lower-tenure employees{scope_suffix}?",
            ],
            "demographics": [
                "How does the workforce result break down by gender or age band?",
                f"Which demographic employee groups are most represented{scope_suffix}?",
                f"Does attrition vary across demographic groups{scope_suffix}?",
            ],
            "policy": [
                f"Which HR access policy applies to my role for {scope_name}?" if scope_name else "Which HR access policy applies to my role?",
                "Which HR measures are approved for my role?",
                "How are HR department filters enforced in this workspace?",
            ],
        }
        return banks.get(metric, [])

    def _build_follow_up_questions(
        self,
        source_message: str,
        route: str,
        access_profile: AccessProfile,
    ) -> list[str]:
        requested_metric_set = access_profile.requested_metrics_for_question(source_message)
        requested_metrics = [metric for metric in FOLLOW_UP_METRIC_ORDER if metric in requested_metric_set]
        scope_name = str(access_profile.scope_name or "").strip()
        candidates: list[str] = []
        seen: set[str] = set()

        def add_candidate(question: str):
            cleaned = " ".join(str(question or "").split()).strip()
            if not cleaned:
                return
            if not cleaned.endswith("?"):
                cleaned = f"{cleaned}?"
            key = cleaned.lower()
            if key in seen:
                return
            allowed, _ = access_profile.can_access_question(cleaned)
            if not allowed:
                return
            seen.add(key)
            candidates.append(cleaned)

        if route == "policy" and "policy" not in requested_metrics:
            requested_metrics.append("policy")
        if not requested_metrics and route != "policy":
            requested_metrics.append("headcount")

        if route == "visual_follow_up":
            add_candidate("Can you show the HR table behind this visual?")
            add_candidate("Which departments or employee groups stand out most in this visual?")

        if route == "report":
            add_candidate("Can you generate the employee-level roster behind this result?")
            add_candidate("Can you break this report down by department or job level?")

        for metric in requested_metrics:
            for question in self._follow_up_candidates_for_metric(metric, scope_name):
                add_candidate(question)

        generic_questions = [
            "Can you break this workforce answer down by department?",
            f"Which employee groups stand out most in {scope_name}?" if scope_name else "Which employee groups stand out most in this workforce?",
            "Can you show the employee-level roster behind this HR answer?",
        ]
        for question in generic_questions:
            add_candidate(question)

        return candidates[:3]

    def _finalize_response_text(
        self,
        raw_text: str,
        source_message: str,
        route: str,
        access_profile: AccessProfile,
    ) -> str:
        text = str(raw_text or "").strip() or "(The model returned no final text.)"
        if self._is_refusal_or_empty_response(text):
            return text
        if self._is_clarification_response(text):
            return text
        if self._has_structured_follow_up_questions(text):
            return text

        follow_up_questions = self._build_follow_up_questions(source_message, route, access_profile)
        if len(follow_up_questions) < 2:
            return text

        follow_up_block = "\n".join(f"- {question}" for question in follow_up_questions[:3])
        return f"{text}\n\n### Follow-up questions\n{follow_up_block}"
