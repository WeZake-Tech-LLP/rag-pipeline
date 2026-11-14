from unittest.mock import patch

from mcp_server import search_knowledge_base_impl


def test_search_passes_question_and_filters_through():
    with patch("mcp_server.query_knowledge_base", return_value={"success": True, "answer": "It's about X.", "sources": []}) as mock_query:
        result = search_knowledge_base_impl("what is this about?", filter_type="reddit", filter_url="https://example.com")
    mock_query.assert_called_once_with("what is this about?", filter_type="reddit", filter_url="https://example.com")
    assert "It's about X." in result


def test_search_handles_empty_question():
    with patch("mcp_server.query_knowledge_base", return_value={"success": False, "error": "Please enter a question."}) as mock_query:
        result = search_knowledge_base_impl("")
    mock_query.assert_called_once_with("", filter_type=None, filter_url=None)
    assert "Please enter a question." in result


def test_search_handles_empty_knowledge_base():
    with patch("mcp_server.query_knowledge_base", return_value={"success": True, "answer": "Knowledge base is empty. Please add some URLs first.", "sources": []}):
        result = search_knowledge_base_impl("anything")
    assert "Knowledge base is empty" in result


def test_search_handles_no_filter_match_gracefully():
    with patch("mcp_server.query_knowledge_base", return_value={"success": True, "answer": "Not found in knowledge base.", "sources": []}):
        result = search_knowledge_base_impl("x", filter_type="youtube", filter_url="https://nonexistent.example")
    assert "Not found in knowledge base." in result
