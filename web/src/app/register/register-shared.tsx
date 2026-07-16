import type { ReactNode } from "react";

import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import type { RegisterConfig, RegisterProvider } from "@/lib/api";

export const PROVIDER_TYPES = [
  ["cloudmail_gen", "CloudMail Gen"],
  ["cloudflare_temp_email", "Cloudflare Temp Email"],
  ["tempmail_lol", "TempMail.lol"],
  ["moemail", "MoEmail"],
  ["inbucket", "Inbucket"],
  ["duckmail", "DuckMail"],
  ["gptmail", "GPTMail"],
  ["donemail", "DoneMail"],
  ["yyds_mail", "YYDS Mail"],
  ["ddg_mail", "DDG + CF Mail"],
  ["outlook_token", "Microsoft Outlook Pool"],
] as const;

export const STAGE_LABELS: Record<string, string> = {
  mailbox_create: "创建邮箱",
  authorize: "授权",
  login_flow: "登录流程",
  signup_send_otp: "发送注册验证码",
  signup_wait_otp: "等待注册验证码",
  signup_validate_otp: "验证注册验证码",
  signup_create_account: "创建账号",
  signup_exchange_tokens: "交换注册令牌",
  persist_account: "保存账号",
  refresh_account: "刷新账号",
};

export type RegisterLogEntry = {
  time: string;
  text: string;
  level?: string;
};

export type RegisterLogTone = "info" | "warning" | "error";

export function providerId(type: string) {
  const suffix = typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID().replaceAll("-", "").slice(0, 12)
    : Math.random().toString(36).slice(2, 14);
  return `${type}-${suffix}`;
}

export function defaultProvider(type = "cloudmail_gen"): RegisterProvider {
  const base = { id: providerId(type), enable: true, type, label: "" };
  switch (type) {
    case "cloudmail_gen": return { ...base, api_base: "", admin_email: "", admin_password: "", domain: [], subdomain: [], email_prefix: "" };
    case "cloudflare_temp_email": return { ...base, api_base: "", admin_password: "", domain: [] };
    case "tempmail_lol": return { ...base, api_key: "", domain: [] };
    case "moemail": return { ...base, api_base: "", api_key: "", domain: [], expiry_time: 0 };
    case "inbucket": return { ...base, api_base: "", domain: [], random_subdomain: true };
    case "duckmail": return { ...base, api_key: "", default_domain: "duckmail.sbs" };
    case "gptmail": return { ...base, key_mode: "public", api_key: "", default_domain: "", local_compose: false };
    case "donemail": return { ...base, api_base: "", admin_key: "", domain: [], email_prefix: "", message_limit: 20 };
    case "yyds_mail": return { ...base, api_base: "", api_key: "", domain: [], subdomain: "", wildcard: false };
    case "ddg_mail": return { ...base, api_base: "", ddg_token: "", cf_inbox_jwt: "", admin_password: "", cf_api_key: "", cf_auth_mode: "none", cf_create_path: "/api/new_address", cf_messages_path: "/api/mails" };
    case "outlook_token": return { ...base, mailboxes: "", mode: "auto", imap_host: "outlook.office365.com", message_limit: 10, alias_enabled: false, alias_per_email: 5, alias_prefix: "c2api", alias_include_original: true };
    default: return base;
  }
}

export function normalizeProvider(provider: RegisterProvider): RegisterProvider {
  const type = String(provider.type || "cloudmail_gen");
  return {
    ...defaultProvider(type),
    ...provider,
    id: String(provider.id || provider.provider_id || "").trim() || providerId(type),
    type,
    enable: provider.enable !== false,
  };
}

export function normalizeConfig(value: RegisterConfig): RegisterConfig {
  const targetQuota = Math.max(1, Number(value.target_quota) || 1);
  const targetAvailable = Math.max(1, Number(value.target_available) || 1);
  const rawTriggerQuota = Number(value.trigger_quota);
  const rawTriggerAvailable = Number(value.trigger_available);
  return {
    ...value,
    mail: { ...(value.mail || {}), providers: (value.mail?.providers || []).map(normalizeProvider) },
    total: Math.max(1, Number(value.total) || 1),
    threads: Math.max(1, Number(value.threads) || 1),
    target_quota: targetQuota,
    trigger_quota: Math.max(0, Math.min(targetQuota - 1, Number.isFinite(rawTriggerQuota) ? rawTriggerQuota : Math.floor(targetQuota / 2))),
    target_available: targetAvailable,
    trigger_available: Math.max(0, Math.min(targetAvailable - 1, Number.isFinite(rawTriggerAvailable) ? rawTriggerAvailable : Math.floor(targetAvailable / 2))),
    expected_quota_per_account: Math.max(1, Number(value.expected_quota_per_account) || 25),
    check_interval: Math.max(1, Number(value.check_interval) || 5),
    max_attempts: Math.max(1, Number(value.max_attempts) || 100),
    max_consecutive_failures: Math.max(1, Number(value.max_consecutive_failures) || 10),
    max_runtime_minutes: Math.max(1, Number(value.max_runtime_minutes) || 60),
    retry_cooldown_seconds: Math.max(30, Number(value.retry_cooldown_seconds) || 300),
    rate_limit_cooldown_seconds: Math.max(60, Number(value.rate_limit_cooldown_seconds) || 900),
    alert_webhook_url: String(value.alert_webhook_url || ""),
  };
}

export function mergeRuntimeSnapshot(current: RegisterConfig, next: RegisterConfig): RegisterConfig {
  return {
    ...current,
    enabled: next.enabled,
    stats: next.stats,
    logs: next.logs,
    history: next.history,
  };
}

export function formatRegisterLogTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).format(date).replace(/\//g, "-");
}

export function formatDurationMs(value: number) {
  const duration = Math.max(0, Number(value) || 0);
  return duration >= 1000 ? `${(duration / 1000).toFixed(1)}s` : `${Math.round(duration)}ms`;
}

export function normalizeRegisterLogTone(level?: string): RegisterLogTone {
  const normalized = String(level || "info").trim().toLowerCase();
  if (normalized === "red" || normalized === "error" || normalized === "danger") return "error";
  if (normalized === "yellow" || normalized === "warn" || normalized === "warning" || normalized === "amber") return "warning";
  return "info";
}

export function getRegisterLogToneMeta(level?: string) {
  const tone = normalizeRegisterLogTone(level);
  if (tone === "error") {
    return {
      tone,
      label: "错误",
      badgeClassName: "border-red-200 bg-red-50 text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-200",
      cardClassName: "border-red-100 bg-red-50/70 dark:border-red-500/20 dark:bg-red-500/10",
      textClassName: "text-red-700 dark:text-red-100",
    };
  }
  if (tone === "warning") {
    return {
      tone,
      label: "警告",
      badgeClassName: "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200",
      cardClassName: "border-amber-100 bg-amber-50/70 dark:border-amber-500/20 dark:bg-amber-500/10",
      textClassName: "text-amber-800 dark:text-amber-100",
    };
  }
  return {
    tone,
    label: "信息",
    badgeClassName: "border-stone-200 bg-white text-stone-600 dark:border-white/10 dark:bg-stone-900 dark:text-stone-200",
    cardClassName: "border-stone-200/70 bg-white/90 dark:border-white/10 dark:bg-stone-900/80",
    textClassName: "text-stone-700 dark:text-stone-100",
  };
}

function hasValue(value: unknown) {
  if (Array.isArray(value)) return value.some((item) => String(item || "").trim());
  return Boolean(String(value ?? "").trim());
}

export function pendingOutlookCount(provider: RegisterProvider) {
  return String(provider.mailboxes || "").split(/\r?\n/).filter((line) => line.trim().split("----").length >= 4).length;
}

export function providerMissing(provider: RegisterProvider) {
  const type = String(provider.type || "");
  const missing: string[] = [];
  const required = (key: keyof RegisterProvider, label: string) => {
    if (!hasValue(provider[key])) missing.push(label);
  };
  switch (type) {
    case "cloudmail_gen": required("api_base", "CloudMail 地址"); required("admin_email", "管理员邮箱"); required("admin_password", "管理员密码"); required("domain", "域名"); break;
    case "cloudflare_temp_email": required("api_base", "API 地址"); required("admin_password", "管理员密码"); required("domain", "域名"); break;
    case "moemail": required("api_base", "API 地址"); required("api_key", "API 密钥"); required("domain", "域名"); break;
    case "inbucket": required("api_base", "API 地址"); required("domain", "基础域名"); break;
    case "duckmail": required("api_key", "API 密钥"); break;
    case "gptmail": if (String(provider.key_mode || "public") === "custom") required("api_key", "API 密钥"); if (provider.local_compose) required("default_domain", "默认域名"); break;
    case "donemail": required("api_base", "DoneMail 地址"); required("admin_key", "管理员密钥"); required("domain", "域名"); break;
    case "yyds_mail": required("api_key", "API 密钥"); break;
    case "ddg_mail": required("api_base", "CF API 地址"); required("ddg_token", "DDG 令牌"); required("cf_inbox_jwt", "CF 收件箱 JWT"); break;
    case "outlook_token": if (Number(provider.mailboxes_count || 0) <= 0 && pendingOutlookCount(provider) <= 0) missing.push("Microsoft Outlook 邮箱池"); break;
  }
  return missing;
}

export function SectionTitle({ title, eyebrow, inverted = false }: { title: string; eyebrow?: string; inverted?: boolean }) {
  return <div>{eyebrow ? <div className="text-[10px] font-semibold tracking-[0.18em] text-stone-400">{eyebrow}</div> : null}<h2 className={`text-base font-semibold ${inverted ? "text-white" : "text-stone-900 dark:text-white"}`}>{title}</h2></div>;
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="min-w-0 space-y-1.5"><span className="block text-xs text-stone-500">{label}</span>{children}</label>;
}

export function Metric({ label, value, inverted = false }: { label: string; value: number; inverted?: boolean }) {
  return <div className={`border border-stone-200/70 p-3 ${inverted ? "bg-stone-950" : "rounded-lg bg-stone-50/80 dark:border-white/10 dark:bg-stone-900"}`}><div className={`text-xs ${inverted ? "text-stone-400" : "text-stone-500"}`}>{label}</div><div className="mt-1 text-xl font-semibold tabular-nums">{value}</div></div>;
}

export function Summary({ label, value, tone = "stone" }: { label: string; value: string | number; tone?: "stone" | "emerald" | "amber" }) {
  const color = tone === "emerald" ? "text-emerald-600" : tone === "amber" ? "text-amber-600" : "text-stone-950 dark:text-white";
  return <div className="min-w-0 bg-white/95 px-4 py-3 dark:bg-stone-900/95"><div className="text-[11px] text-stone-500">{label}</div><div className={`mt-0.5 truncate text-lg font-semibold tabular-nums ${color}`}>{value}</div></div>;
}

export function Toggle({ label, checked, disabled, onChange }: { label: string; checked: boolean; disabled: boolean; onChange: (value: boolean) => void }) {
  return <label className="flex min-h-10 items-center gap-2 text-sm"><Checkbox disabled={disabled} checked={checked} onCheckedChange={(value) => onChange(Boolean(value))} />{label}</label>;
}

export function ProviderInput({
  disabled,
  provider,
  setValue,
  field,
  label,
  placeholder,
  secret = false,
  number = false,
}: {
  disabled: boolean;
  provider: RegisterProvider;
  setValue: (key: keyof RegisterProvider, value: unknown) => void;
  field: keyof RegisterProvider;
  label: string;
  placeholder?: string;
  secret?: boolean;
  number?: boolean;
}) {
  return <Field label={label}><Input disabled={disabled} type={secret ? "password" : number ? "number" : "text"} value={String(provider[field] ?? "")} placeholder={placeholder || ""} onChange={(event) => setValue(field, number ? Number(event.target.value) : event.target.value)} /></Field>;
}
