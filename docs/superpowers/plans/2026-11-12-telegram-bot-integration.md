# Telegram Bot Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a standalone Telegram bot (`telegram_bot.py`) that lets the single authorized user ingest links and ask questions through Telegram, reusing the existing `ingest_url()` and `query_knowledge_base()` pipeline untouched.

**Architecture:** The bot's business logic (URL detection, authorization check, reply formatting, and the ingest-vs-query decision) is built as small, pure, synchronous functions with no Telegram or asyncio dependency, so they're fully unit-testable with pytest. A thin async handler wired to `python-telegram-bot`'s long-polling `Application` is the only part that touches the Telegram API, and it does nothing but call those pure functions and send the replies.

**Tech Stack:** Python, `python-telegram-bot` (new dependency), `pytest` (new dev dependency), existing `ingest.py`/`query.py`/`python-dotenv`.

**Spec:** `docs/superpowers/specs/2026-11-12-telegram-integration-design.md`

## Global Constraints

- Long polling only — no public webhook, no hosted server (per spec Architecture section).
- Single authorized user only, checked against `TELEGRAM_ALLOWED_USER_ID` — no multi-user allowlist (per spec Scope).
- URL-only ingestion input — no raw pasted-text ingestion in this iteration (per spec Scope, explicitly deferred).
- Synchronous processing only — no background thread/queue (per spec Message handling logic).
- `telegram_bot.py` must call `ingest_url()` (from `ingest.py`) and `query_knowledge_base()` (from `query.py`) directly, with zero duplicated extraction/retrieval logic (per spec Architecture).
- New dependency: `python-telegram-bot`, added to `requirements.txt` (per spec Credentials & configuration).
- `.env` already contains `TELEGRAM_BOT_TOKEN` (format `<digits>:<35-char secret>`) and `TELEGRAM_ALLOWED_USER_ID` (numeric), verified present this session — no new `.env` values need to be sourced from the user.
- Missing/empty `TELEGRAM_BOT_TOKEN` or `TELEGRAM_ALLOWED_USER_ID` at startup must fail fast with a clear error, not start in a broken state (per spec Credentials & configuration).

## Review Focus

- Missing or empty `TELEGRAM_BOT_TOKEN`/`TELEGRAM_ALLOWED_USER_ID` at startup should raise a clear, immediate error rather than failing obscurely later — Task 1 tests this directly.
- A non-numeric `TELEGRAM_ALLOWED_USER_ID` value should fail fast at startup with a clear error, not crash later on an `int()` cast at message-handling time — Task 1 tests this directly.
- A message from a sender whose user ID doesn't match `TELEGRAM_ALLOWED_USER_ID` must be silently ignored (no reply sent at all) — Task 5 tests this directly.
- An empty or whitespace-only message (no URL) must produce a graceful "please enter a question"-style reply, not a crash — Task 4 tests this directly.
- An unexpected exception from `ingest_url()` or `query_knowledge_base()` must be caught and turned into a short, readable error reply, never propagate and crash the bot process — Task 4 tests this directly.

---

## File Structure

- **Create:** `telegram_bot.py` — the entire new bot: credential loading, pure business-logic functions, the async Telegram handler, and `main()`.
- **Create:** `tests/test_telegram_bot.py` — unit tests for every pure function and the handler, with `ingest_url`/`query_knowledge_base`/Telegram objects mocked.
- **Modify:** `requirements.txt` — add `python-telegram-bot` and `pytest`.
- **Modify:** `README.md` — add a "Telegram Bot" setup/run section.

---

### Task 1: Credential loading

**Files:**
- Create: `telegram_bot.py`
- Modify: `requirements.txt`
- Test: `tests/test_telegram_bot.py`

**Interfaces:**
- Produces: `get_bot_token() -> str`, `get_allowed_user_id() -> int`, both raising `RuntimeError` with a clear message on missing/invalid config. Later tasks and `main()` call these.

- [ ] **Step 1: Add dependencies**

Add `python-telegram-bot` and `pytest` as new lines to `requirements.txt`.

- [ ] **Step 2: Install dependencies**

Run: `pip install -r requirements.txt`
Expected: installs without error.

- [ ] **Step 3: Write the failing tests**

```python
# tests/test_telegram_bot.py
import pytest
from telegram_bot import get_bot_token, get_allowed_user_id

def test_get_bot_token_missing_raises(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    with pytest.raises(RuntimeError):
        get_bot_token()

def test_get_bot_token_present(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:abcdefghijklmnopqrstuvwxyz0123456789")
    assert get_bot_token() == "123456789:abcdefghijklmnopqrstuvwxyz0123456789"

def test_get_allowed_user_id_missing_raises(monkeypatch):
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_ID", raising=False)
    with pytest.raises(RuntimeError):
        get_allowed_user_id()

def test_get_allowed_user_id_non_numeric_raises(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_ID", "not-a-number")
    with pytest.raises(RuntimeError):
        get_allowed_user_id()

def test_get_allowed_user_id_present(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_ID", "123456789")
    assert get_allowed_user_id() == 123456789
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `pytest tests/test_telegram_bot.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'telegram_bot'`

- [ ] **Step 5: Implement `get_bot_token() -> str` and `get_allowed_user_id() -> int` in `telegram_bot.py`**

Start the file with `from dotenv import load_dotenv` + `load_dotenv()` + `import os` (same pattern as `ingest.py`/`query.py`). Each function reads its env var fresh via `os.getenv` on every call (don't cache at import time, so tests can monkeypatch per-test). Raise `RuntimeError` with a message naming the missing/invalid variable when the value is missing, empty, or (for the user id) not parseable as `int`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_telegram_bot.py -v`
Expected: PASS (5 passed)

- [ ] **Step 7: Commit**

```bash
git add telegram_bot.py requirements.txt tests/test_telegram_bot.py
git commit -m "feat: add Telegram bot credential loading"
```

---

### Task 2: URL detection and authorization

**Files:**
- Modify: `telegram_bot.py`
- Test: `tests/test_telegram_bot.py`

**Interfaces:**
- Consumes: none from Task 1.
- Produces: `extract_first_url(text: str) -> str | None`, `is_authorized(user_id: int, allowed_id: int) -> bool`. Used by Task 4's `build_reply` and Task 5's handler.

- [ ] **Step 1: Write the failing tests**

```python
from telegram_bot import extract_first_url, is_authorized

def test_extract_first_url_finds_url():
    assert extract_first_url("check this out https://example.com/page") == "https://example.com/page"

def test_extract_first_url_returns_none_when_no_url():
    assert extract_first_url("what is this about?") is None

def test_extract_first_url_picks_first_of_multiple():
    text = "https://a.com/1 and also https://b.com/2"
    assert extract_first_url(text) == "https://a.com/1"

def test_is_authorized_true_for_matching_id():
    assert is_authorized(111, 111) is True

def test_is_authorized_false_for_other_id():
    assert is_authorized(111, 222) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_telegram_bot.py -v`
Expected: FAIL with `ImportError` (names not defined)

- [ ] **Step 3: Implement `extract_first_url(text: str) -> str | None` and `is_authorized(user_id: int, allowed_id: int) -> bool` in `telegram_bot.py`**

`extract_first_url` uses a simple regex to find the first `http(s)://`-prefixed token in `text` (e.g. `re.search(r"https?://\S+", text)`), returning `None` if no match. `is_authorized` is a one-line equality check.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_telegram_bot.py -v`
Expected: PASS (10 passed)

- [ ] **Step 5: Commit**

```bash
git add telegram_bot.py tests/test_telegram_bot.py
git commit -m "feat: add URL detection and authorization checks"
```

---

### Task 3: Reply formatters

**Files:**
- Modify: `telegram_bot.py`
- Test: `tests/test_telegram_bot.py`

**Interfaces:**
- Consumes: the `dict` shapes returned by `ingest_url()` (`ingest.py`: keys `success`, `duplicate`, `message`, `chunks_stored`, `extraction_quality`, `url_type`) and `query_knowledge_base()` (`query.py`: keys `success`, `answer`, `sources`/`source_urls`, `error`).
- Produces: `format_ingest_reply(result: dict) -> str`, `format_query_reply(result: dict) -> str`. Used by Task 4's `build_reply`.

- [ ] **Step 1: Write the failing tests**

```python
from telegram_bot import format_ingest_reply, format_query_reply

def test_format_ingest_reply_success():
    result = {"success": True, "duplicate": False, "chunks_stored": 6, "extraction_quality": "full_text", "url_type": "article"}
    reply = format_ingest_reply(result)
    assert "6" in reply and "article" in reply

def test_format_ingest_reply_duplicate():
    result = {"success": True, "duplicate": True, "message": "URL already exists in knowledge base"}
    assert "already exists" in format_ingest_reply(result).lower()

def test_format_ingest_reply_failure():
    result = {"success": False, "duplicate": False, "message": "Could not extract content: boom"}
    assert "boom" in format_ingest_reply(result)

def test_format_query_reply_with_sources():
    result = {"success": True, "answer": "It's about X.", "sources": ["https://example.com/a"]}
    reply = format_query_reply(result)
    assert "It's about X." in reply and "https://example.com/a" in reply

def test_format_query_reply_no_sources():
    result = {"success": True, "answer": "General knowledge answer.", "sources": []}
    reply = format_query_reply(result)
    assert "General knowledge answer." in reply

def test_format_query_reply_failure():
    result = {"success": False, "error": "Please enter a question."}
    assert "Please enter a question." in format_query_reply(result)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_telegram_bot.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement `format_ingest_reply(result: dict) -> str` and `format_query_reply(result: dict) -> str` in `telegram_bot.py`**

`format_ingest_reply`: duplicate → "already exists" message; success (not duplicate) → include `chunks_stored` and `url_type`; failure → include `result["message"]`. `format_query_reply`: failure → `result["error"]`; success → `result["answer"]`, plus a "Sources:" block listing `result.get("sources") or result.get("source_urls") or []` when non-empty.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_telegram_bot.py -v`
Expected: PASS (16 passed)

- [ ] **Step 5: Commit**

```bash
git add telegram_bot.py tests/test_telegram_bot.py
git commit -m "feat: add Telegram reply formatters"
```

---

### Task 4: `build_reply` orchestration

**Files:**
- Modify: `telegram_bot.py`
- Test: `tests/test_telegram_bot.py`

**Interfaces:**
- Consumes: `extract_first_url` (Task 2), `format_ingest_reply`/`format_query_reply` (Task 3), `ingest_url` (from `ingest.py`), `query_knowledge_base` (from `query.py`) — both imported at module level in `telegram_bot.py` as `from ingest import ingest_url` / `from query import query_knowledge_base`, so tests patch `telegram_bot.ingest_url` / `telegram_bot.query_knowledge_base`.
- Produces: `build_reply(text: str) -> str`. Used by Task 5's handler.

- [ ] **Step 1: Write the failing tests**

```python
from unittest.mock import patch
from telegram_bot import build_reply

def test_build_reply_ingests_when_url_present():
    with patch("telegram_bot.ingest_url", return_value={"success": True, "duplicate": False, "chunks_stored": 3, "extraction_quality": "full_text", "url_type": "article"}) as mock_ingest:
        reply = build_reply("here: https://example.com/post")
    mock_ingest.assert_called_once_with("https://example.com/post")
    assert "3" in reply

def test_build_reply_queries_when_no_url():
    with patch("telegram_bot.query_knowledge_base", return_value={"success": True, "answer": "It's about X.", "sources": []}) as mock_query:
        reply = build_reply("what is this about?")
    mock_query.assert_called_once_with("what is this about?")
    assert "It's about X." in reply

def test_build_reply_catches_exception_from_ingest():
    with patch("telegram_bot.ingest_url", side_effect=RuntimeError("boom")):
        reply = build_reply("https://example.com/post")
    assert "boom" in reply

def test_build_reply_catches_exception_from_query():
    with patch("telegram_bot.query_knowledge_base", side_effect=RuntimeError("boom")):
        reply = build_reply("a question with no link")
    assert "boom" in reply

def test_build_reply_empty_message_returns_friendly_error():
    with patch("telegram_bot.query_knowledge_base", return_value={"success": False, "error": "Please enter a question."}) as mock_query:
        reply = build_reply("   ")
    mock_query.assert_called_once_with("   ")
    assert "Please enter a question." in reply
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_telegram_bot.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement `build_reply(text: str) -> str` in `telegram_bot.py`**

Import `ingest_url` from `ingest` and `query_knowledge_base` from `query` at module level. `build_reply` calls `extract_first_url(text)`; if a URL is found, call `ingest_url(url)` inside a `try/except Exception as e` (on exception return a short `f"❌ Error: {e}"` string, else `format_ingest_reply(result)`); otherwise do the same with `query_knowledge_base(text)` / `format_query_reply(result)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_telegram_bot.py -v`
Expected: PASS (21 passed)

- [ ] **Step 5: Commit**

```bash
git add telegram_bot.py tests/test_telegram_bot.py
git commit -m "feat: add build_reply orchestration logic"
```

---

### Task 5: Telegram wiring (handler + main)

**Files:**
- Modify: `telegram_bot.py`
- Test: `tests/test_telegram_bot.py`

**Interfaces:**
- Consumes: `is_authorized`/`get_allowed_user_id` (Tasks 1-2), `extract_first_url` (Task 2), `build_reply` (Task 4).
- Produces: `async def handle_message(update, context) -> None`, `def main() -> None`. `main()` is the module's run entry point (called under `if __name__ == "__main__":`).

- [ ] **Step 1: Write the failing tests**

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from telegram_bot import handle_message

def _make_update(user_id, text):
    update = MagicMock()
    update.effective_user.id = user_id
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update

def test_handle_message_ignores_unauthorized_sender():
    update = _make_update(999, "https://example.com")
    with patch("telegram_bot.get_allowed_user_id", return_value=111):
        asyncio.run(handle_message(update, None))
    update.message.reply_text.assert_not_called()

def test_handle_message_replies_for_authorized_sender():
    update = _make_update(111, "https://example.com")
    with patch("telegram_bot.get_allowed_user_id", return_value=111), \
         patch("telegram_bot.build_reply", return_value="done"):
        asyncio.run(handle_message(update, None))
    assert update.message.reply_text.call_count == 2  # ack, then final reply
    final_call_text = update.message.reply_text.call_args_list[-1].args[0]
    assert final_call_text == "done"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_telegram_bot.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement `handle_message` and `main` in `telegram_bot.py`**

`handle_message(update, context)`: read `update.effective_user.id` and `update.message.text`; if `not is_authorized(user_id, get_allowed_user_id())`, return immediately (no reply). Otherwise `await update.message.reply_text(...)` with `"⏳ Processing..."` if `extract_first_url(text)` else `"⏳ Searching..."`, then `await update.message.reply_text(build_reply(text))`. `main()`: call `get_bot_token()` and `get_allowed_user_id()` up front (fail fast before building anything), build a `telegram.ext.Application` with the token, register `handle_message` via `MessageHandler(filters.TEXT, handle_message)`, call `application.run_polling()`. Add `if __name__ == "__main__": main()` at the bottom of the file.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_telegram_bot.py -v`
Expected: PASS (23 passed)

- [ ] **Step 5: Commit**

```bash
git add telegram_bot.py tests/test_telegram_bot.py
git commit -m "feat: wire Telegram message handler and bot entrypoint"
```

---

### Task 6: Documentation and manual end-to-end verification

**Files:**
- Modify: `README.md`
- Test: manual (no new automated tests — this task verifies the real Telegram integration, which needs a live bot/account)

**Interfaces:**
- Consumes: `main()` (Task 5) as the run entry point.
- Produces: nothing further downstream; this is the final task.

- [ ] **Step 1: Add a "Telegram Bot" section to `README.md`**

Document: creating a bot via BotFather (`/newbot`) to get `TELEGRAM_BOT_TOKEN`, getting your numeric id via `@userinfobot` for `TELEGRAM_ALLOWED_USER_ID`, adding both to `.env`, and running `python telegram_bot.py` alongside `streamlit run app.py`.

- [ ] **Step 2: Run the full test suite**

Run: `pytest tests/test_telegram_bot.py -v`
Expected: PASS (23 passed)

- [ ] **Step 3: Verify the module starts correctly**

Run: `python -m py_compile telegram_bot.py`
Expected: no output, exit code 0.

- [ ] **Step 4: Manual verification — unauthorized sender**

Run: `python telegram_bot.py`, then message the bot from a Telegram account other than the one in `TELEGRAM_ALLOWED_USER_ID`.
Expected: no reply at all from the bot.

- [ ] **Step 5: Manual verification — ingestion**

From the authorized account, send a YouTube, Reddit, LinkedIn, or article URL.
Expected: "Processing..." reply, then a success reply with a chunk count; the new source appears in the Streamlit sidebar's "Ingested Sources" list.

- [ ] **Step 6: Manual verification — question answering**

From the authorized account, send a plain-text question about already-ingested content.
Expected: "Searching..." reply, then an answer consistent with asking the same question in the Streamlit UI.

- [ ] **Step 7: Manual verification — malformed input**

From the authorized account, send an empty message and a garbage non-URL string.
Expected: graceful reply in both cases (e.g. "Please enter a question."), no crash; `python telegram_bot.py` keeps running.

- [ ] **Step 8: Manual verification — duplicate URL**

Re-send a URL already ingested in Step 5.
Expected: reply indicating it already exists in the knowledge base.

- [ ] **Step 9: Commit**

```bash
git add README.md
git commit -m "docs: add Telegram bot setup instructions"
```
