import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ChangesPanel } from "@/components/tailor/ChangesPanel";
import { api } from "@/lib/api";
import type { AtsScore, JobDetail, ResumeMatcherResult, TailoringDetail, TailoringSummary } from "@/lib/types";
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

const atsScore = (score: number, extra: Partial<AtsScore> = {}): AtsScore => ({
  score,
  breakdown: { keyword_match: score, skills_coverage: 50, title_alignment: 75, section_completeness: 100, date_consistency: null },
  missing_keywords: [],
  matched_keywords: [],
  ...extra,
});

const rmResult = (extra: Partial<ResumeMatcherResult> = {}): ResumeMatcherResult => ({
  status: "done",
  error: null,
  warnings: [],
  started_at: now,
  finished_at: now,
  ats_score: 66.5,
  sub_scores: {},
  matched_keywords: ["React"],
  missing_keywords: ["Go"],
  injectable_keywords: [],
  recommendations: ["Add these high-priority missing keywords: Go."],
  interview_prep: {
    role_fit_analysis: ["Strong React background"],
    resume_questions: [{ question: "How did you raise Jest coverage at Microsoft?", focus_area: "Testing", suggested_answer_points: ["Set a coverage gate in CI"] }],
    project_follow_ups: [{ question: "Why FastAPI for SeekHunter?", suggested_answer_points: ["Typed, async"] }],
    skill_gaps: [{ skill: "Go", why_it_matters: "Backend services", preparation_suggestion: "Build a small Go API" }],
    talking_points: [],
  },
  outreach_message: "Hi Sarah, I just applied for the Junior Developer role at Acme.",
  rm_master_id: "m1",
  rm_job_id: "j1",
  rm_resume_id: "t1",
  rm_url: "http://rm.test/resumes/t1",
  ...extra,
});

const ATS = { current: atsScore(61.6), tailored: atsScore(80.6, { missing_keywords: ["Kubernetes", "Terraform"] }), keywords_source: "resume_matcher" as const };

describe("TailorPage · ATS and Resume-Matcher", () => {
  beforeEach(() => {
    vi.spyOn(api, "job").mockResolvedValue({ id: 7, title: "Junior Developer", company: "Acme", work_type: "part_time", contact_name: null } as JobDetail);
    vi.spyOn(api, "tailorings").mockResolvedValue([summary({ status: "done" })]);
  });
  afterEach(() => vi.restoreAllMocks());

  it("shows the ATS score current → tailored with the 5-part breakdown and missing keywords", async () => {
    vi.spyOn(api, "tailoring").mockResolvedValue({ ...DONE, ats: ATS, resume_matcher: rmResult() });
    renderPage();
    expect((await screen.findByTestId("ats-score")).textContent).toBe("62→ to 81");
    const breakdown = screen.getByRole("list", { name: "ATS breakdown" });
    expect(breakdown.querySelectorAll("li").length).toBe(5);
    expect(breakdown.textContent).toContain("Keyword match · 40%");
    expect(breakdown.textContent).toContain("Date consistency · 10%");
    expect(screen.getByText(/via Resume-Matcher scoring/)).toBeTruthy();
    expect(screen.getByText("Terraform")).toBeTruthy();
    expect(screen.getByText(/Resume-Matcher's own AI rewrite scores 67/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open in Resume-Matcher" }).getAttribute("href")).toBe("http://rm.test/resumes/t1");
  });

  it("renders collapsible interview prep and the outreach message with copy and LinkedIn hint", async () => {
    vi.spyOn(api, "tailoring").mockResolvedValue({ ...DONE, ats: ATS, resume_matcher: rmResult() });
    renderPage();
    const q = await screen.findByRole("button", { name: /How did you raise Jest coverage/ });
    expect(q.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText("Set a coverage gate in CI")).toBeNull();
    fireEvent.click(q);
    expect(screen.getByText("Set a coverage gate in CI")).toBeTruthy();
    expect(screen.getByText("2 questions · via Resume-Matcher")).toBeTruthy();
    expect(screen.getByText("Build a small Go API", { exact: false })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Outreach message" }).textContent).toContain("I just applied for the Junior Developer role");
    expect(screen.getByRole("button", { name: "Copy outreach message" })).toBeTruthy();
    expect(screen.getByText("Paste into a LinkedIn invite to Sarah Lee.")).toBeTruthy();
  });

  it("shows progress while Resume-Matcher is running", async () => {
    vi.spyOn(api, "tailoring").mockResolvedValue({ ...DONE, ats: ATS, resume_matcher: rmResult({ status: "running", interview_prep: null, outreach_message: null }) });
    renderPage();
    expect((await screen.findByRole("status")).textContent).toContain("Analysing with Resume-Matcher");
    expect(screen.queryByRole("region", { name: "Outreach message" })).toBeNull();
  });

  it("shows the error and retries a failed Resume-Matcher run", async () => {
    vi.spyOn(api, "tailoring").mockResolvedValue({ ...DONE, ats: ATS, resume_matcher: rmResult({ status: "failed", error: "RMError: improve -> 500" }) });
    const rerun = vi.spyOn(api, "rerunResumeMatcher").mockResolvedValue({ status: "queued", started: true });
    renderPage();
    expect(await screen.findByText("RMError: improve -> 500")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(rerun).toHaveBeenCalledWith(5));
  });

  it("says Resume-Matcher needs ChatGPT sign-in when it has no LLM", async () => {
    vi.spyOn(api, "tailoring").mockResolvedValue({ ...DONE, ats: ATS, resume_matcher: null });
    vi.spyOn(api, "resumeMatcherStatus").mockResolvedValue({
      enabled: true, reachable: true, ready: false, llm_configured: false, llm_healthy: false, status: "setup_required",
      base_url: "http://rm.test", settings_url: "http://rm.test/settings", error: "no llm",
    });
    renderPage();
    await waitFor(() => expect(screen.getByTestId("rm-note").textContent).toContain("Resume-Matcher needs ChatGPT sign-in"));
    expect(screen.getByRole("link", { name: "Open its settings" }).getAttribute("href")).toBe("http://rm.test/settings");
    expect(screen.getByRole("button", { name: "Run Resume-Matcher" })).toBeTruthy();
  });

  it("explains how to enable Resume-Matcher when it is off", async () => {
    vi.spyOn(api, "tailoring").mockResolvedValue({ ...DONE, ats: ATS, resume_matcher: null });
    vi.spyOn(api, "resumeMatcherStatus").mockResolvedValue({
      enabled: false, reachable: false, ready: false, llm_configured: false, llm_healthy: false, status: null,
      base_url: null, settings_url: null, error: "not configured",
    });
    renderPage();
    await waitFor(() => expect(screen.getByTestId("rm-note").textContent).toContain("Set RM_BASE_URL"));
    expect(screen.queryByRole("button", { name: "Run Resume-Matcher" })).toBeNull();
  });
});

describe("ChangesPanel", () => {
  it("renders a reworded bullet as an inline word diff, removed bullets and collapsed kept ones", () => {
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
    // word-level: only the changed words are marked, the sentence isn't repeated
    expect(container.querySelector("del")?.textContent).toBe("APIs");
    expect(container.querySelector("ins")?.textContent).toBe("FastAPI services");
    expect(screen.getAllByText(/Wrote/).length).toBe(1);
    expect(screen.getByText("Removed")).toBeTruthy();
    expect(screen.getByText("1 unchanged")).toBeTruthy();
    expect(container.querySelectorAll("p.font-mono .bg-mark").length).toBe(2);
  });

  it("uses the API diff when present and labels moved bullets", () => {
    const { container } = render(
      <ChangesPanel
        counts={{ reworded: 1, removed: 0, moved: 1, skills_reordered: 5, projects_changed: 1, summary_changed: true }}
        changes={[
          {
            type: "summary",
            before: "Builds web apps.",
            after: "Builds React web apps.",
            changed: true,
            diff: [
              { op: "equal", text: "Builds " },
              { op: "insert", text: "React " },
              { op: "equal", text: "web apps." },
            ],
          },
          {
            type: "bullet", experience: "a", company: "Acme", id: "a-b1", status: "reworded", before: "Led team", after: "Led small team",
            diff: [
              { op: "equal", text: "Led " },
              { op: "delete", text: "the" },
              { op: "insert", text: "a small" },
              { op: "equal", text: " team" },
            ],
          },
          { type: "bullet", experience: "a", company: "Acme", id: "a-b3", status: "moved", before: "Shipped features", after: "Shipped features", position_before: 2, position_after: 0 },
        ]}
      />,
    );
    const ins = Array.from(container.querySelectorAll("ins")).map((n) => n.textContent);
    expect(ins).toEqual(["React", "a small"]);
    expect(container.querySelector("del")?.textContent).toBe("the");
    expect(screen.getByText("Moved up 3 → 1")).toBeTruthy();
    // server word runs come without the spaces between them; they're restored on render
    expect(container.querySelectorAll("p.leading-relaxed")[1]?.textContent).toBe("Led the a small team");
    expect(screen.getByText("Shipped features")).toBeTruthy();
    expect(screen.getByTestId("change-summary").textContent).toBe(
      "Summary rewritten · 1 reworded · 1 moved · skills reordered in 5 lines · projects changed",
    );
  });

  it("falls back to a client-side word diff and counts when the API sends neither", () => {
    const { container } = render(
      <ChangesPanel
        changes={[
          { type: "summary", before: "Engineer with 6 years of experience.", after: "Engineer with 6 years of React experience.", changed: true },
          { type: "bullet", experience: "a", company: "Acme", id: "a-b2", status: "removed", before: "Made coffee", after: null },
        ]}
      />,
    );
    expect(container.querySelector("ins")?.textContent).toBe("React");
    expect(container.querySelector("del")).toBeNull();
    expect(screen.getByTestId("change-summary").textContent).toBe("Summary rewritten · 1 removed");
  });
});
