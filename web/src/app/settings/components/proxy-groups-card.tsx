"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Copy, Link2, LoaderCircle, Pencil, Plus, RefreshCw, ShieldCheck, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  deleteProxyGroup,
  fetchProxyGroups,
  saveProxyGroup,
  testProxyGroup,
  type ProxyGroup,
  type ProxyGroupNode,
} from "@/lib/api";

type ProxyGroupDraftNode = {
  id: string;
  name: string;
  url: string;
  enabled: boolean;
  image_concurrency_limit: string;
};

type ProxyGroupForm = {
  id: string;
  name: string;
  strategy: string;
  rotation_interval_minutes: string;
  enabled: boolean;
  notes: string;
  nodes: ProxyGroupDraftNode[];
};

function createDraftNode(overrides: Partial<ProxyGroupDraftNode> = {}): ProxyGroupDraftNode {
  return {
    id: "",
    name: "",
    url: "",
    enabled: true,
    image_concurrency_limit: "30",
    ...overrides,
  };
}

function emptyForm(): ProxyGroupForm {
  return {
    id: "",
    name: "",
    strategy: "request_random",
    rotation_interval_minutes: "0",
    enabled: true,
    notes: "",
    nodes: [createDraftNode()],
  };
}

function toForm(group: ProxyGroup): ProxyGroupForm {
  return {
    id: String(group.id || ""),
    name: String(group.name || ""),
    strategy: String(group.strategy || "request_random"),
    rotation_interval_minutes: String(group.rotation_interval_minutes ?? 0),
    enabled: group.enabled !== false,
    notes: String(group.notes || ""),
    nodes: Array.isArray(group.nodes) && group.nodes.length > 0
      ? group.nodes.map((node) => createDraftNode({
        id: String(node.id || ""),
        name: String(node.name || ""),
        url: String(node.url || ""),
        enabled: node.enabled !== false,
        image_concurrency_limit: String(node.image_concurrency_limit ?? 30),
      }))
      : [createDraftNode()],
  };
}

function toPayload(form: ProxyGroupForm, createOnly: boolean): ProxyGroup & { create_only: boolean } {
  return {
    id: form.id.trim(),
    name: form.name.trim(),
    strategy: form.strategy,
    rotation_interval_minutes: Number(form.rotation_interval_minutes || 0),
    enabled: form.enabled,
    notes: form.notes.trim(),
    nodes: form.nodes.map((node) => ({
      id: node.id.trim(),
      name: node.name.trim(),
      url: node.url.trim(),
      enabled: node.enabled,
      image_concurrency_limit: Number(node.image_concurrency_limit || 0),
    })),
    create_only: createOnly,
  };
}

function normalizeGroups(items: ProxyGroup[]) {
  return Array.isArray(items) ? items : [];
}

function looksLikeProxyUrl(value: string) {
  const candidate = value.trim().toLowerCase();
  return candidate.startsWith("http://")
    || candidate.startsWith("https://")
    || candidate.startsWith("socks://")
    || candidate.startsWith("socks5://")
    || candidate.startsWith("socks5h://")
    || /^[^,\s:]+:\d+(?::[^,\s]+(?::[^,\s]+)?)?$/.test(candidate);
}

function parseBatchNodes(raw: string): ProxyGroupDraftNode[] {
  const nodes: ProxyGroupDraftNode[] = [];
  const lines = raw
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);

  for (const line of lines) {
    const commaParts = line.split(",").map((item) => item.trim()).filter(Boolean);
    if (commaParts.length >= 2) {
      const [first, second, third] = commaParts;
      if (looksLikeProxyUrl(first) && !looksLikeProxyUrl(second)) {
        nodes.push(createDraftNode({
          url: first,
          name: second,
          image_concurrency_limit: third || "30",
        }));
      } else {
        nodes.push(createDraftNode({
          name: first,
          url: second,
          image_concurrency_limit: third || "30",
        }));
      }
      continue;
    }

    if (looksLikeProxyUrl(line)) {
      nodes.push(createDraftNode({ url: line }));
    }
  }

  return nodes;
}

export function ProxyGroupsCard() {
  const didLoadRef = useRef(false);
  const [groups, setGroups] = useState<ProxyGroup[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingGroupId, setEditingGroupId] = useState<string | null>(null);
  const [form, setForm] = useState<ProxyGroupForm>(emptyForm);
  const [batchText, setBatchText] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [testingKey, setTestingKey] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const loadGroups = async () => {
    setIsLoading(true);
    try {
      const data = await fetchProxyGroups();
      setGroups(normalizeGroups(data.groups));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "加载代理组失败");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (didLoadRef.current) {
      return;
    }
    didLoadRef.current = true;
    void loadGroups();
  }, []);

  const filteredGroups = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    if (!normalizedQuery) {
      return groups;
    }
    return groups.filter((group) => {
      const text = [
        group.id,
        group.name,
        group.notes,
        ...(group.nodes || []).flatMap((node) => [node.id, node.name, node.url]),
      ]
        .filter(Boolean)
        .join("\n")
        .toLowerCase();
      return text.includes(normalizedQuery);
    });
  }, [groups, query]);

  const openCreate = () => {
    setEditingGroupId(null);
    setForm(emptyForm());
    setBatchText("");
    setDialogOpen(true);
  };

  const openEdit = (group: ProxyGroup) => {
    setEditingGroupId(group.id);
    setForm(toForm(group));
    setBatchText("");
    setDialogOpen(true);
  };

  const setNodeField = (index: number, key: keyof ProxyGroupDraftNode, value: string | boolean) => {
    setForm((current) => ({
      ...current,
      nodes: current.nodes.map((node, nodeIndex) => (nodeIndex === index ? { ...node, [key]: value } : node)),
    }));
  };

  const addNode = () => {
    setForm((current) => ({
      ...current,
      nodes: [...current.nodes, createDraftNode()],
    }));
  };

  const removeNode = (index: number) => {
    setForm((current) => ({
      ...current,
      nodes: current.nodes.filter((_, nodeIndex) => nodeIndex !== index),
    }));
  };

  const applyBatchNodes = () => {
    const parsed = parseBatchNodes(batchText);
    if (parsed.length === 0) {
      toast.error("没有识别到可导入的代理节点");
      return;
    }

    setForm((current) => {
      const existing = current.nodes.filter((node) => node.url.trim());
      const seen = new Set(existing.map((node) => node.url.trim()));
      const uniqueIncoming = parsed.filter((node) => {
        const key = node.url.trim();
        if (!key || seen.has(key)) {
          return false;
        }
        seen.add(key);
        return true;
      });
      return {
        ...current,
        nodes: [...existing, ...uniqueIncoming],
      };
    });
    setBatchText("");
    toast.success(`已导入 ${parsed.length} 个节点`);
  };

  const handleSave = async () => {
    const trimmedName = form.name.trim();
    const activeNodes = form.nodes.filter((node) => node.url.trim());
    if (!trimmedName) {
      toast.error("请先填写代理组名称");
      return;
    }
    if (activeNodes.length === 0) {
      toast.error("至少添加一个代理节点地址");
      return;
    }

    setIsSaving(true);
    try {
      const data = await saveProxyGroup(toPayload({ ...form, nodes: activeNodes }, !editingGroupId));
      setGroups(normalizeGroups(data.groups));
      setDialogOpen(false);
      toast.success(editingGroupId ? "代理组已更新" : "代理组已创建");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "保存代理组失败");
    } finally {
      setIsSaving(false);
    }
  };

  const handleDelete = async (groupId: string) => {
    setDeletingId(groupId);
    try {
      const data = await deleteProxyGroup(groupId);
      setGroups(normalizeGroups(data.groups));
      toast.success(`已删除代理组 ${groupId}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "删除代理组失败");
    } finally {
      setDeletingId(null);
    }
  };

  const handleTest = async (group: ProxyGroup, node?: ProxyGroupNode) => {
    const key = `${group.id}:${node?.id || "group"}`;
    setTestingKey(key);
    try {
      const data = await testProxyGroup(node ? { id: group.id, node_id: node.id } : { id: group.id });
      if (data.result.ok) {
        toast.success(`代理测试成功，HTTP ${data.result.status}，${data.result.latency_ms} ms`);
      } else {
        toast.error(data.result.error || "代理测试失败");
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "代理测试失败");
    } finally {
      setTestingKey(null);
    }
  };

  return (
    <>
      <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
        <CardContent className="space-y-5 p-6">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div className="space-y-1">
              <div className="flex items-center gap-2 text-lg font-semibold tracking-tight text-stone-900">
                <Link2 className="size-5 text-stone-500" />
                代理组 / 多出口
              </div>
              <p className="text-sm text-stone-500">
                维护多个代理节点，注册任务和默认代理都可以直接引用 `group:&lt;id&gt;`。
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                className="h-10 rounded-xl border-stone-200 bg-white px-4 text-stone-700"
                onClick={() => void loadGroups()}
                disabled={isLoading}
              >
                {isLoading ? <LoaderCircle className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
                刷新
              </Button>
              <Button
                className="h-10 rounded-xl bg-stone-950 px-4 text-white hover:bg-stone-800"
                onClick={openCreate}
              >
                <Plus className="size-4" />
                新建代理组
              </Button>
            </div>
          </div>

          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索代理组 / 节点 / 地址"
            className="h-11 rounded-xl border-stone-200 bg-white"
          />

          {isLoading ? (
            <div className="flex items-center justify-center py-10">
              <LoaderCircle className="size-5 animate-spin text-stone-400" />
            </div>
          ) : filteredGroups.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-stone-200 bg-stone-50 px-4 py-10 text-center text-sm text-stone-500">
              暂无代理组，创建后即可在注册页或默认代理里引用。
            </div>
          ) : (
            <div className="space-y-4">
              {filteredGroups.map((group) => (
                <div key={group.id} className="rounded-2xl border border-stone-200 bg-white p-4">
                  <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                    <div className="space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <div className="text-base font-semibold text-stone-900">{group.name}</div>
                        <Badge variant={group.enabled === false ? "secondary" : "success"} className="rounded-md px-2.5 py-1">
                          {group.enabled === false ? "已禁用" : "已启用"}
                        </Badge>
                        <Badge variant="secondary" className="rounded-md px-2.5 py-1 font-mono">
                          {group.id}
                        </Badge>
                      </div>
                      <div className="flex flex-wrap items-center gap-2 text-sm text-stone-500">
                        <span className="font-mono">group:{group.id}</span>
                        <button
                          type="button"
                          className="inline-flex items-center gap-1 text-stone-500 transition hover:text-stone-900"
                          onClick={() => {
                            void navigator.clipboard.writeText(`group:${group.id}`);
                            toast.success("已复制代理组引用");
                          }}
                        >
                          <Copy className="size-3.5" />
                          复制引用
                        </button>
                        <span>{(group.nodes || []).length} 个节点</span>
                        <span>轮换间隔 {group.rotation_interval_minutes ?? 0} 分钟</span>
                      </div>
                      {group.notes ? <p className="text-sm text-stone-500">{group.notes}</p> : null}
                    </div>

                    <div className="flex flex-wrap gap-2">
                      <Button
                        variant="outline"
                        className="h-9 rounded-xl border-stone-200 bg-white px-4 text-stone-700"
                        onClick={() => void handleTest(group)}
                        disabled={testingKey === `${group.id}:group`}
                      >
                        {testingKey === `${group.id}:group` ? <LoaderCircle className="size-4 animate-spin" /> : <ShieldCheck className="size-4" />}
                        测试
                      </Button>
                      <Button
                        variant="outline"
                        className="h-9 rounded-xl border-stone-200 bg-white px-4 text-stone-700"
                        onClick={() => openEdit(group)}
                      >
                        <Pencil className="size-4" />
                        编辑
                      </Button>
                      <Button
                        variant="outline"
                        className="h-9 rounded-xl border-rose-200 bg-white px-4 text-rose-700 hover:bg-rose-50"
                        onClick={() => void handleDelete(group.id)}
                        disabled={deletingId === group.id}
                      >
                        {deletingId === group.id ? <LoaderCircle className="size-4 animate-spin" /> : <Trash2 className="size-4" />}
                        删除
                      </Button>
                    </div>
                  </div>

                  <div className="mt-4 grid gap-3 lg:grid-cols-2">
                    {(group.nodes || []).map((node) => (
                      <div key={node.id} className="rounded-xl border border-stone-200 bg-stone-50 p-3">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0 space-y-1">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="font-medium text-stone-900">{node.name}</span>
                              <Badge variant={node.enabled === false ? "secondary" : "outline"} className="rounded-md px-2 py-0.5">
                                {node.enabled === false ? "禁用" : "启用"}
                              </Badge>
                            </div>
                            <div className="break-all font-mono text-xs text-stone-500">{node.url}</div>
                            <div className="text-xs text-stone-500">
                              节点 ID: {node.id} · 图片并发: {node.image_concurrency_limit ?? 30}
                            </div>
                          </div>
                          <Button
                            variant="ghost"
                            className="h-8 rounded-lg px-2 text-stone-600 hover:text-stone-900"
                            onClick={() => void handleTest(group, node)}
                            disabled={testingKey === `${group.id}:${node.id}`}
                          >
                            {testingKey === `${group.id}:${node.id}` ? <LoaderCircle className="size-4 animate-spin" /> : <ShieldCheck className="size-4" />}
                          </Button>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-h-[88vh] overflow-y-auto rounded-2xl p-6">
          <DialogHeader className="gap-2">
            <DialogTitle>{editingGroupId ? "编辑代理组" : "新建代理组"}</DialogTitle>
            <DialogDescription className="text-sm leading-6">
              代理组会保存为 `group:&lt;id&gt;` 引用，运行时会从可用节点中选择出口。
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-5">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <label className="text-sm font-medium text-stone-700">名称</label>
                <Input
                  value={form.name}
                  onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
                  placeholder="例如：香港出口组"
                  className="h-11 rounded-xl border-stone-200 bg-white"
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-stone-700">ID</label>
                <Input
                  value={form.id}
                  onChange={(event) => setForm((current) => ({ ...current, id: event.target.value }))}
                  placeholder="留空则按名称生成"
                  className="h-11 rounded-xl border-stone-200 bg-white font-mono"
                  disabled={Boolean(editingGroupId)}
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-stone-700">轮换间隔（分钟）</label>
                <Input
                  value={form.rotation_interval_minutes}
                  onChange={(event) => setForm((current) => ({ ...current, rotation_interval_minutes: event.target.value }))}
                  placeholder="0"
                  className="h-11 rounded-xl border-stone-200 bg-white"
                />
              </div>
              <label className="flex items-center gap-3 rounded-xl border border-stone-200 bg-white px-4 py-3 text-sm text-stone-700">
                <Checkbox
                  checked={form.enabled}
                  onCheckedChange={(checked) => setForm((current) => ({ ...current, enabled: Boolean(checked) }))}
                />
                启用该代理组
              </label>
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium text-stone-700">备注</label>
              <Textarea
                value={form.notes}
                onChange={(event) => setForm((current) => ({ ...current, notes: event.target.value }))}
                placeholder="可选：记录线路用途、地区或限制"
                className="min-h-20 rounded-xl border-stone-200 bg-white"
              />
            </div>

            <div className="rounded-2xl border border-dashed border-stone-200 bg-stone-50/80 p-4">
              <div className="space-y-3">
                <div className="space-y-1">
                  <div className="text-sm font-medium text-stone-700">批量添加节点</div>
                  <p className="text-xs leading-5 text-stone-500">
                    支持一行一个代理地址，或使用 `名称,代理地址,并发上限`。也支持 `代理地址,名称,并发上限`。
                  </p>
                </div>
                <Textarea
                  value={batchText}
                  onChange={(event) => setBatchText(event.target.value)}
                  placeholder={[
                    "http://127.0.0.1:7890",
                    "hk-01,http://127.0.0.1:7891,30",
                    "socks5://127.0.0.1:7892,sg-02,20",
                  ].join("\n")}
                  className="min-h-28 rounded-xl border-stone-200 bg-white font-mono text-xs"
                />
                <div className="flex justify-end">
                  <Button
                    type="button"
                    variant="outline"
                    className="h-9 rounded-xl border-stone-200 bg-white px-4 text-stone-700"
                    onClick={applyBatchNodes}
                  >
                    <Plus className="size-4" />
                    批量导入
                  </Button>
                </div>
              </div>
            </div>

            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <div className="text-sm font-medium text-stone-700">节点</div>
                <Button
                  type="button"
                  variant="outline"
                  className="h-9 rounded-xl border-stone-200 bg-white px-4 text-stone-700"
                  onClick={addNode}
                >
                  <Plus className="size-4" />
                  添加节点
                </Button>
              </div>

              <div className="space-y-3">
                {form.nodes.map((node, index) => (
                  <div key={`${editingGroupId || "new"}-${index}`} className="rounded-2xl border border-stone-200 bg-stone-50 p-4">
                    <div className="grid gap-3 md:grid-cols-2">
                      <div className="space-y-2">
                        <label className="text-sm font-medium text-stone-700">节点名称</label>
                        <Input
                          value={node.name}
                          onChange={(event) => setNodeField(index, "name", event.target.value)}
                          placeholder="例如：hk-01"
                          className="h-10 rounded-xl border-stone-200 bg-white"
                        />
                      </div>
                      <div className="space-y-2">
                        <label className="text-sm font-medium text-stone-700">节点 ID</label>
                        <Input
                          value={node.id}
                          onChange={(event) => setNodeField(index, "id", event.target.value)}
                          placeholder="留空则按名称生成"
                          className="h-10 rounded-xl border-stone-200 bg-white font-mono"
                        />
                      </div>
                      <div className="space-y-2 md:col-span-2">
                        <label className="text-sm font-medium text-stone-700">代理地址</label>
                        <Input
                          value={node.url}
                          onChange={(event) => setNodeField(index, "url", event.target.value)}
                          placeholder="http://user:pass@127.0.0.1:7890"
                          className="h-10 rounded-xl border-stone-200 bg-white font-mono text-xs"
                        />
                      </div>
                      <div className="space-y-2">
                        <label className="text-sm font-medium text-stone-700">图片并发上限</label>
                        <Input
                          value={node.image_concurrency_limit}
                          onChange={(event) => setNodeField(index, "image_concurrency_limit", event.target.value)}
                          placeholder="30"
                          className="h-10 rounded-xl border-stone-200 bg-white"
                        />
                      </div>
                      <div className="flex items-end justify-between gap-3">
                        <label className="flex items-center gap-3 rounded-xl border border-stone-200 bg-white px-4 py-2 text-sm text-stone-700">
                          <Checkbox
                            checked={node.enabled}
                            onCheckedChange={(checked) => setNodeField(index, "enabled", Boolean(checked))}
                          />
                          启用节点
                        </label>
                        <Button
                          type="button"
                          variant="outline"
                          className="h-9 rounded-xl border-rose-200 bg-white px-4 text-rose-700 hover:bg-rose-50"
                          onClick={() => removeNode(index)}
                          disabled={form.nodes.length === 1}
                        >
                          <Trash2 className="size-4" />
                          删除
                        </Button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <DialogFooter className="pt-2">
            <Button
              variant="secondary"
              className="h-10 rounded-xl bg-stone-100 px-5 text-stone-700 hover:bg-stone-200"
              onClick={() => setDialogOpen(false)}
              disabled={isSaving}
            >
              取消
            </Button>
            <Button
              className="h-10 rounded-xl bg-stone-950 px-5 text-white hover:bg-stone-800"
              onClick={() => void handleSave()}
              disabled={isSaving}
            >
              {isSaving ? <LoaderCircle className="size-4 animate-spin" /> : <Pencil className="size-4" />}
              {editingGroupId ? "保存修改" : "创建代理组"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
