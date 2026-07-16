import type { RefObject } from "react";

import { LoaderCircle, Play, RefreshCw, RotateCcw, Save, Square } from "lucide-react";

import { Button } from "@/components/ui/button";

import {
  type RegisterLogEntry,
  Metric,
  SectionTitle,
  formatRegisterLogTime,
  getRegisterLogToneMeta,
  normalizeRegisterLogTone,
} from "../register-shared";

export function RegisterRuntimePanel({
  action,
  checking,
  running,
  saving,
  stats,
  confirmedAvailable,
  confirmedQuota,
  cachedQuota,
  showNextCheck,
  nextCheckSeconds,
  history,
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
  confirmedAvailable: number;
  confirmedQuota: number;
  cachedQuota: number;
  showNextCheck: boolean;
  nextCheckSeconds: number;
  history: Array<{ id: string; status: string; success?: number; fail?: number; finished_at: string }> | undefined;
  onStart: () => void;
  onStop: () => void;
  onReset: () => void;
  onSave: () => void;
  onCheckNow: () => void;
}) {
  return <div className="min-w-0 rounded-xl border border-stone-200/80 bg-white p-5 shadow-none">
    <div className="space-y-5">
      <SectionTitle title="执行控制" />
      <div className="grid grid-cols-2 gap-3">
        <Metric label="成功" value={Number(stats.success || 0)} />
        <Metric label="失败" value={Number(stats.fail || 0)} />
        <Metric label="完成" value={Number(stats.done || 0)} />
        <Metric label="运行中" value={Number(stats.running || 0)} />
      </div>
      <div className="flex flex-wrap gap-2">
        <Button disabled={Boolean(action) || saving || running} onClick={onStart}>
          {action === "start" ? <LoaderCircle className="animate-spin" /> : <Play />}
          启动
        </Button>
        <Button variant="outline" disabled={Boolean(action) || saving || !running} onClick={onStop}>
          {action === "stop" ? <LoaderCircle className="animate-spin" /> : <Square />}
          停止
        </Button>
        <Button variant="outline" disabled={Boolean(action) || saving || running} onClick={onReset}>
          {action === "reset" ? <LoaderCircle className="animate-spin" /> : <RotateCcw />}
          重置
        </Button>
        <Button variant="outline" disabled={saving} onClick={onSave}>
          {saving ? <LoaderCircle className="animate-spin" /> : <Save />}
          保存
        </Button>
        <Button variant="outline" disabled={checking} onClick={onCheckNow}>
          {checking ? <LoaderCircle className="animate-spin" /> : <RefreshCw />}
          立即检查
        </Button>
      </div>
      <div className="text-xs leading-5 text-stone-500">
        确认账号: {confirmedAvailable}，确认额度: {confirmedQuota}，缓存额度: {cachedQuota}，成功率: {Number(stats.success_rate || 0).toFixed(1)}%
        {showNextCheck ? `，${nextCheckSeconds > 0 ? `下次检查 ${nextCheckSeconds} 秒后` : "等待检查"}` : ""}
      </div>
      {stats.stop_reason ? <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">状态说明: {String(stats.stop_reason)}</div> : null}
      {Object.keys((stats.channel_health as Record<string, { success?: number; fail?: number }> | undefined) || {}).length ? <div className="space-y-1 border-t border-stone-100 pt-3 text-xs text-stone-500 dark:border-white/10">
        <div className="font-medium text-stone-700 dark:text-stone-200">邮箱渠道健康</div>
        {Object.entries((stats.channel_health as Record<string, { success?: number; fail?: number }> | undefined) || {}).map(([name, health]) => <div key={name} className="flex justify-between gap-3">
          <span className="truncate">{name}</span>
          <span className="shrink-0 text-stone-400">成功 {health.success || 0} / 失败 {health.fail || 0}</span>
        </div>)}
      </div> : null}
      {history?.length ? <div className="space-y-1 border-t border-stone-100 pt-3 text-xs text-stone-500 dark:border-white/10">
        <div className="font-medium text-stone-700 dark:text-stone-200">最近补池</div>
        {history.slice().reverse().slice(0, 3).map((item) => <div key={item.id} className="flex justify-between gap-3">
          <span>{item.status === "completed" ? "完成" : item.status === "cooldown" ? "冷却" : "停止"} · {item.success || 0} 成功 / {item.fail || 0} 失败</span>
          <span className="shrink-0">{formatRegisterLogTime(item.finished_at)}</span>
        </div>)}
      </div> : null}
    </div>
  </div>;
}

function LogSummaryMetric({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "error" | "warning" | "info";
}) {
  const styles = tone === "error"
    ? "border-red-100 bg-red-50/55 text-red-700 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-200"
    : tone === "warning"
      ? "border-amber-100 bg-amber-50/55 text-amber-700 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-200"
      : "border-stone-200 bg-white/90 text-stone-700 dark:border-white/10 dark:bg-stone-900 dark:text-stone-100";

  return <div className={`rounded-lg border px-3 py-2 ${styles}`}>
    <div className="text-[11px]">{label}</div>
    <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
  </div>;
}

export function RegisterLogPanel({
  logRef,
  logs,
}: {
  logRef: RefObject<HTMLDivElement | null>;
  logs: RegisterLogEntry[] | undefined;
}) {
  const entries = logs?.length ? [...logs].reverse() : [];
  const counts = entries.reduce((result, entry) => {
    const tone = normalizeRegisterLogTone(entry.level);
    result[tone] += 1;
    return result;
  }, { info: 0, warning: 0, error: 0 });

  return <div className="min-w-0 rounded-xl border border-stone-200/80 bg-white/95 shadow-none xl:sticky xl:top-4">
    <div className="min-w-0 space-y-4 p-5">
      <div className="flex items-start justify-between gap-3">
        <SectionTitle title="实时日志" />
        <span className="rounded-full border border-stone-200 bg-stone-50 px-2.5 py-1 text-[11px] text-stone-500 dark:border-white/10 dark:bg-stone-900 dark:text-stone-300">
          {entries.length} 条
        </span>
      </div>

      <div className="grid grid-cols-3 gap-2">
        <LogSummaryMetric label="错误" value={counts.error} tone="error" />
        <LogSummaryMetric label="警告" value={counts.warning} tone="warning" />
        <LogSummaryMetric label="信息" value={counts.info} tone="info" />
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-stone-200/70 bg-stone-50/70 px-3 py-2 text-[11px] text-stone-500 dark:border-white/10 dark:bg-stone-900/70 dark:text-stone-300">
        <span>最新日志显示在上方</span>
        <span>紧凑排版，优先看内容本身</span>
      </div>

      <div className="rounded-lg border border-stone-200/80 bg-[linear-gradient(180deg,rgba(250,248,244,0.9),rgba(246,243,238,0.72))] p-2 dark:border-white/10 dark:bg-stone-950">
        <div
          ref={logRef}
          className="h-[540px] min-w-0 space-y-1.5 overflow-y-auto overflow-x-hidden pr-1"
        >
          {entries.length ? entries.map((log, index) => {
            const meta = getRegisterLogToneMeta(log.level);
            const accent = meta.tone === "error"
              ? "border-l-red-400"
              : meta.tone === "warning"
                ? "border-l-amber-400"
                : "border-l-stone-300 dark:border-l-stone-700";
            const dot = meta.tone === "error"
              ? "bg-red-500"
              : meta.tone === "warning"
                ? "bg-amber-500"
                : "bg-stone-400";

            return <article
              key={`${log.time}-${index}`}
              data-log-time={log.time}
              className={`min-w-0 rounded-md border border-stone-200/80 border-l-[3px] bg-white/92 px-3 py-2 shadow-[0_1px_0_rgba(28,25,23,0.04)] transition-colors hover:bg-white dark:border-white/10 dark:bg-stone-900/85 dark:hover:bg-stone-900 ${accent}`}
            >
              <div className="flex items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2">
                  <span className={`h-2 w-2 shrink-0 rounded-full ${dot}`} />
                  <span className={`inline-flex shrink-0 items-center rounded-full border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.14em] ${meta.badgeClassName}`}>
                    {meta.label}
                  </span>
                </div>
                <span className="shrink-0 text-[10px] tabular-nums text-stone-400">
                  {formatRegisterLogTime(log.time)}
                </span>
              </div>
              <div className="mt-1.5 break-all font-mono text-[11px] leading-5 text-stone-700 dark:text-stone-100">
                {log.text}
              </div>
            </article>;
          }) : <div className="rounded-lg border border-dashed border-stone-200 bg-white/70 px-4 py-8 text-center text-sm text-stone-500 dark:border-white/10 dark:bg-stone-900/70">暂无日志</div>}
        </div>
      </div>
    </div>
  </div>;
}
