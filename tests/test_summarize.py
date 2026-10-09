from yahoofinance_newsmcp.summarize import (
    build_article_prompt,
    build_company_prompt,
    build_overall_prompt,
    parse_article_summaries,
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