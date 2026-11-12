import { SectionHead } from "@/components/PageHead";
import type { AppSettings } from "@/lib/types";

type LimitKey =
  | "max_pages_per_search"
  | "other_city_max_pages"
  | "linkedin_max_pages"
  | "details_retry_per_run"
  | "closed_checks_per_run"
  | "max_insights_per_run"
  | "linkedin_insights_per_run"
  | "max_notify_per_run"
  | "market_details_per_city"
  | "radar_seed_days"
  | "radar_seed_max_probe";

interface Limit {
  key: LimitKey;
  label: string;
  help: string;
  fallback: number;
  unit?: string;
}

/** Groups of limits, each with a one-line plain explanation. `fallback` is the server default,
 *  used when an older server doesn't send the field. */
const LIMIT_GROUPS: { title: string; items: Limit[] }[] = [
  {
    title: "Search pages",
    items: [
      { key: "max_pages_per_search", label: "Pages per search", help: "Result pages read for each saved search on SEEK, Jora and Indeed.", fallback: 3 },
      { key: "other_city_max_pages", label: "Pages, other cities", help: "Cap for searches outside your Telegram cities.", fallback: 2 },
      { key: "linkedin_max_pages", label: "LinkedIn pages", help: "LinkedIn rate-limits sooner, so it gets its own lower cap.", fallback: 2 },
    ],
  },
  {
    title: "Per run",
    items: [
      { key: "max_notify_per_run", label: "Max notified", help: "Most jobs sent to Telegram in one run, best scores first.", fallback: 20 },
      { key: "max_insights_per_run", label: "SEEK applicant checks", help: "SEEK ads whose applicant numbers are re-read each run.", fallback: 250 },
      { key: "linkedin_insights_per_run", label: "LinkedIn applicant checks", help: "LinkedIn ads whose applicant count is re-read each run.", fallback: 100 },
      { key: "details_retry_per_run", label: "Detail retries", help: "Ads whose description failed to load, tried again each run.", fallback: 15 },
      { key: "closed_checks_per_run", label: "Closed-ad checks", help: "Older ads re-opened to see if the board has taken them down.", fallback: 30 },
      { key: "market_details_per_city", label: "Market ads per city", help: "Ads read per city for the Insights market crawl.", fallback: 40 },
    ],
  },
  {
    title: "Radar",
    items: [
      { key: "radar_seed_days", label: "Seed look-back", help: "Seeding looks at employers whose jobs were seen this many days back.", fallback: 60, unit: "days" },
      { key: "radar_seed_max_probe", label: "Seed probes", help: "Most new employers checked for a careers feed per seed run.", fallback: 80 },
    ],
  },
];

export function CrawlLimits({ s, onChange }: { s: AppSettings; onChange: (patch: Partial<AppSettings>) => void }) {
  return (
    <section className="mt-12" aria-labelledby="limits-head">
      <SectionHead>
        <span id="limits-head">Crawl limits</span>
      </SectionHead>
      <p className="mt-3 max-w-3xl text-[14.5px] leading-relaxed text-ink-muted">
        How much each run reads. Lower numbers are gentler on the job boards; higher ones catch more.
      </p>
      <div className="mt-4 grid gap-x-10 lg:grid-cols-[9rem_minmax(0,1fr)]">
        {LIMIT_GROUPS.map((g) => (
          <div key={g.title} className="contents">
            <h3 className="kicker pt-5 text-ink-muted lg:border-t lg:border-ink lg:pt-4">{g.title}</h3>
            <ul className="border-t border-ink lg:mt-0">
              {g.items.map((item) => {
                const value = (s[item.key] as number | undefined) ?? item.fallback;
                return (
                  <li key={item.key} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-6 border-b border-rule py-2.5">
                    <div className="min-w-0">
                      <label htmlFor={`lim-${item.key}`} className="text-[14.5px] font-medium">
                        {item.label}
                      </label>
                      <p className="text-[13px] text-ink-muted">{item.help}</p>
                    </div>
                    <span className="inline-flex items-baseline gap-1.5">
                      <input
                        id={`lim-${item.key}`}
                        type="number"
                        min={0}
                        step={1}
                        value={value}
                        onChange={(e) => onChange({ [item.key]: Math.max(0, Math.trunc(Number(e.target.value) || 0)) })}
                        className="field num h-8 w-20 px-2 text-right text-[14px] outline-none"
                      />
                      <span className="num w-9 text-[12px] text-ink-muted">{item.unit ?? ""}</span>
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}
