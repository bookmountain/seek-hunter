import { describe, expect, it } from "vitest";
import { highlight } from "./JobDetail";

describe("highlight", () => {
  it("turns plain emails into mailto links and leaves existing links alone", () => {
    const out = highlight('<p>Email jo.smith@acme.com.au or <a href="mailto:a@b.com">a@b.com</a></p>', []);
    expect(out).toContain('<a href="mailto:jo.smith@acme.com.au">jo.smith@acme.com.au</a>');
    expect(out.match(/<a /g)?.length).toBe(2);
  });

  it("explains masked Jora emails instead of linking them", () => {
    const out = highlight("<p>Apply now or email **************@talentweb.com.au</p>", []);
    expect(out).toContain('class="masked-email"');
    expect(out).not.toContain("mailto:");
  });

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
