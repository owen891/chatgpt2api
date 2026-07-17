from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict

from api.support import require_admin, require_identity, resolve_image_base_url
from services.backup_service import BackupError, backup_service
from services.config import config
from services.image_service import (
    compress_images,
    delete_images,
    delete_to_target,
    download_images_zip,
    get_image_download_response,
    get_image_response,
    get_thumbnail_response,
    list_images,
    storage_stats,
)
from services.image_storage_service import ImageStorageError, image_storage_service
from services.image_tags_service import delete_tag, get_all_tags, set_tags
from services.image_upstream_service import image_upstream_service
from services.log_service import log_service
from services.proxy_service import proxy_settings, test_clearance, test_proxy


class SettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")


class ProxyTestRequest(BaseModel):
    url: str = ""


class ClearanceTestRequest(BaseModel):
    target_url: str = "https://chatgpt.com"


class ProxyGroupRequest(BaseModel):
    id: str = ""
    name: str = ""
    strategy: str = "request_random"
    rotation_interval_minutes: float = 0
    enabled: bool = True
    notes: str = ""
    nodes: list[dict[str, Any]] = []
    create_only: bool = False


class ProxyGroupTestRequest(BaseModel):
    id: str = ""
    node_id: str = ""
    url: str = ""


class ImageDeleteRequest(BaseModel):
    paths: list[str] = []
    start_date: str = ""
    end_date: str = ""
    all_matching: bool = False


class ImageDownloadRequest(BaseModel):
    paths: list[str]


class ImageTagsRequest(BaseModel):
    path: str
    tags: list[str]


class LogDeleteRequest(BaseModel):
    ids: list[str] = []


class BackupDeleteRequest(BaseModel):
    key: str = ""


class ImageUpstreamRequest(BaseModel):
    channel: dict[str, object]


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _slug_id(value: object) -> str:
    raw = _clean_text(value).lower()
    chars: list[str] = []
    for char in raw:
        if char.isalnum() or char in {"-", "_"}:
            chars.append(char)
        elif char.isspace():
            chars.append("-")
    return "".join(chars).strip("-_")


def _proxy_group_id(value: object) -> str:
    raw = _clean_text(value)
    if raw.lower().startswith("group:"):
        raw = raw.split(":", 1)[1]
    return _slug_id(raw)


def _coerce_proxy_group_rotation_minutes(value: object) -> float:
    try:
        minutes = float(value)
    except (OverflowError, TypeError, ValueError):
        minutes = 0.0
    return max(0.0, min(minutes, 1440.0))


def _coerce_proxy_node_image_concurrency_limit(value: object, *, default: int = 30) -> int:
    if value is None or value == "":
        return default
    try:
        limit = int(float(value))
    except (OverflowError, TypeError, ValueError):
        return default
    return max(0, min(limit, 10000))


def _config_dict_list(key: str) -> list[dict[str, Any]]:
    getter = getattr(config, "get_proxy_groups_settings", None)
    if key == "proxy_groups" and callable(getter):
        raw = getter()
    else:
        raw = config.get().get(key)
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, dict)]


def _proxy_groups_payload() -> dict[str, Any]:
    return {"groups": _config_dict_list("proxy_groups")}


def _upsert_proxy_group(body: ProxyGroupRequest) -> dict[str, Any]:
    group_id = _proxy_group_id(body.id or body.name)
    if not group_id:
        raise ValueError("proxy group id is required")
    groups = _config_dict_list("proxy_groups")
    exists = any(_proxy_group_id(group.get("id")) == group_id for group in groups)
    if body.create_only and exists:
        raise ValueError("proxy group already exists")

    nodes: list[dict[str, Any]] = []
    seen_node_ids: set[str] = set()
    for index, raw_node in enumerate(body.nodes):
        if not isinstance(raw_node, dict):
            continue
        node_id = _slug_id(raw_node.get("id") or raw_node.get("name") or f"node-{index + 1}") or f"node-{index + 1}"
        if node_id in seen_node_ids:
            continue
        seen_node_ids.add(node_id)
        nodes.append({
            "id": node_id,
            "name": _clean_text(raw_node.get("name")) or node_id,
            "url": _clean_text(raw_node.get("url")),
            "enabled": bool(raw_node.get("enabled", True)),
            "image_concurrency_limit": _coerce_proxy_node_image_concurrency_limit(
                raw_node.get("image_concurrency_limit")
                if raw_node.get("image_concurrency_limit") is not None
                else raw_node.get("image_concurrency"),
            ),
        })

    item = {
        "id": group_id,
        "name": body.name or group_id,
        "strategy": body.strategy or "request_random",
        "rotation_interval_minutes": _coerce_proxy_group_rotation_minutes(body.rotation_interval_minutes),
        "enabled": body.enabled,
        "notes": body.notes,
        "nodes": nodes,
    }
    next_groups = [group for group in groups if _proxy_group_id(group.get("id")) != group_id]
    next_groups.append(item)
    updated = config.update({"proxy_groups": next_groups})
    groups = [dict(group) for group in updated.get("proxy_groups", []) if isinstance(group, dict)]
    return {"group": item, "groups": groups}


def create_router(app_version: str) -> APIRouter:
    router = APIRouter()

    @router.post("/auth/login")
    async def login(authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        return {
            "ok": True,
            "version": app_version,
            "role": identity.get("role"),
            "subject_id": identity.get("id"),
            "name": identity.get("name"),
        }

    @router.get("/version")
    async def get_version():
        return {"version": app_version}

    @router.get("/api/settings")
    async def get_settings(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"config": config.get()}

    @router.get("/api/third-party-apps")
    async def get_third_party_apps(authorization: str | None = Header(default=None)):
        require_identity(authorization)
        return {"third_party_apps": config.get_third_party_apps_settings()}

    @router.post("/api/settings")
    async def save_settings(body: SettingsUpdateRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            return {"config": config.update(body.model_dump(mode="python"))}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.post("/api/image-upstreams/test")
    async def test_image_upstream_endpoint(body: ImageUpstreamRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"result": await run_in_threadpool(image_upstream_service.test_channel, body.channel)}

    @router.post("/api/image-upstreams/models")
    async def fetch_image_upstream_models_endpoint(body: ImageUpstreamRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"result": await run_in_threadpool(image_upstream_service.fetch_models, body.channel)}

    @router.get("/api/image-upstreams/status")
    async def get_image_upstream_status_endpoint(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return await run_in_threadpool(image_upstream_service.statuses)

    @router.get("/api/images")
    async def get_images(request: Request, start_date: str = "", end_date: str = "", authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return list_images(resolve_image_base_url(request), start_date=start_date.strip(), end_date=end_date.strip())

    @router.get("/images/{image_path:path}", include_in_schema=False)
    @router.head("/images/{image_path:path}", include_in_schema=False)
    async def get_image(image_path: str):
        return get_image_response(image_path)

    @router.get("/image-thumbnails/{image_path:path}", include_in_schema=False)
    @router.head("/image-thumbnails/{image_path:path}", include_in_schema=False)
    async def get_image_thumbnail(image_path: str):
        return get_thumbnail_response(image_path)

    @router.post("/api/images/delete")
    async def delete_images_endpoint(body: ImageDeleteRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return delete_images(body.paths, start_date=body.start_date.strip(), end_date=body.end_date.strip(), all_matching=body.all_matching)

    @router.post("/api/images/download")
    async def download_images_endpoint(body: ImageDownloadRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        buf = download_images_zip(body.paths)
        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="images.zip"'},
        )

    @router.get("/api/images/download/{image_path:path}")
    async def download_single_image_endpoint(image_path: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return get_image_download_response(image_path)

    @router.get("/api/logs")
    async def get_logs(type: str = "", start_date: str = "", end_date: str = "", authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"items": log_service.list(type=type.strip(), start_date=start_date.strip(), end_date=end_date.strip())}

    @router.post("/api/logs/delete")
    async def delete_logs(body: LogDeleteRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return log_service.delete(body.ids)

    @router.post("/api/proxy/test")
    async def test_proxy_endpoint(body: ProxyTestRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"result": await run_in_threadpool(test_proxy, (body.url or "").strip())}

    @router.get("/api/proxy/runtime")
    async def get_proxy_runtime_endpoint(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {
            "runtime": config.get_public_proxy_runtime_settings(),
            "status": proxy_settings.get_runtime_status(),
        }

    @router.post("/api/proxy/runtime")
    async def save_proxy_runtime_endpoint(body: SettingsUpdateRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            config.update({"proxy_runtime": body.model_dump(mode="python")})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {
            "runtime": config.get_public_proxy_runtime_settings(),
            "status": proxy_settings.get_runtime_status(),
        }

    @router.get("/api/proxy/groups")
    async def get_proxy_groups_endpoint(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return _proxy_groups_payload()

    @router.post("/api/proxy/groups")
    async def save_proxy_group(body: ProxyGroupRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            return _upsert_proxy_group(body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.delete("/api/proxy/groups/{group_id}")
    async def delete_proxy_group(group_id: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        normalized = _proxy_group_id(group_id)
        groups = _config_dict_list("proxy_groups")
        next_groups = [group for group in groups if _proxy_group_id(group.get("id")) != normalized]
        if len(next_groups) == len(groups):
            raise HTTPException(status_code=404, detail={"error": "proxy group not found"})
        updated = config.update({"proxy_groups": next_groups})
        return {"deleted": normalized, "groups": updated.get("proxy_groups", [])}

    @router.post("/api/proxy/groups/test")
    async def test_proxy_group_endpoint(body: ProxyGroupTestRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        if _clean_text(body.url):
            return {"result": await run_in_threadpool(test_proxy, _clean_text(body.url))}

        group_id = _proxy_group_id(body.id)
        if not group_id:
            raise HTTPException(status_code=400, detail={"error": "proxy group id or url is required"})
        group = next((item for item in _config_dict_list("proxy_groups") if _proxy_group_id(item.get("id")) == group_id), None)
        if group is None:
            raise HTTPException(status_code=404, detail={"error": "proxy group not found"})

        node_id = _slug_id(body.node_id)
        nodes = [dict(node) for node in group.get("nodes", []) if isinstance(node, dict)]
        if node_id:
            node = next((item for item in nodes if _slug_id(item.get("id") or item.get("name")) == node_id), None)
        else:
            node = next((item for item in nodes if item.get("enabled", True) is not False and _clean_text(item.get("url"))), None)
        if node is None:
            raise HTTPException(status_code=404, detail={"error": "proxy group node not found"})

        proxy_url = _clean_text(node.get("url"))
        if not proxy_url:
            raise HTTPException(status_code=400, detail={"error": "proxy group node url is required"})
        return {
            "result": await run_in_threadpool(test_proxy, proxy_url),
            "group": group,
            "node": node,
        }

    @router.post("/api/proxy/clearance/test")
    async def test_proxy_clearance_endpoint(body: ClearanceTestRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"result": await run_in_threadpool(test_clearance, body.target_url)}

    @router.get("/api/storage/info")
    async def get_storage_info(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        storage = config.get_storage_backend()
        return {
            "backend": storage.get_backend_info(),
            "health": storage.health_check(),
        }

    @router.post("/api/backup/test")
    async def test_backup_connection(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            return {"result": await run_in_threadpool(backup_service.test_connection)}
        except BackupError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.post("/api/image-storage/test")
    async def test_image_storage_endpoint(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"result": await run_in_threadpool(image_storage_service.test_webdav)}

    @router.post("/api/image-storage/sync")
    async def sync_image_storage_endpoint(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            return {"result": await run_in_threadpool(image_storage_service.sync_all)}
        except ImageStorageError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.get("/api/backups")
    async def get_backups(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            return {
                "items": await run_in_threadpool(backup_service.list_backups),
                "state": backup_service.get_status(),
                "settings": backup_service.get_settings(),
            }
        except BackupError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.post("/api/backups/run")
    async def run_backup_endpoint(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            return {"result": await run_in_threadpool(backup_service.run_backup)}
        except BackupError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.post("/api/backups/delete")
    async def delete_backup_endpoint(body: BackupDeleteRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            await run_in_threadpool(backup_service.delete_backup, body.key)
            return {"ok": True}
        except BackupError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.get("/api/backups/detail")
    async def get_backup_detail(key: str = "", authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            return {"item": await run_in_threadpool(backup_service.get_backup_detail, key)}
        except BackupError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.get("/api/backups/download")
    async def download_backup_endpoint(key: str = "", authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            item = await run_in_threadpool(backup_service.download_backup, key)
        except BackupError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        filename = str(item.get("name") or "backup.bin")
        quoted = quote(filename)
        headers = {
            "Content-Disposition": f"attachment; filename*=UTF-8''{quoted}",
            "Content-Length": str(int(item.get("size") or 0)),
        }
        return Response(
            content=bytes(item.get("payload") or b""),
            media_type=str(item.get("content_type") or "application/octet-stream"),
            headers=headers,
        )

    @router.get("/api/images/tags")
    async def list_image_tags(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"tags": get_all_tags()}

    @router.post("/api/images/tags")
    async def update_image_tags(body: ImageTagsRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        rel = body.path.strip().lstrip("/")
        if not rel:
            raise HTTPException(status_code=400, detail={"error": "path is required"})
        tags = set_tags(rel, body.tags)
        return {"ok": True, "tags": tags}

    @router.delete("/api/images/tags/{tag}")
    async def delete_image_tag(tag: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        count = delete_tag(tag)
        return {"ok": True, "removed_from": count}

    @router.get("/api/images/storage")
    async def get_image_storage(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return storage_stats()

    @router.post("/api/images/storage/compress")
    async def compress_all_images(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return await run_in_threadpool(compress_images)

    @router.post("/api/images/storage/cleanup-to-target")
    async def cleanup_to_target(
        target_free_mb: int = 500,
        dry_run: bool = False,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        return await run_in_threadpool(delete_to_target, target_free_mb, dry_run)

    @router.get("/health", response_model=None)
    async def health_dashboard(format: str = Query(default="html")):
        from services.account_service import account_service as acct_svc

        stats = acct_svc.get_stats()
        storage = config.get_storage_backend()
        storage_health = storage.health_check()
        healthy = stats["active"] > 0

        stats_json = {
            "status": "ok" if healthy else "degraded",
            "healthy": healthy,
            "version": app_version,
            "storage": {"backend": storage.get_backend_info(), "health": storage_health},
            "proxy_runtime": proxy_settings.get_runtime_status(),
            "accounts": stats,
        }
        if format == "json":
            return stats_json
        return HTMLResponse(f"""<!DOCTYPE html>
<html lang="zh">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>鍙锋睜鍋ュ悍鐩戞帶 - chatgpt2api</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:system-ui,-apple-system,sans-serif;background:#0f1117;color:#e2e8f0;min-height:100vh}}
.header{{background:#1a1d27;border-bottom:1px solid #2a2d3a;padding:16px 24px;display:flex;justify-content:space-between;align-items:center}}
.header h1{{font-size:20px}}
.status-dot{{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:8px}}
.status-ok{{background:#22c55e;box-shadow:0 0 8px #22c55e88}}
.status-degraded{{background:#f59e0b;box-shadow:0 0 8px #f59e0b88}}
.container{{max-width:960px;margin:0 auto;padding:24px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:24px}}
.card{{background:#1a1d27;border:1px solid #2a2d3a;border-radius:10px;padding:16px}}
.card .value{{font-size:28px;font-weight:700;margin:4px 0}}
.card .label{{font-size:13px;color:#94a3b8}}
.green{{color:#22c55e}}.yellow{{color:#f59e0b}}.red{{color:#ef4444}}.blue{{color:#6c63ff}}
table{{width:100%;border-collapse:collapse;background:#1a1d27;border:1px solid #2a2d3a;border-radius:10px;overflow:hidden}}
th{{background:#242836;font-weight:600;text-align:left;padding:10px 12px;font-size:12px;color:#94a3b8;text-transform:uppercase}}
td{{padding:8px 12px;border-top:1px solid #2a2d3a;font-size:14px}}tr:hover td{{background:rgba(108,99,255,.05)}}
.api-url{{font-family:monospace;font-size:12px;color:#6c63ff}}
.refresh{{font-size:12px;color:#64748b;text-align:center;margin-top:24px}}
</style>
<meta http-equiv="refresh" content="30">
</head>
<body>
<div class="header">
<h1><span class="status-dot {'status-ok' if healthy else 'status-degraded'}"></span>鍙锋睜鍋ュ悍鐩戞帶</h1>
<div style="font-size:13px;color:#94a3b8">v{app_version} 路 30s 鑷姩鍒锋柊</div>
</div>
<div class="container">
<div class="cards">
<div class="card"><div class="label">鍙锋睜鐘舵€?</div><div class="value {'green' if healthy else 'yellow'}">{'姝ｅ父' if healthy else '寮傚父'}</div></div>
<div class="card"><div class="label">褰撳墠璐﹀彿</div><div class="value blue">{stats['total']}</div></div>
<div class="card"><div class="label">绱鍏ュ簱</div><div class="value">{stats['cumulative_total']}</div></div>
<div class="card"><div class="label">鍙敤璐﹀彿</div><div class="value green">{stats['active']}</div></div>
<div class="card"><div class="label">鍓╀綑棰濆害</div><div class="value">{stats['total_quota']}</div></div>
<div class="card"><div class="label">闄愭祦</div><div class="value yellow">{stats['limited']}</div></div>
<div class="card"><div class="label">寮傚父</div><div class="value red">{stats['abnormal']}</div></div>
<div class="card"><div class="label">绂佺敤</div><div class="value">{stats['disabled']}</div></div>
<div class="card"><div class="label">鎴愬姛/澶辫触</div><div class="value">{stats['total_success']}<span style="font-size:18px;color:#94a3b8">/</span><span class="red">{stats['total_fail']}</span></div></div>
</div>
<h2 style="margin-bottom:12px;font-size:16px">璐﹀彿绫诲瀷鍒嗗竷</h2>
<table>
<tr><th>绫诲瀷</th><th>鏁伴噺</th></tr>
{''.join(f'<tr><td>{t}</td><td>{c}</td></tr>' for t,c in sorted(stats['by_type'].items()))}
</table>
<div class="refresh">JSON: <span class="api-url">/health?format=json</span></div>
</div></body></html>""")

    return router
