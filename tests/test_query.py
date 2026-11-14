from query import format_query_reply


def test_format_query_reply_with_sources():
    result = {"success": True, "answer": "It's about X.", "sources": ["https://example.com/a"]}
    reply = format_query_reply(result)
    assert "It's about X." in reply and "https://example.com/a" in reply


def test_format_query_reply_failure():
    result = {"success": False, "error": "Please enter a question."}
    assert "Please enter a question." in format_query_reply(result)


def test_debug_log_writes_to_stderr_not_stdout(capsys):
    from query import _debug_log
    _debug_log("[DEBUG] test message")
    captured = capsys.readouterr()
    assert "[DEBUG] test message" in captured.err
    assert "[DEBUG] test message" not in captured.out
