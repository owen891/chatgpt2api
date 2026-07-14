from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from api.register import _consume_event_ticket, _issue_event_ticket
from services.register_service import RegisterService, _redact_register_log


class RegisterQuotaModeTests(unittest.TestCase):
    @staticmethod
    def _wait_for(predicate, timeout: float = 3.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.01)
        raise AssertionError("等待注册任务状态超时")

    @staticmethod
    def _metrics(quota: int = 0) -> dict:
        return {
            "current_quota": quota,
            "current_available": quota // 25,
            "estimated_quota": quota,
            "estimated_available": quota // 25,
            "unconfirmed_available": 0,
            "unknown_quota_count": 0,
            "pool_freshness_seconds": 300,
            "pool_refreshed": 0,
            "pool_refresh_errors": [],
        }

    def test_quota_mode_detects_when_confirmed_quota_reaches_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RegisterService(Path(tmp_dir) / "register.json")
            metrics = {
                "current_quota": 99,
                "current_available": 4,
                "estimated_quota": 99,
                "estimated_available": 4,
                "unconfirmed_available": 0,
                "unknown_quota_count": 0,
                "pool_freshness_seconds": 300,
                "pool_refreshed": 0,
                "pool_refresh_errors": [],
            }
            service._pool_metrics = lambda **_kwargs: dict(metrics)
            config = {"mode": "quota", "target_quota": 100}

            self.assertFalse(service._target_reached(config, submitted=4))

            metrics["current_quota"] = 100
            self.assertTrue(service._target_reached(config, submitted=4))

    def test_pool_check_log_only_changes_with_monitor_signature(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RegisterService(Path(tmp_dir) / "register.json")
            metrics = self._metrics(100)
            service._pool_metrics = lambda **_kwargs: dict(metrics)
            config = {"mode": "quota", "target_quota": 100}

            self.assertTrue(service._target_reached(config, submitted=0))
            self.assertTrue(service._target_reached(config, submitted=0))
            self.assertEqual(len(service._logs), 1)

            metrics.update(self._metrics(75))
            self.assertFalse(service._target_reached(config, submitted=0))
            self.assertEqual(len(service._logs), 2)

    def test_refill_waits_until_trigger_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RegisterService(Path(tmp_dir) / "register.json")
            service._config.update({"mode": "quota", "target_quota": 100, "trigger_quota": 50})
            metrics = self._metrics(75)
            service._pool_metrics = lambda **_kwargs: dict(metrics)
            self.assertFalse(service._refill_required(service.get()))

            metrics.update(self._metrics(49))
            self.assertTrue(service._refill_required(service.get()))

    def test_concurrency_limit_uses_remaining_quota_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RegisterService(Path(tmp_dir) / "register.json")
            service._config.update({"mode": "quota", "target_quota": 100, "expected_quota_per_account": 25})
            service._config["stats"]["current_quota"] = 75
            self.assertEqual(service._concurrency_limit(service._config, 6), 1)
            service._config["stats"]["current_quota"] = 0
            self.assertEqual(service._concurrency_limit(service._config, 6), 4)

    def test_quota_monitor_refills_again_after_quota_drops(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RegisterService(Path(tmp_dir) / "register.json")
            metrics = self._metrics()
            service._pool_metrics = lambda **_kwargs: dict(metrics)
            service._config.update({
                "enabled": True,
                "mode": "quota",
                "target_quota": 50,
                "threads": 1,
                "max_attempts": 10,
                "max_consecutive_failures": 5,
                "max_runtime_minutes": 5,
                "retry_cooldown_seconds": 30,
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
                self._wait_for(lambda: calls == 2 and service._config["stats"].get("phase") == "monitoring")

                self.assertTrue(service._config["enabled"])
                self.assertTrue(runner.is_alive())
                metrics.update(self._metrics(0))
                service._wake_event.set()
                self._wait_for(lambda: calls == 4 and service._config["stats"].get("phase") == "monitoring")

                service.stop()
                runner.join(timeout=2)

            self.assertEqual(calls, 4)
            self.assertFalse(runner.is_alive())
            self.assertFalse(service._config["enabled"])
            self.assertEqual(service._config["stats"]["phase"], "stopped")
            self.assertGreaterEqual(len(service._config["history"]), 1)
            self.assertEqual(service._config["history"][-1]["status"], "completed")

    def test_registration_stops_after_consecutive_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RegisterService(Path(tmp_dir) / "register.json")
            service._pool_metrics = lambda **_kwargs: self._metrics()
            service._config.update({
                "enabled": True,
                "mode": "quota",
                "target_quota": 100,
                "threads": 1,
                "max_attempts": 100,
                "max_consecutive_failures": 2,
                "max_runtime_minutes": 5,
                "retry_cooldown_seconds": 30,
            })

            with patch("services.register_service.openai_register.worker", return_value={"ok": False}) as worker:
                runner = threading.Thread(target=service._run, daemon=True)
                service._runner = runner
                runner.start()
                self._wait_for(lambda: service._config["stats"].get("phase") == "cooldown")

                self.assertTrue(service._config["enabled"])
                self.assertEqual(worker.call_count, 2)
                self.assertIn("连续失败 2 次", service._config["stats"]["stop_reason"])
                service.stop()
                runner.join(timeout=2)

            self.assertFalse(runner.is_alive())
            self.assertFalse(service._config["enabled"])

    def test_total_mode_does_not_submit_more_than_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RegisterService(Path(tmp_dir) / "register.json")
            service._pool_metrics = lambda **_kwargs: self._metrics()
            service._config.update({
                "enabled": True,
                "mode": "total",
                "total": 1,
                "threads": 3,
                "max_attempts": 100,
                "max_consecutive_failures": 10,
                "max_runtime_minutes": 5,
                "retry_cooldown_seconds": 30,
            })
            service._runner = threading.current_thread()

            with patch("services.register_service.openai_register.worker", return_value={"ok": True}) as worker:
                service._run()

            self.assertEqual(worker.call_count, 1)
            self.assertEqual(service._config["stats"]["stop_reason"], "已达到任务目标")

    def test_max_attempts_caps_initial_concurrent_submissions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RegisterService(Path(tmp_dir) / "register.json")
            service._pool_metrics = lambda **_kwargs: self._metrics()
            service._config.update({
                "enabled": True,
                "mode": "quota",
                "target_quota": 100,
                "threads": 3,
                "max_attempts": 2,
                "max_consecutive_failures": 10,
                "max_runtime_minutes": 5,
                "retry_cooldown_seconds": 30,
            })

            with patch("services.register_service.openai_register.worker", return_value={"ok": False}) as worker:
                runner = threading.Thread(target=service._run, daemon=True)
                service._runner = runner
                runner.start()
                self._wait_for(lambda: service._config["stats"].get("phase") == "cooldown")

                self.assertTrue(service._config["enabled"])
                self.assertEqual(worker.call_count, 2)
                self.assertIn("达到最大尝试次数 2", service._config["stats"]["stop_reason"])
                service.stop()
                runner.join(timeout=2)

            self.assertFalse(runner.is_alive())
            self.assertFalse(service._config["enabled"])

    def test_event_ticket_is_single_use(self) -> None:
        ticket = _issue_event_ticket()
        self.assertTrue(_consume_event_ticket(ticket))
        self.assertFalse(_consume_event_ticket(ticket))

    def test_register_logs_redact_query_email_and_body(self) -> None:
        text = _redact_register_log(
            "email=user@example.com url=https://auth.openai.com/path?state=secret&login_hint=user@example.com body=<html>secret</html>"
        )
        self.assertNotIn("secret", text)
        self.assertNotIn("user@example.com", text)
        self.assertIn("?[query redacted]", text)
        self.assertIn("body=[redacted]", text)

    def test_register_log_redaction_preserves_url_trailing_punctuation(self) -> None:
        text = _redact_register_log("request failed (https://example.com/callback?code=secret), retrying")
        self.assertEqual(text, "request failed (https://example.com/callback?[query redacted]), retrying")


if __name__ == "__main__":
    unittest.main()
