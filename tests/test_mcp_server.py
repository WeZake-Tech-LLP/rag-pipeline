from unittest.mock import patch, call

from mcp_server import (
    search_knowledge_base_impl,
    pin_working_directory,
    warmup_models,
    add_to_knowledge_base_impl,
)


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


def test_pin_working_directory_chdirs_to_script_location():
    with patch("mcp_server.os.chdir") as mock_chdir, patch("mcp_server.os.path.dirname", return_value="/fake/script/dir"):
        pin_working_directory()
    mock_chdir.assert_called_once_with("/fake/script/dir")


def test_warmup_models_loads_all_three():
    with patch("mcp_server.get_embed_model") as mock_embed, \
         patch("mcp_server.get_reranker") as mock_reranker, \
         patch("mcp_server.get_groq_client") as mock_groq:
        warmup_models()
    mock_embed.assert_called_once()
    mock_reranker.assert_called_once()
    mock_groq.assert_called_once()


def test_add_passes_url_through_and_formats_success():
    with patch("mcp_server.ingest_url", return_value={"success": True, "duplicate": False, "chunks_stored": 4, "extraction_quality": "full_text", "url_type": "reddit"}) as mock_ingest:
        result = add_to_knowledge_base_impl("https://example.com/post")
    mock_ingest.assert_called_once_with("https://example.com/post")
    assert "4" in result


def test_add_handles_duplicate():
    with patch("mcp_server.ingest_url", return_value={"success": True, "duplicate": True}):
        result = add_to_knowledge_base_impl("https://example.com/post")
    assert "already exists" in result.lower()


def test_add_handles_failure():
    with patch("mcp_server.ingest_url", return_value={"success": False, "duplicate": False, "message": "Could not extract content: boom"}):
        result = add_to_knowledge_base_impl("https://example.com/post")
    assert "boom" in result
