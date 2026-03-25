"""
Provider-agnostic LLM client adapters.

Supports:
  - Anthropic native tool use
  - OpenAI-compatible chat completions tool use
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from config import LLM_TIMEOUT_SECONDS

logger = logging.getLogger("hr_platform.llm")

OPENAI_COMPAT_PROVIDER = "openai-compatible"


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall]
    stop_reason: str


@dataclass
class LLMConfig:
    provider: str
    model: str
    api_key: str
    base_url: str = ""

    def normalized(self) -> "LLMConfig":
        return LLMConfig(
            provider=(self.provider or "anthropic").strip().lower(),
            model=(self.model or "").strip(),
            api_key=(self.api_key or "").strip(),
            base_url=(self.base_url or "").strip(),
        )


class LLMClientError(Exception):
    """Raised when an upstream LLM call fails."""


class BaseLLMClient:
    def __init__(self, config: LLMConfig):
        self.config = config.normalized()

    def create_response(self, system_prompt: str, tools: list[dict], messages: list[dict]) -> LLMResponse:
        raise NotImplementedError


class AnthropicLLMClient(BaseLLMClient):
    def __init__(self, config: LLMConfig):
        super().__init__(config)
        import anthropic

        self._anthropic = anthropic
        self.client = anthropic.Anthropic(
            api_key=self.config.api_key,
            timeout=float(LLM_TIMEOUT_SECONDS),
        )

    def create_response(self, system_prompt: str, tools: list[dict], messages: list[dict]) -> LLMResponse:
        anthropic_messages = self._to_anthropic_messages(messages)

        try:
            response = self.client.messages.create(
                model=self.config.model,
                max_tokens=4096,
                thinking={"type": "adaptive"},
                system=system_prompt,
                tools=tools,
                messages=anthropic_messages,
            )
        except self._anthropic.AuthenticationError as exc:
            raise LLMClientError("Invalid Anthropic API key.") from exc
        except self._anthropic.RateLimitError as exc:
            raise LLMClientError("Anthropic rate limit reached. Please try again shortly.") from exc
        except self._anthropic.APIConnectionError as exc:
            raise LLMClientError("Could not connect to Anthropic. Check your network connection.") from exc
        except self._anthropic.APITimeoutError as exc:
            raise LLMClientError("Anthropic API request timed out. Please try again.") from exc
        except self._anthropic.APIStatusError as exc:
            raise LLMClientError(f"Anthropic API error ({exc.status_code}).") from exc

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for block in response.content:
            if getattr(block, "type", "") == "text":
                text_parts.append(block.text)
            elif getattr(block, "type", "") == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, input=block.input))

        stop_reason = "tool_use" if tool_calls else response.stop_reason or "end_turn"
        return LLMResponse(text="".join(text_parts), tool_calls=tool_calls, stop_reason=stop_reason)

    def _to_anthropic_messages(self, messages: list[dict]) -> list[dict]:
        converted: list[dict] = []
        index = 0

        while index < len(messages):
            message = messages[index]
            role = message["role"]

            if role == "user":
                converted.append({"role": "user", "content": message["content"]})
                index += 1
                continue

            if role == "assistant":
                blocks: list[dict] = []
                if message.get("content"):
                    blocks.append({"type": "text", "text": message["content"]})
                for tool_call in message.get("tool_calls", []):
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": tool_call["id"],
                            "name": tool_call["name"],
                            "input": tool_call["input"],
                        }
                    )
                converted.append({"role": "assistant", "content": blocks or [{"type": "text", "text": ""}]})
                index += 1
                continue

            if role == "tool":
                tool_results: list[dict] = []
                while index < len(messages) and messages[index]["role"] == "tool":
                    tool_message = messages[index]
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_message["tool_call_id"],
                            "content": tool_message["content"],
                        }
                    )
                    index += 1
                converted.append({"role": "user", "content": tool_results})
                continue

            index += 1

        return converted


class OpenAICompatibleLLMClient(BaseLLMClient):
    def __init__(self, config: LLMConfig):
        super().__init__(config)
        from openai import OpenAI

        client_kwargs: dict[str, Any] = {
            "api_key": self.config.api_key or "not-needed",
            "timeout": float(LLM_TIMEOUT_SECONDS),
        }
        if self.config.base_url:
            client_kwargs["base_url"] = self.config.base_url
        self.client = OpenAI(**client_kwargs)

    def create_response(self, system_prompt: str, tools: list[dict], messages: list[dict]) -> LLMResponse:
        openai_messages = self._to_openai_messages(system_prompt, messages)
        openai_tools = self._to_openai_tools(tools)

        try:
            response = self.client.chat.completions.create(
                model=self.config.model,
                messages=openai_messages,
                tools=openai_tools,
                tool_choice="auto",
                temperature=0.2,
            )
        except Exception as exc:
            raise LLMClientError(f"OpenAI-compatible provider error: {type(exc).__name__}") from exc

        message = response.choices[0].message
        tool_calls: list[ToolCall] = []

        for tool_call in message.tool_calls or []:
            try:
                arguments = json.loads(tool_call.function.arguments or "{}")
            except json.JSONDecodeError as exc:
                raise LLMClientError(
                    f"Model returned invalid JSON arguments for tool '{tool_call.function.name}'."
                ) from exc
            tool_calls.append(
                ToolCall(
                    id=tool_call.id,
                    name=tool_call.function.name,
                    input=arguments,
                )
            )

        stop_reason = "tool_use" if tool_calls else (response.choices[0].finish_reason or "stop")
        return LLMResponse(text=message.content or "", tool_calls=tool_calls, stop_reason=stop_reason)

    def _to_openai_messages(self, system_prompt: str, messages: list[dict]) -> list[dict]:
        converted: list[dict] = [{"role": "system", "content": system_prompt}]

        for message in messages:
            role = message["role"]

            if role == "user":
                converted.append({"role": "user", "content": message["content"]})
            elif role == "assistant":
                assistant_message: dict[str, Any] = {
                    "role": "assistant",
                    "content": message.get("content") or "",
                }
                if message.get("tool_calls"):
                    assistant_message["tool_calls"] = [
                        {
                            "id": tool_call["id"],
                            "type": "function",
                            "function": {
                                "name": tool_call["name"],
                                "arguments": json.dumps(tool_call["input"]),
                            },
                        }
                        for tool_call in message["tool_calls"]
                    ]
                converted.append(assistant_message)
            elif role == "tool":
                converted.append(
                    {
                        "role": "tool",
                        "tool_call_id": message["tool_call_id"],
                        "content": message["content"],
                    }
                )

        return converted

    def _to_openai_tools(self, tools: list[dict]) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["input_schema"],
                },
            }
            for tool in tools
        ]


def create_llm_client(config: LLMConfig) -> BaseLLMClient:
    normalized = config.normalized()
    if normalized.provider == OPENAI_COMPAT_PROVIDER:
        return OpenAICompatibleLLMClient(normalized)
    return AnthropicLLMClient(normalized)
