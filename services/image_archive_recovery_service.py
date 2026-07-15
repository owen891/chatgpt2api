from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from services.config import DATA_DIR, config
from services.image_upstream_service import image_upstream_service


RECOVERY_FILE = DATA_DIR / "image_archive_recoveries.json"
TERMINAL_STATUSES = {"success", "error"}


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _clean(value: object) -> str:
    return str(value or "").strip()


def _owner_id(identity: dict[str, object]) -> str:
    return _clean(identity.get("id")) or "anonymous"


def _normalize_pending(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        url = _clean(item.get("url"))
        if not url:
            continue
        result.append({
            "url": url,
            "revised_prompt": _clean(item.get("revised_prompt")),
            "channel_id": _clean(item.get("channel_id")),
            "channel_name": _clean(item.get("channel_name")),
            "operation": _clean(item.get("operation")),
            "model": _clean(item.get("model")),
            "base_url": _clean(item.get("base_url")),
        })
    return result


class ImageArchiveRecoveryService:
    def __init__(self, path: Path = RECOVERY_FILE) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._items: dict[str, dict[str, object]] = {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._items = self._load_locked()
            if self._cleanup_locked():
                self._save_locked()

    def create(
        self,
        identity: dict[str, object],
        *,
        operation: str,
        model: str,
        pending: list[dict[str, object]],
        error: str,
    ) -> dict[str, object]:
        normalized = _normalize_pending(pending)
        if not normalized:
            raise ValueError("pending archive is empty")
        now = _now_iso()
        item = {
            "id": uuid4().hex,
            "owner_id": _owner_id(identity),
            "status": "error",
            "operation": _clean(operation) or "generation",
            "model": _clean(model) or "gpt-image-2",
            "pending": normalized,
            "error": _clean(error) or "image archive failed",
            "created_at": now,
            "updated_at": now,
            "created_ts": time.time(),
        }
        with self._lock:
            self._items[str(item["id"])] = item
            self._cleanup_locked()
            self._save_locked()
        return self._public(item)

    def get(self, identity: dict[str, object], recovery_id: str, *, include_urls: bool = False) -> dict[str, object]:
        with self._lock:
            item = self._owned_item_locked(identity, recovery_id)
            return self._public(item, include_urls=include_urls)

    def retry(self, identity: dict[str, object], recovery_id: str) -> dict[str, object]:
        with self._lock:
            item = self._owned_item_locked(identity, recovery_id)
            if item.get("status") == "running":
                return self._public(item)
            pending = _normalize_pending(item.get("pending"))
            if not pending:
                raise ValueError("recovery record has no pending archive")
            item["status"] = "running"
            item["error"] = ""
            item["updated_at"] = _now_iso()
            self._save_locked()
            snapshot = self._public(item)
        thread = threading.Thread(
            target=self._run_retry,
            args=(str(recovery_id), pending),
            name=f"image-archive-recovery-{str(recovery_id)[:16]}",
            daemon=True,
        )
        thread.start()
        return snapshot

    def _run_retry(self, recovery_id: str, pending: list[dict[str, object]]) -> None:
        try:
            result = image_upstream_service.archive_pending(pending)
        except Exception as exc:
            with self._lock:
                item = self._items.get(recovery_id)
                if item is None:
                    return
                item["status"] = "error"
                item["error"] = _clean(str(exc)) or "image archive failed"
                item["updated_at"] = _now_iso()
                self._save_locked()
            return
        with self._lock:
            item = self._items.get(recovery_id)
            if item is None:
                return
            item["status"] = "success"
            item["data"] = result.get("data") or []
            item["error"] = ""
            item["updated_at"] = _now_iso()
            self._save_locked()

    def _owned_item_locked(self, identity: dict[str, object], recovery_id: str) -> dict[str, object]:
        item = self._items.get(_clean(recovery_id))
        if item is None or item.get("owner_id") != _owner_id(identity):
            raise ValueError("recovery record not found")
        return item

    @staticmethod
    def _public(item: dict[str, object], *, include_urls: bool = False) -> dict[str, object]:
        pending = _normalize_pending(item.get("pending"))
        result: dict[str, object] = {
            "id": item.get("id"),
            "status": item.get("status"),
            "operation": item.get("operation"),
            "model": item.get("model"),
            "count": len(pending),
            "error": item.get("error") or None,
            "data": item.get("data") if item.get("status") == "success" else None,
            "created_at": item.get("created_at"),
            "updated_at": item.get("updated_at"),
        }
        if include_urls:
            result["pending_archive"] = pending
        return result

    def _load_locked(self) -> dict[str, dict[str, object]]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        source = raw.get("items") if isinstance(raw, dict) else None
        if not isinstance(source, list):
            return {}
        result: dict[str, dict[str, object]] = {}
        for item in source:
            if not isinstance(item, dict) or not _clean(item.get("id")) or not _clean(item.get("owner_id")):
                continue
            normalized = dict(item)
            normalized["pending"] = _normalize_pending(item.get("pending"))
            result[_clean(item.get("id"))] = normalized
        return result

    def _save_locked(self) -> None:
        items = sorted(self._items.values(), key=lambda item: _clean(item.get("updated_at")), reverse=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    def _cleanup_locked(self) -> bool:
        try:
            retention_days = max(1, int(config.image_retention_days))
        except Exception:
            retention_days = 30
        cutoff = time.time() - retention_days * 86400
        removed: list[str] = []
        for key, item in self._items.items():
            if item.get("status") not in TERMINAL_STATUSES:
                continue
            try:
                created_ts = float(item.get("created_ts") or 0)
            except (TypeError, ValueError):
                created_ts = 0
            if created_ts and created_ts < cutoff:
                removed.append(key)
        for key in removed:
            self._items.pop(key, None)
        return bool(removed)


image_archive_recovery_service = ImageArchiveRecoveryService()
