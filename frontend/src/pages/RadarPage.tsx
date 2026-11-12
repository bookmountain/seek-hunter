import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Page, PageHead, SectionHead } from "@/components/PageHead";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { api, errMsg } from "@/lib/api";
import { adelaideTime, ago, CITY_NAME, cityName } from "@/lib/format";
import { ATS_LABEL, POLLED, radarStats } from "@/lib/radar";
import type { RadarAts, RadarCompany, RadarCompanyIn } from "@/lib/types";
import { cn } from "@/lib/utils";

const TOKEN_HINT: Record<RadarAts, string> = {
  greenhouse: "board slug, e.g. canva",
  lever: "account, e.g. immutable",
  ashby: "board name, e.g. linktree",
  workable: "account, e.g. acme",
  smartrecruiters: "company id, e.g. Atlassian",
  workday: "tenant.wd3/Site",
  pageup: "not needed",
  other: "not needed",
};

const CITIES = ["adelaide", "melbourne", "sydney", "perth", "brisbane"];

type Filter = "all" | "active" | "paused" | "errors";
const FILTERS: [Filter, string][] = [
  ["all", "All"],
  ["active", "Active"],
  ["paused", "Paused"],
  ["errors", "Errors"],
];

const matches = (c: RadarCompany, f: Filter) =>
  f === "all" || (f === "active" ? c.enabled : f === "paused" ? !c.enabled : Boolean(c.last_error));

const host = (url: string) => {
  try {
    return new URL(url).host.replace(/^www\./, "");
  } catch {
    return url;
  }
};

function Stat({ label, value, tone }: { label: string; value: number; tone?: "blue" | "muted" }) {
  return (
    <div className="border-l border-rule px-4 py-3 first:border-l-0 first:pl-0">
      <p className={cn("num text-[28px] leading-none font-medium", tone === "blue" ? "text-blue" : tone === "muted" ? "text-ink-muted" : "text-ink")}>
        {value}
      </p>
      <p className="kicker mt-1.5 text-[10px] text-ink-muted">{label}</p>
    </div>
  );
}

/** Two-step delete: first click arms it for a few seconds. */
function DeleteButton({ onConfirm, name }: { onConfirm: () => void; name: string }) {
  const [armed, setArmed] = useState(false);
  useEffect(() => {
    if (!armed) return;
    const t = setTimeout(() => setArmed(false), 3000);
    return () => clearTimeout(t);
  }, [armed]);
  return (
    <Button
      size="xs"
      variant={armed ? "default" : "ghost"}
      aria-label={armed ? `Confirm removing ${name}` : `Remove ${name}`}
      onClick={() => (armed ? onConfirm() : setArmed(true))}
    >
      {armed ? "Confirm" : "Remove"}
    </Button>
  );
}

const TH = "kicker px-3 py-2 text-left text-[10.5px] font-medium text-ink-muted";

function CompanyRow({ c, onChanged }: { c: RadarCompany; onChanged: () => void }) {
  const fail = (e: Error) => toast.error(errMsg(e));
  const toggle = useMutation({ mutationFn: (enabled: boolean) => api.patchRadarCompany(c.id, { enabled }), onSuccess: onChanged, onError: fail });
  const check = useMutation({
    mutationFn: () => api.checkRadarCompany(c.id),
    onSuccess: () => toast.success(`Polling ${c.name}. New jobs show up on the Jobs page`),
    onError: fail,
  });
  const remove = useMutation({
    mutationFn: () => api.deleteRadarCompany(c.id),
    onSuccess: () => {
      toast.success(`Removed ${c.name}`);
      onChanged();
    },
    onError: fail,
  });
  const polled = POLLED.has(c.ats);
  return (
    <tr className={cn("border-b border-rule align-top hover:bg-hover", !c.enabled && "text-ink-muted")}>
      <td className="px-3 py-3">
        <Switch
          checked={c.enabled}
          onCheckedChange={(v) => toggle.mutate(v)}
          aria-label={`${c.enabled ? "Pause" : "Resume"} ${c.name}`}
        />
      </td>
      <td className="px-3 py-2.5">
        <p className={cn("text-[14.5px] font-medium", c.enabled && "text-ink")}>{c.name}</p>
        <p className="num mt-0.5 text-[11.5px] text-ink-muted">
          {c.city ? cityName(c.city) : "Any city"} · {c.source === "auto" ? "seeded" : "added"}
        </p>
      </td>
      <td className="px-3 py-2.5 whitespace-nowrap">
        <p className="font-mono text-[11.5px] tracking-[0.06em] uppercase">{ATS_LABEL[c.ats] ?? c.ats}</p>
        <p className="kicker mt-0.5 text-[9.5px] text-ink-muted">{polled ? "Polled" : "Page watch"}</p>
      </td>
      <td className="max-w-[16rem] px-3 py-2.5">
        {c.ats_token && <p className="num truncate text-[12.5px]" title={c.ats_token}>{c.ats_token}</p>}
        {c.careers_url && (
          <a href={c.careers_url} target="_blank" rel="noreferrer" className="block truncate text-[12.5px] text-ink-muted hover:text-blue hover:underline">
            {host(c.careers_url)} <span aria-hidden>↗</span>
          </a>
        )}
        {!c.ats_token && !c.careers_url && <span className="text-ink-low">–</span>}
      </td>
      <td className="num px-3 py-2.5 text-[12.5px] whitespace-nowrap" title={c.last_checked_at ? adelaideTime(c.last_checked_at) : undefined}>
        {c.last_checked_at ? ago(c.last_checked_at) : <span className="text-ink-low">Never</span>}
      </td>
      <td className={cn("num px-3 py-2.5 text-right text-[13px]", c.last_job_count ? "font-medium" : "text-ink-muted")}>
        {c.last_job_count ?? "–"}
      </td>
      <td className="max-w-[15rem] px-3 py-2.5 text-[12.5px]">
        {c.last_error ? (
          <p className="line-clamp-2 border-l-2 border-blue pl-2 text-ink" title={c.last_error}>
            {c.last_error}
          </p>
        ) : (
          <span className="text-ink-low">–</span>
        )}
      </td>
      <td className="px-3 py-2.5">
        <div className="flex justify-end gap-1">
          {polled && (
            <Button size="xs" variant="outline" onClick={() => check.mutate()} disabled={check.isPending} aria-label={`Poll ${c.name} now`}>
              Poll
            </Button>
          )}
          <DeleteButton name={c.name} onConfirm={() => remove.mutate()} />
        </div>
      </td>
    </tr>
  );
}

const EMPTY_FORM = { name: "", careers_url: "", city: "", ats: "greenhouse" as RadarAts, ats_token: "" };

export function AddCompanyForm({ onAdded }: { onAdded: () => void }) {
  const [manual, setManual] = useState(false);
  const [f, setF] = useState(EMPTY_FORM);
  const add = useMutation({
    mutationFn: () => {
      const body: RadarCompanyIn = { name: f.name.trim(), careers_url: f.careers_url.trim() || null, city: f.city || null };
      if (manual) Object.assign(body, { ats: f.ats, ats_token: f.ats_token.trim() || null });
      return api.addRadarCompany(body);
    },
    onSuccess: (c) => {
      if (c.last_error) toast.warning(`${c.name} added, but ${c.last_error}`);
      else toast.success(`${c.name} added · ${ATS_LABEL[c.ats] ?? c.ats}${c.ats_token ? ` ${c.ats_token}` : ""}`);
      setF(EMPTY_FORM);
      onAdded();
    },
    onError: (e: Error) => toast.error(errMsg(e)),
  });
  const needsToken = manual && POLLED.has(f.ats);
  const needsUrl = manual && !POLLED.has(f.ats);
  const ready = f.name.trim() && (!needsToken || f.ats_token.trim()) && (!needsUrl || f.careers_url.trim());

  return (
    <form
      className="mt-5"
      onSubmit={(e) => {
        e.preventDefault();
        if (ready) add.mutate();
      }}
    >
      <div role="radiogroup" aria-label="How to find the job feed" className="flex gap-x-6">
        {(
          [
            [false, "Detect from careers page"],
            [true, "I know the ATS"],
          ] as const
        ).map(([m, label]) => (
          <button
            key={label}
            type="button"
            role="radio"
            aria-checked={manual === m}
            onClick={() => setManual(m)}
            className={cn(
              "kicker py-1 text-[11.5px] underline-offset-[7px]",
              manual === m ? "text-ink underline decoration-blue decoration-2" : "text-ink-muted hover:text-ink",
            )}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="mt-4 grid items-end gap-x-5 gap-y-4 sm:grid-cols-2 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)_10rem_auto]">
        <div className="grid gap-1.5">
          <Label htmlFor="radar-name">Company</Label>
          <Input id="radar-name" placeholder="e.g. Canva" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
        </div>
        {manual ? (
          <div className="grid grid-cols-[9.5rem_minmax(0,1fr)] gap-2">
            <div className="grid gap-1.5">
              <Label htmlFor="radar-ats">ATS</Label>
              <select id="radar-ats" className="field h-9 px-2 text-sm outline-none" value={f.ats} onChange={(e) => setF({ ...f, ats: e.target.value as RadarAts })}>
                {(Object.keys(ATS_LABEL) as RadarAts[]).map((a) => (
                  <option key={a} value={a}>
                    {ATS_LABEL[a]}
                  </option>
                ))}
              </select>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="radar-token">Board slug</Label>
              <Input
                id="radar-token"
                className="font-mono text-[13px]"
                placeholder={TOKEN_HINT[f.ats]}
                disabled={!POLLED.has(f.ats)}
                value={f.ats_token}
                onChange={(e) => setF({ ...f, ats_token: e.target.value })}
              />
            </div>
          </div>
        ) : (
          <div className="grid gap-1.5">
            <Label htmlFor="radar-url">Careers page URL</Label>
            <Input id="radar-url" type="url" placeholder="https://… (optional, helps detection)" value={f.careers_url} onChange={(e) => setF({ ...f, careers_url: e.target.value })} />
          </div>
        )}
        <div className="grid gap-1.5">
          <Label htmlFor="radar-city">City</Label>
          <select id="radar-city" className="field h-9 px-2 text-sm outline-none" value={f.city} onChange={(e) => setF({ ...f, city: e.target.value })}>
            <option value="">Any</option>
            {CITIES.map((c) => (
              <option key={c} value={c}>
                {CITY_NAME[c]}
              </option>
            ))}
          </select>
        </div>
        <Button type="submit" disabled={!ready || add.isPending}>
          {add.isPending ? (manual ? "Adding…" : "Detecting…") : manual ? "Add company" : "Add and detect"}
        </Button>
      </div>
      {manual && needsUrl && (
        <div className="mt-3 grid gap-1.5 sm:max-w-xl">
          <Label htmlFor="radar-url-manual">Careers page URL</Label>
          <Input id="radar-url-manual" type="url" placeholder="https://…" value={f.careers_url} onChange={(e) => setF({ ...f, careers_url: e.target.value })} />
        </div>
      )}
      <p className="mt-3 max-w-3xl text-[13px] text-ink-muted">
        {manual
          ? POLLED.has(f.ats)
            ? `${ATS_LABEL[f.ats]} boards are polled every 30 minutes. The slug is the part of the board URL after the domain.`
            : "PageUp and other careers pages have no feed. They're watched for changes by changedetection.io instead."
          : "Detection reads the careers page for a Greenhouse, Lever, Ashby, Workable, SmartRecruiters or Workday board, then tries guesses from the name. It takes a few seconds."}{" "}
        Adding a company that's already listed updates it.
      </p>
    </form>
  );
}

export function RadarPage() {
  const qc = useQueryClient();
  const { data = [], isLoading, error } = useQuery({ queryKey: ["radar", "companies"], queryFn: api.radarCompanies, refetchInterval: 30_000 });
  const refresh = () => qc.invalidateQueries({ queryKey: ["radar", "companies"] });
  const [filter, setFilter] = useState<Filter>("all");
  const [q, setQ] = useState("");
  const fail = (e: Error) => toast.error(errMsg(e));
  const poll = useMutation({
    mutationFn: api.radarPoll,
    onSuccess: () => toast.success("Polling every active company. New jobs show up on the Jobs page"),
    onError: fail,
  });
  const seed = useMutation({
    mutationFn: api.radarSeed,
    onSuccess: () => toast.success("Looking for careers feeds of recent employers. New companies appear here in a few minutes"),
    onError: fail,
  });
  const stats = radarStats(data);
  const needle = q.trim().toLowerCase();
  const rows = data.filter((c) => matches(c, filter) && (!needle || `${c.name} ${c.ats} ${c.ats_token ?? ""}`.toLowerCase().includes(needle)));

  return (
    <Page wide>
      <PageHead
        kicker="Company radar"
        title="Radar"
        dek="Employers whose own careers feeds are checked every 30 minutes, so their ads turn up before SEEK, LinkedIn and the rest repost them."
        actions={
          <>
            <Button onClick={() => poll.mutate()} disabled={poll.isPending}>
              Poll now
            </Button>
            <Button variant="outline" onClick={() => seed.mutate()} disabled={seed.isPending}>
              Seed from recent employers
            </Button>
          </>
        }
      />

      <div className="grid grid-cols-3 border-b border-rule py-2 sm:grid-cols-6" aria-label="Radar summary">
        <Stat label="Companies" value={stats.total} />
        <Stat label="Polled feeds" value={stats.polled} />
        <Stat label="Watched pages" value={stats.watched} />
        <Stat label="Paused" value={stats.paused} tone="muted" />
        <Stat label="With errors" value={stats.errors} tone={stats.errors ? "blue" : "muted"} />
        <Stat label="Jobs on feeds" value={stats.jobs} />
      </div>

      <div className="mt-6 flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
        <div role="tablist" aria-label="Filter companies" className="flex flex-wrap gap-x-6">
          {FILTERS.map(([id, label]) => {
            const n = data.filter((c) => matches(c, id)).length;
            return (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={filter === id}
                onClick={() => setFilter(id)}
                className={cn(
                  "kicker py-1 text-[11.5px] underline-offset-[7px]",
                  filter === id ? "text-ink underline decoration-blue decoration-2" : "text-ink-muted hover:text-ink",
                )}
              >
                {label} <span className="text-ink-low">{n}</span>
              </button>
            );
          })}
        </div>
        <Input className="w-full sm:w-64" placeholder="Search companies" aria-label="Search radar companies" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>

      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[920px] border-collapse">
          <thead>
            <tr className="border-b-2 border-ink">
              <th className={cn(TH, "w-14")}>
                <span className="sr-only">Active</span>
              </th>
              <th className={TH}>Company</th>
              <th className={TH}>ATS</th>
              <th className={TH}>Board</th>
              <th className={TH}>Last polled</th>
              <th className={cn(TH, "text-right")}>Jobs</th>
              <th className={TH}>Last error</th>
              <th className={TH}>
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <CompanyRow key={c.id} c={c} onChanged={refresh} />
            ))}
          </tbody>
        </table>
        {error && <p className="py-12 text-center text-sm text-ink-muted">{errMsg(error)}</p>}
        {!isLoading && !error && !data.length && (
          <p className="py-12 text-center text-sm text-ink-muted">No companies on the radar yet. Seed from recent employers, or add one below.</p>
        )}
        {!isLoading && data.length > 0 && !rows.length && <p className="py-12 text-center text-sm text-ink-muted">No companies match.</p>}
      </div>

      <section className="mt-12">
        <SectionHead>Add a company</SectionHead>
        <AddCompanyForm onAdded={refresh} />
      </section>
    </Page>
  );
}
