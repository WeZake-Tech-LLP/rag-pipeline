import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup
import chromadb
from llama_index.core.node_parser import SentenceSplitter
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

load_dotenv()

CHROMA_PATH = "./chroma_db"
COLLECTION_NAME = "knowledge_base"
EMBED_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

# Reddit rate-limits unauthenticated requests. This throttle is shared across
# every caller in the process, so concurrent ingestions from different users
# (e.g. multiple Telegram chats) can't collectively exceed it.
_REDDIT_MIN_INTERVAL_SECONDS = 2.0
_reddit_rate_lock = threading.Lock()
_reddit_last_request_time = 0.0


def _throttle_reddit_request():
    global _reddit_last_request_time
    with _reddit_rate_lock:
        now = time.monotonic()
        wait = _REDDIT_MIN_INTERVAL_SECONDS - (now - _reddit_last_request_time)
        if wait > 0:
            time.sleep(wait)
        _reddit_last_request_time = time.monotonic()


_collection = None
_embed_model = None


def get_collection():
    global _collection
    if _collection is None:
        client = chromadb.PersistentClient(path=CHROMA_PATH)
        _collection = client.get_or_create_collection(COLLECTION_NAME)
    return _collection


def get_embed_model():
    global _embed_model
    if _embed_model is None:
        _embed_model = HuggingFaceEmbedding(model_name=EMBED_MODEL_NAME)
    return _embed_model


def detect_url_type(url: str) -> str:
    if "youtube.com" in url or "youtu.be" in url:
        return "youtube"
    elif "linkedin.com" in url or "lnkd.in" in url:
        return "linkedin"
    elif "reddit.com" in url or "redd.it" in url:
        return "reddit"
    elif "x.com" in url or "twitter.com" in url:
        return "x"
    elif "facebook.com" in url or "fb.com" in url:
        return "facebook"
    elif "instagram.com" in url:
        return "instagram"
    elif "github.com" in url:
        return "github"
    else:
        return "article"


def extract_youtube(url: str, follow_links: bool = True):
    # Extract video ID
    patterns = [
        r"(?:v=|\/)([0-9A-Za-z_-]{11}).*",
        r"(?:embed\/)([0-9A-Za-z_-]{11})",
        r"(?:youtu\.be\/)([0-9A-Za-z_-]{11})",
    ]
    video_id = None
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            video_id = match.group(1)
            break

    if not video_id:
        return None, "failed", "Could not extract video ID"

    # Strategy 1: youtube-transcript-api (cookies / retry for regional blocks)
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        from youtube_transcript_api._errors import (
            NoTranscriptFound,
            TranscriptsDisabled,
        )

        # Try with cookies first (bypasses regional blocks)
        # cookies help authenticate as a real browser session
        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(
                video_id,
                cookies=None,  # can add cookie file path here later
            )
        except Exception:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

        transcript = None

        # Priority: manual English → auto English → any available
        for finder in [
            lambda: transcript_list.find_manually_created_transcript(["en"]),
            lambda: transcript_list.find_generated_transcript(["en"]),
            lambda: transcript_list.find_generated_transcript(
                list(transcript_list._generated_transcripts.keys())
                or list(transcript_list._manually_created_transcripts.keys())
            ),
        ]:
            try:
                transcript = finder()
                break
            except Exception:
                continue

        if transcript:
            fetched = transcript.fetch()
            text = " ".join(
                [
                    entry["text"]
                    for entry in fetched
                    if entry["text"].strip()
                    and entry["text"] != "[Music]"
                    and entry["text"] != "[Applause]"
                ]
            )
            if len(text.strip()) > 200:
                print(f"[DEBUG] transcript-api success: {len(text)} chars")
                return text, "transcript", None

    except TranscriptsDisabled:
        print(f"[DEBUG] Transcripts disabled for {video_id}")
    except NoTranscriptFound:
        print(f"[DEBUG] No transcript found for {video_id}")
    except Exception as e:
        print(f"[DEBUG] transcript-api failed: {e}")

    # Strategy 2: Jina Reader with content validation
    try:
        jina_url = f"https://r.jina.ai/{url}"
        response = requests.get(
            jina_url,
            timeout=20,
            headers={"User-Agent": "Mozilla/5.0", "X-Return-Format": "text"},
        )
        if response.status_code == 200:
            text = response.text.strip()
            lines = [line.strip() for line in text.split("\n") if line.strip()]
            meaningful_lines = [
                line
                for line in lines
                if len(line) > 50
                and not line.startswith("Title:")
                and not line.startswith("URL Source:")
                and not line.startswith("http")
            ]
            if len(meaningful_lines) >= 5:
                full_text = "\n".join(meaningful_lines)
                return full_text, "jina_extract", None
            else:
                print("[DEBUG] Jina returned only metadata for YouTube, skipping")
    except Exception as e:
        print(f"[DEBUG] Jina fallback failed: {e}")

    # Strategy 3: yt-dlp to extract actual subtitles/captions
    try:
        import yt_dlp
        import glob

        subtitle_file = f"/tmp/{video_id}_subtitles"

        ydl_opts = {
            "writeautomaticsub": True,
            "writesubtitles": True,
            "subtitleslangs": ["en", "en-US", "en-GB"],
            "subtitlesformat": "vtt",
            "skip_download": True,
            "quiet": True,
            "outtmpl": subtitle_file,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        # Find downloaded subtitle file
        vtt_files = glob.glob(f"{subtitle_file}*.vtt")
        if vtt_files:
            with open(vtt_files[0], "r", encoding="utf-8") as f:
                raw = f.read()

            # Clean VTT format — remove timestamps and tags
            lines = raw.split("\n")
            clean_lines = []
            seen = set()
            for line in lines:
                line = line.strip()
                # Skip VTT headers, timestamps, empty lines
                if (
                    not line
                    or line == "WEBVTT"
                    or line.startswith("Kind:")
                    or line.startswith("Language:")
                    or "-->" in line
                    or re.match(r"^\d+$", line)
                ):
                    continue
                # Remove HTML tags
                line = re.sub(r"<[^>]+>", "", line)
                line = re.sub(r"&amp;", "&", line)
                line = re.sub(r"&nbsp;", " ", line)
                line = line.strip()
                # Skip music/sound annotations
                if re.match(r"^\[.*\]$", line):
                    continue
                # Skip very short lines (single words, punctuation only)
                if len(line.split()) < 3:
                    continue
                # Skip lines that are just numbers or timestamps that slipped through
                if re.match(r"^[\d\s:.,\-]+$", line):
                    continue
                # Deduplicate repeated lines (VTT has overlapping captions)
                if line and line not in seen:
                    seen.add(line)
                    clean_lines.append(line)

            # Clean up temp files
            for vtt_file in vtt_files:
                os.remove(vtt_file)

            transcript_text = " ".join(clean_lines)
            if len(transcript_text) > 300:
                print(f"[DEBUG] yt-dlp subtitle extraction: {len(clean_lines)} lines")
                return transcript_text, "yt_dlp_captions", None

        # If no subtitle file found, use description as last resort
        with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
            info = ydl.extract_info(url, download=False)
            description = info.get("description", "")
            title = info.get("title", "")
            if description and len(description) > 200:
                text = f"Video Title: {title}\n\nDescription: {description}"
                if follow_links:
                    text = _append_linked_content(
                        text, exclude_hosts=_PLATFORM_LABEL_HOSTS.get("YouTube", frozenset()), allow_any_host=True
                    )
                return text, "yt_dlp_meta", None

    except ImportError:
        print("[DEBUG] yt-dlp not installed")
    except Exception as e:
        print(f"[DEBUG] yt-dlp failed: {e}")

    return None, "failed", "All YouTube extraction strategies failed"


_MARKDOWN_IMAGE_PATTERN = re.compile(r"!?\[Image\s+\d+[^\]]*\]\([^)]+\)")
_GENERIC_MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\([^)]+\)")
# A badge (e.g. CI/coverage/PyPI) is a markdown image wrapped in a link:
# [![alt](img-url)](target-url). Stripping only the inner image leaves an
# orphaned [](target-url), so the badge's target still gets scanned as if
# it were a real link — strip the whole wrapper instead.
_BADGE_LINK_PATTERN = re.compile(r"\[!\[[^\]]*\]\([^)]*\)\]\([^)]*\)")
_HTML_IMG_TAG_PATTERN = re.compile(r"<img\b[^>]*>", re.IGNORECASE)


def _strip_image_markdown(text: str) -> str:
    text = _BADGE_LINK_PATTERN.sub("", text)
    text = _HTML_IMG_TAG_PATTERN.sub("", text)
    text = _MARKDOWN_IMAGE_PATTERN.sub("", text)
    text = _GENERIC_MARKDOWN_IMAGE_PATTERN.sub("", text)
    return text


def _is_jina_error_response(text: str) -> bool:
    markers = (
        "Warning: Target URL returned error",
        "Target URL returned error",
    )
    head = text[:500]
    if any(marker in head for marker in markers):
        return True

    # Some platforms (Facebook, Instagram) redirect to a login page instead
    # of erroring, which Jina renders as a normal 200 response — detect
    # that via the "Final URL:" line Jina includes when a redirect happened.
    match = re.search(r"^Final URL:\s*(\S+)", head, re.MULTILINE)
    if match and re.search(r"login|signin", match.group(1), re.IGNORECASE):
        return True

    return False


def extract_article(url: str, follow_links: bool = True):
    # Try Jina Reader first
    try:
        jina_url = f"https://r.jina.ai/{url}"
        response = requests.get(jina_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        text = response.text.strip()
        if response.status_code == 200 and len(text) > 300 and not _is_jina_error_response(text):
            return (_append_linked_content(text) if follow_links else text), "full_text", None
    except Exception:
        pass

    # BeautifulSoup fallback
    try:
        response = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        content = ""
        href_urls = []
        for selector in ["article", "main", "div.content", "div.post"]:
            el = soup.select_one(selector)
            if el:
                from urllib.parse import urljoin

                href_urls = [
                    urljoin(url, a.get("href")) for a in el.find_all("a", href=True) if a.get("href")
                ]
                content = el.get_text(separator=" ", strip=True)
                break

        if not content:
            content = " ".join(p.get_text(strip=True) for p in soup.find_all("p"))

        if len(content.strip()) > 200:
            stripped_content = content.strip()
            return (
                _append_linked_content(stripped_content, extra_scan_text=" ".join(href_urls))
                if follow_links
                else stripped_content,
                "full_text",
                None,
            )
    except Exception:
        pass

    return None, "failed", "Could not extract content"


def _extract_via_jina_or_meta(url: str, platform_label: str, follow_links: bool = True):
    # Try Jina Reader first
    try:
        jina_url = f"https://r.jina.ai/{url}"
        response = requests.get(jina_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        text = response.text.strip()
        if response.status_code == 200 and len(text) > 200 and not _is_jina_error_response(text):
            if follow_links:
                text = _append_linked_content(
                    text,
                    exclude_hosts=_PLATFORM_LABEL_HOSTS.get(platform_label, frozenset()),
                    allow_any_host=True,
                )
            return text, "full_text", None
    except Exception:
        pass

    # Meta tags fallback (title/description survive even behind a login wall)
    try:
        response = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(response.text, "html.parser")
        title = soup.find("meta", property="og:title")
        desc = soup.find("meta", property="og:description")
        text = ""
        if title:
            text += title.get("content", "") + "\n"
        if desc:
            text += desc.get("content", "")
        if len(text.strip()) > 50:
            text = text.strip()
            if follow_links:
                text = _append_linked_content(
                    text,
                    exclude_hosts=_PLATFORM_LABEL_HOSTS.get(platform_label, frozenset()),
                    allow_any_host=True,
                )
            return text, "meta_only", None
    except Exception:
        pass

    return None, "failed", f"{platform_label} blocked extraction"


def extract_linkedin(url: str, follow_links: bool = True):
    return _extract_via_jina_or_meta(url, "LinkedIn", follow_links=follow_links)


def extract_facebook(url: str, follow_links: bool = True):
    return _extract_via_jina_or_meta(url, "Facebook", follow_links=follow_links)


def extract_instagram(url: str, follow_links: bool = True):
    return _extract_via_jina_or_meta(url, "Instagram", follow_links=follow_links)


def extract_x(url: str, follow_links: bool = True):
    try:
        jina_url = f"https://r.jina.ai/{url}"
        response = requests.get(jina_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        text = response.text.strip()
        if response.status_code != 200 or len(text) <= 200 or _is_jina_error_response(text):
            return None, "failed", "X/Twitter blocked extraction"
    except Exception as e:
        return None, "failed", f"X/Twitter extraction failed: {e}"

    if follow_links:
        text = _append_linked_content(
            text, exclude_hosts=_PLATFORM_LABEL_HOSTS.get("X", frozenset()), allow_any_host=True
        )

    return text.strip(), "full_text", None


_PLATFORM_HOSTS = {
    "youtube.com", "youtu.be",
    "linkedin.com", "lnkd.in",
    "reddit.com", "redd.it",
    "x.com", "twitter.com",
    "facebook.com", "fb.com",
    "instagram.com",
    "github.com",
}

_PLATFORM_LABEL_HOSTS = {
    "LinkedIn": frozenset({"linkedin.com", "lnkd.in"}),
    "Facebook": frozenset({"facebook.com", "fb.com"}),
    "Instagram": frozenset({"instagram.com"}),
    "X": frozenset({"x.com", "twitter.com"}),
    "Reddit": frozenset({"reddit.com", "redd.it"}),
    # pypi.org/npmjs.com/opensource.org are excluded for GitHub specifically
    # (common badge targets in a README) — not globally, since on other
    # platforms a registry link is usually the actual package announcement.
    "GitHub": frozenset({"github.com", "pypi.org", "npmjs.com", "opensource.org"}),
    "YouTube": frozenset({"youtube.com", "youtu.be"}),
}

_REDIRECTOR_NETWORK_HOSTS = frozenset({"t.co", "lnkd.in"})
_REDIRECTOR_QUERY_PARAM_HOSTS = frozenset({"l.facebook.com", "l.instagram.com"})


def _decode_query_param_redirector(url: str) -> str:
    # No network call — these wrappers carry the real destination
    # directly in a query parameter.
    from urllib.parse import urlsplit, parse_qs

    parts = urlsplit(url)
    host = parts.netloc.lower()
    normalized = host[4:] if host.startswith("www.") else host

    def _as_http_target(raw):
        # Reject anything that isn't a real http(s) URL — e.g. a
        # javascript: scheme smuggled into the query param — rather than
        # handing it on to be fetched.
        if raw and raw.startswith(("http://", "https://")):
            return raw
        return None

    if normalized in _REDIRECTOR_QUERY_PARAM_HOSTS:
        target = _as_http_target(parse_qs(parts.query).get("u", [None])[0])
        return target if target else url

    is_linkedin_host = normalized == "linkedin.com" or normalized.endswith(".linkedin.com")
    if is_linkedin_host and parts.path.rstrip("/") == "/safety/go":
        target = _as_http_target(parse_qs(parts.query).get("url", [None])[0])
        return target if target else url

    return url


def _resolve_redirector(url: str) -> str:
    from urllib.parse import urlsplit

    decoded = _decode_query_param_redirector(url)
    if decoded != url:
        return decoded

    parts = urlsplit(url)
    host = parts.netloc.lower()
    normalized = host[4:] if host.startswith("www.") else host

    if normalized in _REDIRECTOR_NETWORK_HOSTS:
        try:
            response = requests.get(
                url, timeout=10, headers={"User-Agent": "Mozilla/5.0"},
                allow_redirects=True, stream=True,
            )
            resolved = response.url
            response.close()
            if resolved and resolved != url:
                # The network redirect may itself land on another
                # query-param wrapper (e.g. lnkd.in -> linkedin.com's
                # own safety interstitial) — unwrap that too, still
                # without a second network call.
                return _decode_query_param_redirector(resolved)
            return url
        except Exception:
            return url

    return url

_SHARE_PATH_MARKERS = ("/intent/", "/share", "sharer", "sharearticle", "/submit")

# Hosts that are never real content anywhere they're embedded — CI/badge
# icon targets, image/CDN hosts, and sponsor/community links — so they're
# excluded regardless of allow_any_host. Package-registry hosts (pypi.org,
# npmjs.com, opensource.org) are deliberately NOT here: they're only noise
# as a GitHub README badge target (see _PLATFORM_LABEL_HOSTS["GitHub"]) —
# shared on X/Reddit/etc. they're usually the actual announcement. Likewise
# discord.com itself (unlike the discord.gg invite-shortlink domain) hosts
# real pages (blog posts, docs), so it's not treated as noise.
_NOISE_HOSTS = frozenset({
    "shields.io", "badge.fury.io", "codecov.io", "coveralls.io",
    "travis-ci.org", "travis-ci.com", "circleci.com",
    "githubusercontent.com",
    "patreon.com", "ko-fi.com", "buymeacoffee.com",
    "discord.gg", "linktr.ee",
})

# A bare profile link (one path segment, e.g. twitter.com/someone) is never
# the post's actual subject — unlike a post/status link (multiple segments),
# which is real content. A query string is excluded from this check since
# some platforms' real content links carry the ID there instead of in the
# path (e.g. facebook.com/watch/?v=... or permalink.php?story_fbid=...).
_BARE_PROFILE_HOSTS = frozenset({"twitter.com", "x.com", "instagram.com", "facebook.com", "fb.com"})


def _is_noise_host(host: str) -> bool:
    normalized = host[4:] if host.startswith("www.") else host
    return any(normalized == d or normalized.endswith("." + d) for d in _NOISE_HOSTS)


def _is_bare_profile_link(host: str, path: str, query: str = "") -> bool:
    normalized = host[4:] if host.startswith("www.") else host
    if not any(normalized == d or normalized.endswith("." + d) for d in _BARE_PROFILE_HOSTS):
        return False
    if query:
        return False
    segment = path.strip("/")
    return bool(segment) and "/" not in segment


def _is_platform_host(host: str) -> bool:
    # Host-exact/suffix matching, not substring matching on the full URL —
    # detect_url_type()'s "x.com" in url check also matches unrelated
    # domains like dropbox.com/vox.com ("...bo[x.com]"), which is fine for
    # its original single-URL use but wrongly sweeps in nav/CDN noise once
    # a whole article body gets scanned for several links.
    host = host.lower()
    if host.startswith("www."):
        host = host[4:]
    return any(host == domain or host.endswith("." + domain) for domain in _PLATFORM_HOSTS)


_MAX_REDIRECTOR_RESOLUTIONS = 8


def _find_platform_urls(
    text: str, max_links: int = 4, exclude_hosts: frozenset = frozenset(), allow_any_host: bool = False
) -> List[str]:
    from urllib.parse import urlsplit

    stripped = _strip_image_markdown(text)
    found = []
    resolved_cache = {}
    network_resolutions = 0
    for match in re.finditer(r'https?://[^\s)\]*<"\']+', stripped):
        raw_candidate = match.group(0).rstrip(").,;:!?\"'][}{")

        if raw_candidate in resolved_cache:
            candidate = resolved_cache[raw_candidate]
        else:
            raw_host = urlsplit(raw_candidate).netloc.lower()
            raw_normalized = raw_host[4:] if raw_host.startswith("www.") else raw_host
            if raw_normalized in _REDIRECTOR_NETWORK_HOSTS:
                if network_resolutions >= _MAX_REDIRECTOR_RESOLUTIONS:
                    continue
                network_resolutions += 1
            candidate = _resolve_redirector(raw_candidate)
            resolved_cache[raw_candidate] = candidate

        if candidate in found:
            continue
        if any(marker in candidate.lower() for marker in _SHARE_PATH_MARKERS):
            continue
        candidate_parts = urlsplit(candidate)
        host = candidate_parts.netloc.lower()
        normalized_host = host[4:] if host.startswith("www.") else host
        if any(normalized_host == d or normalized_host.endswith("." + d) for d in exclude_hosts):
            continue
        # Still on a wrapper host means resolution failed or never ran —
        # a bare redirector link is never real content on its own, so
        # this is excluded regardless of allow_any_host.
        if normalized_host in _REDIRECTOR_NETWORK_HOSTS:
            continue
        if _is_noise_host(host) or _is_bare_profile_link(host, candidate_parts.path, candidate_parts.query):
            continue
        if not allow_any_host and not _is_platform_host(host):
            continue
        found.append(candidate)
        if len(found) >= max_links:
            break
    return found


def extract_reddit(url: str, follow_links: bool = True):
    import xml.etree.ElementTree as ET

    ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}

    def _clean_html(raw_html: str):
        # get_text() discards <a href> targets, keeping only the link's
        # visible text — return hrefs separately so a hyperlinked (not
        # bare-pasted) link can still be found and followed.
        if not raw_html:
            return "", []
        soup = BeautifulSoup(raw_html, "html.parser")
        hrefs = [a.get("href") for a in soup.find_all("a", href=True) if a.get("href")]
        return soup.get_text(separator=" ", strip=True), hrefs

    try:
        _throttle_reddit_request()
        resolved = requests.get(
            url, timeout=10, headers={"User-Agent": "rag-knowledge-base/1.0"}, allow_redirects=True
        ).url
        clean_url = resolved.split("?")[0].split("#")[0].rstrip("/")
        rss_url = f"{clean_url}/.rss"

        response = None
        for attempt in range(3):
            _throttle_reddit_request()
            response = requests.get(
                rss_url, timeout=15, headers={"User-Agent": "rag-knowledge-base/1.0"}
            )
            if response.status_code == 429:
                time.sleep(2 * (attempt + 1))
                continue
            break

        if response is None or response.status_code != 200:
            status = response.status_code if response is not None else "no response"
            return None, "failed", f"Reddit returned status {status}"

        root = ET.fromstring(response.content)
        feed_title_el = root.find("atom:title", ATOM_NS)
        feed_title = feed_title_el.text.strip() if feed_title_el is not None and feed_title_el.text else ""

        entries = root.findall("atom:entry", ATOM_NS)
        if not entries:
            return None, "failed", "Reddit post had no entries"

        post_entry = entries[0]
        post_author_el = post_entry.find("atom:author/atom:name", ATOM_NS)
        post_author = post_author_el.text.strip() if post_author_el is not None and post_author_el.text else ""
        post_content_el = post_entry.find("atom:content", ATOM_NS)
        post_text, post_href_urls = _clean_html(post_content_el.text if post_content_el is not None else "")

        parts = [f"Title: {feed_title}", f"Author: {post_author}"]
        if post_text:
            parts.append(f"Post:\n{post_text}")

        comment_lines = []
        comment_href_urls = []
        for entry in entries[1:16]:
            author_el = entry.find("atom:author/atom:name", ATOM_NS)
            author = author_el.text.strip() if author_el is not None and author_el.text else "unknown"
            content_el = entry.find("atom:content", ATOM_NS)
            body, comment_hrefs = _clean_html(content_el.text if content_el is not None else "")
            comment_href_urls.extend(comment_hrefs)
            if not body:
                continue
            comment_lines.append(f"- {author}: {body}")

        if comment_lines:
            parts.append("Top Comments:\n" + "\n".join(comment_lines))

        text = "\n\n".join(parts).strip()
        if len(text) > 50:
            if follow_links:
                # The post's own hyperlinked target (priority_scan_text) must
                # outrank comment links (extra_scan_text) — it's the reason
                # the post exists, and must not lose its slot in the
                # max_links cap to a handful of comments that happen to
                # paste a bare URL.
                text = _append_linked_content(
                    text,
                    priority_scan_text=" ".join(post_href_urls),
                    extra_scan_text=" ".join(comment_href_urls),
                    exclude_hosts=_PLATFORM_LABEL_HOSTS.get("Reddit", frozenset()),
                    allow_any_host=True,
                )
            return text, "reddit_rss", None

        return None, "failed", "Reddit post had no usable content"
    except Exception as e:
        return None, "failed", f"Reddit extraction failed: {e}"


def extract_github(url: str, follow_links: bool = True):
    import base64

    match = re.search(r"github\.com/([^/]+)/([^/?#]+)", url)
    if not match:
        return None, "failed", "Could not parse a GitHub owner/repo from the URL"

    owner, repo = match.group(1), match.group(2)
    headers = {"User-Agent": "rag-knowledge-base/1.0", "Accept": "application/vnd.github+json"}

    try:
        repo_response = requests.get(
            f"https://api.github.com/repos/{owner}/{repo}", headers=headers, timeout=15
        )
        if repo_response.status_code != 200:
            return None, "failed", f"GitHub returned status {repo_response.status_code} for {owner}/{repo}"
        repo_data = repo_response.json()
    except Exception as e:
        return None, "failed", f"GitHub extraction failed: {e}"

    parts = [
        f"Title: {repo_data.get('full_name', f'{owner}/{repo}')}",
        f"Description: {repo_data.get('description') or 'No description provided.'}",
        f"Topics: {', '.join(repo_data.get('topics', [])) or 'none'}",
        f"Stars: {repo_data.get('stargazers_count', 0)}",
    ]

    try:
        readme_response = requests.get(
            f"https://api.github.com/repos/{owner}/{repo}/readme", headers=headers, timeout=15
        )
        if readme_response.status_code == 200:
            readme_data = readme_response.json()
            content_b64 = readme_data.get("content", "")
            readme_text = base64.b64decode(content_b64).decode("utf-8", errors="replace")
            parts.append(f"README:\n{readme_text}")
    except Exception:
        pass  # no README is fine — metadata alone is still useful

    text = "\n\n".join(parts).strip()
    if follow_links:
        text = _append_linked_content(
            text, exclude_hosts=_PLATFORM_LABEL_HOSTS.get("GitHub", frozenset()), allow_any_host=True
        )
    return text, "github_api", None


def _extract_for_type(url: str, url_type: str, follow_links: bool = True):
    """Dispatch to the right extractor for a detected type.

    `follow_links` is passed through to every extractor, each of which can
    itself follow a link found inside its content; it's set False when
    this is itself being called to fetch a *linked* piece of content, so
    following never recurses more than one level deep.
    """
    if url_type == "youtube":
        text, quality, error = extract_youtube(url, follow_links=follow_links)
        chunk_size, chunk_overlap = 800, 100
    elif url_type == "linkedin":
        text, quality, error = extract_linkedin(url, follow_links=follow_links)
        chunk_size, chunk_overlap = 512, 50
    elif url_type == "reddit":
        text, quality, error = extract_reddit(url, follow_links=follow_links)
        chunk_size, chunk_overlap = 512, 50
    elif url_type == "x":
        text, quality, error = extract_x(url, follow_links=follow_links)
        chunk_size, chunk_overlap = 512, 50
    elif url_type == "facebook":
        text, quality, error = extract_facebook(url, follow_links=follow_links)
        chunk_size, chunk_overlap = 512, 50
    elif url_type == "instagram":
        text, quality, error = extract_instagram(url, follow_links=follow_links)
        chunk_size, chunk_overlap = 512, 50
    elif url_type == "github":
        text, quality, error = extract_github(url, follow_links=follow_links)
        chunk_size, chunk_overlap = 512, 50
    else:
        text, quality, error = extract_article(url, follow_links=follow_links)
        chunk_size, chunk_overlap = 512, 50

    return text, quality, error, chunk_size, chunk_overlap


def _append_linked_content(
    text: str,
    max_links: int = 4,
    extra_scan_text: str = "",
    priority_scan_text: str = "",
    exclude_hosts: frozenset = frozenset(),
    allow_any_host: bool = False,
) -> str:
    # extra_scan_text/priority_scan_text let a caller feed in links that
    # don't appear as bare URLs in `text` itself (e.g. <a href> targets
    # BeautifulSoup's get_text() already discarded) without those raw
    # URLs polluting the stored/returned content. Candidates are scanned
    # in the order priority_scan_text, then text, then extra_scan_text —
    # priority_scan_text exists so a caller can rank "the subject itself"
    # (e.g. a Reddit link-post's own target) ahead of secondary content
    # (e.g. comments) that might otherwise fill the max_links cap first.
    scan_text = " ".join(part for part in (priority_scan_text, text, extra_scan_text) if part)
    result = text
    for url in _find_platform_urls(
        scan_text, max_links=max_links, exclude_hosts=exclude_hosts, allow_any_host=allow_any_host
    ):
        content = _fetch_linked_content(url)
        if content:
            result += f"\n\nLinked Content: {url}\n{content}"
    return result


def _fetch_linked_content(url: str):
    """Fetch a URL found inside a post, using the right extractor for
    whatever it turns out to be, instead of always treating it as a
    generic article. Never follows further links itself (depth-limited
    to one level)."""
    try:
        url_type = detect_url_type(url)
        text, _, _, _, _ = _extract_for_type(url, url_type, follow_links=False)
        return text
    except Exception:
        return None


_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "igshid", "igsh", "gclid", "ref", "ref_src", "exln", "dlrf", "si",
}


def _normalize_url(url: str) -> str:
    """Strip known share/tracking query params so the same post shared
    via different "Copy Link" taps doesn't create duplicate KB entries."""
    from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

    parts = urlsplit(url)
    kept_params = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme, parts.netloc, path, urlencode(kept_params), ""))


def ingest_url(url: str) -> dict:
    url = _normalize_url(url)
    collection = get_collection()
    embed_model = get_embed_model()

    # Deduplication check
    existing = collection.get(where={"source": url}, limit=1)
    if existing and existing["ids"]:
        return {
            "success": False,
            "duplicate": True,
            "message": "URL already exists in knowledge base",
        }

    # Detect type and extract
    url_type = detect_url_type(url)
    text, quality, error, chunk_size, chunk_overlap = _extract_for_type(url, url_type)

    if not text:
        return {
            "success": False,
            "duplicate": False,
            "message": f"Could not extract content: {error}",
        }

    # Strip markdown image syntax (Jina Reader renders embedded images as
    # `[Image N: ...](long-cdn-url)` links, which otherwise get chunked as
    # if they were real text and drown out the actual content).
    text = _strip_image_markdown(text).strip()
    if not text:
        return {
            "success": False,
            "duplicate": False,
            "message": "Content was only images, no extractable text",
        }

    # Chunk the text
    splitter = SentenceSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    chunks = splitter.split_text(text)
    chunks = [c for c in chunks if len(c.strip()) > 30]

    if not chunks:
        return {
            "success": False,
            "duplicate": False,
            "message": "Text extracted but could not be chunked",
        }

    # Embed (batched in one call, not one chunk at a time) and store
    documents_list = chunks
    embeddings_list = embed_model.get_text_embedding_batch(chunks, show_progress=False)
    ids_list = [str(uuid.uuid4()) for _ in chunks]
    ingested_at = datetime.now(timezone.utc).isoformat()
    metadatas_list = [
        {
            "source": url,
            "type": url_type,
            "date_ingested": ingested_at,
            "extraction_quality": quality,
        }
        for _ in chunks
    ]

    collection.add(
        documents=documents_list,
        embeddings=embeddings_list,
        ids=ids_list,
        metadatas=metadatas_list,
    )

    return {
        "success": True,
        "duplicate": False,
        "chunks_stored": len(documents_list),
        "extraction_quality": quality,
        "url_type": url_type,
        "source_type": url_type,
        "message": f"Successfully stored {len(documents_list)} chunks",
    }


def format_ingest_reply(result: dict) -> str:
    if result.get("duplicate"):
        return "⚠️ URL already exists in knowledge base"
    if result.get("success"):
        return (
            f"✅ Added — {result.get('chunks_stored', 0)} chunks stored "
            f"(type: {result.get('url_type', 'unknown')}, "
            f"quality: {result.get('extraction_quality', 'unknown')})"
        )
    return f"❌ Failed: {result.get('message', 'Ingestion failed.')}"


def remove_source(url: str) -> dict:
    url = _normalize_url(url)
    collection = get_collection()

    existing = collection.get(where={"source": url}, limit=1)
    if not existing or not existing["ids"]:
        return {"success": False, "message": "URL not found in knowledge base"}

    collection.delete(where={"source": url})
    return {"success": True, "message": f"Removed source: {url}"}


def format_remove_reply(result: dict) -> str:
    if result.get("success"):
        return f"🗑️ {result.get('message', 'Removed.')}"
    return f"❌ {result.get('message', 'Removal failed.')}"


def list_ingested_sources() -> list:
    collection = get_collection()
    if collection.count() == 0:
        return []
    results = collection.get(include=["metadatas"])
    seen = {}
    for meta in results["metadatas"]:
        src = meta.get("source", "")
        if src and src not in seen:
            seen[src] = meta.get("type", "article")
    return [{"source": s, "type": t} for s, t in seen.items()]
