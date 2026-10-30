import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import FRONTEND_ORIGINS, parse_frontend_origins
from app.cors import configure_cors


class FrontendOriginsTests(unittest.TestCase):
    def test_production_and_local_origins_are_always_allowed(self):
        origins = parse_frontend_origins(None)
        self.assertIn("https://improbuddy.in", origins)
        self.assertIn("https://www.improbuddy.in", origins)
        self.assertIn("https://englishbuddy-for-me.vercel.app", origins)
        self.assertIn("http://localhost:5500", origins)
        self.assertIn("http://127.0.0.1:5501", origins)

    def test_configured_origins_are_normalized_and_added_to_defaults(self):
        origins = parse_frontend_origins(
            " https://preview.example.com/ , http://localhost:3000/ "
        )
        self.assertIn("https://preview.example.com", origins)
        self.assertIn("http://localhost:3000", origins)
        self.assertIn("https://improbuddy.in", origins)

    def test_wildcards_and_non_origin_urls_are_rejected(self):
        for value in ("*", "https://example.com/path", "ftp://example.com"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_frontend_origins(value)

    def test_cors_preflight_allows_production_and_local_origins(self):
        app = FastAPI()
        configure_cors(app)
        client = TestClient(app)
        origins = (
            "https://improbuddy.in",
            "https://www.improbuddy.in",
            "http://localhost:5500",
        )

        for origin in origins:
            with self.subTest(origin=origin):
                response = client.options(
                    "/llm/analyze-transcript",
                    headers={
                        "Origin": origin,
                        "Access-Control-Request-Method": "POST",
                        "Access-Control-Request-Headers": (
                            "authorization,content-type"
                        ),
                    },
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.headers["access-control-allow-origin"],
                    origin,
                )
                self.assertEqual(
                    response.headers["access-control-allow-credentials"],
                    "true",
                )
                allowed_headers = response.headers[
                    "access-control-allow-headers"
                ].lower()
                self.assertIn("authorization", allowed_headers)
                self.assertIn("content-type", allowed_headers)
        self.assertEqual(FRONTEND_ORIGINS, parse_frontend_origins(None))


if __name__ == "__main__":
    unittest.main()
