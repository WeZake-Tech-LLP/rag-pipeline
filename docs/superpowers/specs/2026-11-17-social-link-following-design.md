# Link-Following for LinkedIn/Facebook/Instagram — Design (short)

## Intent and why

Generic articles already follow up to 4 embedded links to a recognized
platform (GitHub, YouTube, Reddit, X, LinkedIn, Facebook, Instagram),
filtered and hardened against nav/share-button/markdown noise. LinkedIn,
Facebook, and Instagram posts don't get this at all today, even though a
LinkedIn post linking to a GitHub repo or a news article is just as
common and just as worth capturing as an article doing the same.

## Goals

- Ingesting a LinkedIn, Facebook, or Instagram post also ingests content
  behind up to 4 embedded links, exactly like articles already do.
- A post's links back to its *own* platform (another LinkedIn post, a
  profile page, a share/nav link) are not followed — confirmed: this is
  the one new wrinkle these three platforms have that articles don't,
  since articles are never themselves hosted on a recognized-platform
  domain, but a LinkedIn post's own domain *is* one.

## Non-goals (explicitly out of scope for this iteration)

- Not changing `extract_article()`'s own behavior — already built and
  hardened.
- Not re-litigating the existing cap (4) or the existing noise filters
  (share-button denylist, markdown-aware URL matching, image-markdown
  stripping) — all reused unmodified via `_find_platform_urls()`/
  `_append_linked_content()`.
- Not adding per-platform tuning (e.g. a different cap for Instagram) —
  one shared behavior for all three, matching how they already share
  one extractor function (`_extract_via_jina_or_meta()`).

## Anti-goals

- Must never follow a link back to the same platform being ingested
  (e.g. a LinkedIn post linking to another LinkedIn post or a profile
  page) — that's navigation noise, not new content.
- Must not regress the existing meta-tag fallback path (used when Jina
  Reader fails and only `og:title`/`og:description` are available) —
  it should still get the same link-following treatment, even though in
  practice there's rarely a link in two short meta tags.

## Constraints

- Reuses `_find_platform_urls()` and `_append_linked_content()`
  unmodified in their existing filtering logic — only a new optional
  exclusion parameter is added to each, not a rewrite.
- All three platforms share one extractor function,
  `_extract_via_jina_or_meta(url, platform_label)` — the change is made
  once there, not three times.

## Approach (decided in conversation)

1. `_find_platform_urls(text, max_links=4, exclude_hosts=frozenset())`
   gains one new parameter: any candidate URL whose host exactly
   matches, or is a subdomain of, an entry in `exclude_hosts` is skipped
   before the existing `_is_platform_host()` check even runs (default
   `frozenset()` means "exclude nothing," so `extract_article()`'s
   existing calls are unaffected).
2. `_append_linked_content(text, max_links=4, extra_scan_text="",
   exclude_hosts=frozenset())` gains the same parameter and passes it
   straight through to `_find_platform_urls()`.
3. A new mapping, `_PLATFORM_LABEL_HOSTS`, gives each of the three
   labels `_extract_via_jina_or_meta()` already receives
   (`"LinkedIn"`, `"Facebook"`, `"Instagram"`) its own domain set
   (reusing the exact same domains already in `_PLATFORM_HOSTS`):
   `{"linkedin.com", "lnkd.in"}`, `{"facebook.com", "fb.com"}`,
   `{"instagram.com"}`.
4. `_extract_via_jina_or_meta()` calls `_append_linked_content(text,
   exclude_hosts=_PLATFORM_LABEL_HOSTS.get(platform_label,
   frozenset()))` at both of its existing return points (Jina success,
   meta-tag fallback), exactly mirroring how `extract_article()` already
   calls it at its own two return points.

One alternative considered and set aside: excluding by comparing
`detect_url_type(candidate) == detect_url_type(url)` (the ingested
post's own type) instead of a host-list lookup. Rejected because
`_find_platform_urls()` already moved away from `detect_url_type()`'s
substring-based matching for its own noise filter (the article
hardening work), for exactly the reason that substring matching produces
false positives — reusing it here would reintroduce the same class of
bug this project already fixed once.

## What's left to the builder

- None — the signatures, the exclusion mechanism, and the exact domain
  sets are all fixed above.
