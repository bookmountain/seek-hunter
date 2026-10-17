import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { APPLICATION_STAGES, type ApplicationStage, type InteractionKind } from "@/lib/types";
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
 * Quick-log row. Non-note kinds log immediately, carrying the optional note if one was typed;
 * NOTE opens the note input (or logs it when text is already there).
 */
export function QuickLog({
  kinds,
  onLog,
  onUndo,
  pending,
  withNote = true,
}: {
  kinds: InteractionKind[];
  /** Resolves to the created interaction (its `id` powers UNDO). */
  onLog: (kind: InteractionKind, note: string) => Promise<unknown> | void;
  onUndo?: (id: number) => Promise<unknown>;
  pending?: boolean;
  withNote?: boolean;
}) {
  const [note, setNote] = useState("");
  const [noteOpen, setNoteOpen] = useState(false);
  const [logged, setLogged] = useState<{ label: string; id: number | null } | null>(null);
  const [undone, setUndone] = useState(false);
  const timer = useRef<number | null>(null);
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);
  const show = (next: { label: string; id: number | null } | null, undoneNow = false) => {
    setLogged(next);
    setUndone(undoneNow);
    if (timer.current) clearTimeout(timer.current);
    if (next) timer.current = window.setTimeout(() => setLogged(null), 8000);
  };
  const log = async (kind: InteractionKind) => {
    let created: unknown;
    try {
      created = await onLog(kind, note.trim());
    } catch {
      return; // the caller toasts the error
    }
    const id = created && typeof created === "object" && "id" in created ? Number((created as { id: unknown }).id) : null;
    show({ label: KIND_BUTTON[kind] ?? kind, id });
    setNote("");
    setNoteOpen(false);
  };
  const undo = async () => {
    if (!logged?.id || !onUndo) return;
    try {
      await onUndo(logged.id);
      show({ ...logged, id: null }, true);
    } catch {
      // caller toasts
    }
  };
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Log an interaction">
        {kinds.map((k) => (
          <button
            key={k}
            type="button"
            className={cn(smallBtn, k === "note" && noteOpen && "border-blue text-blue")}
            disabled={pending}
            onClick={() => {
              if (k !== "note") return void log(k);
              if (noteOpen && note.trim()) return void log("note");
              setNoteOpen(true);
            }}
          >
            {KIND_BUTTON[k] ?? k}
          </button>
        ))}
        {logged && (
          <span role="status" className="ml-1 inline-flex items-center gap-2 font-mono text-[11.5px] text-blue">
            {undone ? `Removed · ${logged.label}` : `Logged · ${logged.label}`}
            {!undone && logged.id !== null && onUndo && (
              <button type="button" onClick={undo} className="kicker border-b border-blue text-[10.5px] text-blue hover:text-ink">
                Undo
              </button>
            )}
          </span>
        )}
      </div>
      {withNote && (
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (note.trim()) void log("note");
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
