from __future__ import annotations

import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response
from fastapi.testclient import TestClient

import api.system as system_module


PNG_BYTES = b"\x89PNG\r\n\x1a\nimage"


class ImageHeadApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.patchers = [
            mock.patch.object(
                system_module,
                "get_image_response",
                lambda _path: Response(PNG_BYTES, media_type="image/png"),
            ),
            mock.patch.object(
                system_module,
                "get_thumbnail_response",
                lambda _path: Response(PNG_BYTES, media_type="image/png"),
            ),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

        app = FastAPI()
        app.include_router(system_module.create_router("1.1.1"))

        @app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
        async def serve_web(_full_path: str):
            return HTMLResponse("frontend fallback")

        self.client = TestClient(app)

    def test_image_head_uses_image_route_before_frontend_fallback(self) -> None:
        response = self.client.head("/images/2026/07/17/sample.png")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertEqual(response.headers["content-length"], str(len(PNG_BYTES)))
        self.assertEqual(response.content, b"")

    def test_thumbnail_head_uses_thumbnail_route_before_frontend_fallback(self) -> None:
        response = self.client.head("/image-thumbnails/2026/07/17/sample.png")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertEqual(response.headers["content-length"], str(len(PNG_BYTES)))
        self.assertEqual(response.content, b"")


if __name__ == "__main__":
    unittest.main()
