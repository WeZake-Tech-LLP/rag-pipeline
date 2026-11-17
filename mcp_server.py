"""MCP server: a third entry point into the same RAG knowledge base."""

import os
import threading

from mcp.server.mcpserver import MCPServer

# `ingest`/`query` are imported lazily, inside each function, rather than
# at module level: they transitively pull in torch/transformers/chromadb
# just by being imported, which takes ~20s on its own — before any model
# is actually instantiated. Importing them here would delay server.run()
# (and the MCP client's connection handshake) by that same ~20s, even
# with warmup already backgrounded. Deferring the import moves that cost
# to first real use, the same place warmup's own cost already lives.


def search_knowledge_base_impl(question: str, filter_type: str = None, filter_url: str = None) -> str:
    from query import query_knowledge_base, format_query_reply
    result = query_knowledge_base(question, filter_type=filter_type, filter_url=filter_url)
    return format_query_reply(result)


def add_to_knowledge_base_impl(url: str) -> str:
    from ingest import ingest_url, format_ingest_reply
    result = ingest_url(url)
    return format_ingest_reply(result)


def get_mcp_shared_token() -> str:
    token = os.getenv("MCP_SHARED_TOKEN", "").strip()
    if not token:
        raise RuntimeError("MCP_SHARED_TOKEN is not set in .env")
    return token


def get_mcp_public_url() -> str:
    return os.getenv("MCP_PUBLIC_URL", "http://localhost:8000").strip() or "http://localhost:8000"


def pin_working_directory() -> None:
    os.chdir(os.path.dirname(os.path.abspath(__file__)))


def warmup_models() -> None:
    from query import get_embed_model, get_reranker, get_groq_client
    # ingest.py keeps its own separate singletons from query.py's — both
    # must be warmed, or the first real ingest call still cold-loads.
    from ingest import get_embed_model as ingest_get_embed_model, get_collection as ingest_get_collection

    get_embed_model()
    get_reranker()
    get_groq_client()
    ingest_get_embed_model()
    ingest_get_collection()


server = MCPServer("rag-knowledge-base")


@server.tool()
def search_knowledge_base(question: str, filter_type: str = "", filter_url: str = "") -> str:
    """Search this personal RAG knowledge base (YouTube, LinkedIn, Reddit,
    X/Twitter, Facebook, Instagram, and article content the user has
    ingested) and answer a question grounded in it.

    filter_type: optional, one of youtube/linkedin/reddit/x/facebook/instagram/article
    filter_url: optional, an exact source URL already in the knowledge base
    """
    return search_knowledge_base_impl(question, filter_type or None, filter_url or None)


@server.tool()
def add_to_knowledge_base(url: str) -> str:
    """Save a URL (YouTube, LinkedIn, Reddit, X/Twitter, Facebook,
    Instagram, or a generic article) into this personal RAG knowledge
    base, so it can be searched later via search_knowledge_base. Use
    this when the user asks to save, add, or ingest a link — not for
    a bare URL with no indication they want it stored.
    """
    return add_to_knowledge_base_impl(url)


def main() -> None:
    pin_working_directory()
    # Run in the background: warmup takes ~30s (torch/transformers/
    # reranker/Groq client), and if server.run() waited for it, the
    # MCP client's connection handshake would time out before the
    # server even started listening.
    threading.Thread(target=warmup_models, daemon=True).start()
    server.run()


if __name__ == "__main__":
    main()
