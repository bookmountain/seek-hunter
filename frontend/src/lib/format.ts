import type { Job, WorkType } from "./types";
import { parseIsoUtc } from "./utils";

/** Compact age, e.g. "5h", "3d". */
export function since(iso: string, now = Date.now()): string {
  const h = Math.max(0, Math.round((now - parseIsoUtc(iso).getTime()) / 3_600_000));
  return h < 24 ? `${h}h` : `${Math.round(h / 24)}d`;
}

export const FLEXIBLE_TYPES: ReadonlySet<WorkType> = new Set(["part_time", "contract", "casual"]);

export const isFlexible = (j: Pick<Job, "work_type">) => FLEXIBLE_TYPES.has(j.work_type);

export const WORK_TYPE_CAPS: Record<WorkType, string> = {
  full_time: "Full-time",
  part_time: "Part-time",
  contract: "Contract",
  casual: "Casual",
  unknown: "Not stated",
};

export const CITY_NAME: Record<string, string> = {
  adelaide: "Adelaide",
  melbourne: "Melbourne",
  sydney: "Sydney",
  perth: "Perth",
  brisbane: "Brisbane",
  other: "Other",
};

export const cityName = (c: string | null | undefined) => (c ? (CITY_NAME[c] ?? c) : "");

const SOURCE_NAME: Record<Job["source"], string> = {
  seek: "SEEK",
  jora: "Jora",
  linkedin: "LinkedIn",
  indeed: "Indeed",
  radar: "Employer site",
};

export const sourceName = (s: Job["source"]) => SOURCE_NAME[s] ?? s;

/** "45 min", "6 h", "3 days". */
export function span(ms: number): string {
  const m = Math.max(1, Math.round(ms / 60_000));
  if (m < 60) return `${m} min`;
  const h = Math.round(m / 60);
  if (h < 48) return `${h} h`;
  return `${Math.round(h / 24)} days`;
}

/** What the Company Radar contributed to this job, or null if it never saw it:
 *  - a radar-only job: "Found by radar on the employer's careers site"
 *  - a board job the radar saw first: "Seen on the employer's site 6 h before job boards"
 *  - otherwise: "Also on the employer's careers site" */
export function radarNote(j: Pick<Job, "source" | "first_seen_at" | "radar_first_seen_at">): string | null {
  if (!j.radar_first_seen_at) return null;
  if (j.source === "radar") return "Found by radar on the employer's careers site";
  const lead = parseIsoUtc(j.first_seen_at).getTime() - parseIsoUtc(j.radar_first_seen_at).getTime();
  if (lead >= 60_000) return `Seen on the employer's site ${span(lead)} before job boards`;
  return "Also on the employer's careers site";
}

/** Relative age for status lines, e.g. "just now", "12m ago", "2h ago", "3d ago". */
export function ago(iso: string, now = Date.now()): string {
  const m = Math.max(0, Math.round((now - parseIsoUtc(iso).getTime()) / 60_000));
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  return h < 24 ? `${h}h ago` : `${Math.round(h / 24)}d ago`;
}

/** Adelaide wall-clock time, e.g. "17 Oct, 14:02". */
export function adelaideTime(iso: string): string {
  return parseIsoUtc(iso).toLocaleString("en-AU", {
    timeZone: "Australia/Adelaide",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}
