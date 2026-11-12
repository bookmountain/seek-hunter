import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, errMsg, getToken, onUnauthorized, setToken } from "./api";

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe("api", () => {
  it("sends bearer token on writes and none on reads", async () => {
    setToken("abc");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
      new Response(JSON.stringify({ ok: true }), { status: 200, headers: { "content-type": "application/json" } }),
    );
    await api.jobs({ view: "active" });
    await api.patchJob(1, { status: "saved" });
    const [readUrl, readInit] = fetchMock.mock.calls[0];
    expect(String(readUrl)).toBe("/api/jobs?view=active");
    const readHeaders = (readInit?.headers ?? {}) as Record<string, string>;
    expect(readHeaders.Authorization).toBeUndefined();
    const [, writeInit] = fetchMock.mock.calls[1];
    const writeHeaders = (writeInit?.headers ?? {}) as Record<string, string>;
    expect(writeHeaders.Authorization).toBe("Bearer abc");
    expect(getToken()).toBe("abc");
  });

  it("sends cookies same-origin and no bearer header without a stored token", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response(null, { status: 204 }));
    await api.patchJob(1, { status: "saved" });
    const [, init] = fetchMock.mock.calls[0];
    expect(init?.credentials).toBe("same-origin");
    expect(((init?.headers ?? {}) as Record<string, string>).Authorization).toBeUndefined();
  });

  it("notifies listeners on 401, except for the login call itself", async () => {
    const listener = vi.fn();
    const off = onUnauthorized(listener);
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response("no", { status: 401 }));
    await expect(api.login("book", "bad")).rejects.toMatchObject({ status: 401 });
    expect(listener).not.toHaveBeenCalled();
    await expect(api.jobs({})).rejects.toMatchObject({ status: 401 });
    expect(listener).toHaveBeenCalledTimes(1);
    off();
    await expect(api.jobs({})).rejects.toMatchObject({ status: 401 });
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("throws ApiError with status", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("nope", { status: 401 }));
    await expect(api.patchJob(1, { status: "saved" })).rejects.toMatchObject({ status: 401 });
  });
});

describe("errMsg", () => {
  it("tells the user to sign in again on 401", () => {
    expect(errMsg(new ApiError(401, '{"detail":"authentication required"}'))).toBe("Not signed in. Sign in again");
    expect(errMsg(new ApiError(401, "unauthorized"))).toBe("Not signed in. Sign in again");
  });

  it("joins a 422 validation detail list into readable text", () => {
    const body = JSON.stringify({
      detail: [
        { loc: ["body", "keywords"], msg: "field required", type: "missing" },
        { loc: ["body", "location"], msg: "value is not a valid string", type: "type_error" },
      ],
    });
    expect(errMsg(new ApiError(422, body))).toBe("field required, value is not a valid string");
  });

  it("returns the JSON detail string for other ApiErrors", () => {
    expect(errMsg(new ApiError(403, '{"detail":"forbidden"}'))).toBe("forbidden");
  });

  it("passes a plain string body through unchanged", () => {
    expect(errMsg(new ApiError(500, "Internal Server Error"))).toBe("Internal Server Error");
  });

  it("falls back to e.message for non-ApiError errors", () => {
    expect(errMsg(new Error("boom"))).toBe("boom");
  });
});
