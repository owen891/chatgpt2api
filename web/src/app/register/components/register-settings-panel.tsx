import { Checkbox } from "@/components/ui/checkbox";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import type { RegisterConfig, RegisterProxyGroup } from "@/lib/api";

import { Field, SectionTitle } from "../register-shared";

export function RegisterSettingsPanel({
  config,
  running,
  modeLabel,
  proxyMode,
  proxyGroups,
  onPatch,
  onChangeProxyMode,
}: {
  config: RegisterConfig;
  running: boolean;
  modeLabel: string;
  proxyMode: string;
  proxyGroups: RegisterProxyGroup[];
  onPatch: (changes: Partial<RegisterConfig>) => void;
  onChangeProxyMode: (mode: string) => void;
}) {
  return <Card className="min-w-0 rounded-xl border-stone-200/80 shadow-none">
    <CardContent className="min-w-0 space-y-5 p-5">
      <SectionTitle title="任务参数" />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <Field label="任务模式">
          <select
            disabled={running}
            value={config.mode}
            onChange={(event) => onPatch({ mode: event.target.value })}
            className="h-10 w-full rounded-md border border-stone-200 bg-white px-3 text-sm dark:border-white/10 dark:bg-stone-900"
          >
            <option value="total">按注册总数</option>
            <option value="quota">按目标剩余额度</option>
            <option value="available">按目标可用账号</option>
          </select>
        </Field>

        <Field label={modeLabel}>
          <Input
            disabled={running && config.mode === "total"}
            type="number"
            min="1"
            value={String(
              config.mode === "quota"
                ? config.target_quota
                : config.mode === "available"
                  ? config.target_available
                  : config.total,
            )}
            onChange={(event) => onPatch(
              config.mode === "quota"
                ? { target_quota: Number(event.target.value) }
                : config.mode === "available"
                  ? { target_available: Number(event.target.value) }
                  : { total: Number(event.target.value) },
            )}
          />
        </Field>

        <Field label="线程数">
          <Input
            disabled={running}
            type="number"
            min="1"
            value={String(config.threads)}
            onChange={(event) => onPatch({ threads: Number(event.target.value) })}
          />
        </Field>

        {config.mode !== "total" ? <Field label="检查间隔（秒）">
          <Input
            type="number"
            min="1"
            value={String(config.check_interval)}
            onChange={(event) => onPatch({ check_interval: Number(event.target.value) })}
          />
        </Field> : null}

        <Field label="注册代理模式">
          <select
            disabled={running}
            value={proxyMode}
            onChange={(event) => onChangeProxyMode(event.target.value)}
            className="h-10 w-full rounded-md border border-stone-200 bg-white px-3 text-sm dark:border-white/10 dark:bg-stone-900"
          >
            <option value="default">使用系统默认代理</option>
            <option value="direct">直连</option>
            {proxyGroups.filter((group) => group.enabled !== false).map((group) => <option key={group.id} value={`group:${group.id}`}>代理组: {group.name}</option>)}
            <option value="custom">自定义地址</option>
          </select>
        </Field>

        {proxyMode === "custom" ? <Field label="自定义代理">
          <Input
            disabled={running}
            value={config.proxy || ""}
            onChange={(event) => onPatch({ proxy: event.target.value })}
            placeholder="http://127.0.0.1:7890"
          />
        </Field> : null}
      </div>

      {config.mode !== "total" ? <div className="rounded-lg border border-stone-200/70 bg-stone-50/70 px-3 py-2 text-xs leading-5 text-stone-500 dark:border-white/10 dark:bg-stone-900/70 dark:text-stone-300">
        当前补池规则：只要低于目标值，就立即开始补池；达到目标值后再进入监控。
      </div> : null}

      <div className="grid gap-3 border-t border-stone-100 pt-4 sm:grid-cols-2 lg:grid-cols-4 dark:border-white/10">
        <Field label="最大尝试次数">
          <Input disabled={running} type="number" min="1" value={String(config.max_attempts)} onChange={(event) => onPatch({ max_attempts: Number(event.target.value) })} />
        </Field>
        <Field label="连续失败上限">
          <Input disabled={running} type="number" min="1" value={String(config.max_consecutive_failures)} onChange={(event) => onPatch({ max_consecutive_failures: Number(event.target.value) })} />
        </Field>
        <Field label="最长运行（分钟）">
          <Input disabled={running} type="number" min="1" value={String(config.max_runtime_minutes)} onChange={(event) => onPatch({ max_runtime_minutes: Number(event.target.value) })} />
        </Field>
        <Field label="失败冷却（秒）">
          <Input disabled={running} type="number" min="30" value={String(config.retry_cooldown_seconds)} onChange={(event) => onPatch({ retry_cooldown_seconds: Number(event.target.value) })} />
        </Field>
        <Field label="限流冷却（秒）">
          <Input disabled={running} type="number" min="60" value={String(config.rate_limit_cooldown_seconds)} onChange={(event) => onPatch({ rate_limit_cooldown_seconds: Number(event.target.value) })} />
        </Field>
        <Field label="单账号预估额度">
          <Input disabled={running} type="number" min="1" value={String(config.expected_quota_per_account)} onChange={(event) => onPatch({ expected_quota_per_account: Number(event.target.value) })} />
        </Field>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="邮箱请求超时（秒）">
          <Input disabled={running} type="number" min="1" value={String(config.mail.request_timeout || 30)} onChange={(event) => onPatch({ mail: { ...config.mail, request_timeout: Number(event.target.value) } })} />
        </Field>
        <Field label="验证码等待（秒）">
          <Input disabled={running} type="number" min="1" value={String(config.mail.wait_timeout || 30)} onChange={(event) => onPatch({ mail: { ...config.mail, wait_timeout: Number(event.target.value) } })} />
        </Field>
        <Field label="轮询间隔（秒）">
          <Input disabled={running} type="number" min="1" value={String(config.mail.wait_interval || 2)} onChange={(event) => onPatch({ mail: { ...config.mail, wait_interval: Number(event.target.value) } })} />
        </Field>
      </div>

      <Field label="异常通知 Webhook">
        <Input value={config.alert_webhook_url} onChange={(event) => onPatch({ alert_webhook_url: event.target.value })} placeholder="https://example.com/webhook" />
      </Field>

      <label className="flex items-center gap-2 text-sm text-stone-600">
        <Checkbox disabled={running} checked={config.mail.api_use_register_proxy !== false} onCheckedChange={(checked) => onPatch({ mail: { ...config.mail, api_use_register_proxy: Boolean(checked) } })} />
        邮箱请求跟随注册代理
      </label>
    </CardContent>
  </Card>;
}
