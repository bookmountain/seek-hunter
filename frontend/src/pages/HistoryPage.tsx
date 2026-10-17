import { useSearchParams } from "react-router-dom";
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

export function HistoryPage() {
  const [params, setParams] = useSearchParams();
  const raw = params.get("tab");
  const tab: Tab = TABS.some((t) => t.id === raw) ? (raw as Tab) : "applications";
  const contactId = Number(params.get("contact")) || null;
  const select = (id: Tab) => setParams({ tab: id }, { replace: true });

  return (
    <div className="mx-auto w-full max-w-7xl px-5 py-8 lg:px-8 lg:py-10">
      <header className="border-b-2 border-ink">
        <p className="kicker text-ink-muted">Your search so far</p>
        <h1 className="display mt-2 text-[44px] leading-none">History</h1>
        <div role="tablist" aria-label="History views" className="mt-6 flex flex-wrap gap-x-7 gap-y-2 pb-3">
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
      </header>
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} className="mt-6">
        {tab === "applications" && <ApplicationsTab />}
        {tab === "contacts" && <ContactsTab key={contactId ?? "none"} initialOpen={contactId} />}
        {tab === "companies" && <CompaniesTab />}
        {tab === "timeline" && <TimelineTab />}
      </div>
    </div>
  );
}
