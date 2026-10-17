import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { parseIsoUtc } from "@/lib/utils";

const fmt = (iso: string | null) =>
  iso ? parseIsoUtc(iso).toLocaleString("en-AU", { timeZone: "Australia/Adelaide" }) : "—";

export function RunsPage() {
  const { data = [] } = useQuery({ queryKey: ["runs"], queryFn: api.runs, refetchInterval: 30_000 });
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Started</TableHead>
          <TableHead>Sources</TableHead>
          <TableHead>New</TableHead>
          <TableHead>Notified</TableHead>
          <TableHead>AI</TableHead>
          <TableHead>Error</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {data.map((r) => (
          <TableRow key={r.id}>
            <TableCell>{fmt(r.started_at)}</TableCell>
            <TableCell className="space-x-1">
              {Object.entries(r.source_status).map(([name, st]) => (
                <Badge key={name} variant={st.status === "ok" ? "secondary" : "destructive"} title={st.error ?? ""}>
                  {name} {st.new}/{st.found} · {st.requests} req{st.blocked ? ` · ${st.blocked}×403` : ""}
                </Badge>
              ))}
            </TableCell>
            <TableCell>{r.new_jobs}</TableCell>
            <TableCell>{r.notified}</TableCell>
            <TableCell>{r.llm_provider ?? "rules"}</TableCell>
            <TableCell className="max-w-xs truncate text-sm text-destructive">{r.error}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
