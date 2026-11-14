# MCP Server for RAG Knowledge Base Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Claude Code call a tool that searches this project's RAG knowledge base (the same one Streamlit and the Telegram bot already use), via a new local, read-only MCP server.

**Architecture:** A new file, `mcp_server.py`, wraps the existing `query_knowledge_base()` function behind one MCP tool (`search_knowledge_base`), registered with Claude Code as a local stdio server. Reply formatting (`format_query_reply`) moves from `telegram_bot.py` into `query.py` so both Telegram and MCP share one implementation. Debug `print()`s in `query.py` move to stderr so they never corrupt the stdio protocol channel.

**Tech Stack:** Python, `mcp` SDK v2.x (`from mcp.server.mcpserver import MCPServer`, installed version 2.3.0 — confirmed by direct inspection, not assumed), existing `query.py`/`chromadb`/`sentence-transformers`/`groq` stack.

**Spec:** `docs/superpowers/specs/2026-11-13-mcp-server-design.md`

## Global Constraints

- `query_knowledge_base()`'s retrieval/generation **logic** stays unmodified — only its debug output destination changes (stdout → stderr).
- Local stdio transport only — no remote/hosted server, no authentication (per spec: Claude Code only, confirmed).
- ~~Read-only: the tool only searches; no ingestion capability is exposed via MCP.~~ Superseded by Task 6: ingestion (`add_to_knowledge_base`) was added as an approved follow-up, reusing `ingest_url()` unmodified.
- `mcp_server.py` must pin its own working directory to its own file's location before importing `query`, so `CHROMA_PATH = "./chroma_db"` resolves correctly regardless of where Claude Code was launched from.
- `mcp_server.py` must eagerly warm up the embedding model, reranker, and Groq client at startup, before accepting any tool call — and, since `ingest.py` keeps its own separate singletons from `query.py`'s (found during final review), its embedding model and collection must be warmed too, or the first real ingest call still cold-loads.
- New dependency `mcp>=2.0.0` added to `requirements.txt`.
- Registration goes in `~/.claude.json`'s existing top-level `mcpServers` object, in the same `{"type": "stdio", "command": ..., "args": [...]}` shape as the existing `reddit-rss` entry — added alongside it, never overwriting the file wholesale.

## Review Focus

- An empty/whitespace-only question passed to the tool should get the same friendly "Please enter a question" behavior `query_knowledge_base()` already returns for that case, not a crash — Task 3 tests this directly.
- Querying an empty knowledge base (nothing ingested yet) should return `query_knowledge_base()`'s existing "Knowledge base is empty" message verbatim, not an error — Task 3 tests this directly.
- A `filter_type`/`filter_url` combination that matches nothing should produce a graceful "not found" style answer (already `query_knowledge_base()`'s behavior), not an exception propagating out of the tool — Task 3 tests this directly.
- Debug output must never reach stdout during a real tool call (stdio *is* the protocol channel) — Task 2 tests this directly.
- The server being spawned from a working directory other than its own file's location must not silently open/create an empty knowledge base elsewhere — Task 4 tests the cwd-pinning function directly.

---

## File Structure

- **Modify:** `query.py` — add `format_query_reply()` (moved from `telegram_bot.py`), add a `_debug_log()` helper and redirect the four `[DEBUG]` prints through it.
- **Modify:** `telegram_bot.py` — remove its local `format_query_reply`, import it from `query` instead.
- **Modify:** `requirements.txt` — add `mcp>=2.0.0`.
- **Create:** `mcp_server.py` — cwd pinning, model warmup, the `search_knowledge_base` tool, server entrypoint.
- **Create:** `tests/test_query.py` — tests for the two additions to `query.py`.
- **Create:** `tests/test_mcp_server.py` — tests for `mcp_server.py`'s testable logic.
- **Modify (outside this repo):** `~/.claude.json` — add the new `mcpServers` entry.

---

### Task 1: Move `format_query_reply` into `query.py`

**Files:**
- Modify: `query.py`
- Modify: `telegram_bot.py:58-65` (remove local definition), `telegram_bot.py:11` (import)
- Test: `tests/test_query.py` (new), existing `tests/test_telegram_bot.py` (regression)

**Interfaces:**
- Produces: `query.format_query_reply(result: dict) -> str` — same signature and behavior as the function being moved. `telegram_bot.py` and `mcp_server.py` (Task 3) both import this from `query`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_query.py
from query import format_query_reply

def test_format_query_reply_with_sources():
    result = {"success": True, "answer": "It's about X.", "sources": ["https://example.com/a"]}
    reply = format_query_reply(result)
    assert "It's about X." in reply and "https://example.com/a" in reply

def test_format_query_reply_failure():
    result = {"success": False, "error": "Please enter a question."}
    assert "Please enter a question." in format_query_reply(result)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_query.py -v`
Expected: FAIL with `ImportError: cannot import name 'format_query_reply' from 'query'`

- [ ] **Step 3: Move `format_query_reply` from `telegram_bot.py` into `query.py`**

Copy the function body exactly as it exists at `telegram_bot.py:58-65` into `query.py` (place it near `query_knowledge_base`, since it formats that function's output). Remove the definition from `telegram_bot.py`. Change `telegram_bot.py`'s existing `from query import query_knowledge_base` (line 11) to `from query import query_knowledge_base, format_query_reply`.

- [ ] **Step 4: Run the new test to verify it passes**

Run: `pytest tests/test_query.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Run the full existing suite to verify the move didn't break Telegram's usage**

Run: `pytest tests/ -v`
Expected: PASS (all tests, including the pre-existing `test_format_query_reply_*` tests in `tests/test_telegram_bot.py`, which still pass because `telegram_bot.py` re-exposes the name via its import)

- [ ] **Step 6: Commit**

```bash
git add query.py telegram_bot.py tests/test_query.py
git commit -m "refactor: move format_query_reply into query.py for reuse"
```

---

### Task 2: Redirect debug logging to stderr

**Files:**
- Modify: `query.py` (the four `print(f"[DEBUG] ...")` calls inside `query_rag`)
- Test: `tests/test_query.py`

**Interfaces:**
- Produces: `query._debug_log(message: str) -> None`. No other task depends on this directly, but it structurally guarantees Task 4's stdio server never sees debug text on stdout.

- [ ] **Step 1: Write the failing test**

```python
def test_debug_log_writes_to_stderr_not_stdout(capsys):
    from query import _debug_log
    _debug_log("[DEBUG] test message")
    captured = capsys.readouterr()
    assert "[DEBUG] test message" in captured.err
    assert "[DEBUG] test message" not in captured.out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_query.py -v`
Expected: FAIL with `ImportError: cannot import name '_debug_log' from 'query'`

- [ ] **Step 3: Implement `_debug_log(message: str) -> None` in `query.py` and use it for the existing debug prints**

`_debug_log` is `print(message, file=sys.stderr)` (add `import sys` to `query.py`'s imports if not already present). Replace each of the four `print(f"[DEBUG] ...")` calls inside `query_rag` with `_debug_log(f"[DEBUG] ...")`, keeping their exact existing message text unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_query.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add query.py tests/test_query.py
git commit -m "fix: send debug logging to stderr, not stdout"
```

---

### Task 3: `mcp_server.py` core search logic

**Files:**
- Create: `mcp_server.py`
- Test: `tests/test_mcp_server.py` (new)

**Interfaces:**
- Consumes: `query_knowledge_base` and `format_query_reply` (from `query.py`, both importable as of Tasks 1-2).
- Produces: `search_knowledge_base_impl(question: str, filter_type: str | None = None, filter_url: str | None = None) -> str`. Task 4's MCP-decorated tool wraps this directly.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_mcp_server.py
from unittest.mock import patch
from mcp_server import search_knowledge_base_impl

def test_search_passes_question_and_filters_through():
    with patch("mcp_server.query_knowledge_base", return_value={"success": True, "answer": "It's about X.", "sources": []}) as mock_query:
        result = search_knowledge_base_impl("what is this about?", filter_type="reddit", filter_url="https://example.com")
    mock_query.assert_called_once_with("what is this about?", filter_type="reddit", filter_url="https://example.com")
    assert "It's about X." in result

def test_search_handles_empty_question():
    with patch("mcp_server.query_knowledge_base", return_value={"success": False, "error": "Please enter a question."}) as mock_query:
        result = search_knowledge_base_impl("")
    mock_query.assert_called_once_with("", filter_type=None, filter_url=None)
    assert "Please enter a question." in result

def test_search_handles_empty_knowledge_base():
    with patch("mcp_server.query_knowledge_base", return_value={"success": True, "answer": "Knowledge base is empty. Please add some URLs first.", "sources": []}):
        result = search_knowledge_base_impl("anything")
    assert "Knowledge base is empty" in result

def test_search_handles_no_filter_match_gracefully():
    with patch("mcp_server.query_knowledge_base", return_value={"success": True, "answer": "Not found in knowledge base.", "sources": []}):
        result = search_knowledge_base_impl("x", filter_type="youtube", filter_url="https://nonexistent.example")
    assert "Not found in knowledge base." in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_mcp_server.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mcp_server'`

- [ ] **Step 3: Implement `search_knowledge_base_impl` in `mcp_server.py`**

Start the file with `from query import query_knowledge_base, format_query_reply`. `search_knowledge_base_impl(question, filter_type=None, filter_url=None)` calls `query_knowledge_base(question, filter_type=filter_type, filter_url=filter_url)` and returns `format_query_reply(result)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_mcp_server.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add mcp_server.py tests/test_mcp_server.py
git commit -m "feat: add MCP search tool's core logic"
```

---

### Task 4: Server wiring — cwd pin, warmup, MCP tool, entrypoint

**Files:**
- Modify: `mcp_server.py`
- Modify: `requirements.txt`
- Test: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `search_knowledge_base_impl` (Task 3); `get_embed_model`, `get_reranker`, `get_groq_client` (from `query.py`, already defined).
- Produces: `pin_working_directory() -> None`, `warmup_models() -> None`, `main() -> None`, plus the registered MCP tool `search_knowledge_base`.

- [ ] **Step 1: Add the `mcp` dependency**

Add `mcp>=2.0.0` as a new line to `requirements.txt`. Run: `pip install -r requirements.txt` — Expected: installs without error (already confirmed installable: version 2.3.0 resolves).

- [ ] **Step 2: Write the failing tests**

```python
from unittest.mock import patch, call
from mcp_server import pin_working_directory, warmup_models

def test_pin_working_directory_chdirs_to_script_location():
    with patch("mcp_server.os.chdir") as mock_chdir, patch("mcp_server.os.path.dirname", return_value="/fake/script/dir"):
        pin_working_directory()
    mock_chdir.assert_called_once_with("/fake/script/dir")

def test_warmup_models_loads_all_three():
    with patch("mcp_server.get_embed_model") as mock_embed, \
         patch("mcp_server.get_reranker") as mock_reranker, \
         patch("mcp_server.get_groq_client") as mock_groq:
        warmup_models()
    mock_embed.assert_called_once()
    mock_reranker.assert_called_once()
    mock_groq.assert_called_once()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_mcp_server.py -v`
Expected: FAIL with `ImportError` (names not defined)

- [ ] **Step 4: Implement `pin_working_directory`, `warmup_models`, the MCP tool, and `main` in `mcp_server.py`**

Add `import os` and `from query import get_embed_model, get_reranker, get_groq_client` alongside the Task 3 imports. `pin_working_directory()` is `os.chdir(os.path.dirname(os.path.abspath(__file__)))`. `warmup_models()` calls `get_embed_model()`, `get_reranker()`, `get_groq_client()` in that order (return values discarded — these functions cache themselves, per `query.py`'s existing lazy-singleton pattern). Then: `from mcp.server.mcpserver import MCPServer`; `server = MCPServer("rag-knowledge-base")`; a `@server.tool()`-decorated `search_knowledge_base(question: str, filter_type: str = "", filter_url: str = "") -> str` with a docstring describing it for the calling LLM, whose body calls `search_knowledge_base_impl(question, filter_type or None, filter_url or None)`. `main()` calls `pin_working_directory()`, then `warmup_models()`, then `server.run()`. Add `if __name__ == "__main__": main()` at the bottom.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_mcp_server.py -v`
Expected: PASS (6 passed)

- [ ] **Step 6: Verify the module starts correctly**

Run: `python -m py_compile mcp_server.py`
Expected: no output, exit code 0

- [ ] **Step 7: Commit**

```bash
git add mcp_server.py requirements.txt
git commit -m "feat: wire MCP server startup, tool registration, and entrypoint"
```

---

### Task 5: Register with Claude Code and verify live

**Files:**
- Modify (outside this repo): `~/.claude.json`
- Test: manual (cannot be unit-tested — this verifies the real Claude Code MCP client can reach the real server)

**Interfaces:**
- Consumes: `main()` (Task 4) as the registered command's entrypoint.

- [ ] **Step 1: Read the current `~/.claude.json` and confirm its existing `mcpServers` entries**

Run: `python3 -c "import json; print(json.dumps(json.load(open('/home/nitin/.claude.json'))['mcpServers'], indent=2))"`
Expected: shows the existing `youtube-transcript` and `reddit-rss` entries, confirming the file's current shape before editing it.

- [ ] **Step 2: Add a new entry, preserving the existing ones — ask for explicit confirmation before writing, since this file is outside this project's git repo**

New entry key `"rag-knowledge-base"`, value `{"type": "stdio", "command": "<absolute path to this project's .venv python>", "args": ["<absolute path to mcp_server.py>"], "env": {}}`. Read the full JSON, merge this key into the existing `mcpServers` object (do not replace the object), write the full file back. Confirm the diff with the user before writing, since this is a side effect outside the project worktree.

- [ ] **Step 3: Verify the JSON is still valid and both old entries are intact**

Run: `python3 -c "import json; d = json.load(open('/home/nitin/.claude.json')); print(list(d['mcpServers'].keys()))"`
Expected: `['youtube-transcript', 'reddit-rss', 'rag-knowledge-base']` (order may vary, but all three present)

- [ ] **Step 4: Manual verification — start a fresh Claude Code session and confirm the tool is reachable**

In a new Claude Code session (not this one, since this one started before the registration), ask a question that should trigger the `search_knowledge_base` tool (e.g. "search my knowledge base for the Bengaluru metro post"). Expected: Claude calls the tool and returns an answer grounded in real ingested content, matching what Streamlit/Telegram would give for the same question.

- [ ] **Step 5: Manual verification — confirm cold-start doesn't time out**

In that same fresh session, make this the *first* tool call (no prior warmup from another process). Expected: the call completes successfully despite the eager warmup happening inside that call's process startup — no client-side timeout.

- [ ] **Step 6: Commit the implementation plan's completion** (no code changes in this step; this just closes out the work)

```bash
git log --oneline -6
```
Expected: shows all five tasks' commits in order, confirming the full feature is committed.

---

### Task 6: Add an ingestion tool (`add_to_knowledge_base`)

Added after Task 5, by request — scope confirmed as a small addition
reusing the exact pattern Tasks 3-4 already established, not a new
design.

**Files:**
- Modify: `ingest.py` (add `format_ingest_reply`, moved from `telegram_bot.py:46-55`)
- Modify: `telegram_bot.py:10-11` (remove local `format_ingest_reply`, import from `ingest` instead)
- Modify: `mcp_server.py` (new impl function + new tool, added to the existing `server`)
- Test: `tests/test_ingest.py` (new), `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `ingest_url` (from `ingest.py`, already imported into `mcp_server.py` is NOT yet the case — this task adds that import).
- Produces: `ingest.format_ingest_reply(result: dict) -> str` (moved); `mcp_server.add_to_knowledge_base_impl(url: str) -> str`; the registered tool `add_to_knowledge_base`.

- [ ] **Step 1: Write the failing tests for the moved formatter**

```python
# tests/test_ingest.py
from ingest import format_ingest_reply

def test_format_ingest_reply_success():
    result = {"success": True, "duplicate": False, "chunks_stored": 6, "extraction_quality": "full_text", "url_type": "article"}
    reply = format_ingest_reply(result)
    assert "6" in reply and "article" in reply

def test_format_ingest_reply_duplicate():
    result = {"success": True, "duplicate": True}
    assert "already exists" in format_ingest_reply(result).lower()

def test_format_ingest_reply_failure():
    result = {"success": False, "duplicate": False, "message": "Could not extract content: boom"}
    assert "boom" in format_ingest_reply(result)
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_ingest.py -v`
Expected: FAIL with `ImportError: cannot import name 'format_ingest_reply' from 'ingest'`

- [ ] **Step 3: Move `format_ingest_reply` from `telegram_bot.py` into `ingest.py`**

Copy the function body exactly as it exists at `telegram_bot.py:46-55` into `ingest.py` (place it near `ingest_url`). Remove it from `telegram_bot.py`. Change `telegram_bot.py`'s `from ingest import ingest_url` (line 10) to `from ingest import ingest_url, format_ingest_reply`.

- [ ] **Step 4: Run to verify it passes, then run the full suite for regressions**

Run: `pytest tests/test_ingest.py -v` — Expected: PASS (3 passed)
Run: `pytest tests/ -v` — Expected: PASS (all tests, including `telegram_bot.py`'s pre-existing `test_format_ingest_reply_*` tests, which still pass via the re-exported import)

- [ ] **Step 5: Commit**

```bash
git add ingest.py telegram_bot.py tests/test_ingest.py
git commit -m "refactor: move format_ingest_reply into ingest.py for reuse"
```

- [ ] **Step 6: Write the failing tests for the new MCP tool logic**

```python
# appended to tests/test_mcp_server.py
from unittest.mock import patch
from mcp_server import add_to_knowledge_base_impl

def test_add_passes_url_through_and_formats_success():
    with patch("mcp_server.ingest_url", return_value={"success": True, "duplicate": False, "chunks_stored": 4, "extraction_quality": "full_text", "url_type": "reddit"}) as mock_ingest:
        result = add_to_knowledge_base_impl("https://example.com/post")
    mock_ingest.assert_called_once_with("https://example.com/post")
    assert "4" in result

def test_add_handles_duplicate():
    with patch("mcp_server.ingest_url", return_value={"success": True, "duplicate": True}):
        result = add_to_knowledge_base_impl("https://example.com/post")
    assert "already exists" in result.lower()

def test_add_handles_failure():
    with patch("mcp_server.ingest_url", return_value={"success": False, "duplicate": False, "message": "Could not extract content: boom"}):
        result = add_to_knowledge_base_impl("https://example.com/post")
    assert "boom" in result
```

- [ ] **Step 7: Run to verify they fail**

Run: `pytest tests/test_mcp_server.py -v`
Expected: FAIL with `ImportError: cannot import name 'add_to_knowledge_base_impl' from 'mcp_server'`

- [ ] **Step 8: Implement `add_to_knowledge_base_impl` and the new tool in `mcp_server.py`**

Add `from ingest import ingest_url, format_ingest_reply` to `mcp_server.py`'s imports. `add_to_knowledge_base_impl(url: str) -> str` calls `ingest_url(url)` and returns `format_ingest_reply(result)`. Register a second tool on the same `server` instance:

```python
@server.tool()
def add_to_knowledge_base(url: str) -> str:
    """Save a URL (YouTube, LinkedIn, Reddit, X/Twitter, Facebook,
    Instagram, or a generic article) into this personal RAG knowledge
    base, so it can be searched later via search_knowledge_base. Use
    this when the user asks to save, add, or ingest a link — not for
    a bare URL with no indication they want it stored.
    """
    return add_to_knowledge_base_impl(url)
```

- [ ] **Step 9: Run to verify they pass**

Run: `pytest tests/test_mcp_server.py -v`
Expected: PASS (9 passed)

- [ ] **Step 10: Run the full suite and verify the module still compiles**

Run: `pytest tests/ -v` — Expected: PASS (all tests)
Run: `python -m py_compile mcp_server.py ingest.py telegram_bot.py` — Expected: no output, exit code 0

- [ ] **Step 11: Commit**

```bash
git add mcp_server.py tests/test_mcp_server.py
git commit -m "feat: add ingestion tool to the MCP server"
```

- [ ] **Step 12: Manual verification**

In the same fresh Claude Code session used for Task 5's verification (no server restart needed — Claude Code will relaunch the stdio process on its own next tool call, picking up the new code), ask something like *"add this to my knowledge base: <a real URL>"*. Expected: the tool is called, the URL is ingested, and a follow-up search for it succeeds.
