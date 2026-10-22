from threading import Lock


MAX_TRANSCRIPT_CHUNKS = 720
MAX_TRANSCRIPT_CHARACTERS = 120_000

_lock = Lock()
_sessions: dict[str, dict] = {}


def claim_chunk(conversation_id: str, speaker_id: str, stream_id: str, sequence: int):
    key = (speaker_id, stream_id, sequence)
    with _lock:
        session = _sessions.setdefault(
            conversation_id,
            {"chunks": [], "keys": set(), "characters": 0}
        )
        if key in session["keys"]:
            return "duplicate"
        if (
            len(session["keys"]) >= MAX_TRANSCRIPT_CHUNKS
            or len(session["chunks"]) >= MAX_TRANSCRIPT_CHUNKS
        ):
            return "limit"
        session["keys"].add(key)
        return "claimed"


def release_chunk(conversation_id: str, speaker_id: str, stream_id: str, sequence: int):
    with _lock:
        session = _sessions.get(conversation_id)
        if session:
            session["keys"].discard((speaker_id, stream_id, sequence))


def store_transcript(
    conversation_id: str,
    speaker_id: str,
    stream_id: str,
    sequence: int,
    captured_at: str,
    received_at: str,
    processed_at: str,
    duration_ms: int,
    text: str,
):
    if not text:
        return True

    key = (speaker_id, stream_id, sequence)
    with _lock:
        session = _sessions.get(conversation_id)
        if not session or key not in session["keys"]:
            return False

        if session["characters"] + len(text) > MAX_TRANSCRIPT_CHARACTERS:
            session["keys"].discard(key)
            return False

        session["chunks"].append({
            "conversation_id": conversation_id,
            "speaker_id": speaker_id,
            "sequence": sequence,
            "stream_id": stream_id,
            "captured_at": captured_at,
            "received_at": received_at,
            "processed_at": processed_at,
            "duration_ms": duration_ms,
            "text": text,
        })
        session["characters"] += len(text)
        return True


def clear_conversation_transcript(conversation_id: str):
    with _lock:
        _sessions.pop(conversation_id, None)


def get_conversation_transcript(conversation_id: str):
    with _lock:
        session = _sessions.get(conversation_id)
        return list(session["chunks"]) if session else []
