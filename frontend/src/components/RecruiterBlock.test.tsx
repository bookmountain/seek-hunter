import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RecruiterBlock } from "./RecruiterBlock";

const base = {
  company: "Acme Recruitment",
  contact_name: "Jane Citizen",
  contact_phone: "08 8216 3534",
  contact_email: "jane@acme.com.au",
  contact_linkedin: null,
  contact_search: {
    linkedin: "https://www.linkedin.com/search/results/people/?keywords=Jane%20Citizen%20Acme",
    google: "https://www.google.com/search?q=site%3Alinkedin.com%2Fin+Jane+Citizen",
  },
};

describe("RecruiterBlock", () => {
  it("renders a tel: link with spaces stripped, mailto and the LinkedIn search", () => {
    render(<RecruiterBlock job={base} />);
    const tel = screen.getByRole("link", { name: "08 8216 3534" });
    expect(tel.getAttribute("href")).toBe("tel:0882163534");
    expect(screen.getByRole("link", { name: "jane@acme.com.au" }).getAttribute("href")).toBe("mailto:jane@acme.com.au");
    const search = screen.getByRole("link", { name: /Search LinkedIn/ });
    expect(search.getAttribute("href")).toBe(base.contact_search.linkedin);
    expect(search.getAttribute("target")).toBe("_blank");
    expect(search.getAttribute("rel")).toBe("noreferrer");
    expect(screen.getByRole("link", { name: /Search Google/ })).toBeTruthy();
    expect(screen.queryByRole("link", { name: /LinkedIn profile/ })).toBeNull();
  });

  it("renders the profile link with a caution note when contact_linkedin is set", () => {
    render(<RecruiterBlock job={{ ...base, contact_linkedin: "https://www.linkedin.com/in/jane-citizen" }} />);
    expect(screen.getByRole("link", { name: /LinkedIn profile/ }).getAttribute("href")).toBe(
      "https://www.linkedin.com/in/jane-citizen",
    );
    expect(screen.getByText(/likely match, check before inviting/)).toBeTruthy();
  });

  it("still shows the block and a search link when the ad has no contact", () => {
    render(
      <RecruiterBlock
        job={{
          ...base,
          contact_name: null,
          contact_phone: null,
          contact_email: null,
          contact_search: { linkedin: "https://www.linkedin.com/search/results/people/?keywords=Acme%20recruiter" },
        }}
      />,
    );
    expect(screen.getByText("No contact in the ad")).toBeTruthy();
    expect(screen.queryByRole("link", { name: /^tel:/ })).toBeNull();
    expect(screen.getByRole("link", { name: /Search LinkedIn/ })).toBeTruthy();
    expect(screen.queryByRole("link", { name: /Search Google/ })).toBeNull();
  });
});
