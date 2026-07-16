import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import webConfig from "@/constants/common-env";
import {
  checkRegisterPool,
  createRegisterEventTicket,
  fetchGptMailStatus,
  fetchRegisterConfig,
  fetchRegisterProxyGroups,
  resetOutlookPool,
  resetRegister,
  startRegister,
  stopRegister,
  updateRegisterConfig,
  type RegisterConfig,
  type RegisterGptMailStatus,
  type RegisterProvider,
  type RegisterProxyGroup,
} from "@/lib/api";

import { defaultProvider, mergeRuntimeSnapshot, normalizeConfig, providerId, providerMissing } from "./register-shared";

export function useRegisterPageRuntime() {
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

  const load = async (runtimeOnly = false) => {
    try {
      const data = await fetchRegisterConfig();
      const next = normalizeConfig(data.register);
      if (runtimeOnly) {
        setConfig((current) => current ? mergeRuntimeSnapshot(current, next) : next);
        return;
      }
      setConfig(next);
      setProviders(next.mail.providers || []);
      setProxyMode(next.proxy === "direct" ? "direct" : next.proxy?.startsWith("group:") ? next.proxy : next.proxy ? "custom" : "default");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "加载注册机配置失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

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
        nextSource.onopen = () => {
          reconnectAttempt = 0;
        };
        nextSource.onmessage = (event) => {
          try {
            const raw = JSON.parse(event.data);
            const next = normalizeConfig(raw.register || raw);
            setConfig((current) => current ? mergeRuntimeSnapshot(current, next) : next);
          } catch {
            // Ignore malformed event payloads. The next SSE or polling pass will correct it.
          }
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

  const running = Boolean(config?.enabled);
  const stats = config?.stats || {};
  const phase = String(stats.phase || (running ? "starting" : "stopped"));
  const confirmedQuota = Number(stats.current_quota || 0);
  const cachedQuota = Number(stats.estimated_quota || 0);
  const confirmedAvailable = Number(stats.current_available || 0);
  const pendingAvailable = Number(stats.unconfirmed_available || 0);
  const nextCheckAt = stats.next_check_at ? new Date(String(stats.next_check_at)).getTime() : 0;
  const nextCheckSeconds = nextCheckAt > now ? Math.ceil((nextCheckAt - now) / 1000) : 0;
  const showNextCheck = Boolean(config?.enabled && nextCheckAt && (phase === "monitoring" || phase === "cooldown"));
  const modeLabel = useMemo(() => ({ total: "注册总数", quota: "目标剩余额度", available: "目标可用账号" }[config?.mode || "total"] || "注册总数"), [config?.mode]);
  const targetSummary = config?.mode === "quota"
    ? { label: "确认额度进度", value: `${confirmedQuota} / ${config.target_quota}` }
    : config?.mode === "available"
      ? { label: "确认账号进度", value: `${confirmedAvailable} / ${config.target_available}` }
      : { label: "注册进度", value: `${stats.done || 0} / ${config?.total || 0}` };
  const diagnostics = typeof stats.diagnostics === "object" && stats.diagnostics ? stats.diagnostics : {};
  const funnelEntries = Object.entries((diagnostics.funnel as Record<string, Record<string, number>> | undefined) || {});
  const providerEntries = Object.entries((diagnostics.providers as Record<string, Record<string, unknown>> | undefined) || {});
  const egressEntries = Object.entries((diagnostics.egresses as Record<string, Record<string, unknown>> | undefined) || {}).sort((a, b) => {
    const left = Number(b[1]?.fail || 0) + Number(b[1]?.success || 0);
    const right = Number(a[1]?.fail || 0) + Number(a[1]?.success || 0);
    return left - right;
  });
  const failureKindEntries = Object.entries((diagnostics.failure_kinds as Record<string, number> | undefined) || {}).sort((a, b) => b[1] - a[1]);
  const recentFailures = Array.isArray(diagnostics.recent_failures) ? diagnostics.recent_failures as Array<Record<string, unknown>> : [];

  const patch = (changes: Partial<RegisterConfig>) => {
    setConfig((current) => current ? normalizeConfig({ ...current, ...changes }) : current);
  };

  const changeProxyMode = (mode: string) => {
    setProxyMode(mode);
    if (mode === "direct") patch({ proxy: "direct" });
    else if (mode.startsWith("group:")) {
      const group = proxyGroups.find((item) => `group:${item.id}` === mode);
      const node = group?.nodes?.find((item) => item.enabled !== false);
      patch({ proxy: node?.name || "" });
    } else if (mode === "default") {
      patch({ proxy: "" });
    } else if (config?.proxy === "direct" || config?.proxy?.startsWith("group:")) {
      patch({ proxy: "" });
    }
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
    try {
      await persist();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "保存注册机配置失败");
    } finally {
      setSaving(false);
    }
  };

  const start = async () => {
    const enabledProviders = providers.filter((provider) => provider.enable !== false);
    if (!enabledProviders.length) {
      toast.error("请先添加并启用至少一个邮箱渠道");
      return;
    }
    const invalid = enabledProviders
      .map((provider, index) => ({ provider, index, missing: providerMissing(provider) }))
      .find((item) => item.missing.length);
    if (invalid) {
      toast.error(`邮箱来源 ${invalid.index + 1} 缺少: ${invalid.missing.join(", ")}`);
      return;
    }

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
    } finally {
      setAction(null);
    }
  };

  const runAction = async (name: string, callback: () => Promise<{ register: RegisterConfig }>) => {
    setAction(name);
    try {
      const data = await callback();
      const next = normalizeConfig(data.register);
      setConfig(next);
      setProviders(next.mail.providers || []);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "注册机操作失败");
    } finally {
      setAction(null);
    }
  };

  const checkNow = async () => {
    setChecking(true);
    try {
      const data = await checkRegisterPool();
      const next = normalizeConfig(data.register);
      setConfig(next);
      setProviders(next.mail.providers || []);
      toast.success("已触发号池检查");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "号池检查失败");
    } finally {
      setChecking(false);
    }
  };

  const stopTask = async () => {
    await runAction("stop", stopRegister);
  };

  const resetTask = async () => {
    await runAction("reset", resetRegister);
  };

  const updateProvider = (index: number, changes: Partial<RegisterProvider>) => {
    setProviders((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, ...changes } : item));
  };

  const switchProviderType = (index: number, type: string) => {
    setProviders((current) => current.map((item, itemIndex) => itemIndex === index ? { ...defaultProvider(type), id: item.id || providerId(type), label: item.label || "", enable: item.enable !== false } : item));
  };

  const checkGptMail = async (index: number, provider: RegisterProvider) => {
    setGptmailBusy(index);
    try {
      const data = await fetchGptMailStatus(provider, true);
      setGptmailStatus((current) => ({ ...current, [index]: data.status }));
      toast.success(data.status.ok === false ? "GPTMail 检测失败" : "GPTMail 状态已更新");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "GPTMail 检测失败");
    } finally {
      setGptmailBusy(null);
    }
  };

  const maintainOutlook = async (scope: "retryable" | "invalid" | "unused" | "all") => {
    setAction(`outlook-${scope}`);
    try {
      const data = await resetOutlookPool(scope);
      const next = normalizeConfig(data.register);
      setConfig(next);
      setProviders(next.mail.providers || []);
      toast.success("Outlook 邮箱池状态已更新");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Outlook 邮箱池维护失败");
    } finally {
      setAction(null);
    }
  };

  return {
    config,
    providers,
    loading,
    saving,
    action,
    proxyGroups,
    proxyMode,
    gptmailStatus,
    gptmailBusy,
    checking,
    running,
    stats,
    phase,
    confirmedQuota,
    cachedQuota,
    confirmedAvailable,
    pendingAvailable,
    nextCheckSeconds,
    showNextCheck,
    modeLabel,
    targetSummary,
    diagnostics,
    funnelEntries,
    providerEntries,
    egressEntries,
    failureKindEntries,
    recentFailures,
    patch,
    changeProxyMode,
    save,
    start,
    runAction,
    checkNow,
    stopTask,
    resetTask,
    setProviders,
    updateProvider,
    switchProviderType,
    checkGptMail,
    maintainOutlook,
  };
}
