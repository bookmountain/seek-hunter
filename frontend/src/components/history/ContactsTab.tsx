import { useMutation, useQuery } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useDebouncedInput } from "@/hooks/useDebouncedInput";
import { api, errMsg } from "@/lib/api";
import { adelaideTime, ago } from "@/lib/format";
import type { Contact, InteractionKind } from "@/lib/types";
import { cn } from "@/lib/utils";
import { KIND_BUTTON, QuickLog, StageTag, useInvalidateHistory } from "./shared";

const TH = "kicker px-3 py-2 text-left text-[10.5px] font-medium text-ink-muted";
const QUICK: InteractionKind[] = ["call", "email", "linkedin_invite", "linkedin_accepted", "meeting", "note"];
const KIND_NAME: Record<string, string> = { ...KIND_BUTTON, linkedin_message: "LinkedIn message" };
const CONTACTS_HELP =
  "People you've contacted or applied through. Log a call, email or LinkedIn invite from a job's Recruiter block to add someone.";
const telHref = (p: string) => `tel:${p.replace(/[^\d+]/g, "")}`;

function ContactDetailRow({ contact, colSpan }: { contact: Contact; colSpan: number }) {
  const invalidate = useInvalidateHistory();
  const { data } = useQuery({ queryKey: ["contact", contact.id], queryFn: () => api.contact(contact.id) });
  const log = useMutation({
    mutationFn: ({ kind, note }: { kind: InteractionKind; note: string }) => api.createInteraction({ contact_id: contact.id, kind, note }),
    onSuccess: () => invalidate(),
    onError: (e: Error) => toast.error(errMsg(e)),
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.deleteInteraction(id),
    onSuccess: () => invalidate(),
    onError: (e: Error) => toast.error(errMsg(e)),
  });
  const interactions = [...(data?.interactions ?? [])].sort((a, b) => b.at.localeCompare(a.at));

  return (
    <tr className="border-b border-ink bg-hover">
      <td colSpan={colSpan} className="px-3 pt-3 pb-5">
        <div className="grid gap-8 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
          <section aria-label={`Interactions with ${contact.name}`}>
            <p className="kicker text-ink-muted">Log</p>
            <div className="mt-2">
              <QuickLog kinds={QUICK} pending={log.isPending} onLog={(kind, note) => log.mutateAsync({ kind, note })} onUndo={(id) => remove.mutateAsync(id)} />
            </div>
            <ol className="mt-4 divide-y divide-rule border-y border-rule">
              {interactions.map((i) => (
                <li key={i.id} className="flex items-start gap-3 py-2">
                  <span className="num w-28 shrink-0 pt-0.5 text-[11.5px] text-ink-muted">{adelaideTime(i.at)}</span>
                  <span className="min-w-0 flex-1 text-[13.5px]">
                    <span className="kicker mr-2 text-[10.5px] text-ink">{KIND_NAME[i.kind] ?? i.kind}</span>
                    {i.note && <span className="text-ink-muted">{i.note}</span>}
                  </span>
                  <button
                    type="button"
                    aria-label={`Delete ${KIND_NAME[i.kind] ?? i.kind} on ${adelaideTime(i.at)}`}
                    onClick={() => remove.mutate(i.id)}
                    className="kicker shrink-0 text-[10px] text-ink-muted hover:text-blue"
                  >
                    Delete
                  </button>
                </li>
              ))}
              {data && !interactions.length && <li className="py-3 text-[13px] text-ink-muted">Nothing logged yet.</li>}
            </ol>
          </section>
          <section aria-label="Linked jobs and applications" className="space-y-4">
            <div>
              <p className="kicker text-ink-muted">Jobs</p>
              <ul className="mt-1.5 space-y-1 text-[13.5px]">
                {data?.jobs.map((j) => (
                  <li key={j.id}>
                    <Link to={`/?job=${j.id}`} className="hover:text-blue hover:underline">
                      {j.title}
                    </Link>{" "}
                    <span className="text-ink-muted">· {j.company}</span>
                  </li>
                ))}
                {data && !data.jobs.length && <li className="text-ink-muted">None</li>}
              </ul>
            </div>
            <div>
              <p className="kicker text-ink-muted">Applications</p>
              <ul className="mt-1.5 space-y-1 text-[13.5px]">
                {data?.applications.map((a) => (
                  <li key={a.id} className="flex flex-wrap items-baseline gap-x-2">
                    <span>{a.title}</span>
                    <span className="num text-[11.5px] text-ink-muted">{ago(a.applied_at)}</span>
                    <StageTag stage={a.stage} />
                  </li>
                ))}
                {data && !data.applications.length && <li className="text-ink-muted">None</li>}
              </ul>
            </div>
            {contact.notes && (
              <div>
                <p className="kicker text-ink-muted">Notes</p>
                <p className="mt-1.5 text-[13.5px]">{contact.notes}</p>
              </div>
            )}
          </section>
        </div>
      </td>
    </tr>
  );
}

const EMPTY = { name: "", company: "", role: "", phone: "", email: "", linkedin: "" };

function AddContact({ onDone }: { onDone: () => void }) {
  const [f, setF] = useState(EMPTY);
  const invalidate = useInvalidateHistory();
  const create = useMutation({
    mutationFn: () =>
      api.createContact({
        name: f.name.trim(),
        company: f.company.trim(),
        role: f.role.trim() || null,
        phone: f.phone.trim() || null,
        email: f.email.trim() || null,
        linkedin: f.linkedin.trim() || null,
      }),
    onSuccess: () => {
      toast.success("Contact added");
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
      aria-label="Add contact"
      className="mt-4 border border-ink p-4"
      onSubmit={(e) => {
        e.preventDefault();
        create.mutate();
      }}
    >
      <div className="grid gap-3 sm:grid-cols-3">
        {field("name", "Name", { required: true })}
        {field("company", "Company")}
        {field("role", "Role")}
        {field("phone", "Phone", { type: "tel" })}
        {field("email", "Email", { type: "email" })}
        {field("linkedin", "LinkedIn URL", { type: "url" })}
      </div>
      <div className="mt-4 flex gap-2">
        <Button type="submit" disabled={!f.name.trim() || create.isPending}>
          Add contact
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

export function ContactsTab({ initialOpen, q: urlQ, setQ: commitQ }: { initialOpen?: number | null; q: string; setQ: (q: string) => void }) {
  const [q, setQ] = useDebouncedInput(urlQ, commitQ);
  const [open, setOpen] = useState<number | null>(initialOpen ?? null);
  const [adding, setAdding] = useState(false);
  const { data: contacts = [], isLoading } = useQuery({ queryKey: ["contacts", urlQ], queryFn: () => api.contacts(urlQ || undefined), placeholderData: (p) => p });

  return (
    <div>
      <p className="mb-4 max-w-2xl text-[14px] text-ink-muted">{CONTACTS_HELP}</p>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Input className="w-full sm:w-72" placeholder="Search name or company" aria-label="Search contacts" value={q} onChange={(e) => setQ(e.target.value)} />
        {!adding && (
          <Button variant="outline" onClick={() => setAdding(true)}>
            Add contact
          </Button>
        )}
      </div>
      {adding && <AddContact onDone={() => setAdding(false)} />}
      <div className="mt-5 overflow-x-auto">
        <table className="w-full min-w-[880px] border-collapse text-[13.5px]">
          <caption className="sr-only">Contacts</caption>
          <thead>
            <tr className="border-b-2 border-ink">
              <th className={TH}>Name</th>
              <th className={TH}>Company · role</th>
              <th className={TH}>Phone</th>
              <th className={TH}>Email</th>
              <th className={TH}>LinkedIn</th>
              <th className={TH}>Last contact</th>
              <th className={cn(TH, "text-right")}>Contacts · jobs · apps</th>
            </tr>
          </thead>
          <tbody>
            {contacts.map((c) => {
              const expanded = open === c.id;
              return (
                <Fragment key={c.id}>
                  <tr className={cn("border-b border-rule align-top", expanded ? "bg-selected" : "hover:bg-hover")}>
                    <td className="px-3 py-3">
                      <button
                        type="button"
                        aria-expanded={expanded}
                        onClick={() => setOpen(expanded ? null : c.id)}
                        className="flex items-center gap-2 text-left font-semibold hover:text-blue"
                      >
                        <span aria-hidden className={cn("inline-block font-mono text-[11px] text-ink-muted transition-transform", expanded && "rotate-90")}>
                          ›
                        </span>
                        {c.name}
                      </button>
                    </td>
                    <td className="px-3 py-3">
                      {c.company || <span className="text-ink-muted">—</span>}
                      {c.role && <span className="block text-[12px] text-ink-muted">{c.role}</span>}
                    </td>
                    <td className="num px-3 py-3 whitespace-nowrap">
                      {c.phone ? (
                        <a href={telHref(c.phone)} className="text-blue hover:underline">
                          {c.phone}
                        </a>
                      ) : (
                        <span className="text-ink-muted">—</span>
                      )}
                    </td>
                    <td className="px-3 py-3 font-mono text-[12px]">
                      {c.email ? (
                        <a href={`mailto:${c.email}`} className="text-blue hover:underline">
                          {c.email}
                        </a>
                      ) : (
                        <span className="text-ink-muted">—</span>
                      )}
                    </td>
                    <td className="px-3 py-3 text-[13px]">
                      {c.linkedin ? (
                        <a href={c.linkedin} target="_blank" rel="noreferrer" className="text-blue hover:underline">
                          Profile ↗
                        </a>
                      ) : (
                        <span className="text-ink-muted">—</span>
                      )}
                    </td>
                    <td className="num px-3 py-3 text-[12px] whitespace-nowrap">
                      {c.last_interaction ? ago(c.last_interaction) : <span className="text-ink-muted">never</span>}
                    </td>
                    <td className="num px-3 py-3 text-right text-[12px]">
                      {c.interaction_count} · {c.job_count} · {c.application_count}
                    </td>
                  </tr>
                  {expanded && <ContactDetailRow contact={c} colSpan={7} />}
                </Fragment>
              );
            })}
          </tbody>
        </table>
        {!isLoading && !contacts.length && (
          <div className="py-12 text-center">
            <p className="mx-auto max-w-lg text-[14px] text-ink-muted">{urlQ ? "No contacts match." : CONTACTS_HELP}</p>
            {!urlQ && (
              <Link to="/" className="kicker mt-3 inline-block text-blue hover:underline">
                Go to Jobs
              </Link>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

