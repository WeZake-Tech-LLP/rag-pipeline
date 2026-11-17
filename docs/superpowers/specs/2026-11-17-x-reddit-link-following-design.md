# X/Reddit Link-Following Generalization — Design (short)

## Intent and why

Articles, LinkedIn, Facebook, and Instagram all follow up to 4 embedded
links to a recognized platform, hardened against noise. X and Reddit
still run their original, much narrower logic from before that work
existed: each follows only the *first* external link it finds, with no
noise filtering. The user wants every platform consistent: all embedded
links inside any uploaded URL should be found and queryable.

## Goals

- X and Reddit follow up to 4 recognized-platform links, with the same
  hardening (share-button denylist, markdown-aware matching, image
  stripping) everything else already has.
- X's links work at all: Twitter/X wraps *every* link in a post as a
  `t.co/xxxxx` short link, so without resolving it first there is
  nothing recognizable to filter or follow — this is not optional for X,
  unlike the other platforms.
- Resolving short-link wrappers benefits every platform for free, since
  it plugs into the one shared filter function (`_find_platform_urls()`)
  everything already calls — including fixing the known LinkedIn/
  Facebook/Instagram limitation (their own short-link forms —
  `lnkd.in`, `l.facebook.com`, `l.instagram.com` — were previously
  excluded outright as "same platform" even when they wrapped a
  genuinely different destination).

## Non-goals (explicitly out of scope for this iteration)

- Not changing the cap (4) or adding per-platform tuning.
- Not resolving every possible shortener on the internet — only the
  ones this project's own platforms actually produce: `t.co` (X),
  `lnkd.in` (LinkedIn), `l.facebook.com`/`l.instagram.com` (Facebook/
  Instagram's outbound-link wrapper).
- Not adding redirect resolution to `detect_url_type()`'s own
  classification logic — resolution only happens inside the
  link-following scan, nowhere else.

## Anti-goals

- Must never make an existing non-wrapper URL (github.com, youtube.com,
  etc.) trigger a network call during filtering — resolution must be a
  no-op, zero-network-call pass-through for anything that isn't a known
  wrapper domain.
- Must never let a wrapper link that resolves back to the *same*
  platform being ingested slip past the existing same-platform
  exclusion just because it arrived in short-link form.
- A failed resolution (timeout, connection error) must degrade safely —
  return the original URL unchanged, never raise, never crash the whole
  extraction.

## Constraints

- Reuses `_find_platform_urls()`, `_append_linked_content()`,
  `_is_platform_host()`, and the existing `_SHARE_PATH_MARKERS`/image-
  stripping hardening unmodified in their own logic — resolution is a
  new step inserted before them, not a rewrite of them.
- `extract_x()` and `extract_reddit()` drop their bespoke single-link
  code entirely and call `_append_linked_content()` like every other
  extractor, keeping their existing `follow_links: bool = True`
  parameter (unchanged signature, already wired through
  `_extract_for_type()`).
- `_find_external_url()` becomes dead code once `extract_reddit()` stops
  calling it, and is removed.

## Approach (decided in conversation)

1. New `_resolve_redirector(url: str) -> str`: looks at the candidate's
   host. For `l.facebook.com`/`l.instagram.com`, decodes the `u=` query
   parameter (no network call — these wrappers carry the real URL
   directly). For `t.co`/`lnkd.in`, resolves via a redirect-following
   request (the exact `allow_redirects=True, stream=True` pattern
   `extract_x()`'s own single-link code already uses today). Anything
   else — including every URL already used by existing tests — is
   returned unchanged with no network call at all.
2. `_find_platform_urls()` calls `_resolve_redirector(candidate)`
   immediately after extracting each candidate (before the dedup check,
   the share-marker check, the exclude-hosts check, and the
   `_is_platform_host()` check) — so every later check, and the URL
   actually stored/fetched, operates on the real destination.
3. `extract_x()`: after the existing Jina fetch, replace the manual
   `re.search(r"https://t\.co/...")` + manual redirect-resolution block
   with `text = _append_linked_content(text, exclude_hosts=
   _PLATFORM_LABEL_HOSTS["X"])` when `follow_links` is true.
4. `extract_reddit()`: replace the `_find_external_url(post_text)` +
   single `_fetch_linked_content()` call with `_append_linked_content()`
   applied to the fully-assembled text (post + top comments, not just
   the post body — a deliberate small widening, since a useful link is
   just as likely to appear in a top comment), with `exclude_hosts=
   _PLATFORM_LABEL_HOSTS["Reddit"]`.
5. `_PLATFORM_LABEL_HOSTS` gains two entries: `"X"` →
   `{"x.com", "twitter.com"}`, `"Reddit"` → `{"reddit.com", "redd.it"}`.

One existing test, `test_find_platform_urls_excludes_short_link_form`,
changes meaning once resolution exists: today it proves "a bare
`lnkd.in` URL is excluded because the literal string is in
`exclude_hosts`." After this change, exclusion correctly depends on
where the link actually *resolves to*, not its wrapper form — so it
becomes two tests: one proving a `lnkd.in` link that resolves to another
LinkedIn URL is still excluded, and one proving a `lnkd.in` link that
resolves to a different platform is correctly followed. This is a
deliberate, understood behavior change (a fix, not a regression), not a
mechanical test update.

One alternative considered and set aside: keeping `extract_x()`'s
bespoke t.co-resolution code and only generalizing it to look for up to
4 matches instead of 1, without touching the shared helpers. Rejected
because it would duplicate the resolution logic a second time (once for
X's own t.co, once for LinkedIn's `lnkd.in` if that were ever fixed
separately) instead of solving it once at the one place all platforms
already share.

## What's left to the builder

- None — the signatures, the lookup table entries, and the resolution
  logic's exact scope (which two hosts resolve via network, which two
  via query-param decoding) are all fixed above.
