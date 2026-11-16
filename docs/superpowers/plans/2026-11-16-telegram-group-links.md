# Telegram Group Link-Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let anyone in one designated Telegram group post a link and have it silently ingested into the shared RAG knowledge base, while the bot ignores every other group message (no Q&A, no accidental replies).

**Architecture:** A second `MessageHandler` is registered in `telegram_bot.py`, scoped at registration time to one chat ID via `filters.Chat(chat_id=...)`. It reuses the existing `extract_first_url()` / `ingest_url()` / `format_ingest_reply()` functions already used by the DM flow. The existing DM handler gets narrowed to `filters.ChatType.PRIVATE` so the two flows never overlap.

**Tech Stack:** Python, `python-telegram-bot` (`Application`, `MessageHandler`, `filters`), `pytest` + `unittest.mock` for tests (matching `tests/test_telegram_bot.py`'s existing style).

**Spec:** `docs/superpowers/specs/2026-11-16-telegram-group-links-design.md`

## Global Constraints

- New optional env var `TELEGRAM_GROUP_CHAT_ID`. Unset → group support is off entirely (no handler registered).
- Reuses `extract_first_url()`, `ingest_url()`, `format_ingest_reply()` unmodified — no changes to `ingest.py`.
- The group handler must never send a reply for a message with no URL in it — not even an error or ack.
- Group replies skip the `"⏳ Processing..."` ack the DM flow sends — only the final `format_ingest_reply()` result is sent, to keep the group quieter.
- The DM handler's existing behavior (Q&A + ingestion, open to owner + approved users) is unchanged except for being scoped to private chats.
- Telegram bot "privacy mode" must be disabled via @BotFather for the group handler to ever see non-mention messages — this is a manual setup step to document, not something code controls.

## Review Focus

- A group message mixes ordinary text and a URL (e.g. `"check this out https://..."`) — it must still be detected and ingested, not treated as a no-URL message. → Task 2.
- A group message contains two or more URLs — only the first is ingested (same as the existing DM behavior), so group and DM don't silently diverge. → Task 2.
- A link reposted in the group that's already in the knowledge base — must get the existing "already exists" duplicate reply, not be mistaken for "no URL" and go silent. → Task 2.
- A non-text group message (sticker, photo, etc.) where `update.message.text` is `None` — must not crash the handler. → Task 2.
- `TELEGRAM_GROUP_CHAT_ID` is set to a non-numeric value — must fail fast with a clear error at startup, not silently disable the feature or crash deep inside filter construction. → Task 1.

---

### Task 1: Group chat ID config helper

**Files:**
- Modify: `telegram_bot.py`
- Test: `tests/test_telegram_bot.py`

**Interfaces:**
- Produces: `get_group_chat_id() -> Optional[int]` — `None` when `TELEGRAM_GROUP_CHAT_ID` is unset or blank; the parsed `int` when it's set and numeric; raises `RuntimeError` when it's set but non-numeric.

- [ ] **Step 1: Write the failing tests**

```python
def test_get_group_chat_id_missing_returns_none(monkeypatch):
    from telegram_bot import get_group_chat_id
    monkeypatch.delenv("TELEGRAM_GROUP_CHAT_ID", raising=False)
    assert get_group_chat_id() is None


def test_get_group_chat_id_present_returns_int(monkeypatch):
    from telegram_bot import get_group_chat_id
    monkeypatch.setenv("TELEGRAM_GROUP_CHAT_ID", "-1001234567890")
    assert get_group_chat_id() == -1001234567890


def test_get_group_chat_id_non_numeric_raises(monkeypatch):
    from telegram_bot import get_group_chat_id
    monkeypatch.setenv("TELEGRAM_GROUP_CHAT_ID", "not-a-number")
    with pytest.raises(RuntimeError):
        get_group_chat_id()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_telegram_bot.py -k get_group_chat_id -v`
Expected: FAIL with `ImportError`/`AttributeError` (`get_group_chat_id` not defined)

- [ ] **Step 3: Implement `get_group_chat_id() -> Optional[int]` in `telegram_bot.py`**

Mirror `get_allowed_user_id()`'s existing numeric-parsing/error pattern, but return `None` for a blank/missing value instead of raising (this one is optional; `get_allowed_user_id()` is mandatory, so leave that function untouched).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_telegram_bot.py -k get_group_chat_id -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add telegram_bot.py tests/test_telegram_bot.py
git commit -m "feat: add TELEGRAM_GROUP_CHAT_ID config helper"
```

---

### Task 2: Group message handler

**Files:**
- Modify: `telegram_bot.py`
- Test: `tests/test_telegram_bot.py`

**Interfaces:**
- Consumes: `extract_first_url(text: str) -> Optional[str]` (existing), `ingest_url(url: str) -> dict` (existing, from `ingest.py`), `format_ingest_reply(result: dict) -> str` (existing, from `ingest.py`).
- Produces: `build_group_reply(text: str) -> Optional[str]` — `None` means "send nothing"; a string means "reply with this." `async handle_group_message(update, context) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
def test_build_group_reply_returns_none_without_url():
    from telegram_bot import build_group_reply
    assert build_group_reply("just chatting, no link here") is None


def test_build_group_reply_returns_none_for_empty_text():
    from telegram_bot import build_group_reply
    assert build_group_reply("") is None


def test_build_group_reply_ingests_url_found_in_mixed_text():
    from telegram_bot import build_group_reply
    with patch(
        "telegram_bot.ingest_url",
        return_value={"success": True, "duplicate": False, "chunks_stored": 2, "extraction_quality": "full_text", "url_type": "article"},
    ) as mock_ingest:
        reply = build_group_reply("check this out https://example.com/post")
    mock_ingest.assert_called_once_with("https://example.com/post")
    assert reply is not None and "2" in reply


def test_build_group_reply_ingests_only_first_of_multiple_urls():
    from telegram_bot import build_group_reply
    with patch(
        "telegram_bot.ingest_url",
        return_value={"success": True, "duplicate": False, "chunks_stored": 1, "extraction_quality": "full_text", "url_type": "article"},
    ) as mock_ingest:
        build_group_reply("https://a.com/1 and https://b.com/2")
    mock_ingest.assert_called_once_with("https://a.com/1")


def test_build_group_reply_formats_duplicate():
    from telegram_bot import build_group_reply
    with patch(
        "telegram_bot.ingest_url",
        return_value={"success": True, "duplicate": True, "message": "URL already exists in knowledge base"},
    ):
        reply = build_group_reply("https://example.com/post")
    assert "already exists" in reply.lower()


def test_build_group_reply_catches_exception_from_ingest():
    from telegram_bot import build_group_reply
    with patch("telegram_bot.ingest_url", side_effect=RuntimeError("boom")):
        reply = build_group_reply("https://example.com/post")
    assert "boom" in reply


def test_handle_group_message_sends_no_reply_without_url():
    update = _make_update(111, "just chatting")
    asyncio.run(handle_group_message(update, None))
    update.message.reply_text.assert_not_called()


def test_handle_group_message_sends_no_reply_for_none_text():
    update = _make_update(111, None)
    asyncio.run(handle_group_message(update, None))
    update.message.reply_text.assert_not_called()


def test_handle_group_message_sends_reply_for_link():
    update = _make_update(111, "https://example.com/post")
    with patch("telegram_bot.build_group_reply", return_value="✅ done"):
        asyncio.run(handle_group_message(update, None))
    update.message.reply_text.assert_called_once_with("✅ done")
```

(`_make_update` and `asyncio` are already imported/defined in `tests/test_telegram_bot.py`; `_make_update`'s `update.message.text = text` already handles `None` since it's a plain assignment.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_telegram_bot.py -k "group_reply or group_message" -v`
Expected: FAIL (`build_group_reply`/`handle_group_message` not defined)

- [ ] **Step 3: Implement `build_group_reply(text: str) -> Optional[str]` and `async handle_group_message(update, context) -> None` in `telegram_bot.py`**

`build_group_reply` mirrors `build_reply`'s existing `try/except` ingestion branch exactly (same `f"❌ Error: {e}"` shape on exception), but returns `None` immediately when `extract_first_url(text)` finds nothing — it never falls through to a query, unlike `build_reply`. `handle_group_message` reads `update.message.text or ""`, calls `build_group_reply`, and only calls `await update.message.reply_text(...)` when the result isn't `None`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_telegram_bot.py -k "group_reply or group_message" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add telegram_bot.py tests/test_telegram_bot.py
git commit -m "feat: add group-chat link handler that ignores non-link messages"
```

---

### Task 3: Wire handlers in `main()`, document group setup

**Files:**
- Modify: `telegram_bot.py` (`main()`)
- Modify: `README.md`

**Interfaces:**
- Consumes: `get_group_chat_id()` and `handle_group_message` (Tasks 1–2), existing `handle_message` and `get_allowed_user_id()`.
- Produces: none (terminal task — nothing later depends on `main()`'s internals).

- [ ] **Step 1: Modify `main()` in `telegram_bot.py`**

Scope the existing DM handler to `filters.TEXT & filters.ChatType.PRIVATE` (currently unscoped `filters.TEXT`). After building `application`, call `get_group_chat_id()`; if it returns a value, register a second `MessageHandler(filters.TEXT & filters.Chat(chat_id=group_chat_id), handle_group_message)`. Order doesn't matter since the two filters are mutually exclusive by chat type/ID.

- [ ] **Step 2: Manually verify handler registration**

`main()` isn't unit-tested today (no existing test covers it) and isn't started here either — this step is a one-off manual probe, not a new permanent test. Run in the project's venv:

```bash
python -c "
import os
os.environ['TELEGRAM_BOT_TOKEN'] = '123:fake'
os.environ['TELEGRAM_ALLOWED_USER_ID'] = '111'
os.environ['TELEGRAM_GROUP_CHAT_ID'] = '-1009876543210'
from telegram.ext import Application
import telegram_bot

application = Application.builder().token(telegram_bot.get_bot_token()).build()
from telegram.ext import MessageHandler, filters
application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, telegram_bot.handle_message))
group_chat_id = telegram_bot.get_group_chat_id()
assert group_chat_id == -1009876543210
application.add_handler(MessageHandler(filters.TEXT & filters.Chat(chat_id=group_chat_id), telegram_bot.handle_group_message))
handlers = application.handlers[0]
assert len(handlers) == 2, handlers
print('OK: both handlers registered', handlers)
"
```

Expected: prints `OK: both handlers registered ...` with no assertion error.

- [ ] **Step 3: Document the feature in `README.md`**

Add a subsection under "Telegram Bot (optional second entry point)" (after the existing "Invite other people" section) covering: (a) adding the bot to the target group, (b) disabling the bot's privacy mode via @BotFather (`/mypbots` → bot → Bot Settings → Group Privacy → Turn off) so it can see non-mention messages, (c) finding the group's numeric chat ID (send any message in the group, then call `https://api.telegram.org/bot<token>/getUpdates` and read `message.chat.id` — it will be negative for groups), (d) setting `TELEGRAM_GROUP_CHAT_ID` in `.env`, (e) the resulting behavior: links get ingested with a confirmation reply, everything else is ignored, no Q&A in the group.

- [ ] **Step 4: Run the full test suite**

Run: `pytest -q`
Expected: all tests pass (existing + Tasks 1–2's new tests)

- [ ] **Step 5: Commit**

```bash
git add telegram_bot.py README.md
git commit -m "feat: wire group-chat handler into main() and document setup"
```
