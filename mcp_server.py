"""MCP server: a third entry point into the same RAG knowledge base."""

import os

from mcp.server.mcpserver import MCPServer

from ingest import (
    ingest_url,
    format_ingest_reply,
    get_embed_model as ingest_get_embed_model,
    get_collection as ingest_get_collection,
)
from query import (
    query_knowledge_base,
    format_query_reply,
    get_embed_model,
    get_reranker,
    get_groq_client,
)


def search_knowledge_base_impl(question: str, filter_type: str = None, filter_url: str = None) -> str:
    result = query_knowledge_base(question, filter_type=filter_type, filter_url=filter_url)
    return format_query_reply(result)


def add_to_knowledge_base_impl(url: str) -> str:
    result = ingest_url(url)
    return format_ingest_reply(result)


def pin_working_directory() -> None:
    os.chdir(os.path.dirname(os.path.abspath(__file__)))


def warmup_models() -> None:
    get_embed_model()
    get_reranker()
    get_groq_client()
    # ingest.py keeps its own separate singletons from query.py's — both
    # must be warmed, or the first real ingest call still cold-loads.
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
    warmup_models()
    server.run()


if __name__ == "__main__":
    main()
