from __future__ import annotations

import base64
from datetime import timedelta
from io import BytesIO
import unittest

import requests
from PIL import Image

from services.image_upstream_service import CircuitState, ImageUpstreamService
from services.protocol.conversation import ImageGenerationError


def png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (2, 2), color=(255, 0, 0)).save(buffer, format="PNG")
    return buffer.getvalue()


PNG_BYTES = png_bytes()


class FakeStorage:
    def __init__(self) -> None:
        self.saved: list[bytes] = []

    def save(self, payload: bytes, base_url: str | None = None):
        self.saved.append(payload)
        return type("Stored", (), {"url": f"{base_url or 'http://app.test'}/images/{len(self.saved)}.png"})()


def response(status: int, payload: dict[str, object]) -> requests.Response:
    item = requests.Response()
    item.status_code = status
    item._content = __import__("json").dumps(payload).encode("utf-8")
    item.headers["content-type"] = "application/json"
    item.elapsed = timedelta(milliseconds=12)
    return item


def channel(channel_id: str, priority: int, model: str = "gpt-image-2") -> dict[str, object]:
    return {
        "id": channel_id,
        "name": channel_id,
        "enabled": True,
        "priority": priority,
        "base_url": f"https://{channel_id}.example.test/v1",
        "api_key": "test-key",
        "timeout_secs": 30,
        "supports_generation": True,
        "supports_edits": True,
        "failure_threshold": 2,
        "cooldown_secs": 60,
        "model_mappings": [{"client_model": model, "upstream_model": f"{channel_id}-model"}],
    }


class ImageUpstreamServiceTests(unittest.TestCase):
    def make_service(self, responses: list[requests.Response]) -> tuple[ImageUpstreamService, FakeStorage, list[dict[str, object]]]:
        calls: list[dict[str, object]] = []

        def requester(_method: str, _url: str, **kwargs):
            calls.append(kwargs)
            return responses.pop(0)

        storage = FakeStorage()
        settings = {"max_attempts": 2, "channels": [channel("first", 10), channel("second", 20)]}
        return ImageUpstreamService(lambda: settings, storage=storage, requester=requester), storage, calls

    def make_service_with_channels(self, channels: list[dict[str, object]], responses: list[requests.Response]):
        calls: list[dict[str, object]] = []

        def requester(_method: str, _url: str, **kwargs):
            calls.append(kwargs)
            return responses.pop(0)

        storage = FakeStorage()
        return ImageUpstreamService(lambda: {"max_attempts": 2, "channels": channels}, storage=storage, requester=requester), storage, calls

    def test_retries_next_channel_after_429_and_archives_b64_result(self) -> None:
        service, storage, calls = self.make_service([
            response(429, {"error": {"message": "rate limited"}}),
            response(200, {"created": 1, "data": [{"b64_json": base64.b64encode(PNG_BYTES).decode()}]}),
        ])

        result = service.try_handle("generation", {"model": "gpt-image-2", "prompt": "test", "base_url": "http://app.test"})

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["json"]["model"], "first-model")
        self.assertEqual(calls[1]["json"]["model"], "second-model")
        self.assertEqual(storage.saved, [PNG_BYTES])
        self.assertEqual(result["data"][0]["url"], "http://app.test/images/1.png")
        self.assertEqual(result["_image_upstream_selected"], "second")

    def test_terminal_400_does_not_try_second_channel(self) -> None:
        service, _storage, calls = self.make_service([response(400, {"error": {"message": "bad prompt"}})])

        with self.assertRaises(ImageGenerationError) as raised:
            service.try_handle("generation", {"model": "gpt-image-2", "prompt": "test"})

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(len(calls), 1)

    def test_edit_forwards_images_and_masks_as_multipart(self) -> None:
        service, _storage, calls = self.make_service([
            response(200, {"data": [{"b64_json": base64.b64encode(PNG_BYTES).decode()}]}),
        ])

        service.try_handle(
            "edit",
            {"model": "gpt-image-2", "prompt": "test"},
            images=[(PNG_BYTES, "input.png", "image/png")],
            masks=[(PNG_BYTES, "mask.png", "image/png")],
        )

        file_names = [item[0] for item in calls[0]["files"]]
        self.assertEqual(file_names, ["image", "mask"])
        self.assertEqual(calls[0]["data"]["model"], "first-model")

    def test_archive_failure_is_terminal_and_does_not_retry_generation(self) -> None:
        service, _storage, calls = self.make_service([
            response(200, {"data": [{"b64_json": "not-valid-base64"}]}),
        ])

        with self.assertRaises(ImageGenerationError):
            service.try_handle("generation", {"model": "gpt-image-2", "prompt": "test"})

        self.assertEqual(len(calls), 1)

    def test_url_archive_failure_preserves_pending_archive_context(self) -> None:
        storage = FakeStorage()
        service = ImageUpstreamService(
            lambda: {"max_attempts": 1, "channels": [channel("first", 10)]},
            storage=storage,
            requester=lambda *_args, **_kwargs: response(200, {"data": [{"url": "https://cdn.example.test/image.png"}]}),
            downloader=lambda _url: (_ for _ in ()).throw(RuntimeError("download timeout")),
        )

        with self.assertRaises(ImageGenerationError) as raised:
            service.try_handle("generation", {"model": "gpt-image-2", "prompt": "test"})

        self.assertEqual(raised.exception.code, "image_archive_failed")
        pending = getattr(raised.exception, "image_pending_archive")
        self.assertEqual(pending[0]["url"], "https://cdn.example.test/image.png")
        self.assertEqual(pending[0]["channel_name"], "first")

    def test_url_archive_failure_falls_back_to_next_channel(self) -> None:
        service, storage, calls = self.make_service([
            response(200, {"data": [{"url": "https://cdn.example.test/image.png"}]}),
            response(200, {"data": [{"b64_json": base64.b64encode(PNG_BYTES).decode()}]}),
        ])
        service._downloader = lambda _url: (_ for _ in ()).throw(RuntimeError("download timeout"))

        result = service.try_handle("generation", {"model": "gpt-image-2", "prompt": "test", "base_url": "http://app.test"})

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["json"]["model"], "first-model")
        self.assertEqual(calls[1]["json"]["model"], "second-model")
        self.assertEqual(storage.saved, [PNG_BYTES])
        self.assertEqual(result["_image_upstream_selected"], "second")

    def test_archive_pending_saves_without_calling_upstream(self) -> None:
        service, storage, _calls = self.make_service([])
        service._downloader = lambda _url: (PNG_BYTES, "image.png", "image/png")

        result = service.archive_pending([{"url": "https://cdn.example.test/image.png"}], base_url="http://app.test")

        self.assertEqual(result["data"][0]["url"], "http://app.test/images/1.png")
        self.assertEqual(storage.saved, [PNG_BYTES])

    def test_pinned_channel_model_only_calls_the_selected_channel(self) -> None:
        service, _storage, calls = self.make_service([
            response(200, {"data": [{"b64_json": base64.b64encode(PNG_BYTES).decode()}]}),
        ])
        pinned = service.model_entries()[1]["id"]

        result = service.try_handle("generation", {"model": pinned, "prompt": "test"})

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["json"]["model"], "second-model")
        self.assertEqual(result["_image_upstream_selected"], "second")

    def test_model_alias_is_a_short_pinned_channel_model(self) -> None:
        first = channel("first", 10)
        first["model_alias"] = "first-image"
        service, _storage, calls = self.make_service_with_channels(
            [first, channel("second", 20)],
            [response(200, {"data": [{"b64_json": base64.b64encode(PNG_BYTES).decode()}]})],
        )

        result = service.try_handle("generation", {"model": "first-image", "prompt": "test"})

        self.assertEqual(service.model_entries()[0]["id"], "first-image")
        self.assertEqual(calls[0]["json"]["model"], "first-model")
        self.assertEqual(result["_image_upstream_selected"], "first")

    def test_rate_limit_and_concurrency_are_skipped_without_calling_channel(self) -> None:
        first = channel("first", 10)
        first["requests_per_minute"] = 1
        first["max_concurrency"] = 1
        service, _storage, calls = self.make_service_with_channels(
            [first, channel("second", 20)],
            [response(200, {"data": [{"b64_json": base64.b64encode(PNG_BYTES).decode()}]})],
        )
        service._request_times["first"] = [__import__("time").time()]

        result = service.try_handle("generation", {"model": "gpt-image-2", "prompt": "test"})

        self.assertEqual(calls[0]["json"]["model"], "second-model")
        self.assertEqual(result["_image_upstream_attempts"][0]["outcome"], "skipped_rate_limit")

    def test_runtime_state_restores_circuit_and_test_result(self) -> None:
        state: dict[str, object] = {}
        channels = [channel("first", 10)]
        service, _storage, _calls = self.make_service_with_channels(channels, [])
        service._runtime_state_saver = lambda value: state.update(value)
        service._record_failure(channels[0], "timeout")
        service._record_test(channels[0], {"ok": False, "status": 0, "latency_ms": 1, "error": "timeout", "models": []})

        restored = ImageUpstreamService(lambda: {"max_attempts": 2, "channels": channels}, storage=FakeStorage(), runtime_state_provider=lambda: state)

        self.assertEqual(restored.statuses()["channels"]["first"]["failure_count"], 1)
        self.assertEqual(restored.statuses()["channels"]["first"]["last_test"]["error"], "timeout")

    def test_model_entries_include_channel_name_without_exposing_api_key(self) -> None:
        service, _storage, _calls = self.make_service([])

        entries = service.model_entries()

        self.assertEqual(entries[0]["display_name"], "first · gpt-image-2")
        self.assertEqual(entries[0]["image_upstream"]["channel_name"], "first")
        self.assertNotIn("api_key", entries[0])

    def test_circuit_open_channel_does_not_consume_request_attempt(self) -> None:
        third = channel("third", 30)
        service, _storage, calls = self.make_service_with_channels(
            [channel("first", 10), channel("second", 20), third],
            [
                response(429, {"error": {"message": "rate limited"}}),
                response(200, {"data": [{"b64_json": base64.b64encode(PNG_BYTES).decode()}]}),
            ],
        )
        service._circuits["first"] = CircuitState(opened_until=9999999999)

        result = service.try_handle("generation", {"model": "gpt-image-2", "prompt": "test"})

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["json"]["model"], "second-model")
        self.assertEqual(calls[1]["json"]["model"], "third-model")
        self.assertEqual(result["_image_upstream_selected"], "third")
        self.assertEqual(result["_image_upstream_attempts"][0]["outcome"], "skipped_circuit")

    def test_rejects_base64_that_is_not_an_image(self) -> None:
        service, _storage, calls = self.make_service([
            response(200, {"data": [{"b64_json": base64.b64encode(b"not an image").decode()}]}),
        ])

        with self.assertRaises(ImageGenerationError) as raised:
            service.try_handle("generation", {"model": "gpt-image-2", "prompt": "test"})

        self.assertEqual(raised.exception.code, "invalid_upstream_response")
        self.assertEqual(len(calls), 1)

    def test_default_channel_wins_when_priorities_are_equal(self) -> None:
        first = channel("first", 10)
        second = channel("second", 10)
        second["default"] = True
        service, _storage, calls = self.make_service_with_channels(
            [first, second],
            [response(200, {"data": [{"b64_json": base64.b64encode(PNG_BYTES).decode()}]})],
        )

        result = service.try_handle("generation", {"model": "gpt-image-2", "prompt": "test"})

        self.assertEqual(calls[0]["json"]["model"], "second-model")
        self.assertEqual(result["_image_upstream_selected"], "second")

    def test_statuses_expose_circuit_and_last_test_without_config_secrets(self) -> None:
        service, _storage, _calls = self.make_service([])
        service._circuits["first"] = CircuitState(failures=2, opened_until=9999999999, last_error="timeout")
        service._record_test(channel("first", 10), {"ok": False, "status": 0, "latency_ms": 12, "error": "timeout", "models": []})

        status = service.statuses()["channels"]["first"]

        self.assertTrue(status["circuit_open"])
        self.assertEqual(status["failure_count"], 2)
        self.assertEqual(status["last_test"]["error"], "timeout")
        self.assertNotIn("api_key", str(status))


if __name__ == "__main__":
    unittest.main()
