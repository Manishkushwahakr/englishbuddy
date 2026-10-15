
import os
import tempfile

from faster_whisper import WhisperModel

_model = None


def get_model():
    global _model

    if _model is None:
        _model = WhisperModel(
            "small",
            device="cpu",
            compute_type="int8"
        )

    return _model


def transcribe_audio(audio_bytes: bytes) -> str:
    """Transcribe one temporary WebM audio chunk."""

    audio_path = None

    try:
        with tempfile.NamedTemporaryFile(
            suffix=".webm",
            delete=False
        ) as audio_file:
            audio_file.write(audio_bytes)
            audio_path = audio_file.name

        model = get_model()

        segments, _ = model.transcribe(
            audio_path,
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

    finally:
        if audio_path and os.path.exists(audio_path):
            os.remove(audio_path)
