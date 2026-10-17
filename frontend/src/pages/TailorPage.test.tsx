import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ChangesPanel } from "@/components/tailor/ChangesPanel";
import { api } from "@/lib/api";
import type { JobDetail, TailoringDetail, TailoringSummary } from "@/lib/types";
import { TailorPage } from "./TailorPage";

const now = new Date().toISOString();

const summary = (extra: Partial<TailoringSummary> = {}): TailoringSummary => ({
  id: 5,
  job_id: 7,
  status: "running",
  progress: "Tailoring with AI",
  created_at: now,
  started_at: now,
  finished_at: null,
  provider: null,
  error: null,
  send_requested: false,
  sent_at: null,
  resume_hash: "abc",
  pages: {},
  warnings_count: 0,
  ...extra,
});

const detail = (extra: Partial<TailoringDetail> = {}): TailoringDetail => ({
  ...summary(),
  job: { id: 7, title: "Junior Developer", company: "Acme", location: "Adelaide SA", work_type: "part_time", contact_name: "Sarah Lee" },
  warnings: [],
  keywords_matched: [],
  gaps: [],
  cover_letter: null,
  changes: [],
  files: null,
  current: null,
  ...extra,
});

const DONE = detail({
  status: "done",
  progress: "Done",
  finished_at: now,
  pages: { resume: 2, cover_letter: 1 },
  keywords_matched: ["React"],
  gaps: ["Kubernetes"],
  warnings: ["Bullet exp-b2 introduced a new number; kept original"],
  cover_letter: {
    greeting: "Dear Sarah,",
    paragraphs: ["I build **React** apps.", "See [my site](https://example.com)."],
    sign_off: "Kind regards,",
    text: "Dear Sarah, ...",
    word_count: 240,
  },
  changes: [
    { type: "summary", before: "Old summary", after: "New summary", changed: true },
    { type: "bullet", experience: "acme", company: "Acme", id: "acme-b1", status: "reworded", before: "Built things", after: "Built React things" },
  ],
  files: {
    resume_pdf: "/api/tailorings/5/resume.pdf",
    cover_letter_pdf: "/api/tailorings/5/cover_letter.pdf",
    resume_pages: ["/api/tailorings/5/pages/resume/1.png", "/api/tailorings/5/pages/resume/2.png"],
    cover_letter_pages: ["/api/tailorings/5/pages/cover_letter/1.png"],
  },
  current: {
    hash: "abc",
    ready: true,
    pages: 2,
    pdf_url: "/api/resume/current.pdf?hash=abc",
    page_urls: ["/api/resume/current/pages/1.png?hash=abc", "/api/resume/current/pages/2.png?hash=abc"],
    error: null,
  },
});

function renderPage(url = "/jobs/7/tailor") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path="/jobs/:id/tailor" element={<TailorPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("TailorPage", () => {
  beforeEach(() => {
    vi.spyOn(api, "job").mockResolvedValue({ id: 7, title: "Junior Developer", company: "Acme", work_type: "part_time", contact_name: null } as JobDetail);
  });
  afterEach(() => vi.restoreAllMocks());

  it("shows the progress label while running", async () => {
    vi.spyOn(api, "tailorings").mockResolvedValue([summary()]);
    vi.spyOn(api, "tailoring").mockResolvedValue(detail());
    renderPage();
    expect((await screen.findByRole("status")).textContent).toContain("Tailoring with AI");
    expect(screen.queryByRole("region", { name: "Changes" })).toBeNull();
  });

  it("renders current and tailored columns, changes, chips and cover letter when done", async () => {
    vi.spyOn(api, "tailorings").mockResolvedValue([summary({ status: "done" })]);
    vi.spyOn(api, "tailoring").mockResolvedValue(DONE);
    renderPage();
    expect(await screen.findByRole("img", { name: "Current resume page 1" })).toBeTruthy();
    expect(screen.getByRole("img", { name: "Tailored resume page 2" }).getAttribute("src")).toBe(
      "/api/tailorings/5/pages/resume/2.png",
    );
    expect(screen.getByRole("region", { name: "Current resume" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Tailored resume" })).toBeTruthy();
    expect(screen.getByText("Kubernetes")).toBeTruthy();
    expect(screen.getByText(/introduced a new number/)).toBeTruthy();
    expect(screen.getByText("240 words")).toBeTruthy();
    expect(screen.getByRole("link", { name: "my site" }).getAttribute("href")).toBe("https://example.com");
    expect(screen.getByRole("link", { name: "Download resume PDF" }).getAttribute("href")).toBe("/api/tailorings/5/resume.pdf");
  });

  it("Regenerate POSTs a new tailoring", async () => {
    vi.spyOn(api, "tailorings").mockResolvedValue([summary({ status: "done" })]);
    vi.spyOn(api, "tailoring").mockResolvedValue(DONE);
    const tailor = vi.spyOn(api, "tailor").mockResolvedValue({ tailoring_id: 6, status: "queued", reused: false });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Regenerate" }));
    await waitFor(() => expect(tailor).toHaveBeenCalledWith(7));
  });

  it("shows the error and a Try again button when failed", async () => {
    vi.spyOn(api, "tailorings").mockResolvedValue([summary({ status: "failed" })]);
    vi.spyOn(api, "tailoring").mockResolvedValue(detail({ status: "failed", progress: "Failed", error: "tectonic exited 1" }));
    renderPage();
    expect(await screen.findByText("tectonic exited 1")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
  });
});

describe("ChangesPanel", () => {
  it("renders a reworded bullet with old (struck) and new text, removed bullets and collapsed kept ones", () => {
    const { container } = render(
      <ChangesPanel
        changes={[
          { type: "bullet", experience: "a", company: "Acme", id: "a-b1", status: "reworded", before: "Wrote APIs", after: "Wrote FastAPI services" },
          { type: "bullet", experience: "a", company: "Acme", id: "a-b2", status: "removed", before: "Made coffee", after: null },
          { type: "bullet", experience: "a", company: "Acme", id: "a-b3", status: "kept", before: "Fixed bugs", after: "Fixed bugs" },
          { type: "skills", id: "s1", category: "Languages", before: ["Go", "Python"], after: ["Python", "Go"], changed: true },
        ]}
      />,
    );
    expect(container.querySelector("del")?.textContent).toBe("Wrote APIs");
    expect(container.querySelector("ins")?.textContent).toBe("Wrote FastAPI services");
    expect(screen.getByText("Removed")).toBeTruthy();
    expect(screen.getByText("1 unchanged")).toBeTruthy();
    expect(container.querySelectorAll(".bg-mark").length).toBe(2);
  });
});
