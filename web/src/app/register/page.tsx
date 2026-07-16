"use client";

import { useLayoutEffect, useRef } from "react";
import { LoaderCircle } from "lucide-react";

import { RegisterDiagnosticsPanel } from "./components/register-diagnostics-panel";
import { RegisterProvidersPanel } from "./components/register-providers-panel";
import { RegisterLogPanel, RegisterRuntimePanel } from "./components/register-runtime-panel";
import { RegisterSettingsPanel } from "./components/register-settings-panel";
import { Summary, defaultProvider } from "./register-shared";
import { useRegisterPageRuntime } from "./use-register-page-runtime";

export default function RegisterPage() {
  const {
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
  } = useRegisterPageRuntime();

  const logRef = useRef<HTMLDivElement | null>(null);
  const previousNewestLogRef = useRef("");
  const previousLogHeightRef = useRef(0);

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

  const phaseMeta = {
    starting: { label: "正在启动", className: "bg-amber-100 text-amber-700" },
    monitoring: { label: "监控中", className: "bg-emerald-100 text-emerald-700" },
    registering: { label: "补池中", className: "bg-blue-100 text-blue-700" },
    cooldown: { label: "冷却中", className: "bg-amber-100 text-amber-700" },
    stopping: { label: "正在停止", className: "bg-amber-100 text-amber-700" },
    stopped: { label: "已停止", className: "bg-stone-100 text-stone-500" },
  }[phase] || { label: running ? "运行中" : "已停止", className: running ? "bg-emerald-100 text-emerald-700" : "bg-stone-100 text-stone-500" };

  if (loading || !config) {
    return <div className="grid min-h-[60vh] place-items-center"><LoaderCircle className="size-5 animate-spin text-stone-400" /></div>;
  }

  return (
    <main className="mx-auto box-border min-w-0 w-full max-w-full space-y-4 overflow-x-hidden px-0 py-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-stone-950 dark:text-white">注册机</h1>
          <p className="mt-1 text-sm text-stone-500">注册成功后自动导入当前项目账号池。</p>
        </div>
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
        <RegisterSettingsPanel
          config={config}
          running={running}
          modeLabel={modeLabel}
          proxyMode={proxyMode}
          proxyGroups={proxyGroups}
          onPatch={patch}
          onChangeProxyMode={changeProxyMode}
        />

        <RegisterRuntimePanel
          action={action}
          checking={checking}
          running={running}
          saving={saving}
          stats={stats as Record<string, unknown>}
          confirmedAvailable={confirmedAvailable}
          confirmedQuota={confirmedQuota}
          cachedQuota={cachedQuota}
          showNextCheck={showNextCheck}
          nextCheckSeconds={nextCheckSeconds}
          history={config.history}
          onStart={() => void start()}
          onStop={() => void stopTask()}
          onReset={() => void resetTask()}
          onSave={() => void save()}
          onCheckNow={() => void checkNow()}
        />
      </section>

      <section className="grid min-w-0 items-start gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(320px,1fr)]">
        <RegisterProvidersPanel
          providers={providers}
          running={running}
          gptmailStatus={gptmailStatus}
          gptmailBusy={gptmailBusy}
          onAddProvider={() => setProviders((current) => [...current, defaultProvider()])}
          onCheckGptMail={(index, provider) => void checkGptMail(index, provider)}
          onMaintainOutlook={(scope) => void maintainOutlook(scope)}
          onChange={updateProvider}
          onTypeChange={switchProviderType}
          onRemove={(index) => setProviders((current) => current.length <= 1 ? current : current.filter((_, itemIndex) => itemIndex !== index))}
        />

        <RegisterLogPanel logRef={logRef} logs={config.logs} />
      </section>

      <RegisterDiagnosticsPanel
        diagnostics={diagnostics as Record<string, unknown>}
        funnelEntries={funnelEntries}
        providerEntries={providerEntries}
        egressEntries={egressEntries}
        failureKindEntries={failureKindEntries}
        recentFailures={recentFailures}
      />
    </main>
  );
}
