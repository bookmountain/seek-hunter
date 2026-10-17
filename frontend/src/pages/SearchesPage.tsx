import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api";
import { type SearchProfile, WORK_TYPE_LABEL, type WorkType } from "@/lib/types";

const LOCATIONS = ["All Adelaide SA", "All Melbourne VIC", "All Sydney NSW", "All Perth WA", "All Brisbane QLD"];
const TYPES: WorkType[] = ["part_time", "contract", "casual", "full_time"];
const EMPTY: SearchProfile = { name: "", keywords: "", location: LOCATIONS[0], work_types: [], sources: ["seek", "jora"], enabled: true };

function toggle<T>(list: T[], v: T): T[] {
  return list.includes(v) ? list.filter((x) => x !== v) : [...list, v];
}

function ProfileRow({ initial, onSaved }: { initial: SearchProfile; onSaved: () => void }) {
  const [p, setP] = useState(initial);
  const save = useMutation({
    mutationFn: () => (p.id ? api.updateProfile(p) : api.createProfile({ ...p, name: p.name || `${p.location} · ${p.keywords}` })),
    onSuccess: () => {
      toast.success("Saved");
      onSaved();
      if (!p.id) setP(EMPTY);
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const remove = useMutation({ mutationFn: () => api.deleteProfile(p.id!), onSuccess: onSaved });
  return (
    <Card>
      <CardContent className="flex flex-wrap items-center gap-3 py-4">
        <Switch checked={p.enabled} onCheckedChange={(enabled) => setP({ ...p, enabled })} />
        <Input className="w-48" placeholder="keywords" value={p.keywords} onChange={(e) => setP({ ...p, keywords: e.target.value })} />
        <select className="h-9 rounded-md border px-2 text-sm" value={p.location} onChange={(e) => setP({ ...p, location: e.target.value })}>
          {LOCATIONS.map((l) => (
            <option key={l}>{l}</option>
          ))}
        </select>
        <div className="flex gap-1">
          {TYPES.map((t) => (
            <Button key={t} size="sm" variant={p.work_types.includes(t) ? "default" : "outline"} onClick={() => setP({ ...p, work_types: toggle(p.work_types, t) })}>
              {WORK_TYPE_LABEL[t]}
            </Button>
          ))}
        </div>
        <div className="flex gap-1">
          {(["seek", "jora"] as const).map((s) => (
            <Button key={s} size="sm" variant={p.sources.includes(s) ? "secondary" : "ghost"} onClick={() => setP({ ...p, sources: toggle(p.sources, s) })}>
              {s}
            </Button>
          ))}
        </div>
        <div className="ml-auto flex gap-2">
          <Button size="sm" onClick={() => save.mutate()} disabled={!p.keywords}>
            {p.id ? "Save" : "Add"}
          </Button>
          {p.id && (
            <Button size="sm" variant="ghost" onClick={() => remove.mutate()}>
              Delete
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

export function SearchesPage() {
  const qc = useQueryClient();
  const { data = [] } = useQuery({ queryKey: ["profiles"], queryFn: api.profiles });
  const refresh = () => qc.invalidateQueries({ queryKey: ["profiles"] });
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">No work type selected = all types (full-time still ranked lower).</p>
      {data.map((p) => (
        <ProfileRow key={p.id} initial={p} onSaved={refresh} />
      ))}
      <h2 className="pt-4 font-medium">Add search</h2>
      <ProfileRow initial={EMPTY} onSaved={refresh} />
    </div>
  );
}
