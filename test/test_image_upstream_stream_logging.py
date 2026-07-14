from __future__ import annotations

import unittest
from unittest import mock

from services.log_service import LoggedCall


class ImageUpstreamStreamLoggingTests(unittest.TestCase):
    def test_stream_logs_attempts_without_exposing_internal_fields(self) -> None:
        attempts = [{"channel_id": "primary", "channel_name": "Primary", "outcome": "success", "status": 200}]
        call = LoggedCall({"id": "key", "name": "Test", "role": "admin"}, "/v1/images/generations", "gpt-image-2", "文生图")
        item = {
            "created": 1,
            "data": [{"url": "http://app.test/images/1.png"}],
            "_image_upstream_attempts": attempts,
            "_image_upstream_selected": "Primary",
        }
        with mock.patch("services.log_service.log_service.add") as add:
            streamed = list(call.stream(iter([item])))

        self.assertNotIn("_image_upstream_attempts", streamed[0])
        self.assertNotIn("_image_upstream_selected", streamed[0])
        detail = add.call_args.args[2]
        self.assertEqual(detail["image_upstream_attempts"], attempts)
        self.assertEqual(detail["image_upstream_selected"], "Primary")


if __name__ == "__main__":
    unittest.main()
