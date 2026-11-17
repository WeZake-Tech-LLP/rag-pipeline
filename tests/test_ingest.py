from unittest.mock import MagicMock, patch
from ingest import (
    format_ingest_reply,
    _find_platform_urls,
    _append_linked_content,
    extract_article,
    extract_linkedin,
    extract_facebook,
    extract_instagram,
    _fetch_linked_content,
)


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


def test_find_platform_urls_excludes_substring_false_positives():
    # "x.com" is a substring of "dropbox.com"/"vox.com" — a naive
    # substring check on detect_url_type's domain list would wrongly
    # classify these as X/Twitter links.
    text = (
        "Backup your files at https://www.dropbox.com/s/abc123/file.pdf, "
        "read the news at https://www.vox.com/politics/123, "
        "or check the repo at https://github.com/real/repo"
    )
    assert _find_platform_urls(text) == ["https://github.com/real/repo"]


def test_find_platform_urls_excludes_share_buttons():
    text = (
        "Share: https://twitter.com/intent/tweet?text=hi "
        "https://www.facebook.com/sharer/sharer.php?u=x "
        "https://www.linkedin.com/shareArticle?url=x "
        "https://www.reddit.com/submit?url=x "
        "Repo: https://github.com/real/repo"
    )
    assert _find_platform_urls(text) == ["https://github.com/real/repo"]


def test_find_platform_urls_handles_markdown_link_syntax():
    text = "**[Flask](https://github.com/pallets/flask)** is great"
    assert _find_platform_urls(text) == ["https://github.com/pallets/flask"]


def test_find_platform_urls_handles_adjacent_markdown_links():
    text = "[Home](https://example.com/)[Repo](https://github.com/pallets/flask)"
    assert _find_platform_urls(text) == ["https://github.com/pallets/flask"]


def test_find_platform_urls_ignores_image_markdown_links():
    text = (
        "![Image 1: thumb](https://img.youtube.com/vi/dQw4w9WgXcQ/0.jpg) "
        "Check this repo: https://github.com/pallets/flask"
    )
    assert _find_platform_urls(text) == ["https://github.com/pallets/flask"]


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
    # A real platform link whose fetch fails (e.g. a 404) still counts
    # against the cap but contributes no section — distinct from a
    # share-button link, which is now filtered out before any fetch
    # is attempted (see test_find_platform_urls_excludes_share_buttons).
    text = "A broken repo link: https://github.com/does-not/exist"
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


def test_find_platform_urls_excludes_hosts_in_exclude_set():
    text = "See https://www.linkedin.com/posts/other-person_123 and https://github.com/real/repo"
    result = _find_platform_urls(text, exclude_hosts=frozenset({"linkedin.com"}))
    assert result == ["https://github.com/real/repo"]


def test_find_platform_urls_exclude_hosts_matches_www_subdomain():
    text = "https://www.linkedin.com/feed/update/123 https://github.com/real/repo"
    result = _find_platform_urls(text, exclude_hosts=frozenset({"linkedin.com"}))
    assert result == ["https://github.com/real/repo"]


def test_find_platform_urls_excludes_short_link_form():
    text = "https://lnkd.in/abc123 https://github.com/real/repo"
    result = _find_platform_urls(text, exclude_hosts=frozenset({"linkedin.com", "lnkd.in"}))
    assert result == ["https://github.com/real/repo"]


def test_append_linked_content_passes_exclude_hosts_through():
    text = "See https://www.linkedin.com/posts/other-person_123 and https://github.com/real/repo"
    with patch("ingest._fetch_linked_content", return_value="Flask README text") as mock_fetch:
        result = _append_linked_content(text, exclude_hosts=frozenset({"linkedin.com"}))
    mock_fetch.assert_called_once_with("https://github.com/real/repo")
    assert "Flask README text" in result


def test_extract_linkedin_excludes_links_to_other_linkedin_posts():
    jina_response = MagicMock(status_code=200, text=(
        "x" * 250 + " https://www.linkedin.com/posts/other-person_123 "
        "https://github.com/real/repo"
    ))
    with patch("ingest.requests.get", return_value=jina_response), \
         patch("ingest._fetch_linked_content", return_value="Flask README text") as mock_fetch:
        text, quality, error = extract_linkedin("https://www.linkedin.com/posts/my-post_456")
    mock_fetch.assert_called_once_with("https://github.com/real/repo")
    assert "Flask README text" in text


def test_extract_facebook_excludes_links_to_other_facebook_posts():
    jina_response = MagicMock(status_code=200, text=(
        "x" * 250 + " https://www.facebook.com/someone/posts/789 "
        "https://github.com/real/repo"
    ))
    with patch("ingest.requests.get", return_value=jina_response), \
         patch("ingest._fetch_linked_content", return_value="Flask README text") as mock_fetch:
        text, quality, error = extract_facebook("https://www.facebook.com/someone/posts/123")
    mock_fetch.assert_called_once_with("https://github.com/real/repo")
    assert "Flask README text" in text


def test_extract_instagram_excludes_links_to_other_instagram_posts():
    jina_response = MagicMock(status_code=200, text=(
        "x" * 250 + " https://www.instagram.com/p/other123/ "
        "https://github.com/real/repo"
    ))
    with patch("ingest.requests.get", return_value=jina_response), \
         patch("ingest._fetch_linked_content", return_value="Flask README text") as mock_fetch:
        text, quality, error = extract_instagram("https://www.instagram.com/p/my456/")
    mock_fetch.assert_called_once_with("https://github.com/real/repo")
    assert "Flask README text" in text


def test_extract_via_jina_or_meta_applies_link_following_on_meta_fallback():
    jina_response = MagicMock(status_code=500, text="error")
    html = (
        '<html><head><meta property="og:title" content="A LinkedIn Post">'
        '<meta property="og:description" content="' + ("y" * 60) + '"></head></html>'
    )
    fallback_response = MagicMock(status_code=200, text=html)
    with patch("ingest.requests.get", side_effect=[jina_response, fallback_response]), \
         patch("ingest._append_linked_content", return_value="EXPANDED") as mock_append:
        text, quality, error = extract_linkedin("https://www.linkedin.com/posts/my-post_456")
    mock_append.assert_called_once()
    assert mock_append.call_args.kwargs.get("exclude_hosts") == frozenset({"linkedin.com", "lnkd.in"})
    assert text == "EXPANDED"
    assert quality == "meta_only"


def test_extract_article_does_not_follow_links_when_follow_links_false():
    jina_response = MagicMock(status_code=200, text="x" * 400 + " https://github.com/real/repo")
    with patch("ingest.requests.get", return_value=jina_response), \
         patch("ingest._fetch_linked_content") as mock_fetch:
        text, quality, error = extract_article("https://example.com/post", follow_links=False)
    mock_fetch.assert_not_called()


def test_extract_linkedin_does_not_follow_links_when_follow_links_false():
    jina_response = MagicMock(status_code=200, text="x" * 250 + " https://github.com/real/repo")
    with patch("ingest.requests.get", return_value=jina_response), \
         patch("ingest._fetch_linked_content") as mock_fetch:
        text, quality, error = extract_linkedin("https://www.linkedin.com/posts/my-post_456", follow_links=False)
    mock_fetch.assert_not_called()


def test_extract_facebook_does_not_follow_links_when_follow_links_false():
    jina_response = MagicMock(status_code=200, text="x" * 250 + " https://github.com/real/repo")
    with patch("ingest.requests.get", return_value=jina_response), \
         patch("ingest._fetch_linked_content") as mock_fetch:
        text, quality, error = extract_facebook("https://www.facebook.com/someone/posts/123", follow_links=False)
    mock_fetch.assert_not_called()


def test_extract_instagram_does_not_follow_links_when_follow_links_false():
    jina_response = MagicMock(status_code=200, text="x" * 250 + " https://github.com/real/repo")
    with patch("ingest.requests.get", return_value=jina_response), \
         patch("ingest._fetch_linked_content") as mock_fetch:
        text, quality, error = extract_instagram("https://www.instagram.com/p/my456/", follow_links=False)
    mock_fetch.assert_not_called()


def test_fetch_linked_content_does_not_recurse_through_article():
    jina_response = MagicMock(status_code=200, text="x" * 400)
    with patch("ingest.requests.get", return_value=jina_response), \
         patch("ingest._append_linked_content") as mock_append:
        _fetch_linked_content("https://example.com/post")
    mock_append.assert_not_called()


def test_fetch_linked_content_does_not_recurse_through_linkedin():
    jina_response = MagicMock(status_code=200, text="x" * 250)
    with patch("ingest.requests.get", return_value=jina_response), \
         patch("ingest._append_linked_content") as mock_append:
        _fetch_linked_content("https://www.linkedin.com/posts/abc")
    mock_append.assert_not_called()


def test_fetch_linked_content_does_not_recurse_through_facebook():
    jina_response = MagicMock(status_code=200, text="x" * 250)
    with patch("ingest.requests.get", return_value=jina_response), \
         patch("ingest._append_linked_content") as mock_append:
        _fetch_linked_content("https://www.facebook.com/someone/posts/123")
    mock_append.assert_not_called()


def test_fetch_linked_content_does_not_recurse_through_instagram():
    jina_response = MagicMock(status_code=200, text="x" * 250)
    with patch("ingest.requests.get", return_value=jina_response), \
         patch("ingest._append_linked_content") as mock_append:
        _fetch_linked_content("https://www.instagram.com/p/my456/")
    mock_append.assert_not_called()


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


def test_extract_article_follows_href_links_in_beautifulsoup_fallback():
    # get_text() throws away <a href="..."> attributes, so a link that's
    # only reachable via markup (not visible as a bare URL in the text)
    # must still be found and followed on the fallback path.
    jina_response = MagicMock(status_code=500, text="error")
    html = (
        "<html><body><article><p>" + ("y" * 250) + "</p>"
        '<a href="https://github.com/pallets/flask">Flask</a>'
        "</article></body></html>"
    )
    fallback_response = MagicMock(status_code=200, text=html)
    with patch("ingest.requests.get", side_effect=[jina_response, fallback_response]), \
         patch("ingest._fetch_linked_content", return_value="Flask README text") as mock_fetch:
        text, quality, error = extract_article("https://example.com/post")
    mock_fetch.assert_called_once_with("https://github.com/pallets/flask")
    assert "Linked Content: https://github.com/pallets/flask" in text
    assert "Flask README text" in text
