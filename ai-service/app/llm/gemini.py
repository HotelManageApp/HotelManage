"""Gemini adapter: `models/{model}:generateContent` over REST (function calling + JSON output).

Conversions:
- system messages -> `systemInstruction`; assistant -> role "model"; tool results ->
  `functionResponse` parts in a "user" turn (Gemini needs the function name, looked up from the
  assistant turn that made the call).
- Tool schemas -> Gemini's OpenAPI subset: `additionalProperties`, `$schema`, unsupported formats
  are dropped, `const` becomes a one-value `enum`, `["x", "null"]` becomes `nullable`. The
  orchestrator re-validates tool arguments with the full schema, so nothing is lost.
- Gemini cannot combine function calling with a JSON response in one call: a request with both
  is refused here, and the orchestrator asks for the structured answer in a turn without tools.
"""

import json
from typing import Any

import httpx

from app.llm.base import LLMClient, LLMError, LLMRequest, LLMResponse, Message, ToolCall, ToolSpec
from app.llm.http import post_json

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
_MODES = {"auto": "AUTO", "required": "ANY", "none": "NONE"}
_KEEP = {
    "type", "format", "description", "nullable", "enum", "properties", "required", "items",
    "minItems", "maxItems", "minimum", "maximum", "minLength", "maxLength", "pattern", "anyOf",
    "title", "default",
}  # fmt: skip
_FORMATS = {"enum", "date-time", "int32", "int64", "float", "double"}


def to_gemini_schema(schema: Any) -> Any:
    if isinstance(schema, list):
        return [to_gemini_schema(s) for s in schema]
    if not isinstance(schema, dict):
        return schema
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "const":
            out["enum"] = [value]
        elif key == "type" and isinstance(value, list):
            kinds = [t for t in value if t != "null"]
            out["type"] = kinds[0] if kinds else "string"
            if "null" in value:
                out["nullable"] = True
        elif key == "format" and value not in _FORMATS:
            continue
        elif key == "properties" and isinstance(value, dict):
            out["properties"] = {name: to_gemini_schema(sub) for name, sub in value.items()}
        elif key in ("items", "anyOf"):
            out[key] = to_gemini_schema(value)
        elif key in _KEEP:
            out[key] = value
    if "const" in schema and "type" not in out:
        out["type"] = "string"
    return out


def _tool_names(messages: tuple[Message, ...]) -> dict[str, str]:
    return {call.id: call.name for m in messages for call in m.tool_calls}


def _result_object(content: str) -> dict[str, Any]:
    try:
        value = json.loads(content)
    except ValueError:
        value = content
    return value if isinstance(value, dict) else {"result": value}


def build_body(request: LLMRequest) -> dict[str, Any]:
    if request.tools and request.response_schema is not None:
        raise LLMError("gemini: tools and response_schema cannot be used in the same call")
    names = _tool_names(request.messages)
    system = [m.content for m in request.messages if m.role == "system" and m.content]
    contents: list[dict[str, Any]] = []
    for message in request.messages:
        if message.role == "system":
            continue
        if message.role == "tool":
            part = {
                "functionResponse": {
                    "name": names.get(message.tool_call_id or "", "unknown_tool"),
                    "response": _result_object(message.content),
                }
            }
            if (
                contents
                and contents[-1]["role"] == "user"
                and "functionResponse" in contents[-1]["parts"][0]
            ):
                contents[-1]["parts"].append(part)  # parallel calls answer in one turn
            else:
                contents.append({"role": "user", "parts": [part]})
            continue
        parts: list[dict[str, Any]] = []
        if message.content:
            parts.append({"text": message.content})
        parts += [
            {"functionCall": {"name": call.name, "args": call.arguments}}
            for call in message.tool_calls
        ]
        contents.append(
            {"role": "model" if message.role == "assistant" else "user", "parts": parts}
        )

    body: dict[str, Any] = {
        "contents": contents,
        "generationConfig": {"temperature": request.temperature},
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": "\n\n".join(system)}]}
    if request.tools:
        body["tools"] = [{"functionDeclarations": [_declaration(t) for t in request.tools]}]
        body["toolConfig"] = {"functionCallingConfig": {"mode": _MODES[request.tool_choice]}}
    if request.response_schema is not None:
        body["generationConfig"]["responseMimeType"] = "application/json"
        body["generationConfig"]["responseSchema"] = to_gemini_schema(request.response_schema)
    return body


def _declaration(tool: ToolSpec) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "parameters": to_gemini_schema(tool.input_schema),
    }


def parse_response(data: dict[str, Any], *, structured: bool) -> LLMResponse:
    candidates = data.get("candidates") or []
    if not candidates:
        reason = (data.get("promptFeedback") or {}).get("blockReason", "no candidates")
        raise LLMError(f"gemini returned no answer ({reason})")
    candidate = candidates[0]
    finish = candidate.get("finishReason")
    if finish in {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"}:
        raise LLMError(f"gemini stopped the answer ({finish})")
    texts: list[str] = []
    calls: list[ToolCall] = []
    for index, part in enumerate((candidate.get("content") or {}).get("parts") or []):
        if part.get("thought"):
            continue  # model reasoning, never shown to guests
        if "text" in part:
            texts.append(part["text"])
        elif "functionCall" in part:
            call = part["functionCall"]
            args = call.get("args") or {}
            if not isinstance(args, dict):
                raise LLMError("gemini returned function arguments that are not an object")
            calls.append(
                ToolCall(id=call.get("id") or f"call_{index}", name=call["name"], arguments=args)
            )
    text = "".join(texts)
    parsed = None
    if structured and not calls:
        try:
            parsed = json.loads(text)
        except ValueError:
            raise LLMError("gemini returned JSON that does not parse") from None
        if not isinstance(parsed, dict):
            raise LLMError("gemini returned JSON that is not an object")
    usage = data.get("usageMetadata") or {}
    return LLMResponse(
        text=text,
        tool_calls=tuple(calls),
        structured=parsed,
        usage={
            "input_tokens": int(usage.get("promptTokenCount", 0)),
            "output_tokens": int(usage.get("candidatesTokenCount", 0)),
        },
    )


class GeminiClient(LLMClient):
    provider = "gemini"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float,
        base_url: str = BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._url = f"{base_url}/models/{model}:generateContent"
        self._headers = {"x-goog-api-key": api_key}
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds), transport=transport)

    async def generate(self, request: LLMRequest) -> LLMResponse:
        data = await post_json(
            self._http, self.provider, self._url, headers=self._headers, body=build_body(request)
        )
        return parse_response(data, structured=request.response_schema is not None)

    async def aclose(self) -> None:
        await self._http.aclose()
