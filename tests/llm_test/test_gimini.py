
import os
from dotenv import load_dotenv
from google import genai

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise RuntimeError(
        "GEMINI_API_KEY missing. Check your .env file."
    )

client = genai.Client(api_key=api_key)

try:
    response = client.models.generate_content(
        model="gemini-3.8-flash",
        contents="Reply with exactly: ImproBuddy Gemini connection successful"
    )

    print("Gemini response:")
    print(response.text)

except Exception as e:
    print(f"Gemini connection failed: {type(e).__name__}: {e}")
