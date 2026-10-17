import type { ReactNode } from "react";

const TOKEN = /\[([^\]]+)\]\(([^)\s]+)\)|\*\*([^*]+)\*\*/g;
const SAFE_URL = /^(https?:|mailto:)/i;

/** Renders the tailoring text subset: `[label](url)` as a link (http/https/mailto only) and `**bold**`. */
export function RichText({ text }: { text: string }) {
  const out: ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(TOKEN)) {
    const at = m.index ?? 0;
    if (at > last) out.push(text.slice(last, at));
    const [, label, url, bold] = m;
    if (bold !== undefined) {
      out.push(<strong key={at} className="font-semibold">{bold}</strong>);
    } else if (SAFE_URL.test(url)) {
      out.push(
        <a key={at} href={url} target="_blank" rel="noreferrer" className="text-blue underline-offset-4 hover:underline">
          {label}
        </a>,
      );
    } else {
      out.push(label);
    }
    last = at + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return <>{out}</>;
}
