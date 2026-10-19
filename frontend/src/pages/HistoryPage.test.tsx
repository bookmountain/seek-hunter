import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PriorApplicationsBox, RecruiterQuickLog } from "@/components/history/JobHistoryBits";
import { JobList } from "@/components/JobList";
import { api } from "@/lib/api";
import type { Application, Contact, ContactDetail, Job } from "@/lib/types";
import { HistoryPage } from "./HistoryPage";

const now = new Date().toISOString();

const APP: Application = {
  id: 3,
  job_id: 12,
  company: "Robert Walters",
  company_key: "robert walters",
  title: "Full Stack (Java) Developer",
  url: null,
  location: "Adelaide SA",
  applied_at: now,
  tailoring_id: 4,
  stage: "applied",
  source: "seekhunter",
  notes: "",
  created_at: now,
  updated_at: now,
};

const CONTACT: Contact = {
  id: 9,
  name: "Brayden Mackay",
  company: "Robert Walters",
  company_key: "robert walters",
  role: "Recruiter",
  phone: "08 8216 3534",
  email: "brayden@rw.com",
  linkedin: null,
  notes: "",
  created_at: now,
  updated_at: now,
  last_interaction: null,
  interaction_count: 0,
  job_count: 1,
  application_count: 1,
};

function wrap(ui: ReactNode, url = "/history") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("HistoryPage", () => {
  beforeEach(() => {
    vi.spyOn(api, "applications").mockResolvedValue([APP]);
    vi.spyOn(api, "companies").mockResolvedValue([
      { company: "Robert Walters", company_key: "robert walters", application_count: 1, last_applied_at: now, applications: [{ id: 3, title: APP.title, applied_at: now, stage: "applied", tailoring_id: 4 }], contacts: [{ id: 9, name: "Brayden Mackay" }] },
    ]);
    vi.spyOn(api, "contacts").mockResolvedValue([CONTACT]);
    vi.spyOn(api, "contact").mockResolvedValue({ ...CONTACT, interactions: [], jobs: [], applications: [APP] } as ContactDetail);
    vi.spyOn(api, "history").mockResolvedValue([
      { at: now, type: "event", kind: "created", company: "Robert Walters", title: APP.title, contact_name: null, application_id: 3, contact_id: null, note: "", from_stage: null, to_stage: "applied" },
    ]);
  });
  afterEach(() => vi.restoreAllMocks());

  it("renders the four tabs and switches between them", async () => {
    wrap(<HistoryPage />);
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual(["Applications", "Contacts", "Companies", "Timeline"]);
    expect(await screen.findByRole("link", { name: APP.title })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Tailored #4" }).getAttribute("href")).toBe("/jobs/12/tailor?run=4");
    fireEvent.click(screen.getByRole("tab", { name: "Timeline" }));
    expect(await screen.findByText("Applied")).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "Companies" }));
    expect(await screen.findByRole("link", { name: "Brayden Mackay" })).toBeTruthy();
  });

  it("changing the stage sends a PATCH", async () => {
    const patch = vi.spyOn(api, "patchApplication").mockResolvedValue({ ...APP, stage: "interview" });
    wrap(<HistoryPage />);
    const select = await screen.findByRole("combobox", { name: /Stage for Full Stack/ });
    fireEvent.change(select, { target: { value: "interview" } });
    await waitFor(() => expect(patch).toHaveBeenCalledWith(3, { stage: "interview" }));
  });

  it("the manual add form POSTs an application with the optional contact", async () => {
    const create = vi.spyOn(api, "createApplication").mockResolvedValue({ ...APP, id: 4, job_id: null, source: "manual" });
    wrap(<HistoryPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Add application" }));
    const form = screen.getByRole("form", { name: "Add application" });
    fireEvent.change(within(form).getByLabelText("Company"), { target: { value: "Acme" } });
    fireEvent.change(within(form).getByLabelText("Role"), { target: { value: "Developer" } });
    fireEvent.change(within(form).getByLabelText("Applied on"), { target: { value: "2026-10-10" } });
    fireEvent.change(within(form).getByLabelText("Name"), { target: { value: "Jo Smith" } });
    fireEvent.submit(form);
    await waitFor(() =>
      expect(create).toHaveBeenCalledWith(
        expect.objectContaining({ company: "Acme", title: "Developer", applied_at: "2026-10-10T09:00:00", contact: expect.objectContaining({ name: "Jo Smith" }) }),
      ),
    );
  });

  it("quick log on an expanded contact POSTs an interaction", async () => {
    const create = vi.spyOn(api, "createInteraction").mockResolvedValue({ id: 1, contact_id: 9, application_id: null, kind: "call", at: now, note: "", created_at: now });
    wrap(<HistoryPage />, "/history?tab=contacts");
    fireEvent.click(await screen.findByRole("button", { name: "Brayden Mackay" }));
    const log = await screen.findByRole("group", { name: "Log an interaction" });
    fireEvent.click(within(log).getByRole("button", { name: "Called" }));
    await waitFor(() => expect(create).toHaveBeenCalledWith({ contact_id: 9, kind: "call", note: "" }));
    await waitFor(() => expect(within(log).getByRole("button", { name: "Called" }).getAttribute("aria-pressed")).toBe("true"));
  });
});

describe("job-side history bits", () => {
  afterEach(() => vi.restoreAllMocks());

  it("recruiter quick log POSTs to the job contact-log endpoint", async () => {
    vi.spyOn(api, "contacts").mockResolvedValue([]);
    const log = vi.spyOn(api, "jobContactLog").mockResolvedValue({ id: 1, contact_id: 9, application_id: null, kind: "email", at: now, note: "", created_at: now });
    wrap(<RecruiterQuickLog jobId={12} name="Brayden Mackay" company="Robert Walters" />);
    fireEvent.click(screen.getByRole("button", { name: "Emailed" }));
    await waitFor(() => expect(log).toHaveBeenCalledWith(12, "email"));
  });

  it("shows the prior-application warning box", () => {
    wrap(<PriorApplicationsBox company="Robert Walters" prior={[{ application_id: 3, title: "Full Stack (Java) Developer", applied_at: now, stage: "interview" }]} />);
    expect(screen.getByText("Robert Walters already has your resume")).toBeTruthy();
    expect(screen.getByText("Full Stack (Java) Developer")).toBeTruthy();
    expect(screen.getByText("Interview")).toBeTruthy();
  });

  it("tags list rows APPLIED or HAS RESUME", () => {
    const base = {
      source: "seek", location: "Adelaide SA", work_type: "contract", salary_label: null, listed_at: null, first_seen_at: now, url: "u",
      status: "new", notes: "", force_include: false, excluded: false, reasons: [], snippets: {}, rule_score: 60, llm_score: null,
      llm_note: null, final_score: 70, matched_skills: [], flags: [], contact_name: null, contact_phone: null, contact_email: null,
      contact_linkedin: null, contact_search: { linkedin: "x" }, applicant_count: null, applicant_volume: null, resume_pct: null,
      cover_letter_pct: null, insights_checked_at: null, application: null, prior_applications: [],
    } as const;
    const jobs = [
      { ...base, id: 1, title: "Dev A", company: "Robert Walters", prior_applications: [{ application_id: 3, title: "X", applied_at: now, stage: "applied" }] },
      { ...base, id: 2, title: "Dev B", company: "Acme", application: { id: 5, stage: "applied", applied_at: now, tailoring_id: null, notes: "" } },
    ] as unknown as Job[];
    wrap(<JobList jobs={jobs} view="active" selectedId={null} onSelect={() => {}} onArrowSelect={() => {}} />);
    expect(within(screen.getByRole("button", { name: /Dev A/ })).getByText("HAS RESUME")).toBeTruthy();
    expect(within(screen.getByRole("button", { name: /Dev B/ })).getByText("APPLIED")).toBeTruthy();
  });

  it("recruiter quick-log buttons are toggles: on when logged, off removes it", async () => {
    vi.spyOn(api, "contacts").mockResolvedValue([CONTACT]);
    vi.spyOn(api, "contact").mockResolvedValue({
      ...CONTACT,
      interactions: [{ id: 2, contact_id: 9, application_id: null, kind: "call", at: now, note: "", created_at: now }],
      jobs: [],
      applications: [],
    } as ContactDetail);
    vi.spyOn(api, "jobContactLog").mockResolvedValue({ id: 31, contact_id: 9, application_id: null, kind: "email", at: now, note: "", created_at: now });
    const del = vi.spyOn(api, "deleteInteraction").mockResolvedValue(undefined);
    wrap(<RecruiterQuickLog jobId={12} name="brayden mackay" company="ROBERT WALTERS" />);
    const called = () => screen.getByRole("button", { name: "Called" });
    const emailed = () => screen.getByRole("button", { name: "Emailed" });
    await waitFor(() => expect(called().getAttribute("aria-pressed")).toBe("true"));
    expect(emailed().getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(emailed());
    await waitFor(() => expect(emailed().getAttribute("aria-pressed")).toBe("true"));
    fireEvent.click(emailed());
    await waitFor(() => expect(del).toHaveBeenCalledWith(31));
    await waitFor(() => expect(emailed().getAttribute("aria-pressed")).toBe("false"));
    fireEvent.click(called());
    await waitFor(() => expect(del).toHaveBeenCalledWith(2));
    await waitFor(() => expect(called().getAttribute("aria-pressed")).toBe("false"));
  });
});

describe("contacts tab copy", () => {
  afterEach(() => vi.restoreAllMocks());

  it("explains what a contact is and links to Jobs when empty", async () => {
    vi.spyOn(api, "contacts").mockResolvedValue([]);
    vi.spyOn(api, "uiPrefs").mockResolvedValue({});
    wrap(<HistoryPage />, "/history?tab=contacts");
    const help = "People you've contacted or applied through. Log a call, email or LinkedIn invite from a job's Recruiter block to add someone.";
    await waitFor(() => expect(screen.getAllByText(help).length).toBe(2));
    expect(screen.getByRole("link", { name: "Go to Jobs" }).getAttribute("href")).toBe("/");
    expect(screen.getByRole("columnheader", { name: "Contacts · jobs · apps" })).toBeTruthy();
  });
});
