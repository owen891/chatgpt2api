import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import type { RegisterConfig } from "@/lib/api";

import { Field, SectionTitle } from "../register-shared";

export function RegisterSettingsPanel({
  config,
  running,
  modeLabel,
  onPatch,
}: {
  config: RegisterConfig;
  running: boolean;
  modeLabel: string;
  onPatch: (changes: Partial<RegisterConfig>) => void;
}) {
  return (
    <section className="min-w-0 rounded-xl border border-stone-200/80 bg-white shadow-none">
      <div className="min-w-0 space-y-4 p-4">
        <SectionTitle title="基础参数" />

        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Field label="任务模式">
            <select
              disabled={running}
              value={config.mode}
              onChange={(event) => onPatch({ mode: event.target.value })}
              className="h-10 w-full rounded-md border border-stone-200 bg-white px-3 text-sm dark:border-white/10 dark:bg-stone-950"
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
              onChange={(event) =>
                onPatch(
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

          {config.mode !== "total" ? (
            <Field label="检查间隔（秒）">
              <Input
                type="number"
                min="1"
                value={String(config.check_interval)}
                onChange={(event) => onPatch({ check_interval: Number(event.target.value) })}
              />
            </Field>
          ) : (
            <Field label="注册代理">
              <Input
                disabled={running}
                value={config.proxy || ""}
                onChange={(event) => onPatch({ proxy: event.target.value })}
                placeholder="留空继承全局代理"
              />
            </Field>
          )}
        </div>

        {config.mode !== "total" ? (
          <div className="text-xs text-stone-500">
            当前模式会持续检查号池，只要低于目标值就继续补池。
          </div>
        ) : null}

        <div className="space-y-3 border-t border-stone-100 pt-4 dark:border-white/10">
          <SectionTitle title="网络与邮箱等待" />
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {config.mode !== "total" ? (
              <Field label="注册代理">
                <Input
                  disabled={running}
                  value={config.proxy || ""}
                  onChange={(event) => onPatch({ proxy: event.target.value })}
                  placeholder="留空继承全局代理"
                />
              </Field>
            ) : null}

            <Field label="429 冷却时间（秒）">
              <Input
                disabled={running}
                type="number"
                min="60"
                value={String(config.rate_limit_cooldown_seconds || 900)}
                onChange={(event) => onPatch({ rate_limit_cooldown_seconds: Number(event.target.value) })}
              />
            </Field>

            <Field label="邮箱请求超时（秒）">
              <Input
                disabled={running}
                type="number"
                min="1"
                value={String(config.mail.request_timeout || 30)}
                onChange={(event) =>
                  onPatch({ mail: { ...config.mail, request_timeout: Number(event.target.value) } })
                }
              />
            </Field>

            <Field label="验证码等待（秒）">
              <Input
                disabled={running}
                type="number"
                min="1"
                value={String(config.mail.wait_timeout || 30)}
                onChange={(event) =>
                  onPatch({ mail: { ...config.mail, wait_timeout: Number(event.target.value) } })
                }
              />
            </Field>

            <Field label="轮询间隔（秒）">
              <Input
                disabled={running}
                type="number"
                min="1"
                value={String(config.mail.wait_interval || 2)}
                onChange={(event) =>
                  onPatch({ mail: { ...config.mail, wait_interval: Number(event.target.value) } })
                }
              />
            </Field>
          </div>
        </div>

        <label className="flex items-center gap-2 text-sm text-stone-600">
          <Checkbox
            disabled={running}
            checked={config.mail.api_use_register_proxy !== false}
            onCheckedChange={(checked) =>
              onPatch({ mail: { ...config.mail, api_use_register_proxy: Boolean(checked) } })
            }
          />
          邮箱请求跟随注册代理
        </label>
      </div>
    </section>
  );
}
