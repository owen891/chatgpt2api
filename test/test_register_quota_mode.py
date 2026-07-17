from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from services.register_service import RegisterService


class RegisterServiceSourceCompatTests(unittest.TestCase):
    @staticmethod
    def _metrics(quota: int = 0, available: int | None = None) -> dict:
        resolved_available = quota // 25 if available is None else available
        return {
            "current_quota": quota,
            "current_available": resolved_available,
            "estimated_quota": quota,
            "estimated_available": resolved_available,
            "pool_refreshed": 0,
            "pool_refresh_errors": [],
        }

    @staticmethod
    def _wait_for(predicate, timeout: float = 3.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.01)
        raise AssertionError("waiting for register service timed out")

    def test_get_redacts_outlook_pool_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RegisterService(Path(tmp_dir) / "register.json")
            service._config["mail"]["providers"] = [
                {
                    "id": "outlook-a",
                    "type": "outlook_token",
                    "label": "Outlook Pool",
                    "mailboxes": "demo@example.com----password----client-id----refresh-token",
                }
            ]

            snapshot = service.get()
            provider = snapshot["mail"]["providers"][0]

            self.assertEqual(provider["mailboxes"], "")
            self.assertEqual(provider["mailboxes_count"], 1)
            self.assertEqual(provider["mailboxes_base_count"], 1)
            self.assertEqual(provider["mailboxes_alias_count"], 0)
            self.assertEqual(provider["mailboxes_preview"], ["de***o@example.com"])

    def test_update_merges_outlook_pool_without_duplicate_addresses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RegisterService(Path(tmp_dir) / "register.json")
            service._config["mail"]["providers"] = [
                {
                    "id": "outlook-a",
                    "type": "outlook_token",
                    "label": "Outlook Pool",
                    "mailboxes": "first@example.com----old-pass----client-a----refresh-old",
                }
            ]

            updated = service.update(
                {
                    "mail": {
                        **service._config["mail"],
                        "providers": [
                            {
                                "id": "outlook-a",
                                "type": "outlook_token",
                                "label": "Outlook Pool",
                                "mailboxes": "\n".join(
                                    [
                                        "first@example.com----new-pass----client-a----refresh-new",
                                        "second@example.com----pass-b----client-b----refresh-b",
                                    ]
                                ),
                            }
                        ],
                    }
                }
            )

            persisted = service._config["mail"]["providers"][0]["mailboxes"].splitlines()

            self.assertEqual(len(persisted), 2)
            self.assertIn("first@example.com----new-pass----client-a----refresh-new", persisted)
            self.assertIn("second@example.com----pass-b----client-b----refresh-b", persisted)
            self.assertEqual(updated["mail"]["providers"][0]["mailboxes"], "")
            self.assertEqual(updated["mail"]["providers"][0]["mailboxes_count"], 2)

    def test_total_mode_submits_only_requested_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RegisterService(Path(tmp_dir) / "register.json")
            service._pool_metrics = lambda **_kwargs: self._metrics()
            service._config.update({
                "enabled": True,
                "mode": "total",
                "total": 1,
                "threads": 3,
            })
            service._runner = threading.current_thread()

            with patch("services.register_service.openai_register.worker", return_value={"ok": True}) as worker:
                service._run()

            self.assertEqual(worker.call_count, 1)
            self.assertFalse(service._config["enabled"])
            self.assertEqual(service._config["stats"]["success"], 1)
            self.assertEqual(service._config["stats"]["done"], 1)

    def test_rate_limit_pauses_before_submitting_next_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RegisterService(Path(tmp_dir) / "register.json")
            service._pool_metrics = lambda **_kwargs: self._metrics()
            service._config.update({
                "enabled": True,
                "mode": "total",
                "total": 2,
                "threads": 1,
                "rate_limit_cooldown_seconds": 1,
            })
            call_times: list[float] = []

            def worker(_index: int) -> dict:
                call_times.append(time.monotonic())
                if len(call_times) == 1:
                    return {"ok": False, "failure_kind": "rate_limit", "status_code": 429}
                return {"ok": True}

            with patch("services.register_service.openai_register.worker", side_effect=worker):
                service._run()

            self.assertEqual(len(call_times), 2)
            self.assertGreaterEqual(call_times[1] - call_times[0], 0.9)
            self.assertEqual(service._config["stats"]["success"], 1)
            self.assertEqual(service._config["stats"]["fail"], 1)
            self.assertTrue(any("限流" in item["text"] for item in service._logs))

    def test_first_worker_probes_egress_before_full_concurrency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RegisterService(Path(tmp_dir) / "register.json")
            service._pool_metrics = lambda **_kwargs: self._metrics()
            service._config.update({
                "enabled": True,
                "mode": "total",
                "total": 3,
                "threads": 3,
            })
            first_started = threading.Event()
            release_first = threading.Event()
            call_count = 0
            call_lock = threading.Lock()

            def worker(_index: int) -> dict:
                nonlocal call_count
                with call_lock:
                    call_count += 1
                    current_call = call_count
                if current_call == 1:
                    first_started.set()
                    release_first.wait(timeout=2)
                return {"ok": True}

            with patch("services.register_service.openai_register.worker", side_effect=worker):
                runner = threading.Thread(target=service._run, daemon=True)
                runner.start()
                self.assertTrue(first_started.wait(timeout=1))
                time.sleep(0.1)
                self.assertEqual(call_count, 1)
                release_first.set()
                runner.join(timeout=2)

            self.assertFalse(runner.is_alive())
            self.assertEqual(call_count, 3)
            self.assertEqual(service._config["stats"]["success"], 3)

    def test_rate_limit_recovery_uses_one_worker_until_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RegisterService(Path(tmp_dir) / "register.json")
            service._pool_metrics = lambda **_kwargs: self._metrics()
            service._config.update({
                "enabled": True,
                "mode": "total",
                "total": 4,
                "threads": 3,
                "rate_limit_cooldown_seconds": 1,
            })
            recovery_started = threading.Event()
            release_recovery = threading.Event()
            call_count = 0
            call_lock = threading.Lock()

            def worker(_index: int) -> dict:
                nonlocal call_count
                with call_lock:
                    call_count += 1
                    current_call = call_count
                if current_call == 1:
                    return {"ok": False, "failure_kind": "rate_limit", "status_code": 429}
                if current_call == 2:
                    recovery_started.set()
                    release_recovery.wait(timeout=2)
                return {"ok": True}

            with patch("services.register_service.openai_register.worker", side_effect=worker):
                runner = threading.Thread(target=service._run, daemon=True)
                runner.start()
                self.assertTrue(recovery_started.wait(timeout=2))
                time.sleep(0.1)
                self.assertEqual(call_count, 2)
                release_recovery.set()
                runner.join(timeout=2)

            self.assertFalse(runner.is_alive())
            self.assertEqual(call_count, 4)
            self.assertEqual(service._config["stats"]["success"], 3)
            self.assertEqual(service._config["stats"]["fail"], 1)

    def test_manual_stop_replaces_stale_rate_limit_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RegisterService(Path(tmp_dir) / "register.json")
            service._pool_metrics = lambda **_kwargs: self._metrics()
            service._config.update({
                "enabled": True,
                "mode": "quota",
                "target_quota": 100,
                "threads": 1,
                "rate_limit_cooldown_seconds": 60,
            })

            with patch(
                "services.register_service.openai_register.worker",
                return_value={"ok": False, "failure_kind": "rate_limit", "status_code": 429},
            ):
                runner = threading.Thread(target=service._run, daemon=True)
                service._runner = runner
                runner.start()
                self._wait_for(lambda: service._config["stats"].get("phase") == "cooldown")
                service.stop()
                runner.join(timeout=2)

            self.assertFalse(runner.is_alive())
            self.assertEqual(service._config["stats"]["phase"], "stopped")
            self.assertEqual(service._config["stats"]["stop_reason"], "用户手动停止")

    def test_quota_mode_stops_submitting_once_target_is_reached(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RegisterService(Path(tmp_dir) / "register.json")
            metrics = self._metrics()
            service._pool_metrics = lambda **_kwargs: dict(metrics)
            service._config.update({
                "enabled": True,
                "mode": "quota",
                "target_quota": 50,
                "threads": 1,
                "check_interval": 1,
            })
            calls = 0

            def worker(_index: int) -> dict:
                nonlocal calls
                calls += 1
                metrics.update(self._metrics(metrics["current_quota"] + 25))
                return {"ok": True}

            with patch("services.register_service.openai_register.worker", side_effect=worker):
                runner = threading.Thread(target=service._run, daemon=True)
                service._runner = runner
                runner.start()
                self._wait_for(lambda: calls == 2)
                time.sleep(0.2)
                self.assertEqual(calls, 2)
                self.assertTrue(service._config["enabled"])
                self.assertGreaterEqual(service._config["stats"]["current_quota"], 50)
                service.stop()
                runner.join(timeout=2)

            self.assertFalse(runner.is_alive())

    def test_reset_restores_clean_runtime_stats(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RegisterService(Path(tmp_dir) / "register.json")
            service._pool_metrics = lambda **_kwargs: self._metrics(25, 1)
            service._logs.append({"time": "2026-07-16T00:00:00+00:00", "text": "demo", "level": "info"})
            service._config["stats"].update({
                "success": 2,
                "fail": 1,
                "done": 3,
                "running": 1,
            })

            snapshot = service.reset()

            self.assertEqual(service._logs, [])
            self.assertEqual(snapshot["stats"]["success"], 0)
            self.assertEqual(snapshot["stats"]["fail"], 0)
            self.assertEqual(snapshot["stats"]["done"], 0)
            self.assertEqual(snapshot["stats"]["running"], 0)
            self.assertEqual(snapshot["stats"]["current_quota"], 25)
            self.assertEqual(snapshot["stats"]["current_available"], 1)


if __name__ == "__main__":
    unittest.main()
