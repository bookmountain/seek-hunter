import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import type { TailoringListItem } from "@/lib/types";
import { ResumesPage } from "./ResumesPage";

const now = new Date().toISOString();
const row = (extra: Partial<TailoringListItem>): TailoringListItem => ({
  id: 4,
  job_id: 12,
  status: "done",
  progress: "Done",
  created_at: now,
  started_at: now,
  finished_at: now,
  provider: "openclaw",
  error: null,
  send_requested: false,
  sent_at: null,
  resume_hash: "abc",
  pages: { resume: 2, cover_letter: 1 },
  warnings_count: 0,
  job_title: "Full Stack Developer",
  company: "Robert Walters",
  city: "adelaide",
  resume_pdf: "/api/tailorings/4/resume.pdf",
  cover_letter_pdf: "/api/tailorings/4/cover_letter.pdf",
  thumbnail: "/api/tailorings/4/pages/resume/1.png",
  applied_application_id: 7,
  ...extra,
});

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ResumesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ResumesPage", () => {
  beforeEach(() => {
    vi.spyOn(api, "resumeCurrent").mockResolvedValue({
      hash: "abc", ready: true, pages: 2, pdf_url: "/api/resume/current.pdf?hash=abc", page_urls: ["/api/resume/current/pages/1.png?hash=abc"], error: null,
    });
  });
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("renders the current resume and tailored rows with view, PDF and applied links", async () => {
    vi.spyOn(api, "allTailorings").mockResolvedValue([row({}), row({ id: 5, job_id: 13, status: "failed", error: "tectonic exited 1", resume_pdf: null, cover_letter_pdf: null, thumbnail: null, applied_application_id: null, job_title: "QA Tester" })]);
    renderPage();
    expect(await screen.findByRole("img", { name: "Page 1 of your current resume" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Download PDF" }).getAttribute("href")).toBe("/api/resume/current.pdf?hash=abc");
    const view = await screen.findByRole("link", { name: "View tailored resume for Full Stack Developer" });
    expect(view.getAttribute("href")).toBe("/jobs/12/tailor?run=4");
    const card = view.closest("li")!;
    expect(within(card).getByRole("link", { name: "Resume PDF" }).getAttribute("href")).toBe("/api/tailorings/4/resume.pdf");
    expect(within(card).getByRole("link", { name: "Cover letter PDF" }).getAttribute("href")).toBe("/api/tailorings/4/cover_letter.pdf");
    expect(within(card).getByRole("link", { name: "Applied with this" }).getAttribute("href")).toBe("/history?tab=applications");
    expect(screen.getByText("tectonic exited 1")).toBeTruthy();
  });

  it("shows the empty state", async () => {
    vi.spyOn(api, "allTailorings").mockResolvedValue([]);
    renderPage();
    expect(await screen.findByText("No tailored resumes yet. Open a job and press Tailor resume.")).toBeTruthy();
  });

  it("polls every 3 s while a row is running", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const list = vi.spyOn(api, "allTailorings").mockResolvedValue([row({ status: "running", progress: "Tailoring with AI", thumbnail: null, resume_pdf: null, cover_letter_pdf: null })]);
    renderPage();
    expect(await screen.findByText("Tailoring with AI…")).toBeTruthy();
    const before = list.mock.calls.length;
    await vi.advanceTimersByTimeAsync(3100);
    await waitFor(() => expect(list.mock.calls.length).toBeGreaterThan(before));
  });
});
