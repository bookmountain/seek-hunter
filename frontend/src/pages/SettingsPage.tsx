import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { api, errMsg } from "@/lib/api";
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
  ["fintech_keywords", "Fintech keywords (regex)"],
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

const parseList = (text: string): string[] =>
  text
    .split("\n")
    .map((x) => x.trim())
    .filter(Boolean);

const parseInt0 = (v: string): number => Math.trunc(Number(v) || 0);

export function SettingsPage() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const [s, setS] = useState<AppSettings | null>(null);
  // Raw textarea text, kept separate from `s` so each keystroke (including spaces and
  // newlines) is preserved as typed; it's only split/trimmed/filtered when saving.
  const [listText, setListText] = useState<Partial<Record<ListKey, string>>>({});
  useEffect(() => {
    if (!data) return;
    setS(data);
    setListText(Object.fromEntries(LISTS.map(([k]) => [k, data[k].join("\n")])) as Record<ListKey, string>);
  }, [data]);
  const fail = (e: Error) => toast.error(errMsg(e));
  const save = useMutation({
    mutationFn: () => {
      const lists = Object.fromEntries(LISTS.map(([k]) => [k, parseList(listText[k] ?? "")])) as Record<ListKey, string[]>;
      return api.saveSettings({ ...s!, ...lists });
    },
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
              <Input
                type="number"
                step={1}
                min={0}
                value={s.weights[k]}
                onChange={(e) => setS({ ...s, weights: { ...s.weights, [k]: parseInt0(e.target.value) } })}
              />
            </div>
          ))}
          <div className="space-y-1">
            <Label>Max notified per run</Label>
            <Input
              type="number"
              step={1}
              min={0}
              value={s.max_notify_per_run}
              onChange={(e) => setS({ ...s, max_notify_per_run: parseInt0(e.target.value) })}
            />
          </div>
          <div className="space-y-1">
            <Label>Max pages per search</Label>
            <Input
              type="number"
              step={1}
              min={0}
              value={s.max_pages_per_search}
              onChange={(e) => setS({ ...s, max_pages_per_search: parseInt0(e.target.value) })}
            />
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
                value={listText[k] ?? ""}
                onChange={(e) => setListText({ ...listText, [k]: e.target.value })}
              />
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
