import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram_bot import (
    get_bot_token,
    get_allowed_user_id,
    extract_first_url,
    is_authorized,
    format_ingest_reply,
    format_query_reply,
    build_reply,
    handle_message,
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


def _make_update(user_id, text):
    update = MagicMock()
    update.effective_user.id = user_id
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


def test_handle_message_ignores_unauthorized_sender():
    update = _make_update(999, "https://example.com")
    with patch("telegram_bot.get_allowed_user_id", return_value=111):
        asyncio.run(handle_message(update, None))
    update.message.reply_text.assert_not_called()


def test_handle_message_replies_for_authorized_sender():
    update = _make_update(111, "https://example.com")
    with patch("telegram_bot.get_allowed_user_id", return_value=111), \
         patch("telegram_bot.build_reply", return_value="done"):
        asyncio.run(handle_message(update, None))
    assert update.message.reply_text.call_count == 2  # ack, then final reply
    final_call_text = update.message.reply_text.call_args_list[-1].args[0]
    assert final_call_text == "done"


def test_get_invite_code_missing_raises(monkeypatch):
    from telegram_bot import get_invite_code
    monkeypatch.delenv("TELEGRAM_INVITE_CODE", raising=False)
    with pytest.raises(RuntimeError):
        get_invite_code()


def test_get_invite_code_present(monkeypatch):
    from telegram_bot import get_invite_code
    monkeypatch.setenv("TELEGRAM_INVITE_CODE", "secret123")
    assert get_invite_code() == "secret123"


def test_load_approved_users_missing_file_returns_empty_set(tmp_path, monkeypatch):
    import telegram_bot
    monkeypatch.setattr(telegram_bot, "APPROVED_USERS_PATH", str(tmp_path / "approved.json"))
    assert telegram_bot.load_approved_users() == set()


def test_save_then_load_approved_users_round_trips(tmp_path, monkeypatch):
    import telegram_bot
    monkeypatch.setattr(telegram_bot, "APPROVED_USERS_PATH", str(tmp_path / "approved.json"))
    telegram_bot.save_approved_users({111, 222})
    assert telegram_bot.load_approved_users() == {111, 222}


def test_parse_start_command_extracts_code():
    from telegram_bot import parse_start_command
    assert parse_start_command("/start family2026") == "family2026"


def test_parse_start_command_returns_none_for_bare_start():
    from telegram_bot import parse_start_command
    assert parse_start_command("/start") is None


def test_parse_start_command_returns_none_for_non_start_text():
    from telegram_bot import parse_start_command
    assert parse_start_command("what is this about?") is None
