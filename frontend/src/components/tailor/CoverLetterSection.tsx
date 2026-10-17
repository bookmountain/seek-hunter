import { useState } from "react";
import { CopyButton } from "@/components/CopyButton";
import type { CoverLetter } from "@/lib/types";
import { cn } from "@/lib/utils";
import { RichText } from "./RichText";

export function CoverLetterSection({ letter, pages }: { letter: CoverLetter; pages: string[] }) {
  const [view, setView] = useState<"text" | "pdf">("text");
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
          <CopyButton text={letter.text} label="Copy cover letter" className="lg:h-7" />
        </div>
      </div>

      {view === "text" ? (
        <div className="mt-6 max-w-[68ch] space-y-4 text-[16px] leading-[1.65]">
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
