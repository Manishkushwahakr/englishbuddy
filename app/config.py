import os
from urllib.parse import urlsplit

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
SECRET_KEY = os.getenv("SECRET_KEY")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set")

if not SECRET_KEY:
    raise ValueError("SECRET_KEY is not set")

_DEFAULT_FRONTEND_ORIGINS = (
    "http://127.0.0.1:5500",
    "http://localhost:5500",
    "http://127.0.0.1:5501",
    "http://localhost:5501",
    "https://englishbuddy-for-me.vercel.app",
)
_configured_origins = os.getenv("FRONTEND_ORIGINS")

if _configured_origins is None:
    FRONTEND_ORIGINS = list(_DEFAULT_FRONTEND_ORIGINS)
else:
    FRONTEND_ORIGINS = list(
        dict.fromkeys(
            origin.strip().rstrip("/")
            for origin in _configured_origins.split(",")
            if origin.strip()
        )
    )
    if not FRONTEND_ORIGINS:
        raise ValueError("FRONTEND_ORIGINS must contain at least one origin")

    for origin in FRONTEND_ORIGINS:
        parsed_origin = urlsplit(origin)
        if (
            "*" in origin
            or parsed_origin.scheme not in {"http", "https"}
            or not parsed_origin.netloc
            or parsed_origin.path
            or parsed_origin.query
            or parsed_origin.fragment
        ):
            raise ValueError(
                "FRONTEND_ORIGINS must be a comma-separated list of exact "
                "http:// or https:// origins (without paths or wildcards)"
            )
