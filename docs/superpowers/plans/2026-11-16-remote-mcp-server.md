# Remote MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert `mcp_server.py` from a local stdio-only process into a small networked HTTP service, reachable over the network and protected by one shared bearer token, so Claude Code (on this machine or anyone else's, once given the URL and token) always talks to the one live knowledge base.

**Architecture:** The MCP SDK's own `streamable-http` transport and `TokenVerifier`/`AuthSettings` auth plumbing do the real work; this plan adds a tiny shared-secret check (`SharedTokenVerifier`) on top of it and switches `main()`'s transport. The two existing tools (`search_knowledge_base`, `add_to_knowledge_base`) are untouched.

**Tech Stack:** Python, `mcp` SDK 2.3.0 (already installed — `server.run(transport="streamable-http", ...)`, `mcp.server.auth.provider.{TokenVerifier, AccessToken}`, `mcp.server.auth.settings.AuthSettings`), `pytest` + `unittest.mock` (matching `tests/test_mcp_server.py`'s existing style).

**Spec:** `docs/superpowers/specs/2026-11-16-remote-mcp-server-design.md`

## Global Constraints

- New required env var `MCP_SHARED_TOKEN` — no default; reading it raises `RuntimeError` when unset.
- New optional env var `MCP_PUBLIC_URL` — defaults to `http://localhost:8000`; reading it never raises.
- One shared token for everyone — no per-person tokens, no real OAuth flow.
- Plain HTTP for this iteration (no TLS) — confirmed, matches the project's existing security posture.
- `search_knowledge_base_impl`/`add_to_knowledge_base_impl` and the two `@server.tool()` functions wrapping them are unchanged.
- Server binds `host="0.0.0.0", port=8000` (not the SDK's default `127.0.0.1`, since this must be reachable over the network, not just from localhost).
- **Only the non-raising `get_mcp_public_url()` may be called at module import time** (it already is, via the module-level `server = MCPServer(...)` construction). `get_mcp_shared_token()` is only ever called from inside `verify_token()` (request-handling time) and at the top of `main()` (server-startup time) — never at import time, so importing this module in a test/CI environment without `MCP_SHARED_TOKEN` set continues to work exactly as it does today.

## Review Focus

- No `MCP_SHARED_TOKEN` configured at all — the server must fail fast at startup with a clear error, and (defense in depth) `verify_token()` must fail closed rather than raise or accidentally accept. → Task 2, Task 3.
- A real HTTP request with no `Authorization` header at all (not just a wrong token value) — must get a real 401 over the wire. → Task 3 (manual live verification).
- A token that's a truncated or extended version of the real one (e.g. `"secret12"` instead of `"secret123"`) — must be rejected, confirming exact-match comparison. → Task 2.
- A correct token with incidental extra whitespace (e.g. a trailing newline from copy-pasting) — must be rejected, not silently stripped and accepted. → Task 2.
- Importing `mcp_server.py` with `MCP_SHARED_TOKEN` unset (the normal test/CI environment) must keep working exactly as it does today. → satisfied by the Global Constraint above; proven by Task 1's and the existing test suite's imports continuing to pass.

---

### Task 1: Config helpers

**Files:**
- Modify: `mcp_server.py`
- Test: `tests/test_mcp_server.py`

**Interfaces:**
- Produces: `get_mcp_shared_token() -> str` — raises `RuntimeError` when `MCP_SHARED_TOKEN` is unset or blank. `get_mcp_public_url() -> str` — returns `MCP_PUBLIC_URL` if set, else `"http://localhost:8000"`; never raises.

- [ ] **Step 1: Write the failing tests**

```python
def test_get_mcp_shared_token_missing_raises(monkeypatch):
    from mcp_server import get_mcp_shared_token
    monkeypatch.delenv("MCP_SHARED_TOKEN", raising=False)
    with pytest.raises(RuntimeError):
        get_mcp_shared_token()


def test_get_mcp_shared_token_present_returns_value(monkeypatch):
    from mcp_server import get_mcp_shared_token
    monkeypatch.setenv("MCP_SHARED_TOKEN", "secret123")
    assert get_mcp_shared_token() == "secret123"


def test_get_mcp_public_url_defaults_to_localhost(monkeypatch):
    from mcp_server import get_mcp_public_url
    monkeypatch.delenv("MCP_PUBLIC_URL", raising=False)
    assert get_mcp_public_url() == "http://localhost:8000"


def test_get_mcp_public_url_respects_env_override(monkeypatch):
    from mcp_server import get_mcp_public_url
    monkeypatch.setenv("MCP_PUBLIC_URL", "http://203.0.113.5:8000")
    assert get_mcp_public_url() == "http://203.0.113.5:8000"
```

(`import pytest` is already present at the top of `tests/test_mcp_server.py`'s neighboring test files' style — add it to this file if not already imported.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_mcp_server.py -k "mcp_shared_token or mcp_public_url" -v`
Expected: FAIL (`get_mcp_shared_token`/`get_mcp_public_url` not defined)

- [ ] **Step 3: Implement both functions in `mcp_server.py`**

Place them near the top of the file, before the module-level `server = MCPServer(...)` line (Task 3 will make that line call `get_mcp_public_url()`). `get_mcp_shared_token()` mirrors `telegram_bot.py`'s `get_bot_token()` pattern (`os.getenv(...).strip()`, raise `RuntimeError` with a clear message if falsy). `get_mcp_public_url()` is `os.getenv("MCP_PUBLIC_URL", "http://localhost:8000").strip() or "http://localhost:8000"`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_mcp_server.py -k "mcp_shared_token or mcp_public_url" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mcp_server.py tests/test_mcp_server.py
git commit -m "feat: add MCP_SHARED_TOKEN and MCP_PUBLIC_URL config helpers"
```

---

### Task 2: Shared-token verifier

**Files:**
- Modify: `mcp_server.py`
- Test: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `get_mcp_shared_token() -> str` (Task 1, raises `RuntimeError` when unset).
- Produces: `SharedTokenVerifier` — a class with `async def verify_token(self, token: str) -> AccessToken | None` (no required base class; `TokenVerifier` from `mcp.server.auth.provider` is a structural `Protocol`). Returns a valid `AccessToken` only when `token` exactly equals `get_mcp_shared_token()`'s current value; returns `None` for any mismatch, including when `get_mcp_shared_token()` itself raises (unconfigured server).

- [ ] **Step 1: Write the failing tests**

```python
import asyncio
from mcp_server import SharedTokenVerifier

def test_verify_token_accepts_correct_shared_token(monkeypatch):
    monkeypatch.setenv("MCP_SHARED_TOKEN", "secret123")
    result = asyncio.run(SharedTokenVerifier().verify_token("secret123"))
    assert result is not None
    assert result.token == "secret123"


def test_verify_token_rejects_wrong_token(monkeypatch):
    monkeypatch.setenv("MCP_SHARED_TOKEN", "secret123")
    result = asyncio.run(SharedTokenVerifier().verify_token("wrong"))
    assert result is None


def test_verify_token_rejects_truncated_token(monkeypatch):
    monkeypatch.setenv("MCP_SHARED_TOKEN", "secret123")
    result = asyncio.run(SharedTokenVerifier().verify_token("secret12"))
    assert result is None


def test_verify_token_rejects_token_with_trailing_whitespace(monkeypatch):
    monkeypatch.setenv("MCP_SHARED_TOKEN", "secret123")
    result = asyncio.run(SharedTokenVerifier().verify_token("secret123\n"))
    assert result is None


def test_verify_token_fails_closed_when_not_configured(monkeypatch):
    monkeypatch.delenv("MCP_SHARED_TOKEN", raising=False)
    result = asyncio.run(SharedTokenVerifier().verify_token("anything"))
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_mcp_server.py -k verify_token -v`
Expected: FAIL (`SharedTokenVerifier` not defined)

- [ ] **Step 3: Implement `SharedTokenVerifier` in `mcp_server.py`**

```python
async def verify_token(self, token: str) -> AccessToken | None:
    try:
        expected = get_mcp_shared_token()
    except RuntimeError:
        return None
    if token != expected:
        return None
    return AccessToken(token=token, client_id="shared-user", scopes=[])
```

Import `AccessToken` from `mcp.server.auth.provider`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_mcp_server.py -k verify_token -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mcp_server.py tests/test_mcp_server.py
git commit -m "feat: add shared-bearer-token verifier for the MCP server"
```

---

### Task 3: Wire into the server, switch transport, document setup

**Files:**
- Modify: `mcp_server.py` (module-level `server = MCPServer(...)`, `main()`)
- Modify: `tests/test_mcp_server.py` (update the existing `test_main_pins_cwd_then_runs_without_waiting_for_warmup`)
- Modify: `README.md`

**Interfaces:**
- Consumes: `get_mcp_shared_token()`, `get_mcp_public_url()` (Task 1), `SharedTokenVerifier` (Task 2).
- Produces: none (terminal task).

- [ ] **Step 1: Write the failing tests**

```python
def test_main_fails_fast_when_shared_token_not_configured(monkeypatch):
    import mcp_server
    monkeypatch.delenv("MCP_SHARED_TOKEN", raising=False)
    with patch("mcp_server.pin_working_directory"), \
         patch("mcp_server.threading.Thread") as mock_thread_cls, \
         patch.object(mcp_server.server, "run") as mock_run:
        with pytest.raises(RuntimeError):
            mcp_server.main()
    mock_thread_cls.assert_not_called()
    mock_run.assert_not_called()
```

Also **modify** the existing `test_main_pins_cwd_then_runs_without_waiting_for_warmup` test: add `monkeypatch.setenv("MCP_SHARED_TOKEN", "secret123")` as its first line (give the test function a `monkeypatch` parameter), and change its final assertion from `manager.run.assert_called_once()` to `manager.run.assert_called_once_with(transport="streamable-http", host="0.0.0.0", port=8000)`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_mcp_server.py -k "main_fails_fast or main_pins_cwd" -v`
Expected: FAIL (new test: `main()` doesn't yet call `get_mcp_shared_token()` so nothing raises; modified test: `server.run` is still called with no arguments)

- [ ] **Step 3: Modify `mcp_server.py`**

Add imports: `from mcp.server.auth.provider import AccessToken` (if not already added in Task 2), `from mcp.server.auth.settings import AuthSettings`. Change the module-level server construction to:

```python
server = MCPServer(
    "rag-knowledge-base",
    auth=AuthSettings(
        issuer_url=get_mcp_public_url(),
        resource_server_url=get_mcp_public_url(),
    ),
    token_verifier=SharedTokenVerifier(),
)
```

Change `main()`:

```python
def main() -> None:
    pin_working_directory()
    get_mcp_shared_token()  # fail fast if misconfigured, before starting the server
    threading.Thread(target=warmup_models, daemon=True).start()
    server.run(transport="streamable-http", host="0.0.0.0", port=8000)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_mcp_server.py -k "main_fails_fast or main_pins_cwd" -v`
Expected: PASS

- [ ] **Step 5: Run the full test suite**

Run: `pytest -q`
Expected: all tests pass

- [ ] **Step 6: Manually verify the real HTTP behavior**

This proves the Review Focus item a mock can't: a real request over the wire with no `Authorization` header at all gets a real 401, and a request with the correct token does not. Run in the project's venv:

```bash
MCP_SHARED_TOKEN=test-token-xyz MCP_PUBLIC_URL=http://localhost:8099 \
  python -c "
import os
os.environ.setdefault('MCP_SHARED_TOKEN', 'test-token-xyz')
import mcp_server
import threading
t = threading.Thread(target=lambda: mcp_server.server.run(transport='streamable-http', host='127.0.0.1', port=8099), daemon=True)
t.start()
import time; time.sleep(2)
import requests
no_auth = requests.post('http://127.0.0.1:8099/mcp', timeout=5)
print('no Authorization header ->', no_auth.status_code)
with_auth = requests.post('http://127.0.0.1:8099/mcp', headers={'Authorization': 'Bearer test-token-xyz'}, timeout=5)
print('correct token ->', with_auth.status_code)
"
```

Expected: the first status code is `401`; the second is **not** `401` (it may be `400` or another error from the MCP protocol layer, since this script doesn't send a real MCP `initialize` body — that's fine, it only needs to prove the request got past the auth check).

- [ ] **Step 7: Document in `README.md`**

Add a new subsection (near the existing MCP mention, or create one if none exists) covering: (a) setting `MCP_SHARED_TOKEN` and optionally `MCP_PUBLIC_URL` in `.env`; (b) that `mcp_server.py` now listens on `0.0.0.0:8000` instead of talking over stdio; (c) how someone else connects their own Claude Code once this is deployed to a reachable host: `claude mcp add --transport http rag-knowledge-base <MCP_PUBLIC_URL>/mcp -H "Authorization: Bearer <token>"`; (d) a note that deploying this to an actual always-on server (e.g. a cloud VM) is a separate manual step, not covered by this code change, and that plain HTTP means the token travels unencrypted — acceptable for this project's current demo-level security posture, worth revisiting before any real sensitive use.

- [ ] **Step 8: Commit**

```bash
git add mcp_server.py tests/test_mcp_server.py README.md
git commit -m "feat: serve the MCP server over streamable-http with shared-token auth"
```
