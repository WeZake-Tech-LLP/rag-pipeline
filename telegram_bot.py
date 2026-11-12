"""Telegram bot: a second entry point into the same RAG knowledge base."""

import os
import re
from typing import Optional

from dotenv import load_dotenv

from ingest import ingest_url
from query import query_knowledge_base

load_dotenv()

_URL_PATTERN = re.compile(r"https?://\S+")


def get_bot_token() -> str:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set in .env")
    return token


def get_allowed_user_id() -> int:
    raw = os.getenv("TELEGRAM_ALLOWED_USER_ID", "").strip()
    if not raw:
        raise RuntimeError("TELEGRAM_ALLOWED_USER_ID is not set in .env")
    try:
        return int(raw)
    except ValueError:
        raise RuntimeError(
            f"TELEGRAM_ALLOWED_USER_ID must be numeric, got: {raw!r}"
        )


def extract_first_url(text: str) -> Optional[str]:
    match = _URL_PATTERN.search(text)
    return match.group(0) if match else None


def is_authorized(user_id: int, allowed_id: int) -> bool:
    return user_id == allowed_id


def format_ingest_reply(result: dict) -> str:
    if result.get("success") and result.get("duplicate"):
        return "⚠️ URL already exists in knowledge base"
    if result.get("success"):
        return (
            f"✅ Added — {result.get('chunks_stored', 0)} chunks stored "
            f"(type: {result.get('url_type', 'unknown')}, "
            f"quality: {result.get('extraction_quality', 'unknown')})"
        )
    return f"❌ Failed: {result.get('message', 'Ingestion failed.')}"


def format_query_reply(result: dict) -> str:
    if not result.get("success"):
        return result.get("error", "Query failed.")
    reply = result.get("answer", "")
    sources = result.get("sources") or result.get("source_urls") or []
    if sources:
        reply += "\n\nSources:\n" + "\n".join(f"- {s}" for s in sources)
    return reply


def build_reply(text: str) -> str:
    url = extract_first_url(text)
    if url:
        try:
            result = ingest_url(url)
        except Exception as e:
            return f"❌ Error: {e}"
        return format_ingest_reply(result)

    try:
        result = query_knowledge_base(text)
    except Exception as e:
        return f"❌ Error: {e}"
    return format_query_reply(result)
