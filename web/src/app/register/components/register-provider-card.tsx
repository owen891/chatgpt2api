import { LoaderCircle, RefreshCw, Trash2, Wrench } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { RegisterGptMailStatus, RegisterProvider } from "@/lib/api";

import { Field, PROVIDER_TYPES, ProviderInput, Toggle, providerMissing } from "../register-shared";

export function RegisterProviderCard({
  provider,
  index,
  disabled,
  gptStatus,
  gptBusy,
  onCheckGptMail,
  onMaintainOutlook,
  onChange,
  onTypeChange,
  onRemove,
}: {
  provider: RegisterProvider;
  index: number;
  disabled: boolean;
  gptStatus?: RegisterGptMailStatus;
  gptBusy: boolean;
  onCheckGptMail: () => void;
  onMaintainOutlook: (scope: "retryable" | "invalid" | "unused" | "all") => void;
  onChange: (changes: Partial<RegisterProvider>) => void;
  onTypeChange: (type: string) => void;
  onRemove: () => void;
}) {
  const type = String(provider.type || "cloudmail_gen");
  const missing = provider.enable === false ? [] : providerMissing(provider);
  const setValue = (key: keyof RegisterProvider, value: unknown) => onChange({ [key]: value } as Partial<RegisterProvider>);
  const area = (key: keyof RegisterProvider, label: string, placeholder = "", asList = false) => {
    const raw = provider[key];
    const value = asList && Array.isArray(raw) ? raw.join("\n") : String(raw ?? "");
    return <Field label={label}><textarea disabled={disabled} value={value} placeholder={placeholder} onChange={(event) => setValue(key, asList ? event.target.value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean) : event.target.value)} className="min-h-24 w-full resize-y rounded-md border border-stone-200 bg-white p-2 font-mono text-xs dark:border-white/10 dark:bg-stone-900" /></Field>;
  };

  return <section className="min-w-0 space-y-4 overflow-hidden rounded-lg border border-stone-200 bg-stone-50/70 p-4 dark:border-white/10 dark:bg-stone-900/60">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex flex-wrap items-center gap-3"><label className="flex items-center gap-2 text-sm"><input disabled={disabled} checked={provider.enable !== false} onChange={(event) => setValue("enable", event.target.checked)} type="checkbox" className="size-4 accent-stone-900" />启用</label><strong className="text-sm">邮箱来源 {index + 1}</strong>{missing.length ? <span className="text-xs text-red-600">缺少 {missing.length} 项</span> : provider.enable !== false ? <span className="text-xs text-emerald-600">已就绪</span> : null}</div>
      <Button type="button" size="icon" variant="outline" title="删除邮箱来源" disabled={disabled} onClick={onRemove}><Trash2 /></Button>
    </div>
    {missing.length ? <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">缺少必填项：{missing.join("、")}</div> : null}
    <div className="grid min-w-0 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      <Field label="类型"><select disabled={disabled} value={type} onChange={(event) => onTypeChange(event.target.value)} className="h-10 w-full rounded-md border border-stone-200 bg-white px-3 text-sm dark:border-white/10 dark:bg-stone-950">{PROVIDER_TYPES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
      <ProviderInput disabled={disabled} provider={provider} setValue={setValue} field="label" label="渠道名称" placeholder="主渠道" />
      {type === "cloudmail_gen" ? <><ProviderInput disabled={disabled} provider={provider} setValue={setValue} field="api_base" label="CloudMail 地址" /> <ProviderInput disabled={disabled} provider={provider} setValue={setValue} field="admin_email" label="管理员邮箱" /> <ProviderInput disabled={disabled} provider={provider} setValue={setValue} field="admin_password" label="管理员密码" secret /> {area("domain", "域名", "每行一个域名", true)} {area("subdomain", "子域名", "每行一个前缀", true)} <ProviderInput disabled={disabled} provider={provider} setValue={setValue} field="email_prefix" label="邮箱前缀" placeholder="可选" /></> : null}
      {type === "cloudflare_temp_email" ? <><ProviderInput disabled={disabled} provider={provider} setValue={setValue} field="api_base" label="API 地址" /> <ProviderInput disabled={disabled} provider={provider} setValue={setValue} field="admin_password" label="管理员密码" secret /> {area("domain", "域名", "每行一个域名", true)}</> : null}
      {type === "tempmail_lol" ? <><ProviderInput disabled={disabled} provider={provider} setValue={setValue} field="api_key" label="API 密钥" secret /> {area("domain", "域名", "每行一个域名", true)}</> : null}
      {type === "moemail" ? <><ProviderInput disabled={disabled} provider={provider} setValue={setValue} field="api_base" label="API 地址" /> <ProviderInput disabled={disabled} provider={provider} setValue={setValue} field="api_key" label="API 密钥" secret /> {area("domain", "域名", "每行一个域名", true)} <ProviderInput disabled={disabled} provider={provider} setValue={setValue} field="expiry_time" label="有效期（秒）" number /></> : null}
      {type === "inbucket" ? <><ProviderInput disabled={disabled} provider={provider} setValue={setValue} field="api_base" label="API 地址" /> {area("domain", "基础域名", "每行一个域名", true)} <Toggle disabled={disabled} checked={Boolean(provider.random_subdomain)} onChange={(value) => setValue("random_subdomain", value)} label="随机子域名" /></> : null}
      {type === "duckmail" ? <><ProviderInput disabled={disabled} provider={provider} setValue={setValue} field="api_key" label="API 密钥" secret /> <ProviderInput disabled={disabled} provider={provider} setValue={setValue} field="default_domain" label="默认域名" placeholder="duckmail.sbs" /></> : null}
      {type === "gptmail" ? <><Field label="密钥来源"><select disabled={disabled} value={String(provider.key_mode || "public")} onChange={(event) => setValue("key_mode", event.target.value)} className="h-10 w-full rounded-md border border-stone-200 bg-white px-3 text-sm dark:border-white/10 dark:bg-stone-900"><option value="public">公共测试密钥</option><option value="custom">自定义密钥</option></select></Field>{String(provider.key_mode || "public") === "custom" ? <ProviderInput disabled={disabled} provider={provider} setValue={setValue} field="api_key" label="API 密钥" secret /> : null}<ProviderInput disabled={disabled} provider={provider} setValue={setValue} field="default_domain" label="默认域名" placeholder="本地拼接时必填" /><Toggle disabled={disabled} checked={Boolean(provider.local_compose)} onChange={(value) => setValue("local_compose", value)} label="使用已知域名本地拼接" /><div className="flex min-h-10 items-end gap-2"><Button type="button" size="sm" variant="outline" disabled={disabled || gptBusy} onClick={onCheckGptMail}>{gptBusy ? <LoaderCircle className="animate-spin" /> : <RefreshCw />}检查额度</Button>{gptStatus?.remaining_today != null ? <span className="pb-2 text-xs text-stone-500">今日剩余 {gptStatus.remaining_today}</span> : null}{gptStatus?.reset_at ? <span className="pb-2 text-xs text-stone-500">重置时间 {gptStatus.reset_at}</span> : null}</div></> : null}
      {type === "donemail" ? <><ProviderInput disabled={disabled} provider={provider} setValue={setValue} field="api_base" label="DoneMail 地址" placeholder="https://example.com" /> <ProviderInput disabled={disabled} provider={provider} setValue={setValue} field="admin_key" label="管理员密钥" secret /> {area("domain", "域名", "每行一个域名", true)} <ProviderInput disabled={disabled} provider={provider} setValue={setValue} field="email_prefix" label="邮箱前缀" placeholder="可选" /> <ProviderInput disabled={disabled} provider={provider} setValue={setValue} field="message_limit" label="邮件数量上限" number /></> : null}
      {type === "yyds_mail" ? <><ProviderInput disabled={disabled} provider={provider} setValue={setValue} field="api_base" label="API 地址" /> <ProviderInput disabled={disabled} provider={provider} setValue={setValue} field="api_key" label="API 密钥" secret /> {area("domain", "域名", "每行一个域名", true)} <ProviderInput disabled={disabled} provider={provider} setValue={setValue} field="subdomain" label="子域名" /> <Toggle disabled={disabled} checked={Boolean(provider.wildcard)} onChange={(value) => setValue("wildcard", value)} label="通配域名" /></> : null}
      {type === "ddg_mail" ? <><ProviderInput disabled={disabled} provider={provider} setValue={setValue} field="api_base" label="CF API 地址" /> <ProviderInput disabled={disabled} provider={provider} setValue={setValue} field="ddg_token" label="DDG 令牌" secret /> <ProviderInput disabled={disabled} provider={provider} setValue={setValue} field="cf_inbox_jwt" label="CF 收件箱 JWT" secret /> <ProviderInput disabled={disabled} provider={provider} setValue={setValue} field="admin_password" label="CF 管理员密码" secret /> <ProviderInput disabled={disabled} provider={provider} setValue={setValue} field="cf_api_key" label="CF API 密钥" secret /><Field label="CF 鉴权模式"><select disabled={disabled} value={String(provider.cf_auth_mode || "none")} onChange={(event) => setValue("cf_auth_mode", event.target.value)} className="h-10 w-full rounded-md border border-stone-200 bg-white px-3 text-sm dark:border-white/10 dark:bg-stone-900"><option value="none">无</option><option value="bearer">Bearer</option><option value="x-api-key">X-API-Key</option><option value="query-key">Query Key</option></select></Field><ProviderInput disabled={disabled} provider={provider} setValue={setValue} field="cf_create_path" label="创建接口路径" /> <ProviderInput disabled={disabled} provider={provider} setValue={setValue} field="cf_messages_path" label="邮件接口路径" /></> : null}
      {type === "outlook_token" ? <><Field label="读取模式"><select disabled={disabled} value={String(provider.mode || "auto")} onChange={(event) => setValue("mode", event.target.value)} className="h-10 w-full rounded-md border border-stone-200 bg-white px-3 text-sm dark:border-white/10 dark:bg-stone-900"><option value="auto">自动回退</option><option value="graph">Graph API</option><option value="imap">IMAP</option></select></Field>{provider.mode !== "graph" ? <ProviderInput disabled={disabled} provider={provider} setValue={setValue} field="imap_host" label="IMAP 主机" placeholder="outlook.office365.com" /> : null}<ProviderInput disabled={disabled} provider={provider} setValue={setValue} field="message_limit" label="邮件数量上限" number /><Toggle disabled={disabled} checked={Boolean(provider.alias_enabled)} onChange={(value) => setValue("alias_enabled", value)} label="启用别名" />{provider.alias_enabled ? <><ProviderInput disabled={disabled} provider={provider} setValue={setValue} field="alias_per_email" label="每个邮箱的别名数" number /> <ProviderInput disabled={disabled} provider={provider} setValue={setValue} field="alias_prefix" label="别名前缀" /><Toggle disabled={disabled} checked={provider.alias_include_original !== false} onChange={(value) => setValue("alias_include_original", value)} label="包含原始邮箱" /></> : null}<div className="sm:col-span-2 lg:col-span-3">{area("mailboxes", "导入邮箱", "email----password----client_id----refresh_token")}</div><div className="flex flex-wrap items-center gap-2 text-xs text-stone-500"><span>已保存 {Number(provider.mailboxes_base_count || 0)} 个基础邮箱，共 {Number(provider.mailboxes_count || 0)} 个可用地址。</span><Button type="button" size="sm" variant="outline" disabled={disabled} onClick={() => onMaintainOutlook("retryable")}><Wrench />释放失败项</Button><Button type="button" size="sm" variant="outline" disabled={disabled} onClick={() => onMaintainOutlook("invalid")}>清理无效项</Button><Button type="button" size="sm" variant="outline" disabled={disabled} onClick={() => onMaintainOutlook("unused")}>清理未使用项</Button><Button type="button" size="sm" variant="outline" disabled={disabled} onClick={() => onMaintainOutlook("all")}>重置邮箱池</Button></div></> : null}
    </div>
  </section>;
}
