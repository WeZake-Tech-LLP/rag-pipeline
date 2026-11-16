from unittest.mock import MagicMock, patch
from ingest import format_ingest_reply, _find_platform_urls, _append_linked_content, extract_article


def test_format_ingest_reply_success():
    result = {"success": True, "duplicate": False, "chunks_stored": 6, "extraction_quality": "full_text", "url_type": "article"}
    reply = format_ingest_reply(result)
    assert "6" in reply and "article" in reply


def test_format_ingest_reply_duplicate():
    # ingest_url() actually returns success=False for duplicates (see ingest.py:573-577)
    result = {"success": False, "duplicate": True, "message": "URL already exists in knowledge base"}
    reply = format_ingest_reply(result)
    assert "already exists" in reply.lower()
    assert "Failed" not in reply


def test_format_ingest_reply_failure():
    result = {"success": False, "duplicate": False, "message": "Could not extract content: boom"}
    assert "boom" in format_ingest_reply(result)


def test_find_platform_urls_filters_out_article_links():
    text = (
        "See our FAQ at https://example.com/faq and the repo at "
        "https://github.com/pallets/flask for details."
    )
    assert _find_platform_urls(text) == ["https://github.com/pallets/flask"]


def test_find_platform_urls_returns_empty_list_when_no_platform_links():
    text = "Read more at https://example.com/related and https://example.com/about"
    assert _find_platform_urls(text) == []


def test_find_platform_urls_deduplicates_repeated_urls():
    text = (
        "Check https://github.com/pallets/flask now, and again: "
        "https://github.com/pallets/flask is great."
    )
    assert _find_platform_urls(text) == ["https://github.com/pallets/flask"]


def test_find_platform_urls_caps_at_max_links():
    text = (
        "https://github.com/a/a https://github.com/b/b "
        "https://github.com/c/c https://github.com/d/d https://github.com/e/e"
    )
    result = _find_platform_urls(text)
    assert len(result) == 4
    assert result == [
        "https://github.com/a/a",
        "https://github.com/b/b",
        "https://github.com/c/c",
        "https://github.com/d/d",
    ]


def test_find_platform_urls_respects_custom_max_links():
    text = "https://github.com/a/a https://github.com/b/b https://github.com/c/c"
    result = _find_platform_urls(text, max_links=2)
    assert result == ["https://github.com/a/a", "https://github.com/b/b"]


def test_append_linked_content_adds_section_per_url():
    text = "Article body mentions https://github.com/pallets/flask."
    with patch("ingest._fetch_linked_content", return_value="Flask README text") as mock_fetch:
        result = _append_linked_content(text)
    mock_fetch.assert_called_once_with("https://github.com/pallets/flask")
    assert text in result
    assert "Linked Content: https://github.com/pallets/flask" in result
    assert "Flask README text" in result


def test_append_linked_content_returns_text_unchanged_when_no_platform_links():
    text = "Just a plain article with https://example.com/related in it."
    with patch("ingest._fetch_linked_content") as mock_fetch:
        result = _append_linked_content(text)
    mock_fetch.assert_not_called()
    assert result == text


def test_append_linked_content_skips_section_when_fetch_returns_none():
    text = "A share-button link: https://twitter.com/intent/tweet?text=hi"
    with patch("ingest._fetch_linked_content", return_value=None) as mock_fetch:
        result = _append_linked_content(text)
    mock_fetch.assert_called_once()
    assert result == text


def test_append_linked_content_adds_one_section_per_distinct_url():
    text = "See https://github.com/a/a and https://github.com/b/b"
    with patch("ingest._fetch_linked_content", side_effect=["A content", "B content"]) as mock_fetch:
        result = _append_linked_content(text)
    assert mock_fetch.call_count == 2
    assert "A content" in result and "B content" in result


def test_extract_article_appends_linked_content_on_jina_success():
    jina_response = MagicMock(status_code=200, text="x" * 400)
    with patch("ingest.requests.get", return_value=jina_response), \
         patch("ingest._append_linked_content", return_value="EXPANDED") as mock_append:
        text, quality, error = extract_article("https://example.com/post")
    mock_append.assert_called_once_with("x" * 400)
    assert text == "EXPANDED"
    assert quality == "full_text"
    assert error is None


def test_extract_article_appends_linked_content_on_beautifulsoup_fallback():
    jina_response = MagicMock(status_code=500, text="error")
    html = "<html><body><article><p>" + ("y" * 250) + "</p></article></body></html>"
    fallback_response = MagicMock(status_code=200, text=html)
    with patch("ingest.requests.get", side_effect=[jina_response, fallback_response]), \
         patch("ingest._append_linked_content", return_value="EXPANDED") as mock_append:
        text, quality, error = extract_article("https://example.com/post")
    mock_append.assert_called_once()
    assert mock_append.call_args.args[0].strip() == "y" * 250
    assert text == "EXPANDED"
    assert quality == "full_text"
