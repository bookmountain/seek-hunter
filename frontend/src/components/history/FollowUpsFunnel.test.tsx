import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CallScript, scriptText } from "@/components/CallScript";
import { RecruiterBlock } from "@/components/RecruiterBlock";
import { api } from "@/lib/api";
import type { CallScript as Script, FollowUp, FunnelResult, FunnelRow } from "@/lib/types";
import { HistoryPage } from "@/pages/HistoryPage";
import { FollowUpsTab } from "./FollowUpsTab";
import { FunnelTab, pct } from "./FunnelTab";
import { RecruiterQuickLog } from "./JobHistoryBits";

const now = new Date().toISOString();

function wrap(ui: ReactNode, url = "/history") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

const NUDGE: FollowUp = {
  key: "application_nudge-3-20261105090000",
  kind: "application_nudge",
  days: 6,
  since: now,
  company: "Robert Walters",
  title: "Java Developer",
  channel: "email",
  message: "Hi Brayden,\n\nI applied for the Java Developer role on 5 November and wanted to follow up.\n\nThanks,\nBook Sam",
  subject: "Following up: Java Developer",
  hint: null,
  application_id: 3,
  job_id: 12,
  contact_id: 9,
  contact_name: "Brayden Mackay",
  contact_phone: "08 8216 3534",
  contact_email: "brayden@rw.com",
  contact_linkedin: null,
  link: "/?job=12",
};

const THANK: FollowUp = {
  ...NUDGE,
  key: "linkedin_thank-9-20261111090000",
  kind: "linkedin_thank",
  days: 0,
  channel: "linkedin",
  subject: null,
  message: "Hi Sam,\n\nThanks for connecting.",
  application_id: null,
  job_id: null,
  contact_name: "Sam Lee",
  contact_email: null,
  company: "Hays",
  title: "",
};

describe("FollowUpsTab", () => {
  afterEach(() => vi.restoreAllMocks());

  it("lists due items with the message, copy and mailto, and marks one sent with a note", async () => {
    vi.spyOn(api, "followUps").mockResolvedValue([THANK, NUDGE]);
    const done = vi.spyOn(api, "doneFollowUp").mockResolvedValue(undefined);
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    wrap(<FollowUpsTab />);
    expect(await screen.findByText("2 due")).toBeTruthy();
    const item = screen.getByRole("listitem", { name: "Nudge: Robert Walters · Java Developer" });
    expect(within(item).getByText("Quiet for 6d")).toBeTruthy();
    expect(within(item).getByText("Following up: Java Developer")).toBeTruthy();
    const mail = within(item).getByRole("link", { name: "Open email" }).getAttribute("href")!;
    expect(mail.startsWith("mailto:brayden@rw.com?subject=Following%20up%3A%20Java%20Developer&body=Hi%20Brayden")).toBe(true);
    fireEvent.click(within(item).getByRole("button", { name: /Copy message for Robert Walters/ }));
    expect(writeText).toHaveBeenCalledWith(NUDGE.message);
    fireEvent.change(within(item).getByLabelText("Note"), { target: { value: "sent via email" } });
    fireEvent.click(within(item).getByRole("button", { name: "Mark sent" }));
    await waitFor(() => expect(done).toHaveBeenCalledWith(NUDGE.key, "sent via email"));
    const thank = screen.getByRole("listitem", { name: "Say thanks: Hays" });
    expect(within(thank).getByText("Accepted your invite")).toBeTruthy();
    expect(within(thank).queryByRole("link", { name: "Open email" })).toBeNull();
  });

  it("snoozes and dismisses", async () => {
    vi.spyOn(api, "followUps").mockResolvedValue([NUDGE]);
    const snooze = vi.spyOn(api, "snoozeFollowUp").mockResolvedValue(undefined);
    const dismiss = vi.spyOn(api, "dismissFollowUp").mockResolvedValue(undefined);
    wrap(<FollowUpsTab />);
    fireEvent.click(await screen.findByRole("button", { name: "Snooze 7 days" }));
    await waitFor(() => expect(snooze).toHaveBeenCalledWith(NUDGE.key, 7));
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(dismiss).toHaveBeenCalledWith(NUDGE.key));
  });

  it("says so when nothing is due", async () => {
    vi.spyOn(api, "followUps").mockResolvedValue([]);
    wrap(<FollowUpsTab />);
    expect(await screen.findByText("Nothing to chase today.")).toBeTruthy();
  });

  it("shows the due count on the History tab and opens it from the URL", async () => {
    vi.spyOn(api, "followUps").mockResolvedValue([NUDGE]);
    vi.spyOn(api, "uiPrefs").mockResolvedValue({});
    wrap(<HistoryPage />, "/history?tab=followups");
    const tab = screen.getByRole("tab", { name: /Follow-ups/ });
    await waitFor(() => expect(tab.textContent).toBe("Follow-ups1"));
    expect(tab.getAttribute("aria-selected")).toBe("true");
    expect(await screen.findByRole("listitem", { name: /Nudge: Robert Walters/ })).toBeTruthy();
  });
});

const row = (label: string, applied: number, responded: number, interview: number, offer = 0): FunnelRow => ({
  label,
  applied,
  responded,
  interview,
  offer,
  response_rate: applied ? responded / applied : null,
  interview_rate: applied ? interview / applied : null,
});

const FUNNEL: FunnelResult = {
  total: row("all", 12, 6, 3, 1),
  by_source: [row("seek", 9, 5, 3, 1), row("radar", 3, 1, 0)],
  by_employer: [row("agency", 7, 4, 2), row("direct", 5, 2, 1, 1)],
  by_work_type: [row("contract", 8, 4, 2), row("full_time", 4, 2, 1, 1)],
  by_call: [row("called", 4, 3, 2), row("not called", 8, 3, 1, 1)],
};

describe("FunnelTab", () => {
  afterEach(() => vi.restoreAllMocks());
  beforeEach(() => vi.spyOn(api, "funnel").mockResolvedValue(FUNNEL));

  it("formats rates", () => {
    expect(pct(null)).toBe("—");
    expect(pct(2 / 3)).toBe("67%");
  });

  it("shows the stage strip and breakdown tables with n and low-n marking", async () => {
    wrap(<FunnelTab />);
    const strip = await screen.findByRole("group", { name: "Window" });
    expect(strip).toBeTruthy();
    const funnel = await screen.findByLabelText("Funnel");
    expect(within(funnel).getByText("12")).toBeTruthy();
    expect(within(funnel).getByText("50% of applied")).toBeTruthy();
    const source = screen.getByRole("table", { name: "By source" });
    const seek = within(source).getByRole("row", { name: /SEEK/ });
    expect(within(seek).getByText("n=9")).toBeTruthy();
    expect(within(seek).getByText("56%")).toBeTruthy();
    expect(within(seek).queryByText("low n")).toBeNull();
    const radar = within(source).getByRole("row", { name: /Company radar/ });
    expect(within(radar).getByText("low n")).toBeTruthy();
    const call = screen.getByRole("table", { name: "Called before applying" });
    expect(within(call).getByRole("row", { name: /Called the recruiter/ })).toBeTruthy();
    expect(within(call).getByRole("row", { name: /Didn't call/ })).toBeTruthy();
    expect(screen.getByRole("table", { name: "Agency or direct" })).toBeTruthy();
    expect(screen.getByRole("table", { name: "By work type" })).toBeTruthy();
  });

  it("refetches for a window", async () => {
    wrap(<FunnelTab />);
    fireEvent.click(await screen.findByRole("button", { name: "90 days" }));
    await waitFor(() => expect(api.funnel).toHaveBeenCalledWith(90));
  });

  it("warns when the whole sample is small", async () => {
    vi.spyOn(api, "funnel").mockResolvedValue({ ...FUNNEL, total: row("all", 3, 1, 0) });
    wrap(<FunnelTab />);
    expect(await screen.findByText(/n=3 so far: treat every rate below as a hint/)).toBeTruthy();
  });
});

const SCRIPT: Script = {
  job_id: 12,
  questions: ["How many hours a week?", "How firm is Kubernetes?", "Is this a direct brief?"],
  pitch: "Hi Brayden, it's Book Sam. I'm on a student visa until mid-2027.",
  source: "template",
  provider: null,
  warnings: [],
  cached: false,
  created_at: null,
  agency: true,
};

describe("CallScript", () => {
  afterEach(() => vi.restoreAllMocks());

  it("shows the template preview, then writes with AI", async () => {
    vi.spyOn(api, "callScript").mockResolvedValue(SCRIPT);
    const gen = vi.spyOn(api, "generateCallScript").mockResolvedValue({
      ...SCRIPT,
      source: "llm",
      provider: "openclaw",
      cached: true,
      created_at: now,
      questions: ["A?", "B?", "C?"],
      warnings: ["AI pitch adds 9; used the template pitch."],
    });
    wrap(<CallScript jobId={12} />);
    expect(await screen.findByText(SCRIPT.pitch)).toBeTruthy();
    expect(screen.getByText("Template · not saved")).toBeTruthy();
    const qs = screen.getByRole("list", { name: "Questions to ask" });
    expect(within(qs).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "01How many hours a week?",
      "02How firm is Kubernetes?",
      "03Is this a direct brief?",
    ]);
    fireEvent.click(screen.getByRole("button", { name: "Write with AI" }));
    await waitFor(() => expect(gen).toHaveBeenCalledWith(12, false));
    expect(await screen.findByText("A?")).toBeTruthy();
    expect(screen.getByText(/AI, checked against your resume/)).toBeTruthy();
    expect(screen.getByText("AI pitch adds 9; used the template pitch.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Rewrite" }));
    await waitFor(() => expect(gen).toHaveBeenCalledWith(12, true));
  });

  it("copies pitch and questions together", () => {
    expect(scriptText(SCRIPT)).toBe(
      "Hi Brayden, it's Book Sam. I'm on a student visa until mid-2027.\n\n1. How many hours a week?\n2. How firm is Kubernetes?\n3. Is this a direct brief?",
    );
  });
});

describe("recruiter call logging", () => {
  afterEach(() => vi.restoreAllMocks());

  it("logs a voicemail with the optional note in one tap", async () => {
    vi.spyOn(api, "contacts").mockResolvedValue([]);
    const log = vi.spyOn(api, "jobContactLog").mockResolvedValue({
      id: 5,
      contact_id: 9,
      application_id: null,
      kind: "voicemail",
      at: now,
      note: "call back Fri",
      created_at: now,
    });
    wrap(<RecruiterQuickLog jobId={12} name="Brayden Mackay" company="Robert Walters" />);
    fireEvent.change(screen.getByLabelText("Note"), { target: { value: "call back Fri" } });
    fireEvent.click(screen.getByRole("button", { name: "Left voicemail" }));
    await waitFor(() => expect(log).toHaveBeenCalledWith(12, "voicemail", "call back Fri"));
  });

  it("shows the call script under a recruiter with a phone", async () => {
    vi.spyOn(api, "callScript").mockResolvedValue(SCRIPT);
    vi.spyOn(api, "contacts").mockResolvedValue([]);
    wrap(
      <RecruiterBlock
        jobId={12}
        job={{
          company: "Robert Walters",
          contact_name: "Brayden Mackay",
          contact_phone: "08 8216 3534",
          contact_email: null,
          contact_linkedin: null,
          contact_search: { linkedin: "x" },
        }}
      />,
    );
    expect(await screen.findByText(SCRIPT.pitch)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Called" })).toBeTruthy();
  });
});
