import { useId, useRef, useState } from "react";
import { useWidth } from "@/hooks/useWidth";
import type { SkillShare } from "@/lib/types";
import { niceShareMax, pct } from "./format";
import { TableView, Tooltip } from "./marks";

const ROW = 28;
const BAR = 14;
const LABEL_W = 150;
const VALUE_W = 78;

/** Horizontal bars, emphasis form: ink = you have it, grey = you don't; blue marker + "you" on your skills. */
export function SkillBars({ data, cityLabel }: { data: SkillShare[]; cityLabel: string }) {
  const wrap = useRef<HTMLDivElement>(null);
  const width = useWidth(wrap);
  const titleId = useId();
  const descId = useId();
  const [hover, setHover] = useState<number | null>(null);

  const max = niceShareMax(Math.max(0, ...data.map((d) => d.share)));
  const labelW = width < 480 ? 112 : LABEL_W;
  const plotW = Math.max(80, width - labelW - VALUE_W);
  const x = (v: number) => (v / max) * plotW;
  const height = data.length * ROW + 24;
  const ticks = [0, max / 2, max];
  const haveCount = data.filter((d) => d.you_have).length;

  return (
    <div ref={wrap} className="relative">
      <svg
        width={width}
        height={height}
        role="group"
        aria-labelledby={`${titleId} ${descId}`}
        className="block overflow-visible"
      >
        <title id={titleId}>Top {data.length} skills in {cityLabel} job ads</title>
        <desc id={descId}>
          Share of detailed ads mentioning each skill. You have {haveCount} of the {data.length}.
        </desc>
        {/* grid + axis */}
        {ticks.map((t) => (
          <g key={t} transform={`translate(${labelW + x(t)},0)`}>
            <line y1={0} y2={data.length * ROW} stroke="var(--rule)" />
            <text y={data.length * ROW + 16} textAnchor="middle" className="fill-ink-muted font-mono text-[10.5px]">
              {pct(t)}
            </text>
          </g>
        ))}
        {data.map((d, i) => {
          const y = i * ROW;
          const w = Math.max(1, x(d.share));
          const active = hover === i;
          return (
            <g
              key={d.skill}
              tabIndex={0}
              role="img"
              aria-label={`${d.skill}: ${pct(d.share)} of ads, ${d.count} ads${d.you_have ? ", you have it" : ""}`}
              onPointerEnter={() => setHover(i)}
              onPointerLeave={() => setHover(null)}
              onFocus={() => setHover(i)}
              onBlur={() => setHover(null)}
              className="outline-none focus-visible:[&>rect.hit]:stroke-blue"
            >
              <rect className="hit" x={0} y={y} width={width} height={ROW} fill={active ? "var(--hover)" : "transparent"} strokeWidth={1} />
              {d.you_have && <rect x={labelW - 12} y={y + ROW / 2 - 3} width={6} height={6} fill="var(--blue)" />}
              <text
                x={labelW - (d.you_have ? 18 : 10)}
                y={y + ROW / 2}
                dominantBaseline="central"
                textAnchor="end"
                className="fill-ink text-[12.5px]"
              >
                {d.skill.length > 20 ? `${d.skill.slice(0, 19)}…` : d.skill}
              </text>
              <rect
                x={labelW}
                y={y + (ROW - BAR) / 2}
                width={w}
                height={BAR}
                fill={d.you_have ? "var(--ink)" : "var(--ink-low)"}
                opacity={hover !== null && !active ? 0.55 : 1}
              />
              <text x={labelW + w + 6} y={y + ROW / 2} dominantBaseline="central" className="fill-ink font-mono text-[11.5px]">
                {pct(d.share)}
                {d.you_have && <tspan className="fill-ink-muted" dx={6}>you</tspan>}
              </text>
            </g>
          );
        })}
      </svg>
      {hover !== null && data[hover] && (
        <Tooltip x={Math.min(width - 70, labelW + x(data[hover].share) / 2 + 40)} y={hover * ROW + 4}>
          <strong className="font-medium text-ink">{pct(data[hover].share)}</strong>
          <span className="text-ink-muted"> · {data[hover].count} ads</span>
          <br />
          <span className="text-ink-muted">{data[hover].skill}{data[hover].you_have ? " · on your resume" : ""}</span>
        </Tooltip>
      )}
      <TableView
        caption={`Top skills in ${cityLabel}`}
        head={["Skill", "Share", "Ads", "You"]}
        rows={data.map((d) => [d.skill, pct(d.share), d.count, d.you_have ? "yes" : ""])}
      />
    </div>
  );
}
