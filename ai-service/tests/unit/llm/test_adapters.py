"""Gemini and OpenAI adapters against payloads in the providers' documented formats
(tests/fixtures/llm). No network: httpx.MockTransport stands in for the provider."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.llm.base import LLMError, LLMRequest, LLMTimeout, Message, ToolCall, ToolSpec
from app.llm.gemini import GeminiClient, to_gemini_schema
from app.llm.gemini import build_body as gemini_body
from app.llm.gemini import parse_response as gemini_parse
from app.llm.http import LLMHttpError
from app.llm.openai import OpenAIClient
from app.llm.openai import build_body as openai_body
from app.llm.openai import parse_response as openai_parse
from app.llm.registry import create_llm_client
from tests.conftest import make_settings

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "llm"
API_KEY = "test-key-should-never-leak"

# The real tool schema (docs/chatbot-tools-spec.md §4.1), JSON-Schema style.
GUIDE_TOOL = ToolSpec(
    name="get_hotel_info_and_guide",
    description="Hotel knowledge base and nearby places",
    input_schema={
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "enum": ["BREAKFAST", "WIFI", "ATTRACTIONS", "OTHER"],
            },
            "query": {"type": "string", "maxLength": 300},
            "lang": {"type": ["string", "null"], "description": "BCP-47"},
        },
        "required": ["topic", "query"],
        "additionalProperties": False,
    },
)
ORDER_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "string", "format": "uuid"},
                    "quantity": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": ["item_id", "quantity"],
                "additionalProperties": False,
            },
        },
        "guest_confirmed": {"type": "boolean", "const": True},
    },
    "required": ["items", "guest_confirmed"],
    "additionalProperties": False,
    "$schema": "https://json-schema.org/draft/2020-12/schema",
}
CALL = ToolCall(
    id="call_1",
    name="get_hotel_info_and_guide",
    arguments={"topic": "BREAKFAST", "query": "Mấy giờ ăn sáng?"},
)
CONVERSATION = (
    Message(role="system", content="You are Concierge."),
    Message(role="user", content="Mấy giờ ăn sáng?"),
    Message(role="assistant", tool_calls=(CALL,)),
    Message(
        role="tool",
        tool_call_id="call_1",
        content=json.dumps({"found": True, "entries": [{"content": "06:30–09:30"}]}),
    ),
)
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {"reply": {"type": "string"}, "suggested_actions": {"type": "array"}},
    "required": ["reply"],
}


def fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class Recorder:
    """A provider stand-in: answers with a fixture and remembers the request."""

    def __init__(self, status: int = 200, body: dict | None = None, exc: Exception | None = None):
        self.status, self.body, self.exc = status, body or {}, exc
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.exc is not None:
            raise self.exc
        return httpx.Response(self.status, json=self.body)

    @property
    def sent(self) -> dict[str, Any]:
        return json.loads(self.requests[-1].content)


# ================= Gemini =================


def test_gemini_schema_keeps_what_gemini_understands() -> None:
    converted = to_gemini_schema(ORDER_TOOL_SCHEMA)
    assert "additionalProperties" not in converted and "$schema" not in converted
    item = converted["properties"]["items"]["items"]
    assert "additionalProperties" not in item
    assert item["properties"]["item_id"] == {"type": "string"}  # "uuid" format is not supported
    assert item["properties"]["quantity"] == {"type": "integer", "minimum": 1, "maximum": 20}
    assert converted["properties"]["guest_confirmed"] == {"type": "boolean", "enum": [True]}
    assert to_gemini_schema(GUIDE_TOOL.input_schema)["properties"]["lang"] == {
        "type": "string",
        "nullable": True,
        "description": "BCP-47",
    }


def test_gemini_request_body() -> None:
    body = gemini_body(
        LLMRequest(messages=CONVERSATION, tools=(GUIDE_TOOL,), tool_choice="required")
    )
    assert body["systemInstruction"] == {"parts": [{"text": "You are Concierge."}]}
    assert body["contents"] == [
        {"role": "user", "parts": [{"text": "Mấy giờ ăn sáng?"}]},
        {
            "role": "model",
            "parts": [
                {
                    "functionCall": {
                        "name": "get_hotel_info_and_guide",
                        "args": {"topic": "BREAKFAST", "query": "Mấy giờ ăn sáng?"},
                    }
                }
            ],
        },
        {
            "role": "user",
            "parts": [
                {
                    "functionResponse": {
                        "name": "get_hotel_info_and_guide",
                        "response": {"found": True, "entries": [{"content": "06:30–09:30"}]},
                    }
                }
            ],
        },
    ]
    declaration = body["tools"][0]["functionDeclarations"][0]
    assert declaration["name"] == "get_hotel_info_and_guide"
    assert "additionalProperties" not in declaration["parameters"]
    assert body["toolConfig"] == {"functionCallingConfig": {"mode": "ANY"}}
    assert body["generationConfig"] == {"temperature": 0.2}


def test_gemini_parallel_tool_results_share_one_turn_and_plain_results_are_wrapped() -> None:
    second = ToolCall(id="call_2", name="get_available_menu", arguments={})
    messages = (
        Message(role="user", content="hi"),
        Message(role="assistant", tool_calls=(CALL, second)),
        Message(role="tool", tool_call_id="call_1", content='{"found": false}'),
        Message(role="tool", tool_call_id="call_2", content="not json"),
    )
    contents = gemini_body(LLMRequest(messages=messages))["contents"]
    assert len(contents) == 3
    responses = [p["functionResponse"] for p in contents[2]["parts"]]
    assert responses == [
        {"name": "get_hotel_info_and_guide", "response": {"found": False}},
        {"name": "get_available_menu", "response": {"result": "not json"}},
    ]


def test_gemini_structured_output_config_and_no_tools_with_a_schema() -> None:
    body = gemini_body(LLMRequest(messages=CONVERSATION[:2], response_schema=ANSWER_SCHEMA))
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["responseSchema"]["required"] == ["reply"]
    with pytest.raises(LLMError, match="cannot be used in the same call"):
        gemini_body(
            LLMRequest(messages=CONVERSATION, tools=(GUIDE_TOOL,), response_schema=ANSWER_SCHEMA)
        )


def test_gemini_parses_a_function_call_and_skips_thoughts() -> None:
    response = gemini_parse(fixture("gemini_function_call.json"), structured=False)
    assert response.text == ""
    assert response.tool_calls == (
        ToolCall(
            id="call_1",
            name="get_hotel_info_and_guide",
            arguments={"topic": "BREAKFAST", "query": "Mấy giờ ăn sáng?", "lang": "vi"},
        ),
    )
    assert response.usage == {"input_tokens": 812, "output_tokens": 31}


def test_gemini_parses_text_and_structured_answers() -> None:
    text = gemini_parse(fixture("gemini_text.json"), structured=False)
    assert text.text == "Bữa sáng phục vụ 06:30–09:30 tại tầng 1."
    structured = gemini_parse(fixture("gemini_structured.json"), structured=True)
    assert structured.structured == {
        "reply": "Bữa sáng 06:30–09:30.",
        "suggested_actions": ["CALL_RECEPTION"],
    }


@pytest.mark.parametrize(
    ("data", "structured", "message"),
    [
        (fixture("gemini_blocked.json"), False, r"no answer \(SAFETY\)"),
        ({"candidates": [{"finishReason": "SAFETY", "content": {"parts": []}}]}, False, "SAFETY"),
        (fixture("gemini_text.json"), True, "does not parse"),
        (
            {"candidates": [{"content": {"parts": [{"text": "[1, 2]"}]}}]},
            True,
            "not an object",
        ),
        (
            {
                "candidates": [
                    {"content": {"parts": [{"functionCall": {"name": "x", "args": [1]}}]}}
                ]
            },
            False,
            "not an object",
        ),
    ],
)
def test_gemini_unusable_answers_are_llm_errors(data: dict, structured: bool, message: str) -> None:
    with pytest.raises(LLMError, match=message):
        gemini_parse(data, structured=structured)


async def test_gemini_client_calls_the_rest_api() -> None:
    provider = Recorder(body=fixture("gemini_text.json"))
    llm = GeminiClient(
        api_key=API_KEY,
        model="gemini-2.5-flash",
        timeout_seconds=5,
        transport=httpx.MockTransport(provider),
    )
    answer = await llm.generate(LLMRequest(messages=CONVERSATION[:2]))
    await llm.aclose()
    request = provider.requests[0]
    assert str(request.url) == (
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
    )
    assert request.headers["x-goog-api-key"] == API_KEY
    assert API_KEY not in str(request.url)
    assert answer.text.startswith("Bữa sáng")


async def test_gemini_http_errors_and_timeouts() -> None:
    limited = GeminiClient(
        api_key=API_KEY,
        model="m",
        timeout_seconds=5,
        transport=httpx.MockTransport(Recorder(429, fixture("gemini_error_429.json"))),
    )
    with pytest.raises(LLMHttpError) as caught:
        await limited.generate(LLMRequest(messages=CONVERSATION[:2]))
    assert caught.value.status == 429 and caught.value.retryable
    assert "RESOURCE_EXHAUSTED" in str(caught.value)
    assert API_KEY not in str(caught.value)

    slow = GeminiClient(
        api_key=API_KEY,
        model="m",
        timeout_seconds=5,
        transport=httpx.MockTransport(Recorder(exc=httpx.ReadTimeout("slow"))),
    )
    with pytest.raises(LLMTimeout):
        await slow.generate(LLMRequest(messages=CONVERSATION[:2]))


# ================= OpenAI =================


def test_openai_request_body() -> None:
    body = openai_body(
        LLMRequest(messages=CONVERSATION, tools=(GUIDE_TOOL,), tool_choice="auto"), "gpt-4.1-mini"
    )
    assert body["model"] == "gpt-4.1-mini"
    assert body["messages"] == [
        {"role": "system", "content": "You are Concierge."},
        {"role": "user", "content": "Mấy giờ ăn sáng?"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "get_hotel_info_and_guide",
                        "arguments": '{"topic": "BREAKFAST", "query": "Mấy giờ ăn sáng?"}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "content": CONVERSATION[3].content,  # passed through untouched
        },
    ]
    assert body["tools"][0] == {
        "type": "function",
        "function": {
            "name": "get_hotel_info_and_guide",
            "description": "Hotel knowledge base and nearby places",
            "parameters": GUIDE_TOOL.input_schema,  # OpenAI takes JSON Schema as is
        },
    }
    assert body["tool_choice"] == "auto"
    assert "response_format" not in body


def test_openai_structured_output_config() -> None:
    body = openai_body(
        LLMRequest(messages=CONVERSATION[:2], response_schema=ANSWER_SCHEMA), "gpt-4.1-mini"
    )
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "answer", "schema": ANSWER_SCHEMA, "strict": False},
    }
    assert "tools" not in body


def test_openai_parses_tool_calls_text_and_structured() -> None:
    calls = openai_parse(fixture("openai_tool_call.json"), structured=False)
    assert calls.tool_calls == (
        ToolCall(
            id="call_9xQk",
            name="get_hotel_info_and_guide",
            arguments={"topic": "BREAKFAST", "query": "Mấy giờ ăn sáng?", "lang": "vi"},
        ),
    )
    assert calls.usage == {"input_tokens": 640, "output_tokens": 28}
    assert openai_parse(fixture("openai_text.json"), structured=False).text.startswith("Bữa sáng")
    assert openai_parse(fixture("openai_structured.json"), structured=True).structured == {
        "reply": "Bữa sáng 06:30–09:30.",
        "suggested_actions": [],
    }


def _tool_answer(arguments: str) -> dict:
    return {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "id": "c",
                            "type": "function",
                            "function": {"name": "x", "arguments": arguments},
                        }
                    ]
                },
                "finish_reason": "tool_calls",
            }
        ]
    }


@pytest.mark.parametrize(
    ("data", "structured", "message"),
    [
        ({"choices": []}, False, "no choices"),
        (
            {"choices": [{"message": {}, "finish_reason": "content_filter"}]},
            False,
            "content_filter",
        ),
        ({"choices": [{"message": {"refusal": "I can't"}}]}, False, "refused"),
        (_tool_answer("{not json"), False, "do not parse"),
        (_tool_answer("[1]"), False, "not an object"),
        (fixture("openai_text.json"), True, "does not parse"),
    ],
)
def test_openai_unusable_answers_are_llm_errors(data: dict, structured: bool, message: str) -> None:
    with pytest.raises(LLMError, match=message):
        openai_parse(data, structured=structured)


async def test_openai_client_calls_the_rest_api_and_maps_errors() -> None:
    provider = Recorder(body=fixture("openai_tool_call.json"))
    llm = OpenAIClient(
        api_key=API_KEY,
        model="gpt-4.1-mini",
        timeout_seconds=5,
        transport=httpx.MockTransport(provider),
    )
    answer = await llm.generate(LLMRequest(messages=CONVERSATION[:2], tools=(GUIDE_TOOL,)))
    await llm.aclose()
    request = provider.requests[0]
    assert str(request.url) == "https://api.openai.com/v1/chat/completions"
    assert request.headers["Authorization"] == f"Bearer {API_KEY}"
    assert provider.sent["model"] == "gpt-4.1-mini"
    assert answer.tool_calls[0].name == "get_hotel_info_and_guide"

    wrong_key = OpenAIClient(
        api_key=API_KEY,
        model="m",
        timeout_seconds=5,
        transport=httpx.MockTransport(Recorder(401, fixture("openai_error_401.json"))),
    )
    with pytest.raises(LLMHttpError) as caught:
        await wrong_key.generate(LLMRequest(messages=CONVERSATION[:2]))
    assert caught.value.status == 401 and not caught.value.retryable
    assert API_KEY not in str(caught.value)

    for failure, kind in (
        (httpx.ConnectTimeout("t"), LLMTimeout),
        (httpx.ConnectError("x"), LLMError),
    ):
        broken = OpenAIClient(
            api_key=API_KEY,
            model="m",
            timeout_seconds=5,
            transport=httpx.MockTransport(Recorder(exc=failure)),
        )
        with pytest.raises(kind):
            await broken.generate(LLMRequest(messages=CONVERSATION[:2]))


async def test_a_body_that_is_not_json_is_an_llm_error() -> None:
    def text(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>proxy error</html>")

    llm = OpenAIClient(
        api_key=API_KEY, model="m", timeout_seconds=5, transport=httpx.MockTransport(text)
    )
    with pytest.raises(LLMError, match="not JSON"):
        await llm.generate(LLMRequest(messages=CONVERSATION[:2]))


# ================= registry / settings =================


def test_registry_builds_the_configured_provider() -> None:
    gemini = create_llm_client(make_settings(llm_provider="gemini", gemini_api_key="k" * 20))
    openai = create_llm_client(make_settings(llm_provider="openai", openai_api_key="k" * 20))
    assert isinstance(gemini, GeminiClient) and gemini.provider == "gemini"
    assert isinstance(openai, OpenAIClient) and openai.provider == "openai"
