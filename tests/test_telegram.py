import httpx
import pytest

from yahoofinance_newsmcp.config import Settings
from yahoofinance_newsmcp.telegram import TelegramClient, TelegramError, chunk_message


def _long_text(n=10000):
    return ("line of text for body " * 500)[:n]


def test_chunk_message_short_is_unchanged():
    assert chunk_message("hello") == ["hello"]


def test_chunk_message_splits_under_limit():
    chunks = chunk_message(_long_text(10000), limit=1000)
    assert len(chunks) > 1
    assert all(len(chunk) <= 1000 for chunk in chunks)
    assert "".join(chunks) == _long_text(10000)


def test_chunk_message_prefers_line_breaks():
    text = ("a" * 100) + "\n" + ("b" * 100)
    chunks = chunk_message(text, limit=120)
    assert chunks[0].endswith("a" * 100)
    assert chunks[1] == "b" * 100


def test_send_message_delivers_chunks():
    def handler(request):
        assert "sendMessage" in str(request.url)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 42}})

    settings = Settings(telegram_bot_token="bot-token", telegram_chat_id="123")
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = TelegramClient(settings, http_client=http)
        ids = client.send_message(_long_text(9000))
    assert len(ids) == 3
    assert all(message_id == 42 for message_id in ids)


def test_send_message_requires_token():
    client = TelegramClient(Settings())
    with pytest.raises(TelegramError, match="TELEGRAM_BOT_TOKEN"):
        client.send_message("hi")


def test_send_message_requires_chat_id():
    client = TelegramClient(Settings(telegram_bot_token="t"))
    with pytest.raises(TelegramError, match="TELEGRAM_CHAT_ID"):
        client.send_message("hi")


def test_send_message_raises_on_http_error():
    def handler(request):
        return httpx.Response(400)

    settings = Settings(telegram_bot_token="t", telegram_chat_id="1")
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = TelegramClient(settings, http_client=http)
        with pytest.raises(TelegramError, match="HTTP 400"):
            client.send_message("hi")