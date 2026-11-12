import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import type { AppSettings } from "@/lib/types";
import { SettingsPage } from "./SettingsPage";

const SETTINGS: AppSettings = {
  defence_employers: ["Existing Co"],
  bank_employers: [],
  employer_allowlist: [],
  clearance_patterns: [],
  citizenship_patterns: [],
  defence_keywords: [],
  bank_keywords: [],
  exclude_fintech: false,
  exclude_banks: false,
  fintech_keywords: [],
  role_boost_terms: [],
  role_penalty_terms: [],
  weights: { flexible_work: 35, full_time: 10, skill_max: 50, role_max: 15, skill_saturation: 8 },
  rule_blend: 0.6,
  llm_enabled: true,
  llm_providers: ["anthropic"],
  notify_enabled: true,
  recap_enabled: true,
  max_pages_per_search: 3,
  max_notify_per_run: 20,
  max_insights_per_run: 30,
  notify_cities: ["adelaide"],
  other_city_max_pages: 2,
  notifications_read_at: null,
};

function renderPage() {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <SettingsPage />
    </QueryClientProvider>,
  );
}

describe("SettingsPage list textareas", () => {
  afterEach(() => vi.restoreAllMocks());

  it("preserves spaces and newlines while typing (does not trim/filter per keystroke)", async () => {
    vi.spyOn(api, "settings").mockResolvedValue(SETTINGS);
    const { container } = renderPage();

    await waitFor(() => expect(container.querySelector("textarea")).toBeTruthy());
    const textarea = container.querySelector("textarea") as HTMLTextAreaElement;

    const typed = "Lockheed Martin\nX";
    let acc = "";
    for (const ch of typed) {
      acc += ch;
      fireEvent.change(textarea, { target: { value: acc } });
    }

    expect(textarea.value).toBe(typed);
  });

  it("toggling a notify city saves notify_cities with the full settings PUT", async () => {
    vi.spyOn(api, "settings").mockResolvedValue(SETTINGS);
    const save = vi.spyOn(api, "saveSettings").mockResolvedValue({ ...SETTINGS, notify_cities: ["adelaide", "melbourne"] });
    const { getByRole, getAllByRole, findByRole, getByText } = renderPage();
    const melb = await findByRole("checkbox", { name: "Melbourne" });
    expect((getByRole("checkbox", { name: "Adelaide" }) as HTMLInputElement).checked).toBe(true);
    fireEvent.click(melb);
    expect((melb as HTMLInputElement).checked).toBe(true);
    expect(getByText("Other cities still appear on the website and in the bell.")).toBeTruthy();
    fireEvent.click(getAllByRole("button", { name: "Save settings" })[0]);
    await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({ notify_cities: ["adelaide", "melbourne"], defence_employers: ["Existing Co"] })));
  });
});

describe("SettingsPage scoring", () => {
  afterEach(() => vi.restoreAllMocks());

  const input = (c: HTMLElement, id: string) => c.querySelector(`#${id}`) as HTMLInputElement;

  it("shows the parts as percentages of 100 and the work types relative to the work-type share", async () => {
    vi.spyOn(api, "settings").mockResolvedValue(SETTINGS);
    const { findByTestId, container, getAllByText } = renderPage();
    expect((await findByTestId("weights-total")).textContent).toBe("100%");
    expect(input(container, "part-work").value).toBe("35");
    expect(input(container, "part-skill").value).toBe("50");
    expect(input(container, "part-role").value).toBe("15");
    expect(input(container, "w-full_time").value).toBe("10");
    expect(getAllByText("of 35").length).toBe(2);
  });

  it("blocks saving when the parts don't add up to 100, and Balance fixes it", async () => {
    vi.spyOn(api, "settings").mockResolvedValue(SETTINGS);
    const save = vi.spyOn(api, "saveSettings").mockResolvedValue(SETTINGS);
    const { findByTestId, container, getAllByRole, getByRole } = renderPage();
    await findByTestId("weights-total");
    fireEvent.change(input(container, "part-skill"), { target: { value: "60" } });
    expect((await findByTestId("weights-total")).textContent).toBe("110%");
    expect(getByRole("alert").textContent).toContain("add up to 110%");
    const saveButtons = getAllByRole("button", { name: "Save settings" }) as HTMLButtonElement[];
    expect(saveButtons.every((b) => b.disabled)).toBe(true);

    fireEvent.click(getByRole("button", { name: "Balance to 100" }));
    expect((await findByTestId("weights-total")).textContent).toBe("100%");
    expect(saveButtons[0].disabled).toBe(false);
    fireEvent.click(saveButtons[0]);
    await waitFor(() => expect(save).toHaveBeenCalled());
    const w = save.mock.calls[0][0].weights;
    expect(Math.max(w.flexible_work, w.full_time) + w.skill_max + w.role_max).toBe(100);
  });

  it("scales both work types with the work-type share", async () => {
    vi.spyOn(api, "settings").mockResolvedValue(SETTINGS);
    const { findByTestId, container } = renderPage();
    await findByTestId("weights-total");
    fireEvent.change(input(container, "part-work"), { target: { value: "30" } });
    expect(input(container, "w-flexible_work").value).toBe("30");
    expect(input(container, "w-full_time").value).toBe("9");
  });

  it("saves the rules vs AI blend and offers a rescore afterwards", async () => {
    vi.spyOn(api, "settings").mockResolvedValueOnce(SETTINGS).mockResolvedValue({ ...SETTINGS, rule_blend: 0.75 });
    const save = vi.spyOn(api, "saveSettings").mockResolvedValue(SETTINGS);
    const rescore = vi.spyOn(api, "rescore").mockResolvedValue({ started: true });
    const { findByTestId, getByLabelText, getAllByRole, getByRole } = renderPage();
    expect((await findByTestId("blend-label")).textContent).toBe("60% rules / 40% AI");
    fireEvent.change(getByLabelText("Rules vs AI blend"), { target: { value: "75" } });
    expect((await findByTestId("blend-label")).textContent).toBe("75% rules / 25% AI");
    const rescoreButton = getByRole("button", { name: "Rescore last 7 days" }) as HTMLButtonElement;
    expect(rescoreButton.disabled).toBe(true); // unsaved changes
    fireEvent.click(getAllByRole("button", { name: "Save settings" })[0]);
    await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({ rule_blend: 0.75 })));
    await waitFor(() => expect(getByRole("status").textContent).toContain("still have their old scores"));
    await waitFor(() => expect(rescoreButton.disabled).toBe(false)); // saved settings came back
    fireEvent.click(rescoreButton);
    await waitFor(() => expect(rescore).toHaveBeenCalled());
  });

  it("saves crawl limits, falling back to defaults the server didn't send", async () => {
    vi.spyOn(api, "settings").mockResolvedValue(SETTINGS);
    const save = vi.spyOn(api, "saveSettings").mockResolvedValue(SETTINGS);
    const { findByLabelText, getAllByRole } = renderPage();
    const retries = (await findByLabelText("Detail retries")) as HTMLInputElement;
    expect(retries.value).toBe("15");
    fireEvent.change(retries, { target: { value: "5" } });
    fireEvent.click(getAllByRole("button", { name: "Save settings" })[0]);
    await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({ details_retry_per_run: 5, max_pages_per_search: 3 })));
  });
});
