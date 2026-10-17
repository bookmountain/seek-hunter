import { forwardRef, useRef, useState } from "react";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";

type Side = "current" | "tailored";

const Column = forwardRef<
  HTMLDivElement,
  { side: Side; title: string; urls: string[]; pending?: string; hidden: boolean; onScroll: () => void }
>(function Column({ side, title, urls, pending, hidden, onScroll }, ref) {
  return (
    <section aria-label={`${title} resume`} className={cn("min-w-0", hidden && "hidden lg:block")}>
      <div className="flex items-baseline justify-between border-b-2 border-ink pb-2">
        <h2 className={cn("kicker", side === "tailored" ? "text-blue" : "text-ink")}>{title}</h2>
        <span className="num text-[11.5px] text-ink-muted">
          {urls.length ? `${urls.length} ${urls.length === 1 ? "page" : "pages"}` : ""}
        </span>
      </div>
      <div
        ref={ref}
        onScroll={onScroll}
        data-preview={side}
        className="mt-4 space-y-6 lg:h-[calc(100dvh-15rem)] lg:min-h-[480px] lg:overflow-y-auto lg:pr-2"
      >
        {urls.length ? (
          urls.map((url, i) => (
            <figure key={url}>
              <img
                src={url}
                alt={`${title} resume page ${i + 1}`}
                loading={i === 0 ? "eager" : "lazy"}
                className="block w-full border border-ink/80 bg-white"
              />
              <figcaption className="num mt-1.5 text-right text-[11px] text-ink-muted">
                Page {i + 1} / {urls.length}
              </figcaption>
            </figure>
          ))
        ) : (
          <div className="flex aspect-[1/1.414] items-center justify-center border border-dashed border-input">
            <p className="kicker text-ink-muted">{pending ?? "No pages"}</p>
          </div>
        )}
      </div>
    </section>
  );
});

/** Current vs tailored resume pages, side by side with optional synced scrolling (one column + toggle on mobile). */
export function PagePreviews({
  current,
  tailored,
  currentPending,
}: {
  current: string[];
  tailored: string[];
  currentPending?: string;
}) {
  const [sync, setSync] = useState(true);
  const [side, setSide] = useState<Side>("tailored");
  const left = useRef<HTMLDivElement>(null);
  const right = useRef<HTMLDivElement>(null);
  // Which column is driving the scroll, so the follower's own scroll event is ignored.
  const driver = useRef<Side | null>(null);
  const release = useRef<number | null>(null);

  const follow = (from: Side) => {
    if (!sync) return;
    if (driver.current && driver.current !== from) return;
    driver.current = from;
    const src = from === "current" ? left.current : right.current;
    const dst = from === "current" ? right.current : left.current;
    if (src && dst) {
      const max = src.scrollHeight - src.clientHeight;
      const ratio = max > 0 ? src.scrollTop / max : 0;
      dst.scrollTop = ratio * (dst.scrollHeight - dst.clientHeight);
    }
    if (release.current) clearTimeout(release.current);
    release.current = window.setTimeout(() => (driver.current = null), 120);
  };

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div role="group" aria-label="Show" className="inline-flex border border-ink lg:hidden">
          {(["current", "tailored"] as const).map((s, i) => (
            <button
              key={s}
              type="button"
              aria-pressed={side === s}
              onClick={() => setSide(s)}
              className={cn(
                "h-9 px-4 font-mono text-[11px] font-medium tracking-[0.1em] uppercase",
                i > 0 && "border-l border-ink",
                side === s ? "bg-ink text-white" : "text-ink hover:text-blue",
              )}
            >
              {s}
            </button>
          ))}
        </div>
        <label className="ml-auto hidden cursor-pointer items-center gap-2.5 lg:flex">
          <span className="kicker text-ink-muted">Sync scroll</span>
          <Switch checked={sync} onCheckedChange={setSync} aria-label="Sync scroll" />
        </label>
      </div>
      <div className="grid gap-8 lg:grid-cols-2">
        <Column
          ref={left}
          side="current"
          title="Current"
          urls={current}
          pending={currentPending}
          hidden={side !== "current"}
          onScroll={() => follow("current")}
        />
        <Column
          ref={right}
          side="tailored"
          title="Tailored"
          urls={tailored}
          hidden={side !== "tailored"}
          onScroll={() => follow("tailored")}
        />
      </div>
    </div>
  );
}
