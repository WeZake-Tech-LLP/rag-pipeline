# RAG Knowledge Base

A local **Retrieval-Augmented Generation (RAG)** pipeline with a **Streamlit** web UI. You ingest content from URLs (articles, YouTube, LinkedIn posts), store chunked embeddings in **ChromaDB**, and ask questions grounded in those sources using **Groq** as the LLM.

---

## What It Does

- **Ingest URLs** from the sidebar: detects YouTube, LinkedIn, or generic web articles.
- **Extracts text** using multiple strategies (e.g. YouTube transcripts via `youtube-transcript-api`, Jina Reader fallbacks, `yt-dlp` for captions; articles via Jina Reader or BeautifulSoup).
- **Chunks & embeds** text with LlamaIndex’s `SentenceSplitter` and **Hugging Face** embeddings (`sentence-transformers/all-MiniLM-L6-v2`).
- **Stores vectors** in a persistent **ChromaDB** collection (`./chroma_db` relative to where you run the app).
- **Answers questions** by retrieving similar chunks and calling **Groq** (`llama-3.3-70b-versatile`), with optional filters by content type or exact URL.

If retrieval finds nothing relevant, the model may answer from general knowledge (marked clearly in the UI).

---

## Tools & Technologies

| Area | Stack |
|------|--------|
| Language | Python 3 |
| UI | [Streamlit](https://streamlit.io/) |
| Vector DB | [ChromaDB](https://www.trychroma.com/) (persistent, local) |
| Embeddings | [LlamaIndex HuggingFace embeddings](https://docs.llamaindex.ai/) + [sentence-transformers](https://www.sbert.net/) |
| Chunking | [LlamaIndex SentenceSplitter](https://docs.llamaindex.ai/) |
| LLM API | [Groq](https://groq.com/) via official `groq` SDK |
| HTTP / parsing | `requests`, [BeautifulSoup](https://www.crummy.com/software/BeautifulSoup/) |
| YouTube | `youtube-transcript-api`, `yt-dlp` |
| Config | `python-dotenv` (`.env` for secrets) |

Main Python modules:

- `rag_project/app.py` — Streamlit UI (ingest + query).
- `rag_project/ingest.py` — URL detection, extraction, chunking, indexing into ChromaDB.
- `rag_project/query.py` — Retrieval, optional filters, Groq chat completion.

Dependencies are listed in `rag_project/requirements.txt`.

---

## Prerequisites

- **Python 3.10+** recommended (project has been used with Python 3.13).
- **Groq API key** — create one at [Groq Console](https://console.groq.com/).
- **Internet access** — for Groq, Hugging Face model download (first run), Jina Reader / transcript APIs, and URL fetching.
- **Disk space** — PyTorch + transformers + embedding model cache can be several GB.

Optional: **ffmpeg** can help some `yt-dlp` workflows; many subtitle-only flows work without it.

---

## Run Locally on Your Laptop

### 1. Clone or open the project

```bash
cd "/path/to/rag pipeline"
```

### 2. Create and activate a virtual environment

```bash
cd rag_project
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure Groq

Create a `.env` file **inside `rag_project/`** (same folder as `app.py`):

```env
GROQ_API_KEY=your_groq_api_key_here
```

### 5. Start the Streamlit app

From **`rag_project/`** (important so `./chroma_db` is created in the right place):

```bash
streamlit run app.py
```

Your browser should open to the local URL Streamlit prints (typically `http://localhost:8501`).

### 6. Use the app

1. In the sidebar, paste a URL and click **Add to Knowledge Base**.
2. Wait for ingestion (first embed download may take a few minutes).
3. Ask a question in the main area and click **Ask**.
4. Use **Advanced Filters** if you want to scope retrieval by type (YouTube / LinkedIn / Article) or by exact URL.
5. Click 🗑️ next to any source in the sidebar to remove it (and all its stored chunks) from the knowledge base.

---

## Telegram Bot (optional second entry point)

Alongside the Streamlit UI, you can run a personal Telegram bot that lets
you ingest links and ask questions directly from Telegram. It shares the
same `./chroma_db` knowledge base as Streamlit — nothing needs to be kept
in sync, they just read/write the same folder.

### 1. Create a bot and get a token

Message **@BotFather** on Telegram, send `/newbot`, and follow the
prompts. It replies with a token in the form `<digits>:<secret>` —
add it to `.env`:

```env
TELEGRAM_BOT_TOKEN=123456789:your_token_here
```

### 2. Get your Telegram user ID

Message **@userinfobot** on Telegram — it replies with your numeric user
ID. Add it to `.env`:

```env
TELEGRAM_ALLOWED_USER_ID=your_numeric_id_here
```

Only messages from this user ID are processed; everyone else is
silently ignored.

### 3. Run the bot

```bash
source .venv/bin/activate
python telegram_bot.py
```

It runs continuously (like Streamlit) — leave it running, or run it
alongside `streamlit run app.py` in a separate terminal.

### 4. Use it

- Send a URL (YouTube, LinkedIn, Reddit, or an article link) to ingest it.
- Send any other text to ask a question against the knowledge base.
- Only URLs are supported for ingestion — raw pasted text isn't yet.

### 5. Invite other people (optional)

To let someone else use the bot without collecting their Telegram ID
yourself, pick a secret invite phrase and add it to `.env`:

```env
TELEGRAM_INVITE_CODE=your_secret_phrase_here
```

Then share this link with them (replace `<BotUsername>` with your
bot's actual username, and `<your_secret_phrase_here>` with the code
above):

```
https://t.me/<BotUsername>?start=<your_secret_phrase_here>
```

When they open that link and tap "Start," Telegram sends the code to
the bot automatically — no typing, no ID collection. They're approved
from then on, and share the same knowledge base as the owner. Treat
that link like any shared secret link: anyone who has it can join, so
only send it to people you intend to invite.

### 6. Ingest links from a group (optional)

The bot can also watch one Telegram group: anyone in that group can
drop a link and it gets ingested automatically, with a short
confirmation reply. Everything else in the group — questions, regular
chat — is ignored completely; there's no Q&A in group context, only in
DMs.

1. **Disable the bot's privacy mode first.** By default, bots only see
   messages that mention them. Message **@BotFather**, send
   `/mybots`, pick your bot, go to **Bot Settings → Group Privacy**,
   and turn privacy **off**. Telegram generally only applies this to
   groups the bot joins *after* the change, so do this before the next
   step — if the bot is already in the group, remove it and re-add it
   afterward.
2. **Add the bot to the group** like any other member.
3. **Stop the bot process** if it's already running, then send any
   message in the group. Visit
   `https://api.telegram.org/bot<your_token_here>/getUpdates` in a
   browser and look for `"chat":{"id": ...}` in the response — that's
   the group's numeric chat ID (negative for groups; `-100...` for
   supergroups). This only works while the bot isn't polling, since a
   running bot consumes each update before `getUpdates` can read it.
4. **Add it to `.env`:**

   ```env
   TELEGRAM_GROUP_CHAT_ID=your_negative_group_chat_id_here
   ```

5. **Start the bot.** From then on, any link posted in that group is
   ingested into the same shared knowledge base as DMs and the
   Streamlit UI; non-link messages get no reply at all. If the group is
   later converted to a supergroup, its chat ID changes (it gains the
   `-100` prefix) and `TELEGRAM_GROUP_CHAT_ID` must be updated to match.

If `TELEGRAM_GROUP_CHAT_ID` is left unset, this feature is simply off
and the bot behaves exactly as it does today.

---

## MCP Server (connect Claude Code directly)

`mcp_server.py` exposes this same knowledge base to Claude Code as three
tools — `search_knowledge_base`, `add_to_knowledge_base`, and
`remove_from_knowledge_base` — over the network, instead of the old
stdio-only setup. That means one running copy can serve Claude Code on
this machine *and* anyone else's, once they have the URL and the shared
token below.

### 1. Set the shared secret

```env
MCP_SHARED_TOKEN=pick_a_long_random_secret_here
```

Optionally also set `MCP_PUBLIC_URL` to whatever address this server
will actually be reachable at (defaults to `http://localhost:8000`,
which is only useful for testing on the same machine).

### 2. Run it

```bash
source .venv/bin/activate
python mcp_server.py
```

It listens on `0.0.0.0:8000` and checks every request's
`Authorization: Bearer <token>` header against `MCP_SHARED_TOKEN`
— no token, or the wrong one, gets a `401`.

### 3. Connect Claude Code to it

If you previously registered this server as a local stdio process
(Claude Code launching `mcp_server.py` itself), remove that registration
first — it will otherwise try to start the old way and fail, since
`main()` now requires `MCP_SHARED_TOKEN` and speaks HTTP, not stdio:

```bash
claude mcp remove rag-knowledge-base
```

Then add it back pointed at the running server instead:

```bash
claude mcp add --transport http rag-knowledge-base <MCP_PUBLIC_URL>/mcp -H "Authorization: Bearer <your_token>"
```

Unlike the old stdio setup, Claude Code no longer starts this process
for you — `python mcp_server.py` has to already be running (even for
local-only use) before you connect to it.

Share the URL and token with anyone else you want to have the same
access — same spirit as the Telegram invite link, no install needed on
their end.

**Two things worth knowing:**
- This only covers the server code. Actually putting it somewhere
  always-on (a cloud VM, for example) is a separate, manual deployment
  step this change doesn't do by itself.
- This is plain HTTP, not HTTPS — the token travels unencrypted over
  the network. That matches this project's current "demo, not
  hardened" security posture; revisit before using this for anything
  sensitive.

---

## Project Layout

```
rag pipeline/
├── README.md
└── rag_project/
    ├── app.py
    ├── ingest.py
    ├── query.py
    ├── requirements.txt
    ├── .env              # you create this; not committed
    └── chroma_db/        # created at runtime after first ingest
```

---

## Troubleshooting

- **Empty or failed answers** — Confirm `GROQ_API_KEY` is set and you are not rate-limited.
- **YouTube / LinkedIn extraction fails** — Some pages block scrapers or have no captions; try another URL or check network access to Jina Reader.
- **Slow first run** — The embedding model downloads from Hugging Face on first use; subsequent runs are faster.

---

## License

Add a license here if you publish the repository.
