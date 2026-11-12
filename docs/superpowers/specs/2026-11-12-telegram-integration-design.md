# Telegram Integration Design

## Purpose

Add Telegram as a second, more convenient entry point into the existing
RAG knowledge base, alongside the current Streamlit UI. The goal is to let
the user send a link from their phone (or a question) without opening a
browser, while reusing all existing ingestion/retrieval logic untouched.

## Scope

- **In scope**: a new standalone bot process that can (1) ingest a URL
  sent to it, using the same extractors already built for YouTube,
  LinkedIn, Reddit, and generic articles, and (2) answer questions sent
  to it, using the same retrieval/generation pipeline the Streamlit app
  uses.
- **Out of scope** (deferred, not needed for this iteration):
  - Accepting raw pasted text as an alternative to URLs (e.g. to work
    around LinkedIn's weak extraction) — URL-only for now.
  - Multi-user access / allowlists — single authorized user only.
  - A public webhook / hosted deployment — polling only, run locally.
  - Background/async ingestion queue — synchronous processing only.
  - Fixing the existing whole-KB retrieval relevance issue (fixed
    top-6 chunks, no score threshold, disabled reranker) — this is a
    known, separate problem already identified and intentionally not
    addressed here.

## Architecture

A new file, `telegram_bot.py`, added alongside the existing `app.py`,
`ingest.py`, and `query.py`. It imports and calls `ingest_url()` (from
`ingest.py`) and `query_knowledge_base()` (from `query.py`) directly —
no duplicated extraction, chunking, embedding, or retrieval logic.

The bot runs as a second, independent, always-running process using
**long polling** against the Telegram Bot API (no public URL, domain,
or TLS certificate required — fits a personal machine with no fixed
IP). It is started separately from Streamlit:

```
streamlit run app.py        # existing, unchanged
python telegram_bot.py      # new, runs alongside it
```

Both processes read and write the same `./chroma_db` persistent
ChromaDB folder on disk. They do not communicate with each other
directly — the shared database is the only connection between them.
Either process can run independently; a link ingested via Telegram is
immediately visible to Streamlit (and vice versa) because they share
storage, not because they talk to each other.

## Message handling logic

For every incoming Telegram message, the bot:

1. **Checks the sender's numeric Telegram user ID** against
   `TELEGRAM_ALLOWED_USER_ID` (from `.env`). If it doesn't match, the
   message is silently ignored — no reply is sent, so the bot's
   existence isn't revealed to unauthorized senders.
2. If the message **contains a URL** (same regex-style detection
   already used elsewhere in `ingest.py`), it is treated as a link to
   ingest:
   - Reply immediately with a short "⏳ Processing..." message.
   - Call `ingest_url(url)` synchronously (the bot blocks on this
     call — no background thread/queue).
   - Reply with the result: success and chunk count, "already exists"
     for duplicates, or a failure reason.
3. If the message **has no URL**, it is treated as a question:
   - Reply with "⏳ Searching..." (optional, same pattern).
   - Call `query_knowledge_base(question)` synchronously.
   - Reply with the generated answer and the cited source URL(s), in
     the same style the Streamlit app shows them (plain text,
     Telegram doesn't need the HTML styling Streamlit uses).

No slash commands or special syntax are introduced — the presence or
absence of a URL in the message text is the only branching signal,
matching how a user would naturally message a bot.

## Credentials & configuration

Two new variables added to the existing `.env` file (already
confirmed present and correctly formatted as of this session):

- `TELEGRAM_BOT_TOKEN` — obtained via BotFather (`/newbot`). Format:
  `<numeric_bot_id>:<35-char secret>`.
- `TELEGRAM_ALLOWED_USER_ID` — the user's own numeric Telegram user
  ID (obtained via a helper bot like `@userinfobot`), not their
  @username.

One new dependency added to `requirements.txt`:

- `python-telegram-bot` — handles the polling loop, update parsing,
  and message sending.

If either `TELEGRAM_BOT_TOKEN` or `TELEGRAM_ALLOWED_USER_ID` is
missing or empty at startup, the bot fails fast with a clear error
message rather than starting in a broken state.

## Error handling

- Any exception raised during ingestion or querying is caught at the
  message-handler level and turned into a short, user-readable error
  reply in the chat, rather than crashing the bot process or leaving
  the sender without a response.
- Malformed/empty messages are handled gracefully (treated as an empty
  question, which `query_knowledge_base()` already handles by
  returning a "please enter a question" style error rather than
  raising).
- **Known, accepted limitation**: Streamlit and the bot are separate
  processes both writing to the same ChromaDB SQLite-backed storage.
  Concurrent writes from both at the exact same instant could in
  theory produce a transient "database is locked" error. Given this is
  a single-user, locally-run, low-concurrency setup, this is accepted
  as a rare edge case and not engineered around in this iteration.

## Testing plan

Manual verification (matching how every other piece of this project
has been verified so far in this session):

1. Send a message from an unauthorized Telegram account (or reason
   about the ID check in code) → confirm it is silently ignored.
2. Send a YouTube, Reddit, LinkedIn, or article URL from the
   authorized account → confirm a success reply with chunk count, and
   confirm the new source appears in the Streamlit sidebar's
   "Ingested Sources" list.
3. Send a plain-text question → confirm the reply's answer and cited
   sources are consistent with asking the same question in the
   Streamlit UI.
4. Send a malformed message (garbage text, empty message, a broken
   URL) → confirm a graceful failure reply, not a crash or hang.
5. Re-send a URL already ingested → confirm the existing
   duplicate-detection behavior surfaces correctly via the bot.

## Explicitly deferred (not this iteration)

These were discussed and intentionally excluded from this design to
keep it YAGNI-scoped to what's actually needed now:

- Raw pasted text as an ingestion input (LinkedIn workaround)
- Multi-user allowlist support
- Async/background ingestion with a queue and follow-up message
- Public webhook deployment
- Retrieval quality fixes (relevance threshold, reranker, broader
  query expansion) — a known separate issue, not caused by or specific
  to the Telegram integration
