from __future__ import annotations

from typing import Any, Iterator

from services.protocol.conversation import (
    ConversationRequest,
    collect_image_outputs,
    count_text_tokens,
    stream_image_chunks,
    stream_image_outputs_with_pool,
)
from services.image_upstream_service import image_upstream_service
from services.protocol.image_routing import run_json, run_stream
from utils.image_tokens import count_image_output_items_tokens, image_usage


def handle(body: dict[str, Any]) -> dict[str, Any] | Iterator[dict[str, Any]]:
    prompt = str(body.get("prompt") or "")
    model = str(body.get("model") or "gpt-image-2")
    n = int(body.get("n") or 1)
    size = body.get("size")
    quality = str(body.get("quality") or "auto")
    response_format = str(body.get("response_format") or "b64_json")
    base_url = str(body.get("base_url") or "") or None
    progress_callback = body.get("progress_callback")
    def upstream_call() -> dict[str, Any] | None:
        result = image_upstream_service.try_handle("generation", body)
        if result is None:
            return None
        result["usage"] = image_usage(
            input_text_tokens=count_text_tokens(prompt, model),
            output_tokens=count_image_output_items_tokens(result.get("data"), size, quality),
        )
        return result

    def account_outputs():
        return stream_image_outputs_with_pool(ConversationRequest(
            prompt=prompt,
            model=model,
            n=n,
            size=size,
            quality=quality,
            response_format=response_format,
            base_url=base_url,
            message_as_error=True,
            progress_callback=progress_callback,
        ))

    if body.get("stream"):
        return run_stream(
            model=model,
            body=body,
            account_call=lambda: stream_image_chunks(account_outputs()),
            upstream_call=upstream_call,
        )

    def account_call() -> dict[str, Any]:
        result = collect_image_outputs(account_outputs())
        result["usage"] = image_usage(
            input_text_tokens=count_text_tokens(prompt, model),
            output_tokens=count_image_output_items_tokens(result.get("data"), size, quality),
        )
        return result

    return run_json(model=model, body=body, account_call=account_call, upstream_call=upstream_call)
