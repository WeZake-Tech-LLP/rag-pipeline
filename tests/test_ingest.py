from ingest import format_ingest_reply


def test_format_ingest_reply_success():
    result = {"success": True, "duplicate": False, "chunks_stored": 6, "extraction_quality": "full_text", "url_type": "article"}
    reply = format_ingest_reply(result)
    assert "6" in reply and "article" in reply


def test_format_ingest_reply_duplicate():
    # ingest_url() actually returns success=False for duplicates (see ingest.py:573-577)
    result = {"success": False, "duplicate": True, "message": "URL already exists in knowledge base"}
    reply = format_ingest_reply(result)
    assert "already exists" in reply.lower()
    assert "Failed" not in reply


def test_format_ingest_reply_failure():
    result = {"success": False, "duplicate": False, "message": "Could not extract content: boom"}
    assert "boom" in format_ingest_reply(result)
