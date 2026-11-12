import { describe, expect, it } from "vitest";
import { radarNote, span } from "./format";
import { DEFAULT_WEIGHTS, balance, blendLabel, splitTotal, weightProblems, withWorkMax } from "./scoring";

describe("scoring weights", () => {
  it("balances any split to exactly 100 keeping proportions", () => {
    expect(balance({ work: 35, skill: 60, role: 15 })).toEqual({ work: 32, skill: 54, role: 14 });
    expect(splitTotal(balance({ work: 1, skill: 1, role: 1 }))).toBe(100);
    expect(balance({ work: 0, skill: 0, role: 0 })).toEqual({ work: 35, skill: 50, role: 15 });
  });

  it("scales both work types with the work-type share", () => {
    expect(withWorkMax(DEFAULT_WEIGHTS, 35, 70)).toMatchObject({ flexible_work: 70, full_time: 20 });
    expect(withWorkMax(DEFAULT_WEIGHTS, 35, 30)).toMatchObject({ flexible_work: 30, full_time: 9 });
    expect(withWorkMax({ ...DEFAULT_WEIGHTS, flexible_work: 0, full_time: 0 }, 0, 20)).toMatchObject({ flexible_work: 20, full_time: 20 });
  });

  it("explains what stops weights from being saved", () => {
    expect(weightProblems(DEFAULT_WEIGHTS, 35)).toEqual([]);
    expect(weightProblems({ ...DEFAULT_WEIGHTS, role_max: 25 }, 35)[0]).toContain("add up to 110%");
    expect(weightProblems({ ...DEFAULT_WEIGHTS, flexible_work: 30 }, 35).join(" ")).toContain("Neither work type earns the full 35");
    expect(weightProblems({ ...DEFAULT_WEIGHTS, skill_saturation: 0 }, 35)).toContain("Full skill marks need at least 1 matched skill.");
  });

  it("labels the blend", () => {
    expect(blendLabel(0.6)).toBe("60% rules / 40% AI");
    expect(blendLabel(1)).toBe("100% rules / 0% AI");
  });
});

describe("radarNote", () => {
  const base = { source: "seek" as const, first_seen_at: "2026-11-12T12:00:00" };

  it("is null when the radar never saw the job", () => {
    expect(radarNote({ ...base, radar_first_seen_at: null })).toBeNull();
    expect(radarNote(base)).toBeNull();
  });

  it("shows the radar's head start over the boards", () => {
    expect(radarNote({ ...base, radar_first_seen_at: "2026-11-12T06:00:00" })).toBe("Seen on the employer's site 6 h before job boards");
    expect(radarNote({ ...base, radar_first_seen_at: "2026-11-12T11:20:00" })).toBe("Seen on the employer's site 40 min before job boards");
  });

  it("says found by radar for radar-only jobs, and 'also' when there was no head start", () => {
    expect(radarNote({ source: "radar", first_seen_at: base.first_seen_at, radar_first_seen_at: base.first_seen_at })).toBe(
      "Found by radar on the employer's careers site",
    );
    expect(radarNote({ ...base, radar_first_seen_at: base.first_seen_at })).toBe("Also on the employer's careers site");
  });

  it("formats spans", () => {
    expect(span(30 * 60_000)).toBe("30 min");
    expect(span(3 * 86_400_000)).toBe("3 days");
  });
});
