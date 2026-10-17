import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, errMsg } from "@/lib/api";
import { ago } from "@/lib/format";
import { type Application, APPLICATION_STAGES, type ApplicationCreate, type ApplicationStage } from "@/lib/types";
import { cn, parseIsoUtc } from "@/lib/utils";
import { STAGE_LABEL, StageSelect, smallBtn, useInvalidateHistory } from "./shared";

const fmtDate = (iso: string) =>
  parseIsoUtc(iso).toLocaleDateString("en-AU", { day: "2-digit", month: "short", year: "2-digit", timeZone: "Australia/Adelaide" });

const TH = "kicker px-3 py-2 text-left text-[10.5px] font-medium text-ink-muted";

function NotesCell({ app, onSave }: { app: Application; onSave: (notes: string) => void }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState(app.notes);
  if (!open)
    return (
      <button type="button" onClick={() => setOpen(true)} className="max-w-[18rem] text-left text-[13px] text-ink-muted hover:text-blue">
        {app.notes ? <span className="line-clamp-2">{app.notes}</span> : <span className="kicker text-[10px]">+ Note</span>}
      </button>
    );
  return (
    <form
      className="flex min-w-[14rem] flex-col gap-1.5"
      onSubmit={(e) => {
        e.preventDefault();
        onSave(text);
        setOpen(false);
      }}
    >
      <textarea
        aria-label={`Notes for ${app.title}`}
        autoFocus
        rows={3}
        className="field px-2 py-1.5 text-[13px] outline-none"
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <span className="flex gap-1.5">
        <button type="submit" className={smallBtn}>
          Save
        </button>
        <button type="button" className={cn(smallBtn, "border-transparent text-ink-muted")} onClick={() => setOpen(false)}>
          Cancel
        </button>
      </span>
    </form>
  );
}

const EMPTY = { company: "", title: "", url: "", date: "", notes: "", name: "", phone: "", email: "", linkedin: "" };

function AddApplication({ onDone }: { onDone: () => void }) {
  const [f, setF] = useState(EMPTY);
  const invalidate = useInvalidateHistory();
  const create = useMutation({
    mutationFn: () => {
      const body: ApplicationCreate = {
        company: f.company.trim(),
        title: f.title.trim(),
        url: f.url.trim() || null,
        applied_at: f.date ? `${f.date}T09:00:00` : null,
        notes: f.notes.trim(),
        contact: f.name.trim()
          ? { name: f.name.trim(), phone: f.phone.trim() || null, email: f.email.trim() || null, linkedin: f.linkedin.trim() || null }
          : null,
      };
      return api.createApplication(body);
    },
    onSuccess: () => {
      toast.success("Application added");
      invalidate();
      setF(EMPTY);
      onDone();
    },
    onError: (e: Error) => toast.error(errMsg(e)),
  });
  const field = (k: keyof typeof EMPTY, label: string, props: React.ComponentProps<"input"> = {}) => (
    <label className="grid gap-1">
      <span className="kicker text-ink-muted">{label}</span>
      <Input value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} {...props} />
    </label>
  );
  return (
    <form
      aria-label="Add application"
      className="mt-4 border border-ink p-4"
      onSubmit={(e) => {
        e.preventDefault();
        create.mutate();
      }}
    >
      <p className="kicker text-ink">Add an application made outside SeekHunter</p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {field("company", "Company", { required: true })}
        {field("title", "Role", { required: true })}
        {field("url", "Ad URL", { type: "url", placeholder: "https://" })}
        {field("date", "Applied on", { type: "date" })}
      </div>
      <label className="mt-3 grid gap-1">
        <span className="kicker text-ink-muted">Notes</span>
        <Input value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} />
      </label>
      <p className="kicker mt-4 text-ink-muted">Contact (optional)</p>
      <div className="mt-2 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {field("name", "Name")}
        {field("phone", "Phone", { type: "tel" })}
        {field("email", "Email", { type: "email" })}
        {field("linkedin", "LinkedIn URL", { type: "url" })}
      </div>
      <div className="mt-4 flex gap-2">
        <Button type="submit" disabled={!f.company.trim() || !f.title.trim() || create.isPending}>
          Add application
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

export function ApplicationsTab({ stage, setStage }: { stage: ApplicationStage | ""; setStage: (s: ApplicationStage | "") => void }) {
  const [adding, setAdding] = useState(false);
  const invalidate = useInvalidateHistory();
  const { data: apps = [], isLoading } = useQuery({ queryKey: ["applications"], queryFn: () => api.applications() });
  const { data: companies = [] } = useQuery({ queryKey: ["companies", ""], queryFn: () => api.companies() });
  const contactsBy = new Map(companies.map((c) => [c.company_key, c.contacts]));
  const patch = useMutation({
    mutationFn: ({ id, body }: { id: number; body: { stage?: ApplicationStage; notes?: string } }) => api.patchApplication(id, body),
    onSuccess: (a) => invalidate(a.job_id),
    onError: (e: Error) => toast.error(errMsg(e)),
  });

  const counts = Object.fromEntries(APPLICATION_STAGES.map((s) => [s, apps.filter((a) => a.stage === s).length]));
  const shown = stage ? apps.filter((a) => a.stage === stage) : apps;

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter by stage">
          {[["", "All", apps.length] as const, ...APPLICATION_STAGES.map((s) => [s, STAGE_LABEL[s], counts[s]] as const)].map(([v, label, n]) => (
            <button
              key={v || "all"}
              type="button"
              aria-pressed={stage === v}
              onClick={() => setStage(v)}
              className={cn(
                "h-8 border px-2.5 font-mono text-[11px] tracking-[0.06em] uppercase",
                stage === v ? "border-ink bg-ink text-white" : n ? "border-input text-ink hover:border-ink" : "border-rule text-ink-muted",
              )}
            >
              {label} <span className={stage === v ? "text-white/70" : "text-ink-muted"}>{n}</span>
            </button>
          ))}
        </div>
        {!adding && (
          <Button variant="outline" onClick={() => setAdding(true)}>
            Add application
          </Button>
        )}
      </div>
      {adding && <AddApplication onDone={() => setAdding(false)} />}

      <div className="mt-5 overflow-x-auto">
        <table className="w-full min-w-[860px] border-collapse text-[13.5px]">
          <caption className="sr-only">Applications</caption>
          <thead>
            <tr className="border-b-2 border-ink">
              <th className={TH}>Applied</th>
              <th className={TH}>Company</th>
              <th className={TH}>Role</th>
              <th className={TH}>Stage</th>
              <th className={TH}>Resume</th>
              <th className={TH}>Contact</th>
              <th className={TH}>Notes</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((a) => {
              const contacts = contactsBy.get(a.company_key) ?? [];
              return (
                <tr key={a.id} className="border-b border-rule align-top hover:bg-hover">
                  <td className="num px-3 py-3 whitespace-nowrap" title={ago(a.applied_at)}>
                    {fmtDate(a.applied_at)}
                  </td>
                  <td className="px-3 py-3 font-semibold">{a.company}</td>
                  <td className="px-3 py-3">
                    {a.job_id ? (
                      <Link to={`/?job=${a.job_id}`} className="text-ink underline-offset-4 hover:text-blue hover:underline">
                        {a.title}
                      </Link>
                    ) : (
                      a.title
                    )}
                    <span className="mt-0.5 block font-mono text-[11px] text-ink-muted">
                      {a.source === "manual" ? "added manually" : a.source === "seekhunter" ? "via SeekHunter" : a.source}
                      {a.url && !a.job_id && (
                        <>
                          {" · "}
                          <a href={a.url} target="_blank" rel="noreferrer" className="text-blue hover:underline">
                            ad ↗
                          </a>
                        </>
                      )}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <StageSelect
                      label={`Stage for ${a.title} at ${a.company}`}
                      value={a.stage}
                      onChange={(s) => patch.mutate({ id: a.id, body: { stage: s } })}
                    />
                  </td>
                  <td className="px-3 py-3 font-mono text-[12px]">
                    {a.tailoring_id && a.job_id ? (
                      <Link to={`/jobs/${a.job_id}/tailor?run=${a.tailoring_id}`} className="text-blue hover:underline">
                        Tailored #{a.tailoring_id}
                      </Link>
                    ) : (
                      <span className="text-ink-muted">—</span>
                    )}
                  </td>
                  <td className="px-3 py-3 text-[13px]">
                    {contacts.length ? contacts.map((c) => c.name).join(", ") : <span className="text-ink-muted">—</span>}
                  </td>
                  <td className="px-3 py-3">
                    <NotesCell app={a} onSave={(notes) => patch.mutate({ id: a.id, body: { notes } })} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {!isLoading && !shown.length && (
          <p className="py-12 text-center text-sm text-ink-muted">
            {apps.length ? "No applications at this stage." : "No applications yet. Mark a job as Applied, or add one made elsewhere."}
          </p>
        )}
      </div>
    </div>
  );
}
