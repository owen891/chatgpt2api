from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from services.image_task_service import ImageTaskService
from services.openai_backend_api import ImagePollTimeoutError


OWNER = {"id": "owner-1", "name": "Owner", "role": "admin"}
OTHER_OWNER = {"id": "owner-2", "name": "Other", "role": "user"}


def wait_for_task(service: ImageTaskService, identity: dict[str, object], task_id: str, status: str, timeout: float = 2.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        result = service.list_tasks(identity, [task_id])
        last = (result.get("items") or [None])[0]
        if last and last.get("status") == status:
            return last
        time.sleep(0.02)
    raise AssertionError(f"task {task_id} did not reach {status}, last={last}")


class ImageTaskServiceTests(unittest.TestCase):
    def make_service(self, path: Path, handler=None) -> ImageTaskService:
        return ImageTaskService(
            path,
            generation_handler=handler or (lambda _payload: {"data": [{"url": "http://example.test/image.png"}]}),
            edit_handler=handler or (lambda _payload: {"data": [{"url": "http://example.test/edit.png"}]}),
            retention_days_getter=lambda: 30,
        )

    def test_duplicate_submit_uses_existing_task(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            calls = 0

            def handler(_payload):
                nonlocal calls
                calls += 1
                time.sleep(0.05)
                return {"data": [{"url": "http://example.test/image.png"}]}

            service = self.make_service(Path(tmp_dir) / "image_tasks.json", handler)
            first = service.submit_generation(
                OWNER,
                client_task_id="task-1",
                prompt="cat",
                model="gpt-image-2",
                size=None,
                base_url="http://local.test",
            )
            second = service.submit_generation(
                OWNER,
                client_task_id="task-1",
                prompt="cat",
                model="gpt-image-2",
                size=None,
                base_url="http://local.test",
            )

            self.assertEqual(first["id"], "task-1")
            self.assertEqual(second["id"], "task-1")
            task = wait_for_task(service, OWNER, "task-1", "success")
            self.assertEqual(task["data"][0]["url"], "http://example.test/image.png")
            self.assertEqual(calls, 1)

    def test_different_owner_cannot_query_task(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = self.make_service(Path(tmp_dir) / "image_tasks.json")
            service.submit_generation(
                OWNER,
                client_task_id="private-task",
                prompt="cat",
                model="gpt-image-2",
                size=None,
                base_url="http://local.test",
            )

            wait_for_task(service, OWNER, "private-task", "success")
            result = service.list_tasks(OTHER_OWNER, ["private-task"])

            self.assertEqual(result["items"], [])
            self.assertEqual(result["missing_ids"], ["private-task"])

    def test_success_task_persists_to_new_service_instance(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "image_tasks.json"
            service = self.make_service(path)
            service.submit_generation(
                OWNER,
                client_task_id="persisted-task",
                prompt="cat",
                model="gpt-image-2",
                size=None,
                base_url="http://local.test",
            )
            wait_for_task(service, OWNER, "persisted-task", "success")

            reloaded = self.make_service(path)
            result = reloaded.list_tasks(OWNER, ["persisted-task"])

            self.assertEqual(result["missing_ids"], [])
            self.assertEqual(result["items"][0]["status"], "success")
            self.assertEqual(result["items"][0]["data"][0]["url"], "http://example.test/image.png")

    def test_poll_timeout_can_resume_with_original_account(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            timeout = ImagePollTimeoutError("ChatGPT 生图超时（已等待 120 秒）。")
            timeout.conversation_id = "conv-pending"
            timeout.access_token = "token-original"

            def handler(_payload):
                raise timeout

            service = self.make_service(Path(tmp_dir) / "image_tasks.json", handler)
            service.submit_generation(
                OWNER,
                client_task_id="timeout-task",
                prompt="cat",
                model="gpt-image-2",
                size=None,
                base_url="http://local.test",
            )
            failed = wait_for_task(service, OWNER, "timeout-task", "error")
            self.assertEqual(failed["conversation_id"], "conv-pending")
            self.assertNotIn("_resume_access_token", failed)

            backend = mock.Mock()
            backend._poll_image_results.return_value = (["file-one"], [])
            backend.resolve_conversation_image_urls.return_value = ["https://example.test/image.png"]
            backend.download_image_bytes.return_value = [b"image-bytes"]
            with mock.patch("services.openai_backend_api.OpenAIBackendAPI", return_value=backend) as backend_class:
                service.resume_poll(OWNER, "timeout-task", 30)
                resumed = wait_for_task(service, OWNER, "timeout-task", "success")

            backend_class.assert_called_once_with(access_token="token-original")
            backend._poll_image_results.assert_called_once_with("conv-pending", 30)
            self.assertTrue(resumed["data"][0]["b64_json"])

    def test_success_task_can_expose_upstream_url_when_archive_is_pending(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "image_tasks.json"

            def handler(_payload):
                return {
                    "data": [{"url": "https://cdn.example.test/generated.png"}],
                    "_image_pending_archive": [{"url": "https://cdn.example.test/generated.png", "channel_name": "backup"}],
                }

            service = self.make_service(path, handler)
            service.submit_generation(
                OWNER,
                client_task_id="upstream-url-task",
                prompt="cat",
                model="gpt-image-2",
                size=None,
                base_url="http://local.test",
            )
            result = wait_for_task(service, OWNER, "upstream-url-task", "success")

            self.assertEqual(result["data"][0]["url"], "https://cdn.example.test/generated.png")
            self.assertTrue(result["pending_archive"]["available"])
            self.assertEqual(result["pending_archive"]["channel_name"], "backup")

    def test_startup_marks_unfinished_tasks_as_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "image_tasks.json"
            path.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "id": "queued-task",
                                "owner_id": "owner-1",
                                "status": "queued",
                                "mode": "generate",
                                "model": "gpt-image-2",
                                "created_at": "2099-01-01 00:00:00",
                                "updated_at": "2099-01-01 00:00:00",
                            },
                            {
                                "id": "running-task",
                                "owner_id": "owner-1",
                                "status": "running",
                                "mode": "generate",
                                "model": "gpt-image-2",
                                "created_at": "2099-01-01 00:00:00",
                                "updated_at": "2099-01-01 00:00:00",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            service = self.make_service(path)
            result = service.list_tasks(OWNER, ["queued-task", "running-task"])

            self.assertEqual([item["status"] for item in result["items"]], ["error", "error"])
            self.assertTrue(all("已中断" in item.get("error", "") for item in result["items"]))

    def test_cancel_running_task_cannot_be_overwritten_by_late_success(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            started = threading.Event()
            release = threading.Event()

            def handler(_payload):
                started.set()
                release.wait(2)
                return {"data": [{"url": "http://example.test/late.png"}]}

            service = self.make_service(Path(tmp_dir) / "image_tasks.json", handler)
            service.submit_generation(
                OWNER,
                client_task_id="cancel-running",
                prompt="cat",
                model="gpt-image-2",
                size=None,
                base_url="http://local.test",
            )
            self.assertTrue(started.wait(1))

            result = service.cancel_tasks(OWNER, ["cancel-running"])
            self.assertEqual(result["items"][0]["status"], "cancelled")
            self.assertIn("已停止", result["items"][0]["error"])

            release.set()
            time.sleep(0.1)
            persisted = service.list_tasks(OWNER, ["cancel-running"])["items"][0]
            self.assertEqual(persisted["status"], "cancelled")
            self.assertEqual(persisted.get("data"), [])

    def test_cancel_is_owner_scoped_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            started = threading.Event()
            release = threading.Event()

            def handler(_payload):
                started.set()
                release.wait(2)
                return {"data": [{"url": "http://example.test/image.png"}]}

            service = self.make_service(Path(tmp_dir) / "image_tasks.json", handler)
            service.submit_generation(
                OWNER,
                client_task_id="private-running",
                prompt="cat",
                model="gpt-image-2",
                size=None,
                base_url="http://local.test",
            )
            self.assertTrue(started.wait(1))

            other_result = service.cancel_tasks(OTHER_OWNER, ["private-running"])
            self.assertEqual(other_result["items"], [])
            self.assertEqual(other_result["missing_ids"], ["private-running"])

            first = service.cancel_tasks(OWNER, ["private-running"])
            second = service.cancel_tasks(OWNER, ["private-running"])
            self.assertEqual(first["items"][0]["status"], "cancelled")
            self.assertEqual(second["items"][0]["status"], "cancelled")
            release.set()

    def test_cancelled_task_persists_across_restart(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "image_tasks.json"
            started = threading.Event()
            release = threading.Event()

            def handler(_payload):
                started.set()
                release.wait(2)
                return {"data": [{"url": "http://example.test/image.png"}]}

            service = self.make_service(path, handler)
            service.submit_generation(
                OWNER,
                client_task_id="persisted-cancelled",
                prompt="cat",
                model="gpt-image-2",
                size=None,
                base_url="http://local.test",
            )
            self.assertTrue(started.wait(1))
            service.cancel_tasks(OWNER, ["persisted-cancelled"])

            reloaded = self.make_service(path)
            task = reloaded.list_tasks(OWNER, ["persisted-cancelled"])["items"][0]
            self.assertEqual(task["status"], "cancelled")
            release.set()

    def test_retry_archive_persists_and_does_not_call_generation_handler(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "image_tasks.json"
            generation_calls = 0

            def handler(_payload):
                nonlocal generation_calls
                generation_calls += 1
                return {"data": [{"url": "http://example.test/generated.png"}]}

            service = self.make_service(path, handler)
            service._tasks["owner-1:archive-task"] = {
                "id": "archive-task",
                "owner_id": "owner-1",
                "status": "error",
                "mode": "generate",
                "model": "gpt-image-2",
                "size": "",
                "quality": "auto",
                "base_url": "https://public.example.test",
                "created_at": "2026-01-01 00:00:00",
                "updated_at": "2026-01-01 00:00:00",
                "pending_archive": [{"url": "https://cdn.example.test/image.png", "operation": "generation", "model": "gpt-image-2"}],
                "error": "图片归档下载失败",
            }
            service._save_locked()

            with mock.patch.object(
                __import__("services.image_task_service", fromlist=["image_upstream_service"]).image_upstream_service,
                "archive_pending",
                return_value={"data": [{"url": "http://app.test/images/recovered.png"}]},
            ) as archive:
                service.retry_archive(OWNER, "archive-task")
                task = wait_for_task(service, OWNER, "archive-task", "success")

            self.assertEqual(generation_calls, 0)
            archive.assert_called_once()
            self.assertEqual(archive.call_args.kwargs["base_url"], "https://public.example.test")
            self.assertEqual(task["data"][0]["url"], "http://app.test/images/recovered.png")
            self.assertNotIn("pending_archive", task)

            reloaded = self.make_service(path, handler)
            self.assertEqual(reloaded.list_tasks(OWNER, ["archive-task"])["items"][0]["status"], "success")


if __name__ == "__main__":
    unittest.main()
