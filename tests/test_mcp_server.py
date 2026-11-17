import asyncio
from unittest.mock import patch, call, MagicMock

import pytest

from mcp_server import (
    search_knowledge_base_impl,
    pin_working_directory,
    warmup_models,
    add_to_knowledge_base_impl,
)


def test_get_mcp_shared_token_missing_raises(monkeypatch):
    from mcp_server import get_mcp_shared_token
    monkeypatch.delenv("MCP_SHARED_TOKEN", raising=False)
    with pytest.raises(RuntimeError):
        get_mcp_shared_token()


def test_get_mcp_shared_token_present_returns_value(monkeypatch):
    from mcp_server import get_mcp_shared_token
    monkeypatch.setenv("MCP_SHARED_TOKEN", "secret123")
    assert get_mcp_shared_token() == "secret123"


def test_get_mcp_public_url_defaults_to_localhost(monkeypatch):
    from mcp_server import get_mcp_public_url
    monkeypatch.delenv("MCP_PUBLIC_URL", raising=False)
    assert get_mcp_public_url() == "http://localhost:8000"


def test_get_mcp_public_url_respects_env_override(monkeypatch):
    from mcp_server import get_mcp_public_url
    monkeypatch.setenv("MCP_PUBLIC_URL", "http://203.0.113.5:8000")
    assert get_mcp_public_url() == "http://203.0.113.5:8000"


def test_verify_token_accepts_correct_shared_token(monkeypatch):
    from mcp_server import SharedTokenVerifier
    monkeypatch.setenv("MCP_SHARED_TOKEN", "secret123")
    result = asyncio.run(SharedTokenVerifier().verify_token("secret123"))
    assert result is not None
    assert result.token == "secret123"


def test_verify_token_rejects_wrong_token(monkeypatch):
    from mcp_server import SharedTokenVerifier
    monkeypatch.setenv("MCP_SHARED_TOKEN", "secret123")
    result = asyncio.run(SharedTokenVerifier().verify_token("wrong"))
    assert result is None


def test_verify_token_rejects_truncated_token(monkeypatch):
    from mcp_server import SharedTokenVerifier
    monkeypatch.setenv("MCP_SHARED_TOKEN", "secret123")
    result = asyncio.run(SharedTokenVerifier().verify_token("secret12"))
    assert result is None


def test_verify_token_rejects_token_with_trailing_whitespace(monkeypatch):
    from mcp_server import SharedTokenVerifier
    monkeypatch.setenv("MCP_SHARED_TOKEN", "secret123")
    result = asyncio.run(SharedTokenVerifier().verify_token("secret123\n"))
    assert result is None


def test_verify_token_fails_closed_when_not_configured(monkeypatch):
    from mcp_server import SharedTokenVerifier
    monkeypatch.delenv("MCP_SHARED_TOKEN", raising=False)
    result = asyncio.run(SharedTokenVerifier().verify_token("anything"))
    assert result is None


def test_search_passes_question_and_filters_through():
    with patch("query.query_knowledge_base", return_value={"success": True, "answer": "It's about X.", "sources": []}) as mock_query:
        result = search_knowledge_base_impl("what is this about?", filter_type="reddit", filter_url="https://example.com")
    mock_query.assert_called_once_with("what is this about?", filter_type="reddit", filter_url="https://example.com")
    assert "It's about X." in result


def test_search_handles_empty_question():
    with patch("query.query_knowledge_base", return_value={"success": False, "error": "Please enter a question."}) as mock_query:
        result = search_knowledge_base_impl("")
    mock_query.assert_called_once_with("", filter_type=None, filter_url=None)
    assert "Please enter a question." in result


def test_search_handles_empty_knowledge_base():
    with patch("query.query_knowledge_base", return_value={"success": True, "answer": "Knowledge base is empty. Please add some URLs first.", "sources": []}):
        result = search_knowledge_base_impl("anything")
    assert "Knowledge base is empty" in result


def test_search_handles_no_filter_match_gracefully():
    with patch("query.query_knowledge_base", return_value={"success": True, "answer": "Not found in knowledge base.", "sources": []}):
        result = search_knowledge_base_impl("x", filter_type="youtube", filter_url="https://nonexistent.example")
    assert "Not found in knowledge base." in result


def test_pin_working_directory_chdirs_to_script_location():
    import mcp_server
    import os
    expected = os.path.dirname(os.path.abspath(mcp_server.__file__))
    with patch("mcp_server.os.chdir") as mock_chdir:
        pin_working_directory()
    mock_chdir.assert_called_once_with(expected)


def test_main_fails_fast_when_shared_token_not_configured(monkeypatch):
    import mcp_server
    monkeypatch.delenv("MCP_SHARED_TOKEN", raising=False)
    with patch("mcp_server.pin_working_directory"), \
         patch("mcp_server.threading.Thread") as mock_thread_cls, \
         patch.object(mcp_server.server, "run") as mock_run:
        with pytest.raises(RuntimeError):
            mcp_server.main()
    mock_thread_cls.assert_not_called()
    mock_run.assert_not_called()


def test_main_pins_cwd_then_runs_without_waiting_for_warmup(monkeypatch):
    # warmup_models() takes ~30s (loads torch/transformers/reranker/Groq
    # client); if main() waited for it before server.run(), the MCP
    # client's connection handshake would time out before the server
    # even starts listening. Warmup must run in a background thread so
    # server.run() is reached immediately.
    monkeypatch.setenv("MCP_SHARED_TOKEN", "secret123")
    import mcp_server
    manager = MagicMock()
    with patch("mcp_server.pin_working_directory", manager.pin), \
         patch("mcp_server.threading.Thread") as mock_thread_cls, \
         patch.object(mcp_server.server, "run", manager.run):
        mock_thread_instance = MagicMock()
        mock_thread_cls.return_value = mock_thread_instance
        mcp_server.main()
    manager.pin.assert_called_once()
    mock_thread_cls.assert_called_once_with(target=mcp_server.warmup_models, daemon=True)
    mock_thread_instance.start.assert_called_once()
    manager.run.assert_called_once_with(transport="streamable-http", host="0.0.0.0", port=8000)


def test_warmup_models_loads_all_three():
    with patch("query.get_embed_model") as mock_embed, \
         patch("query.get_reranker") as mock_reranker, \
         patch("query.get_groq_client") as mock_groq, \
         patch("ingest.get_embed_model") as mock_ingest_embed, \
         patch("ingest.get_collection") as mock_ingest_collection:
        warmup_models()
    mock_embed.assert_called_once()
    mock_reranker.assert_called_once()
    mock_groq.assert_called_once()
    # ingest.py has its own separate singletons from query.py's — both
    # must be warmed, or the first real ingest call still cold-loads.
    mock_ingest_embed.assert_called_once()
    mock_ingest_collection.assert_called_once()


def test_add_passes_url_through_and_formats_success():
    with patch("ingest.ingest_url", return_value={"success": True, "duplicate": False, "chunks_stored": 4, "extraction_quality": "full_text", "url_type": "reddit"}) as mock_ingest:
        result = add_to_knowledge_base_impl("https://example.com/post")
    mock_ingest.assert_called_once_with("https://example.com/post")
    assert "4" in result


def test_add_handles_duplicate():
    # ingest_url() actually returns success=False for duplicates (see ingest.py:573-577)
    with patch("ingest.ingest_url", return_value={"success": False, "duplicate": True, "message": "URL already exists in knowledge base"}):
        result = add_to_knowledge_base_impl("https://example.com/post")
    assert "already exists" in result.lower()
    assert "Failed" not in result


def test_add_handles_failure():
    with patch("ingest.ingest_url", return_value={"success": False, "duplicate": False, "message": "Could not extract content: boom"}):
        result = add_to_knowledge_base_impl("https://example.com/post")
    assert "boom" in result
