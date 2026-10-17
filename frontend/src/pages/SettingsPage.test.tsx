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
  fintech_keywords: [],
  role_boost_terms: [],
  role_penalty_terms: [],
  weights: { flexible_work: 1, full_time: 1, skill_max: 1, role_max: 1, skill_saturation: 1 },
  llm_enabled: true,
  llm_providers: ["anthropic"],
  notify_enabled: true,
  recap_enabled: true,
  max_pages_per_search: 3,
  max_notify_per_run: 20,
  max_insights_per_run: 30,
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
});
