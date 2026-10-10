import httpx
import pytest

from yahoofinance_newsmcp.config import Settings
from yahoofinance_newsmcp.telegram import CHUNK_CHARS, TelegramClient, TelegramError, chunk_message


def _long_text(n=10000):
    return ("line of text for body " * 500)[:n]


def test_chunk_message_short_is_unchanged():
    assert chunk_message("hello") == ["hello"]


def test_chunk_message_splits_under_limit():
    chunks = chunk_message(_long_text(10000), limit=1000)
    assert len(chunks) > 1
    assert all(len(chunk) <= 1000 for chunk in chunks)
    assert "".join(chunks) == _long_text(10000)


def test_chunk_message_exact_boundary():
    text = "a" * (CHUNK_CHARS - 5) + "\n" + "b" * 5
    chunks = chunk_message(text, limit=CHUNK_CHARS)
    assert len(chunks) == 2
    assert all(len(c) <= CHUNK_CHARS for c in chunks)
    recon = "\n".join(chunks)
    assert recon == text or recon + "\n" == text


def test_chunk_message_multiple_chunks_at_boundary():
    # Build text that crosses boundary cleanly
    part1 = "a" * (CHUNK_CHARS - 1) + "\n"
    part2 = "b" * (CHUNK_CHARS - 1) + "\n"
    part3 = "c" * 10
    text = part1 + part2 + part3
    chunks = chunk_message(text, limit=CHUNK_CHARS)
    assert all(len(c) <= CHUNK_CHARS for c in chunks)
    recon = "\n".join(chunks)
    assert recon == text or recon + "\n" == text


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


def test_get_me_returns_username():
    def handler(request):
        assert "getMe" in str(request.url)
        return httpx.Response(200, json={"ok": True, "result": {"id": 1, "username": "yahoobot"}})

    settings = Settings(telegram_bot_token="t")
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = TelegramClient(settings, http_client=http)
        assert client.get_me() == "yahoobot"


def test_get_me_requires_token():
    client = TelegramClient(Settings())
    with pytest.raises(TelegramError, match="TELEGRAM_BOT_TOKEN"):
        client.get_me()


def test_get_me_raises_when_bot_unauthorized():
    def handler(request):
        return httpx.Response(401, json={"ok": False, "description": "Unauthorized"})

    settings = Settings(telegram_bot_token="bad")
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = TelegramClient(settings, http_client=http)
        with pytest.raises(TelegramError, match="rejected"):
            client.get_me()


def test_get_me_raises_when_telegram_error():
    def handler(request):
        return httpx.Response(200, json={"ok": False, "description": "flood"})

    settings = Settings(telegram_bot_token="t")
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = TelegramClient(settings, http_client=http)
        with pytest.raises(TelegramError, match="flood"):
            client.get_me()