import { useQuery } from "@tanstack/react-query";
import { useDebouncedInput } from "@/hooks/useDebouncedInput";
import { Link } from "react-router-dom";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { ago } from "@/lib/format";
import { StageTag } from "./shared";

export function CompaniesTab({ q: urlQ, setQ: commitQ }: { q: string; setQ: (q: string) => void }) {
  const [q, setQ] = useDebouncedInput(urlQ, commitQ);
  const { data = [], isLoading } = useQuery({ queryKey: ["companies", urlQ], queryFn: () => api.companies(urlQ || undefined), placeholderData: (p) => p });
  return (
    <div>
      <Input className="w-full sm:w-72" placeholder="Search companies" aria-label="Search companies" value={q} onChange={(e) => setQ(e.target.value)} />
      <ul className="mt-5 border-t-2 border-ink">
        {data.map((c) => (
          <li key={c.company_key} className="grid gap-x-8 gap-y-2 border-b border-rule py-4 md:grid-cols-[minmax(0,16rem)_minmax(0,1fr)_minmax(0,14rem)]">
            <div>
              <p className="font-display text-[17px] font-semibold tracking-[-0.01em]">{c.company}</p>
              <p className="num mt-0.5 text-[11.5px] text-ink-muted">
                {c.application_count} {c.application_count === 1 ? "application" : "applications"} · last {ago(c.last_applied_at)}
              </p>
            </div>
            <ul className="space-y-1.5">
              {c.applications.map((a) => (
                <li key={a.id} className="flex flex-wrap items-baseline gap-x-3 text-[13.5px]">
                  <span>{a.title}</span>
                  <span className="num text-[11.5px] text-ink-muted">{ago(a.applied_at)}</span>
                  <StageTag stage={a.stage} />
                </li>
              ))}
            </ul>
            <div className="text-[13px]">
              <p className="kicker text-[10px] text-ink-muted">Contacts</p>
              {c.contacts.length ? (
                <p className="mt-1">
                  {c.contacts.map((p, i) => (
                    <span key={p.id}>
                      {i > 0 && ", "}
                      <Link to={`/history?tab=contacts&contact=${p.id}`} className="hover:text-blue hover:underline">
                        {p.name}
                      </Link>
                    </span>
                  ))}
                </p>
              ) : (
                <p className="mt-1 text-ink-muted">None</p>
              )}
            </div>
          </li>
        ))}
      </ul>
      {!isLoading && !data.length && <p className="py-12 text-center text-sm text-ink-muted">No companies have your resume yet.</p>}
    </div>
  );
}
