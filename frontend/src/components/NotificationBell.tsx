import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { api, errMsg } from "@/lib/api";
import { ago, cityName } from "@/lib/format";
import type { NotificationItem } from "@/lib/types";
import { cn } from "@/lib/utils";

const KEY = ["notifications"];

function BellIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden className="block">
      <path
        d="M10 2.75a4.75 4.75 0 0 0-4.75 4.75v2.6c0 .9-.3 1.78-.86 2.48L3.5 13.75h13l-.89-1.17a4.06 4.06 0 0 1-.86-2.48V7.5A4.75 4.75 0 0 0 10 2.75Z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <path d="M8 16.25a2 2 0 0 0 4 0" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function href(i: NotificationItem): string {
  if (i.type === "job" && i.job_id) return `/?job=${i.job_id}${i.city ? `&city=${i.city}` : ""}`;
  if (i.type === "tailoring" && i.job_id) return `/jobs/${i.job_id}/tailor${i.tailoring_id ? `?run=${i.tailoring_id}` : ""}`;
  return "/history?tab=applications";
}

function Item({ i, onPick }: { i: NotificationItem; onPick: () => void }) {
  return (
    <li className="border-b border-rule last:border-b-0">
      <Link
        to={href(i)}
        onClick={onPick}
        className={cn(
          "relative grid grid-cols-[2.75rem_minmax(0,1fr)] gap-x-3 px-4 py-3 outline-none hover:bg-hover focus-visible:bg-selected",
          "before:absolute before:inset-y-0 before:left-0 before:w-[3px]",
          i.unread ? "before:bg-blue" : "before:bg-transparent",
        )}
      >
        <span className={cn("num pt-px text-[18px] leading-none font-medium", i.score != null && i.score >= 75 ? "text-blue" : "text-ink")}>
          {i.type === "job" ? (i.score ?? "—") : <span className="kicker text-[9.5px] text-ink-muted">{i.type === "tailoring" ? "CV" : "F/U"}</span>}
        </span>
        <span className="min-w-0">
          <span className="block text-[13.5px] leading-snug font-semibold text-ink">
            {i.type === "tailoring" ? `Tailored resume ready — ${i.title}` : i.type === "follow_up" ? `Follow up: ${i.title}` : i.title}
          </span>
          <span className="mt-0.5 block truncate text-[12px] text-ink-muted">
            {i.subtitle}
            {i.city && (
              <>
                <span className="text-ink-faint"> · </span>
                <span className="font-mono text-[11px] uppercase">{cityName(i.city)}</span>
              </>
            )}
            <span className="text-ink-faint"> · </span>
            <span className="font-mono text-[11px]">{ago(i.at)}</span>
          </span>
        </span>
      </Link>
    </li>
  );
}

/** Navbar bell: unread badge, polling every 60 s (and on focus), dropdown panel. */
export function NotificationBell() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const panelId = useId();
  const { data } = useQuery({ queryKey: KEY, queryFn: () => api.notifications(20), refetchInterval: 60_000, refetchOnWindowFocus: true });
  const markRead = useMutation({
    mutationFn: () => api.markNotificationsRead(20),
    onSuccess: (r) => qc.setQueryData(KEY, r),
    onError: (e: Error) => toast.error(errMsg(e)),
  });

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        button.current?.focus();
      }
    };
    const onDown = (e: PointerEvent) => {
      if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("pointerdown", onDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("pointerdown", onDown);
    };
  }, [open]);

  const unread = data?.unread_count ?? 0;

  return (
    <div ref={wrap} className="lg:relative">
      <button
        ref={button}
        type="button"
        aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((o) => !o)}
        className={cn("relative flex size-9 items-center justify-center text-ink hover:text-blue", open && "text-blue")}
      >
        <BellIcon />
        {unread > 0 && (
          <span
            data-testid="bell-badge"
            className="absolute top-0.5 right-0 flex h-[15px] min-w-[15px] items-center justify-center bg-blue px-[3px] font-mono text-[9.5px] leading-none font-medium text-white"
          >
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>
      {open && (
        <div
          id={panelId}
          role="dialog"
          aria-label="Notifications"
          className="absolute inset-x-0 top-full z-40 border border-t-2 border-rule border-t-ink bg-white lg:inset-x-auto lg:right-0 lg:mt-2 lg:w-[400px]"
        >
          <div className="flex items-center justify-between gap-3 px-4 pt-3 pb-2">
            <p className="kicker text-ink">Notifications</p>
            <button
              type="button"
              onClick={() => markRead.mutate()}
              disabled={markRead.isPending || unread === 0}
              className="kicker text-[10.5px] text-blue hover:underline disabled:text-ink-muted disabled:no-underline"
            >
              Mark all read
            </button>
          </div>
          {data && data.by_city.length > 0 && (
            <p data-testid="bell-cities" className="border-b border-rule px-4 pb-2.5 font-mono text-[11px] tracking-[0.06em] text-ink-muted uppercase">
              {data.by_city.map((c, idx) => (
                <span key={c.city}>
                  {idx > 0 && " · "}
                  {cityName(c.city)} <span className="text-ink">{c.count}</span>
                </span>
              ))}
            </p>
          )}
          <ul className="max-h-[min(70vh,520px)] overflow-y-auto">
            {data?.items.map((i, idx) => (
              <Item key={`${i.type}-${i.job_id ?? i.application_id ?? idx}-${i.tailoring_id ?? ""}`} i={i} onPick={() => setOpen(false)} />
            ))}
            {data && !data.items.length && <li className="px-4 py-6 text-[13px] text-ink-muted">You're all caught up.</li>}
            {!data && <li className="kicker px-4 py-6 text-ink-muted">Loading…</li>}
          </ul>
        </div>
      )}
    </div>
  );
}
