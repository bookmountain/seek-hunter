import type { ReactNode } from "react";
import { SERIES } from "./format";

type Shape = (typeof SERIES)[number]["shape"];

/** Series marker with a 2px white ring so overlapping marks stay legible. */
export function Marker({ shape, color, x, y, r = 4.5 }: { shape: Shape; color: string; x: number; y: number; r?: number }) {
  const common = { fill: color, stroke: "#fff", strokeWidth: 2, paintOrder: "stroke" as const };
  if (shape === "square") return <rect x={x - r} y={y - r} width={r * 2} height={r * 2} {...common} />;
  if (shape === "diamond") {
    const d = r * 1.25;
    return <path d={`M${x} ${y - d}L${x + d} ${y}L${x} ${y + d}L${x - d} ${y}Z`} {...common} />;
  }
  return <circle cx={x} cy={y} r={r} {...common} />;
}

/** Legend key that mirrors the mark. */
export function LegendKey({ shape, color, children }: { shape: Shape; color: string; children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 font-mono text-[11.5px] text-ink">
      <svg width="12" height="12" aria-hidden>
        <Marker shape={shape} color={color} x={6} y={6} r={4} />
      </svg>
      {children}
    </span>
  );
}

/** Floating readout: value strong, label secondary. Positioned inside a `relative` chart wrapper. */
export function Tooltip({ x, y, children }: { x: number; y: number; children: ReactNode }) {
  return (
    <div
      role="presentation"
      className="pointer-events-none absolute z-10 min-w-28 -translate-x-1/2 -translate-y-full border border-ink bg-white px-2.5 py-1.5 font-mono text-[11.5px] leading-snug whitespace-nowrap"
      style={{ left: x, top: y - 8 }}
    >
      {children}
    </div>
  );
}

/** Collapsible table view so every charted value is reachable without hovering. */
export function TableView({ caption, head, rows }: { caption: string; head: string[]; rows: (string | number)[][] }) {
  return (
    <details className="mt-3">
      <summary className="kicker cursor-pointer py-1 text-ink-muted hover:text-blue">View as table</summary>
      <div className="mt-2 overflow-x-auto">
        <table className="num w-full border-collapse text-[12px]">
          <caption className="sr-only">{caption}</caption>
          <thead>
            <tr className="border-b border-ink">
              {head.map((h, i) => (
                <th key={h} className={`kicker px-2 py-1.5 text-[10px] font-medium text-ink-muted ${i ? "text-right" : "text-left"}`}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={String(r[0])} className="border-b border-rule">
                {r.map((c, i) => (
                  <td key={i} className={`px-2 py-1 ${i ? "text-right" : ""}`}>
                    {c}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
