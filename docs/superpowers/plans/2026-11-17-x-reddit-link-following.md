# X/Reddit Link-Following Generalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** X and Reddit follow up to 4 recognized-platform links with the same hardening everything else has, and short-link wrappers (`t.co`, `lnkd.in`, `l.facebook.com`, `l.instagram.com`) are resolved to their real destination before filtering — fixing X (which wraps every link) and, as a side effect, the LinkedIn/Facebook/Instagram short-link limitation too.

**Architecture:** A new `_resolve_redirector()` sits in front of `_find_platform_urls()`'s existing filters, unwrapping known wrapper domains only (zero-cost pass-through otherwise). `extract_x()` and `extract_reddit()` drop their bespoke single-link code and call `_append_linked_content()` like every other extractor already does.

**Tech Stack:** Python, `pytest` + `unittest.mock` (matching `tests/test_ingest.py`'s existing style).

**Spec:** `docs/superpowers/specs/2026-11-17-x-reddit-link-following-design.md`

## Global Constraints

- `_resolve_redirector(url: str) -> str` makes a network call only for `t.co`/`lnkd.in` (redirect-following GET, same `allow_redirects=True, stream=True` pattern `extract_x()`'s old code already used); decodes the `u=` query param for `l.facebook.com`/`l.instagram.com` (no network call); returns anything else unchanged with no network call.
- `_find_platform_urls()` calls `_resolve_redirector()` on each candidate immediately after extracting it, before the dedup/share-marker/exclude-hosts/`_is_platform_host()` checks — every later check and the stored/fetched URL operate on the resolved form.
- `_PLATFORM_LABEL_HOSTS` gains `"X"` → `{"x.com", "twitter.com"}` and `"Reddit"` → `{"reddit.com", "redd.it"}`.
- `extract_x()`/`extract_reddit()` keep their existing `follow_links: bool = True` signature (already wired through `_extract_for_type()`) — only their internal link-following logic changes.
- `_find_external_url()` is deleted once `extract_reddit()` stops calling it.
- A resolution failure (timeout, connection error) returns the original URL unchanged — never raises.

## Review Focus

- A `lnkd.in`/`t.co` link that *resolves to* the same platform being ingested must still be excluded — exclusion has to apply after resolution, not check the wrapper domain itself. → Task 1.
- A non-wrapper URL (github.com, youtube.com, etc.) must never trigger a network call during filtering — this is the zero-cost-pass-through guarantee that keeps every existing test network-free. → Task 1.
- A resolution network failure must degrade to the original URL, not crash the whole extraction. → Task 1.
- X wraps *every* link as `t.co` in real posts — `extract_x()` must actually resolve and follow one, not just filter URLs that are already bare (the core motivating case for this whole plan). → Task 2.
- A link appearing only in a Reddit post's top comments (not the post body itself) must also be found and followed — the deliberate widening from "post only" to "post + comments." → Task 3.

---

### Task 1: Redirect resolution

**Files:**
- Modify: `ingest.py`
- Test: `tests/test_ingest.py`

**Interfaces:**
- Produces: `_resolve_redirector(url: str) -> str`. `_find_platform_urls()` modified to call it per candidate. `_PLATFORM_LABEL_HOSTS["X"]` and `_PLATFORM_LABEL_HOSTS["Reddit"]` added.

- [ ] **Step 1: Write the failing tests**

First, **remove** the existing `test_find_platform_urls_excludes_short_link_form` test — its premise ("a bare `lnkd.in` URL is excluded because the literal string is in `exclude_hosts`") no longer holds once exclusion depends on where the link resolves to, not its wrapper form.

```python
def test_resolve_redirector_returns_unchanged_for_non_redirector_host():
    assert _resolve_redirector("https://github.com/real/repo") == "https://github.com/real/repo"


def test_resolve_redirector_decodes_facebook_link_wrapper():
    wrapped = "https://l.facebook.com/l.php?u=https%3A%2F%2Fgithub.com%2Freal%2Frepo&h=abc"
    assert _resolve_redirector(wrapped) == "https://github.com/real/repo"


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ingest.py -k "resolve_redirector or resolving_to or does_not_call_network_for_non_wrapper" -v`
Expected: FAIL (`_resolve_redirector` not defined; the two `_find_platform_urls` resolution tests fail because nothing resolves yet)

- [ ] **Step 3: Implement in `ingest.py`**

```python
_REDIRECTOR_NETWORK_HOSTS = frozenset({"t.co", "lnkd.in"})
_REDIRECTOR_QUERY_PARAM_HOSTS = frozenset({"l.facebook.com", "l.instagram.com"})


def _resolve_redirector(url: str) -> str:
    from urllib.parse import urlsplit, parse_qs, unquote

    parts = urlsplit(url)
    host = parts.netloc.lower()
    normalized = host[4:] if host.startswith("www.") else host

    if normalized in _REDIRECTOR_QUERY_PARAM_HOSTS:
        target = parse_qs(parts.query).get("u", [None])[0]
        return unquote(target) if target else url

    if normalized in _REDIRECTOR_NETWORK_HOSTS:
        try:
            response = requests.get(
                url, timeout=10, headers={"User-Agent": "Mozilla/5.0"},
                allow_redirects=True, stream=True,
            )
            resolved = response.url
            response.close()
            return resolved if resolved and resolved != url else url
        except Exception:
            return url

    return url
```

In `_find_platform_urls()`, call `candidate = _resolve_redirector(candidate)` immediately after the existing `.rstrip(...)` line, before the `if candidate in found:` check. Add `"X": frozenset({"x.com", "twitter.com"})` and `"Reddit": frozenset({"reddit.com", "redd.it"})` to `_PLATFORM_LABEL_HOSTS`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ingest.py -k "resolve_redirector or resolving_to or does_not_call_network_for_non_wrapper" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ingest.py tests/test_ingest.py
git commit -m "feat: resolve short-link wrappers before filtering embedded links"
```

---

### Task 2: Generalize `extract_x()`

**Files:**
- Modify: `ingest.py` (`extract_x()`)
- Test: `tests/test_ingest.py`

**Interfaces:**
- Consumes: `_append_linked_content(text, exclude_hosts=...)` (existing), `_PLATFORM_LABEL_HOSTS["X"]` (Task 1).
- Produces: none (terminal task for X).

- [ ] **Step 1: Write the failing tests**

```python
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


def test_extract_x_excludes_links_to_other_x_posts():
    jina_response = MagicMock(status_code=200, text="x" * 250 + " https://x.com/other/status/999")
    with patch("ingest.requests.get", return_value=jina_response), \
         patch("ingest._fetch_linked_content") as mock_fetch:
        text, quality, error = extract_x("https://x.com/user/status/123")
    mock_fetch.assert_not_called()


def test_extract_x_does_not_follow_links_when_follow_links_false():
    jina_response = MagicMock(status_code=200, text="x" * 250 + " https://t.co/abc123")
    with patch("ingest.requests.get", return_value=jina_response), \
         patch("ingest._fetch_linked_content") as mock_fetch:
        text, quality, error = extract_x("https://x.com/user/status/123", follow_links=False)
    mock_fetch.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ingest.py -k "extract_x_follows_tco or extract_x_excludes or extract_x_does_not_follow" -v`
Expected: FAIL (old code only matches literal `https://t\.co/[A-Za-z0-9]+` without going through the hardened filters — `test_extract_x_excludes_links_to_other_x_posts` fails because the old code has no same-platform exclusion at all)

- [ ] **Step 3: Implement in `ingest.py`**

Replace the `if follow_links:` block (the `re.search(r"https://t\.co/...")` + manual redirect-resolution + manual `_fetch_linked_content` call) with:

```python
if follow_links:
    text = _append_linked_content(text, exclude_hosts=_PLATFORM_LABEL_HOSTS.get("X", frozenset()))
```

placed where `parts = [text]` used to be built up; return `text.strip(), "full_text", None` instead of joining `parts`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ingest.py -k "extract_x_follows_tco or extract_x_excludes or extract_x_does_not_follow" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ingest.py tests/test_ingest.py
git commit -m "feat: generalize X link-following to the shared up-to-4 pattern"
```

---

### Task 3: Generalize `extract_reddit()`, remove dead code

**Files:**
- Modify: `ingest.py` (`extract_reddit()`, delete `_find_external_url()`)
- Test: `tests/test_ingest.py`

**Interfaces:**
- Consumes: `_append_linked_content(text, exclude_hosts=...)` (existing), `_PLATFORM_LABEL_HOSTS["Reddit"]` (Task 1).
- Produces: none (terminal task).

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ingest.py -k "extract_reddit_follows_links or extract_reddit_excludes or extract_reddit_does_not_follow or extract_reddit_follows_link_found_only_in_a_comment" -v`
Expected: FAIL (old code finds only the first external link via `_find_external_url`, with no same-platform exclusion or comment-scanning)

- [ ] **Step 3: Implement in `ingest.py`**

Replace the `if follow_links and post_text:` block (the `_find_external_url(post_text)` + single `_fetch_linked_content()` call) with nothing — delete it entirely. After `comment_lines` is assembled and `text = "\n\n".join(parts).strip()` is computed, insert:

```python
if len(text) > 50:
    if follow_links:
        text = _append_linked_content(text, exclude_hosts=_PLATFORM_LABEL_HOSTS.get("Reddit", frozenset()))
    return text, "reddit_rss", None
```

in place of the existing `if len(text) > 50: return text, "reddit_rss", None`. Delete `_find_external_url()` entirely (no longer called anywhere).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ingest.py -k "extract_reddit_follows_links or extract_reddit_excludes or extract_reddit_does_not_follow or extract_reddit_follows_link_found_only_in_a_comment" -v`
Expected: PASS

- [ ] **Step 5: Run the full test suite**

Run: `pytest -q`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add ingest.py tests/test_ingest.py
git commit -m "feat: generalize Reddit link-following to the shared up-to-4 pattern"
```
