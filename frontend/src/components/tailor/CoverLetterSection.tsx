import { useState } from "react";
import { CopyButton } from "@/components/CopyButton";
import type { CoverLetter, TailoringDetail } from "@/lib/types";
import { cn } from "@/lib/utils";
import { RichText } from "./RichText";

type Regen = NonNullable<TailoringDetail["cover_letter_regen"]>;

export function CoverLetterSection({
  letter,
  pages,
  regen,
  onRegenerate,
  starting,
}: {
  letter: CoverLetter;
  pages: string[];
  regen: Regen | null;
  onRegenerate: () => void;
  starting: boolean;
}) {
  const [view, setView] = useState<"text" | "pdf">("text");
  const busy = starting || regen?.status === "queued" || regen?.status === "running";
  return (
    <section aria-labelledby="cover-letter-title" className="mt-14">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3 border-b-2 border-ink pb-2">
        <h2 id="cover-letter-title" className="kicker text-ink">
          Cover letter
        </h2>
        <span className="num text-[11.5px] text-ink-muted">{letter.word_count} words</span>
        <div className="ml-auto flex items-center gap-3">
          <div role="group" aria-label="Cover letter view" className="inline-flex border border-ink">
            {(["text", "pdf"] as const).map((v, i) => (
              <button
                key={v}
                type="button"
                aria-pressed={view === v}
                onClick={() => setView(v)}
                className={cn(
                  "h-7 px-3 font-mono text-[10.5px] font-medium tracking-[0.1em] uppercase",
                  i > 0 && "border-l border-ink",
                  view === v ? "bg-ink text-white" : "text-ink hover:text-blue",
                )}
              >
                {v === "text" ? "Text" : "PDF"}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={onRegenerate}
            disabled={busy}
            className="inline-flex h-7 items-center gap-2 border border-ink px-3 font-mono text-[10.5px] font-medium tracking-[0.1em] uppercase transition-colors hover:border-blue hover:text-blue disabled:border-blue disabled:text-blue"
          >
            {busy && <span aria-hidden className="size-[7px] animate-pulse bg-blue" />}
            {busy ? "Writing new letter…" : "Regenerate letter"}
          </button>
          <CopyButton text={letter.text} label="Copy cover letter" className="lg:h-7" />
        </div>
      </div>
      {regen?.status === "failed" && (
        <p role="alert" className="mt-3 bg-chip px-3 py-2 text-[13px]">
          Couldn't write a new letter; the one below is unchanged. <span className="text-ink-muted">{regen.error}</span>
        </p>
      )}

      {view === "text" ? (
        <div className={cn("mt-6 max-w-[68ch] space-y-4 text-[16px] leading-[1.65] transition-opacity", busy && "opacity-50")}>
          <p>{letter.greeting}</p>
          {letter.paragraphs.map((p, i) => (
            <p key={i}>
              <RichText text={p} />
            </p>
          ))}
          <p className="whitespace-pre-line">{letter.sign_off}</p>
        </div>
      ) : (
        <div className="mt-6 max-w-[760px] space-y-6">
          {pages.map((url, i) => (
            <figure key={url}>
              <img src={url} alt={`Cover letter page ${i + 1}`} className="block w-full border border-ink/80" />
              <figcaption className="num mt-1.5 text-right text-[11px] text-ink-muted">
                Page {i + 1} / {pages.length}
              </figcaption>
            </figure>
          ))}
          {!pages.length && <p className="text-sm text-ink-muted">No PDF pages.</p>}
        </div>
      )}
    </section>
  );
}
