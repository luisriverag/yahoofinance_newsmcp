from yahoofinance_newsmcp.cache import JsonCache
from yahoofinance_newsmcp.summarize import (
    build_article_prompt,
    build_company_prompt,
    build_overall_prompt,
    parse_article_summaries,
    summarize_articles,
    summarize_company,
)
from yahoofinance_newsmcp.yahoo import NewsArticle


def _article(title, ticker="AAPL"):
    return NewsArticle(ticker=ticker, title=title, link=f"https://example.com/{title}", body="body " + title)


def test_build_article_prompt_contains_articles_and_json_instruction():
    prompt = build_article_prompt("AAPL", [_article("first"), _article("second")])
    assert "JSON array" in prompt[-1]["content"]
    assert "first" in prompt[-1]["content"] and "second" in prompt[-1]["content"]


def test_build_company_and_overall_prompts():
    company = build_company_prompt("AAPL", [_article("x")])
    assert "AAPL" in company[-1]["content"]
    overall = build_overall_prompt([("AAPL", "strong"), ("MSFT", "weak")])
    assert "strong" in overall[-1]["content"] and "weak" in overall[-1]["content"]


def test_build_prompts_with_company_name():
    article = build_article_prompt("AAPL", [_article("x")], company_name="Apple Inc.")
    assert "AAPL (Apple Inc.)" in article[-1]["content"]
    company = build_company_prompt("AAPL", [_article("x")], company_name="Apple Inc.")
    assert "AAPL (Apple Inc.)" in company[-1]["content"]


def test_build_prompts_company_name_same_as_ticker():
    article = build_article_prompt("AAPL", [_article("x")], company_name="AAPL")
    assert "AAPL (AAPL)" not in article[-1]["content"]


def test_build_overall_prompt_includes_tone():
    overall = build_overall_prompt([("AAPL", "strong")], tone="brisk and plain-spoken")
    assert "brisk and plain-spoken" in overall[-1]["content"]


def test_build_overall_prompt_without_tone_has_no_tone_line():
    overall = build_overall_prompt([("AAPL", "strong")])
    assert "Tone/style" not in overall[-1]["content"]


def test_parse_article_summaries_json_array():
    assert parse_article_summaries('["a", "b"]', expected=2) == ["a", "b"]


def test_parse_article_summaries_dict_objects():
    text = '[{"summary": "s1"}, {"text": "s2"}]'
    assert parse_article_summaries(text, expected=2) == ["s1", "s2"]


def test_parse_article_summaries_pads_missing():
    assert parse_article_summaries('["a"]', expected=3) == ["a", "", ""]


def test_parse_article_summaries_line_fallback():
    text = "1. first summary\n2. second summary"
    assert parse_article_summaries(text, expected=2) == ["first summary", "second summary"]


def test_parse_article_summaries_bullet_fallback():
    assert parse_article_summaries("- bullet summary", expected=1) == ["bullet summary"]


class _RecordingLLM:
    def __init__(self, reply="reply"):
        self.reply = reply
        self.calls = 0

    def chat(self, messages):
        self.calls += 1
        return self.reply


def test_summarize_articles_without_cache_always_calls_llm():
    llm = _RecordingLLM('["s1", "s2"]')
    articles = [_article("first"), _article("second")]

    first = summarize_articles(llm, "AAPL", articles)
    second = summarize_articles(llm, "AAPL", articles)

    assert first == ["s1", "s2"]
    assert second == ["s1", "s2"]
    assert llm.calls == 2


def test_summarize_articles_with_cache_skips_llm_on_repeat_call(tmp_path):
    cache = JsonCache(str(tmp_path / "s.json"), ttl_seconds=3600)
    llm = _RecordingLLM('["s1", "s2"]')
    articles = [_article("first"), _article("second")]

    first = summarize_articles(llm, "AAPL", articles, cache=cache)
    second = summarize_articles(llm, "AAPL", articles, cache=cache)

    assert first == second == ["s1", "s2"]
    assert llm.calls == 1


def test_summarize_articles_with_cache_only_summarizes_the_uncached_article(tmp_path):
    cache = JsonCache(str(tmp_path / "s.json"), ttl_seconds=3600)
    first_llm = _RecordingLLM('["s1"]')
    summarize_articles(first_llm, "AAPL", [_article("first")], cache=cache)

    second_llm = _RecordingLLM('["s2"]')
    result = summarize_articles(
        second_llm, "AAPL", [_article("first"), _article("second")], cache=cache
    )

    assert result == ["s1", "s2"]
    assert second_llm.calls == 1


def test_summarize_articles_cache_misses_when_body_changes(tmp_path):
    cache = JsonCache(str(tmp_path / "s.json"), ttl_seconds=3600)
    llm = _RecordingLLM('["s1"]')
    original = NewsArticle(ticker="AAPL", title="t", link="https://a/1", body="original body")
    summarize_articles(llm, "AAPL", [original], cache=cache)

    changed = NewsArticle(ticker="AAPL", title="t", link="https://a/1", body="updated body")
    summarize_articles(llm, "AAPL", [changed], cache=cache)

    assert llm.calls == 2


def test_summarize_company_with_cache_skips_llm_on_repeat_call(tmp_path):
    cache = JsonCache(str(tmp_path / "s.json"), ttl_seconds=3600)
    llm = _RecordingLLM("Company paragraph.")
    articles = [_article("first"), _article("second")]

    first = summarize_company(llm, "AAPL", articles, cache=cache)
    second = summarize_company(llm, "AAPL", articles, cache=cache)

    assert first == second == "Company paragraph."
    assert llm.calls == 1


def test_summarize_company_cache_misses_when_article_set_changes(tmp_path):
    cache = JsonCache(str(tmp_path / "s.json"), ttl_seconds=3600)
    llm = _RecordingLLM("Company paragraph.")

    summarize_company(llm, "AAPL", [_article("first")], cache=cache)
    summarize_company(llm, "AAPL", [_article("first"), _article("second")], cache=cache)

    assert llm.calls == 2