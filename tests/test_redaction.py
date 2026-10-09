from yahoofinance_newsmcp.redaction import REDACTED, redact_text, redact_url, redact_value


def test_redact_url_credentials_and_query_secret():
    url = "https://user:pass@host.example:8443/path?api_key=abc&keep=1&token=xyz#frag"
    redacted = redact_url(url)
    assert "user" not in redacted and "pass" not in redacted
    assert "abc" not in redacted and "xyz" not in redacted
    assert "keep=1" in redacted
    assert "8443" in redacted


def test_redact_text_fragments():
    text = "Called with token=secret123 and url https://x.example/?apikey=hunter2"
    redacted = redact_text(text)
    assert "secret123" not in redacted
    assert "hunter2" not in redacted
    assert REDACTED in redacted


def test_redact_value_recursive():
    value = {"nested": {"password": "s3cret", "keep": "fine"}, "url": "https://a.example/?key=k"}
    redacted = redact_value(value)
    assert redacted["nested"]["password"] == REDACTED
    assert redacted["nested"]["keep"] == "fine"
    assert "key=k" not in redacted["url"]
    assert REDACTED in redacted["url"]


def test_redact_text_keeps_normal_text():
    assert redact_text("plain text, nothing secret") == "plain text, nothing secret"