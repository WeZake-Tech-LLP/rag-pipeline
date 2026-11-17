# Social Link-Following Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LinkedIn, Facebook, and Instagram posts follow up to 4 embedded links to a recognized platform, exactly like articles already do, except links back to the same platform being ingested are excluded.

**Architecture:** `_find_platform_urls()`/`_append_linked_content()` gain one new optional parameter, `exclude_hosts`, defaulting to "exclude nothing" so `extract_article()`'s existing calls are unaffected. `_extract_via_jina_or_meta()` — the one function all three platforms already share — passes each platform's own domains as `exclude_hosts`, via a small new lookup table.

**Tech Stack:** Python, `pytest` + `unittest.mock` (matching `tests/test_ingest.py`'s existing style).

**Spec:** `docs/superpowers/specs/2026-11-17-social-link-following-design.md`

## Global Constraints

- `_find_platform_urls()`/`_append_linked_content()` get an additional `exclude_hosts: frozenset = frozenset()` parameter; the default preserves `extract_article()`'s existing behavior exactly (it never passes this argument).
- `_PLATFORM_LABEL_HOSTS` maps exactly: `"LinkedIn"` → `{"linkedin.com", "lnkd.in"}`, `"Facebook"` → `{"facebook.com", "fb.com"}`, `"Instagram"` → `{"instagram.com"}` — the same domains already in `_PLATFORM_HOSTS`.
- `_extract_via_jina_or_meta()` passes `exclude_hosts=_PLATFORM_LABEL_HOSTS.get(platform_label, frozenset())` at both of its existing return points (Jina success, meta-tag fallback).
- The cap stays 4; no other filtering logic (share-button denylist, markdown-aware matching, image-markdown stripping) changes.

## Review Focus

- A LinkedIn/Facebook/Instagram post linking to a genuinely different platform (GitHub, YouTube, X, Reddit) must still be followed — the exclusion only ever applies to the platform being ingested, not to platforms generally. → Task 2.
- A same-platform link in its `www.` subdomain form (the common real-world form) must still be excluded, not just the bare domain. → Task 1.
- A same-platform link in its short-link form (`lnkd.in`, `fb.com`) must also be excluded, since `_PLATFORM_LABEL_HOSTS` lists both forms per platform. → Task 1.
- The meta-tag-only fallback path (used when Jina Reader fails) must get the same link-following + exclusion treatment as the Jina-success path — this exact gap was found and fixed for `extract_article()`'s own fallback path during the earlier hardening work, and is just as possible here. → Task 2.
- `extract_article()`'s own existing tests must all still pass unmodified — this change touches the two shared helper functions its own link-following depends on. → proven by the full suite run at the end of Task 2.

---

### Task 1: `exclude_hosts` parameter on the shared helpers

**Files:**
- Modify: `ingest.py`
- Test: `tests/test_ingest.py`

**Interfaces:**
- Produces: `_find_platform_urls(text: str, max_links: int = 4, exclude_hosts: frozenset = frozenset()) -> list[str]` and `_append_linked_content(text: str, max_links: int = 4, extra_scan_text: str = "", exclude_hosts: frozenset = frozenset()) -> str` — both gain the new parameter; a candidate URL is skipped whenever its host, normalized the same way `_is_platform_host()` already normalizes (`www.` prefix stripped), exactly equals or is a subdomain of any entry in `exclude_hosts`.

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ingest.py -k "exclude_hosts or excludes_short_link_form" -v`
Expected: FAIL with `TypeError: ... got an unexpected keyword argument 'exclude_hosts'`

- [ ] **Step 3: Implement the new parameter in `ingest.py`**

In `_find_platform_urls()`, after computing each candidate's `host = urlsplit(candidate).netloc.lower()`, normalize it exactly as `_is_platform_host()` does (strip a leading `"www."`), and `continue` (skip the candidate) if the normalized host equals or ends with `"." + d"` for any `d` in `exclude_hosts` — do this check *before* the existing `_is_platform_host()` check, in the same loop. In `_append_linked_content()`, add the parameter and pass it straight through to its `_find_platform_urls(scan_text, max_links=max_links, exclude_hosts=exclude_hosts)` call.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ingest.py -k "exclude_hosts or excludes_short_link_form" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ingest.py tests/test_ingest.py
git commit -m "feat: add exclude_hosts parameter to the link-following helpers"
```

---

### Task 2: Wire into LinkedIn/Facebook/Instagram extraction

**Files:**
- Modify: `ingest.py` (`_extract_via_jina_or_meta()`)
- Test: `tests/test_ingest.py`

**Interfaces:**
- Consumes: `_append_linked_content(text, max_links=4, extra_scan_text="", exclude_hosts=frozenset())` (Task 1).
- Produces: `_PLATFORM_LABEL_HOSTS: dict[str, frozenset]` — none of it consumed outside this task.

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ingest.py -k "excludes_links_to_other or applies_link_following_on_meta_fallback" -v`
Expected: FAIL (no link-following happens yet; `mock_fetch`/`mock_append` never called)

- [ ] **Step 3: Implement in `ingest.py`**

Add, near `_PLATFORM_HOSTS`:

```python
_PLATFORM_LABEL_HOSTS = {
    "LinkedIn": frozenset({"linkedin.com", "lnkd.in"}),
    "Facebook": frozenset({"facebook.com", "fb.com"}),
    "Instagram": frozenset({"instagram.com"}),
}
```

In `_extract_via_jina_or_meta()`, wrap `text` (Jina-success return) and `text.strip()` (meta-tag-fallback return) with `_append_linked_content(..., exclude_hosts=_PLATFORM_LABEL_HOSTS.get(platform_label, frozenset()))` at each of its two existing return points — the same pattern `extract_article()` already uses at its own two return points.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ingest.py -k "excludes_links_to_other or applies_link_following_on_meta_fallback" -v`
Expected: PASS

- [ ] **Step 5: Run the full test suite**

Run: `pytest -q`
Expected: all tests pass, including every existing `extract_article()` link-following test unchanged

- [ ] **Step 6: Commit**

```bash
git add ingest.py tests/test_ingest.py
git commit -m "feat: follow recognized-platform links embedded in LinkedIn/Facebook/Instagram posts"
```
