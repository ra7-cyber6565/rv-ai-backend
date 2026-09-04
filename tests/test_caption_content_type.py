from research_engine.network_safety import UnexpectedContentType, require_content_type


class _Response:
    def __init__(self, content_type: str):
        self.headers = {"Content-Type": content_type}


def test_discovery_guard_accepts_public_caption_text_mimes():
    for mime in ("text/vtt", "text/srt", "application/srt", "application/x-subrip"):
        require_content_type(_Response(mime), "discovery")


def test_discovery_guard_still_rejects_media_binary_mime():
    try:
        require_content_type(_Response("audio/mpeg"), "discovery")
    except UnexpectedContentType:
        pass
    else:
        raise AssertionError("audio media MIME must remain blocked by discovery helper")
