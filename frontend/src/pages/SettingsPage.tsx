import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import type { AppSettings, Weights } from "@/lib/types";

type ListKey = {
  [K in keyof AppSettings]: AppSettings[K] extends string[] ? K : never;
}[keyof AppSettings];

const LISTS: [ListKey, string][] = [
  ["employer_allowlist", "Employer allowlist (overrides defence/bank)"],
  ["defence_employers", "Defence employers"],
  ["bank_employers", "Bank employers"],
  ["clearance_patterns", "Clearance patterns (regex)"],
  ["citizenship_patterns", "Citizenship/PR patterns (regex)"],
  ["defence_keywords", "Defence keywords (regex)"],
  ["bank_keywords", "Bank keywords (regex)"],
  ["role_boost_terms", "Role boost terms"],
  ["role_penalty_terms", "Role penalty terms"],
  ["llm_providers", "LLM provider order (anthropic, openclaw)"],
];
const WEIGHTS: [keyof Weights, string][] = [
  ["flexible_work", "Part-time/contract/casual points"],
  ["full_time", "Full-time points"],
  ["skill_max", "Skill match max"],
  ["role_max", "Role fit max"],
  ["skill_saturation", "Skills to reach max"],
];
const TOGGLES: [keyof AppSettings, string][] = [
  ["notify_enabled", "Telegram notifications"],
  ["recap_enabled", "Daily 21:15 recap"],
  ["llm_enabled", "AI scoring"],
  ["exclude_fintech", "Exclude fintech"],
];

export function SettingsPage() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const [s, setS] = useState<AppSettings | null>(null);
  useEffect(() => setS(data ?? null), [data]);
  const fail = (e: Error) => toast.error(e.message.includes("401") ? "Set the write token first" : e.message);
  const save = useMutation({
    mutationFn: () => api.saveSettings(s!),
    onSuccess: () => {
      toast.success("Settings saved");
      qc.invalidateQueries({ queryKey: ["settings"] });
    },
    onError: fail,
  });
  const run = useMutation({ mutationFn: api.triggerRun, onSuccess: () => toast.success("Run started"), onError: fail });
  const test = useMutation({ mutationFn: api.notifyTest, onSuccess: () => toast.success("Test sent"), onError: fail });
  if (!s) return <p>Loading…</p>;

  return (
    <div className="space-y-6">
      <div className="flex gap-2">
        <Button onClick={() => save.mutate()}>Save settings</Button>
        <Button variant="outline" onClick={() => run.mutate()}>
          Run now
        </Button>
        <Button variant="outline" onClick={() => test.mutate()}>
          Send test notification
        </Button>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Toggles & weights</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          {TOGGLES.map(([k, label]) => (
            <div key={k} className="flex items-center gap-2">
              <Switch checked={s[k] as boolean} onCheckedChange={(v) => setS({ ...s, [k]: v })} />
              <Label>{label}</Label>
            </div>
          ))}
          {WEIGHTS.map(([k, label]) => (
            <div key={k} className="space-y-1">
              <Label>{label}</Label>
              <Input type="number" value={s.weights[k]} onChange={(e) => setS({ ...s, weights: { ...s.weights, [k]: Number(e.target.value) } })} />
            </div>
          ))}
          <div className="space-y-1">
            <Label>Max notified per run</Label>
            <Input type="number" value={s.max_notify_per_run} onChange={(e) => setS({ ...s, max_notify_per_run: Number(e.target.value) })} />
          </div>
          <div className="space-y-1">
            <Label>Max pages per search</Label>
            <Input type="number" value={s.max_pages_per_search} onChange={(e) => setS({ ...s, max_pages_per_search: Number(e.target.value) })} />
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Lists (one per line)</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          {LISTS.map(([k, label]) => (
            <div key={k} className="space-y-1">
              <Label>{label}</Label>
              <Textarea
                rows={6}
                className="font-mono text-xs"
                value={s[k].join("\n")}
                onChange={(e) => setS({ ...s, [k]: e.target.value.split("\n").map((x) => x.trim()).filter(Boolean) })}
              />
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
