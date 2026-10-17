import { describe, expect, it } from "vitest";
import { highlight } from "./JobDrawer";

describe("highlight", () => {
  it("sanitizes script tags and event handler attributes", () => {
    const dirty = '<p onerror="alert(1)">Hello</p><script>alert(2)</script>';
    const clean = highlight(dirty, []);
    expect(clean).not.toContain("<script>");
    expect(clean).not.toContain("onerror");
    expect(clean).not.toContain("alert");
  });

  it("wraps matched skills in <mark> without breaking tags", () => {
    const html = '<p class="react">We use React and Python daily.</p>';
    const out = highlight(html, ["React", "Python"]);
    expect(out).toContain("<mark>React</mark>");
    expect(out).toContain("<mark>Python</mark>");
    // attribute content must not be mangled by the highlighter
    expect(out).toContain('class="react"');
    expect(out).not.toContain('<mark class="react">');
  });

  it("is case-insensitive and ignores partial-word matches", () => {
    const html = "<p>JavaScripting is not javascript.</p>";
    const out = highlight(html, ["javascript"]);
    expect(out).toContain("<mark>javascript</mark>");
    expect(out).not.toContain("<mark>JavaScript</mark>ing");
  });
});
