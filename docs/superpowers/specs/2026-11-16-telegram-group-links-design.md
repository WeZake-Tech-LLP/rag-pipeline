# Telegram Group Link-Ingestion — Design (short)

## Intent and why

The real purpose of this project: as people discover relevant links
(YouTube, X, Reddit, articles, GitHub repos, ...), they drop them into
a shared Telegram group as they find them. The bot should ingest every
link posted there into the same RAG knowledge base that DMs and
Claude's MCP tools already read/write, with zero friction — no invite
flow, no commands, just post a link.

## Goals

- Anyone already in the one designated group can post a link and have
  it ingested, with a short confirmation reply.
- The group stays usable for normal conversation: the bot must never
  reply to, or otherwise react to, a message that isn't a link.
- The existing DM flow (owner + invite-coded users, Q&A included) is
  completely unaffected — both entry points coexist permanently.

## Non-goals (explicitly out of scope for this iteration)

- No Q&A in the group. Asking a question in the group gets no reply;
  questions still only work in DM.
- No per-user authorization inside the group. Group membership itself
  is the trust boundary — anyone who can see the group can trigger
  ingestion.
- No support for more than one group. One `TELEGRAM_GROUP_CHAT_ID`.

## Anti-goals

- Must never make the bot reply to ordinary group chatter (the
  explicit complaint this design is written to avoid: "no accidental
  replies to regular chat").
- Must not require the owner to re-share an invite link for group
  members — membership already proves intent to be there.

## Constraints

- Reuses `extract_first_url()`, `ingest_url()`, and
  `format_ingest_reply()` unmodified.
- New optional `.env` value: `TELEGRAM_GROUP_CHAT_ID`. Unset means
  group support is off entirely — same graceful-degradation pattern
  already used for `TELEGRAM_INVITE_CODE`.
- Telegram's bot "privacy mode" (set via @BotFather) must be disabled
  for the bot to see non-mention messages in a group at all. This is a
  one-time manual setup step, documented in the README, not something
  the code can control.

## Approach (decided in conversation)

Add a second message handler, scoped at registration time (via
python-telegram-bot's `filters.Chat(chat_id=...)`) to fire only in the
one configured group:

1. `get_group_chat_id() -> Optional[int]` reads `TELEGRAM_GROUP_CHAT_ID`
   and returns `None` if unset (not a `RuntimeError` — this feature is
   fully optional, unlike the invite code which only degrades on the
   `/start` path).
2. `handle_group_message(update, context)`: extract a URL with the
   existing `extract_first_url()`. No URL → return immediately, no
   reply of any kind. URL found → `ingest_url(url)` then reply with
   `format_ingest_reply(result)`.
3. `main()` registers the DM handler scoped to
   `filters.ChatType.PRIVATE` (narrowing it from today's unscoped
   `filters.TEXT`, since group messages must now go to the other
   handler instead) and, only when `get_group_chat_id()` returns a
   value, registers the group handler scoped to that exact chat ID.

One alternative considered and set aside: checking the chat ID inside
the handler body instead of via a filter. Rejected because the filter
approach fails closed (wrong chat ID just means the handler never
fires) and keeps `main()` as the single place authorization-by-chat is
decided, mirroring how user-ID authorization is centralized today.

## What's left to the builder

- Whether the group reply skips the "⏳ Processing..." ack message
  DMs send before the final result (recommended: skip it, to keep the
  group quieter — a busy group doesn't need two bot messages per
  link).
- Exact README wording for locating a group's numeric chat ID (e.g.
  temporarily enabling privacy-mode-off, adding the bot, and reading
  the chat ID from the first update `getUpdates` returns, or using a
  utility bot like @RawDataBot) — not load-bearing, just needs to be
  correct and tested manually once before publishing.
