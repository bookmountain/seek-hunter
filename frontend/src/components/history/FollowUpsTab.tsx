import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { CopyButton } from "@/components/CopyButton";
import { api, errMsg } from "@/lib/api";
import { adelaideTime } from "@/lib/format";
import type { FollowUp, FollowUpKind } from "@/lib/types";
import { cn } from "@/lib/utils";
import { smallBtn, useInvalidateHistory } from "./shared";

export const FOLLOW_UP_LABEL: Record<FollowUpKind, string> = {
  application_nudge: "Nudge",
  linkedin_invite_pending: "Invite pending",
  linkedin_thank: "Say thanks",
  linkedin_no_reply: "No reply",
};

const CHANNEL_LABEL: Record<FollowUp["channel"], string> = { email: "Email", linkedin: "LinkedIn", phone: "Phone" };
const SNOOZE_DAYS = [1, 3, 7] as const;
const telHref = (p: string) => `tel:${p.replace(/[^\d+]/g, "")}`;

function waited(f: FollowUp): string {
  if (f.kind === "linkedin_thank") return "Accepted your invite";
  if (f.kind === "linkedin_invite_pending") return `Invite sent ${f.days}d ago`;
  if (f.kind === "linkedin_no_reply") return `Messaged ${f.days}d ago`;
  return `Quiet for ${f.days}d`;
}

function mailto(f: FollowUp): string | null {
  if (!f.contact_email) return null;
  const q = new URLSearchParams({ subject: f.subject ?? "", body: f.message }).toString().replace(/\+/g, "%20");
  return `mailto:${f.contact_email}?${q}`;
}

function Item({ f }: { f: FollowUp }) {
  const invalidate = useInvalidateHistory();
  const [note, setNote] = useState("");
  const after = (msg: string) => () => {
    toast.success(msg);
    invalidate(f.job_id);
  };
  const fail = (e: Error) => toast.error(errMsg(e));
  const done = useMutation({ mutationFn: () => api.doneFollowUp(f.key, note.trim()), onSuccess: after("Logged as sent"), onError: fail });
  const snooze = useMutation({
    mutationFn: (days: number) => api.snoozeFollowUp(f.key, days),
    onSuccess: (_r, days) => after(`Snoozed for ${days}d`)(),
    onError: fail,
  });
  const dismiss = useMutation({ mutationFn: () => api.dismissFollowUp(f.key), onSuccess: after("Dismissed"), onError: fail });
  const busy = done.isPending || snooze.isPending || dismiss.isPending;
  const mail = mailto(f);
  const heading = [f.company, f.title].filter(Boolean).join(" · ");

  return (
    <li aria-label={`${FOLLOW_UP_LABEL[f.kind]}: ${heading}`} className="grid gap-x-8 gap-y-3 py-5 lg:grid-cols-[13rem_minmax(0,1fr)]">
      <div>
        <p className={cn("kicker text-[11px]", f.kind === "linkedin_thank" ? "text-blue" : "text-ink")}>{FOLLOW_UP_LABEL[f.kind]}</p>
        <p className="num mt-1 text-[12px] text-ink-muted" title={adelaideTime(f.since)}>
          {waited(f)}
        </p>
        <p className="mt-3 font-display text-[16px] leading-tight font-semibold tracking-[-0.01em]">{f.company || f.contact_name}</p>
        {f.title && (
          <p className="mt-0.5 text-[13.5px]">
            {f.job_id ? (
              <Link to={`/?job=${f.job_id}`} className="underline-offset-4 hover:text-blue hover:underline">
                {f.title}
              </Link>
            ) : (
              f.title
            )}
          </p>
        )}
        {f.contact_name && (
          <div className="mt-2 space-y-0.5 text-[13px]">
            <p>
              {f.contact_id ? (
                <Link to={`/history?tab=contacts&contact=${f.contact_id}`} className="hover:text-blue hover:underline">
                  {f.contact_name}
                </Link>
              ) : (
                f.contact_name
              )}
            </p>
            {f.contact_phone && (
              <a href={telHref(f.contact_phone)} className="num block text-blue hover:underline">
                {f.contact_phone}
              </a>
            )}
            {f.contact_linkedin && (
              <a href={f.contact_linkedin} target="_blank" rel="noreferrer" className="block text-blue hover:underline">
                LinkedIn ↗
              </a>
            )}
          </div>
        )}
      </div>

      <div className="min-w-0">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="kicker text-[10.5px] text-ink-muted">
            Send by <span className="text-ink">{CHANNEL_LABEL[f.channel]}</span>
          </p>
          <div className="flex items-center gap-1.5">
            {mail && (
              <a href={mail} className={cn(smallBtn, "inline-flex items-center")}>
                Open email
              </a>
            )}
            <CopyButton text={f.message} label={`Copy message for ${heading}`} className="h-8 lg:h-8" />
          </div>
        </div>
        {f.subject && (
          <p className="mt-2 flex items-center gap-2 text-[13px]">
            <span className="kicker text-[10px] text-ink-muted">Subject</span>
            <span className="min-w-0 flex-1 truncate">{f.subject}</span>
          </p>
        )}
        <p className="mt-2 border border-rule bg-hover px-3 py-2.5 text-[14px] leading-relaxed whitespace-pre-line">{f.message}</p>
        {f.hint && <p className="mt-2 text-[12.5px] text-ink-muted">{f.hint}</p>}

        <form
          className="mt-3 flex flex-wrap items-center gap-1.5"
          aria-label={`Actions for ${heading}`}
          onSubmit={(e) => {
            e.preventDefault();
            done.mutate();
          }}
        >
          <input
            aria-label="Note"
            className="field h-8 min-w-0 flex-1 basis-48 px-2 text-[13px] outline-none"
            placeholder="Optional note, e.g. what you sent"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          <button type="submit" disabled={busy} className={cn(smallBtn, "border-blue bg-blue text-white hover:text-white hover:opacity-90")}>
            Mark sent
          </button>
          <span className="inline-flex" role="group" aria-label="Snooze">
            {SNOOZE_DAYS.map((d, i) => (
              <button
                key={d}
                type="button"
                disabled={busy}
                onClick={() => snooze.mutate(d)}
                className={cn(smallBtn, i > 0 && "-ml-px")}
                aria-label={`Snooze ${d} day${d > 1 ? "s" : ""}`}
              >
                {i === 0 ? `Snooze ${d}d` : `${d}d`}
              </button>
            ))}
          </span>
          <button type="button" disabled={busy} onClick={() => dismiss.mutate()} className={cn(smallBtn, "border-transparent text-ink-muted")}>
            Dismiss
          </button>
        </form>
      </div>
    </li>
  );
}

export function FollowUpsTab() {
  const { data = [], isLoading, error } = useQuery({ queryKey: ["follow-ups"], queryFn: api.followUps });
  return (
    <div className="max-w-5xl">
      <p className="max-w-2xl text-[14px] text-ink-muted">
        Applications still at Applied with nothing heard for 5+ days, LinkedIn invites not accepted, new connections to thank and
        messages without a reply. Each comes with a message you can send as is.
      </p>
      <p className="kicker mt-5 border-b-2 border-ink pb-1.5 text-ink">
        {isLoading ? "Loading…" : `${data.length} due`}
      </p>
      {error && <p className="py-6 text-[13.5px] text-ink-muted">{errMsg(error)}</p>}
      <ol className="divide-y divide-rule border-b border-rule">
        {data.map((f) => (
          <Item key={f.key} f={f} />
        ))}
      </ol>
      {!isLoading && !error && !data.length && <p className="py-12 text-center text-sm text-ink-muted">Nothing to chase today.</p>}
    </div>
  );
}
