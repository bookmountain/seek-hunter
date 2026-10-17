import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

/** Square hairline "Copy" button that flips to "Copied" for 1.5 s. */
export function CopyButton({ text, label, className }: { text: string; label: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(t);
  }, [copied]);
  return (
    <button
      type="button"
      aria-label={label}
      onClick={() => navigator.clipboard?.writeText(text).then(() => setCopied(true), () => {})}
      className={cn(
        "h-10 shrink-0 border px-3 font-mono text-[10.5px] font-medium tracking-[0.1em] uppercase transition-colors lg:h-7 lg:px-2",
        copied ? "border-blue text-blue" : "border-ink text-ink hover:border-blue hover:text-blue",
        className,
      )}
    >
      <span aria-live="polite">{copied ? "Copied" : "Copy"}</span>
    </button>
  );
}
