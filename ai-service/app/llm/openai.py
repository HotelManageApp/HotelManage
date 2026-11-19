"""OpenAI adapter: Chat Completions over REST (function calling + JSON schema output).

Tool calls come back with `arguments` as a JSON string; they are parsed here and a call whose
arguments do not parse is an LLMError (the orchestrator never runs a half-read call).
"""

import json
from typing import Any

import httpx

from app.llm.base import LLMClient, LLMError, LLMRequest, LLMResponse, Message, ToolCall, ToolSpec
from app.llm.http import post_json

BASE_URL = "https://api.openai.com/v1"


def _message(message: Message) -> dict[str, Any]:
    if message.role == "tool":
        return {"role": "tool", "tool_call_id": message.tool_call_id, "content": message.content}
    out: dict[str, Any] = {"role": message.role, "content": message.content or None}
    if message.tool_calls:
        out["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments, ensure_ascii=False),
                },
            }
            for call in message.tool_calls
        ]
    elif out["content"] is None:
        out["content"] = ""
    return out


def _tool(tool: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema,
        },
    }


def build_body(request: LLMRequest, model: str) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "messages": [_message(m) for m in request.messages],
        "temperature": request.temperature,
    }
    if request.tools:
        body["tools"] = [_tool(t) for t in request.tools]
        body["tool_choice"] = request.tool_choice
    if request.response_schema is not None:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "answer", "schema": request.response_schema, "strict": False},
        }
    return body


def parse_response(data: dict[str, Any], *, structured: bool) -> LLMResponse:
    choices = data.get("choices") or []
    if not choices:
        raise LLMError("openai returned no choices")
    choice = choices[0]
    if choice.get("finish_reason") == "content_filter":
        raise LLMError("openai stopped the answer (content_filter)")
    message = choice.get("message") or {}
    if message.get("refusal"):
        raise LLMError("openai refused to answer")
    calls: list[ToolCall] = []
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        try:
            args = json.loads(function.get("arguments") or "{}")
        except ValueError:
            raise LLMError("openai returned tool arguments that do not parse") from None
        if not isinstance(args, dict):
            raise LLMError("openai returned tool arguments that are not an object")
        calls.append(ToolCall(id=call["id"], name=function["name"], arguments=args))
    text = message.get("content") or ""
    parsed = None
    if structured and not calls:
        try:
            parsed = json.loads(text)
        except ValueError:
            raise LLMError("openai returned JSON that does not parse") from None
        if not isinstance(parsed, dict):
            raise LLMError("openai returned JSON that is not an object")
    usage = data.get("usage") or {}
    return LLMResponse(
        text=text,
        tool_calls=tuple(calls),
        structured=parsed,
        usage={
            "input_tokens": int(usage.get("prompt_tokens", 0)),
            "output_tokens": int(usage.get("completion_tokens", 0)),
        },
    )


class OpenAIClient(LLMClient):
    provider = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float,
        base_url: str = BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._url = f"{base_url}/chat/completions"
        self._model = model
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds), transport=transport)

    async def generate(self, request: LLMRequest) -> LLMResponse:
        data = await post_json(
            self._http,
            self.provider,
            self._url,
            headers=self._headers,
            body=build_body(request, self._model),
        )
        return parse_response(data, structured=request.response_schema is not None)

    async def aclose(self) -> None:
        await self._http.aclose()
