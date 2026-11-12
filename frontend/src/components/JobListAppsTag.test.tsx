import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { JobList } from "./JobList";
import type { Job } from "@/lib/types";

const base = (over: Partial<Job>): Job =>
  ({
    id: 1, source: "seek", title: "Dev", company: "Acme", location: "Adelaide SA", city: "adelaide",
    work_type: "contract", salary_label: null, listed_at: null, first_seen_at: new Date().toISOString(),
    url: "u", status: "new", notes: "", force_include: false, excluded: false, reasons: [], snippets: {},
    rule_score: 70, llm_score: null, llm_note: null, final_score: 70, matched_skills: [], flags: [],
    applicant_count: 11, applicant_volume: null, resume_pct: null, cover_letter_pct: null,
    insights_checked_at: null, ...over,
  }) as unknown as Job;

describe("APPS tag freshness", () => {
  it("marks counts older than 48h as possibly stale", () => {
    const old = new Date(Date.now() - 13 * 86_400_000).toISOString();
    render(<MemoryRouter><JobList jobs={[base({ insights_checked_at: old })]} view="active" selectedId={null} onSelect={() => {}} onArrowSelect={() => {}} /></MemoryRouter>);
    const tag = screen.getByTestId("apps-tag");
    expect(tag.textContent).toBe("11 APPS?");
    expect(tag.getAttribute("title")).toContain("13d ago");
  });
  it("shows fresh counts plainly", () => {
    const fresh = new Date(Date.now() - 2 * 3_600_000).toISOString();
    render(<MemoryRouter><JobList jobs={[base({ insights_checked_at: fresh })]} view="active" selectedId={null} onSelect={() => {}} onArrowSelect={() => {}} /></MemoryRouter>);
    expect(screen.getByTestId("apps-tag").textContent).toBe("11 APPS");
  });
});
