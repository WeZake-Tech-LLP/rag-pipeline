from ingest import format_ingest_reply, _find_platform_urls


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
