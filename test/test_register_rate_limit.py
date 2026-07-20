from __future__ import annotations

import unittest

from services.register.openai_register import RegistrationHTTPError, _registration_failure_metadata


class RegistrationRateLimitTests(unittest.TestCase):
    def test_http_429_error_exposes_scheduler_metadata(self) -> None:
        error = RegistrationHTTPError("passwordless_send_otp_http_429", status_code=429, retry_after=37)

        self.assertEqual(
            _registration_failure_metadata(error),
            {"failure_kind": "rate_limit", "status_code": 429, "retry_after": 37},
        )

    def test_rate_limit_response_body_is_classified_without_typed_error(self) -> None:
        metadata = _registration_failure_metadata(RuntimeError("code=rate_limit_exceeded"))

        self.assertEqual(metadata["failure_kind"], "rate_limit")
        self.assertEqual(metadata["status_code"], 429)

    def test_registration_disallowed_response_is_terminal(self) -> None:
        metadata = _registration_failure_metadata(
            RegistrationHTTPError(
                'create_account_http_400 detail={"error":{"code":"registration_disallowed"}}',
                status_code=400,
            )
        )

        self.assertEqual(metadata["failure_kind"], "registration_disallowed")
        self.assertEqual(metadata["status_code"], 400)


if __name__ == "__main__":
    unittest.main()
