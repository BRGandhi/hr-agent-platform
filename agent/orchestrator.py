"""
The agent orchestrator implements a provider-agnostic Think → Act → Observe loop.
"""

from __future__ import annotations

import json
from typing import Generator

from agent.llm_client import LLMClientError, LLMConfig, create_llm_client
from agent.prompts import SYSTEM_PROMPT
from agent.tool_executor import ToolExecutor
from agent.tools import TOOLS
from config import MAX_AGENT_ITERATIONS
from database.connector import HRDatabase


class HRAgent:
    def __init__(self, llm_config: LLMConfig, db: HRDatabase):
        self.llm_config = llm_config.normalized()
        self.client = create_llm_client(self.llm_config)
        self.executor = ToolExecutor(db)
        self.conversation_history: list[dict] = []

    def reset(self):
        """Clear conversation history to start a new session."""
        self.conversation_history = []

    def update_llm_config(self, llm_config: LLMConfig):
        normalized = llm_config.normalized()
        if normalized != self.llm_config:
            self.llm_config = normalized
            self.client = create_llm_client(normalized)

    def chat(self, user_message: str) -> Generator[dict, None, None]:
        """
        Send a user message and run the agent loop.

        Yields event dicts for the UI:
          {"type": "tool_call",   "name": str, "explanation": str, "sql": str}
          {"type": "tool_result", "name": str, "result": str, "table_data": list | dict | None}
          {"type": "chart",       "chart_json": str, "title": str}
          {"type": "final_text",  "text": str}
          {"type": "error",       "message": str}
        """
        self.conversation_history.append({"role": "user", "content": user_message})

        iteration = 0

        while iteration < MAX_AGENT_ITERATIONS:
            iteration += 1

            try:
                response = self.client.create_response(
                    system_prompt=SYSTEM_PROMPT,
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

                    result = self.executor.execute(tool_call.name, tool_input)
                    parsed_result = self._safe_parse_json(result)

                    if isinstance(parsed_result, dict) and "chart_json" in parsed_result:
                        yield {
                            "type": "chart",
                            "chart_json": parsed_result["chart_json"],
                            "title": parsed_result.get("title", "Chart"),
                        }

                    table_data = None
                    if isinstance(parsed_result, list):
                        table_data = parsed_result[:50]
                    elif isinstance(parsed_result, dict) and "results" in parsed_result and isinstance(parsed_result["results"], list):
                        table_data = parsed_result["results"][:50]

                    yield {
                        "type": "tool_result",
                        "name": tool_call.name,
                        "result": result[:2000],
                        "table_data": table_data,
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

            final_text = response.text.strip()
            yield {
                "type": "final_text",
                "text": final_text or "(The model returned no final text.)",
            }
            return

        yield {
            "type": "error",
            "message": f"Agent reached max iterations ({MAX_AGENT_ITERATIONS}). Try a more specific question.",
        }

    def _safe_parse_json(self, value: str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return None
