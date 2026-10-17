import type {
  AppSettings,
  Job,
  JobDetail,
  JobStatus,
  ResumeCurrent,
  Run,
  SearchProfile,
  TailorStart,
  TailoringDetail,
  TailoringSummary,
} from "./types";

const TOKEN_KEY = "seekhunter.token";

export const getToken = () => localStorage.getItem(TOKEN_KEY) ?? "";
export const setToken = (t: string) => localStorage.setItem(TOKEN_KEY, t);

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/** Turns a thrown error into a readable message for toasts. */
export function errMsg(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 401) return "Set the write token first";
    try {
      const data = JSON.parse(e.message) as { detail?: unknown };
      if (Array.isArray(data.detail)) {
        return data.detail
          .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : String(d)))
          .join(", ");
      }
      if (typeof data.detail === "string") return data.detail;
    } catch {
      // not JSON; fall through to the raw response text below
    }
    return e.message;
  }
  return e instanceof Error ? e.message : String(e);
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  if (method !== "GET") headers.Authorization = `Bearer ${getToken()}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  if (!res.ok) throw new ApiError(res.status, await res.text());
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const qs = (params: Record<string, string | undefined>) => {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== "") as [string, string][];
  return entries.length ? `?${new URLSearchParams(entries).toString()}` : "";
};

export const api = {
  jobs: (p: { view?: string; status?: string; work_type?: string; source?: string; q?: string }) =>
    request<Job[]>("GET", `/api/jobs${qs(p)}`),
  job: (id: number) => request<JobDetail>("GET", `/api/jobs/${id}`),
  patchJob: (id: number, body: { status?: JobStatus; notes?: string }) =>
    request<Job>("PATCH", `/api/jobs/${id}`, body),
  unexclude: (id: number, allowlist_employer: boolean) =>
    request<Job>("POST", `/api/jobs/${id}/unexclude`, { allowlist_employer }),
  profiles: () => request<SearchProfile[]>("GET", "/api/search-profiles"),
  createProfile: (p: SearchProfile) => request<SearchProfile>("POST", "/api/search-profiles", p),
  updateProfile: (p: SearchProfile) => request<SearchProfile>("PUT", `/api/search-profiles/${p.id}`, p),
  deleteProfile: (id: number) => request<void>("DELETE", `/api/search-profiles/${id}`),
  settings: () => request<AppSettings>("GET", "/api/settings"),
  saveSettings: (s: AppSettings) => request<AppSettings>("PUT", "/api/settings", s),
  runs: () => request<Run[]>("GET", "/api/runs"),
  triggerRun: () => request<{ started: boolean }>("POST", "/api/runs"),
  notifyTest: () => request<{ sent: boolean }>("POST", "/api/notify/test"),
  tailor: (jobId: number, send = false) =>
    request<TailorStart>("POST", `/api/jobs/${jobId}/tailor?send=${send ? 1 : 0}`),
  tailorings: (jobId: number) => request<TailoringSummary[]>("GET", `/api/jobs/${jobId}/tailorings`),
  tailoring: (tid: number) => request<TailoringDetail>("GET", `/api/tailorings/${tid}`),
  resumeCurrent: () => request<ResumeCurrent>("GET", "/api/resume/current"),
  sendTailoring: (tid: number) =>
    request<{ sent: boolean; sent_at: string | null }>("POST", `/api/tailorings/${tid}/send`),
};
