import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
  beforeEach(() => vi.spyOn(window, "scrollTo").mockImplementation(() => {}));
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
});
