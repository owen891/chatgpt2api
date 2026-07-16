"use client";

import { useLayoutEffect, useRef } from "react";
import { LoaderCircle } from "lucide-react";

import { RegisterProvidersPanel } from "./components/register-providers-panel";
import { RegisterLogPanel, RegisterRuntimePanel } from "./components/register-runtime-panel";
import { RegisterSettingsPanel } from "./components/register-settings-panel";
import { defaultProvider } from "./register-shared";
import { useRegisterPageRuntime } from "./use-register-page-runtime";

export default function RegisterPage() {
  const {
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
        const prependedHeight =
          firstRow && previousNewestRow
            ? previousNewestRow.offsetTop - firstRow.offsetTop
            : Math.max(0, heightDelta);
        panel.scrollTop += Math.max(0, prependedHeight);
      }
    }

    previousNewestLogRef.current = newestLogTime;
    previousLogHeightRef.current = panel.scrollHeight;
  }, [newestLogTime]);

  const phaseMeta = {
    starting: { label: "启动中", className: "bg-amber-100 text-amber-700" },
    monitoring: { label: "监控中", className: "bg-emerald-100 text-emerald-700" },
    registering: { label: "补池中", className: "bg-blue-100 text-blue-700" },
    stopped: { label: "已停止", className: "bg-stone-100 text-stone-500" },
  }[phase] || {
    label: running ? "运行中" : "已停止",
    className: running ? "bg-emerald-100 text-emerald-700" : "bg-stone-100 text-stone-500",
  };

  if (loading || !config) {
    return (
      <div className="grid min-h-[60vh] place-items-center">
        <LoaderCircle className="size-5 animate-spin text-stone-400" />
      </div>
    );
  }

  return (
    <main className="mx-auto box-border min-w-0 w-full max-w-[1380px] space-y-4 overflow-x-hidden px-0 py-5">
      <section className="rounded-xl border border-stone-200/80 bg-white px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold text-stone-950 dark:text-white">注册机</h1>
            <p className="mt-1 text-sm text-stone-500">模式：{modeLabel}</p>
          </div>
          <div className={`rounded-full px-3 py-1 text-xs font-medium ${phaseMeta.className}`}>{phaseMeta.label}</div>
        </div>

        <div className="mt-4 flex flex-wrap gap-x-8 gap-y-2 border-t border-stone-100 pt-3 text-sm dark:border-white/10">
          <StatusLine label="目标进度" value={targetSummary.value} />
          <StatusLine label="可用账号" value={confirmedAvailable} tone="emerald" />
          <StatusLine label="剩余额度" value={confirmedQuota} tone="emerald" />
        </div>
      </section>

      <section className="grid min-w-0 gap-4 xl:grid-cols-2">
        <RegisterSettingsPanel
          config={config}
          running={running}
          modeLabel={modeLabel}
          onPatch={patch}
        />

        <RegisterRuntimePanel
          action={action}
          checking={checking}
          running={running}
          saving={saving}
          stats={stats as Record<string, unknown>}
          configuredThreads={config.threads}
          confirmedAvailable={confirmedAvailable}
          confirmedQuota={confirmedQuota}
          onStart={() => void start()}
          onStop={() => void stopTask()}
          onReset={() => void resetTask()}
          onSave={() => void save()}
          onCheckNow={() => void checkNow()}
        />
      </section>

      <section className="grid min-w-0 gap-4 xl:grid-cols-2">
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
          onRemove={(index) =>
            setProviders((current) =>
              current.length <= 1 ? current : current.filter((_, itemIndex) => itemIndex !== index),
            )
          }
        />

        <RegisterLogPanel logRef={logRef} logs={config.logs} />
      </section>
    </main>
  );
}

function StatusLine({
  label,
  value,
  tone = "stone",
}: {
  label: string;
  value: string | number;
  tone?: "stone" | "emerald";
}) {
  const valueClassName = tone === "emerald" ? "text-emerald-600" : "text-stone-900 dark:text-white";

  return (
    <div className="flex items-center gap-2">
      <span className="text-stone-500">{label}</span>
      <span className={`font-semibold tabular-nums ${valueClassName}`}>{value}</span>
    </div>
  );
}
