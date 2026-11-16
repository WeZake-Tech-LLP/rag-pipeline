# Telegram Multi-User Access — Design (short)

## Intent and why

The bot currently only responds to one hardcoded `TELEGRAM_ALLOWED_USER_ID`.
The user wants to share it with at least one other person (more later,
if it comes up), without manually collecting everyone's numeric
Telegram ID beforehand.

## Goals

- A person the owner wants to invite can start using the bot by
  clicking one link and tapping "Start" — no typed commands, no
  sending their ID to the owner first.
- The owner's existing experience is unchanged — they keep working
  exactly as today, zero new steps for them.
- Anyone who never had that link still gets silently ignored, same as
  today's behavior for strangers.

## Non-goals (explicitly out of scope for this iteration)

- No private-per-user data. Confirmed: everyone approved shares one
  knowledge base, same as the owner uses today.
- No in-bot way to revoke/remove an approved user. Removing someone
  means manually editing the approved-users file for now.
- No multiple admins / multiple invite codes. One owner, one shared
  invite code.

## Anti-goals

- Must never make authorization accidentally permissive (e.g. a bug
  that lets an unapproved message through).
- Must not require the owner to do anything differently than today.

## Constraints

- Reuses `ingest_url()` / `query_knowledge_base()` unmodified — this
  is purely about *who* can message the bot, not what happens once
  they're in.
- No new dependency — Python's built-in `json` module is enough for
  the approved-users list.
- New `.env` value: `TELEGRAM_INVITE_CODE`.
- New file, `telegram_approved_users.json`, holds the approved user ID
  list — added to `.gitignore` (it will contain real people's Telegram
  IDs; this is runtime state, not source, same category as `.env` and
  `chroma_db/`).

## Approach (decided in conversation)

Telegram's deep-link feature: a link shaped
`https://t.me/<BotUsername>?start=<code>` causes Telegram to send
`/start <code>` automatically the moment someone taps "Start" — no
typing required on their end. The bot:

1. Detects a message matching `/start <code>`.
2. If `<code>` matches `TELEGRAM_INVITE_CODE`, adds the sender's user
   ID to `telegram_approved_users.json` and replies with a welcome
   message.
3. If it doesn't match, the message is silently ignored — same
   treatment as any other unauthorized message.
4. For every other message, authorization becomes: the owner's ID
   (`TELEGRAM_ALLOWED_USER_ID`, unchanged) **or** present in the
   approved-users file.

Two alternatives considered and set aside: a typed `/join <code>`
command (same idea, worse UX — requires the person to type a command
instead of just tapping a link), and a pre-collected comma-separated
ID list in `.env` (brings back the exact manual-ID-collection friction
this feature exists to avoid).

## What's left to the builder

- Exact JSON shape for `telegram_approved_users.json` (a flat list of
  ints is sufficient; no need for anything richer, since there's no
  per-user metadata to track yet).
- Whether the welcome reply text differs from a plain "already
  approved" reply if someone re-clicks the link after already joining
  (a small UX nicety, not load-bearing).
