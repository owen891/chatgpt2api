from __future__ import annotations

import json
import re
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from services.account_service import account_service
from services.config import DATA_DIR
from services.json_file import read_json_object, write_json_file
from services.proxy_service import proxy_settings, test_proxy
from services.register import mail_provider, openai_register


REGISTER_FILE = DATA_DIR / "register.json"

_URL_RE = re.compile(r"https?://[^\s<>\"']+")
_EMAIL_RE = re.compile(r"(?i)\b([a-z0-9._%+-]{1,64})@([a-z0-9.-]+\.[a-z]{2,})\b")


def _redact_register_log(value: object) -> str:
    text = str(value or "")

    def redact_url(match: re.Match[str]) -> str:
        raw = match.group(0)
        core = raw.rstrip(".,;:!?)]}")
        trailing = raw[len(core):]
        try:
            parsed = urlsplit(core)
        except ValueError:
            return f"[url redacted]{trailing}"
        base = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        redacted = f"{base}?[query redacted]" if parsed.query else base
        return f"{redacted}{trailing}"

    text = _URL_RE.sub(redact_url, text)
    text = _EMAIL_RE.sub(lambda match: f"{match.group(1)[:2]}***@{match.group(2)}", text)
    text = re.sub(
        r"(?i)\b(access_token|refresh_token|id_token|state|nonce|code_verifier)=([^\s,&]+)",
        r"\1=[redacted]",
        text,
    )
    text = re.sub(r"(?is)\bbody=.*$", "body=[redacted]", text)
    return text[:1200]


def _serialize_outlook_pool(credentials: list[dict]) -> str:
    return "\n".join(
        f'{c["email"]}----{c.get("password", "")}----{c["client_id"]}----{c["refresh_token"]}' for c in credentials
    )


def _merge_outlook_pool(old_text: str, new_text: str) -> str:
    """合并已存邮箱池与新导入文本，按邮箱去重，新导入的同名邮箱覆盖旧凭据。"""
    merged: dict[str, dict] = {}
    for credential in mail_provider.parse_outlook_credentials(old_text or ""):
        merged[credential["email"].strip().lower()] = credential
    for credential in mail_provider.parse_outlook_credentials(new_text or ""):
        merged[credential["email"].strip().lower()] = credential
    return _serialize_outlook_pool(list(merged.values()))


def _outlook_credential_changed(old: dict | None, new: dict) -> bool:
    if not old:
        return False
    for key in ("password", "client_id", "refresh_token"):
        if str(old.get(key) or "") != str(new.get(key) or ""):
            return True
    return False


def _safe_bool(value: object, fallback: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return fallback


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _provider_id(provider: dict) -> str:
    return str(provider.get("id") or provider.get("provider_id") or "").strip()


def _ensure_provider_id(provider: dict) -> str:
    provider_id = _provider_id(provider)
    if provider_id:
        provider["id"] = provider_id
        provider.pop("provider_id", None)
        return provider_id
    provider_id = f"provider-{uuid.uuid4().hex[:12]}"
    provider["id"] = provider_id
    return provider_id


def _provider_has_value(value: object) -> bool:
    if isinstance(value, list):
        return any(str(item or "").strip() for item in value)
    return bool(str(value or "").strip())


def _provider_missing(provider: dict) -> list[str]:
    """启动前校验邮箱渠道，避免线程启动后才因配置错误失败。"""
    provider_type = str(provider.get("type") or "").strip()
    missing: list[str] = []

    def required(key: str, label: str) -> None:
        if not _provider_has_value(provider.get(key)):
            missing.append(label)

    if provider_type == "cloudmail_gen":
        required("api_base", "CloudMail URL")
        required("admin_email", "管理员邮箱")
        required("admin_password", "管理员密码")
        required("domain", "邮箱域名")
    elif provider_type == "cloudflare_temp_email":
        required("api_base", "API Base")
        required("admin_password", "管理员密码")
        required("domain", "域名")
    elif provider_type == "moemail":
        required("api_base", "API Base")
        required("api_key", "API Key")
        required("domain", "域名")
    elif provider_type == "inbucket":
        required("api_base", "API Base")
        required("domain", "基础域名")
    elif provider_type == "duckmail":
        required("api_key", "API Key")
    elif provider_type == "gptmail":
        if str(provider.get("key_mode") or "public") == "custom":
            required("api_key", "API Key")
        if _safe_bool(provider.get("local_compose")):
            required("default_domain", "默认域名")
    elif provider_type == "donemail":
        required("api_base", "DoneMail URL")
        required("admin_key", "Admin Key")
        required("domain", "域名")
    elif provider_type == "yyds_mail":
        required("api_key", "API Key")
    elif provider_type == "ddg_mail":
        required("api_base", "CF API Base")
        required("ddg_token", "DDG Token")
        required("cf_inbox_jwt", "CF Inbox JWT")
    elif provider_type == "outlook_token":
        credentials = mail_provider.parse_outlook_credentials(str(provider.get("mailboxes") or ""))
        if not credentials and int(provider.get("mailboxes_count") or 0) <= 0:
            missing.append("Microsoft 邮箱凭据池")
    return missing


def _default_config() -> dict:
    return {**openai_register.config, "mode": "total", "target_quota": 100, "trigger_quota": 50, "target_available": 10, "trigger_available": 5, "expected_quota_per_account": 25, "check_interval": 5, "max_attempts": 100, "max_consecutive_failures": 10, "max_runtime_minutes": 60, "retry_cooldown_seconds": 300, "rate_limit_cooldown_seconds": 900, "alert_webhook_url": "", "enabled": False, "history": [], "stats": {"success": 0, "fail": 0, "done": 0, "running": 0, "threads": openai_register.config["threads"], "elapsed_seconds": 0, "avg_seconds": 0, "success_rate": 0, "current_quota": 0, "current_available": 0, "phase": "stopped", "stop_reason": "", "last_check_at": "", "next_check_at": "", "channel_health": {}}}


def _normalize(raw: dict) -> dict:
    cfg = _default_config()
    cfg.update({k: v for k, v in raw.items() if k not in {"stats", "logs"}})
    cfg["total"] = max(1, int(cfg.get("total") or 1))
    cfg["threads"] = max(1, int(cfg.get("threads") or 1))
    cfg["mode"] = str(cfg.get("mode") or "total").strip() if str(cfg.get("mode") or "total").strip() in {"total", "quota", "available"} else "total"
    cfg["target_quota"] = max(1, int(cfg.get("target_quota") or 1))
    cfg["trigger_quota"] = max(0, min(cfg["target_quota"] - 1, int(cfg.get("trigger_quota") if cfg.get("trigger_quota") is not None else cfg["target_quota"] // 2)))
    cfg["target_available"] = max(1, int(cfg.get("target_available") or 1))
    cfg["trigger_available"] = max(0, min(cfg["target_available"] - 1, int(cfg.get("trigger_available") if cfg.get("trigger_available") is not None else cfg["target_available"] // 2)))
    cfg["expected_quota_per_account"] = max(1, int(cfg.get("expected_quota_per_account") or 25))
    cfg["check_interval"] = max(1, int(cfg.get("check_interval") or 5))
    cfg["max_attempts"] = max(1, int(cfg.get("max_attempts") or 100))
    cfg["max_consecutive_failures"] = max(1, int(cfg.get("max_consecutive_failures") or 10))
    cfg["max_runtime_minutes"] = max(1, int(cfg.get("max_runtime_minutes") or 60))
    cfg["retry_cooldown_seconds"] = max(30, int(cfg.get("retry_cooldown_seconds") or 300))
    cfg["rate_limit_cooldown_seconds"] = max(60, int(cfg.get("rate_limit_cooldown_seconds") or 900))
    cfg["alert_webhook_url"] = str(cfg.get("alert_webhook_url") or "").strip()
    cfg["proxy"] = str(cfg.get("proxy") or "").strip()
    default_mail = _default_config()["mail"] if isinstance(_default_config().get("mail"), dict) else {}
    mail = cfg.get("mail") if isinstance(cfg.get("mail"), dict) else {}
    cfg["mail"] = {**default_mail, **mail}
    cfg["mail"]["api_use_register_proxy"] = _safe_bool(cfg["mail"].get("api_use_register_proxy"), True)
    cfg["mail"].pop("proxy", None)
    cfg["enabled"] = bool(cfg.get("enabled"))
    stats = {**_default_config()["stats"], **(raw.get("stats") if isinstance(raw.get("stats"), dict) else {}),
             "threads": cfg["threads"]}
    cfg["stats"] = stats
    history = raw.get("history") if isinstance(raw.get("history"), list) else []
    cfg["history"] = [dict(item) for item in history if isinstance(item, dict)][-50:]
    return cfg


class RegisterService:
    def __init__(self, store_file: Path):
        self._store_file = store_file
        self._lock = threading.RLock()
        self._wake_event = threading.Event()
        self._runner: threading.Thread | None = None
        self._logs: list[dict] = []
        self._last_pool_log_signature: tuple[object, ...] | None = None
        openai_register.register_log_sink = self._append_log
        self._config = self._load()
        if self._config["enabled"]:
            self.start()

    def _load(self) -> dict:
        return _normalize(read_json_object(self._store_file, name="register.json"))

    def _save(self) -> None:
        write_json_file(self._store_file, self._config)

    def get(self) -> dict:
        metrics = self._pool_metrics()
        with self._lock:
            runner_alive = bool(self._runner and self._runner.is_alive())
            # 进程重启或任务线程异常退出后，不能把持久化状态当成运行中。
            if self._config.get("enabled") and not runner_alive:
                self._config["enabled"] = False
                self._config["stats"]["running"] = 0
                self._config["stats"]["phase"] = "stopped"
                self._config["stats"]["next_check_at"] = ""
                self._save()
            elif not self._config.get("enabled") and not runner_alive and self._config["stats"].get("phase") == "stopping":
                self._config["stats"]["running"] = 0
                self._config["stats"]["phase"] = "stopped"
                self._config["stats"]["next_check_at"] = ""
                self._save()
            self._config["stats"].update(metrics)
            snapshot = json.loads(json.dumps({**self._config, "logs": self._logs[-300:]}, ensure_ascii=False))
        self._redact_outlook_pools(snapshot)
        return snapshot

    @staticmethod
    def _mask_email(email: str) -> str:
        local, sep, domain = str(email or "").partition("@")
        if not sep:
            return "***"
        masked = (local[:2] + "***" + local[-1:]) if len(local) > 2 else (local[:1] + "***")
        return f"{masked}@{domain}"

    def _redact_outlook_pools(self, snapshot: dict) -> None:
        """把 outlook_token 邮箱池里的密码/refresh_token 从对外输出中抹掉，仅保留脱敏预览与统计。

        mailboxes 改为只写导入框（输出为空），避免把密码与 refresh_token 通过 GET/SSE 反复广播。
        """
        mail = snapshot.get("mail")
        if not isinstance(mail, dict):
            return
        providers = mail.get("providers")
        if not isinstance(providers, list):
            return
        for index, provider in enumerate(providers):
            if not isinstance(provider, dict) or provider.get("type") != "outlook_token":
                continue
            pool_text = str(provider.get("mailboxes") or "")
            base_credentials = mail_provider.parse_outlook_credentials(pool_text)
            credentials = mail_provider.expand_outlook_aliases(base_credentials, provider)
            provider["mailboxes"] = ""
            provider["mailboxes_count"] = len(credentials)
            provider["mailboxes_base_count"] = len(base_credentials)
            provider["mailboxes_alias_count"] = max(0, len(credentials) - len(base_credentials))
            provider["mailboxes_preview"] = [self._mask_email(c["email"]) for c in credentials]
            provider["mailboxes_stats"] = mail_provider.outlook_token_pool_stats(credentials)
            provider["mailboxes_parse_stats"] = mail_provider.inspect_outlook_credentials(pool_text)

    def _drop_mail_proxy(self) -> None:
        if isinstance(self._config.get("mail"), dict):
            self._config["mail"].pop("proxy", None)

    def _merge_outlook_pools(self, updates: dict) -> None:
        """对 outlook_token provider：把前端新导入的 mailboxes 与已存池按邮箱合并去重。

        前端 mailboxes 是只写导入框，留空表示不改动；填入的新行追加/覆盖已存凭据。
        按数组下标与已存的同类型 provider 对齐。
        """
        mail = updates.get("mail")
        if not isinstance(mail, dict) or not isinstance(mail.get("providers"), list):
            return
        old_mail = self._config.get("mail") if isinstance(self._config.get("mail"), dict) else {}
        old_providers = old_mail.get("providers") if isinstance(old_mail.get("providers"), list) else []
        old_outlook_by_id = {
            _provider_id(provider): provider
            for provider in old_providers
            if isinstance(provider, dict) and provider.get("type") == "outlook_token" and _provider_id(provider)
        }
        old_outlook_by_order = [
            provider
            for provider in old_providers
            if isinstance(provider, dict) and provider.get("type") == "outlook_token"
        ]
        outlook_index = 0
        for index, provider in enumerate(mail["providers"]):
            if not isinstance(provider, dict):
                continue
            _ensure_provider_id(provider)
            if provider.get("type") != "outlook_token":
                continue
            provider_id = _provider_id(provider)
            old = old_outlook_by_id.get(provider_id) or {}
            if not old and index < len(old_providers) and isinstance(old_providers[index], dict) and old_providers[index].get("type") == "outlook_token":
                old = old_providers[index]
            if not old and outlook_index < len(old_outlook_by_order):
                old = old_outlook_by_order[outlook_index]
            outlook_index += 1
            old_text = str(old.get("mailboxes") or "") if old.get("type") == "outlook_token" else ""
            new_text = str(provider.get("mailboxes") or "")
            old_credentials = {
                credential["email"].strip().lower(): credential
                for credential in mail_provider.parse_outlook_credentials(old_text or "")
            }
            new_credentials = mail_provider.parse_outlook_credentials(new_text or "")
            if new_text.strip():
                provider["mailboxes"] = _merge_outlook_pool(old_text, new_text)
                refreshed_credentials = [
                    credential
                    for credential in new_credentials
                    if _outlook_credential_changed(old_credentials.get(credential["email"].strip().lower()), credential)
                ]
                if refreshed_credentials:
                    refreshed_addresses = [
                        item["email"]
                        for credential in refreshed_credentials
                        for item in mail_provider.expand_outlook_aliases([credential], provider)
                    ]
                    mail_provider.clear_outlook_token_states(
                        refreshed_addresses,
                        states=mail_provider.OUTLOOK_REFRESHED_CREDENTIAL_RESET_STATES,
                    )
            elif old_text:
                provider["mailboxes"] = _merge_outlook_pool(old_text, "")
            else:
                provider["mailboxes"] = ""
            for key in ("mailboxes_count", "mailboxes_base_count", "mailboxes_alias_count", "mailboxes_preview", "mailboxes_stats", "mailboxes_parse_stats"):
                provider.pop(key, None)

    def _prune_unused_outlook_pools(self) -> int:
        mail = self._config.get("mail")
        if not isinstance(mail, dict):
            return 0
        providers = mail.get("providers")
        if not isinstance(providers, list):
            return 0
        total_removed = 0
        for provider in providers:
            if not isinstance(provider, dict) or provider.get("type") != "outlook_token":
                continue
            credentials = mail_provider.parse_outlook_credentials(str(provider.get("mailboxes") or ""))
            kept, removed = mail_provider.prune_outlook_unused_credentials(credentials, provider)
            if removed:
                provider["mailboxes"] = _serialize_outlook_pool(kept)
                total_removed += removed
            for key in ("mailboxes_count", "mailboxes_base_count", "mailboxes_alias_count", "mailboxes_preview", "mailboxes_stats", "mailboxes_parse_stats"):
                provider.pop(key, None)
        return total_removed

    def update(self, updates: dict) -> dict:
        with self._lock:
            self._merge_outlook_pools(updates)
            self._config = _normalize({**self._config, **updates})
            self._drop_mail_proxy()
            openai_register.config.update({k: self._config[k] for k in ("mail", "proxy", "total", "threads")})
            self._save()
            self._wake_event.set()
            return self.get()

    def start(self) -> dict:
        with self._lock:
            providers = self._config.get("mail", {}).get("providers", []) if isinstance(self._config.get("mail"), dict) else []
            enabled = [item for item in providers if isinstance(item, dict) and item.get("enable") is not False and str(item.get("type") or "").strip()]
            if not enabled:
                raise ValueError("请先配置并启用至少一个邮箱渠道")
            for index, provider in enumerate(enabled, start=1):
                missing = _provider_missing(provider)
                if missing:
                    label = str(provider.get("label") or f"邮箱来源 {index}").strip()
                    raise ValueError(f"{label} 缺少：{'、'.join(missing)}")
            if self._runner and self._runner.is_alive():
                self._config["enabled"] = True
                self._wake_event.set()
                self._save()
                return self.get()
            self._config["enabled"] = True
            self._drop_mail_proxy()
            self._logs = []
            self._last_pool_log_signature = None
            metrics = self._pool_metrics()
            self._config["stats"] = {"job_id": uuid.uuid4().hex, "success": 0, "fail": 0, "done": 0, "running": 0, "threads": self._config["threads"], "phase": "starting", "stop_reason": "", **metrics, "started_at": _now(), "updated_at": _now()}
            openai_register.config.update({k: self._config[k] for k in ("mail", "proxy", "total", "threads")})
            with openai_register.stats_lock:
                openai_register.stats.update({"done": 0, "success": 0, "fail": 0, "start_time": time.time()})
            self._save()
            self._wake_event.clear()
            self._runner = threading.Thread(target=self._run, daemon=True, name="openai-register")
            self._runner.start()
            self._append_log(f"注册任务启动，模式={self._config['mode']}，线程数={self._config['threads']}", "yellow")
            return self.get()

    def stop(self) -> dict:
        with self._lock:
            self._config["enabled"] = False
            self._config["stats"]["phase"] = "stopping"
            self._config["stats"]["next_check_at"] = ""
            self._config["stats"]["updated_at"] = _now()
            self._save()
            self._wake_event.set()
            self._append_log("已请求停止注册任务，正在等待当前运行任务结束", "yellow")
            return self.get()

    def reset(self) -> dict:
        with self._lock:
            self._logs = []
            self._last_pool_log_signature = None
            self._config["stats"] = {"success": 0, "fail": 0, "done": 0, "running": 0, "threads": self._config["threads"], "elapsed_seconds": 0, "avg_seconds": 0, "success_rate": 0, "phase": "stopped", "stop_reason": "", **self._pool_metrics(), "updated_at": _now()}
            with openai_register.stats_lock:
                openai_register.stats.update({"done": 0, "success": 0, "fail": 0, "start_time": 0.0})
            self._save()
            return self.get()

    def check_now(self) -> dict:
        with self._lock:
            enabled = bool(self._config.get("enabled"))
            self._config["stats"]["next_check_at"] = _now()
            self._save()
        self._append_log("已手动触发号池检查", "yellow")
        if enabled:
            self._wake_event.set()
        else:
            self._target_reached(self.get(), 0)
        return self.get()

    def reset_outlook_pool(self, scope: str = "all") -> dict:
        scope = str(scope or "all").strip().lower()
        if scope == "unused":
            with self._lock:
                removed = self._prune_unused_outlook_pools()
                openai_register.config.update({k: self._config[k] for k in ("mail", "proxy", "total", "threads")})
                self._save()
                self._append_log(f"已清空 Outlook 邮箱池未使用邮箱，移除 {removed} 个", "yellow")
            return self.get()
        scope_aliases = {"failed": "retryable", "retryable": "retryable", "invalid": "invalid", "all": "all"}
        scope = scope_aliases.get(scope, "all")
        cleared = mail_provider.reset_outlook_token_pool_state(scope)
        scope_label = {"retryable": "占用/临时失败", "invalid": "异常", "all": "全部"}[scope]
        with self._lock:
            self._append_log(
                f"已重置 Outlook 邮箱池状态（范围={scope_label}），清除 {cleared} 条记录",
                "yellow",
            )
        return self.get()

    def _mail_config_with_proxy(self) -> dict:
        mail = json.loads(json.dumps(self._config.get("mail") if isinstance(self._config.get("mail"), dict) else {}, ensure_ascii=False))
        use_register_proxy = _safe_bool(mail.get("api_use_register_proxy"), True)
        mail["api_use_register_proxy"] = use_register_proxy
        mail["proxy"] = str(self._config.get("proxy") or "").strip() if use_register_proxy else ""
        return mail

    def gptmail_status(self, provider: dict | None = None, force: bool = False) -> dict:
        with self._lock:
            mail = self._mail_config_with_proxy()
        return mail_provider.gptmail_status(mail, provider, force=force)

    def refresh_gptmail_public_key(self, provider: dict | None = None, force: bool = True) -> dict:
        with self._lock:
            mail = self._mail_config_with_proxy()
        return mail_provider.refresh_gptmail_public_key(mail, provider, force=force)

    def _append_log(self, text: str, color: str = "") -> None:
        with self._lock:
            self._logs.append({"time": _now(), "text": _redact_register_log(text), "level": str(color or "info")})
            self._logs = self._logs[-300:]

    def _pool_metrics(
        self,
        *,
        refresh_stale: bool = False,
        target_quota: int | None = None,
        target_available: int | None = None,
    ) -> dict:
        evaluate = getattr(account_service, "evaluate_account_pool", None)
        if callable(evaluate):
            return evaluate(
                refresh_stale=refresh_stale,
                target_quota=target_quota,
                target_available=target_available,
            )

        # basketikun 分支没有上游新版的远端号池评估接口，使用现有统计口径兼容。
        stats = account_service.get_stats()
        return {
            "current_quota": max(0, int(stats.get("total_quota") or 0)),
            "current_available": max(0, int(stats.get("active") or 0)),
            "estimated_quota": max(0, int(stats.get("total_quota") or 0)),
            "estimated_available": max(0, int(stats.get("active") or 0)),
            "pool_refreshed": 0,
            "pool_refresh_errors": [],
        }

    def _target_reached(self, cfg: dict, submitted: int, *, refresh_stale: bool = True) -> bool:
        mode = str(cfg.get("mode") or "total")
        metrics = self._pool_metrics(
            refresh_stale=refresh_stale and mode in {"quota", "available"},
            target_quota=int(cfg.get("target_quota") or 1) if mode == "quota" else None,
            target_available=int(cfg.get("target_available") or 1) if mode == "available" else None,
        )
        checked_at = datetime.now(timezone.utc)
        self._bump(**metrics, last_check_at=checked_at.isoformat())
        if mode == "quota":
            reached = metrics["current_quota"] >= int(cfg.get("target_quota") or 1)
            refill_required = not reached
            signature = (mode, metrics["current_available"], metrics["current_quota"], int(cfg.get("target_quota") or 1), reached)
            if signature != self._last_pool_log_signature:
                self._last_pool_log_signature = signature
                action = "开始补池" if refill_required else "保持监控"
                self._append_log(f"检查号池：当前正常账号={metrics['current_available']}，当前剩余额度={metrics['current_quota']}，目标额度={cfg.get('target_quota')}，{action}", "yellow")
            return reached
        if mode == "available":
            reached = metrics["current_available"] >= int(cfg.get("target_available") or 1)
            refill_required = not reached
            signature = (mode, metrics["current_available"], metrics["current_quota"], int(cfg.get("target_available") or 1), reached)
            if signature != self._last_pool_log_signature:
                self._last_pool_log_signature = signature
                action = "开始补池" if refill_required else "保持监控"
                self._append_log(f"检查号池：当前正常账号={metrics['current_available']}，目标账号={cfg.get('target_available')}，当前剩余额度={metrics['current_quota']}，{action}", "yellow")
            return reached
        return submitted >= int(cfg.get("total") or 1)

    def _refill_required(self, cfg: dict) -> bool:
        stats = self._config.get("stats") if isinstance(self._config.get("stats"), dict) else {}
        mode = str(cfg.get("mode") or "total")
        if mode == "quota":
            return int(stats.get("current_quota") or 0) < int(cfg.get("target_quota") or 1)
        if mode == "available":
            return int(stats.get("current_available") or 0) < int(cfg.get("target_available") or 1)
        return True

    def _concurrency_limit(self, cfg: dict, threads: int) -> int:
        stats = self._config.get("stats") if isinstance(self._config.get("stats"), dict) else {}
        mode = str(cfg.get("mode") or "total")
        if mode == "quota":
            deficit = max(0, int(cfg.get("target_quota") or 1) - int(stats.get("current_quota") or 0))
            expected = max(1, int(cfg.get("expected_quota_per_account") or 25))
            needed = max(1, (deficit + expected - 1) // expected)
            return min(threads, needed)
        if mode == "available":
            deficit = max(0, int(cfg.get("target_available") or 1) - int(stats.get("current_available") or 0))
            return min(threads, max(1, deficit))
        return threads

    def _start_cycle_record(self, cfg: dict, success: int, fail: int) -> dict:
        stats = self._config.get("stats") if isinstance(self._config.get("stats"), dict) else {}
        mode = str(cfg.get("mode") or "quota")
        return {
            "id": uuid.uuid4().hex,
            "mode": mode,
            "started_at": _now(),
            "start_quota": int(stats.get("current_quota") or 0),
            "start_available": int(stats.get("current_available") or 0),
            "target": int(cfg.get("target_quota") if mode == "quota" else cfg.get("target_available") or 0),
            "trigger": int(cfg.get("target_quota") if mode == "quota" else cfg.get("target_available") or 0),
            "_success_start": success,
            "_fail_start": fail,
        }

    def _finish_cycle_record(self, record: dict | None, status: str, reason: str, success: int, fail: int) -> None:
        if not record:
            return
        stats = self._config.get("stats") if isinstance(self._config.get("stats"), dict) else {}
        item = {key: value for key, value in record.items() if not key.startswith("_")}
        item.update({
            "status": status,
            "reason": reason,
            "finished_at": _now(),
            "end_quota": int(stats.get("current_quota") or 0),
            "end_available": int(stats.get("current_available") or 0),
            "success": max(0, success - int(record.get("_success_start") or 0)),
            "fail": max(0, fail - int(record.get("_fail_start") or 0)),
        })
        with self._lock:
            self._config["history"] = [*(self._config.get("history") or []), item][-50:]
            self._save()
        if status in {"cooldown", "failed"}:
            self._notify({"event": "register_refill_cycle_failed", **item})

    def _update_channel_health(self, result: dict) -> None:
        if str(result.get("failure_kind") or "") == "rate_limit":
            return
        payload = result.get("result") if isinstance(result.get("result"), dict) else {}
        provider = str(payload.get("register_provider") or result.get("provider") or "unknown").strip() or "unknown"
        with self._lock:
            stats = self._config["stats"]
            health = stats.get("channel_health") if isinstance(stats.get("channel_health"), dict) else {}
            item = dict(health.get(provider) if isinstance(health.get(provider), dict) else {})
            ok = bool(result.get("ok"))
            item["success" if ok else "fail"] = int(item.get("success" if ok else "fail") or 0) + 1
            item["last_at"] = _now()
            item["last_error"] = "" if ok else _redact_register_log(result.get("error") or "注册失败")[:300]
            health[provider] = item
            stats["channel_health"] = health

    def _notify(self, payload: dict) -> None:
        webhook_url = str(self._config.get("alert_webhook_url") or "").strip()
        if not webhook_url.startswith(("http://", "https://")):
            return

        def send() -> None:
            try:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                with urlopen(Request(webhook_url, data=body, headers={"Content-Type": "application/json"}, method="POST"), timeout=5):
                    pass
            except Exception:
                pass

        threading.Thread(target=send, daemon=True, name="register-alert").start()

    def _bump(self, **updates) -> None:
        with self._lock:
            self._config["stats"].update(updates)
            stats = self._config["stats"]
            started_at = str(stats.get("started_at") or "")
            if started_at:
                try:
                    elapsed = max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(started_at)).total_seconds())
                except Exception:
                    elapsed = 0.0
                done = int(stats.get("done") or 0)
                success = int(stats.get("success") or 0)
                fail = int(stats.get("fail") or 0)
                stats["elapsed_seconds"] = round(elapsed, 1)
                stats["avg_seconds"] = round(elapsed / success, 1) if success else 0
                stats["success_rate"] = round(success * 100 / max(1, success + fail), 1)
            self._config["stats"]["updated_at"] = _now()
            self._save()

    @staticmethod
    def _safety_stop_reason(cfg: dict, submitted: int, consecutive_failures: int, started_at: float) -> str:
        if submitted >= int(cfg.get("max_attempts") or 100):
            return f"达到最大尝试次数 {int(cfg.get('max_attempts') or 100)}"
        if consecutive_failures >= int(cfg.get("max_consecutive_failures") or 10):
            return f"连续失败 {int(cfg.get('max_consecutive_failures') or 10)} 次"
        max_seconds = int(cfg.get("max_runtime_minutes") or 60) * 60
        if time.monotonic() - started_at >= max_seconds:
            return f"达到最长运行时间 {int(cfg.get('max_runtime_minutes') or 60)} 分钟"
        return ""

    def _finish_running_state(self, reason: str) -> None:
        with self._lock:
            self._config["enabled"] = False
            self._config["stats"]["phase"] = "stopped"
            self._config["stats"]["stop_reason"] = reason
            self._config["stats"]["next_check_at"] = ""
            self._config["stats"]["updated_at"] = _now()
            self._save()
        if reason:
            self._append_log(f"注册任务自动停止：{reason}", "yellow")

    def _set_phase(self, phase: str, reason: str = "") -> bool:
        with self._lock:
            stats = self._config["stats"]
            changed = stats.get("phase") != phase or str(stats.get("stop_reason") or "") != reason
            stats["phase"] = phase
            stats["stop_reason"] = reason
            if phase not in {"monitoring", "cooldown"}:
                stats["next_check_at"] = ""
            stats["updated_at"] = _now()
            if changed:
                self._save()
            return changed

    def _schedule_next_check(self, seconds: float) -> None:
        delay = max(0.0, float(seconds))
        deadline = datetime.now(timezone.utc) + timedelta(seconds=delay)
        self._bump(next_check_at=deadline.isoformat())

    def _wait_for_next_check(self, seconds: float) -> None:
        self._wake_event.wait(timeout=max(0.1, float(seconds)))
        self._wake_event.clear()

    def _proxy_preflight(self) -> dict[str, object]:
        register_proxy = str(self._config.get("proxy") or "").strip()
        profile = proxy_settings.get_profile(proxy=register_proxy, upstream=True)
        if not profile.proxy_url:
            return {"ok": True, "skipped": True, "proxy_source": profile.proxy_source}
        result = test_proxy(profile.proxy_url, timeout=10.0)
        if not result.get("ok"):
            return result
        clearance = profile.clearance
        if profile.clearance_mode == "flaresolverr":
            bundle = proxy_settings.refresh_clearance(
                target_url="https://auth.openai.com",
                proxy=profile.proxy_url,
                force=True,
                upstream=True,
            )
            if bundle is None:
                # FlareSolverr 在目标页没有挑战时可能返回 200 但不带 clearance。
                # 代理本身可用时继续执行，由实际注册请求按需处理 403，避免整轮任务被误判为代理故障。
                return {
                    **result,
                    "clearance_ok": False,
                    "clearance_warning": "FlareSolverr 预检未返回 Cookie，将在请求遇到 Cloudflare 时按需重试",
                    "proxy_source": profile.proxy_source,
                    "clearance": clearance,
                }
            result = {
                **result,
                "clearance_ok": True,
                "proxy_source": profile.proxy_source,
                "clearance": clearance,
            }
        return result

    def _run(self) -> None:
        threads = int(self.get()["threads"])
        submitted, done, success, fail = 0, 0, 0, 0
        cycle_submitted = 0
        cycle_consecutive_failures = 0
        cycle_started_monotonic: float | None = None
        runner_started_monotonic = time.monotonic()
        retry_not_before = 0.0
        stop_reason = ""
        cycle_record: dict | None = None
        cycle_block_reason = ""
        cycle_block_cooldown = 0
        with ThreadPoolExecutor(max_workers=threads) as executor:
            futures = set()
            while True:
                cfg = self.get()
                enabled = bool(cfg.get("enabled"))
                mode = str(cfg.get("mode") or "total")
                monitor_mode = mode in {"quota", "available"}
                now = time.monotonic()

                if monitor_mode and enabled and not futures and now < retry_not_before:
                    current_reason = str((cfg.get("stats") or {}).get("stop_reason") or "本轮补池失败，等待重试")
                    self._set_phase("cooldown", current_reason)
                    self._wait_for_next_check(min(1.0, retry_not_before - now))
                    continue

                reached = self._target_reached(cfg, submitted, refresh_stale=not futures)
                refill_required = self._refill_required(cfg) if monitor_mode else True

                if monitor_mode and enabled and not futures:
                    cycle_active = cycle_started_monotonic is not None
                    if cycle_active and reached:
                        self._finish_cycle_record(cycle_record, "completed", "已达到补池目标", success, fail)
                        cycle_record = None
                        cycle_submitted = 0
                        cycle_consecutive_failures = 0
                        cycle_started_monotonic = None
                        retry_not_before = 0.0
                    if (not cycle_active and not refill_required) or reached:
                        if self._set_phase("monitoring"):
                            self._append_log("号池处于安全区间，进入常驻监控", "green")
                        wait_seconds = int(cfg.get("check_interval") or 5)
                        self._bump(running=0, done=done, success=success, fail=fail)
                        self._schedule_next_check(wait_seconds)
                        self._wait_for_next_check(wait_seconds)
                        continue

                if enabled and not reached and not futures and cycle_started_monotonic is None:
                    proxy_check = self._proxy_preflight()
                    if not proxy_check.get("ok"):
                        error = _redact_register_log(proxy_check.get("error") or "代理不可用")
                        reason = f"代理预检失败：{error}"
                        if monitor_mode:
                            cooldown_seconds = int(cfg.get("retry_cooldown_seconds") or 300)
                            retry_not_before = now + cooldown_seconds
                            cooldown_reason = f"{reason}，冷却后自动重试"
                            self._schedule_next_check(cooldown_seconds)
                            if self._set_phase("cooldown", cooldown_reason):
                                self._append_log(cooldown_reason, "yellow")
                            self._bump(running=0, done=done, success=success, fail=fail)
                            self._wait_for_next_check(min(1.0, retry_not_before - now))
                            continue
                        stop_reason = reason
                        self._finish_running_state(stop_reason)
                        break

                if monitor_mode and enabled and not reached and cycle_started_monotonic is None:
                    cycle_started_monotonic = now
                    cycle_submitted = 0
                    cycle_consecutive_failures = 0
                    retry_not_before = 0.0
                    cycle_block_reason = ""
                    cycle_block_cooldown = 0
                    cycle_record = self._start_cycle_record(cfg, success, fail)
                    if self._set_phase("registering"):
                        self._append_log("检测到号池低于目标，开始自动补池", "yellow")

                safety_submitted = cycle_submitted if monitor_mode else submitted
                safety_started = (cycle_started_monotonic or now) if monitor_mode else runner_started_monotonic
                safety_reason = cycle_block_reason or self._safety_stop_reason(cfg, safety_submitted, cycle_consecutive_failures, safety_started)
                if enabled and safety_reason:
                    if monitor_mode:
                        if not futures:
                            cooldown_seconds = cycle_block_cooldown or int(cfg.get("retry_cooldown_seconds") or 300)
                            retry_not_before = now + cooldown_seconds
                            reason = f"本轮补池暂停：{safety_reason}，{cooldown_seconds} 秒后自动重试"
                            self._schedule_next_check(cooldown_seconds)
                            if self._set_phase("cooldown", reason):
                                self._append_log(reason, "yellow")
                            self._finish_cycle_record(cycle_record, "cooldown", reason, success, fail)
                            cycle_record = None
                            cycle_submitted = 0
                            cycle_consecutive_failures = 0
                            cycle_started_monotonic = None
                            cycle_block_reason = ""
                            cycle_block_cooldown = 0
                            self._wait_for_next_check(min(1.0, retry_not_before - now))
                            continue
                    else:
                        stop_reason = safety_reason
                        self._finish_running_state(stop_reason)
                        enabled = False
                max_attempts = int(cfg.get("max_attempts") or 100)
                attempt_count = cycle_submitted if monitor_mode else submitted
                concurrency_limit = self._concurrency_limit(cfg, threads)
                remaining_failure_budget = max(0, int(cfg.get("max_consecutive_failures") or 10) - cycle_consecutive_failures)
                concurrency_limit = min(concurrency_limit, remaining_failure_budget)
                while enabled and not reached and not safety_reason and len(futures) < concurrency_limit and attempt_count < max_attempts:
                    submitted += 1
                    if monitor_mode:
                        cycle_submitted += 1
                        attempt_count = cycle_submitted
                    else:
                        attempt_count = submitted
                    futures.add(executor.submit(openai_register.worker, submitted))
                    if mode == "total":
                        reached = submitted >= int(cfg.get("total") or 1)
                self._bump(running=len(futures), done=done, success=success, fail=fail)
                if not futures and not enabled:
                    break
                if not futures and reached:
                    if mode == "total":
                        stop_reason = "已达到任务目标"
                        self._finish_running_state(stop_reason)
                        break
                    continue
                if not futures and mode == "total":
                    break
                if not futures:
                    self._wait_for_next_check(int(cfg.get("check_interval") or 5))
                    continue
                finished, futures = wait(futures, timeout=1.0, return_when=FIRST_COMPLETED)
                batch_success = False
                batch_failures = 0
                for future in finished:
                    done += 1
                    try:
                        result = future.result()
                        self._update_channel_health(result)
                        if result.get("ok"):
                            success += 1
                            batch_success = True
                        else:
                            fail += 1
                            batch_failures += 1
                            if str(result.get("failure_kind") or "") == "rate_limit" and not cycle_block_reason:
                                retry_after = max(0, int(result.get("retry_after") or 0))
                                configured_cooldown = int(cfg.get("rate_limit_cooldown_seconds") or 900)
                                cycle_block_reason = "注册出口触发上游限流（HTTP 429）"
                                cycle_block_cooldown = max(configured_cooldown, retry_after)
                    except Exception:
                        fail += 1
                        batch_failures += 1
                if batch_success:
                    cycle_consecutive_failures = 0
                else:
                    cycle_consecutive_failures += batch_failures
        self._bump(running=0, done=done, success=success, fail=fail, finished_at=_now())
        self._finish_cycle_record(cycle_record, "stopped", "任务已停止", success, fail)
        with self._lock:
            self._config["enabled"] = False
            self._config["stats"]["phase"] = "stopped"
            self._config["stats"]["next_check_at"] = ""
            if stop_reason:
                self._config["stats"]["stop_reason"] = stop_reason
            self._save()
        self._append_log(f"注册任务结束，成功{success}，失败{fail}", "yellow")


register_service = RegisterService(REGISTER_FILE)
