from unittest.mock import MagicMock, patch
from ingest import (
    format_ingest_reply,
    _find_platform_urls,
    _append_linked_content,
    extract_article,
    extract_linkedin,
    extract_facebook,
    extract_instagram,
    extract_x,
    extract_reddit,
    extract_github,
    extract_youtube,
    _fetch_linked_content,
    _resolve_redirector,
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


def test_resolve_redirector_returns_unchanged_for_non_redirector_host():
    assert _resolve_redirector("https://github.com/real/repo") == "https://github.com/real/repo"


def test_resolve_redirector_decodes_facebook_link_wrapper():
    wrapped = "https://l.facebook.com/l.php?u=https%3A%2F%2Fgithub.com%2Freal%2Frepo&h=abc"
    assert _resolve_redirector(wrapped) == "https://github.com/real/repo"


def test_resolve_redirector_does_not_double_decode_facebook_wrapper():
    # parse_qs already percent-decodes the query value once; a second
    # unquote() wrongly decodes an already-correct %26 (a literal "&"
    # inside the real URL's own query string) into a bare "&", which
    # changes how the resulting URL's query string parses.
    wrapped = "https://l.facebook.com/l.php?u=https%3A%2F%2Fgithub.com%2Fa%2Fb%3Fq%3Dx%2526y&h=abc"
    assert _resolve_redirector(wrapped) == "https://github.com/a/b?q=x%26y"


def test_resolve_redirector_decodes_instagram_link_wrapper():
    wrapped = "https://l.instagram.com/?u=https%3A%2F%2Fgithub.com%2Freal%2Frepo&e=abc"
    assert _resolve_redirector(wrapped) == "https://github.com/real/repo"


def test_resolve_redirector_follows_network_redirect_for_tco():
    fake_response = MagicMock()
    fake_response.url = "https://github.com/real/repo"
    fake_response.close = MagicMock()
    with patch("ingest.requests.get", return_value=fake_response) as mock_get:
        result = _resolve_redirector("https://t.co/abc123")
    mock_get.assert_called_once()
    assert result == "https://github.com/real/repo"


def test_resolve_redirector_decodes_linkedin_safety_go_interstitial():
    wrapped = "https://www.linkedin.com/safety/go?url=https%3A%2F%2Fnytimes.com%2Farticle&urlhash=abc"
    assert _resolve_redirector(wrapped) == "https://nytimes.com/article"


def test_resolve_redirector_decodes_safety_go_reached_via_lnkdin_redirect():
    fake_response = MagicMock()
    fake_response.url = "https://www.linkedin.com/safety/go?url=https%3A%2F%2Fnytimes.com%2Farticle&urlhash=abc"
    fake_response.close = MagicMock()
    with patch("ingest.requests.get", return_value=fake_response) as mock_get:
        result = _resolve_redirector("https://lnkd.in/abc123")
    mock_get.assert_called_once()
    assert result == "https://nytimes.com/article"


def test_resolve_redirector_degrades_safely_on_network_failure():
    with patch("ingest.requests.get", side_effect=Exception("boom")):
        result = _resolve_redirector("https://t.co/abc123")
    assert result == "https://t.co/abc123"


def test_find_platform_urls_does_not_call_network_for_non_wrapper_urls():
    text = "https://github.com/real/repo https://www.youtube.com/watch?v=abc"
    with patch("ingest.requests.get") as mock_get:
        result = _find_platform_urls(text)
    mock_get.assert_not_called()
    assert result == ["https://github.com/real/repo", "https://www.youtube.com/watch?v=abc"]


def test_find_platform_urls_excludes_short_link_resolving_to_same_platform():
    fake_response = MagicMock()
    fake_response.url = "https://www.linkedin.com/posts/other-person_123"
    fake_response.close = MagicMock()
    with patch("ingest.requests.get", return_value=fake_response):
        text = "https://lnkd.in/abc123 https://github.com/real/repo"
        result = _find_platform_urls(text, exclude_hosts=frozenset({"linkedin.com", "lnkd.in"}))
    assert result == ["https://github.com/real/repo"]


def test_find_platform_urls_follows_short_link_resolving_to_different_platform():
    fake_response = MagicMock()
    fake_response.url = "https://github.com/real/repo"
    fake_response.close = MagicMock()
    with patch("ingest.requests.get", return_value=fake_response):
        text = "https://lnkd.in/abc123"
        result = _find_platform_urls(text, exclude_hosts=frozenset({"linkedin.com", "lnkd.in"}))
    assert result == ["https://github.com/real/repo"]


def test_find_platform_urls_caches_duplicate_wrapper_resolutions():
    fake_response = MagicMock()
    fake_response.url = "https://github.com/real/repo"
    fake_response.close = MagicMock()
    with patch("ingest.requests.get", return_value=fake_response) as mock_get:
        text = "https://t.co/abc123 https://t.co/abc123 https://t.co/abc123"
        result = _find_platform_urls(text)
    assert mock_get.call_count == 1
    assert result == ["https://github.com/real/repo"]


def test_find_platform_urls_caps_total_wrapper_resolution_attempts():
    responses = []
    for i in range(20):
        r = MagicMock()
        r.url = f"https://example.com/{i}"
        r.close = MagicMock()
        responses.append(r)
    with patch("ingest.requests.get", side_effect=responses) as mock_get:
        text = " ".join(f"https://t.co/link{i}" for i in range(20))
        result = _find_platform_urls(text)
    assert mock_get.call_count <= 8
    assert result == []


def test_find_platform_urls_allow_any_host_includes_non_platform_links():
    text = "https://example.com/faq https://nytimes.com/2026/article"
    assert _find_platform_urls(text) == []
    assert _find_platform_urls(text, allow_any_host=True) == [
        "https://example.com/faq",
        "https://nytimes.com/2026/article",
    ]


def test_find_platform_urls_allow_any_host_still_excludes_share_buttons():
    text = "https://twitter.com/intent/tweet?text=hi https://nytimes.com/2026/article"
    result = _find_platform_urls(text, allow_any_host=True)
    assert result == ["https://nytimes.com/2026/article"]


def test_find_platform_urls_allow_any_host_still_excludes_same_platform():
    text = "https://x.com/other/status/999 https://nytimes.com/2026/article"
    result = _find_platform_urls(
        text, allow_any_host=True, exclude_hosts=frozenset({"x.com", "twitter.com"})
    )
    assert result == ["https://nytimes.com/2026/article"]


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


def test_extract_linkedin_follows_link_to_a_plain_article():
    jina_response = MagicMock(status_code=200, text="x" * 250 + " https://www.nytimes.com/2026/article")
    with patch("ingest.requests.get", return_value=jina_response), \
         patch("ingest._fetch_linked_content", return_value="Article text") as mock_fetch:
        text, quality, error = extract_linkedin("https://www.linkedin.com/posts/my-post_456")
    mock_fetch.assert_called_once_with("https://www.nytimes.com/2026/article")
    assert "Article text" in text


def test_extract_facebook_follows_link_to_a_plain_article():
    jina_response = MagicMock(status_code=200, text="x" * 250 + " https://www.theverge.com/2026/article")
    with patch("ingest.requests.get", return_value=jina_response), \
         patch("ingest._fetch_linked_content", return_value="Article text") as mock_fetch:
        text, quality, error = extract_facebook("https://www.facebook.com/someone/posts/123")
    mock_fetch.assert_called_once_with("https://www.theverge.com/2026/article")
    assert "Article text" in text


def test_extract_instagram_follows_link_to_a_plain_article():
    jina_response = MagicMock(status_code=200, text="x" * 250 + " https://www.theverge.com/2026/article")
    with patch("ingest.requests.get", return_value=jina_response), \
         patch("ingest._fetch_linked_content", return_value="Article text") as mock_fetch:
        text, quality, error = extract_instagram("https://www.instagram.com/p/my456/")
    mock_fetch.assert_called_once_with("https://www.theverge.com/2026/article")
    assert "Article text" in text


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


def _github_responses(readme_text):
    import base64
    repo_response = MagicMock(status_code=200)
    repo_response.json.return_value = {
        "full_name": "real/repo", "description": "desc", "topics": [], "stargazers_count": 5,
    }
    readme_response = MagicMock(status_code=200)
    readme_response.json.return_value = {"content": base64.b64encode(readme_text.encode()).decode()}
    return repo_response, readme_response


def test_extract_github_follows_link_in_readme():
    repo_response, readme_response = _github_responses("See our docs at https://nytimes.com/2026/article")
    with patch("ingest.requests.get", side_effect=[repo_response, readme_response]), \
         patch("ingest._fetch_linked_content", return_value="Article text") as mock_fetch:
        text, quality, error = extract_github("https://github.com/real/repo")
    mock_fetch.assert_called_once_with("https://nytimes.com/2026/article")
    assert "Article text" in text


def test_extract_github_excludes_links_to_other_github_repos():
    repo_response, readme_response = _github_responses("Fork of https://github.com/other/repo")
    with patch("ingest.requests.get", side_effect=[repo_response, readme_response]), \
         patch("ingest._fetch_linked_content") as mock_fetch:
        text, quality, error = extract_github("https://github.com/real/repo")
    mock_fetch.assert_not_called()


def test_extract_github_does_not_follow_links_when_follow_links_false():
    repo_response, readme_response = _github_responses("See our docs at https://nytimes.com/2026/article")
    with patch("ingest.requests.get", side_effect=[repo_response, readme_response]), \
         patch("ingest._fetch_linked_content") as mock_fetch:
        text, quality, error = extract_github("https://github.com/real/repo", follow_links=False)
    mock_fetch.assert_not_called()


def test_fetch_linked_content_does_not_recurse_through_github():
    repo_response, readme_response = _github_responses("x")
    with patch("ingest.requests.get", side_effect=[repo_response, readme_response]), \
         patch("ingest._append_linked_content") as mock_append:
        _fetch_linked_content("https://github.com/real/repo")
    mock_append.assert_not_called()


def _youtube_description_fallback_mocks(description):
    mock_ydl = MagicMock()
    mock_ydl.__enter__.return_value = mock_ydl
    mock_ydl.extract_info.return_value = {"description": description, "title": "A video"}
    return mock_ydl


def test_extract_youtube_follows_link_in_description_fallback():
    # Strategy 1 (youtube_transcript_api) is forced to fail explicitly —
    # the installed version happens to lack list_transcripts entirely, but
    # the test must not silently depend on that library bug staying put.
    mock_ydl = _youtube_description_fallback_mocks(
        "Check out the full write-up at https://nytimes.com/2026/article " + "x" * 200
    )
    with patch(
             "youtube_transcript_api.YouTubeTranscriptApi.list_transcripts",
             side_effect=Exception("strategy 1 forced to fail"),
             create=True,
         ), \
         patch("ingest.requests.get", side_effect=Exception("jina failed")), \
         patch("glob.glob", return_value=[]), \
         patch("yt_dlp.YoutubeDL", return_value=mock_ydl), \
         patch("ingest._fetch_linked_content", return_value="Article text") as mock_fetch:
        text, quality, error = extract_youtube("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    mock_fetch.assert_called_once_with("https://nytimes.com/2026/article")
    assert "Article text" in text
    assert quality == "yt_dlp_meta"


def test_extract_youtube_does_not_follow_links_when_follow_links_false():
    mock_ydl = _youtube_description_fallback_mocks(
        "Check out the full write-up at https://nytimes.com/2026/article " + "x" * 200
    )
    with patch(
             "youtube_transcript_api.YouTubeTranscriptApi.list_transcripts",
             side_effect=Exception("strategy 1 forced to fail"),
             create=True,
         ), \
         patch("ingest.requests.get", side_effect=Exception("jina failed")), \
         patch("glob.glob", return_value=[]), \
         patch("yt_dlp.YoutubeDL", return_value=mock_ydl), \
         patch("ingest._fetch_linked_content") as mock_fetch:
        text, quality, error = extract_youtube(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ", follow_links=False
        )
    mock_fetch.assert_not_called()


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


def test_extract_x_follows_tco_link_resolved_to_github():
    jina_response = MagicMock(status_code=200, text="x" * 250 + " https://t.co/abc123")
    resolved_response = MagicMock()
    resolved_response.url = "https://github.com/real/repo"
    resolved_response.close = MagicMock()
    with patch("ingest.requests.get", side_effect=[jina_response, resolved_response]), \
         patch("ingest._fetch_linked_content", return_value="Flask README text") as mock_fetch:
        text, quality, error = extract_x("https://x.com/user/status/123")
    mock_fetch.assert_called_once_with("https://github.com/real/repo")
    assert "Flask README text" in text


def test_extract_x_follows_multiple_tco_links():
    jina_response = MagicMock(
        status_code=200, text="x" * 250 + " https://t.co/abc123 https://t.co/def456"
    )
    resolved_github = MagicMock()
    resolved_github.url = "https://github.com/real/repo"
    resolved_github.close = MagicMock()
    resolved_youtube = MagicMock()
    resolved_youtube.url = "https://www.youtube.com/watch?v=abc"
    resolved_youtube.close = MagicMock()
    with patch("ingest.requests.get", side_effect=[jina_response, resolved_github, resolved_youtube]), \
         patch("ingest._fetch_linked_content", side_effect=["Flask README text", "Video transcript"]) as mock_fetch:
        text, quality, error = extract_x("https://x.com/user/status/123")
    assert mock_fetch.call_count == 2
    assert "Flask README text" in text and "Video transcript" in text


def test_extract_x_still_follows_the_link_that_resolves_when_another_fails():
    jina_response = MagicMock(
        status_code=200, text="x" * 250 + " https://t.co/abc123 https://t.co/def456"
    )
    resolved_github = MagicMock()
    resolved_github.url = "https://github.com/real/repo"
    resolved_github.close = MagicMock()
    with patch(
        "ingest.requests.get",
        side_effect=[jina_response, Exception("resolution timed out"), resolved_github],
    ), patch("ingest._fetch_linked_content", return_value="Flask README text") as mock_fetch:
        text, quality, error = extract_x("https://x.com/user/status/123")
    mock_fetch.assert_called_once_with("https://github.com/real/repo")
    assert "Flask README text" in text


def test_extract_x_follows_tco_link_resolved_to_a_plain_article():
    # The single most common real-world case: a tweet sharing a news
    # article. The old code followed any resolved destination; the
    # shared platform-only pipeline must not narrow that away.
    jina_response = MagicMock(status_code=200, text="x" * 250 + " https://t.co/abc123")
    resolved_response = MagicMock()
    resolved_response.url = "https://www.nytimes.com/2026/article"
    resolved_response.close = MagicMock()
    with patch("ingest.requests.get", side_effect=[jina_response, resolved_response]), \
         patch("ingest._fetch_linked_content", return_value="Article text") as mock_fetch:
        text, quality, error = extract_x("https://x.com/user/status/123")
    mock_fetch.assert_called_once_with("https://www.nytimes.com/2026/article")
    assert "Article text" in text


def test_extract_x_excludes_links_to_other_x_posts():
    jina_response = MagicMock(status_code=200, text="x" * 250 + " https://t.co/abc123")
    resolved_response = MagicMock()
    resolved_response.url = "https://x.com/other/status/999"
    resolved_response.close = MagicMock()
    with patch("ingest.requests.get", side_effect=[jina_response, resolved_response]), \
         patch("ingest._fetch_linked_content") as mock_fetch:
        text, quality, error = extract_x("https://x.com/user/status/123")
    mock_fetch.assert_not_called()


def test_extract_x_does_not_follow_links_when_follow_links_false():
    jina_response = MagicMock(status_code=200, text="x" * 250 + " https://t.co/abc123")
    with patch("ingest.requests.get", return_value=jina_response), \
         patch("ingest._fetch_linked_content") as mock_fetch:
        text, quality, error = extract_x("https://x.com/user/status/123", follow_links=False)
    mock_fetch.assert_not_called()


_REDDIT_ATOM_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Test Post Title</title>
  <entry>
    <author><name>poster</name></author>
    <content type="html">Check this out: https://github.com/real/repo</content>
  </entry>
</feed>"""


def test_extract_reddit_follows_links_found_in_post_or_comments():
    resolve_response = MagicMock()
    resolve_response.url = "https://www.reddit.com/r/test/comments/abc/title"
    rss_response = MagicMock(status_code=200, content=_REDDIT_ATOM_XML.encode())
    with patch("ingest.requests.get", side_effect=[resolve_response, rss_response]), \
         patch("ingest._throttle_reddit_request"), \
         patch("ingest._fetch_linked_content", return_value="Flask README text") as mock_fetch:
        text, quality, error = extract_reddit("https://www.reddit.com/r/test/comments/abc/title")
    mock_fetch.assert_called_once_with("https://github.com/real/repo")
    assert "Flask README text" in text


def test_extract_reddit_excludes_links_to_other_reddit_posts():
    xml = _REDDIT_ATOM_XML.replace(
        "https://github.com/real/repo", "https://www.reddit.com/r/test/comments/other/post"
    )
    resolve_response = MagicMock()
    resolve_response.url = "https://www.reddit.com/r/test/comments/abc/title"
    rss_response = MagicMock(status_code=200, content=xml.encode())
    with patch("ingest.requests.get", side_effect=[resolve_response, rss_response]), \
         patch("ingest._throttle_reddit_request"), \
         patch("ingest._fetch_linked_content") as mock_fetch:
        text, quality, error = extract_reddit("https://www.reddit.com/r/test/comments/abc/title")
    mock_fetch.assert_not_called()


def test_extract_reddit_does_not_follow_links_when_follow_links_false():
    resolve_response = MagicMock()
    resolve_response.url = "https://www.reddit.com/r/test/comments/abc/title"
    rss_response = MagicMock(status_code=200, content=_REDDIT_ATOM_XML.encode())
    with patch("ingest.requests.get", side_effect=[resolve_response, rss_response]), \
         patch("ingest._throttle_reddit_request"), \
         patch("ingest._fetch_linked_content") as mock_fetch:
        text, quality, error = extract_reddit(
            "https://www.reddit.com/r/test/comments/abc/title", follow_links=False
        )
    mock_fetch.assert_not_called()


_REDDIT_ATOM_XML_LINK_IN_COMMENT = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Test Post Title</title>
  <entry>
    <author><name>poster</name></author>
    <content type="html">Just a plain post with no links.</content>
  </entry>
  <entry>
    <author><name>commenter</name></author>
    <content type="html">Check this out: https://github.com/real/repo</content>
  </entry>
</feed>"""


def test_extract_reddit_follows_link_found_only_in_a_comment():
    resolve_response = MagicMock()
    resolve_response.url = "https://www.reddit.com/r/test/comments/abc/title"
    rss_response = MagicMock(status_code=200, content=_REDDIT_ATOM_XML_LINK_IN_COMMENT.encode())
    with patch("ingest.requests.get", side_effect=[resolve_response, rss_response]), \
         patch("ingest._throttle_reddit_request"), \
         patch("ingest._fetch_linked_content", return_value="Flask README text") as mock_fetch:
        text, quality, error = extract_reddit("https://www.reddit.com/r/test/comments/abc/title")
    mock_fetch.assert_called_once_with("https://github.com/real/repo")
    assert "Flask README text" in text


def test_extract_reddit_excludes_short_link_resolving_to_another_reddit_post():
    # Old _find_external_url only ever excluded a URL whose literal
    # string already contained "reddit.com"/"redd.it" — a wrapped link
    # (e.g. a t.co/lnkd.in short link) that only resolves to a reddit.com
    # destination would have slipped past that check entirely.
    xml = _REDDIT_ATOM_XML.replace(
        "https://github.com/real/repo", "https://t.co/xyz789"
    )
    resolve_response = MagicMock()
    resolve_response.url = "https://www.reddit.com/r/test/comments/abc/title"
    rss_response = MagicMock(status_code=200, content=xml.encode())
    tco_resolve_response = MagicMock()
    tco_resolve_response.url = "https://www.reddit.com/r/test/comments/other/post"
    tco_resolve_response.close = MagicMock()
    with patch("ingest.requests.get", side_effect=[resolve_response, rss_response, tco_resolve_response]), \
         patch("ingest._throttle_reddit_request"), \
         patch("ingest._fetch_linked_content") as mock_fetch:
        text, quality, error = extract_reddit("https://www.reddit.com/r/test/comments/abc/title")
    mock_fetch.assert_not_called()


def test_extract_reddit_follows_link_to_a_plain_article():
    # The single most common real-world case for a Reddit link-post:
    # a bare link to a news/blog article. The old code followed any
    # non-reddit URL; the shared platform-only pipeline must not
    # narrow that away.
    xml = _REDDIT_ATOM_XML.replace(
        "https://github.com/real/repo", "https://www.theverge.com/2026/article"
    )
    resolve_response = MagicMock()
    resolve_response.url = "https://www.reddit.com/r/test/comments/abc/title"
    rss_response = MagicMock(status_code=200, content=xml.encode())
    with patch("ingest.requests.get", side_effect=[resolve_response, rss_response]), \
         patch("ingest._throttle_reddit_request"), \
         patch("ingest._fetch_linked_content", return_value="Article text") as mock_fetch:
        text, quality, error = extract_reddit("https://www.reddit.com/r/test/comments/abc/title")
    mock_fetch.assert_called_once_with("https://www.theverge.com/2026/article")
    assert "Article text" in text


_REDDIT_ATOM_XML_HREF_ONLY_LINK = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Test Post Title</title>
  <entry>
    <author><name>poster</name></author>
    <content type="html">Check out &lt;a href="https://nytimes.com/2026/article"&gt;this write-up&lt;/a&gt; I found.</content>
  </entry>
</feed>"""


def test_extract_reddit_follows_hyperlinked_text_link_with_no_bare_url():
    # _clean_html's get_text() discards <a href> targets, keeping only
    # the link's visible text ("this write-up") — a link that's never
    # pasted as a bare URL would otherwise be invisible to the scanner.
    resolve_response = MagicMock()
    resolve_response.url = "https://www.reddit.com/r/test/comments/abc/title"
    rss_response = MagicMock(status_code=200, content=_REDDIT_ATOM_XML_HREF_ONLY_LINK.encode())
    with patch("ingest.requests.get", side_effect=[resolve_response, rss_response]), \
         patch("ingest._throttle_reddit_request"), \
         patch("ingest._fetch_linked_content", return_value="Article text") as mock_fetch:
        text, quality, error = extract_reddit("https://www.reddit.com/r/test/comments/abc/title")
    mock_fetch.assert_called_once_with("https://nytimes.com/2026/article")
    assert "Article text" in text
    assert "https://nytimes.com/2026/article" not in text.split("Linked Content:")[0]


_REDDIT_ATOM_XML_HREF_ONLY_IN_COMMENT = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Test Post Title</title>
  <entry>
    <author><name>poster</name></author>
    <content type="html">Just a plain post with no links.</content>
  </entry>
  <entry>
    <author><name>commenter</name></author>
    <content type="html">See &lt;a href="https://nytimes.com/2026/article"&gt;here&lt;/a&gt;.</content>
  </entry>
</feed>"""


def test_extract_reddit_follows_hyperlinked_text_link_found_only_in_a_comment():
    resolve_response = MagicMock()
    resolve_response.url = "https://www.reddit.com/r/test/comments/abc/title"
    rss_response = MagicMock(status_code=200, content=_REDDIT_ATOM_XML_HREF_ONLY_IN_COMMENT.encode())
    with patch("ingest.requests.get", side_effect=[resolve_response, rss_response]), \
         patch("ingest._throttle_reddit_request"), \
         patch("ingest._fetch_linked_content", return_value="Article text") as mock_fetch:
        text, quality, error = extract_reddit("https://www.reddit.com/r/test/comments/abc/title")
    mock_fetch.assert_called_once_with("https://nytimes.com/2026/article")
    assert "Article text" in text


def test_find_platform_urls_skips_badge_and_cdn_noise_hosts():
    text = (
        "[![Build](https://img.shields.io/badge.svg)](https://travis-ci.com/real/repo) "
        '<img src="https://raw.githubusercontent.com/real/repo/main/logo.png"> '
        "Docs: https://proj.readthedocs.io/"
    )
    result = _find_platform_urls(text, exclude_hosts=frozenset({"github.com"}), allow_any_host=True)
    assert result == ["https://proj.readthedocs.io/"]


def test_find_platform_urls_skips_bare_social_profile_links():
    text = (
        "Sponsored by https://www.patreon.com/mychannel and "
        "follow https://twitter.com/mychannel — full paper: "
        "https://arxiv.org/abs/1234.5678"
    )
    result = _find_platform_urls(text, allow_any_host=True)
    assert result == ["https://arxiv.org/abs/1234.5678"]


def test_find_platform_urls_still_follows_real_social_posts_not_just_profiles():
    # A profile link (one path segment) is noise; a post/status link
    # (multiple segments) is real content and must still be followed.
    text = "https://twitter.com/mychannel/status/42"
    result = _find_platform_urls(text, allow_any_host=True)
    assert result == ["https://twitter.com/mychannel/status/42"]


def test_extract_github_prefers_docs_link_over_badge_and_cdn_noise():
    readme = (
        "[![Build](https://img.shields.io/badge.svg)](https://travis-ci.com/real/repo)\n"
        '<img src="https://raw.githubusercontent.com/real/repo/main/logo.png">\n'
        "Docs: https://proj.readthedocs.io/"
    )
    repo_response, readme_response = _github_responses(readme)
    with patch("ingest.requests.get", side_effect=[repo_response, readme_response]), \
         patch("ingest._fetch_linked_content", return_value="Docs text") as mock_fetch:
        text, quality, error = extract_github("https://github.com/real/repo")
    mock_fetch.assert_called_once_with("https://proj.readthedocs.io/")
    assert "Docs text" in text


def test_extract_youtube_description_fallback_skips_sponsor_and_profile_noise():
    mock_ydl = _youtube_description_fallback_mocks(
        "Sponsored by https://www.patreon.com/mychannel. Follow "
        "https://twitter.com/mychannel. Full paper: "
        "https://arxiv.org/abs/1234.5678 " + "x" * 200
    )
    with patch("ingest.requests.get", side_effect=Exception("jina failed")), \
         patch("glob.glob", return_value=[]), \
         patch("yt_dlp.YoutubeDL", return_value=mock_ydl), \
         patch(
             "youtube_transcript_api.YouTubeTranscriptApi.list_transcripts",
             side_effect=Exception("strategy 1 forced to fail"),
             create=True,
         ), \
         patch("ingest._fetch_linked_content", return_value="Paper text") as mock_fetch:
        text, quality, error = extract_youtube("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    mock_fetch.assert_called_once_with("https://arxiv.org/abs/1234.5678")
    assert "Paper text" in text


def test_extract_youtube_never_scans_links_on_transcript_api_success_path():
    fetched = [{"text": "word " * 60}]
    mock_transcript = MagicMock()
    mock_transcript.fetch.return_value = fetched
    mock_transcript_list = MagicMock()
    mock_transcript_list.find_manually_created_transcript.return_value = mock_transcript
    with patch(
        "youtube_transcript_api.YouTubeTranscriptApi.list_transcripts",
        return_value=mock_transcript_list,
        create=True,
    ), patch("ingest._append_linked_content") as mock_append:
        text, quality, error = extract_youtube("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert quality == "transcript"
    mock_append.assert_not_called()


def test_extract_youtube_never_scans_links_on_jina_path():
    jina_response = MagicMock(
        status_code=200,
        text="\n".join([("meaningful line " * 5) for _ in range(6)]),
    )
    with patch(
        "youtube_transcript_api.YouTubeTranscriptApi.list_transcripts",
        side_effect=Exception("strategy 1 forced to fail"),
        create=True,
    ), patch("ingest.requests.get", return_value=jina_response), \
         patch("ingest._append_linked_content") as mock_append:
        text, quality, error = extract_youtube("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert quality == "jina_extract"
    mock_append.assert_not_called()


def test_fetch_linked_content_does_not_recurse_through_youtube():
    mock_ydl = _youtube_description_fallback_mocks("x" * 250)
    with patch("ingest.requests.get", side_effect=Exception("jina failed")), \
         patch("glob.glob", return_value=[]), \
         patch("yt_dlp.YoutubeDL", return_value=mock_ydl), \
         patch(
             "youtube_transcript_api.YouTubeTranscriptApi.list_transcripts",
             side_effect=Exception("strategy 1 forced to fail"),
             create=True,
         ), \
         patch("ingest._append_linked_content") as mock_append:
        _fetch_linked_content("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    mock_append.assert_not_called()


def test_resolve_redirector_degrades_safely_on_lnkd_in_network_failure():
    with patch("ingest.requests.get", side_effect=Exception("boom")):
        result = _resolve_redirector("https://lnkd.in/abc123")
    assert result == "https://lnkd.in/abc123"


def test_decode_query_param_redirector_rejects_non_http_scheme_target():
    wrapped = "https://www.linkedin.com/safety/go?url=javascript%3Aalert(1)&urlhash=abc"
    assert _resolve_redirector(wrapped) == wrapped


def test_decode_query_param_redirector_handles_safety_go_trailing_slash():
    wrapped = "https://www.linkedin.com/safety/go/?url=https%3A%2F%2Fnytimes.com%2Farticle&urlhash=abc"
    assert _resolve_redirector(wrapped) == "https://nytimes.com/article"


def test_decode_query_param_redirector_handles_regional_linkedin_host():
    wrapped = "https://in.linkedin.com/safety/go?url=https%3A%2F%2Fnytimes.com%2Farticle&urlhash=abc"
    assert _resolve_redirector(wrapped) == "https://nytimes.com/article"


def test_extract_linkedin_follows_link_reached_through_safety_go_interstitial():
    jina_response = MagicMock(status_code=200, text=(
        "x" * 250 + " https://www.linkedin.com/safety/go?url="
        "https%3A%2F%2Fnytimes.com%2F2026%2Farticle&urlhash=abc"
    ))
    with patch("ingest.requests.get", return_value=jina_response), \
         patch("ingest._fetch_linked_content", return_value="Article text") as mock_fetch:
        text, quality, error = extract_linkedin("https://www.linkedin.com/posts/my-post_456")
    mock_fetch.assert_called_once_with("https://nytimes.com/2026/article")
    assert "Article text" in text
