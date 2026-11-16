"""Telegram bot: a second entry point into the same RAG knowledge base."""

import json
import os
import re
from typing import Optional

from dotenv import load_dotenv
from telegram.ext import Application, MessageHandler, filters

from ingest import ingest_url, format_ingest_reply
from query import query_knowledge_base, format_query_reply

load_dotenv()

_URL_PATTERN = re.compile(r"https?://\S+")
APPROVED_USERS_PATH = "telegram_approved_users.json"


def get_bot_token() -> str:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set in .env")
    return token


def get_invite_code() -> str:
    code = os.getenv("TELEGRAM_INVITE_CODE", "").strip()
    if not code:
        raise RuntimeError("TELEGRAM_INVITE_CODE is not set in .env")
    return code


def load_approved_users() -> set:
    if not os.path.exists(APPROVED_USERS_PATH):
        return set()
    try:
        with open(APPROVED_USERS_PATH) as f:
            return set(json.load(f))
    except (json.JSONDecodeError, ValueError):
        # A corrupt or truncated file must not take authorization down
        # for everyone (the owner's check reads this too) — degrade to
        # "no approved extra users" instead of crashing.
        return set()


def save_approved_users(users: set) -> None:
    tmp_path = APPROVED_USERS_PATH + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(sorted(users), f)
    os.replace(tmp_path, APPROVED_USERS_PATH)


def parse_start_command(text: str) -> Optional[str]:
    match = re.match(r"^/start\s+(\S+)$", text)
    return match.group(1) if match else None


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


def is_authorized(user_id: int, allowed_ids) -> bool:
    return user_id in allowed_ids


def get_all_authorized_ids() -> set:
    return {get_allowed_user_id()} | load_approved_users()




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


async def handle_message(update, context) -> None:
    user_id = update.effective_user.id
    text = update.message.text or ""

    code = parse_start_command(text)
    if code is not None:
        try:
            invite_code = get_invite_code()
        except RuntimeError:
            # TELEGRAM_INVITE_CODE is optional; treat it as "invites
            # disabled" rather than crashing on a stranger's /start.
            return
        if code == invite_code:
            save_approved_users(load_approved_users() | {user_id})
            await update.message.reply_text(
                "✅ You're in! Send a link to save it, or ask a question."
            )
        return

    if not is_authorized(user_id, get_all_authorized_ids()):
        return

    ack = "⏳ Processing..." if extract_first_url(text) else "⏳ Searching..."
    await update.message.reply_text(ack)
    await update.message.reply_text(build_reply(text))


def main() -> None:
    token = get_bot_token()
    get_allowed_user_id()  # fail fast if misconfigured, before starting the bot

    application = Application.builder().token(token).build()
    application.add_handler(MessageHandler(filters.TEXT, handle_message))
    application.run_polling()


if __name__ == "__main__":
    main()
