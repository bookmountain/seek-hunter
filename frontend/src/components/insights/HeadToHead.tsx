import { useRef, useState } from "react";
import { useWidth } from "@/hooks/useWidth";
import type { CompareResult } from "@/lib/types";
import { CITY_LABEL, niceShareMax, pct, SERIES } from "./format";
import { LegendKey, Marker, TableView, Tooltip } from "./marks";

const ROW = 30;
const LABEL_W = 84;
const VALUE_W = 124;

/** One small multiple: a dot plot of 2–3 skills across the four cities on a shared 0–max scale. */
export function HeadToHeadPanel({ title, data }: { title: string; data: CompareResult }) {
  const wrap = useRef<HTMLDivElement>(null);
  const width = useWidth(wrap, 320);
  const [hover, setHover] = useState<{ row: number; s: number } | null>(null);
  const skills = data.skills.slice(0, SERIES.length);
  const max = niceShareMax(Math.max(0, ...data.cities.flatMap((c) => skills.map((s) => c.shares[s] ?? 0))));
  const plotW = Math.max(60, width - LABEL_W - VALUE_W);
  const x = (v: number) => LABEL_W + (v / max) * plotW;
  const height = data.cities.length * ROW + 22;

  return (
    <figure className="min-w-0 border-t-2 border-ink pt-3">
      <figcaption className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <span className="font-display text-[15px] font-semibold tracking-[-0.01em]">{title}</span>
        <span className="flex flex-wrap gap-x-3 gap-y-1">
          {skills.map((s, i) => (
            <LegendKey key={s} shape={SERIES[i].shape} color={SERIES[i].color}>
              {s}
            </LegendKey>
          ))}
        </span>
      </figcaption>
      <div ref={wrap} className="relative mt-2">
        <svg width={width} height={height} role="group" aria-label={`${title}: share of ads by city`} className="block overflow-visible">
          {[0, max].map((t) => (
            <text key={t} x={x(t)} y={height - 4} textAnchor={t ? "end" : "start"} className="fill-ink-muted font-mono text-[10px]">
              {pct(t)}
            </text>
          ))}
          {data.cities.map((c, row) => {
            const y = row * ROW + ROW / 2;
            const vals = skills.map((s) => c.shares[s] ?? 0);
            const lead = vals.indexOf(Math.max(...vals));
            return (
              <g key={c.city}>
                <text x={0} y={y} dominantBaseline="central" className="fill-ink text-[12px]">
                  {CITY_LABEL[c.city]}
                </text>
                <line x1={x(0)} x2={x(max)} y1={y} y2={y} stroke="var(--rule)" />
                {/* leader value, labelled selectively */}
                <text x={width} y={y} dominantBaseline="central" textAnchor="end" className="fill-ink-muted font-mono text-[11px]">
                  {vals[lead] > 0 ? `${skills[lead]} ${pct(vals[lead])}` : "—"}
                </text>
                {skills.map((s, i) => (
                  <g
                    key={s}
                    role="img"
                    tabIndex={0}
                    aria-label={`${CITY_LABEL[c.city]}, ${s}: ${pct(vals[i])}`}
                    onPointerEnter={() => setHover({ row, s: i })}
                    onPointerLeave={() => setHover(null)}
                    onFocus={() => setHover({ row, s: i })}
                    onBlur={() => setHover(null)}
                    className="outline-none"
                  >
                    <circle cx={x(vals[i])} cy={y} r={12} fill="transparent" />
                    <Marker shape={SERIES[i].shape} color={SERIES[i].color} x={x(vals[i])} y={y} r={hover?.row === row && hover.s === i ? 6 : 4.5} />
                  </g>
                ))}
              </g>
            );
          })}
        </svg>
        {hover && (
          <Tooltip x={x(data.cities[hover.row].shares[skills[hover.s]] ?? 0)} y={hover.row * ROW + 6}>
            <strong className="font-medium">{pct(data.cities[hover.row].shares[skills[hover.s]] ?? 0)}</strong>
            <span className="text-ink-muted">
              {" "}
              · {skills[hover.s]} · {CITY_LABEL[data.cities[hover.row].city]}
            </span>
          </Tooltip>
        )}
      </div>
      <TableView
        caption={title}
        head={["City", ...skills, "Ads"]}
        rows={data.cities.map((c) => [CITY_LABEL[c.city], ...skills.map((s) => pct(c.shares[s] ?? 0)), c.detailed_sample_size])}
      />
    </figure>
  );
}
