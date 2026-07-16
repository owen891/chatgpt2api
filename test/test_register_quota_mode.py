from __future__ import annotations

import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from api.register import _consume_event_ticket, _issue_event_ticket
from services.account_service import AccountService, TerminalRefreshTokenError
from services.register.openai_register import _registration_failure_metadata, _retry_after_seconds
from services.register_service import RegisterService, _redact_register_log


class RegisterQuotaModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._proxy_preflight_patch = patch.object(
            RegisterService,
            "_proxy_preflight",
            return_value={"ok": True, "skipped": True},
        )
        self._proxy_preflight_patch.start()
        self.addCleanup(self._proxy_preflight_patch.stop)

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

    def test_pool_check_does_not_move_scheduled_deadline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RegisterService(Path(tmp_dir) / "register.json")
            service._pool_metrics = lambda **_kwargs: self._metrics(100)
            service._config["stats"]["next_check_at"] = "2026-07-15T12:00:00+00:00"

            service._target_reached({"mode": "quota", "target_quota": 100}, submitted=0)

            self.assertEqual(service._config["stats"]["next_check_at"], "2026-07-15T12:00:00+00:00")

    def test_pool_check_can_skip_stale_account_refresh_while_workers_are_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RegisterService(Path(tmp_dir) / "register.json")
            calls: list[dict] = []

            def metrics(**kwargs):
                calls.append(kwargs)
                return self._metrics(0)

            service._pool_metrics = metrics
            service._target_reached({"mode": "quota", "target_quota": 100}, submitted=0, refresh_stale=False)

            self.assertEqual(len(calls), 1)
            self.assertFalse(calls[0]["refresh_stale"])

    def test_stopping_state_recovers_to_stopped_without_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RegisterService(Path(tmp_dir) / "register.json")
            service._pool_metrics = lambda **_kwargs: self._metrics()
            service._config["enabled"] = False
            service._config["stats"].update({
                "phase": "stopping",
                "running": 1,
                "next_check_at": "2026-07-15T12:00:00+00:00",
            })

            snapshot = service.get()

            self.assertEqual(snapshot["stats"]["phase"], "stopped")
            self.assertEqual(snapshot["stats"]["running"], 0)
            self.assertEqual(snapshot["stats"]["next_check_at"], "")

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

    def test_refill_starts_below_quota_target_and_stops_at_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RegisterService(Path(tmp_dir) / "register.json")
            service._config.update({"mode": "quota", "target_quota": 100, "trigger_quota": 50})
            metrics = self._metrics(75)
            service._pool_metrics = lambda **_kwargs: dict(metrics)
            self.assertTrue(service._refill_required(service.get()))

            metrics.update(self._metrics(0))
            self.assertTrue(service._refill_required(service.get()))

            metrics.update(self._metrics(100))
            self.assertFalse(service._refill_required(service.get()))

    def test_refill_starts_below_available_target_and_stops_at_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RegisterService(Path(tmp_dir) / "register.json")
            service._config.update({"mode": "available", "target_available": 4, "trigger_available": 1})
            metrics = self._metrics(75)
            service._pool_metrics = lambda **_kwargs: dict(metrics)

            self.assertTrue(service._refill_required(service.get()))

            metrics.update(self._metrics(0))
            self.assertTrue(service._refill_required(service.get()))

            metrics.update(self._metrics(100))
            self.assertFalse(service._refill_required(service.get()))

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
                self._wait_for(lambda: service._config["stats"].get("phase") == "cooldown" and bool(service._config["stats"].get("next_check_at")))

                self.assertTrue(service._config["enabled"])
                self.assertEqual(worker.call_count, 2)
                self.assertIn("连续失败 2 次", service._config["stats"]["stop_reason"])
                service.stop()
                runner.join(timeout=2)

            self.assertFalse(runner.is_alive())
            self.assertFalse(service._config["enabled"])

    def test_concurrent_workers_do_not_exceed_failure_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RegisterService(Path(tmp_dir) / "register.json")
            service._pool_metrics = lambda **_kwargs: self._metrics()
            service._config.update({
                "enabled": True,
                "mode": "quota",
                "target_quota": 100,
                "threads": 2,
                "max_attempts": 100,
                "max_consecutive_failures": 3,
                "max_runtime_minutes": 5,
                "retry_cooldown_seconds": 30,
            })

            with patch("services.register_service.openai_register.worker", return_value={"ok": False}) as worker:
                runner = threading.Thread(target=service._run, daemon=True)
                service._runner = runner
                runner.start()
                self._wait_for(lambda: service._config["stats"].get("phase") == "cooldown")

                self.assertEqual(worker.call_count, 3)
                service.stop()
                runner.join(timeout=2)

            self.assertFalse(runner.is_alive())

    def test_first_rate_limit_stops_replacement_submissions_and_enters_cooldown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RegisterService(Path(tmp_dir) / "register.json")
            service._pool_metrics = lambda **_kwargs: self._metrics()
            service._config.update({
                "enabled": True,
                "mode": "quota",
                "target_quota": 100,
                "threads": 2,
                "max_attempts": 100,
                "max_consecutive_failures": 10,
                "max_runtime_minutes": 5,
                "retry_cooldown_seconds": 30,
                "rate_limit_cooldown_seconds": 60,
            })
            result = {
                "ok": False,
                "error": "passwordless_send_otp_http_429",
                "failure_kind": "rate_limit",
                "status_code": 429,
                "retry_after": 120,
                "provider": "mail-a",
            }

            with patch("services.register_service.openai_register.worker", return_value=result) as worker:
                runner = threading.Thread(target=service._run, daemon=True)
                service._runner = runner
                runner.start()
                self._wait_for(lambda: service._config["stats"].get("phase") == "cooldown")

                self.assertEqual(worker.call_count, 2)
                self.assertIn("注册出口触发上游限流", service._config["stats"]["stop_reason"])
                self.assertNotIn("mail-a", service._config["stats"].get("channel_health", {}))
                next_check = datetime.fromisoformat(service._config["stats"]["next_check_at"])
                self.assertGreaterEqual((next_check - datetime.now(timezone.utc)).total_seconds(), 115)
                service.stop()
                runner.join(timeout=2)

            self.assertFalse(runner.is_alive())

    def test_rate_limit_is_classified_from_legacy_error_text(self) -> None:
        metadata = _registration_failure_metadata(
            RuntimeError('passwordless_send_otp_http_429, detail={"code":"rate_limit_exceeded"}')
        )

        self.assertEqual(metadata["failure_kind"], "rate_limit")
        self.assertEqual(metadata["status_code"], 429)

    def test_failure_metadata_ignores_malformed_optional_numbers(self) -> None:
        error = RuntimeError("registration failed")
        error.status_code = "unknown"
        error.retry_after = "later"

        self.assertEqual(_registration_failure_metadata(error), {"failure_kind": "registration_error"})

    def test_retry_after_seconds_accepts_delta_seconds(self) -> None:
        response = type("Response", (), {"headers": {"Retry-After": "120"}})()

        self.assertEqual(_retry_after_seconds(response), 120)

    def test_proxy_preflight_failure_enters_cooldown_without_counting_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RegisterService(Path(tmp_dir) / "register.json")
            service._pool_metrics = lambda **_kwargs: self._metrics()
            service._config.update({
                "enabled": True,
                "mode": "quota",
                "target_quota": 100,
                "threads": 3,
                "max_attempts": 100,
                "max_consecutive_failures": 10,
                "max_runtime_minutes": 5,
                "retry_cooldown_seconds": 30,
            })

            with (
                patch.object(service, "_proxy_preflight", return_value={"ok": False, "error": "connection refused"}),
                patch("services.register_service.openai_register.worker", return_value={"ok": True}) as worker,
            ):
                runner = threading.Thread(target=service._run, daemon=True)
                service._runner = runner
                runner.start()
                self._wait_for(lambda: service._config["stats"].get("phase") == "cooldown")

                self.assertEqual(worker.call_count, 0)
                self.assertEqual(service._config["stats"]["done"], 0)
                self.assertEqual(service._config["stats"]["fail"], 0)
                self.assertIn("代理预检失败", service._config["stats"]["stop_reason"])
                service.stop()
                runner.join(timeout=2)

            self.assertFalse(runner.is_alive())
            self.assertFalse(service._config["enabled"])

    def test_clearance_preflight_warning_does_not_block_proxy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RegisterService(Path(tmp_dir) / "register.json")
            self._proxy_preflight_patch.stop()
            profile = type("Profile", (), {
                "proxy_url": "http://proxy.example:8080",
                "proxy_source": "runtime",
                "clearance_mode": "flaresolverr",
                "clearance": {"enabled": True},
            })()
            with (
                patch("services.register_service.proxy_settings.get_profile", return_value=profile),
                patch("services.register_service.test_proxy", return_value={"ok": True, "status": 200}),
                patch("services.register_service.proxy_settings.refresh_clearance", return_value=None),
            ):
                result = service._proxy_preflight()

            self.assertTrue(result["ok"])
            self.assertFalse(result["clearance_ok"])
            self.assertIn("Cloudflare", result["clearance_warning"])

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

    def test_record_attempt_diagnostics_tracks_stage_funnel_and_recent_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RegisterService(Path(tmp_dir) / "register.json")
            result = {
                "ok": False,
                "provider": "mail-a",
                "error": "Cloudflare blocked: status=403, cf-ray=abc123-SIN, url=https://auth.openai.com/api/accounts/authorize?state=secret",
                "failure_kind": "http_error",
                "status_code": 403,
                "duration_ms": 1200,
                "diagnostics": {
                    "flow": "passwordless_signup",
                    "failure_stage": "signup_wait_otp",
                    "duration_ms": 1200,
                    "proxy_label": "http://proxy.example:8443",
                    "proxy_source": "runtime",
                    "egress_mode": "single_proxy",
                    "clearance_mode": "flaresolverr",
                    "clearance_enabled": True,
                    "clearance_refresh_attempts": 1,
                    "clearance_refresh_success": 0,
                    "stage_order": ["mailbox_create", "authorize", "signup_send_otp", "signup_wait_otp"],
                    "stages": {
                        "mailbox_create": {"attempts": 1, "duration_ms": 100, "last_duration_ms": 100, "ok": True},
                        "authorize": {"attempts": 1, "duration_ms": 200, "last_duration_ms": 200, "ok": True},
                        "signup_send_otp": {"attempts": 1, "duration_ms": 150, "last_duration_ms": 150, "ok": True},
                        "signup_wait_otp": {"attempts": 2, "duration_ms": 750, "last_duration_ms": 600, "ok": False},
                    },
                },
            }

            service._record_attempt_diagnostics(result)

            diagnostics = service._config["stats"]["diagnostics"]
            self.assertEqual(diagnostics["attempts"], 1)
            self.assertEqual(diagnostics["fail"], 1)
            self.assertEqual(diagnostics["funnel"]["signup_wait_otp"]["reached"], 1)
            self.assertEqual(diagnostics["funnel"]["signup_wait_otp"]["fail"], 1)
            self.assertEqual(diagnostics["funnel"]["signup_wait_otp"]["retries"], 1)
            self.assertEqual(diagnostics["providers"]["mail-a"]["fail"], 1)
            self.assertEqual(diagnostics["providers"]["mail-a"]["failure_stages"]["signup_wait_otp"], 1)
            self.assertEqual(diagnostics["egresses"]["http://proxy.example:8443"]["fail"], 1)
            self.assertEqual(diagnostics["egresses"]["http://proxy.example:8443"]["proxy_source"], "runtime")
            self.assertEqual(diagnostics["egresses"]["http://proxy.example:8443"]["clearance_mode"], "flaresolverr")
            self.assertEqual(diagnostics["egresses"]["http://proxy.example:8443"]["status_codes"]["403"], 1)
            self.assertEqual(diagnostics["egresses"]["http://proxy.example:8443"]["last_cf_ray"], "abc123-SIN")
            self.assertEqual(diagnostics["egresses"]["http://proxy.example:8443"]["cloudflare_blocks"], 1)
            self.assertEqual(diagnostics["failure_kinds"]["http_error"], 1)
            self.assertEqual(len(diagnostics["recent_failures"]), 1)
            self.assertEqual(diagnostics["recent_failures"][0]["stage"], "signup_wait_otp")
            self.assertEqual(diagnostics["recent_failures"][0]["proxy_label"], "http://proxy.example:8443")
            self.assertEqual(diagnostics["recent_failures"][0]["status_code"], 403)
            self.assertEqual(diagnostics["recent_failures"][0]["cf_ray"], "abc123-SIN")

    def test_record_attempt_diagnostics_tracks_successful_provider_timing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RegisterService(Path(tmp_dir) / "register.json")
            result = {
                "ok": True,
                "duration_ms": 900,
                "result": {"register_provider": "mail-b"},
                "diagnostics": {
                    "flow": "microsoft_passwordless_login",
                    "duration_ms": 900,
                    "proxy_label": "direct",
                    "proxy_source": "direct",
                    "egress_mode": "direct",
                    "clearance_mode": "none",
                    "clearance_enabled": False,
                    "clearance_refresh_attempts": 0,
                    "clearance_refresh_success": 0,
                    "stage_order": ["mailbox_create", "authorize", "login_flow", "persist_account", "refresh_account"],
                    "stages": {
                        "mailbox_create": {"attempts": 1, "duration_ms": 80, "last_duration_ms": 80, "ok": True},
                        "authorize": {"attempts": 1, "duration_ms": 120, "last_duration_ms": 120, "ok": True},
                        "login_flow": {"attempts": 1, "duration_ms": 500, "last_duration_ms": 500, "ok": True},
                        "persist_account": {"attempts": 1, "duration_ms": 100, "last_duration_ms": 100, "ok": True},
                        "refresh_account": {"attempts": 1, "duration_ms": 100, "last_duration_ms": 100, "ok": True},
                    },
                },
            }

            service._record_attempt_diagnostics(result)

            diagnostics = service._config["stats"]["diagnostics"]
            self.assertEqual(diagnostics["attempts"], 1)
            self.assertEqual(diagnostics["success"], 1)
            self.assertEqual(diagnostics["funnel"]["login_flow"]["success"], 1)
            self.assertEqual(diagnostics["providers"]["mail-b"]["success"], 1)
            self.assertEqual(diagnostics["providers"]["mail-b"]["avg_duration_ms"], 900.0)
            self.assertEqual(diagnostics["providers"]["mail-b"]["last_flow"], "microsoft_passwordless_login")
            self.assertEqual(diagnostics["egresses"]["direct"]["success"], 1)
            self.assertEqual(diagnostics["egresses"]["direct"]["clearance_mode"], "none")
            self.assertEqual(diagnostics["recent_failures"], [])

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

    def test_oauth_refresh_error_classification_distinguishes_terminal_and_transient(self) -> None:
        self.assertTrue(AccountService._is_terminal_refresh_error(400, "invalid_grant", ""))
        self.assertTrue(AccountService._is_terminal_refresh_error(401, "", "Session has ended"))
        self.assertFalse(AccountService._is_terminal_refresh_error(429, "invalid_grant", ""))
        self.assertFalse(AccountService._is_terminal_refresh_error(503, "invalid_refresh_token", ""))

    def test_oauth_refresh_error_fields_supports_nested_payloads(self) -> None:
        self.assertEqual(
            AccountService._oauth_refresh_error_fields({"error": {"code": "invalid_grant", "message": "expired"}}),
            ("invalid_grant", "expired"),
        )

    def test_terminal_oauth_refresh_marks_account_invalid(self) -> None:
        service = object.__new__(AccountService)
        service._token_refresh_lock = threading.Lock()
        service._get_account_for_token = lambda _token: ("access-token", {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "email": "user@example.com",
            "password": "",
        })
        service._token_needs_refresh = lambda _token, force=False: True
        service._recent_token_refresh_error = lambda _account: False
        service._request_access_token_refresh = Mock(
            side_effect=TerminalRefreshTokenError(400, "invalid_grant", "expired")
        )
        service._record_token_refresh_error = Mock()
        service.remove_invalid_token = Mock()

        self.assertEqual(service.refresh_access_token("access-token"), "access-token")
        service._record_token_refresh_error.assert_called_once()
        service.remove_invalid_token.assert_called_once_with("access-token", "refresh_access_token")


if __name__ == "__main__":
    unittest.main()
