import { useSearchParams } from "react-router-dom";
import { ResetFilters } from "@/components/ResetFilters";
import { usePersistedFilters } from "@/hooks/usePersistedFilters";
import type { ApplicationStage } from "@/lib/types";
import { ApplicationsTab } from "@/components/history/ApplicationsTab";
import { CompaniesTab } from "@/components/history/CompaniesTab";
import { ContactsTab } from "@/components/history/ContactsTab";
import { TimelineTab } from "@/components/history/TimelineTab";
import { cn } from "@/lib/utils";

const TABS = [
  { id: "applications", label: "Applications" },
  { id: "contacts", label: "Contacts" },
  { id: "companies", label: "Companies" },
  { id: "timeline", label: "Timeline" },
] as const;
type Tab = (typeof TABS)[number]["id"];

/** Remembered across devices; `contact` (a deep link) is not. */
const FILTER_DEFAULTS = { tab: "applications", stage: "", q: "" };

export function HistoryPage() {
  const [params, setParams] = useSearchParams();
  const filters = usePersistedFilters("history", FILTER_DEFAULTS);
  const raw = filters.values.tab;
  const tab: Tab = TABS.some((t) => t.id === raw) ? (raw as Tab) : "applications";
  const contactId = Number(params.get("contact")) || null;
  const setFilter = filters.set;
  const select = (id: Tab) => {
    setFilter({ tab: id });
    if (contactId) setParams((prev) => { const next = new URLSearchParams(prev); next.delete("contact"); return next; }, { replace: true });
  };

  return (
    <div className="mx-auto w-full max-w-7xl px-5 py-8 lg:px-8 lg:py-10">
      <header className="border-b-2 border-ink">
        <p className="kicker text-ink-muted">Your search so far</p>
        <h1 className="display mt-2 text-[44px] leading-none">History</h1>
        <div className="mt-6 flex flex-wrap items-center justify-between gap-x-6 gap-y-2 pb-3">
        <div role="tablist" aria-label="History views" className="flex flex-wrap gap-x-7 gap-y-2">
          {TABS.map((t) => (
            <button
              key={t.id}
              id={`tab-${t.id}`}
              type="button"
              role="tab"
              aria-selected={tab === t.id}
              aria-controls={`panel-${t.id}`}
              onClick={() => select(t.id)}
              className={cn(
                "kicker py-1 text-[12px] underline-offset-[7px]",
                tab === t.id ? "text-ink underline decoration-blue decoration-2" : "text-ink-muted hover:text-ink",
              )}
            >
              {t.label}
            </button>
          ))}
        </div>
          <ResetFilters onReset={filters.reset} disabled={filters.isDefault} />
        </div>
      </header>
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} className="mt-6">
        {tab === "applications" && (
          <ApplicationsTab stage={filters.values.stage as ApplicationStage | ""} setStage={(s) => setFilter({ stage: s })} />
        )}
        {tab === "contacts" && (
          <ContactsTab key={contactId ?? "none"} initialOpen={contactId} q={filters.values.q} setQ={(q) => setFilter({ q })} />
        )}
        {tab === "companies" && <CompaniesTab q={filters.values.q} setQ={(q) => setFilter({ q })} />}
        {tab === "timeline" && <TimelineTab />}
      </div>
    </div>
  );
}
