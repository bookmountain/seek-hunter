import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { JobDrawer } from "@/components/JobDrawer";
import { JobTable } from "@/components/JobTable";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api } from "@/lib/api";
import type { Job } from "@/lib/types";

const ALL = "all";

export function JobsPage({ view }: { view: "active" | "excluded" }) {
  const [q, setQ] = useState("");
  const [workType, setWorkType] = useState(ALL);
  const [status, setStatus] = useState(ALL);
  const [source, setSource] = useState(ALL);
  const [selected, setSelected] = useState<Job | null>(null);
  const params = {
    view,
    q,
    work_type: workType === ALL ? undefined : workType,
    status: status === ALL ? undefined : status,
    source: source === ALL ? undefined : source,
  };
  const { data = [], isLoading } = useQuery({ queryKey: ["jobs", params], queryFn: () => api.jobs(params) });

  const select = (value: string, onChange: (v: string) => void, options: [string, string][], placeholder: string) => (
    <Select value={value} onValueChange={(v) => onChange(v as string)}>
      <SelectTrigger className="w-36">
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        {options.map(([v, label]) => (
          <SelectItem key={v} value={v}>
            {label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Input className="w-64" placeholder="Search title or company" value={q} onChange={(e) => setQ(e.target.value)} />
        {select(workType, setWorkType, [[ALL, "All types"], ["part_time", "Part time"], ["contract", "Contract"], ["casual", "Casual"], ["full_time", "Full time"]], "Type")}
        {view === "active" &&
          select(status, setStatus, [[ALL, "Any status"], ["new", "New"], ["saved", "Saved"], ["applied", "Applied"], ["hidden", "Hidden"]], "Status")}
        {select(source, setSource, [[ALL, "All sources"], ["seek", "SEEK"], ["jora", "Jora"]], "Source")}
        <span className="ml-auto text-sm text-muted-foreground">{isLoading ? "Loading…" : `${data.length} jobs`}</span>
      </div>
      <JobTable jobs={data} view={view} onSelect={setSelected} />
      <JobDrawer job={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
