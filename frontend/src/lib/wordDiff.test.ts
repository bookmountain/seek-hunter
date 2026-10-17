import { describe, expect, it } from "vitest";
import { wordDiff } from "./wordDiff";

const join = (ops: { op: string; text: string }[], keep: string[]) => ops.filter((o) => keep.includes(o.op)).map((o) => o.text).join("");

describe("wordDiff", () => {
  it("marks only the changed words", () => {
    const ops = wordDiff("Built web apps with React and Vue.", "Built web apps with React and TypeScript.");
    expect(ops).toEqual([
      { op: "equal", text: "Built web apps with React and " },
      { op: "delete", text: "Vue." },
      { op: "insert", text: "TypeScript." },
    ]);
  });

  it("round-trips: equal+delete rebuilds before, equal+insert rebuilds after", () => {
    const before = "Kept unit test coverage above 90% with Jest, improving release stability.";
    const after = "Maintained unit test coverage above 90% with Jest and React Testing Library.";
    const ops = wordDiff(before, after);
    expect(join(ops, ["equal", "delete"])).toBe(before);
    expect(join(ops, ["equal", "insert"])).toBe(after);
  });

  it("folds interleaved single-space equals into one phrase swap", () => {
    const ops = wordDiff("one two three four", "one TWO three FOUR");
    expect(ops.map((o) => o.op)).toEqual(["equal", "delete", "insert", "equal", "delete", "insert"]);
    const swap = wordDiff("a b c d", "a x y d");
    expect(swap).toEqual([
      { op: "equal", text: "a " },
      { op: "delete", text: "b c" },
      { op: "insert", text: "x y" },
      { op: "equal", text: " d" },
    ]);
  });

  it("handles identical and empty input", () => {
    expect(wordDiff("same", "same")).toEqual([{ op: "equal", text: "same" }]);
    expect(wordDiff("", "new text")).toEqual([{ op: "insert", text: "new text" }]);
  });
});
