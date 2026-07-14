"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { CheckCircle2, LoaderCircle, Plus, RefreshCw, Save, Trash2, XCircle } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { fetchImageUpstreamModels, fetchImageUpstreamStatus, testImageUpstream, type ImageUpstreamChannel, type ImageUpstreamRuntimeStatus, type ImageUpstreamTestResult } from "@/lib/api";

import { useSettingsStore } from "../store";

function createChannel(): ImageUpstreamChannel {
  return {
    id: crypto.randomUUID(), name: "新生图上游", model_alias: "", enabled: true, priority: 10, default: false,
    base_url: "", api_key: "", has_api_key: false, clear_api_key: false, timeout_secs: 90, proxy_url: "",
    supports_generation: true, supports_edits: true, failure_threshold: 3, cooldown_secs: 120, max_concurrency: 3, requests_per_minute: 60,
    model_mappings: [{ client_model: "gpt-image-2", upstream_model: "gpt-image-1" }],
  };
}

export function ImageUpstreamsCard() {
  const config = useSettingsStore((state) => state.config);
  const isLoadingConfig = useSettingsStore((state) => state.isLoadingConfig);
  const isSavingConfig = useSettingsStore((state) => state.isSavingConfig);
  const saveConfig = useSettingsStore((state) => state.saveConfig);
  const [results, setResults] = useState<Record<string, ImageUpstreamTestResult>>({});
  const [testing, setTesting] = useState<string | null>(null);
  const [models, setModels] = useState<Record<string, string[]>>({});
  const [runtime, setRuntime] = useState<Record<string, ImageUpstreamRuntimeStatus>>({});

  const upstreams = config?.image_upstreams;
  const channels = useMemo(() => upstreams?.channels || [], [upstreams?.channels]);

  const update = (next: ImageUpstreamChannel[]) => {
    useSettingsStore.setState((state) => state.config ? {
      config: { ...state.config, image_upstreams: { ...(state.config.image_upstreams || { max_attempts: 2, alert_webhook_url: "" }), channels: next } },
    } : {});
  };

  const updateChannel = (id: string, patch: Partial<ImageUpstreamChannel>) => {
    update(channels.map((channel) => channel.id === id ? { ...channel, ...patch } : channel));
  };

  useEffect(() => {
    let cancelled = false;
    const loadRuntime = async () => {
      try {
        const response = await fetchImageUpstreamStatus();
        if (!cancelled) setRuntime(response.channels);
      } catch {
        // Runtime indicators are informational; settings remain editable when unavailable.
      }
    };
    void loadRuntime();
    const timer = window.setInterval(() => void loadRuntime(), 5000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, []);

  const test = async (channel: ImageUpstreamChannel, loadModels = false) => {
    setTesting(channel.id);
    try {
      const response = loadModels ? await fetchImageUpstreamModels(channel) : await testImageUpstream(channel);
      setResults((current) => ({ ...current, [channel.id]: response.result }));
      if (loadModels) {
        setModels((current) => ({ ...current, [channel.id]: response.result.models }));
      }
      void fetchImageUpstreamStatus().then((status) => setRuntime(status.channels)).catch(() => undefined);
      toast[response.result.ok ? "success" : "error"](response.result.ok ? "上游连接正常" : response.result.error || "上游连接失败");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "上游测试失败");
    } finally {
      setTesting(null);
    }
  };

  if (isLoadingConfig) {
    return <Card className="rounded-lg"><CardContent className="flex justify-center p-10"><LoaderCircle className="size-5 animate-spin text-stone-400" /></CardContent></Card>;
  }
  if (!config || !upstreams) return null;

  return (
    <Card className="rounded-lg border-white/80 bg-white/90 shadow-sm">
      <CardContent className="space-y-5 p-6">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div><h2 className="text-lg font-semibold">生图上游</h2><p className="mt-1 text-sm text-stone-500">按优先级转发 OpenAI Images 请求；临时故障自动尝试下一个渠道。</p></div>
          <Button type="button" className="rounded-md" onClick={() => update([...channels, createChannel()])}><Plus />新增渠道</Button>
        </div>

        <div className="max-w-xs space-y-2">
          <label className="text-sm text-stone-700">单次最大上游尝试数</label>
          <Input type="number" min="1" max="10" value={String(upstreams.max_attempts)} onChange={(event) => useSettingsStore.setState((state) => state.config ? { config: { ...state.config, image_upstreams: { ...upstreams, max_attempts: event.target.value } } } : {})} className="h-10 rounded-md border-stone-200" />
        </div>
        <div className="max-w-xl space-y-2">
          <label className="text-sm text-stone-700">熔断告警 Webhook（可选）</label>
          <Input value={upstreams.alert_webhook_url || ""} onChange={(event) => useSettingsStore.setState((state) => state.config ? { config: { ...state.config, image_upstreams: { ...upstreams, alert_webhook_url: event.target.value } } } : {})} placeholder="https://example.com/webhooks/image-alerts" className="h-10 rounded-md border-stone-200" />
        </div>

        {channels.length === 0 ? <div className="border border-dashed border-stone-200 px-5 py-10 text-center text-sm text-stone-500">暂无上游渠道。未配置时图片请求会继续使用现有账号池。</div> : null}

        <div className="space-y-4">
          {channels.map((channel) => {
            const result = results[channel.id];
            const channelRuntime = runtime[channel.id];
            const availableModels = models[channel.id] || [];
            return <section key={channel.id} className="space-y-4 border border-stone-200 bg-stone-50 p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex min-w-0 items-center gap-3"><Checkbox checked={channel.enabled} onCheckedChange={(checked) => updateChannel(channel.id, { enabled: Boolean(checked) })} /><Input value={channel.name} onChange={(event) => updateChannel(channel.id, { name: event.target.value })} className="h-9 w-52 rounded-md border-stone-200 bg-white font-medium" />{channelRuntime?.circuit_open ? <span className="rounded-md bg-rose-100 px-2 py-1 text-xs text-rose-700">熔断中 {channelRuntime.cooldown_remaining_secs}s</span> : <span className="rounded-md bg-emerald-50 px-2 py-1 text-xs text-emerald-700">可用</span>}</div>
                <div className="flex items-center gap-2"><Button type="button" size="sm" variant="outline" className="rounded-md" onClick={() => void test(channel)} disabled={testing === channel.id}>{testing === channel.id ? <LoaderCircle className="animate-spin" /> : <RefreshCw />}测试</Button><Button type="button" size="icon" variant="outline" className="rounded-md border-rose-200 text-rose-700" title="删除渠道" onClick={() => update(channels.filter((item) => item.id !== channel.id))}><Trash2 /></Button></div>
              </div>
              <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
                <Field label="Base URL"><Input value={channel.base_url} onChange={(event) => updateChannel(channel.id, { base_url: event.target.value })} placeholder="https://example.com/v1" className="h-10 rounded-md border-stone-200 bg-white" /></Field>
                <Field label="固定渠道模型别名"><Input value={channel.model_alias} onChange={(event) => updateChannel(channel.id, { model_alias: event.target.value.toLowerCase() })} placeholder="upstream-image" className="h-10 rounded-md border-stone-200 bg-white" /></Field>
                <Field label="API Key"><Input type="password" value={channel.api_key || ""} onChange={(event) => updateChannel(channel.id, { api_key: event.target.value, clear_api_key: false })} placeholder={channel.has_api_key ? "已保存，留空不修改" : "可选"} className="h-10 rounded-md border-stone-200 bg-white" />{channel.has_api_key ? <label className="mt-1 flex items-center gap-2 text-xs text-rose-700"><Checkbox checked={Boolean(channel.clear_api_key)} onCheckedChange={(checked) => updateChannel(channel.id, { clear_api_key: Boolean(checked) })} />清除已保存密钥</label> : null}</Field>
                <Field label="优先级"><Input type="number" min="0" value={String(channel.priority)} onChange={(event) => updateChannel(channel.id, { priority: event.target.value })} className="h-10 rounded-md border-stone-200 bg-white" /></Field>
                <Field label="超时（秒）"><Input type="number" min="1" max="600" value={String(channel.timeout_secs)} onChange={(event) => updateChannel(channel.id, { timeout_secs: event.target.value })} className="h-10 rounded-md border-stone-200 bg-white" /></Field>
                <Field label="渠道代理"><Input value={channel.proxy_url} onChange={(event) => updateChannel(channel.id, { proxy_url: event.target.value })} placeholder="http://127.0.0.1:7890" className="h-10 rounded-md border-stone-200 bg-white" /></Field>
                <Field label="熔断阈值"><Input type="number" min="1" max="20" value={String(channel.failure_threshold)} onChange={(event) => updateChannel(channel.id, { failure_threshold: event.target.value })} className="h-10 rounded-md border-stone-200 bg-white" /></Field>
                <Field label="熔断冷却（秒）"><Input type="number" min="1" max="3600" value={String(channel.cooldown_secs)} onChange={(event) => updateChannel(channel.id, { cooldown_secs: event.target.value })} className="h-10 rounded-md border-stone-200 bg-white" /></Field>
                <Field label="最大并发"><Input type="number" min="1" max="100" value={String(channel.max_concurrency)} onChange={(event) => updateChannel(channel.id, { max_concurrency: event.target.value })} className="h-10 rounded-md border-stone-200 bg-white" /></Field>
                <Field label="每分钟请求数"><Input type="number" min="1" max="10000" value={String(channel.requests_per_minute)} onChange={(event) => updateChannel(channel.id, { requests_per_minute: event.target.value })} className="h-10 rounded-md border-stone-200 bg-white" /></Field>
              </div>
              <div className="flex flex-wrap gap-x-5 gap-y-3 text-sm text-stone-700"><label className="flex items-center gap-2"><Checkbox checked={channel.supports_generation} onCheckedChange={(checked) => updateChannel(channel.id, { supports_generation: Boolean(checked) })} />文生图</label><label className="flex items-center gap-2"><Checkbox checked={channel.supports_edits} onCheckedChange={(checked) => updateChannel(channel.id, { supports_edits: Boolean(checked) })} />图生图</label><label className="flex items-center gap-2"><Checkbox checked={channel.default} onCheckedChange={(checked) => update(channels.map((item) => ({ ...item, default: item.id === channel.id && Boolean(checked) })))} />同优先级默认</label></div>
              <div className="space-y-2 border-t border-stone-200 pt-3"><div className="flex items-center justify-between"><div className="text-sm font-medium text-stone-800">模型映射</div><Button type="button" size="sm" variant="outline" className="rounded-md" onClick={() => void test(channel, true)} disabled={testing === channel.id}>{testing === channel.id ? <LoaderCircle className="animate-spin" /> : <RefreshCw />}拉取模型</Button></div>{channel.model_mappings.map((mapping, index) => <div key={`${channel.id}-${index}`} className="grid gap-2 md:grid-cols-[1fr_1fr_auto]"><Input value={mapping.client_model} onChange={(event) => updateChannel(channel.id, { model_mappings: channel.model_mappings.map((item, current) => current === index ? { ...item, client_model: event.target.value } : item) })} placeholder="客户端模型，例如 gpt-image-2" className="h-9 rounded-md border-stone-200 bg-white" /><Input value={mapping.upstream_model} onChange={(event) => updateChannel(channel.id, { model_mappings: channel.model_mappings.map((item, current) => current === index ? { ...item, upstream_model: event.target.value } : item) })} placeholder="上游模型" list={`${channel.id}-models`} className="h-9 rounded-md border-stone-200 bg-white" /><Button type="button" size="icon" variant="ghost" title="删除映射" onClick={() => updateChannel(channel.id, { model_mappings: channel.model_mappings.filter((_, current) => current !== index) })}><Trash2 /></Button><datalist id={`${channel.id}-models`}>{availableModels.map((model) => <option key={model} value={model} />)}</datalist></div>)}<Button type="button" size="sm" variant="outline" className="rounded-md" onClick={() => updateChannel(channel.id, { model_mappings: [...channel.model_mappings, { client_model: "", upstream_model: "" }] })}><Plus />添加映射</Button></div>
              {result ? <div className={`flex items-center gap-2 border px-3 py-2 text-xs ${result.ok ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-rose-200 bg-rose-50 text-rose-800"}`}>{result.ok ? <CheckCircle2 className="size-4" /> : <XCircle className="size-4" />}{result.ok ? `连接正常，HTTP ${result.status}，${result.latency_ms} ms` : result.error || "连接失败"}</div> : null}
              {channelRuntime?.last_test ? <div className="text-xs text-stone-500">最近测试：{channelRuntime.last_test.ok ? `成功，HTTP ${channelRuntime.last_test.status}，${channelRuntime.last_test.latency_ms} ms` : channelRuntime.last_test.error || "失败"}{channelRuntime.failure_count > 0 ? `；连续失败 ${channelRuntime.failure_count} 次` : ""}{channelRuntime.inflight > 0 ? `；在途 ${channelRuntime.inflight}/${channelRuntime.max_concurrency}` : ""}</div> : null}
            </section>;
          })}
        </div>
        <div className="flex justify-end"><Button type="button" className="rounded-md bg-stone-950 text-white hover:bg-stone-800" onClick={() => void saveConfig()} disabled={isSavingConfig}>{isSavingConfig ? <LoaderCircle className="animate-spin" /> : <Save />}保存生图上游</Button></div>
      </CardContent>
    </Card>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) { return <div className="space-y-1.5"><label className="text-xs text-stone-600">{label}</label>{children}</div>; }
