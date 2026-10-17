import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import type { City, CityOverview } from "@/lib/types";
import { InsightsPage } from "./InsightsPage";

const row = (city: City, total: number, flexible_share: number): CityOverview => ({
  city,
  total,
  flexible: Math.round(total * flexible_share),
  flexible_share,
  work_type_mix: {},
  role_family_mix: {},
  salary_p25: total ? 45 : null,
  salary_p50: total ? 55 : null,
  salary_p75: total ? 68 : null,
  salary_sample_size: total ? 20 : 0,
  detailed_sample_size: Math.round(total * 0.6),
});

const OVERVIEW = [row("adelaide", 120, 0.31), row("melbourne", 400, 0.22), row("sydney", 520, 0.2), row("perth", 90, 0.18)];

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/insights"]}>
        <InsightsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("InsightsPage", () => {
  beforeEach(() => {
    vi.spyOn(api, "insightsOverview").mockResolvedValue(OVERVIEW);
    vi.spyOn(api, "insightsSkills").mockResolvedValue([
      { skill: "React", count: 40, share: 0.55, you_have: true },
      { skill: "Kubernetes", count: 20, share: 0.27, you_have: false },
      { skill: "TypeScript", count: 18, share: 0.25, you_have: true },
    ]);
    vi.spyOn(api, "insightsGaps").mockResolvedValue([
      { skill: "Kubernetes", count: 20, share: 0.27, example_titles: ["Platform Engineer", "DevOps Engineer"], role_families: ["devops_cloud"] },
    ]);
    vi.spyOn(api, "insightsRoles").mockResolvedValue([
      { role_family: "fullstack", count: 50, flexible_share: 0.3, top_skills: ["React", "Kubernetes"] },
    ]);
    vi.spyOn(api, "insightsCompare").mockImplementation(async (skills) => ({
      skills,
      cities: (["adelaide", "melbourne", "sydney", "perth"] as City[]).map((city) => ({
        city,
        shares: Object.fromEntries(skills.map((s, i) => [s, 0.1 * (i + 1)])),
        detailed_sample_size: 50,
      })),
    }));
    vi.spyOn(api, "insightsTrends").mockResolvedValue({
      city: "adelaide",
      skills: ["React"],
      points: [{ date: "2026-10-16T00:00:00", shares: { React: 0.5 } }],
    });
  });
  afterEach(() => vi.restoreAllMocks());

  it("renders the overview for all four cities and highlights the best flexible share", async () => {
    renderPage();
    const table = await screen.findByRole("table", { name: /Overview by city/ });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((r) => within(r).getByRole("rowheader").textContent)).toEqual(["Adelaide", "Melbourne", "Sydney", "Perth"]);
    expect(within(rows[0]).getByText(/31%/).className).toContain("text-blue");
  });

  it("marks skills you have in the demand chart", async () => {
    renderPage();
    expect(await screen.findByRole("img", { name: /React: 55% of ads, 40 ads, you have it/ })).toBeTruthy();
    const k8s = screen.getByRole("img", { name: /Kubernetes: 27% of ads/ });
    expect(k8s.getAttribute("aria-label")).not.toContain("you have it");
    // ink bar for owned skills, grey for the rest
    const fills = Array.from(document.querySelectorAll('svg[role="group"] rect')).map((r) => r.getAttribute("fill"));
    expect(fills).toContain("var(--ink)");
    expect(fills).toContain("var(--ink-low)");
  });

  it("renders gaps with role families and example titles", async () => {
    renderPage();
    const gaps = await screen.findByRole("region", { name: "Gaps" });
    expect(await within(gaps).findByText("Kubernetes")).toBeTruthy();
    expect(within(gaps).getByText("DevOps / cloud")).toBeTruthy();
    expect(within(gaps).getByText("Platform Engineer · DevOps Engineer")).toBeTruthy();
  });

  it("shows the trends note with fewer than two snapshot points", async () => {
    renderPage();
    expect(await screen.findByText("Trends appear after a few daily snapshots.")).toBeTruthy();
  });

  it("shows the empty state when every city has zero jobs", async () => {
    vi.mocked(api.insightsOverview).mockResolvedValue(OVERVIEW.map((r) => ({ ...r, total: 0 })));
    renderPage();
    expect(await screen.findByText(/Market data is collected nightly at 02:30/)).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Skill demand" })).toBeNull();
  });
});
