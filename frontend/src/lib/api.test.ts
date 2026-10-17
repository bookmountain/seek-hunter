import { afterEach, describe, expect, it, vi } from "vitest";
import { api, getToken, setToken } from "./api";

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

  it("throws ApiError with status", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("nope", { status: 401 }));
    await expect(api.patchJob(1, { status: "saved" })).rejects.toMatchObject({ status: 401 });
  });
});
