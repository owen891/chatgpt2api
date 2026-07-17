from __future__ import annotations

import unittest
from unittest import mock

from services.account_service import ImageAccountSelectionError
from services.openai_backend_api import ImagePollTimeoutError
from services.protocol.conversation import ConversationRequest, ImageGenerationError, _generate_single_image
from services.protocol.image_routing import run_json, run_stream


class ImagePoolRoutingTests(unittest.TestCase):
    def test_native_model_uses_account_pool_before_upstream(self) -> None:
        calls: list[str] = []

        result = run_json(
            model="gpt-image-2",
            body={},
            account_call=lambda: calls.append("account") or {"data": [{"b64_json": "ok"}]},
            upstream_call=lambda: calls.append("upstream") or {"data": []},
        )

        self.assertEqual(calls, ["account"])
        self.assertEqual(result["_image_route_selected"], "account_pool")

    def test_retryable_account_error_falls_back_to_upstream(self) -> None:
        body: dict = {}

        def account():
            raise ImageGenerationError("timeout", status_code=504, code="upstream_timeout")

        result = run_json(
            model="gpt-image-2",
            body=body,
            account_call=account,
            upstream_call=lambda: {"data": [{"b64_json": "ok"}], "_image_upstream_selected": "backup"},
        )

        self.assertEqual(result["_image_route_selected"], "backup")
        self.assertEqual(result["_image_pool_attempts"][0]["outcome"], "fallback")

    def test_accepted_poll_timeout_does_not_fall_back_to_upstream(self) -> None:
        timeout = ImagePollTimeoutError("ChatGPT 生图超时")
        timeout.conversation_id = "conv-pending"
        upstream = mock.Mock(return_value={"data": [{"b64_json": "duplicate"}]})

        with self.assertRaises(ImagePollTimeoutError) as raised:
            run_json(
                model="gpt-image-2",
                body={},
                account_call=mock.Mock(side_effect=timeout),
                upstream_call=upstream,
            )

        self.assertIs(raised.exception, timeout)
        upstream.assert_not_called()

    def test_accepted_poll_timeout_does_not_select_another_account(self) -> None:
        timeout = ImagePollTimeoutError("ChatGPT 生图超时")
        timeout.conversation_id = "conv-pending"
        backend = mock.Mock()

        with (
            mock.patch(
                "services.protocol.conversation.account_service.get_available_access_token",
                return_value="token-1",
            ) as select_account,
            mock.patch(
                "services.protocol.conversation.account_service.get_account",
                return_value={"email": "account@example.test"},
            ),
            mock.patch("services.protocol.conversation.account_service.mark_image_result"),
            mock.patch("services.protocol.conversation.OpenAIBackendAPI", return_value=backend),
            mock.patch("services.protocol.conversation.stream_image_outputs", side_effect=timeout),
        ):
            with self.assertRaises(ImagePollTimeoutError) as raised:
                _generate_single_image(
                    ConversationRequest(prompt="draw", model="gpt-image-2"),
                    1,
                    1,
                )

        self.assertIs(raised.exception, timeout)
        self.assertEqual(raised.exception.conversation_id, "conv-pending")
        select_account.assert_called_once()
        backend.close.assert_called_once()

    def test_account_pool_auth_failure_falls_back_to_upstream(self) -> None:
        body: dict = {}

        result = run_json(
            model="gpt-image-2",
            body=body,
            account_call=lambda: (_ for _ in ()).throw(
                ImageAccountSelectionError("auth_invalid", "authentication failed for 1 accounts")
            ),
            upstream_call=lambda: {"data": [{"b64_json": "ok"}], "_image_upstream_selected": "backup"},
        )

        self.assertEqual(result["_image_route_selected"], "backup")
        self.assertEqual(result["_image_pool_attempts"][0]["status"], 401)
        self.assertEqual(result["_image_pool_attempts"][0]["outcome"], "fallback")

    def test_content_policy_error_never_calls_upstream(self) -> None:
        called = False

        def upstream():
            nonlocal called
            called = True
            return {"data": []}

        with self.assertRaises(ImageGenerationError):
            run_json(
                model="gpt-image-2",
                body={},
                account_call=lambda: (_ for _ in ()).throw(ImageGenerationError(
                    "blocked",
                    status_code=400,
                    error_type="invalid_request_error",
                    code="content_policy_violation",
                )),
                upstream_call=upstream,
            )

        self.assertFalse(called)

    def test_non_native_model_goes_directly_to_upstream(self) -> None:
        calls: list[str] = []
        result = run_json(
            model="flux-pro",
            body={},
            account_call=lambda: calls.append("account") or {"data": []},
            upstream_call=lambda: calls.append("upstream") or {"data": [], "_image_upstream_selected": "flux"},
        )
        self.assertEqual(calls, ["upstream"])
        self.assertEqual(result["_image_route_selected"], "flux")

    def test_stream_discards_buffered_progress_before_fallback(self) -> None:
        def account_stream():
            yield {"progress_text": "account progress"}
            raise ImageGenerationError("timeout", status_code=504, code="upstream_timeout")

        chunks = list(run_stream(
            model="gpt-image-2",
            body={},
            account_call=account_stream,
            upstream_call=lambda: {"data": [{"b64_json": "ok"}], "_image_upstream_selected": "backup"},
        ))

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["_image_route_selected"], "backup")

    def test_stream_account_pool_unavailable_falls_back_to_upstream(self) -> None:
        def account_stream():
            yield {"progress_text": "checking account pool"}
            raise ImageAccountSelectionError("unavailable", "no account available")

        chunks = list(run_stream(
            model="gpt-image-2",
            body={},
            account_call=account_stream,
            upstream_call=lambda: {"data": [{"b64_json": "ok"}], "_image_upstream_selected": "backup"},
        ))

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["_image_route_selected"], "backup")


if __name__ == "__main__":
    unittest.main()
