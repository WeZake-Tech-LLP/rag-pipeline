# Generalized Article Link-Following — Design (short)

## Intent and why

`extract_x()` and `extract_reddit()` already follow the one external link
found inside a post and fold its content in. Generic articles/blogs —
the majority of what actually gets shared into the knowledge base — get
none of this: a news article that links out to a GitHub repo, a tweet,
or another relevant source currently only ingests the article's own
text, losing everything it points to.

## Goals

- Ingesting a generic article/blog (`url_type == "article"`) also
  ingests the content behind the links it embeds, not just its own text.
- Noise links (nav, footer, "related posts," ads, social-share buttons)
  are not followed — only links recognized as a specific platform type
  are.
- Cost and time stay bounded regardless of how many links an article
  happens to contain.

## Non-goals (explicitly out of scope for this iteration)

- Not extending X's or Reddit's existing single-link-following to
  multiple links — those already work for their one link; a separate
  concern if it comes up later.
- Not following links to other generic articles (article-to-article).
  Confirmed: only links matching a recognized platform type
  (youtube/linkedin/reddit/x/facebook/instagram/github) are followed.
- Not changing extraction for LinkedIn/Facebook/Instagram/GitHub posts
  themselves — only `extract_article()` gains this behavior.

## Anti-goals

- Must never let a single link-heavy article trigger an unbounded
  number of fetches (cost/time/rate-limit risk — GitHub's
  unauthenticated API alone is 60 requests/hour).
- Must never let followed-link content bury the article's own content
  in retrieval.

## Constraints

- Reuses `detect_url_type()` and `_fetch_linked_content()` (which
  already dispatches through `_extract_for_type(..., follow_links=False)`,
  keeping link-following depth-limited to one level) unmodified.
- Cap: **4** links followed per article, confirmed in conversation.
- Duplicate URLs within the same article body are only fetched once.

## Approach (decided in conversation)

New helper `_find_platform_urls(text: str, max_links: int = 4) -> list[str]`:
scans article text with the same `https?://\S+`-style URL regex already
used by `_find_external_url()`, classifies each match with
`detect_url_type()`, keeps only matches whose type is **not** `"article"`
(this is exactly the filter that discards nav/footer/social-share noise,
since those overwhelmingly resolve to `"article"` or point back to the
same domain), deduplicates, and returns at most `max_links` in the order
they first appear.

`extract_article()` calls this after getting its own text, then for each
URL calls the existing `_fetch_linked_content(url)` and appends it as its
own `"Linked Content: <url>"` section — the same pattern `extract_x()`
and `extract_reddit()` already use for their one link, just repeated per
URL instead of stopping after the first.

One alternative considered and set aside: following *every* embedded
link regardless of type, relying only on the numeric cap to bound cost.
Rejected because it would still waste fetches on social-share buttons
(which link to real platform domains like `twitter.com/intent/tweet` but
aren't real content) and because the user confirmed article-to-article
links are noise to skip entirely, not just rare.

## What's left to the builder

- Exact section header wording for multiple linked-content blocks (e.g.
  numbering them vs. just repeating `"Linked Content: <url>"` per link) —
  not load-bearing, just needs to read sensibly with up to 4 sections.
- Whether a social-share-style URL that matches a platform type (e.g.
  `twitter.com/intent/tweet?...`) but fails extraction should count
  against the 4-link cap even though it contributed nothing — simplest
  behavior (and the one used by X/Reddit's existing single-link code) is
  to count it anyway and not retry with another link; that's acceptable
  here too, since the existing precedent already behaves this way.
