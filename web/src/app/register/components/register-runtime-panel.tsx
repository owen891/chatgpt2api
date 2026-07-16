import type { RefObject } from "react";

import { LoaderCircle, Play, RefreshCw, RotateCcw, Save, Square } from "lucide-react";

import { Button } from "@/components/ui/button";

import {
  type RegisterLogEntry,
  SectionTitle,
  formatRegisterLogTime,
  getRegisterLogToneMeta,
  normalizeRegisterLogTone,
} from "../register-shared";

function formatElapsed(value: unknown) {
  const seconds = Math.max(0, Number(value) || 0);
  if (seconds >= 3600) return `${(seconds / 3600).toFixed(1)}h`;
  if (seconds >= 60) return `${Math.round(seconds / 60)}m`;
  return `${Math.round(seconds)}s`;
}

function RuntimeMetric({
  label,
  value,
  hint,
}: {
  label: string;
  value: string | number;
  hint?: string;
}) {
  return (
    <div className="rounded-xl border border-stone-200/80 bg-stone-50/70 px-4 py-3">
      <div className="text-xs text-stone-500">{label}</div>
      <div className="mt-1 text-3xl font-semibold tabular-nums text-stone-900 dark:text-white">{value}</div>
      {hint ? <div className="mt-1 text-xs text-stone-400">{hint}</div> : null}
    </div>
  );
}

export function RegisterRuntimePanel({
  action,
  checking,
  running,
  saving,
  stats,
  configuredThreads,
  confirmedAvailable,
  confirmedQuota,
  onStart,
  onStop,
  onReset,
  onSave,
  onCheckNow,
}: {
  action: string | null;
  checking: boolean;
  running: boolean;
  saving: boolean;
  stats: Record<string, unknown>;
  configuredThreads: number;
  confirmedAvailable: number;
  confirmedQuota: number;
  onStart: () => void;
  onStop: () => void;
  onReset: () => void;
  onSave: () => void;
  onCheckNow: () => void;
}) {
  const success = Number(stats.success || 0);
  const fail = Number(stats.fail || 0);
  const done = Number(stats.done || 0);
  const inflight = Number(stats.running || 0);
  const avgSeconds = Number(stats.avg_seconds || 0);
  const successRate = Number(stats.success_rate || 0);
  const elapsed = formatElapsed(stats.elapsed_seconds);
  const stopReason = String(stats.stop_reason || "").trim();
  const lastCheckAt = String(stats.last_check_at || "").trim();

  return (
    <section className="min-w-0 rounded-xl border border-stone-200/80 bg-white shadow-none">
      <div className="space-y-4 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <SectionTitle title="执行控制" />
          <span
            className={`rounded-full px-3 py-1 text-xs font-medium ${
              running ? "bg-emerald-100 text-emerald-700" : "bg-stone-100 text-stone-500"
            }`}
          >
            {running ? "运行中" : "未启动"}
          </span>
        </div>

        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <RuntimeMetric label="成功" value={success} hint={`成功率 ${successRate.toFixed(1)}%`} />
          <RuntimeMetric label="失败" value={fail} />
          <RuntimeMetric label="完成" value={done} />
          <RuntimeMetric label="运行 / 线程" value={`${inflight} / ${configuredThreads}`} />
          <RuntimeMetric label="运行时间" value={elapsed} />
          <RuntimeMetric label="平均耗时" value={`${avgSeconds.toFixed(1)}s`} />
          <RuntimeMetric label="当前额度" value={confirmedQuota} />
          <RuntimeMetric label="正常账号" value={confirmedAvailable} />
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <Button
            size="lg"
            className="h-12"
            disabled={Boolean(action) || saving || running}
            onClick={onStart}
          >
            {action === "start" ? <LoaderCircle className="animate-spin" /> : <Play />}
            启动
          </Button>
          <Button
            size="lg"
            variant="outline"
            className="h-12"
            disabled={Boolean(action) || saving || !running}
            onClick={onStop}
          >
            {action === "stop" ? <LoaderCircle className="animate-spin" /> : <Square />}
            停止
          </Button>
          <Button
            variant="outline"
            className="h-11"
            disabled={saving}
            onClick={onSave}
          >
            {saving ? <LoaderCircle className="animate-spin" /> : <Save />}
            保存配置
          </Button>
          <Button
            variant="outline"
            className="h-11"
            disabled={checking}
            onClick={onCheckNow}
          >
            {checking ? <LoaderCircle className="animate-spin" /> : <RefreshCw />}
            刷新状态
          </Button>
        </div>

        <Button
          variant="outline"
          className="h-11 w-full"
          disabled={Boolean(action) || saving || running}
          onClick={onReset}
        >
          {action === "reset" ? <LoaderCircle className="animate-spin" /> : <RotateCcw />}
          重置
        </Button>

        <div className="rounded-xl border border-stone-200/80 bg-stone-50/50 px-4 py-3 text-sm text-stone-600">
          <div>当前确认可用账号：{confirmedAvailable}</div>
          <div className="mt-1">当前确认剩余额度：{confirmedQuota}</div>
          <div className="mt-1">最近平均耗时：{avgSeconds.toFixed(1)}s</div>
          {lastCheckAt ? <div className="mt-1">最近检查：{lastCheckAt}</div> : null}
        </div>

        {stopReason ? (
          <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
            停止原因：{stopReason}
          </div>
        ) : (
          <div className="rounded-xl border border-stone-200/80 bg-white px-4 py-3 text-sm text-stone-500">
            启动前建议先保存配置；运行中可随时刷新状态查看补池进展。
          </div>
        )}
      </div>
    </section>
  );
}

export function RegisterLogPanel({
  logRef,
  logs,
}: {
  logRef: RefObject<HTMLDivElement | null>;
  logs: RegisterLogEntry[] | undefined;
}) {
  const entries = logs?.length ? [...logs].reverse() : [];
  const counts = entries.reduce(
    (result, entry) => {
      const tone = normalizeRegisterLogTone(entry.level);
      result[tone] += 1;
      return result;
    },
    { info: 0, warning: 0, error: 0 },
  );

  return (
    <section className="min-w-0 rounded-xl border border-stone-200/80 bg-white shadow-none xl:sticky xl:top-4">
      <div className="space-y-4 p-4">
        <div className="flex items-start justify-between gap-3">
          <SectionTitle title="实时日志" />
          <div className="text-right text-xs text-stone-500">
            <div>{entries.length} 条</div>
            <div>错 {counts.error} / 警 {counts.warning} / 信 {counts.info}</div>
          </div>
        </div>

        <div
          ref={logRef}
          className="h-[620px] min-w-0 space-y-2 overflow-y-auto overflow-x-hidden rounded-md border border-stone-200 p-2"
        >
          {entries.length ? (
            entries.map((log, index) => {
              const meta = getRegisterLogToneMeta(log.level);
              const borderClassName =
                meta.tone === "error"
                  ? "border-red-200"
                  : meta.tone === "warning"
                    ? "border-amber-200"
                    : "border-stone-200";

              return (
                <article
                  key={`${log.time}-${index}`}
                  data-log-time={log.time}
                  className={`min-w-0 rounded-md border px-3 py-2 ${borderClassName}`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] ${meta.badgeClassName}`}>
                      {meta.label}
                    </span>
                    <span className="shrink-0 text-[10px] tabular-nums text-stone-400">
                      {formatRegisterLogTime(log.time)}
                    </span>
                  </div>
                  <div className="mt-1.5 break-all font-mono text-[11px] leading-5 text-stone-700 dark:text-stone-100">
                    {log.text}
                  </div>
                </article>
              );
            })
          ) : (
            <div className="rounded-md border border-dashed border-stone-200 px-4 py-8 text-center text-sm text-stone-500">
              暂无日志
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
