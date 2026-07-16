import { Card, CardContent } from "@/components/ui/card";

import { Metric, STAGE_LABELS, SectionTitle, formatDurationMs, formatRegisterLogTime } from "../register-shared";

export function RegisterDiagnosticsPanel({
  diagnostics,
  funnelEntries,
  providerEntries,
  egressEntries,
  failureKindEntries,
  recentFailures,
}: {
  diagnostics: Record<string, unknown>;
  funnelEntries: Array<[string, Record<string, number>]>;
  providerEntries: Array<[string, Record<string, unknown>]>;
  egressEntries: Array<[string, Record<string, unknown>]>;
  failureKindEntries: Array<[string, number]>;
  recentFailures: Array<Record<string, unknown>>;
}) {
  if (!funnelEntries.length && !providerEntries.length && !egressEntries.length && !failureKindEntries.length && !recentFailures.length) return null;

  return <section className="grid min-w-0 items-start gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(360px,1fr)]">
    <Card className="min-w-0 rounded-xl border-stone-200/80 shadow-none xl:h-[760px]">
      <CardContent className="flex h-full min-w-0 min-h-0 flex-col space-y-4 p-5">
        <SectionTitle title="注册诊断" />

        <div className="grid grid-cols-3 gap-3">
          <Metric label="尝试" value={Number(diagnostics.attempts || 0)} />
          <Metric label="成功" value={Number(diagnostics.success || 0)} />
          <Metric label="失败" value={Number(diagnostics.fail || 0)} />
        </div>

        {failureKindEntries.length ? <div className="flex flex-wrap gap-2">
          {failureKindEntries.map(([name, count]) => <span key={name} className="rounded-full bg-stone-100 px-2.5 py-1 text-xs text-stone-600 dark:bg-white/10 dark:text-stone-300">{name} · {count}</span>)}
        </div> : null}

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto pr-1">
          {funnelEntries.length ? <div className="space-y-2 border-t border-stone-100 pt-4 text-sm dark:border-white/10">
            <div className="font-medium text-stone-800 dark:text-stone-100">阶段漏斗</div>
            {funnelEntries.map(([stage, item]) => <div key={stage} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-stone-200/70 bg-stone-50/70 px-3 py-2 text-xs dark:border-white/10 dark:bg-stone-900/60">
              <div className="min-w-0">
                <div className="truncate font-medium text-stone-700 dark:text-stone-200">{STAGE_LABELS[stage] || stage}</div>
                <div className="text-stone-500">到达 {Number(item.reached || 0)} / 成功 {Number(item.success || 0)} / 失败 {Number(item.fail || 0)} / 重试 {Number(item.retries || 0)}</div>
              </div>
              <div className="shrink-0 text-stone-500">平均 {formatDurationMs(Number(item.avg_duration_ms || 0))}</div>
            </div>)}
          </div> : null}

          {providerEntries.length ? <div className="space-y-2 border-t border-stone-100 pt-4 text-sm dark:border-white/10">
            <div className="font-medium text-stone-800 dark:text-stone-100">邮箱渠道表现</div>
            {providerEntries.map(([name, item]) => <div key={name} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-stone-200/70 bg-white px-3 py-2 text-xs dark:border-white/10 dark:bg-stone-900">
              <div className="min-w-0">
                <div className="truncate font-medium text-stone-700 dark:text-stone-200">{name}</div>
                <div className="text-stone-500">成功 {Number(item.success || 0)} / 失败 {Number(item.fail || 0)} / 平均 {formatDurationMs(Number(item.avg_duration_ms || 0))}</div>
              </div>
              <div className="shrink-0 text-right text-stone-400">
                <div>{String(item.last_flow || "unknown")}</div>
                {item.last_at ? <div>{formatRegisterLogTime(String(item.last_at))}</div> : null}
              </div>
            </div>)}
          </div> : null}

          {egressEntries.length ? <div className="space-y-2 border-t border-stone-100 pt-4 text-sm dark:border-white/10">
            <div className="font-medium text-stone-800 dark:text-stone-100">出口表现</div>
            {egressEntries.map(([name, item]) => {
              const statusEntries = Object.entries((item.status_codes as Record<string, number> | undefined) || {});
              return <div key={name} className="space-y-2 rounded-lg border border-stone-200/70 bg-stone-50/80 px-3 py-3 text-xs dark:border-white/10 dark:bg-stone-900/60">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate font-medium text-stone-700 dark:text-stone-200">{name}</div>
                    <div className="text-stone-500">成功 {Number(item.success || 0)} / 失败 {Number(item.fail || 0)} / 平均 {formatDurationMs(Number(item.avg_duration_ms || 0))}</div>
                  </div>
                  <div className="shrink-0 text-right text-stone-400">
                    <div>{String(item.proxy_source || "direct")} · {String(item.clearance_mode || "none")}</div>
                    {item.last_at ? <div>{formatRegisterLogTime(String(item.last_at))}</div> : null}
                  </div>
                </div>
                <div className="flex flex-wrap gap-2 text-[11px]">
                  <span className="rounded-full bg-white px-2 py-1 text-stone-600 dark:bg-stone-950 dark:text-stone-300">egress: {String(item.egress_mode || "direct")}</span>
                  <span className="rounded-full bg-white px-2 py-1 text-stone-600 dark:bg-stone-950 dark:text-stone-300">clearance refresh {Number(item.clearance_refresh_success || 0)} / {Number(item.clearance_refresh_attempts || 0)}</span>
                  {Number(item.cloudflare_blocks || 0) > 0 ? <span className="rounded-full bg-red-50 px-2 py-1 text-red-700 dark:bg-red-500/10 dark:text-red-200">Cloudflare 拦截 {Number(item.cloudflare_blocks || 0)}</span> : null}
                  {item.last_status_code ? <span className="rounded-full bg-white px-2 py-1 text-stone-600 dark:bg-stone-950 dark:text-stone-300">last status {String(item.last_status_code)}</span> : null}
                  {item.last_cf_ray ? <span className="rounded-full bg-white px-2 py-1 text-stone-600 dark:bg-stone-950 dark:text-stone-300">cf-ray {String(item.last_cf_ray)}</span> : null}
                </div>
                {statusEntries.length ? <div className="flex flex-wrap gap-2">
                  {statusEntries.map(([status, count]) => <span key={status} className="rounded-full bg-stone-100 px-2 py-1 text-[11px] text-stone-600 dark:bg-white/10 dark:text-stone-300">HTTP {status} · {count}</span>)}
                </div> : null}
              </div>;
            })}
          </div> : null}
        </div>
      </CardContent>
    </Card>

    <Card className="min-w-0 rounded-xl border-stone-200/80 shadow-none xl:sticky xl:top-4 xl:h-[760px]">
      <CardContent className="flex h-full min-w-0 min-h-0 flex-col space-y-4 p-5">
        <SectionTitle title="最近失败" />
        {recentFailures.length ? <div className="min-h-0 flex-1 space-y-2 overflow-y-auto pr-1 text-xs text-stone-500">
          {[...recentFailures].reverse().slice(0, 10).map((item, index) => <div key={`${String(item.at || index)}-${index}`} className="rounded-lg border border-red-100 bg-red-50/70 px-3 py-2 dark:border-red-500/20 dark:bg-red-500/10">
            <div className="flex flex-wrap items-center justify-between gap-2 text-red-700 dark:text-red-200">
              <span>{String(item.provider || "unknown")} · {String(item.stage || "unknown")}</span>
              <span>{formatDurationMs(Number(item.duration_ms || 0))}</span>
            </div>
            <div className="mt-1 text-stone-500">{String(item.failure_kind || "registration_error")} · {String(item.flow || "unknown")}</div>
            {(item.proxy_label || item.clearance_mode || item.status_code || item.cf_ray) ? <div className="mt-1 text-stone-500">
              {String(item.proxy_label || "direct")}
              {item.clearance_mode ? ` · ${String(item.clearance_mode)}` : ""}
              {item.status_code ? ` · HTTP ${String(item.status_code)}` : ""}
              {item.cf_ray ? ` · cf-ray ${String(item.cf_ray)}` : ""}
            </div> : null}
            <div className="mt-1 break-all text-stone-500">{String(item.error || "")}</div>
            {item.at ? <div className="mt-1 text-stone-400">{formatRegisterLogTime(String(item.at))}</div> : null}
          </div>)}
        </div> : <div className="rounded-lg border border-dashed border-stone-200 px-4 py-6 text-sm text-stone-500 dark:border-white/10">暂无失败记录</div>}
      </CardContent>
    </Card>
  </section>;
}
