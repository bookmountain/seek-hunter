import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import type { NotificationsResult } from "@/lib/types";
import { NotificationBell } from "./NotificationBell";

const now = new Date().toISOString();
const DATA: NotificationsResult = {
  read_at: now,
  unread_count: 3,
  by_city: [
    { city: "adelaide", count: 1 },
    { city: "melbourne", count: 1 },
  ],
  items: [
    { type: "job", at: now, title: "React Developer", subtitle: "Acme", city: "melbourne", score: 82, job_id: 7, unread: true },
    { type: "tailoring", at: now, title: "Junior Dev", subtitle: "Tailoring done", job_id: 5, tailoring_id: 9, unread: true },
    { type: "follow_up", at: now, title: "Graduate Engineer", subtitle: "Atlassian", application_id: 3, unread: false },
  ],
};

function renderBell() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <p>outside</p>
        <NotificationBell />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("NotificationBell", () => {
  beforeEach(() => vi.spyOn(api, "notifications").mockResolvedValue(DATA));
  afterEach(() => vi.restoreAllMocks());

  it("shows the unread count badge", async () => {
    renderBell();
    expect((await screen.findByTestId("bell-badge")).textContent).toBe("3");
    expect(screen.getByRole("button", { name: "Notifications, 3 unread" }).getAttribute("aria-expanded")).toBe("false");
  });

  it("hides the badge when nothing is unread", async () => {
    vi.mocked(api.notifications).mockResolvedValue({ ...DATA, unread_count: 0 });
    renderBell();
    await screen.findByRole("button", { name: "Notifications" });
    await waitFor(() => expect(api.notifications).toHaveBeenCalled());
    expect(screen.queryByTestId("bell-badge")).toBeNull();
  });

  it("opens a panel with per-city counts and correctly linked items, and closes on Escape", async () => {
    renderBell();
    const button = await screen.findByRole("button", { name: /Notifications, 3 unread/ });
    fireEvent.click(button);
    expect(button.getAttribute("aria-expanded")).toBe("true");
    const panel = screen.getByRole("dialog", { name: "Notifications" });
    expect(within(panel).getByTestId("bell-cities").textContent).toBe("Adelaide 1 · Melbourne 1");
    expect(within(panel).getByRole("link", { name: /React Developer/ }).getAttribute("href")).toBe("/?job=7&city=melbourne");
    expect(within(panel).getByRole("link", { name: /Tailored resume ready — Junior Dev/ }).getAttribute("href")).toBe("/jobs/5/tailor?run=9");
    expect(within(panel).getByRole("link", { name: /Follow up: Graduate Engineer/ }).getAttribute("href")).toBe("/history?tab=applications");
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("closes when clicking outside", async () => {
    renderBell();
    fireEvent.click(await screen.findByRole("button", { name: /Notifications/ }));
    expect(screen.getByRole("dialog")).toBeTruthy();
    fireEvent.pointerDown(screen.getByText("outside"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("Mark all read POSTs and clears the badge", async () => {
    const mark = vi.spyOn(api, "markNotificationsRead").mockResolvedValue({ ...DATA, unread_count: 0, items: DATA.items.map((i) => ({ ...i, unread: false })) });
    renderBell();
    fireEvent.click(await screen.findByRole("button", { name: /Notifications, 3 unread/ }));
    fireEvent.click(screen.getByRole("button", { name: "Mark all read" }));
    await waitFor(() => expect(mark).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByTestId("bell-badge")).toBeNull());
  });
});
