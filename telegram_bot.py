"""Telegram bot: a second entry point into the same RAG knowledge base."""

import os
import re
from typing import Optional

from dotenv import load_dotenv

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
