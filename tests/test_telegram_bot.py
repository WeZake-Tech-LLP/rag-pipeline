from unittest.mock import patch

import pytest
from telegram_bot import (
    get_bot_token,
    get_allowed_user_id,
    extract_first_url,
    is_authorized,
    format_ingest_reply,
    format_query_reply,
    build_reply,
)


def test_get_bot_token_missing_raises(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    with pytest.raises(RuntimeError):
        get_bot_token()


def test_get_bot_token_present(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:abcdefghijklmnopqrstuvwxyz0123456789")
    assert get_bot_token() == "123456789:abcdefghijklmnopqrstuvwxyz0123456789"


def test_get_allowed_user_id_missing_raises(monkeypatch):
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_ID", raising=False)
    with pytest.raises(RuntimeError):
        get_allowed_user_id()


def test_get_allowed_user_id_non_numeric_raises(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_ID", "not-a-number")
    with pytest.raises(RuntimeError):
        get_allowed_user_id()


def test_get_allowed_user_id_present(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_ID", "123456789")
    assert get_allowed_user_id() == 123456789


def test_extract_first_url_finds_url():
    assert extract_first_url("check this out https://example.com/page") == "https://example.com/page"


def test_extract_first_url_returns_none_when_no_url():
    assert extract_first_url("what is this about?") is None


def test_extract_first_url_picks_first_of_multiple():
    text = "https://a.com/1 and also https://b.com/2"
    assert extract_first_url(text) == "https://a.com/1"


def test_is_authorized_true_for_matching_id():
    assert is_authorized(111, 111) is True


def test_is_authorized_false_for_other_id():
    assert is_authorized(111, 222) is False


def test_format_ingest_reply_success():
    result = {"success": True, "duplicate": False, "chunks_stored": 6, "extraction_quality": "full_text", "url_type": "article"}
    reply = format_ingest_reply(result)
    assert "6" in reply and "article" in reply


def test_format_ingest_reply_duplicate():
    result = {"success": True, "duplicate": True, "message": "URL already exists in knowledge base"}
    assert "already exists" in format_ingest_reply(result).lower()


def test_format_ingest_reply_failure():
    result = {"success": False, "duplicate": False, "message": "Could not extract content: boom"}
    assert "boom" in format_ingest_reply(result)


def test_format_query_reply_with_sources():
    result = {"success": True, "answer": "It's about X.", "sources": ["https://example.com/a"]}
    reply = format_query_reply(result)
    assert "It's about X." in reply and "https://example.com/a" in reply


def test_format_query_reply_no_sources():
    result = {"success": True, "answer": "General knowledge answer.", "sources": []}
    reply = format_query_reply(result)
    assert "General knowledge answer." in reply


def test_format_query_reply_failure():
    result = {"success": False, "error": "Please enter a question."}
    assert "Please enter a question." in format_query_reply(result)


def test_build_reply_ingests_when_url_present():
    with patch("telegram_bot.ingest_url", return_value={"success": True, "duplicate": False, "chunks_stored": 3, "extraction_quality": "full_text", "url_type": "article"}) as mock_ingest:
        reply = build_reply("here: https://example.com/post")
    mock_ingest.assert_called_once_with("https://example.com/post")
    assert "3" in reply


def test_build_reply_queries_when_no_url():
    with patch("telegram_bot.query_knowledge_base", return_value={"success": True, "answer": "It's about X.", "sources": []}) as mock_query:
        reply = build_reply("what is this about?")
    mock_query.assert_called_once_with("what is this about?")
    assert "It's about X." in reply


def test_build_reply_catches_exception_from_ingest():
    with patch("telegram_bot.ingest_url", side_effect=RuntimeError("boom")):
        reply = build_reply("https://example.com/post")
    assert "boom" in reply


def test_build_reply_catches_exception_from_query():
    with patch("telegram_bot.query_knowledge_base", side_effect=RuntimeError("boom")):
        reply = build_reply("a question with no link")
    assert "boom" in reply


def test_build_reply_empty_message_returns_friendly_error():
    with patch("telegram_bot.query_knowledge_base", return_value={"success": False, "error": "Please enter a question."}) as mock_query:
        reply = build_reply("   ")
    mock_query.assert_called_once_with("   ")
    assert "Please enter a question." in reply
