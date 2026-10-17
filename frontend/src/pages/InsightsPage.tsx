import { useQueries, useQuery } from "@tanstack/react-query";
import { CITIES, CITY_LABEL, money, pct, ROLE_FAMILIES, roleLabel, SERIES } from "@/components/insights/format";
import { HeadToHeadPanel } from "@/components/insights/HeadToHead";
import { SkillBars } from "@/components/insights/SkillBars";
import { TrendChart } from "@/components/insights/TrendChart";
import { usePersistedFilters } from "@/hooks/usePersistedFilters";
import { api, errMsg } from "@/lib/api";
import type { City, CityOverview } from "@/lib/types";
import { cn } from "@/lib/utils";

const DAYS = 14;

const FILTER_DEFAULTS = { city: "adelaide", role_family: "", skills: "" };

export const HEAD_TO_HEAD: { title: string; skills: string[] }[] = [
  { title: "Java vs C#", skills: ["Java", "C#"] },
  { title: "TypeScript vs JavaScript", skills: ["TypeScript", "JavaScript"] },
  { title: "React vs Angular vs Vue", skills: ["React", "Angular", "Vue"] },
  { title: "AWS vs Azure vs GCP", skills: ["AWS", "Azure", "GCP"] },
  { title: "Python vs Node.js", skills: ["Python", "Node.js"] },
];

function Section({ id, title, note, actions, children }: { id: string; title: string; note?: React.ReactNode; actions?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section aria-labelledby={id} className="mt-12">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2 border-b-2 border-ink pb-2">
        <div>
          <h2 id={id} className="display text-[22px] leading-none">
            {title}
          </h2>
          {note && <p className="mt-1.5 text-[13px] text-ink-muted">{note}</p>}
        </div>
        {actions}
      </div>
      <div className="mt-4">{children}</div>
    </section>
  );
}

function Overview({ rows, city }: { rows: CityOverview[]; city: City }) {
  const best = Math.max(...rows.map((r) => r.flexible_share));
  const TH = "kicker px-3 py-2 text-[10.5px] font-medium text-ink-muted";
  return (
    <div className="overflow-x-auto">
      <table className="num w-full min-w-[560px] border-collapse text-[13px]">
        <caption className="sr-only">Overview by city, last {DAYS} days</caption>
        <thead>
          <tr className="border-b border-ink">
            <th className={cn(TH, "text-left")}>City</th>
            <th className={cn(TH, "text-right")}>Jobs</th>
            <th className={cn(TH, "text-right")}>Flexible</th>
            <th className={cn(TH, "text-right")}>Median $/h (p25–p75)</th>
            <th className={cn(TH, "text-right")}>Detailed sample</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.city} className={cn("border-b border-rule", r.city === city && "bg-selected")}>
              <th scope="row" className="px-3 py-2.5 text-left font-sans text-[14px] font-medium">
                {CITY_LABEL[r.city]}
              </th>
              <td className="px-3 py-2.5 text-right">{r.total}</td>
              <td className={cn("px-3 py-2.5 text-right whitespace-nowrap", r.total > 0 && r.flexible_share === best && "font-medium text-blue")}>
                {pct(r.flexible_share)} <span className="text-ink-muted">({r.flexible})</span>
              </td>
              <td className="px-3 py-2.5 text-right whitespace-nowrap">
                {money(r.salary_p50)}
                {r.salary_p25 !== null && r.salary_p75 !== null && (
                  <span className="text-ink-muted">
                    {" "}
                    ({money(r.salary_p25)}–{money(r.salary_p75)})
                  </span>
                )}
                <span className="ml-1 text-[11px] text-ink-muted">n={r.salary_sample_size}</span>
              </td>
              <td className="px-3 py-2.5 text-right">{r.detailed_sample_size}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function InsightsPage() {
  const filters = usePersistedFilters("insights", FILTER_DEFAULTS);
  const raw = filters.values.city;
  const city: City = CITIES.includes(raw as City) ? (raw as City) : "adelaide";
  const role = filters.values.role_family;
  const setFilter = filters.set;
  const setRole = (r: string) => setFilter({ role_family: r });
  // Trend skills as three fixed slots, "a,,c" in the URL ("" = use the top three).
  const slots: (string | null)[] | null = filters.values.skills
    ? [0, 1, 2].map((i) => filters.values.skills.split(",")[i] || null)
    : null;
  const setSlots = (next: (string | null)[]) => setFilter({ skills: next.map((s) => s ?? "").join(",") });

  const overview = useQuery({ queryKey: ["insights", "overview", DAYS], queryFn: () => api.insightsOverview(DAYS) });
  const skillsAll = useQuery({ queryKey: ["insights", "skills", city, ""], queryFn: () => api.insightsSkills(city, undefined, DAYS) });
  const skillsRole = useQuery({
    queryKey: ["insights", "skills", city, role],
    queryFn: () => api.insightsSkills(city, role, DAYS),
    enabled: !!role,
    placeholderData: (prev) => prev,
  });
  const gaps = useQuery({ queryKey: ["insights", "gaps", city], queryFn: () => api.insightsGaps(city, DAYS) });
  const roles = useQuery({ queryKey: ["insights", "roles", city], queryFn: () => api.insightsRoles(city, DAYS) });
  const compares = useQueries({
    queries: HEAD_TO_HEAD.map((g) => ({
      queryKey: ["insights", "compare", g.skills.join(","), DAYS],
      queryFn: () => api.insightsCompare(g.skills, DAYS),
    })),
  });

  const all = skillsAll.data ?? [];
  const chart = (role ? skillsRole.data : all) ?? [];
  const defaultSlots = [all[0]?.skill ?? null, all[1]?.skill ?? null, all[2]?.skill ?? null];
  const activeSlots = slots ?? defaultSlots;
  const trendSkills = activeSlots.filter((s): s is string => !!s);
  const trends = useQuery({
    queryKey: ["insights", "trends", city, trendSkills.join(",")],
    queryFn: () => api.insightsTrends(city, trendSkills),
    enabled: trendSkills.length > 0,
    placeholderData: (prev) => prev,
  });

  const have = new Set(all.filter((s) => s.you_have).map((s) => s.skill));
  const cityRow = overview.data?.find((r) => r.city === city);
  const empty = !!overview.data && overview.data.every((r) => r.total === 0);

  const setCity = (c: City) => setFilter({ city: c, skills: "" });

  const toggleTrend = (skill: string) => {
    const cur = [...activeSlots];
    const at = cur.indexOf(skill);
    if (at >= 0) cur[at] = null;
    else {
      const free = cur.indexOf(null);
      if (free < 0) return;
      cur[free] = skill;
    }
    setSlots(cur);
  };

  return (
    <div className="mx-auto w-full max-w-6xl px-5 py-8 lg:px-8 lg:py-10">
      <header className="border-b-2 border-ink pb-4">
        <p className="kicker text-ink-muted">Insights</p>
        <h1 className="display mt-2 text-[44px] leading-none">Market</h1>
        <div className="mt-6 flex flex-wrap items-end justify-between gap-x-8 gap-y-3">
          <nav aria-label="City" className="flex flex-wrap gap-x-6 gap-y-2">
            {CITIES.map((c) => (
              <button
                key={c}
                type="button"
                aria-current={c === city ? "page" : undefined}
                onClick={() => setCity(c)}
                className={cn(
                  "kicker py-1 text-[12px] underline-offset-[7px]",
                  c === city ? "text-ink underline decoration-blue decoration-2" : "text-ink-muted hover:text-ink",
                )}
              >
                {CITY_LABEL[c]}
              </button>
            ))}
          </nav>
          <p className="font-mono text-[11.5px] text-ink-muted">
            Last {DAYS} days
            {cityRow && (
              <>
                {" "}
                · {cityRow.total} jobs · {cityRow.detailed_sample_size} full ads read
              </>
            )}
          </p>
        </div>
      </header>

      {overview.error ? (
        <p className="mt-10 bg-chip px-4 py-3 text-sm">{errMsg(overview.error)}</p>
      ) : !overview.data ? (
        <p className="kicker mt-10 text-ink-muted">Loading…</p>
      ) : empty ? (
        <div className="mx-auto mt-16 max-w-lg text-center">
          <div aria-hidden className="mx-auto mb-5 size-3 bg-blue" />
          <p className="text-[16px] leading-relaxed">Market data is collected nightly at 02:30. The first crawl may still be running.</p>
        </div>
      ) : (
        <>
          <Section id="ins-overview" title="Overview" note="All four cities. Salary is AUD per hour where the ad states one.">
            <Overview rows={overview.data} city={city} />
          </Section>

          <Section
            id="ins-skills"
            title="Skill demand"
            note={
              <>
                Share of {cityRow?.detailed_sample_size ?? 0} detailed {CITY_LABEL[city]} ads mentioning each skill. Top 20.
              </>
            }
            actions={
              <label className="flex items-center gap-2">
                <span className="kicker text-ink-muted">Role</span>
                <select className="field h-8 px-2 font-mono text-[12px] outline-none" value={role} onChange={(e) => setRole(e.target.value)}>
                  <option value="">All roles</option>
                  {ROLE_FAMILIES.map((f) => (
                    <option key={f} value={f}>
                      {roleLabel(f)}
                    </option>
                  ))}
                </select>
              </label>
            }
          >
            <div className="mb-3 flex flex-wrap gap-x-5 gap-y-1 font-mono text-[11.5px]">
              <span className="inline-flex items-center gap-1.5">
                <span aria-hidden className="inline-block h-2.5 w-4 bg-ink" /> On your resume
              </span>
              <span className="inline-flex items-center gap-1.5">
                <span aria-hidden className="inline-block h-2.5 w-4 bg-ink-low" /> Not on your resume
              </span>
            </div>
            <div className={cn(skillsRole.isFetching && "opacity-60 transition-opacity")}>
              {chart.length ? (
                <SkillBars data={chart.slice(0, 20)} cityLabel={CITY_LABEL[city]} />
              ) : (
                <p className="text-sm text-ink-muted">No detailed ads for this filter yet.</p>
              )}
            </div>
          </Section>

          <Section id="ins-h2h" title="Head to head" note="Share of detailed ads in each city that mention the skill. Shared scale within each panel.">
            <div className="grid gap-x-10 gap-y-8 md:grid-cols-2">
              {HEAD_TO_HEAD.map((g, i) =>
                compares[i].data ? (
                  <HeadToHeadPanel key={g.title} title={g.title} data={compares[i].data} />
                ) : (
                  <p key={g.title} className="kicker border-t-2 border-ink pt-3 text-ink-muted">
                    {g.title} · loading…
                  </p>
                ),
              )}
            </div>
          </Section>

          <Section id="ins-gaps" title="Gaps" note={`Skills ${CITY_LABEL[city]} ads ask for that aren't on your resume.`}>
            {gaps.data?.length ? (
              <ol className="divide-y divide-rule border-b border-rule">
                {gaps.data.slice(0, 10).map((g, i) => (
                  <li key={g.skill} className="grid grid-cols-[2rem_minmax(0,1fr)] gap-x-3 py-3 sm:grid-cols-[2rem_15rem_minmax(0,1fr)]">
                    <span className="num pt-0.5 text-[12px] text-ink-muted">{String(i + 1).padStart(2, "0")}</span>
                    <div>
                      <p className="text-[15px] font-semibold">{g.skill}</p>
                      <div className="mt-1.5 flex items-center gap-2">
                        <span className="h-2 w-28 bg-rule" aria-hidden>
                          <span className="block h-full bg-ink" style={{ width: `${Math.min(100, (g.share / (gaps.data[0].share || 1)) * 100)}%` }} />
                        </span>
                        <span className="num text-[11.5px] whitespace-nowrap">
                          {pct(g.share)} <span className="text-ink-muted">· {g.count} ads</span>
                        </span>
                      </div>
                    </div>
                    <div className="col-start-2 mt-2 sm:col-start-auto sm:mt-0">
                      <p className="flex flex-wrap gap-1">
                        {g.role_families.slice(0, 4).map((f) => (
                          <span key={f} className="kicker bg-chip px-1.5 py-[3px] text-[10px] text-ink">
                            {roleLabel(f)}
                          </span>
                        ))}
                        {g.role_families.length > 4 && (
                          <span className="kicker px-1 py-[3px] text-[10px] text-ink-muted">+{g.role_families.length - 4}</span>
                        )}
                      </p>
                      {g.example_titles.length > 0 && (
                        <p className="mt-1.5 text-[13px] leading-snug text-ink-muted">{g.example_titles.slice(0, 3).join(" · ")}</p>
                      )}
                    </div>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="text-sm text-ink-muted">{gaps.isLoading ? "Loading…" : "No gaps found in the current sample."}</p>
            )}
          </Section>

          <Section id="ins-roles" title="Roles" note="Role families by title. Skill chips outlined in blue are on your resume.">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] border-collapse text-[13px]">
                <thead>
                  <tr className="border-b border-ink">
                    <th className="kicker px-3 py-2 text-left text-[10.5px] font-medium text-ink-muted">Role family</th>
                    <th className="kicker px-3 py-2 text-right text-[10.5px] font-medium text-ink-muted">Jobs</th>
                    <th className="kicker px-3 py-2 text-right text-[10.5px] font-medium text-ink-muted">Flexible</th>
                    <th className="kicker px-3 py-2 text-left text-[10.5px] font-medium text-ink-muted">Top skills</th>
                  </tr>
                </thead>
                <tbody>
                  {(roles.data ?? []).map((r) => (
                    <tr key={r.role_family} className="border-b border-rule align-top">
                      <th scope="row" className="px-3 py-2.5 text-left text-[14px] font-medium">
                        {roleLabel(r.role_family)}
                      </th>
                      <td className="num px-3 py-2.5 text-right">{r.count}</td>
                      <td className="num px-3 py-2.5 text-right">{pct(r.flexible_share)}</td>
                      <td className="px-3 py-2">
                        <span className="flex flex-wrap gap-1">
                          {r.top_skills.map((s) => (
                            <span
                              key={s}
                              className={cn(
                                "border px-1.5 py-[3px] font-mono text-[11px] leading-none",
                                have.has(s) ? "border-blue text-blue" : "border-rule text-ink-muted",
                              )}
                            >
                              {s}
                            </span>
                          ))}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>

          <Section id="ins-trends" title="Trends" note="Share of detailed ads per daily snapshot. Pick up to three skills.">
            <div className="mb-4 flex flex-wrap gap-1.5" role="group" aria-label="Trend skills">
              {all.slice(0, 14).map((s) => {
                const slot = activeSlots.indexOf(s.skill);
                return (
                  <button
                    key={s.skill}
                    type="button"
                    aria-pressed={slot >= 0}
                    onClick={() => toggleTrend(s.skill)}
                    className={cn(
                      "inline-flex h-7 items-center gap-1.5 border px-2 font-mono text-[11px]",
                      slot >= 0 ? "border-ink text-ink" : "border-rule text-ink-muted hover:border-ink hover:text-ink",
                    )}
                  >
                    {slot >= 0 && (
                      <svg width="10" height="10" aria-hidden>
                        {SERIES[slot].shape === "square" ? (
                          <rect x={1} y={1} width={8} height={8} fill={SERIES[slot].color} />
                        ) : SERIES[slot].shape === "diamond" ? (
                          <path d="M5 0L10 5L5 10L0 5Z" fill={SERIES[slot].color} />
                        ) : (
                          <circle cx={5} cy={5} r={4} fill={SERIES[slot].color} />
                        )}
                      </svg>
                    )}
                    {s.skill}
                  </button>
                );
              })}
            </div>
            {trends.data && trends.data.points.length >= 2 ? (
              <TrendChart data={trends.data} slots={activeSlots} />
            ) : (
              <p className="bg-chip px-4 py-3 text-[14px] text-ink">Trends appear after a few daily snapshots.</p>
            )}
          </Section>
        </>
      )}
    </div>
  );
}
