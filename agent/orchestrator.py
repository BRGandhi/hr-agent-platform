"""
The Agent Orchestrator: implements the Think → Act → Observe loop.

Flow:
  1. THINK  — Send conversation + tools to Claude (claude-opus-4-6)
  2. ACT    — Claude responds with text or tool_use blocks
  3. OBSERVE — If tool_use: execute tool, append result, loop back to 1
              If end_turn: return final text to Streamlit
"""

import anthropic
from typing import Generator

from agent.tools import TOOLS
from agent.tool_executor import ToolExecutor
from agent.prompts import SYSTEM_PROMPT
from database.connector import HRDatabase
from config import DEFAULT_MODEL, MAX_AGENT_ITERATIONS


class HRAgent:
    def __init__(self, api_key: str, db: HRDatabase):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.executor = ToolExecutor(db)
        self.conversation_history: list[dict] = []

    def reset(self):
        """Clear conversation history to start a new session."""
        self.conversation_history = []

    def chat(self, user_message: str) -> Generator[dict, None, None]:
        """
        Send a user message and run the agent loop.

        Yields event dicts so Streamlit can stream updates in real-time:
          {"type": "tool_call",   "name": str, "explanation": str, "sql": str}
          {"type": "tool_result", "name": str, "result": str}
          {"type": "chart",       "chart_json": str, "title": str}
          {"type": "final_text",  "text": str}
          {"type": "error",       "message": str}
        """
        self.conversation_history.append({
            "role": "user",
            "content": user_message,
        })

        iteration = 0

        while iteration < MAX_AGENT_ITERATIONS:
            iteration += 1

            try:
                response = self.client.messages.create(
                    model=DEFAULT_MODEL,
                    max_tokens=4096,
                    thinking={"type": "adaptive"},
                    system=SYSTEM_PROMPT,
                    tools=TOOLS,
                    messages=self.conversation_history,
                )
            except anthropic.AuthenticationError:
                yield {"type": "error", "message": "Invalid Anthropic API key. Please check your key in the sidebar."}
                return
            except anthropic.RateLimitError:
                yield {"type": "error", "message": "Rate limit reached. Please wait a moment and try again."}
                return
            except anthropic.APIConnectionError:
                yield {"type": "error", "message": "Connection error. Please check your internet connection."}
                return
            except anthropic.APIStatusError as e:
                yield {"type": "error", "message": f"API error ({e.status_code}): {e.message}"}
                return

            assistant_content = response.content

            # Append the full assistant response (including tool_use blocks)
            self.conversation_history.append({
                "role": "assistant",
                "content": assistant_content,
            })

            if response.stop_reason == "end_turn":
                # Extract the final text and return it
                text = ""
                for block in assistant_content:
                    if hasattr(block, "text"):
                        text += block.text
                yield {"type": "final_text", "text": text}
                return

            elif response.stop_reason == "tool_use":
                # Extract and execute each tool call
                tool_results = []

                for block in assistant_content:
                    if block.type != "tool_use":
                        continue

                    tool_name = block.name
                    tool_input = block.input

                    # Stream tool call info to UI
                    event = {
                        "type": "tool_call",
                        "name": tool_name,
                        "explanation": tool_input.get("explanation", ""),
                        "sql": tool_input.get("sql_query", ""),
                        "inputs": tool_input,
                    }
                    yield event

                    # Execute the tool
                    result = self.executor.execute(tool_name, tool_input)

                    # Check if it's a chart result
                    try:
                        import json
                        parsed = json.loads(result)
                        if isinstance(parsed, dict) and "chart_json" in parsed:
                            yield {
                                "type": "chart",
                                "chart_json": parsed["chart_json"],
                                "title": parsed.get("title", "Chart"),
                            }
                    except (json.JSONDecodeError, TypeError):
                        pass

                    yield {
                        "type": "tool_result",
                        "name": tool_name,
                        "result": result[:2000],  # truncate for display
                    }

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

                # Feed all tool results back to Claude
                self.conversation_history.append({
                    "role": "user",
                    "content": tool_results,
                })

            else:
                # Unexpected stop reason — return whatever text we have
                text = ""
                for block in assistant_content:
                    if hasattr(block, "text"):
                        text += block.text
                yield {"type": "final_text", "text": text or f"(stopped: {response.stop_reason})"}
                return

        yield {
            "type": "error",
            "message": f"Agent reached max iterations ({MAX_AGENT_ITERATIONS}). Try a more specific question.",
        }
