import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, errMsg, getToken, setToken } from "./api";

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

describe("errMsg", () => {
  it("tells the user to set the write token on 401", () => {
    expect(errMsg(new ApiError(401, '{"detail":"write token required"}'))).toBe("Set the write token first");
    expect(errMsg(new ApiError(401, "unauthorized"))).toBe("Set the write token first");
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
