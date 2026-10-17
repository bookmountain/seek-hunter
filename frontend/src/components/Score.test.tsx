import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Score, scoreBand } from "./Score";

describe("Score", () => {
  it("renders high scores in the accent blue", () => {
    render(<Score score={82} />);
    const el = screen.getByText("82");
    expect(el.dataset.band).toBe("high");
    expect(el.className).toContain("text-blue");
  });

  it("uses ink for the middle band and faint ink for low scores", () => {
    render(<Score score={60} />);
    render(<Score score={30} />);
    expect(screen.getByText("60").className).toContain("text-ink");
    expect(screen.getByText("30").className).toContain("text-ink-low");
  });

  it("bands at 75 and 55", () => {
    expect([scoreBand(75), scoreBand(74), scoreBand(55), scoreBand(54)]).toEqual(["high", "mid", "mid", "low"]);
  });
});
