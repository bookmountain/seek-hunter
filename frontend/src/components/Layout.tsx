import { NavLink, Outlet, useLocation } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import { cn } from "@/lib/utils";
import { TokenDialog } from "./TokenDialog";

const links = [
  { to: "/", label: "Jobs" },
  { to: "/excluded", label: "Excluded" },
  { to: "/searches", label: "Searches" },
  { to: "/settings", label: "Settings" },
  { to: "/runs", label: "Runs" },
];

const dateline = new Intl.DateTimeFormat("en-AU", {
  weekday: "short",
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "Australia/Adelaide",
}).format(new Date());

export function Wordmark() {
  return (
    <span className="inline-flex items-center gap-2.5 text-ink select-none">
      <span aria-hidden className="size-[12px] bg-blue" />
      <span className="display text-[21px] leading-none font-[900] tracking-[-0.04em] uppercase [font-stretch:80%]">
        SeekHunter
      </span>
    </span>
  );
}

export function Layout() {
  const { pathname } = useLocation();
  return (
    <div className="flex min-h-dvh flex-col lg:h-dvh">
      <a
        href="#main"
        className="kicker sr-only z-50 bg-ink px-3 py-2 text-white focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
      >
        Skip to content
      </a>
      <header className="paper z-30 border-b-2 border-ink">
        <div className="flex flex-wrap items-center gap-x-8 gap-y-2 px-5 pt-3 pb-2 lg:h-14 lg:flex-nowrap lg:px-6 lg:py-0">
          <NavLink to="/" aria-label="SeekHunter, jobs" className="shrink-0">
            <Wordmark />
          </NavLink>
          <div className="ml-auto flex items-center gap-5 lg:order-last">
            <span className="kicker hidden text-ink-muted xl:inline">Adelaide · {dateline}</span>
            <TokenDialog />
          </div>
          <nav
            aria-label="Main"
            className="-mx-1 flex w-full gap-5 overflow-x-auto px-1 pb-1 lg:w-auto lg:overflow-visible lg:pb-0"
          >
            {links.map((l) => (
              <NavLink
                key={l.to}
                to={l.to}
                end={l.to === "/"}
                className={({ isActive: active }) => {
                  const isActive = active || (l.to === "/" && pathname.startsWith("/jobs/"));
                  return (
                  cn(
                    "kicker shrink-0 py-1 underline-offset-[7px] transition-colors",
                    isActive
                      ? "text-ink underline decoration-blue decoration-2"
                      : "text-ink-muted hover:text-ink hover:underline hover:decoration-rule-strong hover:decoration-1",
                  )
                  );
                }}
              >
                {l.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>
      <main id="main" className="flex-1 lg:min-h-0 lg:overflow-y-auto">
        <Outlet />
      </main>
      <Toaster />
    </div>
  );
}
