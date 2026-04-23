import os
import re
import uuid
from datetime import datetime, timezone

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


def get_collection():
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    return client.get_or_create_collection(COLLECTION_NAME)


def get_embed_model():
    return HuggingFaceEmbedding(model_name=EMBED_MODEL_NAME)


def detect_url_type(url: str) -> str:
    if "youtube.com" in url or "youtu.be" in url:
        return "youtube"
    elif "linkedin.com" in url:
        return "linkedin"
    else:
        return "article"


def extract_youtube(url: str):
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
                return text, "yt_dlp_meta", None

    except ImportError:
        print("[DEBUG] yt-dlp not installed")
    except Exception as e:
        print(f"[DEBUG] yt-dlp failed: {e}")

    return None, "failed", "All YouTube extraction strategies failed"


def extract_article(url: str):
    # Try Jina Reader first
    try:
        jina_url = f"https://r.jina.ai/{url}"
        response = requests.get(jina_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        if response.status_code == 200 and len(response.text.strip()) > 300:
            return response.text.strip(), "full_text", None
    except Exception:
        pass

    # BeautifulSoup fallback
    try:
        response = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        content = ""
        for selector in ["article", "main", "div.content", "div.post"]:
            el = soup.select_one(selector)
            if el:
                content = el.get_text(separator=" ", strip=True)
                break

        if not content:
            content = " ".join(p.get_text(strip=True) for p in soup.find_all("p"))

        if len(content.strip()) > 200:
            return content.strip(), "full_text", None
    except Exception:
        pass

    return None, "failed", "Could not extract content"


def extract_linkedin(url: str):
    # Try Jina first for LinkedIn
    try:
        jina_url = f"https://r.jina.ai/{url}"
        response = requests.get(jina_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        if response.status_code == 200 and len(response.text.strip()) > 200:
            return response.text.strip(), "full_text", None
    except Exception:
        pass

    # Meta tags fallback
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
            return text.strip(), "meta_only", None
    except Exception:
        pass

    return None, "failed", "LinkedIn blocked extraction"


def ingest_url(url: str) -> dict:
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

    if url_type == "youtube":
        text, quality, error = extract_youtube(url)
        chunk_size, chunk_overlap = 800, 100
    elif url_type == "linkedin":
        text, quality, error = extract_linkedin(url)
        chunk_size, chunk_overlap = 512, 50
    else:
        text, quality, error = extract_article(url)
        chunk_size, chunk_overlap = 512, 50

    if not text:
        return {
            "success": False,
            "duplicate": False,
            "message": f"Could not extract content: {error}",
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

    # Embed and store directly in ChromaDB
    documents_list = []
    embeddings_list = []
    ids_list = []
    metadatas_list = []

    for chunk in chunks:
        embedding = embed_model.get_text_embedding(chunk)
        documents_list.append(chunk)
        embeddings_list.append(embedding)
        ids_list.append(str(uuid.uuid4()))
        metadatas_list.append(
            {
                "source": url,
                "type": url_type,
                "date_ingested": datetime.now(timezone.utc).isoformat(),
                "extraction_quality": quality,
            }
        )

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
