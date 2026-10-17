import type {
  AppSettings,
  TailoringListItem,
  CityCount,
  NotificationsResult,
  Application,
  ApplicationCreate,
  ApplicationStage,
  CompanyHistory,
  Contact,
  ContactDetail,
  ContactIn,
  HistoryEvent,
  Interaction,
  InteractionKind,
  CityOverview,
  CompareResult,
  RoleFamilyRow,
  SkillGap,
  SkillShare,
  TrendsResult,
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
  meta: () => request<{ write_requires_token: boolean }>("GET", "/api/meta"),
  jobs: (p: { view?: string; status?: string; work_type?: string; source?: string; q?: string; city?: string }) =>
    request<Job[]>("GET", `/api/jobs${qs(p)}`),
  jobCities: (view = "active") => request<CityCount[]>("GET", `/api/jobs/cities${qs({ view })}`),
  notifications: (limit = 20) => request<NotificationsResult>("GET", `/api/notifications${qs({ limit: String(limit) })}`),
  markNotificationsRead: (limit = 20) =>
    request<NotificationsResult>("POST", `/api/notifications/read${qs({ limit: String(limit) })}`),
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
  allTailorings: (q?: string, limit = 100) =>
    request<TailoringListItem[]>("GET", `/api/tailorings${qs({ limit: String(limit), q })}`),
  tailoring: (tid: number) => request<TailoringDetail>("GET", `/api/tailorings/${tid}`),
  resumeCurrent: () => request<ResumeCurrent>("GET", "/api/resume/current"),
  insightsOverview: (days = 14) => request<CityOverview[]>("GET", `/api/insights/overview${qs({ days: String(days) })}`),
  insightsSkills: (city: string, roleFamily?: string, days = 14) =>
    request<SkillShare[]>("GET", `/api/insights/skills${qs({ city, days: String(days), role_family: roleFamily })}`),
  insightsCompare: (skills: string[], days = 14) =>
    request<CompareResult>("GET", `/api/insights/compare${qs({ skills: skills.join(","), days: String(days) })}`),
  insightsGaps: (city: string, days = 14) =>
    request<SkillGap[]>("GET", `/api/insights/gaps${qs({ city, days: String(days) })}`),
  insightsTrends: (city: string, skills: string[], weeks = 8) =>
    request<TrendsResult>("GET", `/api/insights/trends${qs({ city, skills: skills.join(","), weeks: String(weeks) })}`),
  insightsRoles: (city: string, days = 14) =>
    request<RoleFamilyRow[]>("GET", `/api/insights/roles${qs({ city, days: String(days) })}`),
  applications: (p: { stage?: string; q?: string } = {}) => request<Application[]>("GET", `/api/applications${qs(p)}`),
  createApplication: (body: ApplicationCreate) => request<Application>("POST", "/api/applications", body),
  patchApplication: (id: number, body: { stage?: ApplicationStage; notes?: string; applied_at?: string; tailoring_id?: number | null }) =>
    request<Application>("PATCH", `/api/applications/${id}`, body),
  deleteApplication: (id: number) => request<void>("DELETE", `/api/applications/${id}`),
  contacts: (q?: string) => request<Contact[]>("GET", `/api/contacts${qs({ q })}`),
  contact: (id: number) => request<ContactDetail>("GET", `/api/contacts/${id}`),
  createContact: (body: ContactIn & { company?: string; notes?: string }) => request<Contact>("POST", "/api/contacts", body),
  patchContact: (id: number, body: Partial<ContactIn & { company: string; notes: string }>) =>
    request<Contact>("PATCH", `/api/contacts/${id}`, body),
  createInteraction: (body: { contact_id?: number; application_id?: number; kind: InteractionKind; at?: string; note?: string }) =>
    request<Interaction>("POST", "/api/interactions", body),
  deleteInteraction: (id: number) => request<void>("DELETE", `/api/interactions/${id}`),
  jobContactLog: (jobId: number, kind: InteractionKind, note = "") =>
    request<Interaction>("POST", `/api/jobs/${jobId}/contact-log`, { kind, note }),
  companies: (q?: string) => request<CompanyHistory[]>("GET", `/api/companies${qs({ q })}`),
  history: (limit = 100) => request<HistoryEvent[]>("GET", `/api/history${qs({ limit: String(limit) })}`),
  sendTailoring: (tid: number) =>
    request<{ sent: boolean; sent_at: string | null }>("POST", `/api/tailorings/${tid}/send`),
};
