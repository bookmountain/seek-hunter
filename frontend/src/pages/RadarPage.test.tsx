import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import type { RadarCompany } from "@/lib/types";
import { RadarPage } from "./RadarPage";

const now = new Date().toISOString().replace("Z", "");

const COMPANIES: RadarCompany[] = [
  {
    id: 1, name: "Canva", company_key: "canva", ats: "greenhouse", ats_token: "canva", careers_url: "https://www.canva.com/careers",
    city: "sydney", enabled: true, source: "auto", last_checked_at: now, last_error: null, last_job_count: 12, created_at: now,
  },
  {
    id: 2, name: "Maptek", company_key: "maptek", ats: "other", ats_token: null, careers_url: null, city: "adelaide",
    enabled: false, source: "manual", last_checked_at: null, last_error: "no ATS found; add a careers URL", last_job_count: null,
    created_at: now,
  },
];

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <RadarPage />
    </QueryClientProvider>,
  );
}

describe("RadarPage", () => {
  afterEach(() => vi.restoreAllMocks());

  it("lists companies with ATS, board, jobs found and last error, plus a summary", async () => {
    vi.spyOn(api, "radarCompanies").mockResolvedValue(COMPANIES);
    const { findByText, getByLabelText, getByText } = renderPage();
    const canva = (await findByText("Canva")).closest("tr")!;
    expect(within(canva).getByText("Greenhouse")).toBeTruthy();
    expect(within(canva).getByText("canva.com", { exact: false })).toBeTruthy();
    expect(within(canva).getByText("12")).toBeTruthy();
    expect(within(canva).getByText("just now")).toBeTruthy();
    const maptek = getByText("Maptek").closest("tr")!;
    expect(within(maptek).getByText("no ATS found; add a careers URL")).toBeTruthy();
    expect(within(maptek).getByText("Never")).toBeTruthy();
    expect(within(maptek).queryByRole("button", { name: "Poll Maptek now" })).toBeNull(); // page watch, not polled
    const summary = getByLabelText("Radar summary");
    expect(within(summary).getByText("Companies").previousSibling?.textContent).toBe("2");
    expect(within(summary).getByText("Paused").previousSibling?.textContent).toBe("1");
  });

  it("pauses/resumes, polls, removes with confirmation, seeds and polls everything", async () => {
    vi.spyOn(api, "radarCompanies").mockResolvedValue(COMPANIES);
    const patch = vi.spyOn(api, "patchRadarCompany").mockResolvedValue({ ...COMPANIES[0], enabled: false });
    const check = vi.spyOn(api, "checkRadarCompany").mockResolvedValue({ started: true, company_id: 1 });
    const del = vi.spyOn(api, "deleteRadarCompany").mockResolvedValue({ deleted: true });
    const poll = vi.spyOn(api, "radarPoll").mockResolvedValue({ started: true });
    const seed = vi.spyOn(api, "radarSeed").mockResolvedValue({ started: true });
    const { findByRole, getByRole } = renderPage();

    fireEvent.click(await findByRole("switch", { name: "Pause Canva" }));
    await waitFor(() => expect(patch).toHaveBeenCalledWith(1, { enabled: false }));
    fireEvent.click(getByRole("button", { name: "Poll Canva now" }));
    await waitFor(() => expect(check).toHaveBeenCalledWith(1));

    fireEvent.click(getByRole("button", { name: "Remove Maptek" }));
    expect(del).not.toHaveBeenCalled();
    fireEvent.click(getByRole("button", { name: "Confirm removing Maptek" }));
    await waitFor(() => expect(del).toHaveBeenCalledWith(2));

    fireEvent.click(getByRole("button", { name: "Poll now" }));
    fireEvent.click(getByRole("button", { name: "Seed from recent employers" }));
    await waitFor(() => expect(poll).toHaveBeenCalled());
    await waitFor(() => expect(seed).toHaveBeenCalled());
  });

  it("filters to companies with errors", async () => {
    vi.spyOn(api, "radarCompanies").mockResolvedValue(COMPANIES);
    const { findByText, getByRole, queryByText } = renderPage();
    await findByText("Canva");
    fireEvent.click(getByRole("tab", { name: /Errors/ }));
    expect(queryByText("Canva")).toBeNull();
    expect(queryByText("Maptek")).toBeTruthy();
  });

  it("adds a company by careers URL (detect) or by ATS + slug", async () => {
    vi.spyOn(api, "radarCompanies").mockResolvedValue([]);
    const add = vi.spyOn(api, "addRadarCompany").mockResolvedValue(COMPANIES[0]);
    const { findByText, getByLabelText, getByRole } = renderPage();
    await findByText(/No companies on the radar yet/);

    const submit = getByRole("button", { name: "Add and detect" }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    fireEvent.change(getByLabelText("Company"), { target: { value: "Canva" } });
    fireEvent.change(getByLabelText("Careers page URL"), { target: { value: "https://www.canva.com/careers" } });
    fireEvent.click(submit);
    await waitFor(() =>
      expect(add).toHaveBeenCalledWith({ name: "Canva", careers_url: "https://www.canva.com/careers", city: null }),
    );

    fireEvent.click(getByRole("radio", { name: "I know the ATS" }));
    fireEvent.change(getByLabelText("Company"), { target: { value: "Immutable" } });
    fireEvent.change(getByLabelText("ATS"), { target: { value: "lever" } });
    const addButton = getByRole("button", { name: "Add company" }) as HTMLButtonElement;
    expect(addButton.disabled).toBe(true); // needs the slug
    fireEvent.change(getByLabelText("Board slug"), { target: { value: "immutable" } });
    fireEvent.change(getByLabelText("City"), { target: { value: "sydney" } });
    fireEvent.click(addButton);
    await waitFor(() =>
      expect(add).toHaveBeenLastCalledWith({ name: "Immutable", careers_url: null, city: "sydney", ats: "lever", ats_token: "immutable" }),
    );
  });
});
