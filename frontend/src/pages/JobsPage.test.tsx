import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import type { Job, JobDetail } from "@/lib/types";
import { JobsPage } from "./JobsPage";

const job = (id: number, title: string, extra: Partial<Job> = {}): Job => ({
  id,
  source: "seek",
  title,
  company: `Company ${id}`,
  location: "Adelaide SA",
  city: "adelaide",
  work_type: "contract",
  salary_label: null,
  listed_at: null,
  first_seen_at: new Date().toISOString(),
  url: `https://example.com/${id}`,
  status: "new",
  notes: "",
  force_include: false,
  excluded: false,
  reasons: [],
  snippets: {},
  rule_score: 60,
  llm_score: 80,
  llm_note: "Strong React match",
  final_score: 78,
  matched_skills: ["React", "TypeScript"],
  flags: [],
  contact_name: null,
  contact_phone: null,
  contact_email: null,
  contact_linkedin: null,
  contact_search: { linkedin: "https://www.linkedin.com/search/results/people/?keywords=x" },
  application: null,
  prior_applications: [],
  applicant_count: null,
  applicant_volume: null,
  resume_pct: null,
  cover_letter_pct: null,
  insights_checked_at: null,
  ...extra,
});

const JOBS = [job(1, "Frontend Developer"), job(2, "Graduate Software Engineer", { final_score: 50 })];

function Location() {
  const loc = useLocation();
  return <output data-testid="loc">{loc.pathname + loc.search}</output>;
}

function renderPage(initial = "/") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initial]}>
        <JobsPage view="active" />
        <Location />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("JobsPage split view", () => {
  beforeEach(() => {
    vi.spyOn(window, "scrollTo").mockImplementation(() => {});
    vi.spyOn(api, "tailorings").mockResolvedValue([]);
    vi.spyOn(api, "jobCities").mockResolvedValue([
      { city: "adelaide", count: 92 },
      { city: "melbourne", count: 41 },
    ]);
  });
  afterEach(() => vi.restoreAllMocks());

  it("opens the detail inline (no overlay) and reflects the job in the URL", async () => {
    vi.spyOn(api, "jobs").mockResolvedValue(JOBS);
    vi.spyOn(api, "job").mockImplementation(async (id) => ({
      ...JOBS.find((j) => j.id === id)!,
      description_html: "<h2>About</h2><p>We use React daily.</p>",
      teaser: "",
    }) as JobDetail);

    const { container } = renderPage();
    const row = await screen.findByRole("button", { name: /Frontend Developer/ });
    fireEvent.click(row);

    expect(await screen.findByRole("heading", { level: 1, name: "Frontend Developer" })).toBeTruthy();
    expect(screen.getByTestId("loc").textContent).toBe("/?job=1");
    expect(row.getAttribute("aria-current")).toBe("true");
    // No modal overlay / backdrop: the list stays in the document, un-obscured.
    expect(container.ownerDocument.querySelector('[role="dialog"]')).toBeNull();
    expect(container.ownerDocument.querySelector('[class*="backdrop"]')).toBeNull();
    await waitFor(() => expect(container.querySelector(".article mark")?.textContent).toBe("React"));
  });

  it("restores the selection from the URL and clears it with Escape", async () => {
    vi.spyOn(api, "jobs").mockResolvedValue(JOBS);
    vi.spyOn(api, "job").mockResolvedValue({ ...JOBS[1], description_html: "", teaser: "Teaser" } as JobDetail);

    renderPage("/?job=2");
    expect(await screen.findByRole("heading", { level: 1, name: "Graduate Software Engineer" })).toBeTruthy();

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.getByTestId("loc").textContent).toBe("/"));
  });

  it("sends city= from the URL filter and tags non-Adelaide rows", async () => {
    const jobs = vi.spyOn(api, "jobs").mockResolvedValue([job(7, "Melbourne Dev", { city: "melbourne" })]);
    renderPage("/?city=melbourne");
    expect(await screen.findByRole("button", { name: /Melbourne Dev/ })).toBeTruthy();
    expect(jobs).toHaveBeenCalledWith(expect.objectContaining({ city: "melbourne" }));
    expect(within(screen.getByRole("button", { name: /Melbourne Dev/ })).getByText("Melbourne")).toBeTruthy();
    expect(screen.getByRole("combobox", { name: "Location" }).textContent).toContain("Melbourne 41");
  });

  it("omits city when All locations", async () => {
    const jobs = vi.spyOn(api, "jobs").mockResolvedValue(JOBS);
    renderPage();
    await screen.findByRole("button", { name: /Frontend Developer/ });
    expect(jobs.mock.calls[0][0].city).toBeUndefined();
  });

  it("shows source and listed columns, highlights ads listed within 24h, and sorts by listed", async () => {
    const hoursAgo = (h: number) => new Date(Date.now() - h * 3_600_000).toISOString();
    vi.spyOn(api, "jobs").mockResolvedValue([
      job(1, "Older High Score", { final_score: 90, source: "jora", listed_at: hoursAgo(80) }),
      job(2, "Fresh Lower Score", { final_score: 60, source: "linkedin", listed_at: hoursAgo(3) }),
      job(3, "No Listing Date", { final_score: 70, listed_at: null }),
    ]);
    vi.spyOn(api, "uiPrefs").mockResolvedValue({});
    const put = vi.spyOn(api, "putUiPrefs").mockResolvedValue({});
    const { container } = renderPage();
    await screen.findByRole("button", { name: /Older High Score/ });
    const order = () => Array.from(container.querySelectorAll("[data-row]")).map((r) => r.getAttribute("data-job-id"));
    expect(order()).toEqual(["1", "3", "2"]); // default: score

    const sources = Array.from(container.querySelectorAll('[data-col="source"]')).map((n) => n.textContent);
    expect(sources).toEqual(["Jora", "SEEK", "LinkedIn"]);
    const listed = container.querySelectorAll('[data-col="listed"]');
    expect(listed[2].firstElementChild?.className).toContain("text-blue"); // 3h ago
    expect(listed[0].firstElementChild?.className).not.toContain("text-blue"); // 80h ago
    expect(listed[1].textContent).toBe("—");

    fireEvent.click(within(screen.getByRole("group", { name: "Sort jobs" })).getByRole("button", { name: "Sort by listed" }));
    await waitFor(() => expect(order()).toEqual(["2", "1", "3"]));
    expect(screen.getByTestId("loc").textContent).toContain("sort=listed");
    await waitFor(() => expect(put).toHaveBeenCalledWith("jobs", expect.objectContaining({ sort: "listed" })), { timeout: 2000 });
  });

  it("applies a remembered sort", async () => {
    vi.spyOn(api, "jobs").mockResolvedValue([
      job(1, "Seen Long Ago", { final_score: 90, first_seen_at: new Date(Date.now() - 5 * 86_400_000).toISOString() }),
      job(2, "Seen Just Now", { final_score: 50 }),
    ]);
    vi.spyOn(api, "uiPrefs").mockResolvedValue({ jobs: { sort: "seen" } });
    const { container } = renderPage();
    await screen.findByRole("button", { name: /Seen Just Now/ });
    await waitFor(() =>
      expect(Array.from(container.querySelectorAll("[data-row]")).map((r) => r.getAttribute("data-job-id"))).toEqual(["2", "1"]),
    );
    expect(within(screen.getByRole("group", { name: "Sort jobs" })).getByRole("button", { name: "Sort by seen" }).getAttribute("aria-pressed")).toBe("true");
  });
});
