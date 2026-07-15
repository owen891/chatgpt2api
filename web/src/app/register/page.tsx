"use client";

import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { LoaderCircle, Play, Plus, RotateCcw, Save, Square, Trash2, RefreshCw, Wrench } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  fetchRegisterConfig,
  checkRegisterPool,
  createRegisterEventTicket,
  fetchRegisterProxyGroups,
  fetchGptMailStatus,
  resetOutlookPool,
  resetRegister,
  startRegister,
  stopRegister,
  updateRegisterConfig,
  type RegisterConfig,
  type RegisterProvider,
  type RegisterGptMailStatus,
  type RegisterProxyGroup,
} from "@/lib/api";
import webConfig from "@/constants/common-env";

const PROVIDER_TYPES = [
  ["cloudmail_gen", "CloudMail Gen"],
  ["cloudflare_temp_email", "Cloudflare Temp Email"],
  ["tempmail_lol", "TempMail.lol"],
  ["moemail", "MoEmail"],
  ["inbucket", "Inbucket"],
  ["duckmail", "DuckMail"],
  ["gptmail", "GPTMail"],
  ["donemail", "DoneMail"],
  ["yyds_mail", "YYDS Mail"],
  ["ddg_mail", "DDG + CF 收件箱"],
  ["outlook_token", "Microsoft 邮箱凭据池"],
] as const;

function providerId(type: string) {
  const suffix = typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID().replaceAll("-", "").slice(0, 12)
    : Math.random().toString(36).slice(2, 14);
  return `${type}-${suffix}`;
}

function defaultProvider(type = "cloudmail_gen"): RegisterProvider {
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

function normalizeProvider(provider: RegisterProvider): RegisterProvider {
  const type = String(provider.type || "cloudmail_gen");
  return {
    ...defaultProvider(type),
    ...provider,
    id: String(provider.id || provider.provider_id || "").trim() || providerId(type),
    type,
    enable: provider.enable !== false,
  };
}

function normalizeConfig(value: RegisterConfig): RegisterConfig {
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

function mergeRuntimeSnapshot(current: RegisterConfig, next: RegisterConfig): RegisterConfig {
  return {
    ...current,
    enabled: next.enabled,
    stats: next.stats,
    logs: next.logs,
    history: next.history,
  };
}

function formatRegisterLogTime(value: string) {
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

function hasValue(value: unknown) {
  if (Array.isArray(value)) return value.some((item) => String(item || "").trim());
  return Boolean(String(value ?? "").trim());
}

function pendingOutlookCount(provider: RegisterProvider) {
  return String(provider.mailboxes || "").split(/\r?\n/).filter((line) => line.trim().split("----").length >= 4).length;
}

function providerMissing(provider: RegisterProvider) {
  const type = String(provider.type || "");
  const missing: string[] = [];
  const required = (key: keyof RegisterProvider, label: string) => { if (!hasValue(provider[key])) missing.push(label); };
  switch (type) {
    case "cloudmail_gen": required("api_base", "CloudMail URL"); required("admin_email", "管理员邮箱"); required("admin_password", "管理员密码"); required("domain", "邮箱域名"); break;
    case "cloudflare_temp_email": required("api_base", "API Base"); required("admin_password", "管理员密码"); required("domain", "域名"); break;
    case "moemail": required("api_base", "API Base"); required("api_key", "API Key"); required("domain", "域名"); break;
    case "inbucket": required("api_base", "API Base"); required("domain", "基础域名"); break;
    case "duckmail": required("api_key", "API Key"); break;
    case "gptmail": if (String(provider.key_mode || "public") === "custom") required("api_key", "API Key"); if (provider.local_compose) required("default_domain", "默认域名"); break;
    case "donemail": required("api_base", "DoneMail URL"); required("admin_key", "Admin Key"); required("domain", "域名"); break;
    case "yyds_mail": required("api_key", "API Key"); break;
    case "ddg_mail": required("api_base", "CF API Base"); required("ddg_token", "DDG Token"); required("cf_inbox_jwt", "CF Inbox JWT"); break;
    case "outlook_token": if (Number(provider.mailboxes_count || 0) <= 0 && pendingOutlookCount(provider) <= 0) missing.push("Microsoft 邮箱凭据池"); break;
  }
  return missing;
}

export default function RegisterPage() {
  const [config, setConfig] = useState<RegisterConfig | null>(null);
  const [providers, setProviders] = useState<RegisterProvider[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [action, setAction] = useState<string | null>(null);
  const [proxyGroups, setProxyGroups] = useState<RegisterProxyGroup[]>([]);
  const [proxyMode, setProxyMode] = useState("default");
  const [gptmailStatus, setGptmailStatus] = useState<Record<number, RegisterGptMailStatus>>({});
  const [gptmailBusy, setGptmailBusy] = useState<number | null>(null);
  const [checking, setChecking] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const logRef = useRef<HTMLDivElement | null>(null);
  const previousNewestLogRef = useRef("");
  const previousLogHeightRef = useRef(0);

  const load = async (runtimeOnly = false) => {
    try {
      const data = await fetchRegisterConfig();
      const next = normalizeConfig(data.register);
      if (runtimeOnly) {
        setConfig((current) => current ? mergeRuntimeSnapshot(current, next) : next);
      } else {
        setConfig(next);
        setProviders(next.mail.providers || []);
        setProxyMode(next.proxy === "direct" ? "direct" : next.proxy?.startsWith("group:") ? next.proxy : next.proxy ? "custom" : "default");
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "加载注册机配置失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, []);
  useEffect(() => {
    void fetchRegisterProxyGroups().then((data) => setProxyGroups(data.groups || [])).catch(() => setProxyGroups([]));
  }, []);
  useEffect(() => {
    if (!config?.enabled) return;
    const timer = window.setInterval(() => void load(true), 2000);
    return () => window.clearInterval(timer);
  }, [config?.enabled]);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!config?.enabled || typeof window === "undefined") return;
    let source: EventSource | null = null;
    let reconnectTimer: number | null = null;
    let reconnectAttempt = 0;
    let active = true;

    const scheduleReconnect = () => {
      if (!active || reconnectTimer !== null) return;
      const delay = Math.min(30_000, 1_000 * (2 ** reconnectAttempt));
      reconnectAttempt += 1;
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = null;
        void connect();
      }, delay);
    };

    const connect = async () => {
      try {
        const { ticket } = await createRegisterEventTicket();
        if (!active) return;
        const apiBaseUrl = webConfig.apiUrl.replace(/\/$/, "") || window.location.origin;
        const nextSource = new EventSource(`${apiBaseUrl}/api/register/events?ticket=${encodeURIComponent(ticket)}`);
        source = nextSource;
        nextSource.onopen = () => { reconnectAttempt = 0; };
        nextSource.onmessage = (event) => {
          try {
            const raw = JSON.parse(event.data);
            const next = normalizeConfig(raw.register || raw);
            setConfig((current) => current ? mergeRuntimeSnapshot(current, next) : next);
          } catch { /* 非法事件由下一次 SSE 或轮询覆盖。 */ }
        };
        nextSource.onerror = () => {
          nextSource.close();
          if (source === nextSource) source = null;
          scheduleReconnect();
        };
      } catch {
        scheduleReconnect();
      }
    };

    void connect();
    return () => {
      active = false;
      source?.close();
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
    };
  }, [config?.enabled]);

  const newestLogTime = config?.logs?.length ? config.logs[config.logs.length - 1].time : "";
  useLayoutEffect(() => {
    const panel = logRef.current;
    if (!panel) return;
    const previousNewest = previousNewestLogRef.current;
    const isInitialRender = !previousNewest && previousLogHeightRef.current === 0;
    const hasNewLogs = Boolean(newestLogTime && newestLogTime !== previousNewest);
    const wasAtTop = panel.scrollTop <= 8;
    const heightDelta = panel.scrollHeight - previousLogHeightRef.current;

    if (isInitialRender) {
      panel.scrollTop = 0;
    } else if (hasNewLogs) {
      if (wasAtTop) {
        panel.scrollTop = 0;
      } else {
        const rows = Array.from(panel.querySelectorAll<HTMLElement>("[data-log-time]"));
        const firstRow = rows[0];
        const previousNewestRow = rows.find((row) => row.dataset.logTime === previousNewest);
        const prependedHeight = firstRow && previousNewestRow
          ? previousNewestRow.offsetTop - firstRow.offsetTop
          : Math.max(0, heightDelta);
        panel.scrollTop += Math.max(0, prependedHeight);
      }
    }

    previousNewestLogRef.current = newestLogTime;
    previousLogHeightRef.current = panel.scrollHeight;
  }, [newestLogTime]);

  const running = Boolean(config?.enabled);
  const stats = config?.stats || {};
  const phase = String(stats.phase || (running ? "starting" : "stopped"));
  const phaseMeta = {
    starting: { label: "正在启动", className: "bg-amber-100 text-amber-700" },
    monitoring: { label: "额度监控中", className: "bg-emerald-100 text-emerald-700" },
    registering: { label: "自动补池中", className: "bg-blue-100 text-blue-700" },
    cooldown: { label: "冷却等待中", className: "bg-amber-100 text-amber-700" },
    stopping: { label: "正在停止", className: "bg-amber-100 text-amber-700" },
    stopped: { label: "任务已停止", className: "bg-stone-100 text-stone-500" },
  }[phase] || { label: running ? "任务运行中" : "任务已停止", className: running ? "bg-emerald-100 text-emerald-700" : "bg-stone-100 text-stone-500" };
  const confirmedQuota = Number(stats.current_quota || 0);
  const cachedQuota = Number(stats.estimated_quota || 0);
  const confirmedAvailable = Number(stats.current_available || 0);
  const pendingAvailable = Number(stats.unconfirmed_available || 0);
  const nextCheckAt = stats.next_check_at ? new Date(stats.next_check_at).getTime() : 0;
  const nextCheckSeconds = nextCheckAt > now ? Math.ceil((nextCheckAt - now) / 1000) : 0;
  const showNextCheck = Boolean(config?.enabled && nextCheckAt && (phase === "monitoring" || phase === "cooldown"));
  const modeLabel = useMemo(() => ({ total: "注册总数", quota: "目标剩余额度", available: "目标可用账号" }[config?.mode || "total"] || "注册总数"), [config?.mode]);
  const targetSummary = config?.mode === "quota"
    ? { label: "确认额度进度", value: `${confirmedQuota} / ${config.target_quota}` }
    : config?.mode === "available"
      ? { label: "确认账号进度", value: `${confirmedAvailable} / ${config.target_available}` }
      : { label: "注册进度", value: `${stats.done || 0} / ${config?.total || 0}` };
  const patch = (changes: Partial<RegisterConfig>) => setConfig((current) => current ? normalizeConfig({ ...current, ...changes }) : current);
  const changeProxyMode = (mode: string) => {
    setProxyMode(mode);
    if (mode === "direct") patch({ proxy: "direct" });
    else if (mode.startsWith("group:")) {
      const group = proxyGroups.find((item) => `group:${item.id}` === mode);
      const node = group?.nodes?.find((item) => item.enabled !== false);
      patch({ proxy: node?.name || "" });
    }
    else if (mode === "default") patch({ proxy: "" });
    else if (config?.proxy === "direct" || config?.proxy?.startsWith("group:")) patch({ proxy: "" });
  };

  const persist = async (showToast = true) => {
    if (!config) throw new Error("配置尚未加载");
    const data = await updateRegisterConfig({ ...config, mail: { ...config.mail, providers } });
    const next = normalizeConfig(data.register);
    setConfig(next);
    setProviders(next.mail.providers || []);
    if (showToast) toast.success("注册机配置已保存");
    return next;
  };

  const save = async () => {
    setSaving(true);
    try { await persist(); }
    catch (error) { toast.error(error instanceof Error ? error.message : "保存注册机配置失败"); }
    finally { setSaving(false); }
  };

  const start = async () => {
    const enabled = providers.filter((provider) => provider.enable !== false);
    if (!enabled.length) return toast.error("请先添加并启用至少一个邮箱渠道");
    const invalid = enabled.map((provider, index) => ({ provider, index, missing: providerMissing(provider) })).find((item) => item.missing.length);
    if (invalid) return toast.error(`邮箱来源 ${invalid.index + 1} 缺少：${invalid.missing.join("、")}`);
    setAction("start");
    try {
      await persist(false);
      const data = await startRegister();
      const next = normalizeConfig(data.register);
      setConfig(next);
      setProviders(next.mail.providers || []);
      toast.success("注册任务已启动");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "启动注册任务失败");
    } finally { setAction(null); }
  };

  const runAction = async (name: string, callback: () => Promise<{ register: RegisterConfig }>) => {
    setAction(name);
    try {
      const data = await callback();
      const next = normalizeConfig(data.register);
      setConfig(next);
      setProviders(next.mail.providers || []);
    } catch (error) { toast.error(error instanceof Error ? error.message : "注册机操作失败"); }
    finally { setAction(null); }
  };

  const checkNow = async () => {
    setChecking(true);
    try {
      const data = await checkRegisterPool();
      const next = normalizeConfig(data.register);
      setConfig(next);
      setProviders(next.mail.providers || []);
      toast.success("已触发号池检查");
    } catch (error) { toast.error(error instanceof Error ? error.message : "号池检查失败"); }
    finally { setChecking(false); }
  };

  const updateProvider = (index: number, changes: Partial<RegisterProvider>) => setProviders((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, ...changes } : item));
  const switchProviderType = (index: number, type: string) => setProviders((current) => current.map((item, itemIndex) => itemIndex === index ? { ...defaultProvider(type), id: item.id || providerId(type), label: item.label || "", enable: item.enable !== false } : item));

  const checkGptMail = async (index: number, provider: RegisterProvider) => {
    setGptmailBusy(index);
    try {
      const data = await fetchGptMailStatus(provider, true);
      setGptmailStatus((current) => ({ ...current, [index]: data.status }));
      toast.success(data.status.ok === false ? "GPTMail 检测失败" : "GPTMail 状态已更新");
    } catch (error) { toast.error(error instanceof Error ? error.message : "GPTMail 检测失败"); }
    finally { setGptmailBusy(null); }
  };

  const maintainOutlook = async (scope: "retryable" | "invalid" | "unused" | "all") => {
    setAction(`outlook-${scope}`);
    try {
      const data = await resetOutlookPool(scope);
      const next = normalizeConfig(data.register);
      setConfig(next);
      setProviders(next.mail.providers || []);
      toast.success("Outlook 邮箱池状态已更新");
    } catch (error) { toast.error(error instanceof Error ? error.message : "Outlook 邮箱池维护失败"); }
    finally { setAction(null); }
  };

  if (loading || !config) return <div className="grid min-h-[60vh] place-items-center"><LoaderCircle className="size-5 animate-spin text-stone-400" /></div>;

  return (
    <main className="mx-auto box-border min-w-0 w-full max-w-full space-y-4 overflow-x-hidden px-0 py-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div><h1 className="text-2xl font-semibold text-stone-950 dark:text-white">注册机</h1><p className="mt-1 text-sm text-stone-500">注册成功后自动导入当前项目账号池。</p></div>
        <div className={`rounded-full px-3 py-1 text-xs font-medium ${phaseMeta.className}`}>{phaseMeta.label}</div>
      </div>

      <section className="grid min-w-0 grid-cols-2 gap-px overflow-hidden rounded-xl border border-stone-200/80 bg-stone-200/80 shadow-sm sm:grid-cols-5 dark:border-white/10 dark:bg-white/10">
        <Summary label="确认账号" value={confirmedAvailable} tone="emerald" />
        <Summary label={targetSummary.label} value={targetSummary.value} />
        <Summary label="确认额度" value={confirmedQuota} tone="emerald" />
        <Summary label="缓存额度" value={cachedQuota} tone="amber" />
        <Summary label="待确认账号" value={pendingAvailable} />
      </section>

      <section className="grid min-w-0 items-stretch gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(320px,1fr)]">
        <Card className="min-w-0 rounded-xl border-stone-200/80 shadow-none"><CardContent className="min-w-0 space-y-5 p-5">
          <SectionTitle title="任务参数" />
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <Field label="任务模式"><select disabled={running} value={config.mode} onChange={(event) => patch({ mode: event.target.value })} className="h-10 w-full rounded-md border border-stone-200 bg-white px-3 text-sm dark:border-white/10 dark:bg-stone-900"><option value="total">按注册总数</option><option value="quota">按目标剩余额度</option><option value="available">按目标可用账号</option></select></Field>
            <Field label={modeLabel}><Input disabled={running && config.mode === "total"} type="number" min="1" value={String(config.mode === "quota" ? config.target_quota : config.mode === "available" ? config.target_available : config.total)} onChange={(event) => patch(config.mode === "quota" ? { target_quota: Number(event.target.value) } : config.mode === "available" ? { target_available: Number(event.target.value) } : { total: Number(event.target.value) })} /></Field>
            <Field label="线程数"><Input disabled={running} type="number" min="1" value={String(config.threads)} onChange={(event) => patch({ threads: Number(event.target.value) })} /></Field>
            {config.mode !== "total" ? <Field label="检查间隔（秒）"><Input disabled={false} type="number" min="1" value={String(config.check_interval)} onChange={(event) => patch({ check_interval: Number(event.target.value) })} /></Field> : null}
          <Field label="注册代理模式"><select disabled={running} value={proxyMode} onChange={(event) => changeProxyMode(event.target.value)} className="h-10 w-full rounded-md border border-stone-200 bg-white px-3 text-sm dark:border-white/10 dark:bg-stone-900"><option value="default">使用系统默认代理</option><option value="direct">直连</option>{proxyGroups.filter((group) => group.enabled !== false).map((group) => <option key={group.id} value={`group:${group.id}`}>代理组：{group.name}</option>)}<option value="custom">自定义地址</option></select></Field>
          {proxyMode === "custom" ? <Field label="自定义代理"><Input disabled={running} value={config.proxy || ""} onChange={(event) => patch({ proxy: event.target.value })} placeholder="http://127.0.0.1:7890" /></Field> : null}
          </div>
          <div className="grid gap-3 border-t border-stone-100 pt-4 sm:grid-cols-2 lg:grid-cols-4 dark:border-white/10">
            <Field label="最大尝试次数"><Input disabled={running} type="number" min="1" value={String(config.max_attempts)} onChange={(event) => patch({ max_attempts: Number(event.target.value) })} /></Field>
            <Field label="连续失败上限"><Input disabled={running} type="number" min="1" value={String(config.max_consecutive_failures)} onChange={(event) => patch({ max_consecutive_failures: Number(event.target.value) })} /></Field>
            <Field label="最长运行（分钟）"><Input disabled={running} type="number" min="1" value={String(config.max_runtime_minutes)} onChange={(event) => patch({ max_runtime_minutes: Number(event.target.value) })} /></Field>
            <Field label="失败冷却（秒）"><Input disabled={running} type="number" min="30" value={String(config.retry_cooldown_seconds)} onChange={(event) => patch({ retry_cooldown_seconds: Number(event.target.value) })} /></Field>
            <Field label="限流冷却（秒）"><Input disabled={running} type="number" min="60" value={String(config.rate_limit_cooldown_seconds)} onChange={(event) => patch({ rate_limit_cooldown_seconds: Number(event.target.value) })} /></Field>
            <Field label="单账号预估额度"><Input disabled={running} type="number" min="1" value={String(config.expected_quota_per_account)} onChange={(event) => patch({ expected_quota_per_account: Number(event.target.value) })} /></Field>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="邮箱请求超时（秒）"><Input disabled={running} type="number" min="1" value={String(config.mail.request_timeout || 30)} onChange={(event) => patch({ mail: { ...config.mail, request_timeout: Number(event.target.value) } })} /></Field>
            <Field label="验证码等待（秒）"><Input disabled={running} type="number" min="1" value={String(config.mail.wait_timeout || 30)} onChange={(event) => patch({ mail: { ...config.mail, wait_timeout: Number(event.target.value) } })} /></Field>
            <Field label="轮询间隔（秒）"><Input disabled={running} type="number" min="1" value={String(config.mail.wait_interval || 2)} onChange={(event) => patch({ mail: { ...config.mail, wait_interval: Number(event.target.value) } })} /></Field>
          </div>
          <Field label="异常通知 Webhook"><Input value={config.alert_webhook_url} onChange={(event) => patch({ alert_webhook_url: event.target.value })} placeholder="https://example.com/webhook" /></Field>
          <label className="flex items-center gap-2 text-sm text-stone-600"><Checkbox disabled={running} checked={config.mail.api_use_register_proxy !== false} onCheckedChange={(checked) => patch({ mail: { ...config.mail, api_use_register_proxy: Boolean(checked) } })} />邮箱请求跟随注册代理</label>
        </CardContent></Card>

        <Card className="min-w-0 rounded-xl border-stone-200/80 bg-white shadow-none"><CardContent className="min-w-0 space-y-5 p-5">
          <SectionTitle title="执行控制" />
          <div className="grid grid-cols-2 gap-3"><Metric label="成功" value={stats.success || 0} /><Metric label="失败" value={stats.fail || 0} /><Metric label="完成" value={stats.done || 0} /><Metric label="在途" value={stats.running || 0} /></div>
          <div className="flex flex-wrap gap-2">
            <Button disabled={Boolean(action) || saving || running} onClick={() => void start()}>{action === "start" ? <LoaderCircle className="animate-spin" /> : <Play />}启动</Button>
            <Button variant="outline" disabled={Boolean(action) || saving || !running} onClick={() => void runAction("stop", stopRegister)}>{action === "stop" ? <LoaderCircle className="animate-spin" /> : <Square />}停止</Button>
            <Button variant="outline" disabled={Boolean(action) || saving || running} onClick={() => void runAction("reset", resetRegister)}>{action === "reset" ? <LoaderCircle className="animate-spin" /> : <RotateCcw />}重置</Button>
            <Button variant="outline" disabled={saving} onClick={() => void save()}>{saving ? <LoaderCircle className="animate-spin" /> : <Save />}保存</Button>
            <Button variant="outline" disabled={checking} onClick={() => void checkNow()}>{checking ? <LoaderCircle className="animate-spin" /> : <RefreshCw />}立即检查</Button>
          </div>
          <div className="text-xs leading-5 text-stone-500">确认账号：{confirmedAvailable}，确认额度：{confirmedQuota}，缓存额度：{cachedQuota}，成功率：{Number(stats.success_rate || 0).toFixed(1)}%{showNextCheck ? `，${nextCheckSeconds > 0 ? `下次检查 ${nextCheckSeconds} 秒后` : "等待检查"}` : ""}</div>
          {stats.stop_reason ? <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">状态说明：{String(stats.stop_reason)}</div> : null}
          {Object.keys(stats.channel_health || {}).length ? <div className="space-y-1 border-t border-stone-100 pt-3 text-xs text-stone-500 dark:border-white/10"><div className="font-medium text-stone-700 dark:text-stone-200">邮箱渠道健康</div>{Object.entries(stats.channel_health || {}).map(([name, health]) => <div key={name} className="flex justify-between gap-3"><span className="truncate">{name}</span><span className="shrink-0 text-stone-400">成功 {health.success || 0} / 失败 {health.fail || 0}</span></div>)}</div> : null}
          {config.history?.length ? <div className="space-y-1 border-t border-stone-100 pt-3 text-xs text-stone-500 dark:border-white/10"><div className="font-medium text-stone-700 dark:text-stone-200">最近补池</div>{config.history.slice().reverse().slice(0, 3).map((item) => <div key={item.id} className="flex justify-between gap-3"><span>{item.status === "completed" ? "完成" : item.status === "cooldown" ? "冷却" : "停止"} · {item.success || 0} 成功 / {item.fail || 0} 失败</span><span className="shrink-0">{formatRegisterLogTime(item.finished_at)}</span></div>)}</div> : null}
        </CardContent></Card>
      </section>

      <section className="grid min-w-0 items-start gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(320px,1fr)]">
        <Card className="min-w-0 rounded-xl border-stone-200/80 shadow-none"><CardContent className="min-w-0 space-y-4 p-5">
          <div className="flex flex-wrap items-center justify-between gap-3"><SectionTitle title="邮箱来源" /><Button type="button" variant="outline" disabled={running} onClick={() => setProviders((current) => [...current, defaultProvider()])}><Plus />添加来源</Button></div>
          <p className="text-xs leading-5 text-stone-500">每次注册会按启用顺序轮换邮箱来源。渠道名称仅用于区分配置，不会作为邮箱地址。</p>
          {providers.length === 0 ? <div className="rounded-md border border-dashed border-stone-200 px-4 py-8 text-center text-sm text-stone-500">暂无邮箱来源，请先添加。</div> : <div className="space-y-4">{providers.map((provider, index) => <RegisterProviderCard key={String(provider.id || `${provider.type}-${index}`)} provider={provider} index={index} disabled={running} gptStatus={gptmailStatus[index]} gptBusy={gptmailBusy === index} onCheckGptMail={() => void checkGptMail(index, provider)} onMaintainOutlook={(scope) => void maintainOutlook(scope)} onChange={(changes) => updateProvider(index, changes)} onTypeChange={(type) => switchProviderType(index, type)} onRemove={() => setProviders((current) => current.length <= 1 ? current : current.filter((_, itemIndex) => itemIndex !== index))} />)}</div>}
        </CardContent></Card>
        <Card className="min-w-0 rounded-xl border-stone-200/80 shadow-none xl:sticky xl:top-4"><CardContent className="min-w-0 space-y-4 p-5"><SectionTitle title="实时日志" /><div ref={logRef} className="h-[420px] min-w-0 space-y-2 overflow-y-auto overflow-x-hidden rounded-lg border border-stone-200 bg-stone-50/80 p-3 font-mono text-[11px] leading-5 text-stone-700 dark:border-white/10 dark:bg-stone-950 dark:text-stone-200">{config.logs?.length ? [...config.logs].reverse().map((log) => <div key={log.time} data-log-time={log.time} className="min-w-0 border-b border-stone-200/70 pb-1.5 last:border-0 dark:border-white/5"><span className="text-stone-400">{formatRegisterLogTime(log.time)}</span> <span className={`break-all ${log.level === "red" ? "text-red-600 dark:text-red-300" : log.level === "yellow" ? "text-amber-600 dark:text-amber-300" : "text-stone-700 dark:text-stone-200"}`}>{log.text}</span></div>) : <div className="text-stone-500">暂无日志</div>}</div></CardContent></Card>
      </section>
    </main>
  );
}

function RegisterProviderCard({ provider, index, disabled, gptStatus, gptBusy, onCheckGptMail, onMaintainOutlook, onChange, onTypeChange, onRemove }: { provider: RegisterProvider; index: number; disabled: boolean; gptStatus?: RegisterGptMailStatus; gptBusy: boolean; onCheckGptMail: () => void; onMaintainOutlook: (scope: "retryable" | "invalid" | "unused" | "all") => void; onChange: (changes: Partial<RegisterProvider>) => void; onTypeChange: (type: string) => void; onRemove: () => void }) {
  const type = String(provider.type || "cloudmail_gen");
  const missing = provider.enable === false ? [] : providerMissing(provider);
  const set = (key: keyof RegisterProvider, value: unknown) => onChange({ [key]: value } as Partial<RegisterProvider>);
  const input = (key: keyof RegisterProvider, label: string, options: { placeholder?: string; secret?: boolean; number?: boolean } = {}) => <Field label={label}><Input disabled={disabled} type={options.secret ? "password" : options.number ? "number" : "text"} value={String(provider[key] ?? "")} placeholder={options.placeholder || ""} onChange={(event) => set(key, options.number ? Number(event.target.value) : event.target.value)} /></Field>;
  const area = (key: keyof RegisterProvider, label: string, placeholder = "", asList = false) => {
    const raw = provider[key];
    const value = asList && Array.isArray(raw) ? raw.join("\n") : String(raw ?? "");
    return <Field label={label}><textarea disabled={disabled} value={value} placeholder={placeholder} onChange={(event) => set(key, asList ? event.target.value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean) : event.target.value)} className="min-h-24 w-full resize-y rounded-md border border-stone-200 bg-white p-2 font-mono text-xs dark:border-white/10 dark:bg-stone-900" /></Field>;
  };

  return <section className="min-w-0 space-y-4 overflow-hidden rounded-lg border border-stone-200 bg-stone-50/70 p-4 dark:border-white/10 dark:bg-stone-900/60">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex flex-wrap items-center gap-3"><label className="flex items-center gap-2 text-sm"><Checkbox disabled={disabled} checked={provider.enable !== false} onCheckedChange={(checked) => set("enable", Boolean(checked))} />启用</label><strong className="text-sm">邮箱来源 {index + 1}</strong>{missing.length ? <span className="text-xs text-red-600">缺少 {missing.length} 项</span> : provider.enable !== false ? <span className="text-xs text-emerald-600">配置完整</span> : null}</div>
      <Button type="button" size="icon" variant="outline" title="删除邮箱来源" disabled={disabled} onClick={onRemove}><Trash2 /></Button>
    </div>
    {missing.length ? <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">缺少：{missing.join("、")}</div> : null}
    <div className="grid min-w-0 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      <Field label="类型"><select disabled={disabled} value={type} onChange={(event) => onTypeChange(event.target.value)} className="h-10 w-full rounded-md border border-stone-200 bg-white px-3 text-sm dark:border-white/10 dark:bg-stone-950">{PROVIDER_TYPES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
      {input("label", "渠道名称（可选）", { placeholder: "例如：主渠道" })}
      {type === "cloudmail_gen" ? <>{input("api_base", "CloudMail URL")} {input("admin_email", "管理员邮箱")} {input("admin_password", "管理员密码", { secret: true })} {area("domain", "邮箱域名", "每行一个域名", true)} {area("subdomain", "子域名前缀", "每行一个，可留空", true)} {input("email_prefix", "邮箱前缀", { placeholder: "可选" })}</> : null}
      {type === "cloudflare_temp_email" ? <>{input("api_base", "API Base")} {input("admin_password", "管理员密码", { secret: true })} {area("domain", "域名", "每行一个域名", true)}</> : null}
      {type === "tempmail_lol" ? <>{input("api_key", "API Key", { secret: true })} {area("domain", "域名", "每行一个，可留空使用服务默认", true)}</> : null}
      {type === "moemail" ? <>{input("api_base", "API Base")} {input("api_key", "API Key", { secret: true })} {area("domain", "域名", "每行一个域名", true)} {input("expiry_time", "过期时间（秒）", { number: true })}</> : null}
      {type === "inbucket" ? <>{input("api_base", "API Base")} {area("domain", "基础域名", "每行一个基础域名", true)} <Toggle disabled={disabled} checked={Boolean(provider.random_subdomain)} onChange={(value) => set("random_subdomain", value)} label="随机子域名" /></> : null}
      {type === "duckmail" ? <>{input("api_key", "API Key", { secret: true })} {input("default_domain", "默认域名", { placeholder: "duckmail.sbs" })}</> : null}
      {type === "gptmail" ? <><Field label="Key 来源"><select disabled={disabled} value={String(provider.key_mode || "public")} onChange={(event) => set("key_mode", event.target.value)} className="h-10 w-full rounded-md border border-stone-200 bg-white px-3 text-sm dark:border-white/10 dark:bg-stone-900"><option value="public">公共测试 Key</option><option value="custom">自定义 Key</option></select></Field>{String(provider.key_mode || "public") === "custom" ? input("api_key", "API Key", { secret: true }) : null}{input("default_domain", "默认域名", { placeholder: "仅本地拼接时必填" })}<Toggle disabled={disabled} checked={Boolean(provider.local_compose)} onChange={(value) => set("local_compose", value)} label="已知域名本地拼接" /><div className="flex min-h-10 items-end gap-2"><Button type="button" size="sm" variant="outline" disabled={disabled || gptBusy} onClick={onCheckGptMail}>{gptBusy ? <LoaderCircle className="animate-spin" /> : <RefreshCw />}检测额度</Button>{gptStatus?.remaining_today != null ? <span className="pb-2 text-xs text-stone-500">今日剩余 {gptStatus.remaining_today}</span> : null}{gptStatus?.reset_at ? <span className="pb-2 text-xs text-stone-500">重置 {gptStatus.reset_at}</span> : null}</div></> : null}
      {type === "donemail" ? <>{input("api_base", "DoneMail URL", { placeholder: "https://sow.us.kg" })} {input("admin_key", "Admin Key", { secret: true })} {area("domain", "域名", "每行一个已接收域名", true)} {input("email_prefix", "邮箱前缀", { placeholder: "可选" })} {input("message_limit", "读取邮件数", { number: true })}</> : null}
      {type === "yyds_mail" ? <>{input("api_base", "API Base")} {input("api_key", "API Key", { secret: true })} {area("domain", "域名", "每行一个，可留空", true)} {input("subdomain", "Subdomain")} <Toggle disabled={disabled} checked={Boolean(provider.wildcard)} onChange={(value) => set("wildcard", value)} label="Wildcard" /></> : null}
      {type === "ddg_mail" ? <>{input("api_base", "CF API Base")} {input("ddg_token", "DDG Token", { secret: true })} {input("cf_inbox_jwt", "CF Inbox JWT", { secret: true })} {input("admin_password", "CF Admin Password", { secret: true })} {input("cf_api_key", "CF API Key", { secret: true })}<Field label="CF 鉴权方式"><select disabled={disabled} value={String(provider.cf_auth_mode || "none")} onChange={(event) => set("cf_auth_mode", event.target.value)} className="h-10 w-full rounded-md border border-stone-200 bg-white px-3 text-sm dark:border-white/10 dark:bg-stone-900"><option value="none">不附加</option><option value="bearer">Bearer</option><option value="x-api-key">X-API-Key</option><option value="query-key">Query Key</option></select></Field>{input("cf_create_path", "创建路径")} {input("cf_messages_path", "邮件列表路径")}</> : null}
      {type === "outlook_token" ? <><Field label="读取方式"><select disabled={disabled} value={String(provider.mode || "auto")} onChange={(event) => set("mode", event.target.value)} className="h-10 w-full rounded-md border border-stone-200 bg-white px-3 text-sm dark:border-white/10 dark:bg-stone-900"><option value="auto">自动兜底</option><option value="graph">Graph API</option><option value="imap">IMAP</option></select></Field>{provider.mode !== "graph" ? input("imap_host", "IMAP Host", { placeholder: "outlook.office365.com" }) : null}{input("message_limit", "读取邮件数", { number: true })}<Toggle disabled={disabled} checked={Boolean(provider.alias_enabled)} onChange={(value) => set("alias_enabled", value)} label="启用加号别名" />{provider.alias_enabled ? <>{input("alias_per_email", "每个邮箱别名数", { number: true })} {input("alias_prefix", "别名前缀")}<Toggle disabled={disabled} checked={provider.alias_include_original !== false} onChange={(value) => set("alias_include_original", value)} label="包含原邮箱" /></> : null}<div className="sm:col-span-2 lg:col-span-3">{area("mailboxes", "邮箱池导入（保存后不回显凭据）", "每行一个：邮箱----密码----client_id----refresh_token")}</div><div className="flex flex-wrap items-center gap-2 text-xs text-stone-500"><span>已保存 {Number(provider.mailboxes_base_count || 0)} 个基础邮箱，共 {Number(provider.mailboxes_count || 0)} 个地址。</span><Button type="button" size="sm" variant="outline" disabled={disabled} onClick={() => onMaintainOutlook("retryable")}><Wrench />释放失败</Button><Button type="button" size="sm" variant="outline" disabled={disabled} onClick={() => onMaintainOutlook("invalid")}>清除异常</Button><Button type="button" size="sm" variant="outline" disabled={disabled} onClick={() => onMaintainOutlook("unused")}>清理已用</Button><Button type="button" size="sm" variant="outline" disabled={disabled} onClick={() => onMaintainOutlook("all")}>重置状态</Button></div></> : null}
    </div>
  </section>;
}

function SectionTitle({ title, eyebrow, inverted = false }: { title: string; eyebrow?: string; inverted?: boolean }) { return <div>{eyebrow ? <div className="text-[10px] font-semibold tracking-[0.18em] text-stone-400">{eyebrow}</div> : null}<h2 className={`text-base font-semibold ${inverted ? "text-white" : "text-stone-900 dark:text-white"}`}>{title}</h2></div>; }
function Field({ label, children }: { label: string; children: ReactNode }) { return <label className="min-w-0 space-y-1.5"><span className="block text-xs text-stone-500">{label}</span>{children}</label>; }
function Metric({ label, value, inverted = false }: { label: string; value: number; inverted?: boolean }) { return <div className={`border border-stone-200/70 p-3 ${inverted ? "bg-stone-950" : "rounded-lg bg-stone-50/80 dark:border-white/10 dark:bg-stone-900"}`}><div className={`text-xs ${inverted ? "text-stone-400" : "text-stone-500"}`}>{label}</div><div className="mt-1 text-xl font-semibold tabular-nums">{value}</div></div>; }
function Summary({ label, value, tone = "stone" }: { label: string; value: string | number; tone?: "stone" | "emerald" | "amber" }) { const color = tone === "emerald" ? "text-emerald-600" : tone === "amber" ? "text-amber-600" : "text-stone-950 dark:text-white"; return <div className="min-w-0 bg-white/95 px-4 py-3 dark:bg-stone-900/95"><div className="text-[11px] text-stone-500">{label}</div><div className={`mt-0.5 truncate text-lg font-semibold tabular-nums ${color}`}>{value}</div></div>; }
function Toggle({ label, checked, disabled, onChange }: { label: string; checked: boolean; disabled: boolean; onChange: (value: boolean) => void }) { return <label className="flex min-h-10 items-center gap-2 text-sm"><Checkbox disabled={disabled} checked={checked} onCheckedChange={(value) => onChange(Boolean(value))} />{label}</label>; }
