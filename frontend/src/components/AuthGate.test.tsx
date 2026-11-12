import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, type AuthMe } from "@/lib/api";
import { AuthGate, SignOutButton } from "./AuthGate";

const ANON: AuthMe = { authenticated: false, username: null, login_required: true };
const IN: AuthMe = { authenticated: true, username: "book", login_required: true };
const LAN: AuthMe = { authenticated: false, username: null, login_required: false };

function renderGate() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AuthGate>
        <SignOutButton />
        <p>app content</p>
      </AuthGate>
    </QueryClientProvider>,
  );
}

function signIn(user = "book", pass = "pw") {
  fireEvent.change(screen.getByLabelText("Username"), { target: { value: user } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: pass } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

afterEach(() => vi.restoreAllMocks());

describe("AuthGate", () => {
  it("shows the login screen when login is required", async () => {
    vi.spyOn(api, "me").mockResolvedValue(ANON);
    renderGate();
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeTruthy();
    expect(screen.getByText("SeekHunter")).toBeTruthy();
    expect(screen.queryByText("app content")).toBeNull();
  });

  it("renders the app directly on the LAN, without a sign-out link", async () => {
    vi.spyOn(api, "me").mockResolvedValue(LAN);
    renderGate();
    expect(await screen.findByText("app content")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Sign out" })).toBeNull();
  });

  it("proceeds to the app after a successful login", async () => {
    const me = vi.spyOn(api, "me").mockResolvedValueOnce(ANON).mockResolvedValue(IN);
    const login = vi.spyOn(api, "login").mockResolvedValue(undefined);
    renderGate();
    await screen.findByRole("button", { name: "Sign in" });
    signIn("book", "secret");
    expect(await screen.findByText("app content")).toBeTruthy();
    expect(login).toHaveBeenCalledWith("book", "secret");
    expect(me).toHaveBeenCalledTimes(2);
  });

  it("shows a generic error on wrong credentials and a wait message on 429", async () => {
    vi.spyOn(api, "me").mockResolvedValue(ANON);
    const login = vi.spyOn(api, "login").mockRejectedValueOnce(new ApiError(401, "{}"));
    renderGate();
    await screen.findByRole("button", { name: "Sign in" });
    signIn();
    expect((await screen.findByRole("alert")).textContent).toContain("Wrong username or password.");
    login.mockRejectedValueOnce(new ApiError(429, "{}"));
    signIn();
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("Too many attempts"));
  });

  it("returns to the login screen when an API call gets a 401", async () => {
    vi.spyOn(api, "me").mockResolvedValueOnce(IN).mockResolvedValue(ANON);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("no", { status: 401 }));
    renderGate();
    await screen.findByText("app content");
    await expect(api.jobs({})).rejects.toBeInstanceOf(ApiError);
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeTruthy();
    expect(screen.queryByText("app content")).toBeNull();
  });

  it("signs out from the navbar link", async () => {
    vi.spyOn(api, "me").mockResolvedValue(IN);
    const logout = vi.spyOn(api, "logout").mockResolvedValue(undefined);
    renderGate();
    fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeTruthy();
    expect(logout).toHaveBeenCalled();
    expect(screen.queryByText("app content")).toBeNull();
  });
});
