
import sounddevice as sd
import numpy as np
from faster_whisper import WhisperModel
import queue
import time

SAMPLE_RATE = 16000
CHUNK_DURATION = 8

audio_queue = queue.Queue()

def audio_callback(indata, frames, time_info, status):
    if status:
        print("Audio status:", status)
    audio_queue.put(indata.copy())

print("Loading Whisper model...")

model = WhisperModel(
    "base",
    device="cpu",
    compute_type="int8"
)

print("Model ready!")
print("Speak English. Press Ctrl+C to stop.\n")

try:
    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
        blocksize=int(SAMPLE_RATE * CHUNK_DURATION),
        callback=audio_callback
    ):
        while True:
            audio_chunk = audio_queue.get()

            segments, info = model.transcribe(
                audio_chunk.flatten(),
                language= "en",
                vad_filter=True,
                condition_on_previous_text=False,
                beam_size=5,
                no_speech_threshold=0.6
            )

            text = " ".join(
                segment.text.strip() for segment in segments
            ).strip()

            if text:
                print("Transcript:", text)

except KeyboardInterrupt:
    print("\nContinuous transcription stopped.")
