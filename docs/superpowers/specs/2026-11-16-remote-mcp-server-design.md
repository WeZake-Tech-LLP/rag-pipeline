# Remote MCP Server — Design (short)

## Intent and why

The MCP server currently only runs locally via stdio, read by the exact
machine it's installed on. Once the bot and knowledge base move to an
always-on VM (a separate, not-yet-started piece of work), a laptop-local
MCP server would be reading a stale, out-of-date copy of the knowledge
base. This makes the MCP server itself remotely reachable, so Claude
Code — on this laptop or anyone else's — always talks to the one live
knowledge base directly, with no sync step.

## Goals

- `mcp_server.py` runs as a small networked HTTP service instead of a
  local stdio process, using the MCP SDK's own `streamable-http`
  transport.
- It's protected by a single shared secret (a bearer token), checked on
  every request — not left open to anyone who finds the URL.
- Inviting someone else to use it is just handing them a URL and the
  token — no install, no code, mirroring the Telegram invite link.

## Non-goals (explicitly out of scope for this iteration)

- Not provisioning the Oracle VM itself, or deploying this service to
  it — that's a separate, manual, guided step once this code exists and
  is verified locally. This plan only changes `mcp_server.py` and
  proves it works with a local HTTP request.
- Not per-person tokens. Confirmed: one shared token for everyone,
  matching the Telegram invite-code precedent. Revoking access means
  rotating the token for everyone, same tradeoff already accepted there.
- Not real OAuth (dynamic client registration, authorization codes,
  token issuance). The MCP SDK's auth plumbing is reused only for its
  bearer-token-checking middleware; the "token" is a long static
  secret, handed out exactly like the Telegram invite code.
- Not HTTPS/TLS for this iteration. Confirmed: plain HTTP, consistent
  with the project's established "demo, not hardened" security
  posture. The token travels unencrypted; revisit if this moves beyond
  demo use.

## Anti-goals

- Must never serve a request with a missing or wrong token.
- Must not require the SDK's full OAuth discovery/dynamic-registration
  flow — Claude Code just sends a static `Authorization: Bearer
  <token>` header per the `claude mcp add --transport http ... -H
  "Authorization: Bearer <token>"` pattern already confirmed against
  the installed CLI.

## Constraints

- MCP SDK version already installed: 2.3.0, confirmed to support
  `server.run(transport="streamable-http", host=..., port=...)` and a
  `TokenVerifier` protocol (`async def verify_token(token: str) ->
  AccessToken | None`) passed via the `MCPServer(..., token_verifier=...,
  auth=AuthSettings(...))` constructor — reusing this rather than
  hand-rolling ASGI middleware.
- `AuthSettings` requires `issuer_url` and `resource_server_url`
  (both just syntactically-valid URLs — they feed discovery metadata
  routes this flow never uses, since the token is supplied manually via
  `-H`, not through OAuth discovery). Both come from a new env var,
  `MCP_PUBLIC_URL`, defaulting to `http://localhost:8000` for local
  testing before a real VM URL exists.
- New required env var: `MCP_SHARED_TOKEN`.
- Existing tools (`search_knowledge_base`, `add_to_knowledge_base`) and
  their implementations are unchanged — this only changes *how the
  server is reached*, not what it does once reached.

## Approach (decided in conversation)

1. `get_mcp_shared_token() -> str` reads `MCP_SHARED_TOKEN`, raising
   `RuntimeError` if unset — mirrors `telegram_bot.py`'s
   `get_bot_token()` fail-fast pattern exactly.
2. `SharedTokenVerifier` (implements the SDK's `TokenVerifier`
   protocol): `verify_token(token)` returns a valid `AccessToken` when
   `token == get_mcp_shared_token()`, else `None`.
3. The `MCPServer(...)` constructor gains `auth=AuthSettings(
   issuer_url=..., resource_server_url=...)` and
   `token_verifier=SharedTokenVerifier()`.
4. `main()` calls `server.run(transport="streamable-http", host="0.0.0.0",
   port=8000)` instead of today's bare `server.run()` (stdio).

One alternative considered and set aside: hand-writing a small ASGI
middleware function to check the header ourselves, bypassing the SDK's
auth settings entirely. Rejected because the SDK's `TokenVerifier` path
is already implemented, tested, and handles the header-parsing/401
edge cases correctly — reinventing it saves nothing and risks a subtly
wrong 401 response shape that a real MCP client might not parse the
same way.

## What's left to the builder

- Exact values for `MCP_PUBLIC_URL`'s default (`http://localhost:8000`
  is a reasonable placeholder; the README should note it needs updating
  once a real VM URL exists).
- Whether `AccessToken`'s `client_id`/`scopes` fields need any
  particular value beyond satisfying the type — since there's only one
  shared identity, a fixed placeholder like `"shared-user"` and an
  empty scopes list is sufficient; no code reads them for authorization
  decisions beyond "was verify_token non-None."
