import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import webConfig from "@/constants/common-env";
import {
  checkRegisterPool,
  fetchGptMailStatus,
  fetchRegisterConfig,
  resetOutlookPool,
  resetRegister,
  startRegister,
  stopRegister,
  updateRegisterConfig,
  type RegisterConfig,
  type RegisterGptMailStatus,
  type RegisterProvider,
} from "@/lib/api";
import { getStoredAuthKey } from "@/store/auth";

import { defaultProvider, mergeRuntimeSnapshot, normalizeConfig, providerId, providerMissing } from "./register-shared";

export function useRegisterPageRuntime() {
  const [config, setConfig] = useState<RegisterConfig | null>(null);
  const [providers, setProviders] = useState<RegisterProvider[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [action, setAction] = useState<string | null>(null);
  const [gptmailStatus, setGptmailStatus] = useState<Record<number, RegisterGptMailStatus>>({});
  const [gptmailBusy, setGptmailBusy] = useState<number | null>(null);
  const [checking, setChecking] = useState(false);

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
    if (!config?.enabled) return;
    const timer = window.setInterval(() => void load(true), 2000);
    return () => window.clearInterval(timer);
  }, [config?.enabled]);

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
        const authKey = await getStoredAuthKey();
        if (!authKey) {
          scheduleReconnect();
          return;
        }
        if (!active) return;
        const apiBaseUrl = webConfig.apiUrl.replace(/\/$/, "") || window.location.origin;
        const nextSource = new EventSource(`${apiBaseUrl}/api/register/events?token=${encodeURIComponent(authKey)}`);
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
            // Ignore malformed payloads; next event or poll will self-heal.
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
  const inferredPhase = running
    ? Number(stats.running || 0) > 0
      ? "registering"
      : config?.mode === "total"
        ? "starting"
        : "monitoring"
    : "stopped";
  const phase = String(stats.phase || inferredPhase);
  const confirmedQuota = Number(stats.current_quota || 0);
  const confirmedAvailable = Number(stats.current_available || 0);
  const modeLabel = useMemo(() => ({ total: "注册总数", quota: "目标剩余额度", available: "目标可用账号" }[config?.mode || "total"] || "注册总数"), [config?.mode]);
  const targetSummary = config?.mode === "quota"
    ? { label: "确认额度进度", value: `${confirmedQuota} / ${config.target_quota}` }
    : config?.mode === "available"
      ? { label: "确认账号进度", value: `${confirmedAvailable} / ${config.target_available}` }
      : { label: "注册进度", value: `${stats.done || 0} / ${config?.total || 0}` };

  const patch = (changes: Partial<RegisterConfig>) => {
    setConfig((current) => current ? normalizeConfig({ ...current, ...changes }) : current);
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
      toast.success("注册机状态已刷新");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "刷新注册机状态失败");
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
    gptmailStatus,
    gptmailBusy,
    checking,
    running,
    stats,
    phase,
    confirmedQuota,
    confirmedAvailable,
    modeLabel,
    targetSummary,
    patch,
    save,
    start,
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
