from ingest import format_ingest_reply


def test_format_ingest_reply_success():
    result = {"success": True, "duplicate": False, "chunks_stored": 6, "extraction_quality": "full_text", "url_type": "article"}
    reply = format_ingest_reply(result)
    assert "6" in reply and "article" in reply


def test_format_ingest_reply_duplicate():
    result = {"success": True, "duplicate": True}
    assert "already exists" in format_ingest_reply(result).lower()


def test_format_ingest_reply_failure():
    result = {"success": False, "duplicate": False, "message": "Could not extract content: boom"}
    assert "boom" in format_ingest_reply(result)
