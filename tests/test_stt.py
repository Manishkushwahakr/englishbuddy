
from faster_whisper import WhisperModel

print("Loading Whisper model...")

model = WhisperModel(
    "base",
    device="cpu",
    compute_type="int8"
)

print("Model ready!")

audio_file = input("Enter audio file path: ").strip().strip('"')

segments, info = model.transcribe(
    audio_file,
    language="en"
)

print("\nTranscription:")

for segment in segments:
    print(segment.text, end=" ")

print("\n\nSpeech-to-text test complete!")
