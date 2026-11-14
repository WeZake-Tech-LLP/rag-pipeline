from unittest.mock import patch, call, MagicMock

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
    import mcp_server
    import os
    expected = os.path.dirname(os.path.abspath(mcp_server.__file__))
    with patch("mcp_server.os.chdir") as mock_chdir:
        pin_working_directory()
    mock_chdir.assert_called_once_with(expected)


def test_main_calls_pin_then_warmup_then_run_in_order():
    import mcp_server
    manager = MagicMock()
    with patch("mcp_server.pin_working_directory", manager.pin), \
         patch("mcp_server.warmup_models", manager.warmup), \
         patch.object(mcp_server.server, "run", manager.run):
        mcp_server.main()
    assert manager.mock_calls == [call.pin(), call.warmup(), call.run()]


def test_warmup_models_loads_all_three():
    with patch("mcp_server.get_embed_model") as mock_embed, \
         patch("mcp_server.get_reranker") as mock_reranker, \
         patch("mcp_server.get_groq_client") as mock_groq, \
         patch("mcp_server.ingest_get_embed_model") as mock_ingest_embed, \
         patch("mcp_server.ingest_get_collection") as mock_ingest_collection:
        warmup_models()
    mock_embed.assert_called_once()
    mock_reranker.assert_called_once()
    mock_groq.assert_called_once()
    # ingest.py has its own separate singletons from query.py's — both
    # must be warmed, or the first real ingest call still cold-loads.
    mock_ingest_embed.assert_called_once()
    mock_ingest_collection.assert_called_once()


def test_add_passes_url_through_and_formats_success():
    with patch("mcp_server.ingest_url", return_value={"success": True, "duplicate": False, "chunks_stored": 4, "extraction_quality": "full_text", "url_type": "reddit"}) as mock_ingest:
        result = add_to_knowledge_base_impl("https://example.com/post")
    mock_ingest.assert_called_once_with("https://example.com/post")
    assert "4" in result


def test_add_handles_duplicate():
    # ingest_url() actually returns success=False for duplicates (see ingest.py:573-577)
    with patch("mcp_server.ingest_url", return_value={"success": False, "duplicate": True, "message": "URL already exists in knowledge base"}):
        result = add_to_knowledge_base_impl("https://example.com/post")
    assert "already exists" in result.lower()
    assert "Failed" not in result


def test_add_handles_failure():
    with patch("mcp_server.ingest_url", return_value={"success": False, "duplicate": False, "message": "Could not extract content: boom"}):
        result = add_to_knowledge_base_impl("https://example.com/post")
    assert "boom" in result
