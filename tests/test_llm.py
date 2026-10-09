import httpx
import pytest

from yahoofinance_newsmcp.config import Settings
from yahoofinance_newsmcp.llm import LlmClient, LlmError, extract_chat_text, parse_json_block


def _chat_payload(content="hello"):
    return {"choices": [{"message": {"content": content}}]}


def test_extract_chat_text():
    assert extract_chat_text(_chat_payload(" hi ")) == "hi"


def test_extract_chat_text_missing_content_raises():
    with pytest.raises(LlmError):
        extract_chat_text({"choices": [{"message": {}}]})


def test_parse_json_block_bare():
    assert parse_json_block('["a", "b"]') == ["a", "b"]


def test_parse_json_block_fenced():
    assert parse_json_block('Here you go:\n```json\n{"ok": true}\n```\nDone') == {"ok": True}


def test_parse_json_block_nested_in_prose():
    assert parse_json_block('The result is {"a": 1} period.') == {"a": 1}


def test_parse_json_block_unparseable_raises():
    with pytest.raises(LlmError):
        parse_json_block("not json at all")


class TestChat:
    def test_chat_returns_text(self):
        def handler(request):
            assert request.headers.get("authorization") == "Bearer sk-test"
            return httpx.Response(200, json=_chat_payload("the answer"))

        settings = Settings(llm_chat_url="https://llm.example/v1/chat/completions", llm_model="m", llm_api_key="sk-test")
        with httpx.Client(transport=httpx.MockTransport(handler)) as http:
            llm = LlmClient(settings, http_client=http)
            assert llm.chat([{"role": "user", "content": "q"}]) == "the answer"

    def test_chat_requires_url(self):
        llm = LlmClient(Settings(llm_model="m"))
        with pytest.raises(LlmError, match="LLM_CHAT_URL"):
            llm.chat([{"role": "user", "content": "q"}])

    def test_chat_requires_model(self):
        llm = LlmClient(Settings(llm_chat_url="https://x.example"))
        with pytest.raises(LlmError, match="LLM_MODEL"):
            llm.chat([{"role": "user", "content": "q"}])

    def test_chat_raises_on_http_error(self):
        def handler(request):
            return httpx.Response(500)

        settings = Settings(llm_chat_url="https://llm.example/v1/chat/completions", llm_model="m")
        with httpx.Client(transport=httpx.MockTransport(handler)) as http:
            llm = LlmClient(settings, http_client=http)
            with pytest.raises(LlmError, match="HTTP 500"):
                llm.chat([{"role": "user", "content": "q"}])