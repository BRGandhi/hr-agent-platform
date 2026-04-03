"""
Provider-agnostic Think -> Act -> Observe loop with scope, access, and context enforcement.
"""

from __future__ import annotations

import json
import logging
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

    def _is_contextual_follow_up(self, user_message: str) -> bool:
        if not self._latest_user_context_anchor():
            return False

        normalized = self._normalized_message(user_message)
        if not normalized:
            return False

        words = normalized.split()
        if len(words) > 8:
            return False

        if normalized in GENERIC_FOLLOW_UP_REPLIES:
            return True
        if any(phrase in normalized for phrase in CONTEXTUAL_REPLY_PHRASES):
            return True
        if any(word in FOLLOW_UP_REFERENCE_WORDS for word in words):
            return True

        mentions_hr_scope = any(keyword in normalized for keyword in HR_SCOPE_KEYWORDS)
        return not mentions_hr_scope

    def _build_contextual_message(self, user_message: str) -> str:
        prior_user_message = self._latest_user_context_anchor()
        if not prior_user_message:
            return user_message
        return f"{user_message} Follow-up to prior HR question: {prior_user_message}."

    def _build_access_check_message(self, user_message: str, table_context: dict | None) -> str:
        message_for_checks = user_message
        if self._is_contextual_follow_up(user_message):
            message_for_checks = self._build_contextual_message(message_for_checks)

        if not self._is_visualization_follow_up(user_message, table_context):
            return message_for_checks

        rows = table_context.get("rows") or []
        columns = list(rows[0].keys()) if rows else []
        title = str(table_context.get("title", "Latest Table") or "Latest Table")
        context_summary = f" HR table context: {title}. Columns: {', '.join(columns[:12])}."
        return f"{message_for_checks}{context_summary}"

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
        )
        helpful_memory = self._dedupe_memories(helpful_memory)

        related_memory: list[dict] = []
        if route in {"history_lookup", "report", "visual_follow_up"}:
            related_memory = self.context_store.search_memories(
                access_profile.email,
                user_message,
                limit=MAX_RELATED_MEMORY,
                exclude_memory_ids=recent_memory_ids,
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
        access_check_message = self._build_access_check_message(user_message, active_table_context)
        allowed, reason = access_profile.can_access_question(access_check_message)
        if not allowed:
            yield {"type": "final_text", "text": reason}
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
                yield {"type": "error", "message": str(exc)}
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

            final_text = response.text.strip() or "(The model returned no final text.)"
            memory_id = self.context_store.remember(access_profile.email, user_message, final_text)
            yield {"type": "final_text", "text": final_text, "memory_id": memory_id, "feedback_score": 0}
            return

        # Max iterations reached — return best-effort answer if available
        if last_text:
            memory_id = self.context_store.remember(access_profile.email, user_message, last_text)
            yield {"type": "final_text", "text": last_text, "memory_id": memory_id, "feedback_score": 0}
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
