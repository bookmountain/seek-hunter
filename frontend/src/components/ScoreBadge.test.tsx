import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ScoreBadge } from "./ScoreBadge";

describe("ScoreBadge", () => {
  it("shows score with tone class", () => {
    render(<ScoreBadge score={82} />);
    const el = screen.getByText("82");
    expect(el.className).toContain("bg-emerald");
  });
  it("uses muted tone for low scores", () => {
    render(<ScoreBadge score={30} />);
    expect(screen.getByText("30").className).toContain("bg-muted");
  });
});
