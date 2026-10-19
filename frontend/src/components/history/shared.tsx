import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { APPLICATION_STAGES, type ApplicationStage, type Interaction, type InteractionKind } from "@/lib/types";
import { cn } from "@/lib/utils";

export const STAGE_LABEL: Record<ApplicationStage, string> = {
  applied: "Applied",
  screening: "Screening",
  interview: "Interview",
  offer: "Offer",
  rejected: "Rejected",
  withdrawn: "Withdrawn",
  no_response: "No response",
};

export const stageLabel = (s: string) => STAGE_LABEL[s as ApplicationStage] ?? s;

/** Past-tense labels for the timeline ("Called Brayden"). */
export const KIND_PAST: Record<InteractionKind, string> = {
  call: "Called",
  email: "Emailed",
  linkedin_invite: "LinkedIn invite to",
  linkedin_accepted: "Invite accepted by",
  linkedin_message: "LinkedIn message with",
  meeting: "Met",
  note: "Note on",
};

/** Button labels for quick logging. */
export const KIND_BUTTON: Partial<Record<InteractionKind, string>> = {
  call: "Called",
  email: "Emailed",
  linkedin_invite: "LinkedIn invite",
  linkedin_accepted: "Invite accepted",
  meeting: "Meeting",
  note: "Note",
};

/** Invalidate everything an application/contact mutation can change. */
export function useInvalidateHistory() {
  const qc = useQueryClient();
  return useCallback(
    (jobId?: number | null) => {
      for (const key of ["jobs", "applications", "contacts", "contact", "companies", "history"]) {
        qc.invalidateQueries({ queryKey: [key] });
      }
      if (jobId) qc.invalidateQueries({ queryKey: ["job", jobId] });
    },
    [qc],
  );
}

const STAGE_TONE: Partial<Record<ApplicationStage, string>> = {
  interview: "text-blue",
  offer: "text-blue font-semibold",
  rejected: "text-ink-muted",
  withdrawn: "text-ink-muted",
  no_response: "text-ink-muted",
};

/** Inline stage control: a square native select styled as a mono tag. */
export function StageSelect({
  value,
  onChange,
  label = "Stage",
  disabled,
  className,
}: {
  value: ApplicationStage;
  onChange: (s: ApplicationStage) => void;
  label?: string;
  disabled?: boolean;
  className?: string;
}) {
  return (
    <select
      aria-label={label}
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value as ApplicationStage)}
      className={cn(
        "field h-8 cursor-pointer px-1.5 font-mono text-[11.5px] tracking-[0.04em] uppercase outline-none",
        STAGE_TONE[value],
        className,
      )}
    >
      {APPLICATION_STAGES.map((s) => (
        <option key={s} value={s}>
          {STAGE_LABEL[s]}
        </option>
      ))}
    </select>
  );
}

/** Stage as a static mono tag (lists, companies). */
export function StageTag({ stage }: { stage: string }) {
  return (
    <span className={cn("kicker text-[10.5px]", STAGE_TONE[stage as ApplicationStage] ?? "text-ink")}>{stageLabel(stage)}</span>
  );
}

export const smallBtn =
  "h-8 border border-ink px-2.5 font-mono text-[10.5px] font-medium tracking-[0.1em] uppercase transition-colors hover:border-blue hover:text-blue disabled:opacity-40";

/**
 * Quick-log row. Each non-note kind is an on/off toggle: on means an interaction of that kind is logged.
 * Turning one on logs it (carrying the optional note); turning it off removes every entry of that kind.
 * NOTE is a plain action: it opens the note input (or logs it when text is already there).
 */
export function QuickLog({
  kinds,
  interactions,
  onLog,
  onRemove,
  pending,
  withNote = true,
}: {
  kinds: InteractionKind[];
  /** What's logged so far; drives each toggle's on/off state. */
  interactions: Interaction[];
  /** Resolves to the created interaction (its `id` lets the toggle turn off before the list refetches). */
  onLog: (kind: InteractionKind, note: string) => Promise<unknown> | void;
  onRemove: (id: number) => Promise<unknown>;
  pending?: boolean;
  withNote?: boolean;
}) {
  const [note, setNote] = useState("");
  const [noteOpen, setNoteOpen] = useState(false);
  const [busy, setBusy] = useState<InteractionKind | null>(null);
  // Optimistic on/off per kind until the refetched list agrees; `created` covers ids the list hasn't caught up with.
  const [override, setOverride] = useState<Partial<Record<InteractionKind, boolean>>>({});
  const created = useRef<Partial<Record<InteractionKind, number>>>({});
  const loggedIds = (k: InteractionKind) => {
    const ids = interactions.filter((i) => i.kind === k).map((i) => i.id);
    const extra = created.current[k];
    return extra !== undefined && !ids.includes(extra) ? [...ids, extra] : ids;
  };
  const isOn = (k: InteractionKind) => override[k] ?? interactions.some((i) => i.kind === k);
  // Once the list agrees with an override, drop it so later edits elsewhere (row deletes) show through.
  const serverKey = interactions.map((i) => `${i.id}:${i.kind}`).join(",");
  useEffect(() => {
    const has = (k: InteractionKind) => interactions.some((i) => i.kind === k);
    for (const [k, id] of Object.entries(created.current) as [InteractionKind, number][])
      if (interactions.some((i) => i.id === id)) delete created.current[k];
    setOverride((o) => {
      const stale = (Object.keys(o) as InteractionKind[]).filter((k) => o[k] === has(k));
      if (!stale.length) return o;
      const next = { ...o };
      for (const k of stale) delete next[k];
      return next;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverKey]);

  const logNote = async () => {
    try {
      await onLog("note", note.trim());
    } catch {
      return; // the caller toasts the error
    }
    setNote("");
    setNoteOpen(false);
  };
  const toggle = async (k: InteractionKind) => {
    const turnOn = !isOn(k);
    setBusy(k);
    try {
      if (turnOn) {
        const res = await onLog(k, note.trim());
        if (res && typeof res === "object" && "id" in res) created.current[k] = Number((res as { id: unknown }).id);
        setNote("");
        setNoteOpen(false);
      } else {
        for (const id of loggedIds(k)) await onRemove(id);
        delete created.current[k];
      }
      setOverride((o) => ({ ...o, [k]: turnOn }));
    } catch {
      // the caller toasts the error
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Log an interaction">
        {kinds.map((k) => {
          if (k === "note")
            return (
              <button
                key={k}
                type="button"
                className={cn(smallBtn, noteOpen && "border-blue text-blue")}
                disabled={pending}
                onClick={() => {
                  if (noteOpen && note.trim()) return void logNote();
                  setNoteOpen(true);
                }}
              >
                {KIND_BUTTON[k] ?? k}
              </button>
            );
          const on = isOn(k);
          return (
            <button
              key={k}
              type="button"
              aria-pressed={on}
              title={on ? "Logged. Click to remove" : "Click to log"}
              disabled={pending || busy !== null}
              onClick={() => void toggle(k)}
              className={cn(
                "inline-flex h-8 items-center gap-1.5 border px-2.5 font-mono text-[10.5px] font-medium tracking-[0.1em] uppercase transition-colors disabled:opacity-60",
                on ? "border-blue bg-blue text-white hover:opacity-90" : "border-input text-ink-muted hover:border-ink hover:text-ink",
              )}
            >
              <span aria-hidden className={cn("size-[7px]", on ? "bg-white" : "border border-current")} />
              {KIND_BUTTON[k] ?? k}
            </button>
          );
        })}
      </div>
      {withNote && (
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (note.trim()) void logNote();
          }}
        >
          <input
            aria-label="Note"
            autoFocus={noteOpen}
            key={noteOpen ? "open" : "closed"}
            className={cn("field h-8 min-w-0 flex-1 px-2 text-[13px] outline-none", noteOpen && "border-blue")}
            placeholder={noteOpen ? "Write the note, then Enter" : "Optional note for the next log"}
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          {noteOpen && (
            <button type="submit" className={smallBtn} disabled={!note.trim() || pending}>
              Save note
            </button>
          )}
        </form>
      )}
    </div>
  );
}
