"""Telegram bot: a second entry point into the same RAG knowledge base."""

import os

from dotenv import load_dotenv

load_dotenv()


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
