
import sounddevice as sd
import numpy as np
from faster_whisper import WhisperModel
import tempfile
import wave

SAMPLE_RATE = 16000
DURATION = 30

print("Loading Whisper model...")

model = WhisperModel(
    "base",
    device="cpu",
    compute_type="int8"
)

print("Model ready!")
print("\nSpeak in English for 5 seconds.")
input("Press Enter to start recording...")

print("\nRecording started! Speak now...")

audio = sd.rec(
    int(DURATION * SAMPLE_RATE),
    samplerate=SAMPLE_RATE,
    channels=1,
    dtype="int16"
)

sd.wait()
print("Recording complete!")

with tempfile.NamedTemporaryFile(
    suffix=".wav",
    delete=False
) as temp_file:
    audio_path = temp_file.name

with wave.open(audio_path, "wb") as wav_file:
    wav_file.setnchannels(1)
    wav_file.setsampwidth(2)
    wav_file.setframerate(SAMPLE_RATE)
    wav_file.writeframes(audio.tobytes())

print("\nConverting speech to text...")

segments, info = model.transcribe(
    audio_path,
    language="en"
)

print("\nYour transcript:")

for segment in segments:
    print(segment.text, end=" ")

print("\n\nLive microphone STT test complete!")
