import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Page, PageHead, SectionHead } from "@/components/PageHead";
import { Button } from "@/components/ui/button";
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

const NOTIFY_CITIES: [string, string][] = [
  ["adelaide", "Adelaide"],
  ["melbourne", "Melbourne"],
  ["sydney", "Sydney"],
  ["perth", "Perth"],
  ["brisbane", "Brisbane"],
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
  if (!s) return <Page><p className="kicker text-ink-muted">Loading settings…</p></Page>;

  const numberField = (id: string, label: string, value: number, onChange: (n: number) => void) => (
    <div key={id} className="grid content-end gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} type="number" step={1} min={0} className="num w-32" value={value} onChange={(e) => onChange(parseInt0(e.target.value))} />
    </div>
  );

  return (
    <Page>
      <PageHead
        kicker="Configuration"
        title="Settings"
        dek="How jobs are filtered, scored and announced. Changes apply from the next run."
        actions={
          <>
            <Button onClick={() => save.mutate()}>Save settings</Button>
            <Button variant="outline" onClick={() => run.mutate()}>
              Run now
            </Button>
            <Button variant="outline" onClick={() => test.mutate()}>
              Send test notification
            </Button>
          </>
        }
      />

      <section className="mt-10">
        <SectionHead>Switches</SectionHead>
        <div className="grid sm:grid-cols-2">
          {TOGGLES.map(([k, label]) => (
            <label key={k} className="flex cursor-pointer items-center justify-between gap-4 border-b border-rule py-3 sm:odd:pr-6 sm:even:pl-6">
              <span className="text-[15px]">{label}</span>
              <Switch checked={s[k] as boolean} onCheckedChange={(v) => setS({ ...s, [k]: v })} />
            </label>
          ))}
        </div>
      </section>

      <section className="mt-10">
        <SectionHead>Telegram notification cities</SectionHead>
        <fieldset className="mt-4">
          <legend className="sr-only">Telegram notification cities</legend>
          <div className="flex flex-wrap gap-2">
            {NOTIFY_CITIES.map(([c, label]) => {
              const cur = s.notify_cities ?? [];
              const on = cur.includes(c);
              return (
                <label
                  key={c}
                  className={`inline-flex h-9 cursor-pointer items-center gap-2 border px-3 font-mono text-[12px] tracking-[0.06em] uppercase ${
                    on ? "border-ink text-ink" : "border-input text-ink-muted hover:border-ink"
                  }`}
                >
                  <input
                    type="checkbox"
                    className="size-3.5 accent-[var(--blue)]"
                    checked={on}
                    onChange={() =>
                      setS({ ...s, notify_cities: on ? cur.filter((x) => x !== c) : [...cur, c] })
                    }
                  />
                  {label}
                </label>
              );
            })}
          </div>
          <p className="mt-2 text-[13px] text-ink-muted">Other cities still appear on the website and in the bell.</p>
        </fieldset>
      </section>

      <section className="mt-10">
        <SectionHead>Weights &amp; limits</SectionHead>
        <div className="mt-5 grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-3 lg:grid-cols-4">
          {WEIGHTS.map(([k, label]) =>
            numberField(`w-${k}`, label, s.weights[k], (n) => setS({ ...s, weights: { ...s.weights, [k]: n } })),
          )}
          {numberField("max-notify", "Max notified per run", s.max_notify_per_run, (n) => setS({ ...s, max_notify_per_run: n }))}
          {numberField("max-pages", "Max pages per search", s.max_pages_per_search, (n) => setS({ ...s, max_pages_per_search: n }))}
          {numberField("other-pages", "Max pages, other cities", s.other_city_max_pages ?? 2, (n) => setS({ ...s, other_city_max_pages: n }))}
        </div>
      </section>

      <section className="mt-12">
        <SectionHead>Lists, one entry per line</SectionHead>
        <div className="mt-5 grid gap-x-6 gap-y-6 sm:grid-cols-2">
          {LISTS.map(([k, label]) => (
            <div key={k} className="grid content-start gap-1.5">
              <Label htmlFor={`l-${k}`}>{label}</Label>
              <Textarea
                id={`l-${k}`}
                rows={6}
                className="font-mono text-[12px] leading-[1.6]"
                value={listText[k] ?? ""}
                onChange={(e) => setListText({ ...listText, [k]: e.target.value })}
              />
            </div>
          ))}
        </div>
      </section>

      <div className="mt-10 flex justify-end border-t border-ink pt-5">
        <Button onClick={() => save.mutate()}>Save settings</Button>
      </div>
    </Page>
  );
}
