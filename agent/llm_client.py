"""
Provider-agnostic LLM client adapters.

Supports:
  - Anthropic native tool use
  - OpenAI-compatible chat completions tool use
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from config import LLM_RATE_LIMIT_BACKOFF_SECONDS, LLM_RATE_LIMIT_RETRIES, LLM_TIMEOUT_SECONDS

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

    def _retry_rate_limit(self, provider_label: str, attempt_index: int) -> bool:
        if attempt_index >= LLM_RATE_LIMIT_RETRIES:
            return False

        delay_seconds = max(0.25, float(LLM_RATE_LIMIT_BACKOFF_SECONDS)) * (2 ** attempt_index)
        logger.warning(
            "%s rate limit reached for model=%s; retrying in %.2fs (%d/%d)",
            provider_label,
            self.config.model,
            delay_seconds,
            attempt_index + 1,
            LLM_RATE_LIMIT_RETRIES,
        )
        time.sleep(delay_seconds)
        return True


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

        for attempt_index in range(LLM_RATE_LIMIT_RETRIES + 1):
            try:
                response = self.client.messages.create(
                    model=self.config.model,
                    max_tokens=4096,
                    thinking={"type": "adaptive"},
                    system=system_prompt,
                    tools=tools,
                    messages=anthropic_messages,
                )
                break
            except self._anthropic.AuthenticationError as exc:
                raise LLMClientError("Invalid Anthropic API key.") from exc
            except self._anthropic.RateLimitError as exc:
                if self._retry_rate_limit("Anthropic", attempt_index):
                    continue
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
        from openai import (
            APIConnectionError,
            APIStatusError,
            APITimeoutError,
            AuthenticationError,
            BadRequestError,
            NotFoundError,
            OpenAI,
            PermissionDeniedError,
            RateLimitError,
        )

        client_kwargs: dict[str, Any] = {
            "api_key": self.config.api_key or "not-needed",
            "timeout": float(LLM_TIMEOUT_SECONDS),
        }
        if self.config.base_url:
            client_kwargs["base_url"] = self.config.base_url
        self._api_connection_error = APIConnectionError
        self._api_status_error = APIStatusError
        self._api_timeout_error = APITimeoutError
        self._authentication_error = AuthenticationError
        self._bad_request_error = BadRequestError
        self._not_found_error = NotFoundError
        self._permission_denied_error = PermissionDeniedError
        self._rate_limit_error = RateLimitError
        self.client = OpenAI(**client_kwargs)

    def create_response(self, system_prompt: str, tools: list[dict], messages: list[dict]) -> LLMResponse:
        openai_messages = self._to_openai_messages(system_prompt, messages)
        openai_tools = self._to_openai_tools(tools)

        for attempt_index in range(LLM_RATE_LIMIT_RETRIES + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.config.model,
                    messages=openai_messages,
                    tools=openai_tools,
                    tool_choice="auto",
                    temperature=0.2,
                )
                break
            except self._authentication_error as exc:
                raise LLMClientError("Invalid OpenAI-compatible API key.") from exc
            except self._permission_denied_error as exc:
                raise LLMClientError("OpenAI-compatible access denied. Confirm your API key and project permissions.") from exc
            except self._rate_limit_error as exc:
                if self._retry_rate_limit("OpenAI-compatible", attempt_index):
                    continue
                raise LLMClientError("OpenAI-compatible rate limit reached. Please try again shortly.") from exc
            except self._api_timeout_error as exc:
                raise LLMClientError("OpenAI-compatible request timed out. Please try again.") from exc
            except self._api_connection_error as exc:
                endpoint = self._openai_endpoint_label()
                detail = self._exception_detail(exc)
                message = (
                    f"Could not reach {endpoint}. Check the Base URL, outbound internet access, "
                    "or any proxy / firewall settings."
                )
                if detail:
                    message = f"{message} Details: {detail}"
                raise LLMClientError(message) from exc
            except self._not_found_error as exc:
                raise LLMClientError(
                    f"Model '{self.config.model}' was not found at {self._openai_endpoint_label()}. "
                    "Confirm the model name and endpoint."
                ) from exc
            except self._bad_request_error as exc:
                detail = self._exception_detail(exc)
                message = f"OpenAI-compatible request was rejected for model '{self.config.model}'."
                if detail:
                    message = f"{message} Details: {detail}"
                raise LLMClientError(message) from exc
            except self._api_status_error as exc:
                detail = self._exception_detail(exc)
                message = f"OpenAI-compatible API error ({exc.status_code}) from {self._openai_endpoint_label()}."
                if detail:
                    message = f"{message} Details: {detail}"
                raise LLMClientError(message) from exc
            except Exception as exc:
                detail = self._exception_detail(exc)
                message = f"OpenAI-compatible provider error: {type(exc).__name__}"
                if detail:
                    message = f"{message}. Details: {detail}"
                raise LLMClientError(message) from exc

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

    def _openai_endpoint_label(self) -> str:
        endpoint = self.config.base_url or "https://api.openai.com/v1"
        parsed = urlparse(endpoint)
        if parsed.scheme and parsed.netloc:
            path = parsed.path.rstrip("/")
            return f"{parsed.scheme}://{parsed.netloc}{path}"
        return endpoint

    def _exception_detail(self, exc: Exception) -> str:
        detail = str(exc).strip()
        cause = getattr(exc, "__cause__", None)
        cause_detail = str(cause).strip() if cause else ""
        if cause_detail and cause_detail not in detail:
            return f"{detail} ({cause_detail})" if detail else cause_detail
        return detail


def create_llm_client(config: LLMConfig) -> BaseLLMClient:
    normalized = config.normalized()
    if normalized.provider == OPENAI_COMPAT_PROVIDER:
        return OpenAICompatibleLLMClient(normalized)
    return AnthropicLLMClient(normalized)
