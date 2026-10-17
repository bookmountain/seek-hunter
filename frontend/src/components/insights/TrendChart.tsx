import { useRef, useState } from "react";
import { useWidth } from "@/hooks/useWidth";
import type { TrendsResult } from "@/lib/types";
import { parseIsoUtc } from "@/lib/utils";
import { niceShareMax, pct, SERIES } from "./format";
import { LegendKey, Marker, TableView } from "./marks";

const H = 220;
const PAD = { top: 12, right: 120, bottom: 26, left: 40 };

const day = (iso: string) => parseIsoUtc(iso).toLocaleDateString("en-AU", { day: "numeric", month: "short", timeZone: "UTC" });

/** Multi-line share over time, up to three skills in fixed slots (colour follows the slot, not the rank). */
export function TrendChart({ data, slots }: { data: TrendsResult; slots: (string | null)[] }) {
  const wrap = useRef<HTMLDivElement>(null);
  const width = useWidth(wrap);
  const [hi, setHi] = useState<number | null>(null);
  const series = slots.map((s, i) => (s ? { skill: s, ...SERIES[i] } : null)).filter((s) => s !== null);
  const pts = data.points;
  const max = niceShareMax(Math.max(0, ...pts.flatMap((p) => series.map((s) => p.shares[s.skill] ?? 0))));
  const plotW = Math.max(120, width - PAD.left - PAD.right);
  const plotH = H - PAD.top - PAD.bottom;
  const x = (i: number) => PAD.left + (pts.length > 1 ? (i / (pts.length - 1)) * plotW : plotW / 2);
  const y = (v: number) => PAD.top + plotH - (v / max) * plotH;
  const ticks = [0, max / 2, max];

  const onMove = (e: React.PointerEvent<SVGRectElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const rel = (e.clientX - r.left) / Math.max(1, r.width);
    setHi(Math.max(0, Math.min(pts.length - 1, Math.round(rel * (pts.length - 1)))));
  };
  const last = pts.length - 1;

  // End labels: spread converging labels at least 14px apart and connect them with leader lines.
  const endLabels = series
    .map((s) => {
      const v = pts[last]?.shares[s.skill] ?? 0;
      return { ...s, v, y: y(v), ly: y(v) };
    })
    .sort((a, b) => a.y - b.y);
  for (let i = 1; i < endLabels.length; i++) {
    endLabels[i].ly = Math.max(endLabels[i].ly, endLabels[i - 1].ly + 14);
  }

  return (
    <div>
      <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1">
        {series.map((s) => (
          <LegendKey key={s.skill} shape={s.shape} color={s.color}>
            {s.skill}
          </LegendKey>
        ))}
      </div>
      <div ref={wrap} className="relative">
        <svg width={width} height={H} role="img" aria-label={`Share of ads over time for ${series.map((s) => s.skill).join(", ")}`} className="block">
          {ticks.map((t) => (
            <g key={t}>
              <line x1={PAD.left} x2={PAD.left + plotW} y1={y(t)} y2={y(t)} stroke="var(--rule)" />
              <text x={PAD.left - 6} y={y(t)} dominantBaseline="central" textAnchor="end" className="fill-ink-muted font-mono text-[10.5px]">
                {pct(t)}
              </text>
            </g>
          ))}
          {[0, last].filter((v, i, a) => a.indexOf(v) === i).map((i) => (
            <text key={i} x={x(i)} y={H - 6} textAnchor={i === 0 ? "start" : "end"} className="fill-ink-muted font-mono text-[10.5px]">
              {day(pts[i].date)}
            </text>
          ))}
          {series.map((s) => (
            <polyline
              key={s.skill}
              points={pts.map((p, i) => `${x(i)},${y(p.shares[s.skill] ?? 0)}`).join(" ")}
              fill="none"
              stroke={s.color}
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
            />
          ))}
          {endLabels.map((l) => (
            <g key={l.skill}>
              {Math.abs(l.ly - l.y) > 1 && (
                <line x1={x(last) + 6} y1={l.y} x2={x(last) + 16} y2={l.ly} stroke="var(--ink-faint)" strokeWidth={1} />
              )}
              <Marker shape={l.shape} color={l.color} x={x(last)} y={l.y} />
              <text x={x(last) + 20} y={l.ly} dominantBaseline="central" className="fill-ink font-mono text-[11px]">
                {l.skill} {pct(l.v)}
              </text>
            </g>
          ))}
          {hi !== null && <line x1={x(hi)} x2={x(hi)} y1={PAD.top} y2={PAD.top + plotH} stroke="var(--ink)" strokeWidth={1} />}
          <rect
            x={PAD.left}
            y={PAD.top}
            width={plotW}
            height={plotH}
            fill="transparent"
            onPointerMove={onMove}
            onPointerLeave={() => setHi(null)}
          />
        </svg>
        {hi !== null && (
          <div
            className="pointer-events-none absolute z-10 border border-ink bg-white px-2.5 py-1.5 font-mono text-[11.5px] leading-snug"
            style={{ left: Math.min(x(hi) + 10, width - 150), top: PAD.top }}
          >
            <p className="text-ink-muted">{day(pts[hi].date)}</p>
            {series.map((s) => (
              <p key={s.skill} className="flex items-center gap-2">
                <span aria-hidden className="inline-block h-0.5 w-3" style={{ background: s.color }} />
                <strong className="font-medium">{pct(pts[hi].shares[s.skill] ?? 0)}</strong>
                <span className="text-ink-muted">{s.skill}</span>
              </p>
            ))}
          </div>
        )}
      </div>
      <TableView
        caption="Skill share over time"
        head={["Date", ...series.map((s) => s.skill)]}
        rows={pts.map((p) => [day(p.date), ...series.map((s) => pct(p.shares[s.skill] ?? 0))])}
      />
    </div>
  );
}
