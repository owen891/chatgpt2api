from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from io import BytesIO
import threading
import time
from typing import Any, Callable

import requests
from PIL import Image
from services.config import config
from services.image_storage_service import ImageStorageService, image_storage_service
from services.protocol.conversation import ImageGenerationError


RETRYABLE_STATUS_CODES = {429}
TERMINAL_STATUS_CODES = {400, 401, 403, 404, 422}


@dataclass
class CircuitState:
    failures: int = 0
    opened_until: float = 0
    last_error: str = ""


@dataclass
class TestState:
    result: dict[str, object]
    tested_at: float


class ImageUpstreamService:
    def __init__(
        self,
        settings_provider: Callable[[], dict[str, object]] | None = None,
        storage: ImageStorageService | None = None,
        downloader: Callable[[str], tuple[bytes, str, str]] | None = None,
        requester: Callable[..., requests.Response] | None = None,
        runtime_state_provider: Callable[[], dict[str, object]] | None = None,
        runtime_state_saver: Callable[[dict[str, object]], None] | None = None,
    ) -> None:
        self._settings_provider = settings_provider or config.get_image_upstreams_settings
        self._storage = storage or image_storage_service
        self._downloader = downloader
        self._requester = requester or requests.request
        self._circuits: dict[str, CircuitState] = {}
        self._tests: dict[str, TestState] = {}
        self._inflight: dict[str, int] = {}
        self._request_times: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        self._runtime_state_saver = runtime_state_saver or (config.save_image_upstream_runtime_state if settings_provider is None else None)
        self._restore_runtime_state((runtime_state_provider or (config.get_image_upstream_runtime_state if settings_provider is None else lambda: {}))())

    def client_models(self) -> set[str]:
        models: set[str] = set()
        for channel in self._channels():
            if not channel.get("enabled"):
                continue
            for mapping in channel.get("model_mappings") or []:
                if isinstance(mapping, dict) and str(mapping.get("client_model") or "").strip():
                    models.add(str(mapping["client_model"]).strip())
        return models

    def model_entries(self) -> list[dict[str, object]]:
        """Return selectable channel-pinned image models for compatible clients."""
        entries: list[dict[str, object]] = []
        for channel in self._channels():
            if not channel.get("enabled"):
                continue
            channel_id = str(channel.get("id") or "").strip()
            channel_name = str(channel.get("name") or channel_id).strip()
            if not channel_id:
                continue
            for mapping in channel.get("model_mappings") or []:
                if not isinstance(mapping, dict):
                    continue
                client_model = str(mapping.get("client_model") or "").strip()
                if not client_model:
                    continue
                entries.append({
                    "id": self._selectable_model_id(channel, client_model),
                    "object": "model",
                    "created": 0,
                    "owned_by": "image-upstream",
                    "permission": [],
                    "root": client_model,
                    "parent": channel_id,
                    "display_name": f"{channel_name} · {client_model}",
                    "image_upstream": {
                        "channel_id": channel_id,
                        "channel_name": channel_name,
                        "client_model": client_model,
                        "model_alias": str(channel.get("model_alias") or ""),
                    },
                })
        return entries

    def statuses(self) -> dict[str, object]:
        now = time.time()
        channels: dict[str, dict[str, object]] = {}
        for channel in self._channels():
            channel_id = str(channel.get("id") or "").strip()
            if not channel_id:
                continue
            circuit = self._circuits.get(channel_id)
            test = self._tests.get(channel_id)
            opened_until = circuit.opened_until if circuit else 0
            channels[channel_id] = {
                "circuit_open": bool(opened_until > now),
                "cooldown_remaining_secs": max(0, int(opened_until - now)),
                "failure_count": circuit.failures if circuit else 0,
                "last_error": circuit.last_error if circuit else "",
                "last_test": dict(test.result) if test else None,
                "last_tested_at": int(test.tested_at) if test else None,
                "inflight": self._inflight.get(channel_id, 0),
                "max_concurrency": int(channel.get("max_concurrency") or 3),
                "requests_per_minute": int(channel.get("requests_per_minute") or 60),
            }
        return {"channels": channels}

    def try_handle(
        self,
        operation: str,
        body: dict[str, Any],
        *,
        images: list[tuple[bytes, str, str]] | None = None,
        masks: list[tuple[bytes, str, str]] | None = None,
    ) -> dict[str, Any] | None:
        model = str(body.get("model") or "gpt-image-2").strip()
        attempts: list[dict[str, object]] = []
        candidates = self._candidates(operation, model)
        max_attempts = int(self._settings().get("max_attempts") or 2)
        request_attempts = 0
        last_archive_error: ImageGenerationError | None = None
        last_archive_fallback_result: dict[str, Any] | None = None
        for channel, upstream_model in candidates:
            state = self._circuits.get(str(channel["id"]))
            if state and state.opened_until > time.time():
                attempts.append(self._attempt(channel, operation, 0, 0, "skipped_circuit"))
                continue
            if request_attempts >= max_attempts:
                break
            admitted, reason = self._admit(channel)
            if not admitted:
                attempts.append(self._attempt(channel, operation, 0, 0, reason))
                continue
            request_attempts += 1
            try:
                response = self._call(channel, operation, upstream_model, body, images, masks)
            except requests.RequestException as exc:
                self._record_failure(channel, str(exc))
                attempts.append(self._attempt(channel, operation, 0, 0, "retry", str(exc)))
                continue
            except Exception as exc:
                self._record_failure(channel, str(exc))
                attempts.append(self._attempt(channel, operation, 0, 0, "retry", str(exc)))
                continue
            finally:
                self._release(channel)

            duration_ms = int(response.elapsed.total_seconds() * 1000) if response.elapsed else 0
            status = int(response.status_code)
            if 200 <= status < 300:
                try:
                    result = self._archive_response(response, body)
                except ImageGenerationError as exc:
                    attempts.append(self._attempt(channel, operation, status, duration_ms, "archive_failed"))
                    pending = getattr(exc, "pending_archive", None)
                    if isinstance(pending, list):
                        enriched = [
                            {
                                **item,
                                "channel_id": str(channel.get("id") or ""),
                                "channel_name": str(channel.get("name") or channel.get("id") or ""),
                                "operation": operation,
                                "model": model,
                                "base_url": str(body.get("base_url") or ""),
                            }
                            for item in pending
                            if isinstance(item, dict) and str(item.get("url") or "").strip()
                        ]
                        if enriched:
                            fallback_result = self._fallback_result_from_pending(response, enriched)
                            if fallback_result is not None:
                                fallback_result["_image_pending_archive"] = enriched
                                fallback_result["_image_upstream_selected"] = str(channel.get("name") or channel.get("id"))
                                last_archive_fallback_result = fallback_result
                                if request_attempts >= max_attempts:
                                    fallback_result["_image_upstream_attempts"] = attempts
                                    return fallback_result
                            last_archive_error = exc
                            setattr(exc, "image_pending_archive", enriched)
                            body["_image_pending_archive"] = enriched
                            self._record_failure(channel, str(exc))
                            if request_attempts < max_attempts:
                                continue
                    body["_image_upstream_attempts"] = attempts
                    setattr(exc, "image_upstream_attempts", attempts)
                    raise
                except Exception as exc:
                    attempts.append(self._attempt(channel, operation, status, duration_ms, "archive_failed", str(exc)))
                    error = ImageGenerationError(
                        "上游生图成功，但图片归档失败",
                        status_code=502,
                        error_type="server_error",
                        code="image_archive_failed",
                    )
                    setattr(error, "image_upstream_attempts", attempts)
                    raise error from exc
                self._record_success(channel)
                attempts.append(self._attempt(channel, operation, status, duration_ms, "success"))
                result["_image_upstream_attempts"] = attempts
                result["_image_upstream_selected"] = str(channel.get("name") or channel.get("id"))
                return result

            message = self._safe_error(response)
            if status in TERMINAL_STATUS_CODES:
                attempts.append(self._attempt(channel, operation, status, duration_ms, "terminal", message))
                error = ImageGenerationError(message, status_code=status, error_type="invalid_request_error", code="image_upstream_error")
                setattr(error, "image_upstream_attempts", attempts)
                raise error
            if status in RETRYABLE_STATUS_CODES or 500 <= status <= 599:
                self._record_failure(channel, message)
                attempts.append(self._attempt(channel, operation, status, duration_ms, "retry", message))
                continue
            attempts.append(self._attempt(channel, operation, status, duration_ms, "terminal", message))
            error = ImageGenerationError(message, status_code=status, error_type="server_error", code="image_upstream_error")
            setattr(error, "image_upstream_attempts", attempts)
            raise error
        if last_archive_fallback_result is not None:
            last_archive_fallback_result["_image_upstream_attempts"] = attempts
            return last_archive_fallback_result
        if last_archive_error is not None:
            body["_image_upstream_attempts"] = attempts
            setattr(last_archive_error, "image_upstream_attempts", attempts)
            raise last_archive_error
        body["_image_upstream_attempts"] = attempts
        return None

    def _fallback_result_from_pending(
        self,
        response: requests.Response,
        pending: list[dict[str, object]],
    ) -> dict[str, Any] | None:
        data: list[dict[str, object]] = []
        for item in pending:
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            result: dict[str, object] = {"url": url}
            revised_prompt = str(item.get("revised_prompt") or "").strip()
            if revised_prompt:
                result["revised_prompt"] = revised_prompt
            data.append(result)
        if not data:
            return None
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        created = int(payload.get("created") or time.time()) if isinstance(payload, dict) else int(time.time())
        return {"created": created, "data": data}

    def archive_pending(self, pending: list[dict[str, object]], *, base_url: str = "") -> dict[str, Any]:
        """重新下载并归档已生成的图片，不重新调用上游生图。"""
        archived: list[dict[str, object]] = []
        for item in pending:
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            downloader = self._downloader
            if downloader is None:
                from api.image_inputs import download_image_url

                downloader = download_image_url
            image_data, _, _ = downloader(url)
            self._validate_image_data(image_data)
            stored = self._storage.save(image_data, base_url or str(item.get("base_url") or "") or None)
            result: dict[str, object] = {"url": stored.url}
            if item.get("revised_prompt"):
                result["revised_prompt"] = str(item["revised_prompt"])
            archived.append(result)
        if not archived:
            raise ImageGenerationError("待归档图片不存在", status_code=400, code="pending_archive_empty")
        return {"created": int(time.time()), "data": archived}

    def test_channel(self, channel: dict[str, object]) -> dict[str, object]:
        started = time.monotonic()
        prepared = self._prepare_channel(channel)
        if not prepared.get("base_url"):
            result = {"ok": False, "status": 0, "latency_ms": 0, "error": "Base URL is required", "models": []}
            self._record_test(prepared, result)
            return result
        try:
            response = self._requester(
                "GET",
                f"{prepared['base_url']}/models",
                headers=self._headers(prepared),
                timeout=float(prepared.get("timeout_secs") or 90),
                proxies=self._proxies(prepared),
            )
            models = self._response_models(response) if 200 <= response.status_code < 300 else []
            if 200 <= response.status_code < 300:
                self._record_success(prepared)
            result = {
                "ok": 200 <= response.status_code < 300,
                "status": int(response.status_code),
                "latency_ms": int((time.monotonic() - started) * 1000),
                "error": None if 200 <= response.status_code < 300 else self._safe_error(response),
                "models": models,
            }
            self._record_test(prepared, result)
            return result
        except Exception as exc:
            result = {"ok": False, "status": 0, "latency_ms": int((time.monotonic() - started) * 1000), "error": str(exc) or exc.__class__.__name__, "models": []}
            self._record_test(prepared, result)
            return result

    def fetch_models(self, channel: dict[str, object]) -> dict[str, object]:
        return self.test_channel(channel)

    def _settings(self) -> dict[str, object]:
        value = self._settings_provider()
        return value if isinstance(value, dict) else {"max_attempts": 2, "channels": []}

    def _channels(self) -> list[dict[str, object]]:
        channels = self._settings().get("channels")
        return [item for item in channels if isinstance(item, dict)] if isinstance(channels, list) else []

    def _candidates(self, operation: str, model: str) -> list[tuple[dict[str, object], str]]:
        capability = "supports_generation" if operation == "generation" else "supports_edits"
        pinned_channel_id, client_model = self._pinned_model_info(model)
        result: list[tuple[dict[str, object], str]] = []
        for channel in self._channels():
            if not channel.get("enabled") or not channel.get(capability):
                continue
            if pinned_channel_id and str(channel.get("id") or "") != pinned_channel_id:
                continue
            for mapping in channel.get("model_mappings") or []:
                if isinstance(mapping, dict) and str(mapping.get("client_model") or "").strip() == client_model:
                    result.append((channel, str(mapping.get("upstream_model") or "").strip()))
                    break
        return sorted(
            result,
            key=lambda item: (
                int(item[0].get("priority") or 0),
                0 if item[0].get("default") else 1,
                str(item[0].get("id") or ""),
            ),
        )

    def _pinned_model_info(self, model: str) -> tuple[str | None, str]:
        pinned_channel_id, client_model = self._parse_pinned_model_id(model)
        if pinned_channel_id:
            return pinned_channel_id, client_model
        for channel in self._channels():
            channel_id = str(channel.get("id") or "").strip()
            for mapping in channel.get("model_mappings") or []:
                if not isinstance(mapping, dict):
                    continue
                mapped_model = str(mapping.get("client_model") or "").strip()
                if mapped_model and model == self._selectable_model_id(channel, mapped_model):
                    return channel_id, mapped_model
        return None, model

    def _selectable_model_id(self, channel: dict[str, object], client_model: str) -> str:
        alias = str(channel.get("model_alias") or "").strip()
        if not alias:
            return self._pinned_model_id(str(channel.get("id") or ""), client_model)
        mappings = [item for item in channel.get("model_mappings") or [] if isinstance(item, dict) and str(item.get("client_model") or "").strip()]
        return alias if len(mappings) == 1 else f"{alias}--{client_model}"

    @staticmethod
    def _pinned_model_id(channel_id: str, client_model: str) -> str:
        encoded_model = base64.urlsafe_b64encode(client_model.encode("utf-8")).decode("ascii").rstrip("=")
        return f"image-upstream:{channel_id}:{encoded_model}"

    @staticmethod
    def _parse_pinned_model_id(model: str) -> tuple[str | None, str]:
        prefix = "image-upstream:"
        if not model.startswith(prefix):
            return None, model
        channel_id, separator, encoded_model = model[len(prefix):].partition(":")
        if not channel_id or not separator or not encoded_model:
            return None, model
        try:
            padding = "=" * (-len(encoded_model) % 4)
            client_model = base64.urlsafe_b64decode(f"{encoded_model}{padding}").decode("utf-8").strip()
        except (UnicodeDecodeError, ValueError):
            return None, model
        return (channel_id, client_model) if client_model else (None, model)

    def _prepare_channel(self, channel: dict[str, object]) -> dict[str, object]:
        prepared = dict(channel)
        channel_id = str(prepared.get("id") or "")
        if not str(prepared.get("api_key") or "").strip() and channel_id:
            for existing in self._channels():
                if str(existing.get("id") or "") == channel_id:
                    prepared["api_key"] = existing.get("api_key")
                    break
        prepared["base_url"] = str(prepared.get("base_url") or "").strip().rstrip("/")
        return prepared

    def _call(self, channel: dict[str, object], operation: str, upstream_model: str, body: dict[str, Any], images, masks) -> requests.Response:
        channel = self._prepare_channel(channel)
        url = f"{channel['base_url']}/images/{'generations' if operation == 'generation' else 'edits'}"
        kwargs: dict[str, Any] = {
            "headers": self._headers(channel),
            # Image upstreams can perform their own polling and account retry.
            # Keep the default above that full lifecycle, not just first-byte time.
            "timeout": float(channel.get("timeout_secs") or 360),
            "proxies": self._proxies(channel),
        }
        if operation == "generation":
            kwargs["json"] = self._generation_payload(body, upstream_model)
        else:
            kwargs["data"], kwargs["files"] = self._edit_payload(body, upstream_model, images or [], masks or [])
        return self._requester("POST", url, **kwargs)

    @staticmethod
    def _headers(channel: dict[str, object]) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        api_key = str(channel.get("api_key") or "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    @staticmethod
    def _proxies(channel: dict[str, object]) -> dict[str, str] | None:
        proxy_url = str(channel.get("proxy_url") or "").strip()
        return {"http": proxy_url, "https": proxy_url} if proxy_url else None

    @staticmethod
    def _generation_payload(body: dict[str, Any], model: str) -> dict[str, Any]:
        fields = ("prompt", "n", "size", "quality", "response_format", "style", "background", "output_format", "output_compression")
        payload = {key: body[key] for key in fields if body.get(key) is not None}
        payload["model"] = model
        return payload

    @staticmethod
    def _edit_payload(body: dict[str, Any], model: str, images: list[tuple[bytes, str, str]], masks: list[tuple[bytes, str, str]]):
        fields = ("prompt", "n", "size", "quality", "response_format", "background", "output_format", "output_compression")
        data = {key: str(body[key]) for key in fields if body.get(key) is not None}
        data["model"] = model
        files: list[tuple[str, tuple[str, BytesIO, str]]] = []
        for image_data, filename, mime_type in images:
            files.append(("image", (filename or "image.png", BytesIO(image_data), mime_type or "image/png")))
        for mask_data, filename, mime_type in masks:
            files.append(("mask", (filename or "mask.png", BytesIO(mask_data), mime_type or "image/png")))
        return data, files

    def _archive_response(self, response: requests.Response, body: dict[str, Any]) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise ImageGenerationError("上游返回了无效的图片响应", status_code=502, code="invalid_upstream_response") from exc
        items = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(items, list) or not items:
            raise ImageGenerationError("上游图片响应不包含 data", status_code=502, code="invalid_upstream_response")
        archived: list[dict[str, object]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("b64_json"):
                try:
                    image_data = base64.b64decode(str(item["b64_json"]), validate=True)
                except (binascii.Error, ValueError) as exc:
                    raise ImageGenerationError("上游返回了无效的图片数据", status_code=502, code="invalid_upstream_response") from exc
            elif item.get("url"):
                source_url = str(item["url"])
                downloader = self._downloader
                if downloader is None:
                    from api.image_inputs import download_image_url

                    downloader = download_image_url
                try:
                    image_data, _, _ = downloader(source_url)
                except Exception as exc:
                    error = ImageGenerationError(
                        f"图片归档下载失败：{str(exc)[:500]}",
                        status_code=502,
                        error_type="server_error",
                        code="image_archive_failed",
                    )
                    setattr(
                        error,
                        "pending_archive",
                        [{"url": source_url, "revised_prompt": str(item.get("revised_prompt") or "")}],
                    )
                    raise error from exc
            else:
                raise ImageGenerationError("上游图片响应缺少 url 或 b64_json", status_code=502, code="invalid_upstream_response")
            if not image_data:
                raise ImageGenerationError("上游返回了空图片", status_code=502, code="invalid_upstream_response")
            try:
                self._validate_image_data(image_data)
                stored = self._storage.save(image_data, str(body.get("base_url") or "") or None)
            except Exception as exc:
                if item.get("url"):
                    error = ImageGenerationError(
                        f"图片归档保存失败：{str(exc)[:500]}",
                        status_code=502,
                        error_type="server_error",
                        code="image_archive_failed",
                    )
                    setattr(
                        error,
                        "pending_archive",
                        [{"url": str(item["url"]), "revised_prompt": str(item.get("revised_prompt") or "")}],
                    )
                    raise error from exc
                raise
            result: dict[str, object] = {"url": stored.url}
            if item.get("revised_prompt"):
                result["revised_prompt"] = str(item["revised_prompt"])
            archived.append(result)
        if not archived:
            raise ImageGenerationError("上游图片响应不包含有效图片", status_code=502, code="invalid_upstream_response")
        return {"created": int(payload.get("created") or time.time()), "data": archived}

    @staticmethod
    def _validate_image_data(image_data: bytes) -> None:
        try:
            with Image.open(BytesIO(image_data)) as image:
                image.verify()
        except Exception as exc:
            raise ImageGenerationError("上游返回的数据不是有效图片", status_code=502, code="invalid_upstream_response") from exc

    @staticmethod
    def _response_models(response: requests.Response) -> list[str]:
        try:
            payload = response.json()
        except ValueError:
            return []
        items = payload.get("data") if isinstance(payload, dict) else []
        return [str(item.get("id") or "").strip() for item in items if isinstance(item, dict) and str(item.get("id") or "").strip()]

    @staticmethod
    def _safe_error(response: requests.Response) -> str:
        try:
            payload = response.json()
            if isinstance(payload, dict):
                error = payload.get("error")
                if isinstance(error, dict):
                    message = str(error.get("message") or "").strip()
                    if message:
                        return message[:500]
                if isinstance(error, str) and error.strip():
                    return error.strip()[:500]
        except ValueError:
            pass
        return f"Image upstream returned HTTP {response.status_code}"

    @staticmethod
    def _attempt(channel: dict[str, object], operation: str, status: int, duration_ms: int, outcome: str, error: str = "") -> dict[str, object]:
        result: dict[str, object] = {
            "channel_id": str(channel.get("id") or ""),
            "channel_name": str(channel.get("name") or ""),
            "operation": operation,
            "status": status,
            "duration_ms": duration_ms,
            "outcome": outcome,
        }
        if error:
            result["error"] = error[:500]
        return result

    def _record_success(self, channel: dict[str, object]) -> None:
        self._circuits.pop(str(channel.get("id") or ""), None)
        self._persist_runtime_state()

    def _record_test(self, channel: dict[str, object], result: dict[str, object]) -> None:
        channel_id = str(channel.get("id") or "").strip()
        if channel_id:
            self._tests[channel_id] = TestState(result=dict(result), tested_at=time.time())
            self._persist_runtime_state()

    def _record_failure(self, channel: dict[str, object], error: str) -> None:
        channel_id = str(channel.get("id") or "")
        state = self._circuits.setdefault(channel_id, CircuitState())
        state.failures += 1
        state.last_error = error[:500]
        threshold = int(channel.get("failure_threshold") or 3)
        was_open = state.opened_until > time.time()
        if state.failures >= threshold:
            state.opened_until = time.time() + int(channel.get("cooldown_secs") or 120)
            if not was_open:
                self._notify_circuit_open(channel, state)
        self._persist_runtime_state()

    def _admit(self, channel: dict[str, object]) -> tuple[bool, str]:
        channel_id = str(channel.get("id") or "")
        now = time.time()
        with self._lock:
            timestamps = [item for item in self._request_times.get(channel_id, []) if item > now - 60]
            self._request_times[channel_id] = timestamps
            if len(timestamps) >= int(channel.get("requests_per_minute") or 60):
                return False, "skipped_rate_limit"
            if self._inflight.get(channel_id, 0) >= int(channel.get("max_concurrency") or 3):
                return False, "skipped_concurrency"
            timestamps.append(now)
            self._inflight[channel_id] = self._inflight.get(channel_id, 0) + 1
            return True, ""

    def _release(self, channel: dict[str, object]) -> None:
        channel_id = str(channel.get("id") or "")
        with self._lock:
            current = self._inflight.get(channel_id, 0)
            if current <= 1:
                self._inflight.pop(channel_id, None)
            else:
                self._inflight[channel_id] = current - 1

    def _restore_runtime_state(self, state: dict[str, object]) -> None:
        channels = state.get("channels") if isinstance(state, dict) else None
        if not isinstance(channels, dict):
            return
        for channel_id, value in channels.items():
            if not isinstance(value, dict):
                continue
            self._circuits[str(channel_id)] = CircuitState(
                failures=max(0, int(value.get("failures") or 0)),
                opened_until=max(0, float(value.get("opened_until") or 0)),
                last_error=str(value.get("last_error") or "")[:500],
            )
            last_test = value.get("last_test")
            if isinstance(last_test, dict):
                self._tests[str(channel_id)] = TestState(dict(last_test), float(value.get("last_tested_at") or 0))

    def _persist_runtime_state(self) -> None:
        if self._runtime_state_saver is None:
            return
        channel_ids = {str(channel.get("id") or "") for channel in self._channels()}
        state: dict[str, dict[str, object]] = {}
        for channel_id in channel_ids:
            if not channel_id:
                continue
            circuit = self._circuits.get(channel_id, CircuitState())
            test = self._tests.get(channel_id)
            state[channel_id] = {
                "failures": circuit.failures,
                "opened_until": circuit.opened_until,
                "last_error": circuit.last_error,
                "last_test": dict(test.result) if test else None,
                "last_tested_at": test.tested_at if test else None,
            }
        try:
            self._runtime_state_saver({"channels": state})
        except Exception:
            pass

    def _notify_circuit_open(self, channel: dict[str, object], state: CircuitState) -> None:
        webhook_url = str(self._settings().get("alert_webhook_url") or "").strip()
        if not webhook_url:
            return
        payload = {"event": "image_upstream_circuit_open", "channel_id": str(channel.get("id") or ""), "channel_name": str(channel.get("name") or ""), "failure_count": state.failures, "opened_until": int(state.opened_until)}
        threading.Thread(target=self._send_alert, args=(webhook_url, payload), daemon=True).start()

    def _send_alert(self, webhook_url: str, payload: dict[str, object]) -> None:
        try:
            self._requester("POST", webhook_url, json=payload, timeout=5)
        except Exception:
            pass


image_upstream_service = ImageUpstreamService()


def attach_upstream_attempts_to_stream(items, attempts: object, selected: object = ""):
    """Keep routing metadata available to call logging without exposing it to clients."""
    for item in items:
        if isinstance(item, dict) and isinstance(attempts, list):
            item = dict(item)
            item["_image_upstream_attempts"] = attempts
            if selected:
                item["_image_upstream_selected"] = str(selected)
        yield item
