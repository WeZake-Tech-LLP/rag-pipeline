# Telegram Multi-User Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the owner share one Telegram deep-link with another person, who gains access by tapping "Start" — no manually collected user IDs, no typed commands — while the owner's existing flow keeps working unchanged.

**Architecture:** A new invite-code check runs before the existing authorization check in `handle_message()`. A `/start <code>` message (which Telegram sends automatically when someone opens `https://t.me/<Bot>?start=<code>`) is compared against `TELEGRAM_INVITE_CODE`; on a match, the sender's ID is added to a small JSON file (`telegram_approved_users.json`) and they're welcomed. Everyone else's authorization becomes "is this ID the owner's, or in that approved file" instead of "does it match the one hardcoded ID."

**Tech Stack:** Python, existing `telegram_bot.py` conventions (stdlib `json`, no new dependency).

**Spec:** `docs/superpowers/specs/2026-11-16-telegram-multi-user-design.md`

## Global Constraints

- Reuses `ingest_url()` / `query_knowledge_base()` unmodified — this only changes *who* can message the bot, never what happens once they're in (shared knowledge base, confirmed in the spec's Non-goals).
- New `.env` value: `TELEGRAM_INVITE_CODE`.
- New file `telegram_approved_users.json` added to `.gitignore` — it holds real Telegram user IDs and is runtime state, not source.
- No new dependency.
- The owner's existing `TELEGRAM_ALLOWED_USER_ID` flow must keep working with zero new steps for them.
- A wrong or missing invite code is silently ignored — no reply, no hint about whether the code was close (same philosophy as today's silent-ignore for unauthorized messages).

## Review Focus

- A wrong invite code must be silently ignored, not crash and not reply with anything that confirms/denies the guess — Task 4 tests this directly.
- No `telegram_approved_users.json` file yet (first run) must behave as an empty approved set, not crash — Task 1 tests this directly.
- A previously-approved user's *normal* (non-`/start`) messages must keep working across calls — persistence has to actually round-trip, not just work in-memory for one request — Task 1 and Task 4 test this directly.
- A bare `/start` with no code (someone who found the bot directly, not through the deep link) must not accidentally authorize them — Task 2 and Task 4 test this directly.
- The owner's own ID must keep being authorized with no behavior change — Task 3 tests this directly.

---

## File Structure

- **Modify:** `telegram_bot.py` — add invite-code + approved-users persistence, `/start` parsing, update `is_authorized()`'s signature, update `handle_message()`'s wiring.
- **Modify:** `.gitignore` — add `telegram_approved_users.json`.
- **Modify:** `tests/test_telegram_bot.py` — new tests plus two existing `is_authorized` tests updated for its new signature.

---

### Task 1: Invite code + approved-users file persistence

**Files:**
- Modify: `telegram_bot.py`
- Modify: `.gitignore`
- Test: `tests/test_telegram_bot.py`

**Interfaces:**
- Produces: `get_invite_code() -> str` (raises `RuntimeError` if `TELEGRAM_INVITE_CODE` is missing/empty, same pattern as `get_bot_token()` at `telegram_bot.py:18-22`); `load_approved_users() -> set[int]`; `save_approved_users(users: set[int]) -> None`. Task 3's `get_all_authorized_ids()` and Task 4's `handle_message()` both use these.

- [ ] **Step 1: Write the failing tests**

```python
import pytest

def test_get_invite_code_missing_raises(monkeypatch):
    from telegram_bot import get_invite_code
    monkeypatch.delenv("TELEGRAM_INVITE_CODE", raising=False)
    with pytest.raises(RuntimeError):
        get_invite_code()

def test_get_invite_code_present(monkeypatch):
    from telegram_bot import get_invite_code
    monkeypatch.setenv("TELEGRAM_INVITE_CODE", "secret123")
    assert get_invite_code() == "secret123"

def test_load_approved_users_missing_file_returns_empty_set(tmp_path, monkeypatch):
    import telegram_bot
    monkeypatch.setattr(telegram_bot, "APPROVED_USERS_PATH", str(tmp_path / "approved.json"))
    assert telegram_bot.load_approved_users() == set()

def test_save_then_load_approved_users_round_trips(tmp_path, monkeypatch):
    import telegram_bot
    monkeypatch.setattr(telegram_bot, "APPROVED_USERS_PATH", str(tmp_path / "approved.json"))
    telegram_bot.save_approved_users({111, 222})
    assert telegram_bot.load_approved_users() == {111, 222}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_telegram_bot.py -v`
Expected: FAIL with `ImportError`/`AttributeError` (names not defined)

- [ ] **Step 3: Implement in `telegram_bot.py`**

Add `import json` to the imports. Add a module-level constant `APPROVED_USERS_PATH = "telegram_approved_users.json"` (near `_URL_PATTERN`). `get_invite_code()` mirrors `get_bot_token()`'s exact shape (strip, raise `RuntimeError` naming `TELEGRAM_INVITE_CODE` if empty). `load_approved_users()` reads `APPROVED_USERS_PATH` as JSON (a flat list of ints) and returns it as a `set`; if the file doesn't exist, return `set()`. `save_approved_users(users)` writes `sorted(users)` to `APPROVED_USERS_PATH` as JSON.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_telegram_bot.py -v`
Expected: PASS (new tests pass; full file still green)

- [ ] **Step 5: Add `telegram_approved_users.json` to `.gitignore`**

- [ ] **Step 6: Commit**

```bash
git add telegram_bot.py .gitignore tests/test_telegram_bot.py
git commit -m "feat: add invite-code and approved-users persistence"
```

---

### Task 2: Parse the `/start <code>` deep-link command

**Files:**
- Modify: `telegram_bot.py`
- Test: `tests/test_telegram_bot.py`

**Interfaces:**
- Produces: `parse_start_command(text: str) -> Optional[str]`. Task 4's `handle_message()` uses this.

- [ ] **Step 1: Write the failing tests**

```python
def test_parse_start_command_extracts_code():
    from telegram_bot import parse_start_command
    assert parse_start_command("/start family2026") == "family2026"

def test_parse_start_command_returns_none_for_bare_start():
    from telegram_bot import parse_start_command
    assert parse_start_command("/start") is None

def test_parse_start_command_returns_none_for_non_start_text():
    from telegram_bot import parse_start_command
    assert parse_start_command("what is this about?") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_telegram_bot.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement `parse_start_command` in `telegram_bot.py`**

A regex matching exactly `/start` followed by whitespace and one non-whitespace token, e.g. `re.match(r"^/start\s+(\S+)$", text)`; return the captured group, or `None` if it doesn't match (bare `/start`, or any other text).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_telegram_bot.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add telegram_bot.py tests/test_telegram_bot.py
git commit -m "feat: parse /start deep-link invite code"
```

---

### Task 3: Authorize against the owner + approved set

**Files:**
- Modify: `telegram_bot.py:42-43` (`is_authorized`'s signature)
- Modify: `tests/test_telegram_bot.py:58-63` (the two existing `is_authorized` tests)

**Interfaces:**
- Consumes: `get_allowed_user_id` (existing), `load_approved_users` (Task 1).
- Produces: `is_authorized(user_id: int, allowed_ids) -> bool` (signature changed — now takes a collection, not a single int); `get_all_authorized_ids() -> set[int]`. Task 4's `handle_message()` uses both.

- [ ] **Step 1: Update the two existing tests for the new signature, and write the new one**

```python
def test_is_authorized_true_for_matching_id():
    assert is_authorized(111, {111}) is True

def test_is_authorized_false_for_other_id():
    assert is_authorized(111, {222}) is False

def test_get_all_authorized_ids_includes_owner_and_approved(monkeypatch):
    import telegram_bot
    monkeypatch.setattr(telegram_bot, "get_allowed_user_id", lambda: 111)
    monkeypatch.setattr(telegram_bot, "load_approved_users", lambda: {222, 333})
    assert telegram_bot.get_all_authorized_ids() == {111, 222, 333}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_telegram_bot.py -v`
Expected: FAIL — the two updated tests fail because `is_authorized` still takes a single int (`222 == {222}` is `False`, not the equality check the old code does); `get_all_authorized_ids` doesn't exist yet

- [ ] **Step 3: Implement in `telegram_bot.py`**

Change `is_authorized(user_id: int, allowed_id: int) -> bool: return user_id == allowed_id` to `is_authorized(user_id: int, allowed_ids) -> bool: return user_id in allowed_ids`. Add `get_all_authorized_ids() -> set[int]`: `return {get_allowed_user_id()} | load_approved_users()`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_telegram_bot.py -v`
Expected: PASS (all tests, including the two updated ones)

- [ ] **Step 5: Commit**

```bash
git add telegram_bot.py tests/test_telegram_bot.py
git commit -m "feat: authorize against owner plus approved-users set"
```

---

### Task 4: Wire `/start` handling and the new authorization into `handle_message`

**Files:**
- Modify: `telegram_bot.py:64-73` (`handle_message`)
- Test: `tests/test_telegram_bot.py` (new tests, plus isolation fixes to the two pre-existing `handle_message` tests)

**Interfaces:**
- Consumes: `parse_start_command` (Task 2), `get_invite_code`, `load_approved_users`, `save_approved_users` (Task 1), `is_authorized`, `get_all_authorized_ids` (Task 3).
- Produces: `handle_message(update, context)` with the new behavior described below. Nothing else depends on this (it's the bot's entrypoint handler).

- [ ] **Step 1: Write the failing tests**

```python
def test_handle_message_approves_new_user_with_correct_code():
    update = _make_update(999, "/start family2026")
    with patch("telegram_bot.get_invite_code", return_value="family2026"), \
         patch("telegram_bot.load_approved_users", return_value=set()), \
         patch("telegram_bot.save_approved_users") as mock_save:
        asyncio.run(handle_message(update, None))
    mock_save.assert_called_once_with({999})
    update.message.reply_text.assert_called_once()
    assert "in" in update.message.reply_text.call_args.args[0].lower()

def test_handle_message_ignores_start_with_wrong_code():
    update = _make_update(999, "/start wrongcode")
    with patch("telegram_bot.get_invite_code", return_value="family2026"), \
         patch("telegram_bot.save_approved_users") as mock_save:
        asyncio.run(handle_message(update, None))
    mock_save.assert_not_called()
    update.message.reply_text.assert_not_called()

def test_handle_message_allows_previously_approved_user():
    update = _make_update(222, "what is this about?")
    with patch("telegram_bot.get_allowed_user_id", return_value=111), \
         patch("telegram_bot.load_approved_users", return_value={222}), \
         patch("telegram_bot.build_reply", return_value="done"):
        asyncio.run(handle_message(update, None))
    assert update.message.reply_text.call_count == 2
    assert update.message.reply_text.call_args_list[-1].args[0] == "done"

def test_handle_message_ignores_bare_start_from_unapproved_stranger():
    update = _make_update(999, "/start")
    with patch("telegram_bot.get_allowed_user_id", return_value=111), \
         patch("telegram_bot.load_approved_users", return_value=set()):
        asyncio.run(handle_message(update, None))
    update.message.reply_text.assert_not_called()
```

(`_make_update` already exists in the test file from the earlier Telegram work — reuse it.)

Also update the two pre-existing tests `test_handle_message_ignores_unauthorized_sender` and `test_handle_message_replies_for_authorized_sender`: add `patch("telegram_bot.load_approved_users", return_value=set())` to each one's `with` block. Without this, after this task's change they'd transitively call the real `load_approved_users()` (since it's no longer bypassed by the old single-ID check) and touch the real `telegram_approved_users.json` file instead of staying isolated.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_telegram_bot.py -v`
Expected: FAIL — `handle_message` doesn't yet check for `/start`, and its authorization check still calls the old single-ID `is_authorized`

- [ ] **Step 3: Implement the new `handle_message` in `telegram_bot.py`**

At the top of the function, after reading `user_id`/`text`: call `code = parse_start_command(text)`. If `code is not None`: if `code == get_invite_code()`, call `save_approved_users(load_approved_users() | {user_id})` and `await update.message.reply_text(...)` with a welcome message (e.g. `"✅ You're in! Send a link to save it, or ask a question."`); either way (matched or not), `return` — do not fall through. Otherwise, replace the existing `if not is_authorized(user_id, get_allowed_user_id()):` with `if not is_authorized(user_id, get_all_authorized_ids()):`, and leave the rest of the function (the ack + `build_reply` flow) unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_telegram_bot.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Run the full suite and verify the module still compiles**

Run: `pytest tests/ -v` — Expected: PASS (all tests across every file)
Run: `python -m py_compile telegram_bot.py` — Expected: no output, exit code 0

- [ ] **Step 6: Commit**

```bash
git add telegram_bot.py tests/test_telegram_bot.py
git commit -m "feat: wire /start invite handling into the message handler"
```

---

### Task 5: Document the new setup step

**Files:**
- Modify: `README.md` (the existing "Telegram Bot" section)

**Interfaces:**
- Consumes: nothing new; this is documentation only.

- [ ] **Step 1: Add the invite-code setup and sharing steps to the README's Telegram Bot section**

Document: adding `TELEGRAM_INVITE_CODE` to `.env`, and sharing a link shaped `https://t.me/<YourBotUsername>?start=<the code>` with whoever should get access — tapping it and pressing Start is all they need to do.

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document inviting additional Telegram users"
```
