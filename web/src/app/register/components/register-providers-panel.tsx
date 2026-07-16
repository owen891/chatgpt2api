import { Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { RegisterGptMailStatus, RegisterProvider } from "@/lib/api";

import { SectionTitle, defaultProvider } from "../register-shared";
import { RegisterProviderCard } from "./register-provider-card";

export function RegisterProvidersPanel({
  providers,
  running,
  gptmailStatus,
  gptmailBusy,
  onAddProvider,
  onCheckGptMail,
  onMaintainOutlook,
  onChange,
  onTypeChange,
  onRemove,
}: {
  providers: RegisterProvider[];
  running: boolean;
  gptmailStatus: Record<number, RegisterGptMailStatus>;
  gptmailBusy: number | null;
  onAddProvider: () => void;
  onCheckGptMail: (index: number, provider: RegisterProvider) => void;
  onMaintainOutlook: (scope: "retryable" | "invalid" | "unused" | "all") => void;
  onChange: (index: number, changes: Partial<RegisterProvider>) => void;
  onTypeChange: (index: number, type: string) => void;
  onRemove: (index: number) => void;
}) {
  return (
    <section className="min-w-0 rounded-xl border border-stone-200/80 bg-white shadow-none">
      <div className="min-w-0 space-y-4 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <SectionTitle title="邮箱来源" />
          <Button type="button" variant="outline" disabled={running} onClick={onAddProvider}>
            <Plus />
            添加来源
          </Button>
        </div>

        <p className="text-xs text-stone-500">
          按启用顺序轮换邮箱源，只保留旧注册机实际用到的配置能力。
        </p>

        {providers.length === 0 ? (
          <div className="rounded-md border border-dashed border-stone-200 px-4 py-8 text-center text-sm text-stone-500">
            暂无邮箱来源，请先添加。
          </div>
        ) : (
          <div className="space-y-3">
            {providers.map((provider, index) => (
              <RegisterProviderCard
                key={String(provider.id || `${provider.type}-${index}`)}
                provider={provider}
                index={index}
                disabled={running}
                gptStatus={gptmailStatus[index]}
                gptBusy={gptmailBusy === index}
                onCheckGptMail={() => onCheckGptMail(index, provider)}
                onMaintainOutlook={(scope) => onMaintainOutlook(scope)}
                onChange={(changes) => onChange(index, changes)}
                onTypeChange={(type) => onTypeChange(index, type)}
                onRemove={() => onRemove(index)}
              />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

export function createDefaultRegisterProvider() {
  return defaultProvider();
}
