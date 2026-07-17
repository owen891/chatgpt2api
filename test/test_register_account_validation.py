from __future__ import annotations

import unittest
from unittest import mock

import services.register.openai_register as register_module


class FakeAccountService:
    def __init__(self, account: dict, errors: list[dict] | None = None) -> None:
        self.account = account
        self.errors = errors or []
        self.added: list[dict] = []
        self.deleted: list[str] = []

    def add_account_items(self, items: list[dict]) -> dict:
        self.added.extend(items)
        return {"added": len(items)}

    def refresh_accounts(self, _tokens: list[str]) -> dict:
        return {"errors": list(self.errors)}

    @staticmethod
    def resolve_access_token(token: str) -> str:
        return token

    def get_account(self, _token: str) -> dict:
        return dict(self.account)

    def delete_accounts(self, tokens: list[str]) -> dict:
        self.deleted.extend(tokens)
        return {"removed": len(tokens)}


class RegisterAccountValidationTests(unittest.TestCase):
    def test_accepts_only_remotely_validated_account(self) -> None:
        service = FakeAccountService({"last_remote_check_result": "success", "status": "normal"})

        with mock.patch.object(register_module, "account_service", service):
            account = register_module._store_and_validate_registered_account({"access_token": "token"}, 1)

        self.assertEqual(account["last_remote_check_result"], "success")
        self.assertEqual(service.deleted, [])

    def test_removes_terminally_invalid_registered_account(self) -> None:
        service = FakeAccountService(
            {"last_remote_check_result": "auth_invalid"},
            [{"error": "token invalidated"}],
        )

        with mock.patch.object(register_module, "account_service", service):
            with self.assertRaisesRegex(RuntimeError, "registered_account_auth_invalid"):
                register_module._store_and_validate_registered_account({"access_token": "token"}, 1)

        self.assertEqual(service.deleted, ["token"])

    def test_keeps_transient_failure_but_does_not_report_success(self) -> None:
        service = FakeAccountService(
            {"last_remote_check_result": "attempting"},
            [{"error": "network timeout"}],
        )

        with (
            mock.patch.object(register_module, "account_service", service),
            mock.patch.object(register_module, "step"),
        ):
            with self.assertRaisesRegex(RuntimeError, "registered_account_validation_failed"):
                register_module._store_and_validate_registered_account({"access_token": "token"}, 1)

        self.assertEqual(service.deleted, [])


if __name__ == "__main__":
    unittest.main()
