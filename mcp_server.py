"""MCP server: a third entry point into the same RAG knowledge base."""

from query import query_knowledge_base, format_query_reply


def search_knowledge_base_impl(question: str, filter_type: str = None, filter_url: str = None) -> str:
    result = query_knowledge_base(question, filter_type=filter_type, filter_url=filter_url)
    return format_query_reply(result)
