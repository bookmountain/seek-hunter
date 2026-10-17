import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CompetitionBlock } from "./CompetitionBlock";

const base = {
  source: "seek" as const,
  applicant_count: 77,
  applicant_volume: "Medium application volume",
  resume_pct: 100,
  cover_letter_pct: 57,
  insights_checked_at: new Date(Date.now() - 2 * 3_600_000).toISOString(),
};

describe("CompetitionBlock", () => {
  it("renders the applicant count, volume label and both percentages", () => {
    render(<CompetitionBlock job={base} />);
    expect(screen.getByText("77")).toBeTruthy();
    expect(screen.getByText("applicants")).toBeTruthy();
    expect(screen.getByText("Medium application volume")).toBeTruthy();
    expect(screen.getByText("100%")).toBeTruthy();
    expect(screen.getByText("57%")).toBeTruthy();
    expect(screen.getByText("Resume")).toBeTruthy();
    expect(screen.getByText("Cover letter")).toBeTruthy();
    expect(screen.getByText(/checked 2h ago/)).toBeTruthy();
  });

  it("notes the share of applicants who skipped the cover letter", () => {
    render(<CompetitionBlock job={base} />);
    expect(screen.getByText("43% of applicants skipped the cover letter")).toBeTruthy();
  });

  it("shows a Jora-specific fallback when there is no applicant count", () => {
    render(<CompetitionBlock job={{ ...base, source: "jora", applicant_count: null, applicant_volume: null,
      resume_pct: null, cover_letter_pct: null, insights_checked_at: null }} />);
    expect(screen.getByText("SEEK only — not available for Jora ads")).toBeTruthy();
    expect(screen.queryByText("applicants")).toBeNull();
  });

  it("shows a SEEK-specific fallback when SEEK has no insights for this ad yet", () => {
    render(<CompetitionBlock job={{ ...base, source: "seek", applicant_count: null, applicant_volume: null,
      resume_pct: null, cover_letter_pct: null, insights_checked_at: null }} />);
    expect(screen.getByText("SEEK hasn't published applicant numbers for this ad")).toBeTruthy();
  });

  it("omits the bars section entirely when only the count is known", () => {
    render(<CompetitionBlock job={{ ...base, resume_pct: null, cover_letter_pct: null }} />);
    expect(screen.getByText("77")).toBeTruthy();
    expect(screen.queryByText("Resume")).toBeNull();
    expect(screen.queryByText(/skipped the cover letter/)).toBeNull();
  });
});
