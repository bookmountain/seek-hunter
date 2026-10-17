import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Page, PageHead, SectionHead } from "@/components/PageHead";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { api, errMsg } from "@/lib/api";
import { FLEXIBLE_TYPES } from "@/lib/format";
import { type SearchProfile, WORK_TYPE_LABEL, type WorkType } from "@/lib/types";
import { cn } from "@/lib/utils";

const LOCATIONS = ["All Adelaide SA", "All Melbourne VIC", "All Sydney NSW", "All Perth WA", "All Brisbane QLD"];
const TYPES: WorkType[] = ["part_time", "contract", "casual", "full_time"];
const EMPTY: SearchProfile = { name: "", keywords: "", location: LOCATIONS[0], work_types: [], sources: ["seek", "jora"], enabled: true };

function toggle<T>(list: T[], v: T): T[] {
  return list.includes(v) ? list.filter((x) => x !== v) : [...list, v];
}

/** Square small-caps toggle chip. */
function Chip({ on, onClick, children, tone = "ink" }: { on: boolean; onClick: () => void; children: React.ReactNode; tone?: "ink" | "blue" }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={cn(
        "inline-flex h-8 items-center gap-1.5 border px-2.5 font-mono text-[11px] font-medium tracking-[0.1em] whitespace-nowrap uppercase transition-colors",
        on
          ? tone === "blue"
            ? "border-blue bg-selected text-blue"
            : "border-ink bg-chip text-ink"
          : "border-input text-ink-muted hover:border-ink hover:text-ink",
      )}
    >
      <span aria-hidden className={cn("size-[7px]", on ? (tone === "blue" ? "bg-blue" : "bg-ink") : "border border-current")} />
      {children}
    </button>
  );
}

function ProfileRow({ initial, onSaved, index }: { initial: SearchProfile; onSaved: () => void; index?: number }) {
  const [p, setP] = useState(initial);
  const save = useMutation({
    mutationFn: () => (p.id ? api.updateProfile(p) : api.createProfile({ ...p, name: p.name || `${p.location} · ${p.keywords}` })),
    onSuccess: () => {
      toast.success("Saved");
      onSaved();
      if (!p.id) setP(EMPTY);
    },
    onError: (e: Error) => toast.error(errMsg(e)),
  });
  const remove = useMutation({
    mutationFn: () => api.deleteProfile(p.id!),
    onSuccess: onSaved,
    onError: (e: Error) => toast.error(errMsg(e)),
  });
  return (
    <div className={cn("grid gap-x-5 gap-y-3 border-b border-rule py-4 md:grid-cols-[2.5rem_auto_minmax(10rem,1fr)_11rem] xl:grid-cols-[2rem_auto_minmax(9rem,1fr)_10.5rem_auto_auto_auto] xl:items-center", !p.enabled && "opacity-60")}>
      <span className="num hidden text-[13px] text-ink-muted md:block">{index !== undefined ? String(index + 1).padStart(2, "0") : "+"}</span>
      <Switch checked={p.enabled} onCheckedChange={(enabled) => setP({ ...p, enabled })} aria-label="Enabled" />
      <Input placeholder="keywords" aria-label="Keywords" value={p.keywords} onChange={(e) => setP({ ...p, keywords: e.target.value })} />
      <select
        aria-label="Location"
        className="field h-9 px-2 text-sm outline-none"
        value={p.location}
        onChange={(e) => setP({ ...p, location: e.target.value })}
      >
        {LOCATIONS.map((l) => (
          <option key={l}>{l}</option>
        ))}
      </select>
      <div className="flex flex-wrap gap-1 xl:flex-nowrap md:col-start-3 xl:col-start-auto" role="group" aria-label="Work types">
        {TYPES.map((t) => (
          <Chip key={t} on={p.work_types.includes(t)} tone={FLEXIBLE_TYPES.has(t) ? "blue" : "ink"} onClick={() => setP({ ...p, work_types: toggle(p.work_types, t) })}>
            {WORK_TYPE_LABEL[t]}
          </Chip>
        ))}
      </div>
      <div className="flex gap-1" role="group" aria-label="Sources">
        {(["seek", "jora"] as const).map((s) => (
          <Chip key={s} on={p.sources.includes(s)} onClick={() => setP({ ...p, sources: toggle(p.sources, s) })}>
            {s}
          </Chip>
        ))}
      </div>
      <div className="flex gap-2 xl:justify-end">
        <Button size="sm" onClick={() => save.mutate()} disabled={!p.keywords}>
          {p.id ? "Save" : "Add"}
        </Button>
        {p.id && (
          <Button size="sm" variant="ghost" onClick={() => remove.mutate()}>
            Delete
          </Button>
        )}
      </div>
    </div>
  );
}

export function SearchesPage() {
  const qc = useQueryClient();
  const { data = [] } = useQuery({ queryKey: ["profiles"], queryFn: api.profiles });
  const refresh = () => qc.invalidateQueries({ queryKey: ["profiles"] });
  return (
    <Page wide>
      <PageHead
        kicker="Crawl profiles"
        title="Searches"
        dek="What gets crawled on SEEK and Jora each run. No work type selected means all types; full-time is still ranked lower."
      />
      <div className="mt-2">
        {data.map((p, i) => (
          <ProfileRow key={p.id} index={i} initial={p} onSaved={refresh} />
        ))}
      </div>
      <div className="mt-10">
        <SectionHead>Add a search</SectionHead>
        <ProfileRow initial={EMPTY} onSaved={refresh} />
      </div>
    </Page>
  );
}
