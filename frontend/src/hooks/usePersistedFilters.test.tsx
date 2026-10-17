import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import { usePersistedFilters } from "./usePersistedFilters";

const DEFAULTS = { q: "", city: "", status: "" };

function Probe() {
  const f = usePersistedFilters("jobs", DEFAULTS);
  const loc = useLocation();
  return (
    <div>
      <output data-testid="search">{loc.search}</output>
      <output data-testid="ready">{String(f.ready)}</output>
      <button type="button" onClick={() => f.set({ city: "sydney" })}>
        sydney
      </button>
      <button type="button" onClick={f.reset}>
        reset
      </button>
    </div>
  );
}

function renderAt(url: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <Probe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("usePersistedFilters", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("applies saved prefs when the URL has no filter params, keeping other params", async () => {
    vi.spyOn(api, "uiPrefs").mockResolvedValue({ jobs: { city: "melbourne", status: "saved" } });
    const put = vi.spyOn(api, "putUiPrefs").mockResolvedValue({});
    renderAt("/?job=5");
    await waitFor(() => expect(screen.getByTestId("ready").textContent).toBe("true"));
    const params = new URLSearchParams(screen.getByTestId("search").textContent!);
    expect(params.get("city")).toBe("melbourne");
    expect(params.get("status")).toBe("saved");
    expect(params.get("job")).toBe("5");
    await new Promise((r) => setTimeout(r, 600));
    expect(put).not.toHaveBeenCalled(); // applying what's saved isn't a change
  });

  it("URL params win over saved prefs", async () => {
    const prefs = vi.spyOn(api, "uiPrefs").mockResolvedValue({ jobs: { city: "melbourne" } });
    renderAt("/?city=perth");
    expect(screen.getByTestId("ready").textContent).toBe("true");
    await new Promise((r) => setTimeout(r, 50));
    expect(new URLSearchParams(screen.getByTestId("search").textContent!).get("city")).toBe("perth");
    expect(prefs).not.toHaveBeenCalled();
  });

  it("debounces a PUT after a change, and reset clears and saves defaults", async () => {
    vi.spyOn(api, "uiPrefs").mockResolvedValue({});
    const put = vi.spyOn(api, "putUiPrefs").mockResolvedValue({});
    renderAt("/");
    await waitFor(() => expect(screen.getByTestId("ready").textContent).toBe("true"));
    vi.useFakeTimers();
    fireEvent.click(screen.getByText("sydney"));
    act(() => vi.advanceTimersByTime(300));
    expect(put).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(300));
    expect(put).toHaveBeenCalledWith("jobs", { q: "", city: "sydney", status: "" });

    fireEvent.click(screen.getByText("reset"));
    expect(screen.getByTestId("search").textContent).toBe("");
    expect(put).toHaveBeenLastCalledWith("jobs", DEFAULTS);
    act(() => vi.advanceTimersByTime(1000));
    expect(put).toHaveBeenCalledTimes(2); // no duplicate save after reset
  });
});
