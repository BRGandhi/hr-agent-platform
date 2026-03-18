"""
Provider-agnostic Think -> Act -> Observe loop with scope, access, and context enforcement.
"""

from __future__ import annotations

import json
from typing import Generator

from agent.llm_client import LLMClientError, LLMConfig, create_llm_client
from agent.prompts import build_system_prompt
from agent.tool_executor import ToolExecutor
from agent.tools import TOOLS
from config import MAX_AGENT_ITERATIONS
from database.access_control import AccessProfile
from database.connector import HRDatabase
from database.context_store import ContextStore


class HRAgent:
    def __init__(self, llm_config: LLMConfig, db: HRDatabase, context_store: ContextStore):
        self.llm_config = llm_config.normalized()
        self.client = create_llm_client(self.llm_config)
        self.executor = ToolExecutor(db)
        self.context_store = context_store
        self.conversation_history: list[dict] = []

    def reset(self):
        self.conversation_history = []

    def update_llm_config(self, llm_config: LLMConfig):
        normalized = llm_config.normalized()
        if normalized != self.llm_config:
            self.llm_config = normalized
            self.client = create_llm_client(normalized)

    def chat(self, user_message: str, access_profile: AccessProfile) -> Generator[dict, None, None]:
        allowed, reason = access_profile.can_access_question(user_message)
        if not allowed:
            yield {"type": "final_text", "text": reason}
            self.context_store.remember(access_profile.email, user_message, reason)
            return

        recent_memory = self.context_store.recent_memory(access_profile.email)
        context_documents = self.context_store.search_documents(
            user_message,
            access_profile.allowed_doc_tags,
        )
        system_prompt = build_system_prompt(
            access_profile=access_profile.summary(),
            recent_memory=recent_memory,
            context_documents=context_documents,
        )

        self.conversation_history.append({"role": "user", "content": user_message})
        iteration = 0

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
                    yield {
                        "type": "tool_call",
                        "name": tool_call.name,
                        "explanation": tool_input.get("explanation", ""),
                        "sql": tool_input.get("sql_query", ""),
                        "inputs": tool_input,
                    }

                    result = self.executor.execute(tool_call.name, tool_input, access_profile=access_profile)
                    parsed_result = self._safe_parse_json(result)

                    if isinstance(parsed_result, dict) and "chart_json" in parsed_result:
                        yield {
                            "type": "chart",
                            "chart_json": parsed_result["chart_json"],
                            "title": parsed_result.get("title", "Chart"),
                        }

                    table_data = None
                    table_title = tool_call.name
                    if isinstance(parsed_result, list):
                        table_data = parsed_result[:50]
                    elif isinstance(parsed_result, dict) and "results" in parsed_result and isinstance(parsed_result["results"], list):
                        table_data = parsed_result["results"][:50]
                        table_title = parsed_result.get("report_name") or parsed_result.get("focus_area") or tool_call.name

                    yield {
                        "type": "tool_result",
                        "name": tool_call.name,
                        "result": result[:2000],
                        "table_data": table_data,
                        "title": table_title,
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
            self.context_store.remember(access_profile.email, user_message, final_text)
            yield {"type": "final_text", "text": final_text}
            return

        fallback = f"Agent reached max iterations ({MAX_AGENT_ITERATIONS}). Try a more specific HR question."
        self.context_store.remember(access_profile.email, user_message, fallback)
        yield {"type": "error", "message": fallback}

    def _safe_parse_json(self, value: str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return None
