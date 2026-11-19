import pytest

from app.llm.base import LLMError, LLMRequest, LLMResponse, LLMTimeout, Message, ToolCall, ToolSpec
from app.llm.fake import DEFAULT_REPLY, FakeLLMClient
from app.llm.registry import create_llm_client
from tests.conftest import make_settings

REQUEST = LLMRequest(
    messages=(Message(role="system", content="sys"), Message(role="user", content="hi")),
    tools=(ToolSpec(name="get_hotel_info_and_guide", description="kb", input_schema={}),),
)


async def test_fake_returns_scripted_responses_in_order_and_records_requests() -> None:
    call = ToolCall(id="c1", name="get_hotel_info_and_guide", arguments={"topic": "BREAKFAST"})
    llm = FakeLLMClient([LLMResponse(tool_calls=(call,)), LLMResponse(text="06:30")])

    first = await llm.generate(REQUEST)
    second = await llm.generate(REQUEST)

    assert first.tool_calls == (call,)
    assert second.text == "06:30"
    assert llm.requests == [REQUEST, REQUEST]
    assert llm.remaining == 0


async def test_fake_default_reply_when_script_is_empty() -> None:
    assert (await FakeLLMClient().generate(REQUEST)).text == DEFAULT_REPLY


async def test_fake_raises_scripted_errors() -> None:
    llm = FakeLLMClient()
    llm.queue(LLMTimeout("slow"))
    with pytest.raises(LLMTimeout):
        await llm.generate(REQUEST)


async def test_fake_rejects_non_response_items() -> None:
    llm = FakeLLMClient(["not a response"])
    with pytest.raises(LLMError):
        await llm.generate(REQUEST)


def test_registry_builds_adapter_from_settings() -> None:
    client = create_llm_client(make_settings(llm_provider="fake"))
    assert isinstance(client, FakeLLMClient)
    assert client.provider == "fake"


def test_registry_rejects_unregistered_provider() -> None:
    settings = make_settings().model_copy(update={"llm_provider": "nope"})
    with pytest.raises(ValueError, match="no LLM adapter"):
        create_llm_client(settings)
