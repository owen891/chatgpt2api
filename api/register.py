from __future__ import annotations

import asyncio
import json
import secrets
import threading
import time

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.support import require_admin
from services.register_service import register_service


_EVENT_TICKET_TTL_SECONDS = 60
_event_tickets: dict[str, float] = {}
_event_ticket_lock = threading.Lock()


def _issue_event_ticket() -> str:
    now = time.monotonic()
    ticket = secrets.token_urlsafe(32)
    with _event_ticket_lock:
        expired = [key for key, expires_at in _event_tickets.items() if expires_at <= now]
        for key in expired:
            _event_tickets.pop(key, None)
        _event_tickets[ticket] = now + _EVENT_TICKET_TTL_SECONDS
    return ticket


def _consume_event_ticket(ticket: str) -> bool:
    now = time.monotonic()
    with _event_ticket_lock:
        expires_at = _event_tickets.pop(str(ticket or ""), None)
    return expires_at is not None and expires_at > now


class RegisterConfigRequest(BaseModel):
    mail: dict | None = None
    proxy: str | None = None
    total: int | None = None
    threads: int | None = None
    mode: str | None = None
    target_quota: int | None = None
    trigger_quota: int | None = None
    target_available: int | None = None
    trigger_available: int | None = None
    expected_quota_per_account: int | None = None
    check_interval: int | None = None
    max_attempts: int | None = None
    max_consecutive_failures: int | None = None
    max_runtime_minutes: int | None = None
    retry_cooldown_seconds: int | None = None
    rate_limit_cooldown_seconds: int | None = None
    alert_webhook_url: str | None = None


class OutlookPoolResetRequest(BaseModel):
    scope: str | None = None


class GptMailStatusRequest(BaseModel):
    provider: dict | None = None
    force: bool | None = None


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/register")
    async def get_register_config(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"register": register_service.get()}

    @router.post("/api/register")
    async def update_register_config(body: RegisterConfigRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"register": register_service.update(body.model_dump(exclude_none=True))}

    @router.post("/api/register/start")
    async def start_register(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            return {"register": register_service.start()}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.post("/api/register/stop")
    async def stop_register(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"register": register_service.stop()}

    @router.post("/api/register/reset")
    async def reset_register(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"register": register_service.reset()}

    @router.post("/api/register/check")
    async def check_register_pool(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"register": register_service.check_now()}

    @router.post("/api/register/outlook-pool/reset")
    async def reset_outlook_pool(body: OutlookPoolResetRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"register": register_service.reset_outlook_pool(body.scope or "all")}

    @router.post("/api/register/gptmail/status")
    async def get_gptmail_status(body: GptMailStatusRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            return {"status": register_service.gptmail_status(body.provider, force=bool(body.force))}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/register/gptmail/refresh-key")
    async def refresh_gptmail_public_key(body: GptMailStatusRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            return {"status": register_service.refresh_gptmail_public_key(body.provider, force=body.force is not False)}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/register/events/ticket")
    async def create_register_event_ticket(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"ticket": _issue_event_ticket(), "expires_in": _EVENT_TICKET_TTL_SECONDS}

    @router.get("/api/register/events")
    async def register_events(ticket: str = ""):
        if not _consume_event_ticket(ticket):
            raise HTTPException(status_code=401, detail={"error": "event ticket invalid or expired"})

        async def stream():
            last = ""
            while True:
                payload = json.dumps(register_service.get(), ensure_ascii=False)
                if payload != last:
                    last = payload
                    yield f"data: {payload}\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(stream(), media_type="text/event-stream")

    return router
