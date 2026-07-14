from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

from services.openai_backend_api import ImagePollTimeoutError
from services.protocol.conversation import ImageGenerationError
from utils.helper import is_supported_image_model


NON_FALLBACK_CODES = {
    "content_policy_violation",
    "invalid_request_error",
    "invalid_image_input",
    "no_image_generated",
    "authentication_error",
    "invalid_api_key",
    "token_invalid",
}


def uses_account_pool(model: object) -> bool:
    """只有项目明确支持的 ChatGPT 原生图片模型进入账号池。"""
    return is_supported_image_model(model)


def allows_upstream_fallback(error: BaseException) -> bool:
    if isinstance(error, ImagePollTimeoutError):
        return True
    if isinstance(error, ImageGenerationError):
        code = str(getattr(error, "code", "") or "").strip().lower()
        status = int(getattr(error, "status_code", 0) or 0)
        if code in NON_FALLBACK_CODES or status in {400, 401, 403, 404, 422}:
            return False
        return status == 429 or status >= 500
    return isinstance(error, (ConnectionError, TimeoutError))


def _attempt(error: BaseException) -> dict[str, object]:
    return {
        "source": "account_pool",
        "outcome": "fallback" if allows_upstream_fallback(error) else "terminal",
        "status": int(getattr(error, "status_code", 0) or 0),
        "code": str(getattr(error, "code", "") or ""),
        "error": str(error)[:500],
    }


def _attach_route(result: dict[str, Any], body: dict[str, Any], selected: str) -> dict[str, Any]:
    result["_image_route_selected"] = selected
    if body.get("_image_pool_attempts"):
        result["_image_pool_attempts"] = list(body["_image_pool_attempts"])
    return result


def run_json(
    *,
    model: object,
    body: dict[str, Any],
    account_call: Callable[[], dict[str, Any]],
    upstream_call: Callable[[], dict[str, Any] | None],
) -> dict[str, Any]:
    if not uses_account_pool(model):
        result = upstream_call()
        if result is None:
            raise ImageGenerationError(
                "unsupported image model",
                status_code=400,
                error_type="invalid_request_error",
                code="unsupported_model",
            )
        return _attach_route(result, body, str(result.get("_image_upstream_selected") or "image_upstream"))

    try:
        return _attach_route(account_call(), body, "account_pool")
    except BaseException as error:
        body.setdefault("_image_pool_attempts", []).append(_attempt(error))
        if not allows_upstream_fallback(error):
            raise
        result = upstream_call()
        if result is None:
            raise
        return _attach_route(result, body, str(result.get("_image_upstream_selected") or "image_upstream"))


def _has_business_output(chunk: dict[str, Any]) -> bool:
    if isinstance(chunk.get("data"), list) and chunk["data"]:
        return True
    if isinstance(chunk.get("error"), dict):
        return True
    return bool(chunk.get("message") or chunk.get("finish_reason"))


def run_stream(
    *,
    model: object,
    body: dict[str, Any],
    account_call: Callable[[], Iterator[dict[str, Any]]],
    upstream_call: Callable[[], dict[str, Any] | None],
) -> Iterator[dict[str, Any]]:
    def stream() -> Iterator[dict[str, Any]]:
        if not uses_account_pool(model):
            result = upstream_call()
            if result is None:
                raise ImageGenerationError(
                    "unsupported image model",
                    status_code=400,
                    error_type="invalid_request_error",
                    code="unsupported_model",
                )
            yield _attach_route(result, body, str(result.get("_image_upstream_selected") or "image_upstream"))
            return

        buffered: list[dict[str, Any]] = []
        emitted_business = False
        try:
            for chunk in account_call():
                tagged = dict(chunk)
                tagged["_image_route_selected"] = "account_pool"
                if _has_business_output(tagged):
                    if not emitted_business:
                        emitted_business = True
                        yield from buffered
                        buffered.clear()
                    yield tagged
                else:
                    buffered.append(tagged)
            yield from buffered
            return
        except BaseException as error:
            body.setdefault("_image_pool_attempts", []).append(_attempt(error))
            if emitted_business or not allows_upstream_fallback(error):
                raise
            result = upstream_call()
            if result is None:
                raise
            yield _attach_route(result, body, str(result.get("_image_upstream_selected") or "image_upstream"))

    return stream()
