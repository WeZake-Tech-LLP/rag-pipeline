# MCP Server for the RAG Knowledge Base — Design

## Intent and why

Everything ingested into this knowledge base so far — via the Streamlit
sidebar and the Telegram bot — can only be queried through those same
two interfaces. The user wants a third way in: asking Claude itself
(specifically Claude Code, the CLI this whole project has been built
in) to search this personal knowledge base during an ordinary
conversation, without opening Streamlit or messaging the bot.

This completes a symmetry the project already has on the ingestion
side (multiple ways to add content) by giving it multiple ways to ask
about that content too.

## Goals

- Claude Code can call a tool that searches this knowledge base and
  returns an answer, during any conversation, without the user leaving
  Claude Code.
- The tool reuses the exact same retrieval/generation logic Streamlit
  and Telegram already use — no duplicated logic, no second answer
  pipeline that could drift from the first.
- Setup is local-only: no hosting, no authentication, no network
  exposure beyond what already exists (Groq API calls).

## Non-goals (explicitly out of scope for this iteration)

- ~~**No ingestion via Claude.**~~ **Superseded.** Search-only was the
  agreed default when this feature was first scoped, but ingestion via
  Claude Code was added as an approved follow-up (`add_to_knowledge_base`,
  implementation plan Task 6) — same pattern as the search tool, reusing
  `ingest_url()` unmodified. The tool set is no longer read-only.
- **No Claude Desktop or claude.ai support.** Confirmed: Claude Code
  only. Claude Desktop uses a different config file/location and
  claude.ai would need a hosted remote server with OAuth — neither is
  needed here.
- **No new retrieval behavior.** The tool calls the existing
  `query_knowledge_base()` function exactly as Streamlit and Telegram
  do (same reranking, same filters, same everything built today).

## Anti-goals

- This must not become something the user has to remember to manually
  start, the way Streamlit and the Telegram bot are. MCP stdio servers
  are launched on demand by the Claude Code client itself per its
  config — that property should be preserved, not worked around.
- Must not require editing `ingest.py`/`query.py`'s existing behavior
  to accommodate this — it's a new consumer of existing code, not a
  reason to change that code.

## Constraints

- Must reuse `query_knowledge_base(question, filter_type=None,
  filter_url=None)` from `query.py` unmodified.
- Must run inside the project's existing `.venv` (same dependencies
  already installed — torch, chromadb, sentence-transformers, groq,
  etc. — no reason to duplicate that environment).
- Registration must use Claude Code's own MCP configuration mechanism
  (the `mcpServers` structure already observed in this machine's
  `~/.claude.json`, the same place the pre-existing `reddit-rss` MCP
  server is registered).

## Approaches considered

1. **A local stdio MCP server using the official `mcp` Python SDK's
   `FastMCP` high-level API** (new dependency: `mcp`, added to
   `requirements.txt`). A new file, `mcp_server.py`, defines one tool
   via a decorator and calls `query_knowledge_base()` inside it. This
   is the same shape as every other integration in this project
   (Streamlit calls the shared functions, Telegram calls the shared
   functions, now MCP calls the shared functions) — **this is the
   pick**, since it needs no new protocol knowledge beyond what the
   `mcp` SDK already provides, and matches how the pre-existing
   `reddit-rss` MCP server is configured (stdio, command + args).
2. **Hand-roll the MCP stdio protocol directly** (reading/writing JSON-RPC
   messages over stdin/stdout manually, no SDK). Rejected — reinvents
   what the official SDK already does correctly, for no benefit at
   this scale.
3. **A remote/hosted MCP server** (HTTP+SSE transport, auth). Rejected —
   explicitly out of scope per the confirmed "Claude Code only, local"
   decision; this is infrastructure this personal project doesn't need.

## Decided design

- **New file**: `mcp_server.py`, alongside `app.py`/`telegram_bot.py`.
- **One tool**, `search_knowledge_base`, with the same parameters
  `query_knowledge_base()` already takes:
  - `question: str` (required)
  - `filter_type: str | None` (optional — one of the existing source
    types: youtube, linkedin, reddit, x, facebook, instagram, article)
  - `filter_url: str | None` (optional — an exact source URL)
  - Returns the answer text plus a "Sources:" list, formatted as plain
    text (the same shape Telegram's `format_query_reply()` already
    produces — reusable rather than inventing a third format).
- **New dependency**: `mcp`, added to `requirements.txt`.
- **Registration**: a new entry under `mcpServers` in
  `~/.claude.json`, of the same `{"type": "stdio", "command": ...,
  "args": [...]}` shape as the existing `reddit-rss` entry, pointing
  at this project's `.venv` Python interpreter and `mcp_server.py` by
  absolute path (so it works regardless of what directory a future
  Claude Code session is started from).

## Resolved during builder check

A fresh review of this doc against the actual code surfaced three
correctness gaps a literal reading of "reuse unmodified" would have
missed. None change the goals/scope above — they're wiring decisions,
settled here rather than bounced back as open questions:

- **stdout corruption risk**: `query_rag()` in `query.py` has four
  `print(f"[DEBUG] ...")` calls that write straight to stdout — which,
  in stdio MCP transport, *is* the JSON-RPC wire. Calling
  `query_knowledge_base()` as-is from `mcp_server.py` would interleave
  debug text into the protocol channel on every call. **Decision**:
  change those four `print()` calls in `query.py` to write to stderr
  (`print(..., file=sys.stderr)`) instead of stdout. This is a debug
  output *destination* fix, not a behavior change — it doesn't affect
  Streamlit or Telegram, and keeps retrieval/generation logic
  untouched.
- **Working-directory risk**: `CHROMA_PATH = "./chroma_db"` is a
  relative path resolved against the process's current working
  directory at call time. Since this server registers in the
  **global** `~/.claude.json` (confirmed: that's where the existing
  `reddit-rss`/`youtube-transcript` entries live), Claude Code could
  spawn it from any directory the user happens to be in — silently
  opening/creating an *empty* collection there instead of erroring.
  **Decision**: `mcp_server.py` pins its own working directory via
  `os.chdir()` to its own file's directory (derived from
  `os.path.dirname(os.path.abspath(__file__))`) as its first action,
  before importing `query`. This keeps `query.py`/`ingest.py`
  genuinely unmodified in logic, and self-contains the fix in the new
  file.
- **Cold-start timeout risk**: the embedding model, cross-encoder
  reranker, and Groq client are all lazily instantiated on first use.
  The first real tool call in a freshly spawned server would pay that
  full load cost synchronously, risking a client-side MCP call
  timeout. **Decision**: `mcp_server.py` eagerly calls
  `get_embed_model()`, `get_reranker()`, and `get_groq_client()` once
  at server startup (before `mcp.run()`), so the first real tool call
  is already warm.

## What's left to the builder

- Exact `mcp` SDK API surface/version pin (the plan should verify
  the installed version's `FastMCP` decorator syntax matches what's
  written here, since this is a fast-moving SDK).
- Whether `format_query_reply()` needs to move out of `telegram_bot.py`
  into a shared location (e.g. `query.py`) to be reusable from
  `mcp_server.py` without importing Telegram-specific code — this is
  a small refactor call, not a design decision.
- Manual verification steps for confirming the registered tool is
  actually callable from a real Claude Code session (this can't be
  unit-tested the way `telegram_bot.py`'s pure functions were).
