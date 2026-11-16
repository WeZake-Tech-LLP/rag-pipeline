# Generalized Article Link-Following Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When ingesting a generic article/blog, also ingest the content behind up to 4 embedded links that point to a recognized platform (YouTube/LinkedIn/Reddit/X/Facebook/Instagram/GitHub), skipping nav/footer/social-share noise.

**Architecture:** A new pure helper classifies and filters URLs found in article text down to recognized-platform matches; a second helper fetches each (reusing the existing depth-limited `_fetch_linked_content()`) and appends their content as "Linked Content" sections; `extract_article()` calls the second helper at both of its existing return points (Jina success, BeautifulSoup fallback).

**Tech Stack:** Python, `pytest` + `unittest.mock` (matching `tests/test_ingest.py`'s existing style).

**Spec:** `docs/superpowers/specs/2026-11-16-article-link-following-design.md`

## Global Constraints

- Only `extract_article()` gains this behavior — `extract_x()` and `extract_reddit()`'s existing single-link-following are unchanged.
- A URL is followed only if `detect_url_type(url)` returns something other than `"article"` — this is the entire noise filter (nav/footer/"related posts"/same-domain links all resolve to `"article"` and are dropped).
- Cap: **4** links followed per article (confirmed value).
- Duplicate URLs within the same article body are fetched only once.
- Reuses `detect_url_type()` and `_fetch_linked_content()` unmodified.

## Review Focus

- A social-share-style URL that matches a recognized platform type (e.g. a `twitter.com/intent/tweet?...` share link) but isn't real content, so its fetch returns nothing — it should count against the cap and contribute no section, per the spec's accepted behavior (same precedent as X/Reddit's existing single-link code). → Task 2.
- The exact same platform URL appearing more than once in one article's body — fetched/counted once, not once per occurrence. → Task 1.
- `extract_article()`'s BeautifulSoup fallback path (used when Jina Reader fails) must also get link-following applied, not only the Jina success path. → Task 3.
- An article with zero recognized-platform links (the common case) — text must come back unchanged, no crash, no empty "Linked Content" section appended. → Task 2.
- More than 4 candidate platform URLs in one article — only the first 4 (by order of appearance) are followed; the rest are never fetched. → Task 1.

---

### Task 1: URL filtering helper

**Files:**
- Modify: `ingest.py`
- Test: `tests/test_ingest.py`

**Interfaces:**
- Consumes: `detect_url_type(url: str) -> str` (existing).
- Produces: `_find_platform_urls(text: str, max_links: int = 4) -> list[str]` — URLs from `text` whose `detect_url_type()` is not `"article"`, deduplicated, in order of first appearance, capped at `max_links`.

- [ ] **Step 1: Write the failing tests**

```python
from ingest import _find_platform_urls

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ingest.py -k find_platform_urls -v`
Expected: FAIL (`_find_platform_urls` not defined)

- [ ] **Step 3: Implement `_find_platform_urls(text: str, max_links: int = 4) -> list[str]` in `ingest.py`**

Reuse the same URL-matching and trailing-punctuation-stripping approach already used by `_find_external_url()` (regex `https?://\S+`, then `.rstrip(").,;:!?\"'][}{")`). Iterate matches in order, classify each with `detect_url_type()`, skip `"article"` and already-seen URLs, stop once `max_links` are collected.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ingest.py -k find_platform_urls -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ingest.py tests/test_ingest.py
git commit -m "feat: add helper to find recognized-platform links in article text"
```

---

### Task 2: Append linked content

**Files:**
- Modify: `ingest.py`
- Test: `tests/test_ingest.py`

**Interfaces:**
- Consumes: `_find_platform_urls(text: str, max_links: int = 4) -> list[str]` (Task 1), `_fetch_linked_content(url: str) -> Optional[str]` (existing).
- Produces: `_append_linked_content(text: str, max_links: int = 4) -> str` — `text` with one `"Linked Content: <url>\n<content>"` section appended per URL `_find_platform_urls` returns, for whichever of those `_fetch_linked_content` returns a truthy value for; returns `text` unchanged if no URLs are found or none of their fetches succeed.

- [ ] **Step 1: Write the failing tests**

```python
from unittest.mock import patch
from ingest import _append_linked_content

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ingest.py -k append_linked_content -v`
Expected: FAIL (`_append_linked_content` not defined)

- [ ] **Step 3: Implement `_append_linked_content(text: str, max_links: int = 4) -> str` in `ingest.py`**

Call `_find_platform_urls(text, max_links=max_links)`, and for each URL call `_fetch_linked_content(url)`; when it returns a truthy value, append `f"\n\nLinked Content: {url}\n{content}"` to the result (mirroring the `"Linked Content:\n{linked_text}"` wording `extract_x()`/`extract_reddit()` already use, with the URL added since there can now be more than one section). Return the original `text` untouched if no sections get added.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ingest.py -k append_linked_content -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ingest.py tests/test_ingest.py
git commit -m "feat: add helper to append linked content for multiple platform URLs"
```

---

### Task 3: Wire into `extract_article()`

**Files:**
- Modify: `ingest.py` (`extract_article()`)
- Test: `tests/test_ingest.py`

**Interfaces:**
- Consumes: `_append_linked_content(text: str, max_links: int = 4) -> str` (Task 2).
- Produces: none (terminal task).

- [ ] **Step 1: Write the failing tests**

```python
from unittest.mock import MagicMock, patch
from ingest import extract_article

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ingest.py -k "extract_article_appends" -v`
Expected: FAIL (`_append_linked_content` is never called — assertion failure, not an import error, since `extract_article` already exists)

- [ ] **Step 3: Modify `extract_article()` in `ingest.py`**

At both existing `return text, "full_text", None` / `return content.strip(), "full_text", None` points, replace `text` (respectively `content.strip()`) with `_append_linked_content(text)` (respectively `_append_linked_content(content.strip())`) inline in the return statement.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ingest.py -k "extract_article_appends" -v`
Expected: PASS

- [ ] **Step 5: Run the full test suite**

Run: `pytest -q`
Expected: all tests pass (existing + Tasks 1–3's new tests)

- [ ] **Step 6: Commit**

```bash
git add ingest.py tests/test_ingest.py
git commit -m "feat: follow recognized-platform links embedded in articles"
```
