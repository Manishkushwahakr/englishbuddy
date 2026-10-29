
import io
import threading

_model = None
_model_lock = threading.Lock()


def get_model():
    global _model

    if _model is None:
        with _model_lock:
            if _model is None:
                from faster_whisper import WhisperModel

                _model = WhisperModel(
                    "small",
                    device="cpu",
                    compute_type="int8"
                )

    return _model


def transcribe_audio(audio_bytes: bytes | bytearray) -> str:
    """Transcribe one in-memory WAV chunk without writing audio to disk."""
    if not audio_bytes:
        raise ValueError("Audio chunk is empty")

    model = get_model()
    segments, _ = model.transcribe(
        io.BytesIO(audio_bytes),
        task="transcribe",
        language="en",
        vad_filter=True,
        condition_on_previous_text=False,
        beam_size=5
    )

    return " ".join(
        segment.text.strip()
        for segment in segments
        if segment.text.strip()
    ).strip()
