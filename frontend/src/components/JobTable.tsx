import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { type Job, WORK_TYPE_LABEL } from "@/lib/types";
import { ScoreBadge } from "./ScoreBadge";

const since = (iso: string) => {
  const h = Math.round((Date.now() - new Date(iso.endsWith("Z") ? iso : `${iso}Z`).getTime()) / 3_600_000);
  return h < 24 ? `${h}h` : `${Math.round(h / 24)}d`;
};

export function JobTable({ jobs, view, onSelect }: { jobs: Job[]; view: "active" | "excluded"; onSelect: (j: Job) => void }) {
  if (!jobs.length) return <p className="py-12 text-center text-muted-foreground">No jobs yet.</p>;
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-14">Score</TableHead>
          <TableHead>Role</TableHead>
          <TableHead>Type</TableHead>
          <TableHead>{view === "excluded" ? "Reason" : "Skills"}</TableHead>
          <TableHead className="w-16">Seen</TableHead>
          <TableHead className="w-20">Status</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {jobs.map((j) => (
          <TableRow key={j.id} className="cursor-pointer" onClick={() => onSelect(j)}>
            <TableCell>
              <ScoreBadge score={j.final_score} />
            </TableCell>
            <TableCell>
              <div className="font-medium">{j.title}</div>
              <div className="text-sm text-muted-foreground">
                {j.company} · {j.location} · {j.source}
              </div>
            </TableCell>
            <TableCell>
              <Badge variant={j.flags.includes("flexible") ? "default" : "secondary"}>{WORK_TYPE_LABEL[j.work_type]}</Badge>
              {j.flags.includes("hours") && <span className="ml-1" title="Stated hours may exceed visa limit">⚠️</span>}
            </TableCell>
            <TableCell className="max-w-xs text-sm">
              {view === "excluded" ? j.reasons.join(", ") : j.matched_skills.slice(0, 5).join(", ")}
            </TableCell>
            <TableCell className="text-sm text-muted-foreground">{since(j.first_seen_at)}</TableCell>
            <TableCell className="text-sm">{j.status}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
