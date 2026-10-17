import { NavLink, Outlet } from "react-router-dom";
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

export function Layout() {
  return (
    <div className="min-h-screen bg-background">
      <header className="border-b">
        <div className="mx-auto flex max-w-7xl items-center gap-6 px-4 py-3">
          <span className="font-semibold">🎯 SeekHunter</span>
          <nav className="flex gap-1">
            {links.map((l) => (
              <NavLink
                key={l.to}
                to={l.to}
                end={l.to === "/"}
                className={({ isActive }) =>
                  cn("rounded-md px-3 py-1.5 text-sm", isActive ? "bg-muted font-medium" : "text-muted-foreground")
                }
              >
                {l.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto">
            <TokenDialog />
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6">
        <Outlet />
      </main>
      <Toaster />
    </div>
  );
}
